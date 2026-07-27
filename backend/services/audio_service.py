# audio_service.py - Logique de gestion de la playlist et des audios
import copy
from datetime import datetime
from config import COURS_PLAYLIST, DATABASE_BACKEND, FRANCE_TZ, PIPELINE_DATABASE_BACKEND
from services.time_service import get_heure_debut_cours, get_current_simulated_time
from utils.logger import get_logger

logger = get_logger(__name__)


class CourseSessionPlaylistUnavailable(RuntimeError):
    """A V2 occurrence has no usable immutable playlist."""


def is_explicit_schedule_occurrence(occurrence):
    """Return whether an occurrence belongs to the explicit V2 calendar.

    ``local_date`` is persisted as soon as an explicit calendar is saved,
    while ``module_day_id`` can temporarily remain NULL until the durable
    module snapshots are linked. Such an incomplete V2 occurrence must fail
    closed instead of borrowing the historic V1 playlist.
    """
    return bool(occurrence) and (
        occurrence.get("module_day_id") is not None
        or occurrence.get("local_date") is not None
    )


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


def _platform_audio_base(audio_base_url, audio_container):
    """Base URL audio propre à la plateforme.

    Priorité : platform_config.audio_base_url > host commun (FrontDoor) +
    platform_config.audio_container > base env du backend (_AUDIO_BASE).
    Indispensable pour les plateformes créées depuis le dashboard (P5+) qui
    partagent le backend socrate1 : sans ça, elles jouaient toutes les audios
    du container de P1 (formationaudio-dev).
    """
    base = (audio_base_url or "").strip().rstrip("/")
    if base:
        return base
    container = (audio_container or "").strip().strip("/")
    if container:
        host = _AUDIO_BASE.rsplit("/", 1)[0]
        return f"{host}/{container}"
    return _AUDIO_BASE


def get_playlist(platform_id=None):
    """
    Retourne la playlist adaptée à la plateforme :
    - mode été/hiver ('ete' → cours/qa/pause ; 'hiver' ou NULL → pause/cours/qa)
    - URLs réécrites sur le container audio de la plateforme (platform_config)
    """
    playlist = copy.deepcopy(COURS_PLAYLIST)

    if platform_id is None:
        return playlist

    postgres_authoritative = (
        DATABASE_BACKEND in {"postgres", "postgresql", "supabase"}
        or PIPELINE_DATABASE_BACKEND in {"postgres", "postgresql", "supabase"}
    )
    try:
        if postgres_authoritative:
            from repositories.core_repository import get_platform_audio_config

            row = get_platform_audio_config(int(platform_id))
            if not row:
                raise LookupError(f"Plateforme {platform_id} introuvable dans PostgreSQL")
            logger.debug(
                "PLAYLIST_CONFIG_POSTGRES_READ platform_id=%s database_backend=%s "
                "pipeline_backend=%s",
                platform_id,
                DATABASE_BACKEND,
                PIPELINE_DATABASE_BACKEND,
            )
            mode = row["playlist_mode"]
            audio_base_url = row["audio_base_url"]
            audio_container = row["audio_container"]
        else:
            from database.db import get_db_connection

            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT playlist_mode, audio_base_url, audio_container FROM platform_config WHERE id = ?",
                    (platform_id,),
                )
                row = cursor.fetchone()
            finally:
                conn.close()
            mode, audio_base_url, audio_container = row if row else (None, None, None)
    except Exception as e:
        if postgres_authoritative:
            logger.error(
                "PLAYLIST_CONFIG_POSTGRES_READ_FAILED platform_id=%s "
                "database_backend=%s pipeline_backend=%s error=%s",
                platform_id,
                DATABASE_BACKEND,
                PIPELINE_DATABASE_BACKEND,
                str(e)[:500],
                exc_info=True,
            )
            raise
        logger.warning(f"⚠️ Impossible de lire platform_config SQLite pour la playlist: {e}")
        return playlist

    if mode == "ete":
        bloc = BLOC4_ETE
    else:
        bloc = BLOC4_HIVER

    # Remplacer les items aux positions 9, 10, 11 (index 0-based pour IDs 10, 11, 12)
    playlist[9] = bloc[0]
    playlist[10] = bloc[1]
    playlist[11] = bloc[2]

    # Réécrire les URLs sur le container de la plateforme. Copie des dicts
    # obligatoire : les items BLOC4_* sont des objets module partagés.
    base = _platform_audio_base(audio_base_url, audio_container)
    if base != _AUDIO_BASE:
        playlist = [
            {**item, "filename": f"{base}/{item['filename'].rsplit('/', 1)[-1]}"}
            for item in playlist
        ]

    return playlist


def _clock_label(minute_of_day):
    minute = int(minute_of_day or 0)
    return f"{minute // 60:02d}:{minute % 60:02d}"


