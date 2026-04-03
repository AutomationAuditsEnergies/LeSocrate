# db.py - Gestion de la base de données
import sqlite3
from datetime import datetime
from config import DB_PATH, FRANCE_TZ
from utils.logger import get_logger

logger = get_logger(__name__)


def get_db_connection():
    """Retourne une connexion à la base de données SQLite"""
    return sqlite3.connect(DB_PATH)


def init_database():
    """Initialise la base de données avec les tables nécessaires"""
    logger.info("🗄️ Initialisation de la base de données...")
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

        # Seed 3 plateformes si la table est vide
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
                ],
            )
            logger.info("✅ 3 plateformes insérées dans platform_config")
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

        # Migration : ajout colonne playlist_mode si absente
        cursor.execute("PRAGMA table_info(platform_config)")
        columns = [col[1] for col in cursor.fetchall()]
        if "playlist_mode" not in columns:
            cursor.execute("ALTER TABLE platform_config ADD COLUMN playlist_mode TEXT DEFAULT NULL")
            logger.info("✅ Colonne playlist_mode ajoutée à platform_config")

        # Table des dossiers de cours
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS cours_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        )
        logger.info("✅ Table cours_folders créée/vérifiée")

        # Table des documents de cours (PDFs + audios générés)
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS cours_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            status TEXT DEFAULT 'uploaded',
            audio_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (folder_id) REFERENCES cours_folders(id)
        )
        """
        )
        logger.info("✅ Table cours_documents créée/vérifiée")

        conn.commit()
        conn.close()
        logger.info("✅ Base de données initialisée avec succès")

    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation de la base: {e}")
        raise
