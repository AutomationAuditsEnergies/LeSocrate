# audio_service.py - Logique de gestion de la playlist et des audios
import copy
from config import COURS_PLAYLIST, FRANCE_TZ
from services.time_service import get_heure_debut_cours, get_current_simulated_time
from utils.logger import get_logger

logger = get_logger(__name__)

# ─── Items été : cours → qa → pause_midi ─────────────────────────────────
_AUDIO_BASE = COURS_PLAYLIST[0]["filename"].rsplit("/", 1)[0]

BLOC4_ETE = [
    {
        "id": 10,
        "filename": f"{_AUDIO_BASE}/cours_12h20_13h05.mp3",
        "duration": 2700,
        "title": "Cours - Bloc 4 (12h20-13h05)",
        "type": "cours",
    },
    {
        "id": 11,
        "filename": f"{_AUDIO_BASE}/qa_13h05_13h15.mp3",
        "duration": 600,
        "title": "Questions-Réponses IA (13h05-13h15)",
        "type": "qa",
    },
    {
        "id": 12,
        "filename": f"{_AUDIO_BASE}/pause_midi_13h15_14h45.mp3",
        "duration": 5400,
        "title": "Pause déjeuner (13h15-14h45)",
        "type": "pause_midi",
    },
]

# ─── Items hiver (ordre actuel) : pause_midi → cours → qa ────────────────
BLOC4_HIVER = [
    {
        "id": 10,
        "filename": f"{_AUDIO_BASE}/pause_midi_13h15_14h45.mp3",
        "duration": 5400,
        "title": "Pause déjeuner (12h20-13h50)",
        "type": "pause_midi",
    },
    {
        "id": 11,
        "filename": f"{_AUDIO_BASE}/cours_12h20_13h05.mp3",
        "duration": 2700,
        "title": "Cours - Bloc 4 (13h50-14h35)",
        "type": "cours",
    },
    {
        "id": 12,
        "filename": f"{_AUDIO_BASE}/qa_13h05_13h15.mp3",
        "duration": 600,
        "title": "Questions-Réponses IA (14h35-14h45)",
        "type": "qa",
    },
]


def get_playlist(platform_id=None):
    """
    Retourne la playlist adaptée selon le mode été/hiver de la plateforme.
    - playlist_mode = 'ete' → cours/qa/pause (été)
    - playlist_mode = 'hiver' ou NULL → pause/cours/qa (hiver, défaut)
    """
    playlist = copy.deepcopy(COURS_PLAYLIST)

    if platform_id is None:
        return playlist

    try:
        from database.db import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT playlist_mode FROM platform_config WHERE id = ?", (platform_id,))
        row = cursor.fetchone()
        conn.close()

        mode = row[0] if row else None
    except Exception as e:
        logger.warning(f"⚠️ Impossible de lire playlist_mode: {e}")
        return playlist

    if mode == "ete":
        bloc = BLOC4_ETE
    else:
        bloc = BLOC4_HIVER

    # Remplacer les items aux positions 9, 10, 11 (index 0-based pour IDs 10, 11, 12)
    playlist[9] = bloc[0]
    playlist[10] = bloc[1]
    playlist[11] = bloc[2]

    return playlist


def get_current_audio_info(platform_id=None):
    """
    Détermine quel fichier audio doit être joué et à quelle position.
    Retourne: (audio_info, offset, temps_restant)
    """
    try:
        logger.debug("🎵 Calcul info audio actuel")
        heure_debut_cours = get_heure_debut_cours(platform_id or 1)
        now = get_current_simulated_time(platform_id)

        logger.debug(f"🎵 Heure début: {heure_debut_cours}")
        logger.debug(f"🎵 Heure actuelle: {now}")

        if now.tzinfo is None:
            now = FRANCE_TZ.localize(now)
        if heure_debut_cours.tzinfo is None:
            heure_debut_cours = FRANCE_TZ.localize(heure_debut_cours)

        if now < heure_debut_cours:
            temps_restant = int((heure_debut_cours - now).total_seconds())
            logger.debug(
                f"🎵 Cours pas encore commencé, temps restant: {temps_restant}s"
            )
            return None, 0, temps_restant

        temps_ecoule = int((now - heure_debut_cours).total_seconds())
        logger.debug(f"🎵 Temps écoulé depuis début: {temps_ecoule}s")

        playlist = get_playlist(platform_id)

        temps_cumule = 0
        for i, audio in enumerate(playlist):
            if temps_cumule + audio["duration"] > temps_ecoule:
                offset_dans_audio = temps_ecoule - temps_cumule
                logger.info(
                    f"🎵 Audio actuel: {audio['title']} (ID: {audio['id']}) - Offset: {offset_dans_audio}s"
                )
                return audio, offset_dans_audio, 0
            temps_cumule += audio["duration"]
            logger.debug(f"🎵 Audio {i+1} passé, temps cumulé: {temps_cumule}s")

        logger.info("🎵 Cours terminé - tous les audios ont été joués")
        return None, 0, 0

    except Exception as e:
        logger.error(f"❌ Erreur dans get_current_audio_info: {e}")
        return None, 0, 0
