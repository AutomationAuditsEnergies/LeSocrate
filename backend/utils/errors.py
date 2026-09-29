"""Réponse JSON commune pour les erreurs internes de l'API.

Le texte de l'exception (noms de tables, chemins, détails SQL) ne quitte jamais
le serveur : il part dans les logs avec un identifiant court, et le navigateur
ne reçoit que cet identifiant, à citer au support.
"""

from uuid import uuid4

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from utils.logger import get_logger

logger = get_logger(__name__)


def internal_error_response(exc, context=""):
    error_id = uuid4().hex[:8]
    logger.exception(
        "INTERNAL_ERROR error_id=%s context=%s",
        error_id,
        context or "-",
        exc_info=exc,
    )
    return jsonify({
        "success": False,
        "error": (
            "Une erreur interne est survenue. Réessayez ou contactez le support "
            f"(réf. {error_id})."
        ),
        "error_id": error_id,
    }), 500


def register_api_error_handler(app):
    """Gestionnaire global des exceptions non prévues sur ``app``.

    - Les HTTPException (404, 405, 429…) gardent leur réponse habituelle ; un
      gestionnaire plus précis (ex. RateLimitExceeded) reste prioritaire.
    - Sous ``/api/`` : réponse JSON avec un identifiant, détail dans les logs.
    - Ailleurs : comportement Flask par défaut, inchangé.
    """

    @app.errorhandler(Exception)
    def _handle_unexpected_exception(exc):
        if isinstance(exc, HTTPException):
            return exc
        if not request.path.startswith("/api/"):
            raise exc
        return internal_error_response(exc, context=f"{request.method} {request.path}")

    return _handle_unexpected_exception
