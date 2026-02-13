# audio_service.py - Logique de gestion de la playlist et des audios
from config import COURS_PLAYLIST, FRANCE_TZ
from services.time_service import get_heure_debut_cours, get_current_simulated_time
from utils.logger import get_logger

logger = get_logger(__name__)


def get_current_audio_info():
    """
    Détermine quel fichier audio doit être joué et à quelle position
    Retourne: (audio_info, offset, temps_restant)
    """
    try:
        logger.debug("🎵 Calcul info audio actuel")
        heure_debut_cours = get_heure_debut_cours()
        now = get_current_simulated_time()

        logger.debug(f"🎵 Heure début: {heure_debut_cours}")
        logger.debug(f"🎵 Heure actuelle: {now}")

        # S'assurer que les deux ont le même timezone
        if now.tzinfo is None:
            now = FRANCE_TZ.localize(now)
        if heure_debut_cours.tzinfo is None:
            heure_debut_cours = FRANCE_TZ.localize(heure_debut_cours)

        # Si le cours n'a pas encore commencé
        if now < heure_debut_cours:
            temps_restant = int((heure_debut_cours - now).total_seconds())
            logger.debug(
                f"🎵 Cours pas encore commencé, temps restant: {temps_restant}s"
            )
            return None, 0, temps_restant

        # Calculer le temps écoulé depuis le début du cours
        temps_ecoule = int((now - heure_debut_cours).total_seconds())
        logger.debug(f"🎵 Temps écoulé depuis début: {temps_ecoule}s")

        # Parcourir la playlist pour trouver l'audio actuel
        temps_cumule = 0
        for i, audio in enumerate(COURS_PLAYLIST):
            if temps_cumule + audio["duration"] > temps_ecoule:
                # C'est l'audio actuel
                offset_dans_audio = temps_ecoule - temps_cumule
                logger.info(
                    f"🎵 Audio actuel: {audio['title']} (ID: {audio['id']}) - Offset: {offset_dans_audio}s"
                )
                return audio, offset_dans_audio, 0
            temps_cumule += audio["duration"]
            logger.debug(f"🎵 Audio {i+1} passé, temps cumulé: {temps_cumule}s")

        # Si on a dépassé tous les audios, le cours est terminé
        logger.info("🎵 Cours terminé - tous les audios ont été joués")
        return None, 0, 0

    except Exception as e:
        logger.error(f"❌ Erreur dans get_current_audio_info: {e}")
        return None, 0, 0
