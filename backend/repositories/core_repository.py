"""Repository for the SaaS core stored in Postgres.

This module intentionally covers only centres, public platforms, students, logs
and commercial orders. Pipeline orchestration/content remains on SQLite for now.
"""
from datetime import datetime

import requests

from config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from database.postgres import get_postgres_connection, postgres_enabled
from utils.logger import get_logger
from utils.slug import slugify

logger = get_logger(__name__)


class DuplicateTrainingCenterUsername(Exception):
    pass


def _supabase_rest_enabled():
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _rest_headers(prefer=None):
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _rest_table_url(table_name):
    return f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table_name}"


def _rest_get_first(table_name, params):
    response = requests.get(
        _rest_table_url(table_name),
        headers=_rest_headers(),
        params={**params, "limit": "1"},
        timeout=12,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def _rest_post_returning(table_name, payload):
    response = requests.post(
        _rest_table_url(table_name),
        headers=_rest_headers("return=representation"),
        json=payload,
        timeout=12,
    )
    if response.status_code == 409:
        raise DuplicateTrainingCenterUsername()
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def _rest_upsert(table_name, payload, on_conflict="id"):
    response = requests.post(
        _rest_table_url(table_name),
        headers=_rest_headers("resolution=merge-duplicates,return=minimal"),
        params={"on_conflict": on_conflict},
        json=payload,
        timeout=12,
    )
    response.raise_for_status()


def _log_pg_fallback(operation, exc):
    logger.warning(
        "⚠️ Postgres direct indisponible pour %s, fallback Supabase REST",
        operation,
        exc_info=exc,
    )


def _bump_named_sequence(conn, table_name, column_name="id"):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence(%s, %s),
                COALESCE((SELECT MAX({column_name}) FROM {table_name}), 1),
                TRUE
            )
            """,
            (table_name, column_name),
        )


def _unique_center_slug(conn, base_slug):
    candidate_base = slugify(base_slug, fallback="centre")
    candidate = candidate_base
    suffix = 2
    with conn.cursor() as cur:
        while True:
            cur.execute(
                "SELECT 1 FROM training_center_accounts WHERE slug = %s LIMIT 1",
                (candidate,),
            )
            if cur.fetchone() is None:
                return candidate
            candidate = f"{candidate_base}-{suffix}"
            suffix += 1


def _unique_center_slug_rest(base_slug):
    candidate_base = slugify(base_slug, fallback="centre")
    candidate = candidate_base
    suffix = 2
    while True:
        row = _rest_get_first(
            "training_center_accounts",
            {"select": "id", "slug": f"eq.{candidate}"},
        )
        if row is None:
            return candidate
        candidate = f"{candidate_base}-{suffix}"
        suffix += 1


def get_training_center_by_username(username):
    if not postgres_enabled() or not username:
        return None
    try:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, password_hash, center_name, slug, is_active, password_debug_plaintext
                    FROM training_center_accounts
                    WHERE username = %s
                    """,
                    (username,),
                )
                return cur.fetchone()
    except Exception as exc:
        if not _supabase_rest_enabled():
            raise
        _log_pg_fallback("get_training_center_by_username", exc)
        return _rest_get_first(
            "training_center_accounts",
            {
                "select": "id,username,password_hash,center_name,slug,is_active,password_debug_plaintext",
                "username": f"eq.{username}",
            },
        )


