"""
Gestion d'état persistante pour la pipeline TTS.

Combine :
- SQLite local (tts_pipeline_state.db) : journal des jobs et segments
- Azure Blob Storage : stockage persistant des segments audio

Permet à pipeline_tts_v2.py d'être reprise après un crash ou manque de crédit
API, sans refaire les appels TTS déjà réussis.
"""

import os
import sqlite3
from datetime import datetime
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv("backend/.env")

# ─── Config ──────────────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), "tts_pipeline_state.db")
AZURE_CONN_STR = os.getenv("AZURE_AUDIO_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER = os.getenv("AZURE_BACKUP_CONTAINER", "pipelinebackup")


# ─── SQLite ──────────────────────────────────────────────────────────────────

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crée les tables si absentes."""
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS tts_jobs (
                job_id TEXT PRIMARY KEY,
                source_file TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                total_paragraphs INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                updated_at TEXT,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS tts_segments (
                job_id TEXT NOT NULL,
                paragraph_idx INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                azure_path TEXT,
                duration_ms INTEGER,
                updated_at TEXT,
                PRIMARY KEY (job_id, paragraph_idx)
            );

            CREATE INDEX IF NOT EXISTS idx_segments_job
                ON tts_segments(job_id, status);
        """)


def create_or_resume_job(job_id, source_file, output_dir, total_paragraphs):
    """
    Crée le job en BDD ou reprend l'existant.
    Retourne le set des paragraph_idx déjà terminés (statut 'done').
    """
    init_db()
    now = datetime.now().isoformat()

    with _conn() as c:
        existing = c.execute(
            "SELECT job_id, total_paragraphs FROM tts_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()

        if existing:
            c.execute(
                """UPDATE tts_jobs
                   SET status = 'running', updated_at = ?, error_message = NULL
                   WHERE job_id = ?""",
                (now, job_id),
            )
            print(f"  ♻️ Job '{job_id}' repris")
        else:
            c.execute(
                """INSERT INTO tts_jobs
                   (job_id, source_file, output_dir, total_paragraphs,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'running', ?, ?)""",
                (job_id, source_file, output_dir, total_paragraphs, now, now),
            )
            print(f"  ✨ Nouveau job '{job_id}' créé")

        done_rows = c.execute(
            """SELECT paragraph_idx FROM tts_segments
               WHERE job_id = ? AND status = 'done'""",
            (job_id,),
        ).fetchall()

    done_set = {row["paragraph_idx"] for row in done_rows}
    print(f"  📊 {len(done_set)}/{total_paragraphs} segments déjà en cache Azure")
    return done_set


def mark_segment_done(job_id, idx, azure_path, duration_ms):
    """Enregistre un segment comme terminé en BDD."""
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO tts_segments
               (job_id, paragraph_idx, status, azure_path, duration_ms, updated_at)
               VALUES (?, ?, 'done', ?, ?, ?)""",
            (job_id, idx, azure_path, duration_ms, now),
        )


def mark_segment_failed(job_id, idx):
    """Marque un segment comme échoué."""
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO tts_segments
               (job_id, paragraph_idx, status, updated_at)
               VALUES (?, ?, 'failed', ?)""",
            (job_id, idx, now),
        )


def get_segment_azure_path(job_id, idx):
    """Retourne le chemin Azure d'un segment déjà terminé, ou None."""
    with _conn() as c:
        row = c.execute(
            """SELECT azure_path FROM tts_segments
               WHERE job_id = ? AND paragraph_idx = ? AND status = 'done'""",
            (job_id, idx),
        ).fetchone()
    return row["azure_path"] if row else None


def mark_job_completed(job_id):
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE tts_jobs SET status = 'completed', updated_at = ? WHERE job_id = ?",
            (now, job_id),
        )


def mark_job_failed(job_id, error):
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute(
            """UPDATE tts_jobs
               SET status = 'failed', updated_at = ?, error_message = ?
               WHERE job_id = ?""",
            (now, str(error), job_id),
        )


# ─── Azure Blob ──────────────────────────────────────────────────────────────

_blob_client = None


def _get_client():
    global _blob_client
    if _blob_client is None:
        if not AZURE_CONN_STR:
            raise ValueError(
                "AZURE_AUDIO_STORAGE_CONNECTION_STRING manquante dans backend/.env"
            )
        _blob_client = BlobServiceClient.from_connection_string(AZURE_CONN_STR)
        # S'assurer que le container existe
        try:
            _blob_client.create_container(AZURE_CONTAINER)
            print(f"  ✨ Container Azure '{AZURE_CONTAINER}' créé")
        except Exception:
            pass  # Container existe déjà
    return _blob_client


def azure_upload_segment(job_id, idx, audio_bytes):
    """
    Upload un segment MP3 vers Azure Blob.
    Retourne le chemin blob (ex: 'jour1/segments/seg_0123.mp3').
    """
    client = _get_client()
    blob_path = f"{job_id}/segments/seg_{idx:04d}.mp3"
    blob = client.get_blob_client(container=AZURE_CONTAINER, blob=blob_path)
    blob.upload_blob(audio_bytes, overwrite=True)
    return blob_path


def azure_download_segment(blob_path):
    """Télécharge un segment depuis Azure et retourne les bytes."""
    client = _get_client()
    blob = client.get_blob_client(container=AZURE_CONTAINER, blob=blob_path)
    return blob.download_blob().readall()


def azure_upload_final(job_id, filename, audio_bytes):
    """
    Upload un MP3 final (un des 7 blocs cours) vers Azure.
    Retourne l'URL complète.
    """
    client = _get_client()
    blob_path = f"{job_id}/final/{filename}"
    blob = client.get_blob_client(container=AZURE_CONTAINER, blob=blob_path)
    blob.upload_blob(audio_bytes, overwrite=True)
    return blob.url
