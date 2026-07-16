# video_routes.py --- Routes pour l'API vidéo et cours (JSON uniquement)
from flask import Blueprint, session, jsonify, request, Response
import hmac
import os
import requests as http_requests
import time
from urllib.parse import unquote, urlsplit

import state
from repositories.course_schedule_repository import get_audio_generation_session
from services.audio_service import (
    get_course_session_audio_info,
    get_current_audio_info,
    get_playlist,
)
from services.script_slide_generation_service import get_latest_script_slide_deck_for_audio
from services.platform_storage_service import issue_platform_audio_read_url
from services.time_service import get_heure_debut_cours
from utils.auth_tokens import issue_auth_token, verify_auth_token
from utils.logger import get_logger

logger = get_logger(__name__)

video_bp = Blueprint("video", __name__)
BREAK_AUDIO_TYPES = {"qa", "pause", "pause_midi"}


class StudentCourseAccessError(Exception):
    def __init__(self, status_code=401):
        super().__init__("Accès au cours refusé")
        self.status_code = int(status_code)


def _positive_int(value):
    if value is None or isinstance(value, bool):
        raise ValueError("identifiant invalide")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("identifiant invalide")
    return parsed


def _get_public_platform_id():
    """Select a tenant only for the deliberately non-sensitive public status."""
    raw = request.args.get("platform_id")
    if raw is None:
        raw = request.headers.get("X-Platform-Id")
    if raw is None:
        raw = session.get("platform_id", 1)
    return _positive_int(raw)


def _student_course_context():
    """Authorize one signed student identity against one durable occurrence."""
    required = ("nom", "prenom", "log_id", "platform_id", "course_session_id")
    if any(session.get(key) in (None, "") for key in required):
        raise StudentCourseAccessError(401)

    try:
        platform_id = _positive_int(session.get("platform_id"))
        course_session_id = _positive_int(session.get("course_session_id"))
    except (TypeError, ValueError):
        raise StudentCourseAccessError(401) from None

    # Client hints may help route a request, but can never switch the tenant
    # selected by the signed student session.
    for raw_hint in (
        request.args.get("platform_id"),
        request.headers.get("X-Platform-Id"),
    ):
        if raw_hint is None:
            continue
        try:
            hinted_platform_id = _positive_int(raw_hint)
        except (TypeError, ValueError):
            raise StudentCourseAccessError(403) from None
        if hinted_platform_id != platform_id:
            raise StudentCourseAccessError(403)

    supplied_token = request.headers.get("X-Auth-Token")
    if supplied_token:
        token_user = state.user_tokens.get(supplied_token) or verify_auth_token(
            "student",
            supplied_token,
        )
        if not token_user:
            raise StudentCourseAccessError(401)
        try:
            token_platform_id = _positive_int(token_user.get("platform_id"))
            token_course_session_id = _positive_int(token_user.get("course_session_id"))
        except (TypeError, ValueError):
            raise StudentCourseAccessError(401) from None
        if (
            token_platform_id != platform_id
            or token_course_session_id != course_session_id
            or str(token_user.get("log_id")) != str(session.get("log_id"))
        ):
            raise StudentCourseAccessError(403)

    occurrence = get_audio_generation_session(platform_id, course_session_id)
    if (
        not occurrence
        or int(occurrence.get("platform_id") or 0) != platform_id
        or int(occurrence.get("id") or 0) != course_session_id
    ):
        raise StudentCourseAccessError(403)

    return {
        "platform_id": platform_id,
        "course_session_id": course_session_id,
        "occurrence": occurrence,
        "nom": session.get("nom"),
        "prenom": session.get("prenom"),
    }