def get_training_center_by_id(center_id):
    if not postgres_enabled() or not center_id:
        return None
    try:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, center_name, slug, is_active
                    FROM training_center_accounts
                    WHERE id = %s
                    """,
                    (center_id,),
                )
                return cur.fetchone()
    except Exception as exc:
        if not _supabase_rest_enabled():
            raise
        _log_pg_fallback("get_training_center_by_id", exc)
        return _rest_get_first(
            "training_center_accounts",
            {
                "select": "id,username,center_name,slug,is_active",
                "id": f"eq.{center_id}",
            },
        )


def create_training_center(username, password_hash, center_name, slug_base, now=None, password_debug_plaintext=None):
    now = now or datetime.utcnow()
    try:
        with get_postgres_connection() as conn:
            slug = _unique_center_slug(conn, slug_base)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO training_center_accounts
                        (username, password_hash, password_debug_plaintext, center_name, slug, is_active, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s)
                    ON CONFLICT (username) DO NOTHING
                    RETURNING id, username, password_hash, center_name, slug, is_active, password_debug_plaintext
                    """,
                    (username, password_hash, password_debug_plaintext, center_name, slug, now, now),
                )
                row = cur.fetchone()
                if row is None:
                    raise DuplicateTrainingCenterUsername()
                return row
    except DuplicateTrainingCenterUsername:
        raise
    except Exception as exc:
        if not _supabase_rest_enabled():
            raise
        _log_pg_fallback("create_training_center", exc)
        slug = _unique_center_slug_rest(slug_base)
        row = _rest_post_returning(
            "training_center_accounts",
            {
                "username": username,
                "password_hash": password_hash,
                "password_debug_plaintext": password_debug_plaintext,
                "center_name": center_name,
                "slug": slug,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        return row


def update_training_center_password(username, password_hash, password_debug_plaintext=None):
    if not postgres_enabled() or not username:
        return False
    try:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE training_center_accounts
                    SET password_hash = %s,
                        password_debug_plaintext = %s,
                        updated_at = NOW()
                    WHERE username = %s
                    """,
                    (password_hash, password_debug_plaintext, username),
                )
                return cur.rowcount > 0
    except Exception as exc:
        if not _supabase_rest_enabled():
            raise
        _log_pg_fallback("update_training_center_password", exc)
        response = requests.patch(
            _rest_table_url("training_center_accounts"),
            headers=_rest_headers("return=minimal"),
            params={"username": f"eq.{username}"},
            json={
                "password_hash": password_hash,
                "password_debug_plaintext": password_debug_plaintext,
                "updated_at": datetime.utcnow().isoformat(),
            },
            timeout=12,
        )
        response.raise_for_status()
        return True


def resolve_class_access(center_slug, platform_slug):
    if not postgres_enabled():
        return None
    try:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        pc.id,
                        pc.name,
                        pc.slug,
                        COALESCE(tca.slug, 'le-socrate') AS center_slug,
                        COALESCE(tca.center_name, 'Le Socrate') AS center_name,
                        COALESCE(pc.public_access_enabled, TRUE) AS public_access_enabled,
                        COALESCE(pc.status, 'ready') AS status
                    FROM platform_config pc
                    LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
                    WHERE pc.slug = %s
                      AND COALESCE(tca.slug, 'le-socrate') = %s
                    LIMIT 1
                    """,
                    (platform_slug, center_slug),
                )
                return cur.fetchone()
    except Exception as exc:
        if not _supabase_rest_enabled():
            raise
        _log_pg_fallback("resolve_class_access", exc)
        center_name = "Le Socrate"
        center_account_id = None
        if center_slug != "le-socrate":
            center = _rest_get_first(
                "training_center_accounts",
                {"select": "id,slug,center_name", "slug": f"eq.{center_slug}"},
            )
            if not center:
                return None
            center_account_id = center["id"]
            center_name = center["center_name"]
        platform = _rest_get_first(
            "platform_config",
            {
                "select": "id,name,slug,public_access_enabled,status",
                "slug": f"eq.{platform_slug}",
                "center_account_id": f"eq.{center_account_id}" if center_account_id else "is.null",
            },
        )
        if not platform:
            return None
        return {
            "id": platform["id"],
            "name": platform["name"],
            "slug": platform["slug"],
            "center_slug": center_slug,
            "center_name": center_name,
            "public_access_enabled": platform.get("public_access_enabled", True),
            "status": platform.get("status") or "ready",
        }


def get_platform_info(platform_id):
    if not postgres_enabled():
        return None
    try:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, slug
                    FROM platform_config
                    WHERE id = %s
                    """,
                    (platform_id,),
                )
                return cur.fetchone()
    except Exception as exc:
        if not _supabase_rest_enabled():
            raise
        _log_pg_fallback("get_platform_info", exc)
        return _rest_get_first(
            "platform_config",
            {"select": "id,name,slug", "id": f"eq.{platform_id}"},
        )


def upsert_platform_config(platform):
    """Mirror a SQLite platform row into Postgres with the same platform id."""
    try:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO platform_config (
                        id, center_account_id, name, slug, upload_locked,
                        public_access_enabled, pdf_filename, pdf_uploaded_at, updated_at,
                        playlist_mode, audio_container, pdf_container, archive_container,
                        audio_base_url, status, source_formation_id, source_module_id
                    )
                    VALUES (
                        %(id)s, %(center_account_id)s, %(name)s, %(slug)s, %(upload_locked)s,
                        %(public_access_enabled)s, %(pdf_filename)s, %(pdf_uploaded_at)s, %(updated_at)s,
                        %(playlist_mode)s, %(audio_container)s, %(pdf_container)s, %(archive_container)s,
                        %(audio_base_url)s, %(status)s, %(source_formation_id)s, %(source_module_id)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        center_account_id = EXCLUDED.center_account_id,
                        name = EXCLUDED.name,
                        slug = EXCLUDED.slug,
                        upload_locked = EXCLUDED.upload_locked,
                        public_access_enabled = EXCLUDED.public_access_enabled,
                        pdf_filename = EXCLUDED.pdf_filename,
                        pdf_uploaded_at = EXCLUDED.pdf_uploaded_at,
                        updated_at = EXCLUDED.updated_at,
                        playlist_mode = EXCLUDED.playlist_mode,
                        audio_container = EXCLUDED.audio_container,
                        pdf_container = EXCLUDED.pdf_container,
                        archive_container = EXCLUDED.archive_container,
                        audio_base_url = EXCLUDED.audio_base_url,
                        status = EXCLUDED.status,
                        source_formation_id = EXCLUDED.source_formation_id,
                        source_module_id = EXCLUDED.source_module_id
                    """,
                    platform,
                )
            _bump_named_sequence(conn, "platform_config")
    except Exception as exc:
        if not _supabase_rest_enabled():
            raise
        _log_pg_fallback("upsert_platform_config", exc)
        _rest_upsert("platform_config", platform, on_conflict="id")


