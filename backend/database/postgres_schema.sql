-- Postgres target schema for Le Socrate multi-tenant SaaS.
-- This schema keeps the current table names where possible to make the
-- SQLite -> Postgres migration incremental instead of a full rewrite.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS training_center_accounts (
    id BIGSERIAL PRIMARY KEY,
    auth_user_id UUID UNIQUE,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_debug_plaintext TEXT,
    center_name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    pipeline_access_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    stripe_customer_id TEXT,
    billing_mode TEXT NOT NULL DEFAULT 'stripe_required',
    billing_exempt_reason TEXT,
    billing_exempt_at TIMESTAMPTZ,
    billing_exempt_updated_by TEXT,
    onboarding_version INTEGER NOT NULL DEFAULT 0,
    onboarding_completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE training_center_accounts
    ADD COLUMN IF NOT EXISTS auth_user_id UUID;
ALTER TABLE training_center_accounts
    ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE training_center_accounts
    ADD COLUMN IF NOT EXISTS billing_mode TEXT NOT NULL DEFAULT 'stripe_required';
ALTER TABLE training_center_accounts
    ADD COLUMN IF NOT EXISTS billing_exempt_reason TEXT;
ALTER TABLE training_center_accounts
    ADD COLUMN IF NOT EXISTS billing_exempt_at TIMESTAMPTZ;
ALTER TABLE training_center_accounts
    ADD COLUMN IF NOT EXISTS billing_exempt_updated_by TEXT;
ALTER TABLE training_center_accounts
    ADD COLUMN IF NOT EXISTS onboarding_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE training_center_accounts
    ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;

DO $$
BEGIN
    -- Supabase Auth peut partager cette base, mais l'architecture supporte
    -- aussi un PostgreSQL metier independant (Azure ou PostgreSQL standard).
    -- Dans ce second cas, l'identifiant JWT reste stocke sans imposer le
    -- schema prive `auth`, qui n'existe que dans une base Supabase complete.
    IF to_regclass('auth.users') IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'training_center_accounts_auth_user_id_fkey'
          AND conrelid = 'training_center_accounts'::regclass
    ) THEN
        EXECUTE '
            ALTER TABLE training_center_accounts
                ADD CONSTRAINT training_center_accounts_auth_user_id_fkey
                FOREIGN KEY (auth_user_id)
                REFERENCES auth.users(id)
                ON DELETE SET NULL
        ';
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_training_center_accounts_auth_user_id
    ON training_center_accounts(auth_user_id)
    WHERE auth_user_id IS NOT NULL;

DO $$
BEGIN
    IF to_regclass('auth.users') IS NOT NULL THEN
        EXECUTE '
            UPDATE training_center_accounts AS center
            SET auth_user_id = auth_user.id,
                updated_at = NOW()
            FROM auth.users AS auth_user
            WHERE center.auth_user_id IS NULL
              AND auth_user.email IS NOT NULL
              AND LOWER(auth_user.email) = LOWER(center.username)
        ';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS platform_config (
    id BIGSERIAL PRIMARY KEY,
    center_account_id BIGINT REFERENCES training_center_accounts(id) ON DELETE CASCADE,
    center_platform_number INTEGER,
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
    teacher_name TEXT,
    teacher_color TEXT,
    creation_request_id TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    completed_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    asset_binding_mode TEXT NOT NULL DEFAULT 'canonical',
    UNIQUE(center_account_id, slug)
);

ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS teacher_name TEXT;
ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS teacher_color TEXT;
ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS creation_request_id TEXT;
ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS lifecycle_status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS asset_binding_mode TEXT NOT NULL DEFAULT 'canonical';
ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS center_platform_number INTEGER;

-- L'identifiant global reste la cle technique. Ce numero est l'identifiant
-- lisible du professeur dans son centre et recommence donc a 1 pour chaque
-- nouveau centre. Les numeros existants ne sont jamais reutilises.
WITH numbered_platforms AS (
    SELECT
        id,
        ROW_NUMBER() OVER (PARTITION BY center_account_id ORDER BY id) AS local_number
    FROM platform_config
    WHERE center_account_id IS NOT NULL
)
UPDATE platform_config pc
SET center_platform_number = numbered.local_number
FROM numbered_platforms numbered
WHERE pc.id = numbered.id
  AND pc.center_platform_number IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_config_center_number
    ON platform_config(center_account_id, center_platform_number)
    WHERE center_account_id IS NOT NULL;

DO $$
BEGIN
    ALTER TABLE platform_config
        ADD CONSTRAINT platform_config_center_number_check
        CHECK (
            (center_account_id IS NULL AND center_platform_number IS NULL)
            OR (center_account_id IS NOT NULL AND center_platform_number > 0)
        ) NOT VALID;
EXCEPTION
    WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

CREATE OR REPLACE FUNCTION assign_center_platform_number()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.center_account_id IS NULL THEN
        NEW.center_platform_number := NULL;
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.center_account_id IS NOT NULL
       AND NEW.center_account_id IS DISTINCT FROM OLD.center_account_id THEN
        RAISE EXCEPTION 'Le centre proprietaire d une plateforme est immuable';
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.center_platform_number IS NOT NULL
       AND NEW.center_platform_number IS DISTINCT FROM OLD.center_platform_number THEN
        RAISE EXCEPTION 'Le numero de plateforme dans le centre est immuable';
    END IF;

    IF NEW.center_platform_number IS NULL THEN
        -- La creation d'une plateforme est rare par rapport aux lectures. Un
        -- verrou par centre rend MAX + 1 atomique sans bloquer les autres
        -- centres qui creent une plateforme au meme moment.
        PERFORM pg_advisory_xact_lock(
            hashtextextended('center-platform-number:' || NEW.center_account_id::text, 0)
        );
        SELECT COALESCE(MAX(pc.center_platform_number), 0) + 1
        INTO NEW.center_platform_number
        FROM platform_config pc
        WHERE pc.center_account_id = NEW.center_account_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_assign_center_platform_number ON platform_config;
CREATE TRIGGER trg_assign_center_platform_number
    BEFORE INSERT OR UPDATE OF center_account_id, center_platform_number
    ON platform_config
    FOR EACH ROW
    EXECUTE FUNCTION assign_center_platform_number();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM platform_config
        WHERE (center_account_id IS NULL AND center_platform_number IS NOT NULL)
           OR (
                center_account_id IS NOT NULL
                AND (center_platform_number IS NULL OR center_platform_number <= 0)
              )
    ) THEN
        ALTER TABLE platform_config
            VALIDATE CONSTRAINT platform_config_center_number_check;
    END IF;
END $$;