def _student_access_error(exc):
    response = jsonify(
        {
            "authenticated": False,
            "error": "Non authentifié" if exc.status_code == 401 else "Accès refusé",
        }
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response, exc.status_code


def _private_json(payload, status_code=200):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "private, no-store"
    return response, status_code


def _student_audio_info(context):
    occurrence = context["occurrence"]
    if str(occurrence.get("status") or "").lower() == "cancelled":
        return None, 0, 0
    return get_course_session_audio_info(
        context["platform_id"],
        occurrence.get("scheduled_at"),
    )


def _safe_audio_key(filename):
    path = unquote(urlsplit(str(filename or "")).path)
    return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def _occurrence_audio_key(context, audio_info):
    """Resolve the immutable blob key owned by this exact occurrence.

    Rows created before occurrence-scoped storage remain compatible with a
    NULL prefix and use the historical root blob. New claims always persist a
    deterministic prefix bound to the session id.
    """
    basename = _safe_audio_key(audio_info.get("filename"))
    if not basename:
        raise RuntimeError("Clé audio absente")
    prefix = str(context["occurrence"].get("audio_storage_prefix") or "").strip("/")
    if not prefix:
        return basename
    expected_prefix = f"course-sessions/{int(context['course_session_id'])}"
    if not hmac.compare_digest(prefix, expected_prefix):
        raise RuntimeError("Préfixe audio de séance incohérent")
    return f"{expected_prefix}/{basename}"


def _issue_audio_stream_ticket(context, audio_info, remaining):
    """Issue a bearer ticket valid only for the current occurrence segment."""
    lifetime = max(1, int(remaining or 0))
    boundary = int(time.time()) + lifetime
    return issue_auth_token(
        "audio_stream",
        {
            "platform_id": context["platform_id"],
            "course_session_id": context["course_session_id"],
            "log_id": session.get("log_id"),
            "audio_id": int(audio_info["id"]),
            "audio_key": _occurrence_audio_key(context, audio_info),
            "boundary": boundary,
            "exp": boundary,
        },
    )


def _audio_stream_ticket_context(raw_ticket):
    """Validate a cookie-independent ticket and re-resolve current server state."""
    payload = verify_auth_token("audio_stream", str(raw_ticket or "").strip())
    if not payload or payload.get("log_id") in (None, ""):
        raise StudentCourseAccessError(401)
    try:
        platform_id = _positive_int(payload.get("platform_id"))
        course_session_id = _positive_int(payload.get("course_session_id"))
        ticket_audio_id = _positive_int(payload.get("audio_id"))
        expires_at = _positive_int(payload.get("exp"))
        boundary = _positive_int(payload.get("boundary"))
    except (TypeError, ValueError):
        raise StudentCourseAccessError(401) from None
    if expires_at != boundary or time.time() >= expires_at:
        raise StudentCourseAccessError(401)

    for raw_hint in (
        request.args.get("platform_id"),
        request.headers.get("X-Platform-Id"),
    ):
        if raw_hint is None:
            continue
        try:
            if _positive_int(raw_hint) != platform_id:
                raise StudentCourseAccessError(403)
        except (TypeError, ValueError):
            raise StudentCourseAccessError(403) from None

    occurrence = get_audio_generation_session(platform_id, course_session_id)
    if (
        not occurrence
        or int(occurrence.get("platform_id") or 0) != platform_id
        or int(occurrence.get("id") or 0) != course_session_id
    ):
        raise StudentCourseAccessError(403)
    context = {
        "platform_id": platform_id,
        "course_session_id": course_session_id,
        "occurrence": occurrence,
        "nom": None,
        "prenom": None,
        "stream_boundary": boundary,
    }
    audio_info, offset, temps_restant = _student_audio_info(context)
    if not audio_info:
        return context, audio_info, offset, temps_restant

    ticket_audio_key = str(payload.get("audio_key") or "")
    current_audio_key = _occurrence_audio_key(context, audio_info)
    if (
        int(audio_info.get("id") or 0) != ticket_audio_id
        or not ticket_audio_key
        or not hmac.compare_digest(ticket_audio_key, current_audio_key)
    ):
        raise StudentCourseAccessError(403)
    return context, audio_info, offset, temps_restant


def _sanitize_deck_audio_references(value):
    if isinstance(value, list):
        return [_sanitize_deck_audio_references(item) for item in value]
    if not isinstance(value, dict):
        return value
    clean = {}
    for key, item in value.items():
        if key == "audio_filename" and isinstance(item, str):
            clean[key] = _safe_audio_key(item)
        elif key == "filename" and isinstance(item, str) and item.lower().split("?", 1)[0].endswith(
            (".mp3", ".wav", ".m4a", ".ogg")
        ):
            clean[key] = _safe_audio_key(item)
        else:
            clean[key] = _sanitize_deck_audio_references(item)
    return clean


def _next_playlist_audio(platform_id, current_audio_id):
    try:
        playlist = get_playlist(platform_id)
        for index, item in enumerate(playlist):
            if item.get("id") == current_audio_id and index + 1 < len(playlist):
                return playlist[index + 1]
    except Exception as exc:
        logger.warning(f"⚠️ Impossible de lire l'audio suivant: {exc}")
    return None


@video_bp.route("/api/video/status")
def video_status():
    """Return the server-timed state of the student's authenticated occurrence."""
    try:
        context = _student_course_context()
        logger.info(
            "🎥 Demande statut vidéo par %s %s P%s occurrence=%s",
            context["nom"],
            context["prenom"],
            context["platform_id"],
            context["course_session_id"],
        )
        audio_info, offset, temps_restant = _student_audio_info(context)

        logger.debug(
            f"🎥 Info audio: {audio_info['title'] if audio_info else 'None'}, offset: {offset}, temps_restant: {temps_restant}"
        )

        # Si le cours n'a pas encore commencé
        if audio_info is None and temps_restant > 0:
            logger.info(f"⏳ Cours pas encore commencé, attente de {temps_restant}s")
            return _private_json(
                {
                    "authenticated": True,
                    "user": {"nom": context["nom"], "prenom": context["prenom"]},
                    "status": "waiting",
                    "heure_debut": str(context["occurrence"].get("scheduled_at") or ""),
                    "temps_restant": max(0, int(temps_restant)),
                }
            )

        # Si le cours est terminé
        if audio_info is None:
            logger.info("🏁 Cours terminé")
            return _private_json(
                {
                    "authenticated": True,
                    "user": {"nom": context["nom"], "prenom": context["prenom"]},
                    "status": "finished",
                    "cours_termine": True,
                }
            )

        # Le cours est en cours
        logger.info(f"▶️ Cours en cours: {audio_info['title']}")
        next_audio = _next_playlist_audio(context["platform_id"], audio_info.get("id"))
        remaining = max(0, int(audio_info.get("duration", 0)) - int(offset or 0))
        result = {
            "authenticated": True,
            "user": {"nom": context["nom"], "prenom": context["prenom"]},
            "status": "playing",
            # Only a non-routable basename is exposed. The storage URL stays server-side.
            "audio_key": _safe_audio_key(audio_info.get("filename")),
            "audio_title": audio_info["title"],
            "audio_id": audio_info["id"],
            "audio_type": audio_info["type"],
            "audio_duration": audio_info.get("duration", 0),
            "offset": offset,
            "remaining": remaining,
            "next_audio_id": next_audio.get("id") if next_audio else None,
            "next_audio_title": next_audio.get("title") if next_audio else None,
            "next_audio_type": next_audio.get("type") if next_audio else None,
            "next_audio_duration": next_audio.get("duration", 0) if next_audio else 0,
            "cours_termine": False,
        }
        if str(audio_info.get("type") or "").lower() not in BREAK_AUDIO_TYPES:
            result["audio_stream_token"] = _issue_audio_stream_ticket(
                context,
                audio_info,
                remaining,
            )
        return _private_json(result)

    except StudentCourseAccessError as exc:
        logger.warning("⚠️ Accès /api/video/status refusé status=%s", exc.status_code)
        return _student_access_error(exc)
    except Exception as e:
        logger.error(f"❌ Erreur API video/status: {e}")
        return _private_json({"success": False, "error": "Erreur serveur"}, 500)


@video_bp.route("/api/video/slides")
def video_slides():
    """Retourne le deck synchronisé avec l'audio actuellement projetable côté cours."""
    try:
        context = _student_course_context()
        audio_info, _offset, temps_restant = _student_audio_info(context)
        if not audio_info:
            if temps_restant > 0:
                return _private_json(
                    {"authenticated": True, "status": "waiting", "message": "Cours non démarré"},
                    425,
                )
            return _private_json(
                {"authenticated": True, "status": "finished", "message": "Cours terminé"},
                410,
            )

        # The client cannot select a filename: the server resolves the current
        # audio from the authenticated occurrence on every request.
        deck = get_latest_script_slide_deck_for_audio(
            audio_info.get("filename"),
            platform_id=context["platform_id"],
        )
        if not deck:
            return _private_json(
                {
                    "authenticated": True,
                    "status": "no_data",
                    "message": "Aucun deck synchronisé pour cet audio",
                }
            )

        return _private_json(
            {
                "authenticated": True,
                "status": "success",
                "audio_sync": _sanitize_deck_audio_references(deck.get("audio_sync") or {}),
                "slides": _sanitize_deck_audio_references(deck.get("slides") or []),
            }
        )

    except StudentCourseAccessError as exc:
        logger.warning("⚠️ Accès /api/video/slides refusé status=%s", exc.status_code)
        return _student_access_error(exc)
    except Exception as e:
        logger.error(f"❌ Erreur API video/slides: {e}")
        return _private_json({"success": False, "error": "Erreur serveur"}, 500)


@video_bp.route("/api/audio/stream")
def audio_stream():
    """Deliver one authorized audio through short SAS redirect or proxy fallback."""
    try:
        stream_ticket = request.args.get("stream_token")
        if stream_ticket:
            context, audio_info, offset, temps_restant = _audio_stream_ticket_context(
                stream_ticket
            )
        else:
            context = _student_course_context()
            audio_info, offset, temps_restant = _student_audio_info(context)
        if not audio_info:
            if temps_restant > 0:
                return _private_json(
                    {"authenticated": True, "error": "Cours non démarré"},
                    425,
                )
            return _private_json(
                {"authenticated": True, "error": "Cours terminé"},
                410,
            )

        if str(audio_info.get("type") or "").lower() in BREAK_AUDIO_TYPES:
            response = Response(status=204)
            response.headers["Cache-Control"] = "private, no-store"
            return response

        audio_key = _occurrence_audio_key(context, audio_info)
        if not audio_key:
            raise RuntimeError("URL audio absente")
        boundary = context.get("stream_boundary")
        if boundary is None:
            remaining = max(
                1,
                int(audio_info.get("duration") or 0) - int(offset or 0),
            )
            boundary = int(time.time()) + remaining
        signed_blob_url = issue_platform_audio_read_url(
            context["platform_id"],
            audio_key,
            expires_at=int(boundary),
        )

        delivery_mode = (
            os.environ.get("STUDENT_AUDIO_DELIVERY_MODE", "redirect_sas")
            .strip()
            .lower()
        )
        if delivery_mode not in {"redirect_sas", "proxy"}:
            raise RuntimeError("STUDENT_AUDIO_DELIVERY_MODE invalide")
        if delivery_mode == "redirect_sas":
            response = Response(status=302)
            response.headers.update(
                {
                    "Location": signed_blob_url,
                    "Cache-Control": "private, no-store",
                    "Pragma": "no-cache",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                }
            )
            return response

        range_header = request.headers.get("Range")

        # Transférer la requête Range à Azure (server-to-server, pas de CORS)
        headers = {}
        if range_header:
            headers["Range"] = range_header

        resp = http_requests.get(
            signed_blob_url,
            headers=headers,
            stream=True,
            timeout=(5, 30),
            allow_redirects=False,
        )
        if resp.status_code not in {200, 206}:
            resp.close()
            logger.error(
                "AUDIO_STORAGE_RESPONSE_FAILED platform_id=%s occurrence=%s status=%s",
                context["platform_id"],
                context["course_session_id"],
                resp.status_code,
            )
            return _private_json({"error": "Audio indisponible"}, 502)

        # Construire les headers de la réponse
        response_headers = {
            "Content-Type": "audio/mpeg",
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        }
        if resp.headers.get("Content-Length"):
            response_headers["Content-Length"] = resp.headers["Content-Length"]
        if resp.headers.get("Content-Range"):
            response_headers["Content-Range"] = resp.headers["Content-Range"]

        def stream_chunks():
            try:
                yield from resp.iter_content(chunk_size=8192)
            finally:
                resp.close()

        return Response(
            stream_chunks(),
            status=resp.status_code,
            headers=response_headers,
        )

    except StudentCourseAccessError as exc:
        logger.warning("⚠️ Accès /api/audio/stream refusé status=%s", exc.status_code)
        return _student_access_error(exc)
    except Exception as e:
        logger.error(f"❌ Erreur proxy audio: {e}")
        return _private_json({"error": "Erreur serveur"}, 500)


@video_bp.route("/api/cours-status")
def cours_status():
    """API endpoint pour obtenir l'état actuel du cours (sans authentification requise)"""
    try:
        logger.debug("📊 Demande statut cours")

        platform_id = _get_public_platform_id()
        audio_info, offset, temps_restant = get_current_audio_info(platform_id)

        if audio_info is None and temps_restant > 0:
            heure_debut_cours = get_heure_debut_cours(platform_id)
            result = {
                "status": "waiting",
                "temps_restant": temps_restant,
                "heure_debut": heure_debut_cours.strftime("%H:%M"),
            }
        elif audio_info is None:
            result = {"status": "finished"}
        else:
            # Public callers only need the coarse room state. Audio/deck
            # metadata is occurrence-bound and available through authenticated APIs.
            result = {"status": "playing"}

        logger.debug(f"📊 Statut cours: {result['status']}")
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Plateforme invalide"}), 400
    except Exception as e:
        logger.error(f"❌ Erreur API cours-status: {e}")
        return jsonify({"status": "error", "message": "Erreur serveur"}), 500


@video_bp.route("/api/intro")
def intro():
    """Retourne les informations pour la page d'introduction"""
    try:
        context = _student_course_context()
        nom = context["nom"]
        prenom = context["prenom"]
        logger.info(f"📺 Demande page intro par {nom} {prenom}")

        return _private_json(
            {
                "authenticated": True,
                "user": {"nom": nom, "prenom": prenom},
                "message": "Page d'introduction",
            }
        )

    except StudentCourseAccessError as exc:
        return _student_access_error(exc)
    except Exception as e:
        logger.error(f"❌ Erreur API intro: {e}")
        return _private_json({"success": False, "error": "Erreur serveur"}, 500)
