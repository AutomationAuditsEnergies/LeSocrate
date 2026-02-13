# time_service.py - Gestion du temps et des simulations
from datetime import datetime
import state
from config import FRANCE_TZ
from database.db import get_db_connection
from utils.logger import get_logger

logger = get_logger(__name__)


def get_current_simulated_time():
    """Retourne l'heure actuelle ou l'heure simulée EN HEURE FRANÇAISE"""
    try:
        if state.simulated_time_offset is not None:
            logger.debug(f"⏰ Utilisation temps simulé: {state.simulated_time_offset}")
            # S'assurer que la simulation a un timezone français
            if state.simulated_time_offset.tzinfo is None:
                result = FRANCE_TZ.localize(state.simulated_time_offset)
                logger.debug(f"⏰ Timezone ajouté au temps simulé: {result}")
                return result
            result = state.simulated_time_offset.astimezone(FRANCE_TZ)
            logger.debug(f"⏰ Temps simulé converti: {result}")
            return result

        # Heure actuelle en France
        result = datetime.now(FRANCE_TZ)
        logger.debug(f"⏰ Heure réelle française: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Erreur get_current_simulated_time: {e}")
        return datetime.now(FRANCE_TZ)


def set_heure_debut_cours(nouvelle_heure):
    """Met à jour l'heure de début du cours dans la base de données"""
    try:
        logger.info(f"⏰ Mise à jour heure début cours: {nouvelle_heure}")
        conn = get_db_connection()
        cursor = conn.cursor()

        # Si l'heure n'a pas de timezone, la considérer comme française
        if nouvelle_heure.tzinfo is None:
            nouvelle_heure = FRANCE_TZ.localize(nouvelle_heure)
            logger.debug(f"⏰ Timezone ajouté: {nouvelle_heure}")

        # Stocker en format string (sans timezone pour simplicité)
        heure_str = nouvelle_heure.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE cours_config SET heure_debut = ? WHERE id = 1", (heure_str,)
        )
        conn.commit()
        conn.close()
        logger.info(f"✅ Heure début cours mise à jour: {heure_str}")
    except Exception as e:
        logger.error(f"❌ Erreur set_heure_debut_cours: {e}")
        raise


def get_heure_debut_cours():
    """Récupère l'heure de début du cours EN HEURE FRANÇAISE"""
    try:
        logger.debug("🔍 Récupération heure début cours")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT heure_debut FROM cours_config WHERE id = 1")
        result = cursor.fetchone()
        conn.close()

        if result:
            # Interpréter l'heure stockée comme heure française
            dt_naive = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
            dt_fr = FRANCE_TZ.localize(dt_naive)
            logger.debug(f"✅ Heure début cours récupérée: {dt_fr}")
            return dt_fr
        else:
            # Fallback par défaut en heure française
            dt_naive = datetime(2025, 5, 28, 16, 35, 0)
            dt_fr = FRANCE_TZ.localize(dt_naive)
            logger.warning(f"⚠️ Utilisation heure par défaut: {dt_fr}")
            return dt_fr
    except Exception as e:
        logger.error(f"❌ Erreur get_heure_debut_cours: {e}")
        dt_naive = datetime(2025, 5, 28, 16, 35, 0)
        return FRANCE_TZ.localize(dt_naive)