DO $$
BEGIN
    ALTER TABLE platform_config
        ADD CONSTRAINT uq_platform_config_owner_identity
        UNIQUE (id, center_account_id, center_platform_number);
EXCEPTION
    WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_platform_config_global_slug
    ON platform_config(slug)
    WHERE center_account_id IS NULL;

CREATE TABLE IF NOT EXISTS deletion_requests (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    requester_name TEXT NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

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
    reminder_previous_evening_claimed_at TIMESTAMPTZ,
    reminder_5min_claimed_at TIMESTAMPTZ,
    session_password TEXT,
    session_password_generated_at TIMESTAMPTZ,
    audio_generation_status TEXT NOT NULL DEFAULT 'pending',
    audio_generation_started_at TIMESTAMPTZ,
    audio_generation_completed_at TIMESTAMPTZ,
    audio_generation_error TEXT,
    audio_generation_attempts INTEGER NOT NULL DEFAULT 0,
    audio_generation_next_retry_at TIMESTAMPTZ,
    audio_job_id BIGINT,
    audio_folder_id BIGINT,
    audio_storage_prefix TEXT,
    postponed_from TIMESTAMPTZ,
    postponed_at TIMESTAMPTZ,
    postponement_count INTEGER NOT NULL DEFAULT 0,
    module_day_id BIGINT,
    local_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(platform_id, session_index)
);

DO $$
BEGIN
    ALTER TABLE course_sessions
        ADD CONSTRAINT uq_course_sessions_platform_identity
        UNIQUE (id, platform_id);
EXCEPTION
    WHEN duplicate_object OR duplicate_table THEN NULL;
END $$;

-- CREATE TABLE IF NOT EXISTS does not evolve an already provisioned Supabase
-- table. Keep additive runtime migrations explicit and idempotent here.
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS session_password TEXT;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS session_password_generated_at TIMESTAMPTZ;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS reminder_previous_evening_claimed_at TIMESTAMPTZ;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS reminder_5min_claimed_at TIMESTAMPTZ;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_generation_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_generation_started_at TIMESTAMPTZ;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_generation_completed_at TIMESTAMPTZ;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_generation_error TEXT;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_generation_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_generation_next_retry_at TIMESTAMPTZ;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_job_id BIGINT;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_folder_id BIGINT;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_storage_prefix TEXT;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS postponed_from TIMESTAMPTZ;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS postponed_at TIMESTAMPTZ;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS postponement_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS module_day_id BIGINT;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS local_date DATE;

