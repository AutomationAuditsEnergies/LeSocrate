const PIPELINE_PROGRESS_BY_STEP = {
  reac: 12,
  kb: 24,
  global: 36,
  daily: 48,
  content: 64,
  review: 78,
  post_review_docs: 88,
  slides: 96,
  audio: 98,
  done: 100,
}

const PIPELINE_PROGRESS_BY_STATUS = {
  init: 8,
  reac_ready: 18,
  kb_building: 24,
  global_generating: 34,
  global_ready: 42,
  global_validated: 46,
  daily_splitting: 50,
  daily_ready: 56,
  daily_validated: 60,
  tts_launched: 90,
  text_ready: 100,
  audio_running: 98,
  audio_launched: 100,
  audio_completed: 100,
  completed: 100,
}

export function getHiddenPipelineProgress(platform = {}) {
  if (Number.isFinite(Number(platform.teacher_preparation?.progress))) {
    return Math.max(1, Math.min(100, Number(platform.teacher_preparation.progress)))
  }
  const step = String(platform.pipeline_auto_pilot_step || '').trim()
  if (step && Object.prototype.hasOwnProperty.call(PIPELINE_PROGRESS_BY_STEP, step)) {
    return PIPELINE_PROGRESS_BY_STEP[step]
  }
  const status = String(platform.pipeline_status || platform.status || '').trim()
  if (status && Object.prototype.hasOwnProperty.call(PIPELINE_PROGRESS_BY_STATUS, status)) {
    return PIPELINE_PROGRESS_BY_STATUS[status]
  }
  return 8
}

export function getTeacherPreparation(platform = {}) {
  if (platform.teacher_preparation?.status) return platform.teacher_preparation

  const status = platform.status === 'error'
    ? 'failed'
    : (platform.status === 'pending' ? 'preparing' : 'ready')
  return {
    status,
    progress: getHiddenPipelineProgress(platform),
    stage: status === 'failed'
      ? 'Préparation interrompue'
      : (status === 'preparing' ? 'Préparation des cours' : 'Professeur prêt'),
    can_retry: status === 'failed' && Boolean(platform.source_formation_id),
  }
}
