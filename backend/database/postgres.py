"""Postgres access helpers for the SaaS core.

SQLite still powers the historical course pipeline. These helpers are only for
the multi-tenant SaaS tables that are being moved to Supabase/Postgres first.
"""
from contextlib import contextmanager
from functools import lru_cache
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config import DATABASE_BACKEND, DATABASE_URL

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - local env may still be SQLite-only.
    psycopg = None
    dict_row = None


POSTGRES_BACKENDS = {"postgres", "postgres_core", "hybrid", "supabase"}


def postgres_enabled():
    return bool(DATABASE_URL) and DATABASE_BACKEND in POSTGRES_BACKENDS


def require_postgres():
    if not postgres_enabled():
        raise RuntimeError("Postgres n'est pas activé (DATABASE_BACKEND/DATABASE_URL).")
    if psycopg is None:
        raise RuntimeError("psycopg n'est pas installé. Lancez: pip install -r requirements.txt")


@lru_cache(maxsize=1)
def _connection_url() -> str:
    """Prefer IPv4 when the platform cannot open IPv6 outbound sockets."""
    if not DATABASE_URL:
        return DATABASE_URL

    parts = urlsplit(DATABASE_URL)
    if parts.scheme not in {"postgres", "postgresql"} or not parts.hostname:
        return DATABASE_URL

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if query.get("hostaddr"):
        return DATABASE_URL

    try:
        infos = socket.getaddrinfo(
            parts.hostname,
            parts.port or 5432,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        return DATABASE_URL

    if not infos:
        return DATABASE_URL

    query["hostaddr"] = infos[0][4][0]
    if "connect_timeout" not in query:
        query["connect_timeout"] = "10"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@contextmanager
def get_postgres_connection():
    require_postgres()
    with psycopg.connect(_connection_url(), row_factory=dict_row) as conn:
        yield conn
