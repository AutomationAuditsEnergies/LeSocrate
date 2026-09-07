"""Single browser CORS contract shared by the API runtime and tests."""

from flask_cors import CORS


API_CORS_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
API_CORS_HEADERS = (
    "Content-Type",
    "Authorization",
    "X-Auth-Token",
    "X-Platform-Id",
    "X-Internal-Secret",
    "Idempotency-Key",
    "Range",
)
API_CORS_EXPOSE_HEADERS = (
    "Accept-Ranges",
    "Content-Length",
    "Content-Range",
    "Content-Disposition",
)


def configure_api_cors(app, origins):
    """Configure cross-origin browser access for every supported API verb."""
    return CORS(
        app,
        resources={
            r"/*": {
                "origins": list(origins),
                "methods": list(API_CORS_METHODS),
                "allow_headers": list(API_CORS_HEADERS),
                "expose_headers": list(API_CORS_EXPOSE_HEADERS),
                "supports_credentials": True,
            }
        },
    )
