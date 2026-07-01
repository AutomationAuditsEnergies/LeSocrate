-- Postgres target schema for Le Socrate multi-tenant SaaS.
-- This schema keeps the current table names where possible to make the
-- SQLite -> Postgres migration incremental instead of a full rewrite.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS training_center_accounts (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_debug_plaintext TEXT,
    center_name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS platform_config (
    id BIGSERIAL PRIMARY KEY,
    center_account_id BIGINT REFERENCES training_center_accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    upload_locked BOOLEAN NOT NULL DEFAULT TRUE,
    public_access_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    pdf_filename TEXT,
    pdf_uploaded_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    playlist_mode TEXT,
    audio_container TEXT,
    pdf_container TEXT,
    archive_container TEXT,
    audio_base_url TEXT,
    status TEXT NOT NULL DEFAULT 'ready',
    source_formation_id BIGINT,
    source_module_id BIGINT,
    UNIQUE(center_account_id, slug)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_config_global_slug
    ON platform_config(slug)
    WHERE center_account_id IS NULL;

CREATE TABLE IF NOT EXISTS cours_config (
    id BIGINT PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    heure_debut TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS course_schedule_config (
    platform_id BIGINT PRIMARY KEY REFERENCES platform_config(id) ON DELETE CASCADE,
    total_training_days INTEGER NOT NULL,
    weekly_course_count INTEGER NOT NULL,
    weekdays_json TEXT NOT NULL,
    start_time TEXT NOT NULL DEFAULT '09:00',
    timezone TEXT NOT NULL DEFAULT 'Europe/Paris',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS course_sessions (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    session_index INTEGER NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    activated_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    reminder_previous_evening_sent_at TIMESTAMPTZ,
    reminder_5min_sent_at TIMESTAMPTZ,
    audio_generation_status TEXT NOT NULL DEFAULT 'pending',
    audio_generation_started_at TIMESTAMPTZ,
    audio_generation_completed_at TIMESTAMPTZ,
    audio_generation_error TEXT,
    audio_job_id BIGINT,
    audio_folder_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(platform_id, session_index)
);

CREATE TABLE IF NOT EXISTS course_reminder_recipients (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(platform_id, email)
);

CREATE TABLE IF NOT EXISTS logs (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT REFERENCES platform_config(id) ON DELETE SET NULL,
    nom TEXT,
    prenom TEXT,
    arrivee TIMESTAMPTZ,
    depart TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS video_visits (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT REFERENCES platform_config(id) ON DELETE SET NULL,
    log_id BIGINT REFERENCES logs(id) ON DELETE SET NULL,
    timestamp TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS student_accounts (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(platform_id, username)
);

CREATE TABLE IF NOT EXISTS student_profiles (
    id BIGSERIAL PRIMARY KEY,
    auth_user_id UUID NOT NULL UNIQUE,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS student_attendance_records (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    student_profile_id BIGINT NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
    course_date DATE NOT NULL,
    slots_json TEXT NOT NULL DEFAULT '[]',
    total_minutes INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'absent',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(platform_id, student_profile_id, course_date)
);

CREATE TABLE IF NOT EXISTS ai_teacher_orders (
    id BIGSERIAL PRIMARY KEY,
    center_account_id BIGINT NOT NULL REFERENCES training_center_accounts(id) ON DELETE CASCADE,
    platform_id BIGINT REFERENCES platform_config(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    training_title TEXT NOT NULL,
    rncp_code TEXT,
    total_hours INTEGER NOT NULL,
    quoted_amount_cents INTEGER,
    currency TEXT NOT NULL DEFAULT 'eur',
    stripe_checkout_session_id TEXT,
    stripe_payment_intent_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_config_center ON platform_config(center_account_id);
CREATE INDEX IF NOT EXISTS idx_cours_config_platform ON cours_config(platform_id);
CREATE INDEX IF NOT EXISTS idx_course_sessions_platform_scheduled ON course_sessions(platform_id, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_course_sessions_status_scheduled ON course_sessions(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_course_reminder_recipients_platform ON course_reminder_recipients(platform_id);
CREATE INDEX IF NOT EXISTS idx_logs_platform_arrivee ON logs(platform_id, arrivee);
CREATE INDEX IF NOT EXISTS idx_video_visits_platform ON video_visits(platform_id);
CREATE INDEX IF NOT EXISTS idx_video_visits_log ON video_visits(log_id);
CREATE INDEX IF NOT EXISTS idx_student_profiles_platform ON student_profiles(platform_id);
CREATE INDEX IF NOT EXISTS idx_student_attendance_platform_date ON student_attendance_records(platform_id, course_date);
CREATE INDEX IF NOT EXISTS idx_student_attendance_student ON student_attendance_records(student_profile_id);
CREATE INDEX IF NOT EXISTS idx_ai_teacher_orders_center ON ai_teacher_orders(center_account_id);
CREATE INDEX IF NOT EXISTS idx_ai_teacher_orders_platform ON ai_teacher_orders(platform_id);