CREATE TABLE IF NOT EXISTS course_session_postponements (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    session_id BIGINT NOT NULL REFERENCES course_sessions(id) ON DELETE CASCADE,
    session_index INTEGER NOT NULL,
    previous_scheduled_at TIMESTAMPTZ NOT NULL,
    new_scheduled_at TIMESTAMPTZ NOT NULL,
    mode TEXT NOT NULL,
    reason TEXT,
    affected_session_count INTEGER NOT NULL DEFAULT 1,
    idempotency_key TEXT,
    actor_account_id BIGINT,
    impact_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_course_session_postponements_idempotency
    ON course_session_postponements(platform_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_course_session_postponements_session
    ON course_session_postponements(platform_id, session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS course_reminder_recipients (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(platform_id, email)
);

CREATE TABLE IF NOT EXISTS course_reminder_rules (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    system_key TEXT,
    name TEXT NOT NULL,
    trigger_mode TEXT NOT NULL,
    days_before INTEGER,
    minutes_before INTEGER,
    local_time TIME,
    subject_template TEXT NOT NULL,
    content_template TEXT NOT NULL,
    recipient_scope TEXT NOT NULL DEFAULT 'all',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (trigger_mode IN ('local_day_time', 'relative_minutes')),
    CHECK (recipient_scope IN ('all', 'selected_explicit')),
    CHECK (days_before IS NULL OR days_before >= 0),
    CHECK (minutes_before IS NULL OR minutes_before >= 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_course_reminder_rules_system_key
    ON course_reminder_rules(platform_id, system_key)
    WHERE system_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS course_reminder_rule_recipients (
    rule_id BIGINT NOT NULL REFERENCES course_reminder_rules(id) ON DELETE CASCADE,
    recipient_id BIGINT NOT NULL REFERENCES course_reminder_recipients(id) ON DELETE CASCADE,
    PRIMARY KEY(rule_id, recipient_id)
);

CREATE TABLE IF NOT EXISTS course_reminder_deliveries (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    session_id BIGINT NOT NULL REFERENCES course_sessions(id) ON DELETE CASCADE,
    rule_id BIGINT NOT NULL REFERENCES course_reminder_rules(id) ON DELETE CASCADE,
    recipient_id BIGINT NOT NULL REFERENCES course_reminder_recipients(id) ON DELETE CASCADE,
    recipient_hash TEXT NOT NULL,
    due_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    claimed_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_retry_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(session_id, rule_id, recipient_hash),
    CHECK (status IN ('pending', 'claimed', 'retry_scheduled', 'sent', 'dead_lettered')),
    CHECK (max_attempts > 0)
);

CREATE TABLE IF NOT EXISTS logs (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT REFERENCES platform_config(id) ON DELETE SET NULL,
    course_session_id BIGINT REFERENCES course_sessions(id) ON DELETE SET NULL,
    recipient_hash TEXT,
    nom TEXT,
    prenom TEXT,
    arrivee TIMESTAMPTZ,
    attendance_started_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    depart TIMESTAMPTZ,
    closed_reason TEXT
);

ALTER TABLE logs ADD COLUMN IF NOT EXISTS course_session_id BIGINT;
ALTER TABLE logs ADD COLUMN IF NOT EXISTS recipient_hash TEXT;
ALTER TABLE logs ADD COLUMN IF NOT EXISTS attendance_started_at TIMESTAMPTZ;
ALTER TABLE logs ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
ALTER TABLE logs ADD COLUMN IF NOT EXISTS closed_reason TEXT;
DO $$
BEGIN
    ALTER TABLE logs
        ADD CONSTRAINT logs_course_session_id_fkey
        FOREIGN KEY (course_session_id) REFERENCES course_sessions(id) ON DELETE SET NULL;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS attendance_daily_exports (
    id BIGSERIAL PRIMARY KEY,
    center_account_id BIGINT NOT NULL REFERENCES training_center_accounts(id) ON DELETE CASCADE,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    center_platform_number INTEGER NOT NULL,
    course_session_id BIGINT NOT NULL REFERENCES course_sessions(id) ON DELETE CASCADE,
    teacher_module_id BIGINT,
    course_date DATE NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    claimed_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_retry_at TIMESTAMPTZ,
    container_name TEXT,
    blob_key TEXT,
    filename TEXT,
    size_bytes BIGINT,
    sha256 TEXT,
    participant_count INTEGER NOT NULL DEFAULT 0,
    generated_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(course_session_id),
    CHECK (status IN ('pending', 'claimed', 'retry_scheduled', 'ready', 'dead_lettered')),
    CHECK (attempts >= 0),
    CHECK (max_attempts > 0)
);

ALTER TABLE attendance_daily_exports
    ADD COLUMN IF NOT EXISTS center_account_id BIGINT;
ALTER TABLE attendance_daily_exports
    ADD COLUMN IF NOT EXISTS center_platform_number INTEGER;
ALTER TABLE attendance_daily_exports
    ADD COLUMN IF NOT EXISTS teacher_module_id BIGINT;

UPDATE attendance_daily_exports export
SET center_account_id = pc.center_account_id,
    center_platform_number = pc.center_platform_number
FROM platform_config pc
WHERE pc.id = export.platform_id
  AND (
      export.center_account_id IS DISTINCT FROM pc.center_account_id
      OR export.center_platform_number IS DISTINCT FROM pc.center_platform_number
  );

DO $$
BEGIN
    ALTER TABLE attendance_daily_exports
        ADD CONSTRAINT attendance_daily_exports_owner_required
        CHECK (center_account_id IS NOT NULL AND center_platform_number IS NOT NULL) NOT VALID;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE attendance_daily_exports
        ADD CONSTRAINT attendance_daily_exports_center_fkey
        FOREIGN KEY (center_account_id)
        REFERENCES training_center_accounts(id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE attendance_daily_exports
        ADD CONSTRAINT attendance_daily_exports_platform_owner_fkey
        FOREIGN KEY (platform_id, center_account_id, center_platform_number)
        REFERENCES platform_config(id, center_account_id, center_platform_number)
        ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE attendance_daily_exports
        ADD CONSTRAINT attendance_daily_exports_session_platform_fkey
        FOREIGN KEY (course_session_id, platform_id)
        REFERENCES course_sessions(id, platform_id) ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM attendance_daily_exports
        WHERE center_account_id IS NULL OR center_platform_number IS NULL
    ) THEN
        ALTER TABLE attendance_daily_exports
            VALIDATE CONSTRAINT attendance_daily_exports_owner_required;
    END IF;
END $$;

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
    public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    center_account_id BIGINT NOT NULL REFERENCES training_center_accounts(id) ON DELETE CASCADE,
    platform_id BIGINT REFERENCES platform_config(id) ON DELETE SET NULL,
    pipeline_job_id BIGINT,
    operation_type TEXT NOT NULL DEFAULT 'new_teacher',
    source_module_id BIGINT,
    status TEXT NOT NULL DEFAULT 'awaiting_payment',
    payment_status TEXT NOT NULL DEFAULT 'awaiting_payment',
    fulfillment_status TEXT NOT NULL DEFAULT 'not_started',
    training_title TEXT NOT NULL,
    rncp_code TEXT,
    total_hours INTEGER NOT NULL,
    request_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    creation_request_id TEXT NOT NULL DEFAULT gen_random_uuid()::text,
    request_fingerprint TEXT NOT NULL DEFAULT gen_random_uuid()::text,
    pricing_key TEXT NOT NULL DEFAULT 'new_teacher',
    stripe_price_id TEXT,
    quoted_amount_cents INTEGER,
    catalog_amount_cents INTEGER,
    charged_amount_cents INTEGER,
    currency TEXT NOT NULL DEFAULT 'eur',
    authorization_kind TEXT NOT NULL DEFAULT 'stripe',
    stripe_checkout_session_id TEXT,
    checkout_attempt_count INTEGER NOT NULL DEFAULT 0,
    stripe_payment_intent_id TEXT,
    checkout_expires_at TIMESTAMPTZ,
    authorized_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    refunded_at TIMESTAMPTZ,
    fulfilled_at TIMESTAMPTZ,
    fulfillment_work_item_id UUID,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS public_id UUID DEFAULT gen_random_uuid();
UPDATE ai_teacher_orders SET public_id = gen_random_uuid() WHERE public_id IS NULL;
ALTER TABLE ai_teacher_orders ALTER COLUMN public_id SET NOT NULL;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS pipeline_job_id BIGINT;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS operation_type TEXT NOT NULL DEFAULT 'new_teacher';
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS source_module_id BIGINT;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS payment_status TEXT NOT NULL DEFAULT 'awaiting_payment';
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS fulfillment_status TEXT NOT NULL DEFAULT 'not_started';
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS request_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS creation_request_id TEXT;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS request_fingerprint TEXT;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS pricing_key TEXT;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS stripe_price_id TEXT;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS catalog_amount_cents INTEGER;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS charged_amount_cents INTEGER;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS authorization_kind TEXT NOT NULL DEFAULT 'stripe';
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS checkout_expires_at TIMESTAMPTZ;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS authorized_at TIMESTAMPTZ;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMPTZ;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS fulfilled_at TIMESTAMPTZ;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS fulfillment_work_item_id UUID;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE ai_teacher_orders ADD COLUMN IF NOT EXISTS checkout_attempt_count INTEGER NOT NULL DEFAULT 0;
UPDATE ai_teacher_orders
SET creation_request_id = COALESCE(creation_request_id, 'legacy-' || id::text),
    request_fingerprint = COALESCE(request_fingerprint, 'legacy-' || id::text),
    pricing_key = COALESCE(pricing_key, operation_type)
WHERE creation_request_id IS NULL OR request_fingerprint IS NULL OR pricing_key IS NULL;
ALTER TABLE ai_teacher_orders ALTER COLUMN creation_request_id SET NOT NULL;
ALTER TABLE ai_teacher_orders ALTER COLUMN request_fingerprint SET NOT NULL;
ALTER TABLE ai_teacher_orders ALTER COLUMN pricing_key SET NOT NULL;
ALTER TABLE ai_teacher_orders ALTER COLUMN creation_request_id SET DEFAULT gen_random_uuid()::text;
ALTER TABLE ai_teacher_orders ALTER COLUMN request_fingerprint SET DEFAULT gen_random_uuid()::text;
ALTER TABLE ai_teacher_orders ALTER COLUMN pricing_key SET DEFAULT 'new_teacher';

CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    livemode BOOLEAN NOT NULL DEFAULT FALSE,
    payload_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS formation_pipeline_jobs (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    tp_name TEXT NOT NULL,
    rncp_code TEXT,
    total_hours INTEGER NOT NULL,
    nb_days INTEGER NOT NULL,
    reac_text TEXT,
    global_program TEXT,
    global_program_validated BOOLEAN NOT NULL DEFAULT FALSE,
    daily_programs TEXT NOT NULL DEFAULT '[]',
    daily_programs_validated BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'init',
    error_message TEXT,
    kb_generated_via TEXT,
    global_program_generated_via TEXT,
    daily_programs_generated_via TEXT,
    auto_pilot_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    auto_pilot_step TEXT,
    auto_pilot_model TEXT,
    auto_pilot_tts_mode TEXT,
    auto_pilot_post_review_docs_done BOOLEAN NOT NULL DEFAULT FALSE,
    auto_pilot_error TEXT,
    auto_pilot_locked_at TIMESTAMPTZ,
    auto_pilot_lock_owner TEXT,
    schedule_schema_version INTEGER NOT NULL DEFAULT 1,
    schedule_snapshot_json JSONB,
    schedule_hash TEXT,
    schedule_locked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE formation_pipeline_jobs
    DROP COLUMN IF EXISTS rc_text,
    DROP COLUMN IF EXISTS rome_text,
    DROP COLUMN IF EXISTS auto_pilot_use_cc,
    DROP COLUMN IF EXISTS auto_pilot_volume_done,
    DROP COLUMN IF EXISTS auto_pilot_generate_audio,
    DROP COLUMN IF EXISTS auto_pilot_skip_vs;

ALTER TABLE formation_pipeline_jobs
    ADD COLUMN IF NOT EXISTS schedule_schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE formation_pipeline_jobs
    ADD COLUMN IF NOT EXISTS schedule_snapshot_json JSONB;
ALTER TABLE formation_pipeline_jobs
    ADD COLUMN IF NOT EXISTS schedule_hash TEXT;
ALTER TABLE formation_pipeline_jobs
    ADD COLUMN IF NOT EXISTS schedule_locked_at TIMESTAMPTZ;

-- Grant the initial Formation3 operator only when this permission is
-- introduced. Pipeline permission and tenant ownership are intentionally
-- independent: granting access to the pipeline must never make a centre the
-- owner of pre-existing global platforms.
DO $$
DECLARE
    pipeline_permission_was_missing BOOLEAN;
    pipeline_operator_count INTEGER;
BEGIN
    SELECT NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'training_center_accounts'
          AND column_name = 'pipeline_access_enabled'
    )
    INTO pipeline_permission_was_missing;

    ALTER TABLE training_center_accounts
        ADD COLUMN IF NOT EXISTS pipeline_access_enabled BOOLEAN NOT NULL DEFAULT FALSE;

    IF pipeline_permission_was_missing THEN
        SELECT COUNT(*)
        INTO pipeline_operator_count
        FROM training_center_accounts
        WHERE LOWER(username) = 'newpiprod@gmail.com';

        IF pipeline_operator_count > 1 THEN
            RAISE EXCEPTION
                'Plusieurs comptes correspondent à newpiprod@gmail.com; bootstrap pipeline refusé';
        END IF;

        UPDATE training_center_accounts
        SET pipeline_access_enabled = TRUE
        WHERE LOWER(username) = 'newpiprod@gmail.com'
          AND is_active = TRUE;
    END IF;
END
$$;

-- Correction one-shot du bootstrap historique ci-dessus. Il avait rattaché
-- tous les pipelines orphelins au premier opérateur Formation3. Les lignes
-- restent intégralement persistées mais redeviennent globales quand aucune
-- preuve durable ne les relie au centre (commande, job de commande ou demande
-- de création). Les plateformes réellement recrutées par le centre gardent
-- leur propriétaire.
CREATE TABLE IF NOT EXISTS app_schema_migrations (
    migration_key TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
DECLARE
    migration_key_value CONSTANT TEXT :=
        '20260727_remove_pipeline_operator_bulk_ownership_v1';
    pipeline_operator_count INTEGER;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM app_schema_migrations
        WHERE migration_key = migration_key_value
    ) THEN
        SELECT COUNT(*)
        INTO pipeline_operator_count
        FROM training_center_accounts
        WHERE LOWER(username) = 'newpiprod@gmail.com';

        IF pipeline_operator_count > 1 THEN
            RAISE EXCEPTION
                'Plusieurs comptes correspondent à newpiprod@gmail.com; correction de propriété refusée';
        END IF;

        IF pipeline_operator_count = 1 THEN
            -- Le trigger protège normalement l'identité propriétaire. Le
            -- désactiver dans cette transaction est nécessaire uniquement
            -- pour réparer l'attribution historique erronée ; tout rollback
            -- restaure automatiquement son état.
            ALTER TABLE platform_config
                DISABLE TRIGGER trg_assign_center_platform_number;

            WITH pipeline_operator AS (
                SELECT id
                FROM training_center_accounts
                WHERE LOWER(username) = 'newpiprod@gmail.com'
            )
            UPDATE platform_config AS platform
            SET center_account_id = NULL,
                center_platform_number = NULL
            FROM pipeline_operator
            WHERE platform.center_account_id = pipeline_operator.id
              AND platform.creation_request_id IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM formation_pipeline_jobs AS job
                  WHERE job.platform_id = platform.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM ai_teacher_orders AS teacher_order
                  WHERE teacher_order.center_account_id = pipeline_operator.id
                    AND (
                        teacher_order.platform_id = platform.id
                        OR (
                            teacher_order.pipeline_job_id IS NOT NULL
                            AND EXISTS (
                                SELECT 1
                                FROM formation_pipeline_jobs AS ordered_job
                                WHERE ordered_job.id = teacher_order.pipeline_job_id
                                  AND ordered_job.platform_id = platform.id
                            )
                        )
                    )
              );

            ALTER TABLE platform_config
                ENABLE TRIGGER trg_assign_center_platform_number;
        END IF;

        INSERT INTO app_schema_migrations (migration_key)
        VALUES (migration_key_value);
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS formation_knowledge_base (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES formation_pipeline_jobs(id) ON DELETE CASCADE,
    competence_index INTEGER NOT NULL,
    competence_key TEXT NOT NULL,
    competence_title TEXT NOT NULL,
    bloc TEXT,
    raw_source TEXT,
    definition_pedagogique TEXT NOT NULL DEFAULT '',
    etudes_de_cas TEXT NOT NULL DEFAULT '[]',
    pieges_frequents TEXT NOT NULL DEFAULT '[]',
    vocabulaire_metier TEXT NOT NULL DEFAULT '{}',
    contexte_terrain TEXT NOT NULL DEFAULT '',
    liens_connexes TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    dirty BOOLEAN NOT NULL DEFAULT FALSE,
    error_message TEXT,
    total_words INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(job_id, competence_index)
);

CREATE TABLE IF NOT EXISTS cours_folders (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    formation_job_id BIGINT REFERENCES formation_pipeline_jobs(id) ON DELETE SET NULL,
    module_day_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE cours_folders
    ADD COLUMN IF NOT EXISTS module_day_id BIGINT;

CREATE TABLE IF NOT EXISTS cours_documents (
    id BIGSERIAL PRIMARY KEY,
    folder_id BIGINT NOT NULL REFERENCES cours_folders(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'source',
    status TEXT NOT NULL DEFAULT 'uploaded',
    audio_filename TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Stable source -> target folder identities for retryable HR clones. Blob
-- object paths contain folder IDs, so a retry must reuse the first mapping
-- instead of creating another set of folders with different IDs.
CREATE TABLE IF NOT EXISTS course_clone_folder_map (
    target_platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    source_platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    source_folder_id BIGINT NOT NULL REFERENCES cours_folders(id) ON DELETE CASCADE,
    target_folder_id BIGINT NOT NULL UNIQUE REFERENCES cours_folders(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (target_platform_id, source_folder_id)
);

CREATE TABLE IF NOT EXISTS content_generation_jobs (
    id BIGSERIAL PRIMARY KEY,
    folder_id BIGINT NOT NULL UNIQUE REFERENCES cours_folders(id) ON DELETE CASCADE,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    program_text TEXT NOT NULL,
    program_title TEXT NOT NULL DEFAULT '',
    sub_parts TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'idle',
    current_sub_part INTEGER NOT NULL DEFAULT 0,
    current_passe INTEGER NOT NULL DEFAULT 1,
    total_words INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    from_scratch BOOLEAN NOT NULL DEFAULT FALSE,
    module_contents TEXT NOT NULL DEFAULT '{}',
    carryover_in_text TEXT NOT NULL DEFAULT '',
    carryover_in_source_folder_id BIGINT REFERENCES cours_folders(id) ON DELETE SET NULL,
    carryover_out_text TEXT NOT NULL DEFAULT '',
    carryover_out_target_folder_id BIGINT REFERENCES cours_folders(id) ON DELETE SET NULL,
    structured_plan_input_signature TEXT,
    structured_plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE content_generation_jobs
    ADD COLUMN IF NOT EXISTS structured_plan_input_signature TEXT;
ALTER TABLE content_generation_jobs
    ADD COLUMN IF NOT EXISTS structured_plan_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS content_generation_segments (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES content_generation_jobs(id) ON DELETE CASCADE,
    sub_part_index INTEGER NOT NULL,
    sub_part_name TEXT NOT NULL,
    passe INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    text_content TEXT NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    dirty BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed BOOLEAN NOT NULL DEFAULT FALSE,
    generated_via TEXT,
    review_error TEXT,
    text_content_pre_review TEXT,
    review_signature TEXT,
    structured_checkpoint_signature TEXT,
    structured_checkpoint_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(job_id, sub_part_index, passe)
);

ALTER TABLE content_generation_segments
    ADD COLUMN IF NOT EXISTS structured_checkpoint_signature TEXT;
ALTER TABLE content_generation_segments
    ADD COLUMN IF NOT EXISTS structured_checkpoint_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE content_generation_segments
    DROP COLUMN IF EXISTS humanized,
    DROP COLUMN IF EXISTS humanization_error,
    DROP COLUMN IF EXISTS humanization_signature;

CREATE TABLE IF NOT EXISTS content_script_annotations (
    id BIGSERIAL PRIMARY KEY,
    folder_id BIGINT NOT NULL REFERENCES cours_folders(id) ON DELETE CASCADE,
    job_id BIGINT NOT NULL REFERENCES content_generation_jobs(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL DEFAULT 'course',
    sub_part_index INTEGER,
    passe INTEGER,
    bloc_number INTEGER,
    filename TEXT,
    selected_text TEXT NOT NULL,
    comment TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    markdown_path TEXT,
    original_paragraph TEXT,
    proposed_text TEXT,
    correction_status TEXT NOT NULL DEFAULT 'pending',
    correction_error TEXT,
    applied_at TIMESTAMPTZ,
    splice_status TEXT,
    splice_error TEXT,
    splice_blob_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS content_script_rules (
    id BIGSERIAL PRIMARY KEY,
    folder_id BIGINT NOT NULL REFERENCES cours_folders(id) ON DELETE CASCADE,
    job_id BIGINT NOT NULL REFERENCES content_generation_jobs(id) ON DELETE CASCADE,
    rules_markdown TEXT NOT NULL DEFAULT '',
    rules_count INTEGER NOT NULL DEFAULT 0,
    source_annotations_count INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    markdown_path TEXT,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(folder_id, job_id)
);

CREATE TABLE IF NOT EXISTS content_review_reports (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES formation_pipeline_jobs(id) ON DELETE CASCADE,
    folder_id BIGINT NOT NULL REFERENCES cours_folders(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'api',
    generated_via TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    report_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS formation_pipeline_events (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES formation_pipeline_jobs(id) ON DELETE CASCADE,
    folder_id BIGINT REFERENCES cours_folders(id) ON DELETE SET NULL,
    step TEXT,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'info',
    message TEXT,
    model TEXT,
    duration_ms INTEGER,
    data_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS formation_modules (
    id BIGSERIAL PRIMARY KEY,
    center_account_id BIGINT REFERENCES training_center_accounts(id) ON DELETE CASCADE,
    rncp_code TEXT,
    tp_name TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'validated',
    source_pipeline_job_id BIGINT UNIQUE REFERENCES formation_pipeline_jobs(id) ON DELETE SET NULL,
    source_platform_id BIGINT REFERENCES platform_config(id) ON DELETE SET NULL,
    voice_type TEXT,
    voice_updated_at TIMESTAMPTZ,
    teacher_name TEXT,
    teacher_color TEXT,
    asset_namespace TEXT,
    immutable BOOLEAN NOT NULL DEFAULT TRUE,
    canonical_fingerprint TEXT,
    canonical_signature_json JSONB,
    canonical_generator_version TEXT,
    canonical_reuse_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    nb_days INTEGER,
    schedule_schema_version INTEGER NOT NULL DEFAULT 1,
    schedule_hash TEXT,
    schedule_locked_at TIMESTAMPTZ,
    reusable_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    validated_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ
);

ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS teacher_name TEXT;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS teacher_color TEXT;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS asset_namespace TEXT;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS immutable BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS canonical_fingerprint TEXT;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS canonical_signature_json JSONB;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS canonical_generator_version TEXT;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS canonical_reuse_allowed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS nb_days INTEGER;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS schedule_schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS schedule_hash TEXT;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS schedule_locked_at TIMESTAMPTZ;
ALTER TABLE formation_modules
    ADD COLUMN IF NOT EXISTS reusable_at TIMESTAMPTZ;

UPDATE formation_modules AS module
SET nb_days = job.nb_days
FROM formation_pipeline_jobs AS job
WHERE job.id = module.source_pipeline_job_id
  AND module.nb_days IS NULL
  AND job.nb_days IS NOT NULL;

-- Bibliothèque d'organisations de journées, propre à chaque centre. Le
-- repository fige name + blocs dès used_at/locked_at; status='deleted' masque
-- seulement le template de la bibliothèque et conserve son historique.
CREATE TABLE IF NOT EXISTS day_schedule_templates (
    id BIGSERIAL PRIMARY KEY,
    center_account_id BIGINT NOT NULL
        REFERENCES training_center_accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deleted')),
    schedule_schema_version INTEGER NOT NULL DEFAULT 2,
    blocks_snapshot_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocks_hash TEXT NOT NULL,
    block_count INTEGER NOT NULL DEFAULT 0,
    total_duration_minutes INTEGER NOT NULL DEFAULT 0,
    course_duration_minutes INTEGER NOT NULL DEFAULT 0,
    used_at TIMESTAMPTZ,
    locked_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS day_schedule_template_blocks (
    id BIGSERIAL PRIMARY KEY,
    template_id BIGINT NOT NULL
        REFERENCES day_schedule_templates(id) ON DELETE CASCADE,
    block_key TEXT NOT NULL,
    position INTEGER NOT NULL,
    block_type TEXT NOT NULL
        CHECK (block_type IN ('course', 'qa', 'pause')),
    pause_kind TEXT
        CHECK (pause_kind IS NULL OR pause_kind IN ('short', 'lunch')),
    start_minute INTEGER NOT NULL,
    end_minute INTEGER NOT NULL,
    duration_minutes INTEGER NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(template_id, position),
    UNIQUE(template_id, block_key)
);

-- Copie autonome et immuable du déroulé de chaque journée d'un module.
-- Aucune date de promotion n'est stockée ici.
CREATE TABLE IF NOT EXISTS formation_module_days (
    id BIGSERIAL PRIMARY KEY,
    module_id BIGINT NOT NULL
        REFERENCES formation_modules(id) ON DELETE RESTRICT,
    center_account_id BIGINT NOT NULL
        REFERENCES training_center_accounts(id) ON DELETE CASCADE,
    day_index INTEGER NOT NULL CHECK (day_index > 0),
    source_template_id BIGINT
        REFERENCES day_schedule_templates(id) ON DELETE SET NULL,
    template_name TEXT NOT NULL,
    schedule_schema_version INTEGER NOT NULL DEFAULT 2,
    schedule_hash TEXT NOT NULL,
    blocks_snapshot_json JSONB NOT NULL,
    block_count INTEGER NOT NULL,
    total_duration_minutes INTEGER NOT NULL,
    course_duration_minutes INTEGER NOT NULL,
    immutable BOOLEAN NOT NULL DEFAULT TRUE,
    locked_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(module_id, day_index)
);

DO $$
BEGIN
    ALTER TABLE course_sessions
        ADD CONSTRAINT course_sessions_module_day_fkey
        FOREIGN KEY (module_day_id)
        REFERENCES formation_module_days(id) ON DELETE RESTRICT;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE cours_folders
        ADD CONSTRAINT cours_folders_module_day_fkey
        FOREIGN KEY (module_day_id)
        REFERENCES formation_module_days(id) ON DELETE RESTRICT;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

UPDATE attendance_daily_exports export
SET teacher_module_id = module.id
FROM platform_config pc
JOIN formation_modules module ON module.id = pc.source_module_id
WHERE pc.id = export.platform_id
  AND export.teacher_module_id IS NULL;

DO $$
BEGIN
    ALTER TABLE attendance_daily_exports
        ADD CONSTRAINT attendance_daily_exports_teacher_module_fkey
        FOREIGN KEY (teacher_module_id)
        REFERENCES formation_modules(id) ON DELETE SET NULL;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

UPDATE formation_modules AS m
SET teacher_name = COALESCE(m.teacher_name, pc.teacher_name),
    teacher_color = COALESCE(m.teacher_color, pc.teacher_color),
    asset_namespace = COALESCE(
        m.asset_namespace,
        'centres/' || COALESCE(m.center_account_id, 0)::text
            || '/modules/' || m.id::text
            || '/versions/' || m.version
    )
FROM platform_config AS pc
WHERE pc.id = m.source_platform_id
  AND (
      m.teacher_name IS NULL
      OR m.teacher_color IS NULL
      OR m.asset_namespace IS NULL
  );

-- Registre des ressources canoniques d'une version de professeur IA. Les MP3
-- validés sont copiés une seule fois dans asset_namespace, puis les promotions
-- pointent vers formation_modules et course_clone_folder_map sans les recopier.
-- Les documents historiques peuvent rester référencés par leur chemin source.
CREATE TABLE IF NOT EXISTS formation_module_assets (
    id BIGSERIAL PRIMARY KEY,
    module_id BIGINT NOT NULL REFERENCES formation_modules(id) ON DELETE RESTRICT,
    center_account_id BIGINT NOT NULL REFERENCES training_center_accounts(id) ON DELETE CASCADE,
    source_folder_id BIGINT REFERENCES cours_folders(id) ON DELETE SET NULL,
    asset_kind TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    container_name TEXT NOT NULL,
    blob_path TEXT NOT NULL,
    content_sha256 TEXT,
    byte_size BIGINT,
    mime_type TEXT,
    language TEXT,
    voice_profile TEXT,
    generator_version TEXT,
    generation_params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'ready',
    storage_tier TEXT NOT NULL DEFAULT 'Hot',
    immutable BOOLEAN NOT NULL DEFAULT TRUE,
    last_verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(module_id, logical_key)
);

CREATE TABLE IF NOT EXISTS script_slide_decks (
    id BIGSERIAL PRIMARY KEY,
    folder_id BIGINT NOT NULL REFERENCES cours_folders(id) ON DELETE CASCADE,
    content_job_id BIGINT NOT NULL REFERENCES content_generation_jobs(id) ON DELETE CASCADE,
    formation_job_id BIGINT REFERENCES formation_pipeline_jobs(id) ON DELETE SET NULL,
    platform_id BIGINT REFERENCES platform_config(id) ON DELETE CASCADE,
    generation_mode TEXT NOT NULL DEFAULT 'script',
    pace TEXT,
    max_slides INTEGER,
    model TEXT,
    slides_json TEXT NOT NULL,
    timeline_json TEXT,
    stats_json TEXT,
    pipeline_debug_json TEXT,
    audio_sync_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_config_center ON platform_config(center_account_id);
CREATE INDEX IF NOT EXISTS idx_platform_config_center_lifecycle
    ON platform_config(center_account_id, lifecycle_status, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_config_creation_request
    ON platform_config(creation_request_id)
    WHERE creation_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_deletion_requests_platform_status_created
    ON deletion_requests(platform_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cours_config_platform ON cours_config(platform_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cours_config_platform_unique ON cours_config(platform_id);
CREATE INDEX IF NOT EXISTS idx_course_sessions_platform_scheduled ON course_sessions(platform_id, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_course_sessions_status_scheduled ON course_sessions(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_course_sessions_audio_due
    ON course_sessions(audio_generation_status, audio_generation_next_retry_at, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_course_sessions_module_day_date
    ON course_sessions(module_day_id, local_date);
CREATE INDEX IF NOT EXISTS idx_course_reminder_recipients_platform ON course_reminder_recipients(platform_id);
CREATE INDEX IF NOT EXISTS idx_course_reminder_rules_platform ON course_reminder_rules(platform_id, is_active);
CREATE INDEX IF NOT EXISTS idx_course_reminder_rule_recipients_recipient
    ON course_reminder_rule_recipients(recipient_id);
CREATE INDEX IF NOT EXISTS idx_course_reminder_deliveries_due
    ON course_reminder_deliveries(status, due_at, claimed_at);
CREATE INDEX IF NOT EXISTS idx_course_reminder_deliveries_platform
    ON course_reminder_deliveries(platform_id, session_id);
CREATE INDEX IF NOT EXISTS idx_course_reminder_deliveries_recipient
    ON course_reminder_deliveries(recipient_id);
CREATE INDEX IF NOT EXISTS idx_course_reminder_deliveries_lookup
    ON course_reminder_deliveries(session_id, rule_id, recipient_id);
CREATE INDEX IF NOT EXISTS idx_logs_platform_arrivee ON logs(platform_id, arrivee);
CREATE INDEX IF NOT EXISTS idx_logs_session_attendance
    ON logs(course_session_id, attendance_started_at);
CREATE INDEX IF NOT EXISTS idx_logs_open_presence
    ON logs(last_seen_at)
    WHERE attendance_started_at IS NOT NULL AND depart IS NULL;
CREATE INDEX IF NOT EXISTS idx_attendance_daily_exports_due
    ON attendance_daily_exports(status, available_at, next_retry_at, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_attendance_daily_exports_platform_date
    ON attendance_daily_exports(platform_id, course_date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_daily_exports_center_platform_date
    ON attendance_daily_exports(center_account_id, center_platform_number, course_date DESC);
CREATE INDEX IF NOT EXISTS idx_video_visits_platform ON video_visits(platform_id);
CREATE INDEX IF NOT EXISTS idx_video_visits_log ON video_visits(log_id);
CREATE INDEX IF NOT EXISTS idx_student_profiles_platform ON student_profiles(platform_id);
CREATE INDEX IF NOT EXISTS idx_student_attendance_platform_date ON student_attendance_records(platform_id, course_date);
CREATE INDEX IF NOT EXISTS idx_student_attendance_student ON student_attendance_records(student_profile_id);
CREATE INDEX IF NOT EXISTS idx_ai_teacher_orders_center ON ai_teacher_orders(center_account_id);
CREATE INDEX IF NOT EXISTS idx_ai_teacher_orders_platform ON ai_teacher_orders(platform_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_teacher_orders_public_id ON ai_teacher_orders(public_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_teacher_orders_creation_request
    ON ai_teacher_orders(center_account_id, creation_request_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_teacher_orders_checkout_session
    ON ai_teacher_orders(stripe_checkout_session_id)
    WHERE stripe_checkout_session_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_teacher_orders_payment_intent
    ON ai_teacher_orders(stripe_payment_intent_id)
    WHERE stripe_payment_intent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_teacher_orders_fulfillment
    ON ai_teacher_orders(fulfillment_status, updated_at);
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_jobs_platform_created ON formation_pipeline_jobs(platform_id, created_at);
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_jobs_status ON formation_pipeline_jobs(status);
CREATE INDEX IF NOT EXISTS idx_formation_knowledge_base_job ON formation_knowledge_base(job_id);
CREATE INDEX IF NOT EXISTS idx_cours_folders_platform_position ON cours_folders(platform_id, position);
CREATE INDEX IF NOT EXISTS idx_cours_folders_formation_job ON cours_folders(formation_job_id);
CREATE INDEX IF NOT EXISTS idx_cours_folders_module_day ON cours_folders(module_day_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cours_folders_job_name
    ON cours_folders(formation_job_id, name)
    WHERE formation_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cours_documents_folder ON cours_documents(folder_id);
CREATE INDEX IF NOT EXISTS idx_course_clone_folder_map_source
    ON course_clone_folder_map(source_platform_id, source_folder_id);
CREATE INDEX IF NOT EXISTS idx_content_generation_jobs_platform ON content_generation_jobs(platform_id);
CREATE INDEX IF NOT EXISTS idx_content_generation_jobs_carryover_in
    ON content_generation_jobs(carryover_in_source_folder_id)
    WHERE carryover_in_source_folder_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_content_generation_jobs_carryover_out
    ON content_generation_jobs(carryover_out_target_folder_id)
    WHERE carryover_out_target_folder_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_content_generation_segments_job ON content_generation_segments(job_id);
CREATE INDEX IF NOT EXISTS idx_content_script_annotations_folder_job ON content_script_annotations(folder_id, job_id, status);
CREATE INDEX IF NOT EXISTS idx_content_script_annotations_job ON content_script_annotations(job_id);
CREATE INDEX IF NOT EXISTS idx_content_script_rules_folder_job ON content_script_rules(folder_id, job_id);
CREATE INDEX IF NOT EXISTS idx_content_script_rules_job ON content_script_rules(job_id);
CREATE INDEX IF NOT EXISTS idx_content_review_reports_job_folder ON content_review_reports(job_id, folder_id, created_at);
CREATE INDEX IF NOT EXISTS idx_content_review_reports_folder ON content_review_reports(folder_id);
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_events_job ON formation_pipeline_events(job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_events_folder ON formation_pipeline_events(folder_id)
    WHERE folder_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_formation_modules_center_rncp ON formation_modules(center_account_id, rncp_code);
CREATE INDEX IF NOT EXISTS idx_formation_modules_source_platform ON formation_modules(source_platform_id);
CREATE INDEX IF NOT EXISTS idx_day_schedule_templates_center_status
    ON day_schedule_templates(center_account_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_day_schedule_template_blocks_template
    ON day_schedule_template_blocks(template_id, position);
CREATE INDEX IF NOT EXISTS idx_formation_module_days_center_module
    ON formation_module_days(center_account_id, module_id, day_index);
CREATE INDEX IF NOT EXISTS idx_formation_modules_canonical_reuse
    ON formation_modules(canonical_fingerprint, validated_at, id)
    WHERE status = 'validated'
      AND canonical_reuse_allowed = TRUE
      AND archived_at IS NULL
      AND canonical_fingerprint IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_formation_modules_asset_namespace
    ON formation_modules(asset_namespace)
    WHERE asset_namespace IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_formation_module_assets_module_kind
    ON formation_module_assets(module_id, asset_kind, status);
CREATE INDEX IF NOT EXISTS idx_formation_module_assets_center
    ON formation_module_assets(center_account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_formation_module_assets_blob
    ON formation_module_assets(container_name, blob_path);
CREATE INDEX IF NOT EXISTS idx_script_slide_decks_folder ON script_slide_decks(folder_id, content_job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_script_slide_decks_content_job ON script_slide_decks(content_job_id);
CREATE INDEX IF NOT EXISTS idx_script_slide_decks_formation_job ON script_slide_decks(formation_job_id)
    WHERE formation_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_script_slide_decks_platform ON script_slide_decks(platform_id)
    WHERE platform_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_jobs_auto_pilot_resume
    ON formation_pipeline_jobs(auto_pilot_locked_at, id)
    WHERE auto_pilot_enabled = TRUE
      AND auto_pilot_error IS NULL
      AND (auto_pilot_step IS NULL OR auto_pilot_step != 'done');

-- The browser only uses Supabase Auth; business data is served by Flask.
-- With no anon/authenticated policies, RLS denies direct Data API access while
-- the Postgres owner and Supabase service role used by the backend keep access.
ALTER TABLE training_center_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_schema_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE deletion_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE cours_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_schedule_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_session_postponements ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_reminder_recipients ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_reminder_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_reminder_rule_recipients ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_reminder_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_daily_exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE video_visits ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_attendance_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_teacher_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE stripe_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE formation_pipeline_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE formation_knowledge_base ENABLE ROW LEVEL SECURITY;
ALTER TABLE cours_folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE cours_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_clone_folder_map ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_generation_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_generation_segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_script_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_script_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_review_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE formation_pipeline_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE formation_modules ENABLE ROW LEVEL SECURITY;
ALTER TABLE day_schedule_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE day_schedule_template_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE formation_module_days ENABLE ROW LEVEL SECURITY;
ALTER TABLE formation_module_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE script_slide_decks ENABLE ROW LEVEL SECURITY;

-- Durable pipeline work queue. PostgreSQL is authoritative; Azure Service Bus
-- only carries small notifications that reference these fenced work-items.
CREATE TABLE IF NOT EXISTS pipeline_work_items (
    id UUID PRIMARY KEY,
    pipeline_job_id BIGINT REFERENCES formation_pipeline_jobs(id) ON DELETE CASCADE,
    folder_id BIGINT REFERENCES cours_folders(id) ON DELETE CASCADE,
    resource_key TEXT NOT NULL,
    run_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    scope_key TEXT NOT NULL DEFAULT 'pipeline',
    dedupe_key TEXT NOT NULL UNIQUE,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_owner TEXT,
    lease_token UUID,
    lease_version BIGINT NOT NULL DEFAULT 0,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    dead_lettered_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Folder-level HR audio jobs use the same durable queue even when a manually
-- created folder is not attached to a formation pipeline job. Existing queue
-- rows remain addressed by their pipeline resource key.
ALTER TABLE pipeline_work_items
    ALTER COLUMN pipeline_job_id DROP NOT NULL;
ALTER TABLE pipeline_work_items
    ADD COLUMN IF NOT EXISTS folder_id BIGINT REFERENCES cours_folders(id) ON DELETE CASCADE;
ALTER TABLE pipeline_work_items
    ADD COLUMN IF NOT EXISTS resource_key TEXT;
UPDATE pipeline_work_items
SET resource_key = 'pipeline:' || pipeline_job_id::text
WHERE resource_key IS NULL;
ALTER TABLE pipeline_work_items
    ALTER COLUMN resource_key SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pipeline_work_items_due
    ON pipeline_work_items(status, available_at, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_pipeline_work_items_job
    ON pipeline_work_items(pipeline_job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pipeline_work_items_folder
    ON pipeline_work_items(folder_id, created_at);

-- Older deployments could enqueue two runs for the same pipeline scope. Keep
-- the item already doing useful work (then a retry, then the oldest queued
-- item), fence/cancel the others, and make the invariant database-enforced.
WITH ranked_active AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY pipeline_job_id, scope_key
               ORDER BY CASE status
                            WHEN 'running' THEN 0
                            WHEN 'retry_scheduled' THEN 1
                            ELSE 2
                        END,
                        created_at,
                        id
           ) AS active_rank
    FROM pipeline_work_items
    WHERE status IN ('queued', 'retry_scheduled', 'running')
)
UPDATE pipeline_work_items AS item
SET status = 'cancelled',
    cancelled_at = COALESCE(item.cancelled_at, NOW()),
    updated_at = NOW(),
    lease_owner = NULL,
    lease_token = NULL,
    lease_expires_at = NULL,
    last_error = COALESCE(
        item.last_error,
        'Superseded while enforcing one active pipeline item per scope'
    )
FROM ranked_active
WHERE item.id = ranked_active.id
  AND ranked_active.active_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_work_items_active_scope
    ON pipeline_work_items(pipeline_job_id, scope_key)
    WHERE status IN ('queued', 'retry_scheduled', 'running');
CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_work_items_active_resource_scope
    ON pipeline_work_items(resource_key, scope_key)
    WHERE status IN ('queued', 'retry_scheduled', 'running');

CREATE TABLE IF NOT EXISTS pipeline_work_outbox (
    id UUID PRIMARY KEY,
    delivery_id UUID NOT NULL UNIQUE,
    work_item_id UUID NOT NULL REFERENCES pipeline_work_items(id) ON DELETE CASCADE,
    payload_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    publish_attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_work_outbox_due
    ON pipeline_work_outbox(status, available_at, created_at);

ALTER TABLE pipeline_work_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_work_outbox ENABLE ROW LEVEL SECURITY;

-- Security cleanup for databases provisioned by an older debug build. Keep the
-- nullable compatibility column for a non-breaking rollout, but never retain
-- credentials in clear text. It can be dropped in a later schema version.
UPDATE training_center_accounts
SET password_debug_plaintext = NULL
WHERE password_debug_plaintext IS NOT NULL;
