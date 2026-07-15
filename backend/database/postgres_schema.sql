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
    teacher_name TEXT,
    teacher_color TEXT,
    creation_request_id TEXT,
    UNIQUE(center_account_id, slug)
);

ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS teacher_name TEXT;
ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS teacher_color TEXT;
ALTER TABLE platform_config
    ADD COLUMN IF NOT EXISTS creation_request_id TEXT;

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
    audio_job_id BIGINT,
    audio_folder_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(platform_id, session_index)
);

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
    ADD COLUMN IF NOT EXISTS audio_job_id BIGINT;
ALTER TABLE course_sessions
    ADD COLUMN IF NOT EXISTS audio_folder_id BIGINT;

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

CREATE TABLE IF NOT EXISTS formation_pipeline_jobs (
    id BIGSERIAL PRIMARY KEY,
    platform_id BIGINT NOT NULL REFERENCES platform_config(id) ON DELETE CASCADE,
    tp_name TEXT NOT NULL,
    rncp_code TEXT,
    total_hours INTEGER NOT NULL,
    nb_days INTEGER NOT NULL,
    reac_text TEXT,
    rc_text TEXT,
    rome_text TEXT,
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
    auto_pilot_use_cc BOOLEAN NOT NULL DEFAULT FALSE,
    auto_pilot_skip_vs BOOLEAN NOT NULL DEFAULT FALSE,
    auto_pilot_generate_audio BOOLEAN NOT NULL DEFAULT FALSE,
    auto_pilot_volume_done BOOLEAN NOT NULL DEFAULT FALSE,
    auto_pilot_post_review_docs_done BOOLEAN NOT NULL DEFAULT FALSE,
    auto_pilot_error TEXT,
    auto_pilot_locked_at TIMESTAMPTZ,
    auto_pilot_lock_owner TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
    humanized BOOLEAN NOT NULL DEFAULT FALSE,
    humanization_error TEXT,
    humanization_signature TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(job_id, sub_part_index, passe)
);

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    validated_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_config_creation_request
    ON platform_config(creation_request_id)
    WHERE creation_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_deletion_requests_platform_status_created
    ON deletion_requests(platform_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cours_config_platform ON cours_config(platform_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cours_config_platform_unique ON cours_config(platform_id);
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
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_jobs_platform_created ON formation_pipeline_jobs(platform_id, created_at);
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_jobs_status ON formation_pipeline_jobs(status);
CREATE INDEX IF NOT EXISTS idx_formation_knowledge_base_job ON formation_knowledge_base(job_id);
CREATE INDEX IF NOT EXISTS idx_cours_folders_platform_position ON cours_folders(platform_id, position);
CREATE INDEX IF NOT EXISTS idx_cours_folders_formation_job ON cours_folders(formation_job_id);
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
ALTER TABLE platform_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE deletion_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE cours_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_schedule_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE course_reminder_recipients ENABLE ROW LEVEL SECURITY;
ALTER TABLE logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE video_visits ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_attendance_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_teacher_orders ENABLE ROW LEVEL SECURITY;
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