def upsert_cours_config(cours_config):
    try:
        with get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cours_config (id, platform_id, heure_debut)
                    VALUES (%(id)s, %(platform_id)s, %(heure_debut)s)
                    ON CONFLICT (id) DO UPDATE SET
                        platform_id = EXCLUDED.platform_id,
                        heure_debut = EXCLUDED.heure_debut
                    """,
                    cours_config,
                )
    except Exception as exc:
        if not _supabase_rest_enabled():
            raise
        _log_pg_fallback("upsert_cours_config", exc)
        _rest_upsert("cours_config", cours_config, on_conflict="id")


def get_student_account(platform_id, username):
    if not postgres_enabled() or not username:
        return None
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, password_hash, nom, prenom, is_active
                FROM student_accounts
                WHERE platform_id = %s AND username = %s
                """,
                (platform_id, username),
            )
            return cur.fetchone()


def count_student_accounts(platform_id):
    if not postgres_enabled():
        return 0
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM student_accounts WHERE platform_id = %s",
                (platform_id,),
            )
            row = cur.fetchone()
            return int(row["total"] if row else 0)


def get_student_profile(auth_user_id):
    if not postgres_enabled() or not auth_user_id:
        return None
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT nom, prenom, platform_id, is_active, role, email
                FROM student_profiles
                WHERE auth_user_id = %s
                """,
                (auth_user_id,),
            )
            return cur.fetchone()


def upsert_student_profile(profile):
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO student_profiles
                    (auth_user_id, platform_id, email, nom, prenom, role, is_active, created_at, updated_at)
                VALUES
                    (%(auth_user_id)s, %(platform_id)s, %(email)s, %(nom)s, %(prenom)s,
                     %(role)s, %(is_active)s, %(created_at)s, %(updated_at)s)
                ON CONFLICT (auth_user_id) DO UPDATE SET
                    platform_id = EXCLUDED.platform_id,
                    email = EXCLUDED.email,
                    nom = EXCLUDED.nom,
                    prenom = EXCLUDED.prenom,
                    role = EXCLUDED.role,
                    is_active = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at
                """,
                profile,
            )


def upsert_student_profile_with_id(profile):
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO student_profiles
                    (id, auth_user_id, platform_id, email, nom, prenom, role, is_active, created_at, updated_at)
                VALUES
                    (%(id)s, %(auth_user_id)s, %(platform_id)s, %(email)s, %(nom)s, %(prenom)s,
                     %(role)s, %(is_active)s, %(created_at)s, %(updated_at)s)
                ON CONFLICT (auth_user_id) DO UPDATE SET
                    platform_id = EXCLUDED.platform_id,
                    email = EXCLUDED.email,
                    nom = EXCLUDED.nom,
                    prenom = EXCLUDED.prenom,
                    role = EXCLUDED.role,
                    is_active = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at
                """,
                profile,
            )
        _bump_named_sequence(conn, "student_profiles")


def upsert_log(log_row):
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO logs (id, platform_id, nom, prenom, arrivee, depart)
                VALUES (%(id)s, %(platform_id)s, %(nom)s, %(prenom)s, %(arrivee)s, %(depart)s)
                ON CONFLICT (id) DO UPDATE SET
                    platform_id = EXCLUDED.platform_id,
                    nom = EXCLUDED.nom,
                    prenom = EXCLUDED.prenom,
                    arrivee = EXCLUDED.arrivee,
                    depart = EXCLUDED.depart
                """,
                log_row,
            )
        _bump_named_sequence(conn, "logs")


def update_log_depart(log_id, depart):
    if not postgres_enabled() or not log_id:
        return
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE logs SET depart = %s WHERE id = %s", (depart, log_id))


def create_ai_teacher_order(order):
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_teacher_orders (
                    center_account_id, platform_id, status, training_title,
                    rncp_code, total_hours, quoted_amount_cents, currency,
                    stripe_checkout_session_id, stripe_payment_intent_id
                )
                VALUES (
                    %(center_account_id)s, %(platform_id)s, %(status)s, %(training_title)s,
                    %(rncp_code)s, %(total_hours)s, %(quoted_amount_cents)s, %(currency)s,
                    %(stripe_checkout_session_id)s, %(stripe_payment_intent_id)s
                )
                RETURNING *
                """,
                order,
            )
            return cur.fetchone()


def list_ai_teacher_orders(center_account_id):
    if not postgres_enabled() or not center_account_id:
        return []
    with get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM ai_teacher_orders
                WHERE center_account_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (center_account_id,),
            )
            return cur.fetchall()
