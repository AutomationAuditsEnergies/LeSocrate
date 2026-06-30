"""Postgres access helpers for the SaaS core.

SQLite still powers the historical course pipeline. These helpers are only for
the multi-tenant SaaS tables that are being moved to Supabase/Postgres first.
"""
from contextlib import contextmanager

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


@contextmanager
def get_postgres_connection():
    require_postgres()
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        yield conn
