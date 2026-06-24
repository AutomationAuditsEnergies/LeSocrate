# time_service.py - Gestion du temps et des simulations
from datetime import datetime
import state
from config import FRANCE_TZ
from database.db import get_db_connection
from utils.logger import get_logger

logger = get_logger(__name__)


def _ensure_cours_config(cursor):
    """Ensure the course-time table exists before reading/writing it."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cours_config (
            id INTEGER PRIMARY KEY,
            heure_debut TEXT NOT NULL
        )
        """
    )
    cursor.execute("PRAGMA table_info(cours_config)")
    columns = [col[1] for col in cursor.fetchall()]
    if "platform_id" not in columns:
        cursor.execute("ALTER TABLE cours_config ADD COLUMN platform_id INTEGER")
        cursor.execute("UPDATE cours_config SET platform_id = id WHERE platform_id IS NULL")


def get_current_simulated_time(platform_id=None):
    """Retourne l'heure actuelle ou l'heure simulée EN HEURE FRANÇAISE"""
    try:
        # Chercher un offset spécifique à la plateforme d'abord
        offset = None
        if platform_id is not None:
            offset = state.simulated_time_offsets.get(platform_id)
        # Fallback sur l'ancien global
        if offset is None:
            offset = state.simulated_time_offset

        if offset is not None:
            logger.debug(f"⏰ Utilisation temps simulé (P{platform_id}): {offset}")
            if offset.tzinfo is None:
                return FRANCE_TZ.localize(offset)
            return offset.astimezone(FRANCE_TZ)

        return datetime.now(FRANCE_TZ)
    except Exception as e:
        logger.error(f"❌ Erreur get_current_simulated_time: {e}")
        return datetime.now(FRANCE_TZ)


def set_heure_debut_cours(nouvelle_heure, platform_id=1):
    """Met à jour l'heure de début du cours dans la base de données"""
    try:
        logger.info(f"⏰ Mise à jour heure début cours P{platform_id}: {nouvelle_heure}")
        conn = get_db_connection()
        cursor = conn.cursor()
        _ensure_cours_config(cursor)

        if nouvelle_heure.tzinfo is None:
            nouvelle_heure = FRANCE_TZ.localize(nouvelle_heure)

        heure_str = nouvelle_heure.strftime("%Y-%m-%d %H:%M:%S")

        # Essayer de mettre à jour par platform_id d'abord (multi-tenant)
        cursor.execute(
            "UPDATE cours_config SET heure_debut = ? WHERE platform_id = ?",
            (heure_str, platform_id),
        )
        if cursor.rowcount == 0:
            # Fallback : insérer si la ligne n'existe pas encore
            cursor.execute(
                "INSERT INTO cours_config (id, heure_debut, platform_id) VALUES (?, ?, ?)",
                (platform_id, heure_str, platform_id),
            )

        conn.commit()
        conn.close()
        logger.info(f"✅ Heure début cours P{platform_id} mise à jour: {heure_str}")
    except Exception as e:
        logger.error(f"❌ Erreur set_heure_debut_cours: {e}")
        raise


def get_heure_debut_cours(platform_id=1):
    """Récupère l'heure de début du cours EN HEURE FRANÇAISE"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        _ensure_cours_config(cursor)

        # Essayer par platform_id d'abord (multi-tenant)
        cursor.execute("SELECT heure_debut FROM cours_config WHERE platform_id = ?", (platform_id,))
        result = cursor.fetchone()

        if not result:
            # Fallback : ancienne table avec id = 1
            cursor.execute("SELECT heure_debut FROM cours_config WHERE id = 1")
            result = cursor.fetchone()

        conn.close()

        if result:
            dt_naive = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
            return FRANCE_TZ.localize(dt_naive)
        else:
            dt_naive = datetime(2025, 5, 28, 16, 35, 0)
            return FRANCE_TZ.localize(dt_naive)
    except Exception as e:
        logger.error(f"❌ Erreur get_heure_debut_cours: {e}")
        dt_naive = datetime(2025, 5, 28, 16, 35, 0)
        return FRANCE_TZ.localize(dt_naive)
