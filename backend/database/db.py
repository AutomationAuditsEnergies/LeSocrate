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

        conn.commit()
        conn.close()
        logger.info("✅ Base de données initialisée avec succès")

    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation de la base: {e}")
        raise
