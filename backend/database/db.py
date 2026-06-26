# db.py - Gestion de la base de données
import os
import shutil
import sqlite3
from datetime import datetime
from config import DB_PATH, FRANCE_TZ
from utils.logger import get_logger

logger = get_logger(__name__)


def get_db_connection():
    """Retourne une connexion à la base de données SQLite.

    timeout=30 : en cas d'écriture concurrente (pipelines parallèles), la
    connexion attend jusqu'à 30s que le verrou se libère au lieu de lever
    immédiatement "database is locked". Le journal_mode WAL (activé au boot
    par db_safety.startup_check, persistant) permet lecteurs + 1 écrivain
    simultanés et réduit fortement le risque de corruption.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    # NORMAL n'est sûr qu'avec WAL (jamais activé sur Azure : /home est un
    # partage réseau, cf. db_safety.enable_wal). En mode rollback journal on
    # garde le FULL par défaut, plus lent mais sans risque de corruption.
    if not os.getenv("WEBSITE_SITE_NAME"):
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _is_malformed_database_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "database disk image is malformed" in message
        or "file is not a database" in message
    )


def _quarantine_corrupt_database(db_path: str) -> str:
    timestamp = datetime.now(FRANCE_TZ).strftime("%Y%m%d-%H%M%S")
    backup_path = f"{db_path}.corrupt-{timestamp}"

    for path in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
        if not os.path.exists(path):
            continue
        suffix = path[len(db_path):]
        target = f"{backup_path}{suffix}"
        try:
            os.replace(path, target)
        except OSError:
            shutil.copy2(path, target)
            os.remove(path)
        logger.error("🧯 Base SQLite corrompue mise de côté: %s -> %s", path, target)

    return backup_path


def init_database(_recovered_from_corruption: bool = False):
    """Initialise la base de données avec les tables nécessaires"""
    logger.info("🗄️ Initialisation de la base de données...")
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        logger.info("✅ Connexion à la base de données réussie")

        # Table des logs existante
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT,
            prenom TEXT,
            arrivee TEXT,
            depart TEXT
        )
        """
        )
        logger.info("✅ Table logs créée/vérifiée")

        # Table pour suivre les visites de /video
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS video_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_id INTEGER,
                timestamp TEXT
            )
            """
        )
        logger.info("✅ Table video_visits créée/vérifiée")

        # Table pour stocker l'heure de début du cours
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cours_config (
                id INTEGER PRIMARY KEY,
                heure_debut TEXT NOT NULL
            )
            """
        )
        logger.info("✅ Table cours_config créée/vérifiée")

        # Insérer une heure par défaut si la table est vide
        cursor.execute("SELECT COUNT(*) FROM cours_config")
        count = cursor.fetchone()[0]
        logger.info(f"📊 Nombre d'entrées dans cours_config: {count}")

        if count == 0:
            # Heure par défaut en heure française
            heure_defaut_naive = datetime(2025, 5, 28, 16, 35, 0)
            heure_defaut = FRANCE_TZ.localize(heure_defaut_naive).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            cursor.execute(
                "INSERT INTO cours_config (id, heure_debut) VALUES (1, ?)",
                (heure_defaut,),
            )
            logger.info(f"✅ Heure par défaut insérée: {heure_defaut}")
        else:
            logger.info("ℹ️ Configuration cours déjà présente")

        # Table de configuration par plateforme (3 lignes fixes)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_config (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                upload_locked INTEGER DEFAULT 1,
                pdf_filename TEXT,
                pdf_uploaded_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        logger.info("✅ Table platform_config créée/vérifiée")

        # Table des demandes de suppression des contributeurs
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS deletion_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                requester_name TEXT NOT NULL,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
            """
        )
        logger.info("✅ Table deletion_requests créée/vérifiée")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform_id INTEGER NOT NULL DEFAULT 1,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                nom TEXT NOT NULL,
                prenom TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(platform_id, username)
            )
            """
        )
        logger.info("✅ Table student_accounts créée/vérifiée")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS student_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auth_user_id TEXT NOT NULL UNIQUE,
                platform_id INTEGER NOT NULL DEFAULT 1,
                email TEXT NOT NULL,
                nom TEXT NOT NULL,
                prenom TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        logger.info("✅ Table student_profiles créée/vérifiée")

        # Seed plateformes si la table est vide
        cursor.execute("SELECT COUNT(*) FROM platform_config")
        pc_count = cursor.fetchone()[0]
        if pc_count == 0:
            now_str = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cursor.executemany(
                "INSERT INTO platform_config (id, name, upload_locked, updated_at) VALUES (?, ?, 1, ?)",
                [
                    (1, "Formation 1 TP CRCD", now_str),
                    (2, "Formation 2 TP EC", now_str),
                    (3, "Formation 3 TP EC", now_str),
                    (4, "Formation Courte", now_str),
                ],
            )
            logger.info("✅ 4 plateformes insérées dans platform_config")
        else:
            logger.info("ℹ️ platform_config déjà peuplée")

        # Migration des noms de plateformes
        cursor.executemany(
            "UPDATE platform_config SET name = ? WHERE id = ?",
            [
                ("Formation 1 TP CRCD", 1),
                ("Formation 2 TP EC", 2),
                ("Formation 3 TP EC", 3),
            ],
        )

        # Migration : ajouter P4 si absent
        cursor.execute("SELECT COUNT(*) FROM platform_config WHERE id = 4")
        if cursor.fetchone()[0] == 0:
            now_str = datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO platform_config (id, name, upload_locked, updated_at) VALUES (?, ?, 1, ?)",
                (4, "Formation Courte", now_str),
            )
            logger.info("✅ Plateforme 4 (Formation Courte) insérée dans platform_config")

        # Migration : ajout colonne playlist_mode si absente
        cursor.execute("PRAGMA table_info(platform_config)")
        columns = [col[1] for col in cursor.fetchall()]
        if "playlist_mode" not in columns:
            cursor.execute("ALTER TABLE platform_config ADD COLUMN playlist_mode TEXT DEFAULT NULL")
            logger.info("✅ Colonne playlist_mode ajoutée à platform_config")

        # Migration multi-tenant : colonnes containers dans platform_config
        cursor.execute("PRAGMA table_info(platform_config)")
        pc_columns = [col[1] for col in cursor.fetchall()]
        if "audio_container" not in pc_columns:
            cursor.execute("ALTER TABLE platform_config ADD COLUMN audio_container TEXT")
            cursor.execute("ALTER TABLE platform_config ADD COLUMN pdf_container TEXT")
            cursor.execute("ALTER TABLE platform_config ADD COLUMN archive_container TEXT")
            cursor.execute("ALTER TABLE platform_config ADD COLUMN audio_base_url TEXT")
            cursor.execute("ALTER TABLE platform_config ADD COLUMN slug TEXT")
            # Peupler les valeurs par défaut pour les plateformes existantes
            cursor.execute("UPDATE platform_config SET audio_container = 'formationaudio-dev', pdf_container = 'formationpdf', archive_container = 'formationaudio-archives', slug = 'formation-1' WHERE id = 1")
            cursor.execute("UPDATE platform_config SET audio_container = 'formationaudio-p2', pdf_container = 'formationpdf-p2', archive_container = 'formationaudio-archives-p2', slug = 'formation-2' WHERE id = 2")
            cursor.execute("UPDATE platform_config SET audio_container = 'formationaudio-p3', pdf_container = 'formationpdf-p3', archive_container = 'formationaudio-p3-archives', slug = 'formation-3' WHERE id = 3")
            cursor.execute("UPDATE platform_config SET audio_container = 'formationaudio-p4', pdf_container = 'formationpdf-p4', archive_container = 'formationaudio-p4-archives', slug = 'formation-courte' WHERE id = 4")
            logger.info("✅ Colonnes multi-tenant ajoutées à platform_config")

        # Migration formations durables : statut + référence vers la formation source
        # status : 'ready' (cours disponibles), 'pending' (pipeline en cours), 'error'
        # source_formation_id : pointe vers formation_pipeline_jobs.id quand cette
        # plateforme réutilise les cours d'une formation existante (1 RNCP = 1 module
        # réutilisé pour N promos).
        cursor.execute("PRAGMA table_info(platform_config)")
        pc_columns = [col[1] for col in cursor.fetchall()]
        if "status" not in pc_columns:
            cursor.execute("ALTER TABLE platform_config ADD COLUMN status TEXT DEFAULT 'ready'")
            cursor.execute("UPDATE platform_config SET status = 'ready' WHERE status IS NULL")
            logger.info("✅ Colonne status ajoutée à platform_config (default 'ready')")
        if "source_formation_id" not in pc_columns:
            cursor.execute("ALTER TABLE platform_config ADD COLUMN source_formation_id INTEGER")
            logger.info("✅ Colonne source_formation_id ajoutée à platform_config")

        # Migration multi-tenant : platform_id dans logs
        cursor.execute("PRAGMA table_info(logs)")
        logs_columns = [col[1] for col in cursor.fetchall()]
        if "platform_id" not in logs_columns:
            cursor.execute("ALTER TABLE logs ADD COLUMN platform_id INTEGER DEFAULT 1")
            logger.info("✅ Colonne platform_id ajoutée à logs")

        # Migration multi-tenant : platform_id dans video_visits
        cursor.execute("PRAGMA table_info(video_visits)")
        vv_columns = [col[1] for col in cursor.fetchall()]
        if "platform_id" not in vv_columns:
            cursor.execute("ALTER TABLE video_visits ADD COLUMN platform_id INTEGER DEFAULT 1")
            logger.info("✅ Colonne platform_id ajoutée à video_visits")

        # Migration multi-tenant : cours_config avec platform_id
        cursor.execute("PRAGMA table_info(cours_config)")
        cc_columns = [col[1] for col in cursor.fetchall()]
        if "platform_id" not in cc_columns:
            # Ajouter platform_id et copier la config existante pour toutes les plateformes
            cursor.execute("ALTER TABLE cours_config ADD COLUMN platform_id INTEGER")
            cursor.execute("UPDATE cours_config SET platform_id = 1 WHERE id = 1")
            # Créer une entrée par défaut pour chaque plateforme existante
            cursor.execute("SELECT heure_debut FROM cours_config WHERE id = 1")
            default_row = cursor.fetchone()
            if default_row:
                default_heure = default_row[0]
                for pid in [2, 3, 4]:
                    cursor.execute("SELECT COUNT(*) FROM cours_config WHERE platform_id = ?", (pid,))
                    if cursor.fetchone()[0] == 0:
                        cursor.execute("INSERT INTO cours_config (id, heure_debut, platform_id) VALUES (?, ?, ?)", (pid, default_heure, pid))
            logger.info("✅ cours_config migrée en multi-platform")

        # Table des dossiers de cours
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS cours_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        )
        # Migration : ajouter la colonne position si elle n'existe pas encore
        try:
            cursor.execute("ALTER TABLE cours_folders ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
            logger.info("✅ Colonne position ajoutée à cours_folders")
            # Initialiser les positions existantes par ordre de création
            cursor.execute("""
                UPDATE cours_folders SET position = (
                    SELECT COUNT(*) FROM cours_folders cf2
                    WHERE cf2.platform_id = cours_folders.platform_id
                    AND cf2.created_at <= cours_folders.created_at
                    AND cf2.id <= cours_folders.id
                ) - 1
            """)
        except Exception:
            pass  # Colonne déjà présente

        # Note : le carryover bloc 7 → folder suivant est porté par
        # `content_generation_jobs.carryover_in_text/out_text` (cf. migration plus
        # bas). Pas de colonne carryover sur `cours_folders`.

        # Migration : formation_job_id — lie un folder au pipeline qui l'a créé.
        # Évite que _determine_next_ap_step compte les segments de pipelines
        # différents sur la même plateforme (bug multi-run).
        try:
            cursor.execute("ALTER TABLE cours_folders ADD COLUMN formation_job_id INTEGER")
            logger.info("✅ Colonne formation_job_id ajoutée à cours_folders")
        except Exception:
            pass  # Colonne déjà présente

        logger.info("✅ Table cours_folders créée/vérifiée")

        # Table des documents de cours (PDFs + audios générés)
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS cours_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            doc_type TEXT DEFAULT 'source',
            status TEXT DEFAULT 'uploaded',
            audio_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id)
        )
        """
        )
        try:
            cursor.execute("ALTER TABLE cours_documents ADD COLUMN doc_type TEXT DEFAULT 'source'")
            logger.info("✅ Colonne doc_type ajoutée à cours_documents")
        except Exception:
            pass  # Colonne déjà présente
        cursor.execute("""
            UPDATE cours_documents
            SET doc_type = 'final_script'
            WHERE original_name LIKE 'cours_genere_%.txt'
        """)
        logger.info("✅ Table cours_documents créée/vérifiée")

        # Table des jobs de génération de contenu TTS-direct
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_generation_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL UNIQUE,
            platform_id INTEGER NOT NULL,
            program_text TEXT NOT NULL,
            program_title TEXT DEFAULT '',
            sub_parts TEXT DEFAULT '[]',
            status TEXT DEFAULT 'idle',
            current_sub_part INTEGER DEFAULT 0,
            current_passe INTEGER DEFAULT 1,
            total_words INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id)
        )
        """)
        logger.info("✅ Table content_generation_jobs créée/vérifiée")

        # Table des segments générés (checkpointing)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_generation_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            sub_part_index INTEGER NOT NULL,
            sub_part_name TEXT NOT NULL,
            passe INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            text_content TEXT DEFAULT '',
            word_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES content_generation_jobs(id),
            UNIQUE(job_id, sub_part_index, passe)
        )
        """)
        logger.info("✅ Table content_generation_segments créée/vérifiée")

        # Migration : ajouter colonne dirty si elle n'existe pas
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN dirty INTEGER DEFAULT 0")
            logger.info("✅ Colonne dirty ajoutée à content_generation_segments")
        except Exception:
            pass  # Colonne déjà présente

        # Migration : colonne reviewed (reviewer conformité, cf. memoire/03-decisions/pipeline-dual-api-et-claude-code.md)
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN reviewed INTEGER DEFAULT 0")
            logger.info("✅ Colonne reviewed ajoutée à content_generation_segments")
        except Exception:
            pass
        # Migration : colonne generated_via (trace d'origine API / Claude Code, valeurs :
        # 'api' | 'claude_code_haiku' | 'claude_code_sonnet'). NULL tant que rien n'a tranché.
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN generated_via TEXT")
            logger.info("✅ Colonne generated_via ajoutée à content_generation_segments")
        except Exception:
            pass
        # Migration : colonne review_error — message d'erreur quand l'appel
        # reviewer Claude a échoué. NULL si jamais audité ou audit OK.
        # Le polling frontend considère un segment comme "traité" si
        # reviewed=1 OU review_error IS NOT NULL (les deux comptent pour
        # arrêter la barre de progression sans mentir sur la conformité).
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN review_error TEXT")
            logger.info("✅ Colonne review_error ajoutée à content_generation_segments")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN text_content_pre_review TEXT")
            logger.info("✅ Colonne text_content_pre_review ajoutée à content_generation_segments")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN review_signature TEXT")
            logger.info("✅ Colonne review_signature ajoutée à content_generation_segments")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN humanized INTEGER DEFAULT 0")
            logger.info("✅ Colonne humanized ajoutée à content_generation_segments")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN humanization_error TEXT")
            logger.info("✅ Colonne humanization_error ajoutée à content_generation_segments")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE content_generation_segments ADD COLUMN humanization_signature TEXT")
            logger.info("✅ Colonne humanization_signature ajoutée à content_generation_segments")
        except Exception:
            pass

        # Notes humaines sur le script TTS : chaque selection/commentaire est
        # conservé pour produire un markdown de revue exploitable par l'agent de
        # correction avant régénération audio.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_script_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'course',
            sub_part_index INTEGER,
            passe INTEGER,
            bloc_number INTEGER,
            filename TEXT,
            selected_text TEXT NOT NULL,
            comment TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            markdown_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id),
            FOREIGN KEY (job_id) REFERENCES content_generation_jobs(id)
        )
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_script_annotations_folder_job
        ON content_script_annotations(folder_id, job_id, status)
        """)
        logger.info("✅ Table content_script_annotations créée/vérifiée")

        # Migration : colonnes pour la correction DeepSeek immédiate.
        # original_paragraph = paragraphe alentour extrait du script au moment de l'annotation.
        # proposed_text = correction renvoyée par DeepSeek (paragraphe complet réécrit).
        # correction_status = pending | proposed | applied | rejected | error.
        # correction_error = message d'erreur quand l'appel DeepSeek a échoué.
        # Règles transversales apprises depuis les annotations appliquées.
        # Un markdown éditable par (folder_id, job_id) — alimente la Phase 3
        # de revérif post-TTS qui patche les chunks non-conformes.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_script_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            rules_markdown TEXT NOT NULL DEFAULT '',
            rules_count INTEGER DEFAULT 0,
            source_annotations_count INTEGER DEFAULT 0,
            model TEXT,
            markdown_path TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(folder_id, job_id),
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id),
            FOREIGN KEY (job_id) REFERENCES content_generation_jobs(id)
        )
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_script_rules_folder_job
        ON content_script_rules(folder_id, job_id)
        """)
        logger.info("✅ Table content_script_rules créée/vérifiée")

        for _col, _ddl in (
            ("original_paragraph", "ALTER TABLE content_script_annotations ADD COLUMN original_paragraph TEXT"),
            ("proposed_text", "ALTER TABLE content_script_annotations ADD COLUMN proposed_text TEXT"),
            ("correction_status", "ALTER TABLE content_script_annotations ADD COLUMN correction_status TEXT DEFAULT 'pending'"),
            ("correction_error", "ALTER TABLE content_script_annotations ADD COLUMN correction_error TEXT"),
            ("applied_at", "ALTER TABLE content_script_annotations ADD COLUMN applied_at TIMESTAMP"),
            ("splice_status", "ALTER TABLE content_script_annotations ADD COLUMN splice_status TEXT"),
            ("splice_error", "ALTER TABLE content_script_annotations ADD COLUMN splice_error TEXT"),
            ("splice_blob_path", "ALTER TABLE content_script_annotations ADD COLUMN splice_blob_path TEXT"),
        ):
            try:
                cursor.execute(_ddl)
                logger.info(f"✅ Colonne {_col} ajoutée à content_script_annotations")
            except Exception:
                pass

        # Migration : ajouter colonnes from_scratch + module_contents (pipeline formation)
        cursor.execute("PRAGMA table_info(content_generation_jobs)")
        cg_columns = [col[1] for col in cursor.fetchall()]
        if "from_scratch" not in cg_columns:
            cursor.execute("ALTER TABLE content_generation_jobs ADD COLUMN from_scratch INTEGER DEFAULT 0")
            logger.info("✅ Colonne from_scratch ajoutée à content_generation_jobs")
        if "module_contents" not in cg_columns:
            cursor.execute("ALTER TABLE content_generation_jobs ADD COLUMN module_contents TEXT DEFAULT '{}'")
            logger.info("✅ Colonne module_contents ajoutée à content_generation_jobs")
        _carryover_cols = {
            "carryover_in_text": "TEXT DEFAULT ''",
            "carryover_in_source_folder_id": "INTEGER",
            "carryover_out_text": "TEXT DEFAULT ''",
            "carryover_out_target_folder_id": "INTEGER",
        }
        for col, col_type in _carryover_cols.items():
            if col not in cg_columns:
                cursor.execute(f"ALTER TABLE content_generation_jobs ADD COLUMN {col} {col_type}")
                logger.info(f"✅ Colonne {col} ajoutée à content_generation_jobs")

        # Table des jobs pipeline formation automatisé
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS formation_pipeline_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL DEFAULT 1,
            tp_name TEXT NOT NULL,
            rncp_code TEXT,
            total_hours INTEGER NOT NULL,
            nb_days INTEGER NOT NULL,
            reac_text TEXT,
            global_program TEXT,
            global_program_validated INTEGER DEFAULT 0,
            daily_programs TEXT DEFAULT '[]',
            daily_programs_validated INTEGER DEFAULT 0,
            status TEXT DEFAULT 'init',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        logger.info("✅ Table formation_pipeline_jobs créée/vérifiée")

        # Migration : colonnes rc_text + rome_text
        cursor.execute("PRAGMA table_info(formation_pipeline_jobs)")
        fpj_cols = [col[1] for col in cursor.fetchall()]
        if "rc_text" not in fpj_cols:
            cursor.execute("ALTER TABLE formation_pipeline_jobs ADD COLUMN rc_text TEXT")
            logger.info("✅ Colonne rc_text ajoutée à formation_pipeline_jobs")
        if "rome_text" not in fpj_cols:
            cursor.execute("ALTER TABLE formation_pipeline_jobs ADD COLUMN rome_text TEXT")
            logger.info("✅ Colonne rome_text ajoutée à formation_pipeline_jobs")

        # Migrations pour tracer l'origine API / Claude Code de chaque artefact
        # (Phase 2 de memoire/03-decisions/pipeline-dual-api-et-claude-code.md).
        # Valeurs attendues : 'api' | 'claude_code_haiku' | 'claude_code_sonnet'.
        for col in ("kb_generated_via", "global_program_generated_via", "daily_programs_generated_via"):
            if col not in fpj_cols:
                cursor.execute(f"ALTER TABLE formation_pipeline_jobs ADD COLUMN {col} TEXT")
                logger.info(f"✅ Colonne {col} ajoutée à formation_pipeline_jobs")

        # State machine auto-pilot persistée (résiste aux restarts Azure App Service)
        _ap_cols = {
            "auto_pilot_enabled": "INTEGER DEFAULT 0",
            "auto_pilot_step":    "TEXT",
            "auto_pilot_model":   "TEXT",
            "auto_pilot_tts_mode": "TEXT",
            "auto_pilot_use_cc":  "INTEGER DEFAULT 0",
            "auto_pilot_skip_vs": "INTEGER DEFAULT 0",
            "auto_pilot_generate_audio": "INTEGER DEFAULT 0",
            "auto_pilot_volume_done": "INTEGER DEFAULT 0",
            "auto_pilot_post_review_docs_done": "INTEGER DEFAULT 0",
            "auto_pilot_error":   "TEXT",
            "auto_pilot_locked_at": "TIMESTAMP",
            "auto_pilot_lock_owner": "TEXT",
        }
        for col, col_type in _ap_cols.items():
            if col not in fpj_cols:
                cursor.execute(f"ALTER TABLE formation_pipeline_jobs ADD COLUMN {col} {col_type}")
                logger.info(f"✅ Colonne {col} ajoutée à formation_pipeline_jobs")

        # ─── Couche 1 : Knowledge Base enrichie depuis REAC ──────────────────
        # Chaque compétence du REAC est enrichie par Claude avec définition
        # pédagogique, études de cas, pièges, vocabulaire, contexte terrain,
        # liens connexes. Objectif : passer le matériau source de ~15k mots
        # (REAC brut) à ~120-150k mots exploitables pour la génération du
        # programme de formation. Checkpointing + flag dirty permettent de
        # régénérer sélectivement une compétence éditée.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS formation_knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            competence_index INTEGER NOT NULL,
            competence_key TEXT NOT NULL,
            competence_title TEXT NOT NULL,
            bloc TEXT,
            raw_source TEXT,
            definition_pedagogique TEXT DEFAULT '',
            etudes_de_cas TEXT DEFAULT '[]',
            pieges_frequents TEXT DEFAULT '[]',
            vocabulaire_metier TEXT DEFAULT '{}',
            contexte_terrain TEXT DEFAULT '',
            liens_connexes TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            dirty INTEGER DEFAULT 0,
            error_message TEXT,
            total_words INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES formation_pipeline_jobs(id),
            UNIQUE(job_id, competence_index)
        )
        """)
        logger.info("✅ Table formation_knowledge_base créée/vérifiée")

        # ─── Table formation_modules : produits durables des pipelines ────────
        # Principe "1 RNCP = 1 module durable" matérialisé : quand une pipeline
        # atteint audio_launched, un module est auto-créé. Les plateformes
        # (promos) créées ensuite pointent vers un module et clonent son contenu.
        # UNIQUE(source_pipeline_job_id) : un job pipeline produit 0 ou 1 module.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS formation_modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rncp_code TEXT,
            tp_name TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT DEFAULT 'validated',
            source_pipeline_job_id INTEGER UNIQUE,
            source_platform_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            validated_at TIMESTAMP,
            archived_at TIMESTAMP,
            FOREIGN KEY (source_pipeline_job_id) REFERENCES formation_pipeline_jobs(id),
            FOREIGN KEY (source_platform_id) REFERENCES platform_config(id)
        )
        """)
        logger.info("✅ Table formation_modules créée/vérifiée")

        # Colonne voice_type : trace la voix TTS utilisée pour les MP3 du module.
        # Mise à jour à chaque relance de l'étape 7 (Fish Audio / gTTS / mock).
        # Permet de savoir d'un coup d'œil quelle voix porte les audios du module.
        cursor.execute("PRAGMA table_info(formation_modules)")
        fm_cols = [col[1] for col in cursor.fetchall()]
        if "voice_type" not in fm_cols:
            cursor.execute("ALTER TABLE formation_modules ADD COLUMN voice_type TEXT")
            logger.info("✅ Colonne voice_type ajoutée à formation_modules")
        if "voice_updated_at" not in fm_cols:
            cursor.execute("ALTER TABLE formation_modules ADD COLUMN voice_updated_at TIMESTAMP")
            logger.info("✅ Colonne voice_updated_at ajoutée à formation_modules")

        # ─── Observabilité pipeline : rapports conformité + événements ───────
        # Les rapports de conformité ne peuvent pas dépendre uniquement du
        # filesystem local en production Azure. Cette table garde un snapshot
        # durable par exécution de review, récupérable par le frontend.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_review_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            folder_id INTEGER NOT NULL,
            source TEXT DEFAULT 'api',
            generated_via TEXT,
            summary_json TEXT DEFAULT '{}',
            report_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES formation_pipeline_jobs(id),
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id)
        )
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_review_reports_job_folder
        ON content_review_reports(job_id, folder_id, created_at)
        """)
        logger.info("✅ Table content_review_reports créée/vérifiée")

        # Append-only : chaque transition importante de pipeline est conservée
        # pour diagnostic et futur dashboard qualité.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS formation_pipeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            folder_id INTEGER,
            step TEXT,
            event_type TEXT NOT NULL,
            status TEXT DEFAULT 'info',
            message TEXT,
            model TEXT,
            duration_ms INTEGER,
            data_json TEXT DEFAULT '{}',
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES formation_pipeline_jobs(id),
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id)
        )
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_formation_pipeline_events_job
        ON formation_pipeline_events(job_id, created_at)
        """)
        logger.info("✅ Table formation_pipeline_events créée/vérifiée")

        # Colonne source_module_id sur platform_config (nullable, FK vers le module)
        cursor.execute("PRAGMA table_info(platform_config)")
        pc_cols_mod = [col[1] for col in cursor.fetchall()]
        if "source_module_id" not in pc_cols_mod:
            cursor.execute("ALTER TABLE platform_config ADD COLUMN source_module_id INTEGER")
            logger.info("✅ Colonne source_module_id ajoutée à platform_config")

        # Migration rétroactive idempotente : pour chaque job pipeline terminé
        # sans module, créer un module automatiquement. L'UNIQUE constraint sur
        # source_pipeline_job_id garantit qu'on ne duplique pas si on tourne
        # cette migration plusieurs fois.
        cursor.execute("""
            SELECT j.id, j.rncp_code, j.tp_name, j.platform_id, j.created_at
            FROM formation_pipeline_jobs j
            WHERE j.status IN ('audio_launched', 'completed')
              AND NOT EXISTS (
                SELECT 1 FROM formation_modules WHERE source_pipeline_job_id = j.id
              )
            ORDER BY j.created_at ASC
        """)
        jobs_to_migrate = cursor.fetchall()
        current_year = datetime.now(FRANCE_TZ).year
        for j_id, j_rncp, j_tp, j_pid, j_created in jobs_to_migrate:
            # Version = {year}-v{n} où n = modules existants pour ce RNCP + 1
            cursor.execute(
                "SELECT COUNT(*) FROM formation_modules WHERE rncp_code = ?",
                (j_rncp or "",),
            )
            n = cursor.fetchone()[0] + 1
            version = f"{current_year}-v{n}"
            cursor.execute("""
                INSERT OR IGNORE INTO formation_modules
                (rncp_code, tp_name, version, status, source_pipeline_job_id, source_platform_id, validated_at)
                VALUES (?, ?, ?, 'validated', ?, ?, CURRENT_TIMESTAMP)
            """, (j_rncp, j_tp, version, j_id, j_pid))
            if cursor.rowcount > 0:
                logger.info(f"🔄 Module rétro-créé : {j_tp} {version} (job {j_id})")
        if jobs_to_migrate:
            logger.info(f"🔄 Migration rétroactive formation_modules : {len(jobs_to_migrate)} job(s) traités")

        conn.commit()
        conn.close()
        logger.info("✅ Base de données initialisée avec succès")

    except Exception as e:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        logger.error(f"❌ Erreur lors de l'initialisation de la base: {e}")
        if _is_malformed_database_error(e) and not _recovered_from_corruption:
            backup_path = _quarantine_corrupt_database(DB_PATH)
            logger.error(
                "🧯 Récupération SQLite: ancienne base sauvegardée sous %s",
                backup_path,
            )
            # Tenter de repartir du dernier backup sain plutôt que d'une base
            # vide ; sinon, base neuve + mode maintenance (cf. db_safety).
            from database.db_safety import (
                _restore_latest_healthy_backup,
                db_health,
                set_maintenance,
            )
            restored = _restore_latest_healthy_backup(DB_PATH)
            if restored:
                logger.warning("♻️ Base restaurée depuis le backup %s", restored)
                db_health["recovery_notice"] = "restored_from_backup"
                db_health["recovery_detail"] = (
                    f"Corruption détectée pendant init_database ({e}). "
                    f"Restaurée depuis {restored}."
                )
            else:
                db_health["recovery_notice"] = "recreated_empty"
                db_health["recovery_detail"] = (
                    f"Corruption détectée pendant init_database ({e}). "
                    "Aucun backup sain : base recréée vide."
                )
                set_maintenance(
                    True,
                    "Base corrompue recréée vide pendant init_database — "
                    "restauration manuelle requise.",
                )
            return init_database(_recovered_from_corruption=True)
        raise
