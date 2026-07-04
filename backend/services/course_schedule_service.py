import json
import os
import secrets
import smtplib
import imaplib
import time as time_module
from datetime import datetime, time, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid

import requests as http_requests

from config import FRANCE_TZ
from database.db import get_db_connection
from utils.logger import get_logger

logger = get_logger(__name__)

WEEKDAY_IDS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}

SESSION_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def ensure_course_schedule_tables(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_schedule_config (
            platform_id INTEGER PRIMARY KEY,
            total_training_days INTEGER NOT NULL,
            weekly_course_count INTEGER NOT NULL,
            weekdays_json TEXT NOT NULL,
            start_time TEXT NOT NULL DEFAULT '09:00',
            timezone TEXT NOT NULL DEFAULT 'Europe/Paris',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS course_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            session_index INTEGER NOT NULL,
            scheduled_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            activated_at TEXT,
            completed_at TEXT,
            reminder_previous_evening_sent_at TEXT,
            reminder_5min_sent_at TEXT,
            session_password TEXT,
            session_password_generated_at TEXT,
            audio_generation_status TEXT DEFAULT 'pending',
            audio_generation_started_at TEXT,
            audio_generation_completed_at TEXT,
            audio_generation_error TEXT,
            audio_job_id INTEGER,
            audio_folder_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(platform_id, session_index)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_sessions_platform_scheduled ON course_sessions(platform_id, scheduled_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_course_sessions_status_scheduled ON course_sessions(status, scheduled_at)"
    )
    cursor.execute("PRAGMA table_info(course_sessions)")
    columns = [col[1] for col in cursor.fetchall()]
    for col, col_type in {
        "session_password": "TEXT",
        "session_password_generated_at": "TEXT",
        "audio_generation_status": "TEXT DEFAULT 'pending'",
        "audio_generation_started_at": "TEXT",
        "audio_generation_completed_at": "TEXT",
        "audio_generation_error": "TEXT",
        "audio_job_id": "INTEGER",
        "audio_folder_id": "INTEGER",
    }.items():
        if col not in columns:
            cursor.execute(f"ALTER TABLE course_sessions ADD COLUMN {col} {col_type}")


def _generate_session_password():
    length = int(os.environ.get("COURSE_SESSION_PASSWORD_LENGTH", "6"))
    length = max(4, min(length, 16))
    return "".join(secrets.choice(SESSION_PASSWORD_ALPHABET) for _ in range(length))


def _ensure_session_password(cursor, session_id, now_str=None):
    cursor.execute(
        "SELECT session_password FROM course_sessions WHERE id = ?",
        (session_id,),
    )
    row = cursor.fetchone()
    if row and row[0]:
        return row[0]

    generated_at = now_str or _now_str()
    password = _generate_session_password()
    cursor.execute(
        """
        UPDATE course_sessions
        SET session_password = ?,
            session_password_generated_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (password, generated_at, generated_at, session_id),
    )
    return password


def _now_str():
    return datetime.now(FRANCE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _parse_start_time(value):
    raw = str(value or "09:00").strip()
    try:
        hour, minute = raw.split(":", 1)
        return time(int(hour), int(minute[:2]))
    except Exception:
        raise ValueError("start_time invalide, format attendu HH:MM")


def _normalize_weekdays(weekdays, weekly_course_count=None):
    result = []
    for item in weekdays or []:
        key = str(item).strip().lower()
        if key in WEEKDAY_IDS:
            result.append(WEEKDAY_IDS[key])
            continue
        try:
            value = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"Jour de cours invalide: {item}")
        if value < 0 or value > 6:
            raise ValueError(f"Jour de cours invalide: {item}")
        result.append(value)

    ordered = sorted(set(result))
    if not ordered:
        raise ValueError("Au moins un jour de cours est requis")
    if weekly_course_count and int(weekly_course_count) != len(ordered):
        raise ValueError("Le nombre de cours par semaine doit correspondre aux jours sélectionnés")
    return ordered


def _audio_schedule_window_hours():
    horizon = float(os.environ.get("SCHEDULED_AUDIO_HORIZON_HOURS", "24"))
    late_grace = float(os.environ.get("SCHEDULED_AUDIO_LATE_GRACE_HOURS", "2"))
    return horizon, late_grace


def _format_session_for_error(scheduled_at):
    try:
        dt = _parse_local_datetime(str(scheduled_at))
        return dt.strftime("%d/%m/%Y à %H:%M")
    except Exception:
        return str(scheduled_at or "prochaine séance")


def _find_schedule_update_lock(cursor, platform_id):
    """Bloque une modification qui pourrait déplacer une génération audio proche."""
    ensure_course_schedule_tables(cursor)
    horizon, late_grace = _audio_schedule_window_hours()
    now = datetime.now(FRANCE_TZ)
    lower_bound = (now - timedelta(hours=late_grace)).strftime("%Y-%m-%d %H:%M:%S")
    upper_bound = (now + timedelta(hours=horizon)).strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        SELECT scheduled_at, audio_generation_status, audio_generation_started_at, audio_generation_completed_at
        FROM course_sessions
        WHERE platform_id = ?
          AND status IN ('planned', 'active')
          AND (
            scheduled_at BETWEEN ? AND ?
            OR (
              audio_generation_started_at IS NOT NULL
              AND audio_generation_completed_at IS NULL
            )
            OR COALESCE(audio_generation_status, 'pending') IN ('queued', 'running', 'processing')
          )
        ORDER BY scheduled_at ASC
        LIMIT 1
        """,
        (platform_id, lower_bound, upper_bound),
    )
    row = cursor.fetchone()
    if not row:
        return None

    scheduled_at, audio_status, audio_started_at, audio_completed_at = row
    return {
        "scheduled_at": scheduled_at,
        "audio_generation_status": audio_status,
        "audio_generation_started_at": audio_started_at,
        "audio_generation_completed_at": audio_completed_at,
        "horizon_hours": horizon,
        "late_grace_hours": late_grace,
    }


def _assert_schedule_can_be_changed(cursor, platform_id):
    lock = _find_schedule_update_lock(cursor, platform_id)
    if not lock:
        return
    session_label = _format_session_for_error(lock.get("scheduled_at"))
    horizon = int(lock.get("horizon_hours") or 24)
    raise ValueError(
        f"Planning verrouillé: une journée est prévue le {session_label}. "
        f"Le planning ne peut plus être modifié dans les {horizon}h avant une séance, "
        "car l'audio peut être préparé automatiquement."
    )


def _assert_requested_sessions_are_not_due_soon(sessions):
    if not sessions:
        return
    horizon, late_grace = _audio_schedule_window_hours()
    now = datetime.now(FRANCE_TZ)
    lower_bound = now - timedelta(hours=late_grace)
    upper_bound = now + timedelta(hours=horizon)
    first_session = sessions[0]
    if lower_bound <= first_session <= upper_bound:
        session_label = first_session.strftime("%d/%m/%Y à %H:%M")
        raise ValueError(
            f"Planning refusé: la nouvelle prochaine journée tomberait le {session_label}. "
            f"Choisissez un planning dont la prochaine journée est à plus de {int(horizon)}h, "
            "pour laisser le temps à l'audio de se préparer."
        )


def _generate_session_datetimes(total_training_days, weekdays, start_time, start_date=None):
    total = int(total_training_days)
    if total <= 0:
        raise ValueError("total_training_days doit être positif")

    course_time = _parse_start_time(start_time)
    now = datetime.now(FRANCE_TZ)
    if start_date:
        cursor_date = datetime.strptime(str(start_date), "%Y-%m-%d").date()
    else:
        cursor_date = now.date()

    sessions = []
    max_days = total * 14 + 370
    for _ in range(max_days):
        if cursor_date.weekday() in weekdays:
            scheduled = FRANCE_TZ.localize(datetime.combine(cursor_date, course_time))
            if scheduled > now:
                sessions.append(scheduled)
                if len(sessions) >= total:
                    break
        cursor_date += timedelta(days=1)

    if len(sessions) < total:
        raise ValueError("Impossible de générer toutes les séances demandées")
    return sessions


def save_course_schedule(cursor, platform_id, schedule):
    ensure_course_schedule_tables(cursor)

    schedule = schedule or {}
    total_training_days = int(schedule.get("total_training_days") or 0)
    weekly_course_count = int(schedule.get("weekly_course_count") or 0)
    weekdays = _normalize_weekdays(schedule.get("weekdays"), weekly_course_count)
    start_time = str(schedule.get("start_time") or "09:00").strip()
    start_date = schedule.get("start_date") or None

    sessions = _generate_session_datetimes(
        total_training_days=total_training_days,
        weekdays=weekdays,
        start_time=start_time,
        start_date=start_date,
    )
    now = _now_str()
    weekdays_json = json.dumps(weekdays)

    cursor.execute(
        """
        INSERT INTO course_schedule_config (
            platform_id, total_training_days, weekly_course_count, weekdays_json,
            start_time, timezone, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'Europe/Paris', ?, ?)
        ON CONFLICT(platform_id) DO UPDATE SET
            total_training_days = excluded.total_training_days,
            weekly_course_count = excluded.weekly_course_count,
            weekdays_json = excluded.weekdays_json,
            start_time = excluded.start_time,
            timezone = excluded.timezone,
            updated_at = excluded.updated_at
        """,
        (platform_id, total_training_days, weekly_course_count, weekdays_json, start_time, now, now),
    )
    cursor.execute("DELETE FROM course_sessions WHERE platform_id = ?", (platform_id,))
    for index, scheduled in enumerate(sessions, start=1):
        session_password = _generate_session_password()
        cursor.execute(
            """
            INSERT INTO course_sessions (
                platform_id, session_index, scheduled_at, status,
                session_password, session_password_generated_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 'planned', ?, ?, ?, ?)
            """,
            (
                platform_id,
                index,
                scheduled.strftime("%Y-%m-%d %H:%M:%S"),
                session_password,
                now,
                now,
                now,
            ),
        )
    return {
        "total_sessions": len(sessions),
        "first_session_at": sessions[0].strftime("%Y-%m-%d %H:%M:%S") if sessions else None,
        "last_session_at": sessions[-1].strftime("%Y-%m-%d %H:%M:%S") if sessions else None,
    }


def get_course_schedule_summary(cursor, platform_id):
    ensure_course_schedule_tables(cursor)
    cursor.execute(
        """
        SELECT total_training_days, weekly_course_count, weekdays_json, start_time, timezone
        FROM course_schedule_config
        WHERE platform_id = ?
        """,
        (platform_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    total_training_days, weekly_course_count, weekdays_json, start_time, timezone_name = row
    try:
        weekdays = json.loads(weekdays_json or "[]")
    except Exception:
        weekdays = []
    cursor.execute(
        """
        SELECT scheduled_at
        FROM course_sessions
        WHERE platform_id = ?
          AND status IN ('planned', 'active')
        ORDER BY scheduled_at ASC
        LIMIT 1
        """,
        (platform_id,),
    )
    next_row = cursor.fetchone()
    cursor.execute(
        """
        SELECT scheduled_at
        FROM course_sessions
        WHERE platform_id = ?
        ORDER BY session_index DESC
        LIMIT 1
        """,
        (platform_id,),
    )
    last_row = cursor.fetchone()
    return {
        "total_training_days": total_training_days,
        "weekly_course_count": weekly_course_count,
        "weekdays": weekdays,
        "start_time": start_time,
        "timezone": timezone_name,
        "next_session_at": next_row[0] if next_row else None,
        "last_session_at": last_row[0] if last_row else None,
    }


def update_course_schedule_start_time(cursor, platform_id, start_time):
    return update_course_schedule(cursor, platform_id, start_time=start_time)


def update_course_schedule(cursor, platform_id, start_time=None, weekdays=None):
    ensure_course_schedule_tables(cursor)
    summary = get_course_schedule_summary(cursor, platform_id)
    if not summary:
        return None

    requested_start_time = str(start_time or summary["start_time"] or "09:00").strip()
    requested_weekdays = (
        _normalize_weekdays(weekdays, summary["weekly_course_count"])
        if weekdays is not None
        else _normalize_weekdays(summary["weekdays"], summary["weekly_course_count"])
    )
    current_weekdays = _normalize_weekdays(summary["weekdays"], summary["weekly_course_count"])

    if requested_start_time == summary.get("start_time") and requested_weekdays == current_weekdays:
        return {
            **summary,
            "total_sessions": summary["total_training_days"],
            "first_session_at": summary.get("next_session_at"),
            "last_session_at": summary.get("last_session_at"),
            "start_time": requested_start_time,
            "weekdays": requested_weekdays,
        }

    _assert_schedule_can_be_changed(cursor, platform_id)
    requested_sessions = _generate_session_datetimes(
        total_training_days=summary["total_training_days"],
        weekdays=requested_weekdays,
        start_time=requested_start_time,
    )
    _assert_requested_sessions_are_not_due_soon(requested_sessions)

    result = save_course_schedule(
        cursor,
        platform_id,
        {
            "total_training_days": summary["total_training_days"],
            "weekly_course_count": summary["weekly_course_count"],
            "weekdays": requested_weekdays,
            "start_time": requested_start_time,
        },
    )
    if result.get("first_session_at"):
        _upsert_course_time(cursor, platform_id, result["first_session_at"])
    return {**summary, **result, "start_time": requested_start_time, "weekdays": requested_weekdays}


def create_course_schedule(platform_id, schedule):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        result = save_course_schedule(cursor, platform_id, schedule)
        conn.commit()
        return result
    finally:
        conn.close()


def _parse_local_datetime(value):
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return FRANCE_TZ.localize(dt)


def _upsert_course_time(cursor, platform_id, scheduled_at):
    cursor.execute(
        "UPDATE cours_config SET heure_debut = ? WHERE platform_id = ?",
        (scheduled_at, platform_id),
    )
    if cursor.rowcount == 0:
        cursor.execute(
            "INSERT INTO cours_config (id, heure_debut, platform_id) VALUES (?, ?, ?)",
            (platform_id, scheduled_at, platform_id),
        )


def advance_platform_schedule(cursor, platform_id, now=None):
    ensure_course_schedule_tables(cursor)
    now = now or datetime.now(FRANCE_TZ)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    active_hours = float(os.environ.get("COURSE_SESSION_ACTIVE_HOURS", "12"))
    stale_before = (now - timedelta(hours=active_hours)).strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        UPDATE course_sessions
        SET status = 'completed', completed_at = ?, updated_at = ?
        WHERE platform_id = ?
          AND status IN ('planned', 'active')
          AND scheduled_at < ?
        """,
        (now_str, now_str, platform_id, stale_before),
    )

    cursor.execute(
        """
        SELECT id, scheduled_at
        FROM course_sessions
        WHERE platform_id = ?
          AND status IN ('planned', 'active')
          AND scheduled_at <= ?
          AND scheduled_at >= ?
        ORDER BY scheduled_at DESC
        LIMIT 1
        """,
        (platform_id, now_str, stale_before),
    )
    row = cursor.fetchone()
    if row:
        session_id, scheduled_at = row
        cursor.execute(
            """
            UPDATE course_sessions
            SET status = 'active',
                activated_at = COALESCE(activated_at, ?),
                updated_at = ?
            WHERE id = ?
            """,
            (now_str, now_str, session_id),
        )
        _upsert_course_time(cursor, platform_id, scheduled_at)
        return {"platform_id": platform_id, "session_id": session_id, "status": "active", "scheduled_at": scheduled_at}

    cursor.execute(
        """
        SELECT id, scheduled_at
        FROM course_sessions
        WHERE platform_id = ?
          AND status = 'planned'
          AND scheduled_at > ?
        ORDER BY scheduled_at ASC
        LIMIT 1
        """,
        (platform_id, now_str),
    )
    row = cursor.fetchone()
    if row:
        session_id, scheduled_at = row
        _upsert_course_time(cursor, platform_id, scheduled_at)
        return {"platform_id": platform_id, "session_id": session_id, "status": "scheduled", "scheduled_at": scheduled_at}

    return {"platform_id": platform_id, "status": "empty"}


def run_scheduler_tick(platform_ids=None):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        ensure_course_schedule_tables(cursor)
        if platform_ids:
            ids = [int(pid) for pid in platform_ids]
        else:
            cursor.execute("SELECT platform_id FROM course_schedule_config ORDER BY platform_id")
            ids = [row[0] for row in cursor.fetchall()]

        results = [advance_platform_schedule(cursor, pid) for pid in ids]
        conn.commit()
        return results
    finally:
        conn.close()


def _platform_class_url(cursor, platform_id, base_url=None):
    cursor.execute(
        """
        SELECT pc.slug, COALESCE(tca.slug, 'le-socrate')
        FROM platform_config pc
        LEFT JOIN training_center_accounts tca ON tca.id = pc.center_account_id
        WHERE pc.id = ?
        """,
        (platform_id,),
    )
    row = cursor.fetchone()
    if not row:
        return ""
    platform_slug, center_slug = row
    path = f"/classe/{center_slug or 'le-socrate'}/{platform_slug}"
    return f"{str(base_url).rstrip('/')}{path}" if base_url else path


def _student_recipients(cursor, platform_id):
    recipients = {}
    try:
        ensure_course_schedule_tables(cursor)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS course_reminder_recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(platform_id, email)
            )
            """
        )
        cursor.execute(
            """
            SELECT email
            FROM course_reminder_recipients
            WHERE platform_id = ?
            ORDER BY email COLLATE NOCASE
            """,
            (platform_id,),
        )
        for (email,) in cursor.fetchall():
            email = str(email or "").strip().lower()
            if email:
                recipients[email] = {"email": email, "nom": "", "prenom": ""}
    except Exception as exc:
        logger.warning("⚠️ Lecture course_reminder_recipients impossible: %s", exc)

    cursor.execute(
        """
        SELECT email, nom, prenom
        FROM student_profiles
        WHERE platform_id = ? AND COALESCE(is_active, 1) = 1 AND email IS NOT NULL
        """,
        (platform_id,),
    )
    for email, nom, prenom in cursor.fetchall():
        email = str(email or "").strip().lower()
        if email:
            recipients[email] = {"email": email, "nom": nom or "", "prenom": prenom or ""}

    cursor.execute(
        """
        SELECT username, nom, prenom
        FROM student_accounts
        WHERE platform_id = ? AND COALESCE(is_active, 1) = 1 AND username LIKE '%@%'
        """,
        (platform_id,),
    )
    for email, nom, prenom in cursor.fetchall():
        email = str(email or "").strip().lower()
        if email and email not in recipients:
            recipients[email] = {"email": email, "nom": nom or "", "prenom": prenom or ""}
    return list(recipients.values())


def _post_reminder_webhook(payload):
    webhook_url = os.environ.get("REMINDER_WEBHOOK_URL")
    if not webhook_url:
        return False, "REMINDER_WEBHOOK_URL non configuré"

    headers = {"Content-Type": "application/json"}
    webhook_key = os.environ.get("REMINDER_WEBHOOK_KEY")
    if webhook_key:
        headers["X-Reminder-Key"] = webhook_key

    response = http_requests.post(webhook_url, json=payload, headers=headers, timeout=20)
    if response.status_code >= 400:
        return False, f"Webhook rappel HTTP {response.status_code}: {response.text[:300]}"
    return True, None


def _email_configured():
    return bool(os.environ.get("EMAIL_USERNAME") and os.environ.get("EMAIL_PASSWORD"))


def _reminder_subject(reminder_type):
    if reminder_type == "five_minutes_before":
        return "Le cours commence dans 5 minutes !"
    return "Votre formation commence demain"


def _reminder_html(payload):
    reminder_type = payload.get("type")
    class_url = payload.get("class_url") or "#"
    scheduled_at = payload.get("scheduled_at") or ""
    session_password = str(
        payload.get("session_password") or os.environ.get("COURSE_SESSION_PASSWORD", "")
    ).strip()
    password_line = (
        f'<div class="meta">Mot de passe de session : <strong>{session_password}</strong></div>'
        if session_password
        else ""
    )
    try:
        scheduled = _parse_local_datetime(scheduled_at)
        date_label = scheduled.strftime("%d/%m/%Y")
        time_label = scheduled.strftime("%H:%M")
    except Exception:
        date_label = "demain"
        time_label = "09:00"

    if reminder_type == "five_minutes_before":
        headline = "C'est parti !"
        body = (
            f"Votre cours démarre dans 5 minutes, à {time_label}. "
            "Connectez-vous maintenant à la plateforme pour ne rien manquer."
        )
        button = "Se connecter maintenant"
        closing = "On vous attend !"
    else:
        headline = "Votre formation commence demain"
        body = (
            f"Votre prochaine journée de formation aura lieu le {date_label} à {time_label}. "
            "Connectez-vous quelques minutes avant le début avec le lien ci-dessous."
        )
        button = "Accéder à la formation"
        closing = "À demain et bonne soirée."

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{ margin:0; padding:0; background:#f6f7fb; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif; color:#0f172a; }}
    .wrap {{ max-width:680px; margin:0 auto; padding:28px 18px; }}
    .header {{ background:linear-gradient(135deg,#5b4bff,#8b5cf6); color:#fff; padding:34px 36px; border-radius:18px 18px 0 0; }}
    .brand {{ font-size:24px; font-weight:800; margin:0; }}
    .card {{ background:#fff; padding:38px 36px; border:1px solid #e2e8f0; border-top:0; border-radius:0 0 18px 18px; box-shadow:0 12px 32px rgba(15,23,42,.08); }}
    h1 {{ font-size:30px; line-height:1.15; margin:0 0 20px; color:#111827; }}
    p {{ font-size:16px; line-height:1.65; margin:0 0 22px; color:#334155; }}
    .cta {{ display:inline-block; background:#8b5cf6; color:#fff !important; text-decoration:none; padding:15px 24px; border-radius:12px; font-weight:700; }}
    .meta {{ margin-top:26px; padding:14px 16px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; font-size:14px; color:#64748b; }}
    .footer {{ text-align:center; color:#94a3b8; font-size:12px; margin-top:18px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header"><p class="brand">Le Socrate</p></div>
    <div class="card">
      <h1>{headline}</h1>
      <p>Bonjour,</p>
      <p>{body}</p>
      <p><a class="cta" href="{class_url}" target="_blank">{button}</a></p>
      <div class="meta">Horaire prévu : {date_label} à {time_label}</div>
      {password_line}
      <p style="margin-top:26px;">{closing}</p>
      <p>L'équipe Le Socrate</p>
    </div>
    <div class="footer">Email automatique de rappel de formation.</div>
  </div>
</body>
</html>"""


def _send_reminder_emails(payload):
    if not _email_configured():
        return False, "EMAIL_USERNAME/EMAIL_PASSWORD non configurés"

    recipients = payload.get("recipients") or []
    if not recipients:
        return True, None

    smtp_server = os.environ.get("SMTP_SERVER", "mail.infomaniak.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    imap_server = os.environ.get("IMAP_SERVER", "mail.infomaniak.com")
    imap_port = int(os.environ.get("IMAP_PORT", "993"))
    username = os.environ.get("EMAIL_USERNAME")
    password = os.environ.get("EMAIL_PASSWORD")
    sender = os.environ.get("EMAIL_FROM") or username
    sender_name = os.environ.get("EMAIL_FROM_NAME", "Le Socrate")
    subject = _reminder_subject(payload.get("type"))
    html = _reminder_html(payload)

    errors = []
    for recipient in recipients:
        receiver = (recipient.get("email") if isinstance(recipient, dict) else recipient) or ""
        receiver = str(receiver).strip()
        if not receiver:
            continue

        try:
            msg = MIMEMultipart("alternative")
            msg["Message-ID"] = make_msgid()
            msg["Subject"] = subject
            msg["From"] = f"{sender_name} <{sender}>"
            msg["To"] = receiver
            msg.attach(MIMEText(html, "html", "utf-8"))
            raw_message = msg.as_string()

            with smtplib.SMTP_SSL(smtp_server, smtp_port) as smtp:
                smtp.login(username, password)
                smtp.sendmail(sender, receiver, raw_message)

            if os.environ.get("EMAIL_COPY_TO_SENT", "1") != "0":
                with imaplib.IMAP4_SSL(imap_server, imap_port) as imap:
                    imap.login(username, password)
                    imap.append(
                        '"Sent"',
                        "",
                        imaplib.Time2Internaldate(time_module.time()),
                        raw_message.encode("utf8"),
                    )
            time_module.sleep(float(os.environ.get("EMAIL_SEND_PAUSE_SECONDS", "0.5")))
        except Exception as exc:
            logger.error("❌ Rappel email non envoyé à %s: %s", receiver, exc)
            errors.append(f"{receiver}: {exc}")

    if errors:
        return False, "; ".join(errors[:3])
    return True, None


def _dispatch_reminder(payload):
    if os.environ.get("REMINDER_WEBHOOK_URL"):
        return _post_reminder_webhook(payload)
    return _send_reminder_emails(payload)


def process_due_reminders(base_url=None, dry_run=False):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        ensure_course_schedule_tables(cursor)
        now = datetime.now(FRANCE_TZ)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        evening_hour = int(os.environ.get("REMINDER_PREVIOUS_EVENING_HOUR", "18"))
        active_hours = float(os.environ.get("COURSE_SESSION_ACTIVE_HOURS", "12"))
        active_until = now + timedelta(hours=active_hours)

        cursor.execute(
            """
            SELECT id, platform_id, session_index, scheduled_at,
                   reminder_previous_evening_sent_at, reminder_5min_sent_at,
                   session_password
            FROM course_sessions
            WHERE status IN ('planned', 'active')
              AND scheduled_at <= ?
            ORDER BY scheduled_at ASC
            """,
            (active_until.strftime("%Y-%m-%d %H:%M:%S"),),
        )

        results = []
        for (
            session_id,
            platform_id,
            session_index,
            scheduled_at_str,
            previous_sent,
            five_sent,
            session_password,
        ) in cursor.fetchall():
            scheduled_at = _parse_local_datetime(scheduled_at_str)
            due_types = []
            previous_evening_at = FRANCE_TZ.localize(
                datetime.combine((scheduled_at - timedelta(days=1)).date(), time(evening_hour, 0))
            )
            if not previous_sent and now >= previous_evening_at and now < scheduled_at:
                due_types.append(("previous_evening", "reminder_previous_evening_sent_at"))

            five_min_at = scheduled_at - timedelta(minutes=5)
            if not five_sent and now >= five_min_at and now <= scheduled_at + timedelta(hours=active_hours):
                due_types.append(("five_minutes_before", "reminder_5min_sent_at"))

            if not due_types:
                continue

            recipients = _student_recipients(cursor, platform_id)
            class_url = _platform_class_url(cursor, platform_id, base_url)
            for reminder_type, sent_column in due_types:
                password_for_email = session_password
                if not password_for_email and not dry_run:
                    password_for_email = _ensure_session_password(cursor, session_id, now_str)
                payload = {
                    "type": reminder_type,
                    "platform_id": platform_id,
                    "session_id": session_id,
                    "session_index": session_index,
                    "scheduled_at": scheduled_at_str,
                    "class_url": class_url,
                    "session_password": password_for_email,
                    "recipients": recipients,
                }
                if dry_run:
                    results.append({**payload, "success": True, "dry_run": True})
                    continue

                ok, error = _dispatch_reminder(payload)
                if ok:
                    cursor.execute(
                        f"UPDATE course_sessions SET {sent_column} = ?, updated_at = ? WHERE id = ?",
                        (now_str, now_str, session_id),
                    )
                results.append({**payload, "success": ok, "error": error})

        conn.commit()
        return results
    finally:
        conn.close()