def resolve_v2_course_session_manifest(platform_id, occurrence):
    """Resolve and validate the manifest bound to ``occurrence.module_day_id``.

    This function is deliberately fail-closed. Once an occurrence references
    a durable module day, playing the shared V1 playlist would expose content
    from another pedagogical day.
    """

    if not occurrence or occurrence.get("module_day_id") is None:
        raise CourseSessionPlaylistUnavailable(
            "Cette occurrence n'est pas liée à une journée pédagogique V2"
        )
    try:
        module_day_id = int(occurrence["module_day_id"])
    except (TypeError, ValueError) as exc:
        raise CourseSessionPlaylistUnavailable(
            "module_day_id invalide pour cette occurrence"
        ) from exc
    if module_day_id <= 0:
        raise CourseSessionPlaylistUnavailable(
            "module_day_id invalide pour cette occurrence"
        )

    from repositories.pipeline_repository import (
        list_course_folder_ids_for_platform,
    )
    from services.day_playlist_service import (
        build_playlist_items,
        resolve_folder_playlist,
    )
    from services.dynamic_day_schedule_service import compile_day_schedule

    folder_ids = list_course_folder_ids_for_platform(int(platform_id))
    if not folder_ids:
        raise CourseSessionPlaylistUnavailable(
            f"Aucun dossier audio pour la journée durable {module_day_id}"
        )

    session_index = int(occurrence.get("session_index") or 0)
    preferred_index = session_index - 1
    ordered_folder_ids = list(folder_ids)
    if 0 <= preferred_index < len(ordered_folder_ids):
        preferred_folder_id = ordered_folder_ids.pop(preferred_index)
        ordered_folder_ids.insert(0, preferred_folder_id)

    resolution_errors = []
    for folder_id in ordered_folder_ids:
        try:
            resolved = resolve_folder_playlist(int(folder_id))
        except Exception as exc:
            resolution_errors.append(f"dossier {folder_id}: {exc}")
            continue

        if int(resolved.get("schema_version") or 1) != 2:
            continue
        try:
            resolved_module_day_id = int(resolved.get("module_day_id") or 0)
        except (TypeError, ValueError):
            continue
        if resolved_module_day_id != module_day_id:
            continue

        try:
            canonical_day = compile_day_schedule(
                resolved.get("blocks") or []
            )
            expected_items = build_playlist_items(canonical_day["blocks"])
            actual_items = [
                tuple(item)
                for item in (resolved.get("playlist_items") or [])
            ]
            if actual_items != expected_items:
                raise ValueError(
                    "Le manifeste audio ne correspond pas aux blocs verrouillés"
                )
        except Exception as exc:
            raise CourseSessionPlaylistUnavailable(
                f"Manifeste V2 invalide pour la journée durable {module_day_id}: {exc}"
            ) from exc

        return {
            **resolved,
            "folder_id": int(folder_id),
            "module_day_id": module_day_id,
            "blocks": canonical_day["blocks"],
            "playlist_items": expected_items,
        }

    suffix = (
        f" ({'; '.join(resolution_errors[:3])})"
        if resolution_errors
        else ""
    )
    raise CourseSessionPlaylistUnavailable(
        f"Manifeste V2 introuvable pour la journée durable "
        f"{module_day_id}{suffix}"
    )


def get_course_session_playlist(platform_id, occurrence=None):
    """Return the exact playlist owned by one scheduled training day.

    V2 resolves the immutable folder/day manifest. Historic occurrences keep
    the platform summer/winter playlist byte-for-byte.
    """
    if not is_explicit_schedule_occurrence(occurrence):
        return get_playlist(platform_id)
    resolved = resolve_v2_course_session_manifest(platform_id, occurrence)
    blocks_by_key = {
        str(block["block_key"]): block
        for block in resolved["blocks"]
    }
    playlist = []
    for audio_id, item in enumerate(resolved["playlist_items"], start=1):
        filename, duration, file_type, course_index = item
        block_key = str(filename).rsplit("/", 1)[-1].rsplit(".", 1)[0]
        block = blocks_by_key[block_key]
        start_label = _clock_label(block["start_minute"])
        end_label = _clock_label(block["end_minute"])
        if file_type == "cours":
            label = f"Cours {course_index}"
        elif file_type == "qa":
            label = "Questions-réponses"
        elif file_type == "pause_midi":
            label = "Pause déjeuner"
        else:
            label = "Pause"
        playlist.append(
            {
                "id": audio_id,
                "filename": filename,
                "duration": int(duration),
                "title": f"{label} ({start_label}-{end_label})",
                "type": file_type,
                "course_index": int(course_index),
                "block_key": block_key,
                "folder_id": int(resolved["folder_id"]),
                "module_day_id": int(resolved["module_day_id"]),
                "schedule_schema_version": 2,
            }
        )
    return playlist


