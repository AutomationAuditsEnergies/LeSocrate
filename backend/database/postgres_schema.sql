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
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_jobs_platform_created ON formation_pipeline_jobs(platform_id, created_at);
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_jobs_status ON formation_pipeline_jobs(status);
CREATE INDEX IF NOT EXISTS idx_formation_knowledge_base_job ON formation_knowledge_base(job_id);
CREATE INDEX IF NOT EXISTS idx_cours_folders_platform_position ON cours_folders(platform_id, position);
CREATE INDEX IF NOT EXISTS idx_cours_folders_formation_job ON cours_folders(formation_job_id);
CREATE INDEX IF NOT EXISTS idx_cours_documents_folder ON cours_documents(folder_id);
CREATE INDEX IF NOT EXISTS idx_content_generation_jobs_platform ON content_generation_jobs(platform_id);
CREATE INDEX IF NOT EXISTS idx_content_generation_segments_job ON content_generation_segments(job_id);
CREATE INDEX IF NOT EXISTS idx_content_script_annotations_folder_job ON content_script_annotations(folder_id, job_id, status);
CREATE INDEX IF NOT EXISTS idx_content_script_rules_folder_job ON content_script_rules(folder_id, job_id);
CREATE INDEX IF NOT EXISTS idx_content_review_reports_job_folder ON content_review_reports(job_id, folder_id, created_at);
CREATE INDEX IF NOT EXISTS idx_formation_pipeline_events_job ON formation_pipeline_events(job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_formation_modules_center_rncp ON formation_modules(center_account_id, rncp_code);
CREATE INDEX IF NOT EXISTS idx_formation_modules_source_platform ON formation_modules(source_platform_id);
CREATE INDEX IF NOT EXISTS idx_script_slide_decks_folder ON script_slide_decks(folder_id, content_job_id, created_at);
