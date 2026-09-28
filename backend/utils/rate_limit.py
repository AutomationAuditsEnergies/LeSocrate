"""Per-IP rate limits on the authentication endpoints.

The limiter is created per Flask app (not as a module-level singleton) so that
tests building their own app never share counters with each other.  Storage is
in memory: production runs a single gunicorn worker (run_saas.py,
``--workers 1``), so every request of a given IP hits the same counters.
"""

from flask import jsonify, request
from flask_limiter import Limiter
from flask_limiter.errors import RateLimitExceeded


RATE_LIMIT_ERROR = "Trop de tentatives. Réessayez dans quelques minutes."

# endpoint Flask -> limites (syntaxe `limits`, séparées par « ; »)
AUTH_RATE_LIMITS = {
    "auth.login": "10 per minute;50 per hour",
    "auth.supabase_session": "10 per minute;50 per hour",
    "admin.register_admin": "5 per hour",
    "admin.login_admin": "5 per minute;20 per hour",
}


def client_ip():
    """Client address used as the rate-limit key.

    ``request.remote_addr`` is already the real client once ProxyFix has
    processed the trusted proxy hop (see main_app).  Azure App Service may
    forward ``ip:port``; the port changes with each connection, so it is
    dropped to keep one counter per address.
    """
    addr = (request.remote_addr or "").strip()
    if addr.startswith("["):  # [ipv6]:port
        return addr[1:].split("]", 1)[0]
    if addr.count(":") == 1:  # ipv4:port
        return addr.split(":", 1)[0]
    return addr or "unknown"


def _rate_limit_exceeded(_error):
    return jsonify({"success": False, "error": RATE_LIMIT_ERROR}), 429


def init_rate_limiter(app):
    """Attach an in-memory limiter to ``app`` without any global default limit."""
    limiter = Limiter(
        key_func=client_ip,
        app=app,
        storage_uri="memory://",
        default_limits=[],
    )
    app.register_error_handler(RateLimitExceeded, _rate_limit_exceeded)
    return limiter


def apply_auth_rate_limits(app, limiter):
    """Wrap the authentication views registered on ``app`` with their limits."""
    for endpoint, limits in AUTH_RATE_LIMITS.items():
        view = app.view_functions.get(endpoint)
        if view is None:
            raise RuntimeError(f"Route à limiter introuvable : {endpoint}")
        app.view_functions[endpoint] = limiter.limit(limits)(view)