def _as_france_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return FRANCE_TZ.localize(parsed)
    return parsed.astimezone(FRANCE_TZ)


def _audio_info_for_start(
    platform_id,
    heure_debut_cours,
    *,
    now=None,
    playlist=None,
):
    """Resolve playback from a server-owned occurrence start time."""
    platform_id = int(platform_id or 1)
    heure_debut_cours = _as_france_datetime(heure_debut_cours)
    now = _as_france_datetime(now or get_current_simulated_time(platform_id))

    logger.debug(f"🎵 Heure début: {heure_debut_cours}")
    logger.debug(f"🎵 Heure actuelle: {now}")

    if now < heure_debut_cours:
        temps_restant = int((heure_debut_cours - now).total_seconds())
        logger.debug(
            f"🎵 Cours pas encore commencé, temps restant: {temps_restant}s"
        )
        return None, 0, temps_restant

    temps_ecoule = int((now - heure_debut_cours).total_seconds())
    logger.debug(f"🎵 Temps écoulé depuis début: {temps_ecoule}s")

    if playlist is None:
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


def get_course_session_audio_info(
    platform_id,
    scheduled_at,
    *,
    now=None,
    occurrence=None,
):
    """Resolve one authenticated occurrence without consulting another session."""
    return _audio_info_for_start(
        platform_id,
        scheduled_at,
        now=now,
        playlist=get_course_session_playlist(platform_id, occurrence),
    )


def get_current_audio_info(platform_id=None):
    """
    Détermine quel fichier audio doit être joué et à quelle position.
    Retourne: (audio_info, offset, temps_restant)
    """
    try:
        logger.debug("🎵 Calcul info audio actuel")
        heure_debut_cours = get_heure_debut_cours(platform_id or 1)
        return _audio_info_for_start(platform_id or 1, heure_debut_cours)

    except Exception as e:
        logger.error(f"❌ Erreur dans get_current_audio_info: {e}")
        return None, 0, 0


def _current_v2_occurrence(platform_id, course_start):
    """Return the V2 occurrence represented by the platform course clock.

    ``cours_config`` remains the V1-compatible source of the room clock. When
    that timestamp belongs to a durable module day, playback must switch to
    the immutable occurrence manifest instead of the platform root playlist.
    """
    from repositories.course_schedule_repository import list_course_sessions

    course_start = _as_france_datetime(course_start)
    sessions = list_course_sessions(int(platform_id), limit=1000)
    active_candidate = None
    active_candidate_at = None
    for occurrence in sessions:
        if (
            not is_explicit_schedule_occurrence(occurrence)
            or str(occurrence.get("status") or "").lower() == "cancelled"
        ):
            continue
        try:
            scheduled_at = _as_france_datetime(occurrence.get("scheduled_at"))
        except (TypeError, ValueError):
            continue
        if abs((scheduled_at - course_start).total_seconds()) < 1:
            return occurrence
        if str(occurrence.get("status") or "").lower() == "active":
            if active_candidate_at is None or scheduled_at > active_candidate_at:
                active_candidate = occurrence
                active_candidate_at = scheduled_at
    return active_candidate


def get_current_playback_context(platform_id=None):
    """Resolve the public/debug room state with its authoritative playlist.

    V2 is selected when the current room clock maps to an explicit calendar
    occurrence. Any missing link or corrupt manifest then propagates as an
    error and can never fall back to the V1 root playlist. Platforms without
    such an occurrence keep the historic V1 functions unchanged.
    """
    platform_id = int(platform_id or 1)
    course_start = get_heure_debut_cours(platform_id)
    occurrence = _current_v2_occurrence(platform_id, course_start)
    if occurrence is None:
        audio_info, offset, time_remaining = get_current_audio_info(platform_id)
        return {
            "schedule_schema_version": 1,
            "occurrence": None,
            "playlist": get_playlist(platform_id),
            "course_start": course_start,
            "now": get_current_simulated_time(platform_id),
            "audio_info": audio_info,
            "offset": offset,
            "time_remaining": time_remaining,
        }

    now = get_current_simulated_time(platform_id)
    playlist = get_course_session_playlist(platform_id, occurrence)
    audio_info, offset, time_remaining = _audio_info_for_start(
        platform_id,
        occurrence.get("scheduled_at"),
        now=now,
        playlist=playlist,
    )
    return {
        "schedule_schema_version": 2,
        "occurrence": occurrence,
        "playlist": playlist,
        "course_start": _as_france_datetime(occurrence.get("scheduled_at")),
        "now": _as_france_datetime(now),
        "audio_info": audio_info,
        "offset": offset,
        "time_remaining": time_remaining,
    }
