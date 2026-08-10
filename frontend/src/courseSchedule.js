export const AUDIO_STATUS_META = {
  scheduled: { label: 'Audios manquants', color: '#475569', background: '#f1f5f9' },
  preparing: { label: 'Audios en cours de génération', color: '#3f3f46', background: '#f4f4f5' },
  ready: { label: 'Audios générés et disponibles', color: '#047857', background: '#d1fae5' },
  error: { label: 'Audios en erreur', color: '#b91c1c', background: '#fee2e2' },
  waiting_content: { label: 'Audios manquants', color: '#92400e', background: '#fef3c7' },
  cancelled: { label: 'Annulée', color: '#64748b', background: '#e2e8f0' },
}

export function getAudioStatusMeta(status) {
  return AUDIO_STATUS_META[status] || AUDIO_STATUS_META.scheduled
}

export function getNextCourseSession(platform = {}) {
  return platform.course_schedule?.next_session || null
}

export function scheduleSelectionIsValid({ selectedWeekdays, expectedWeekdayCount }) {
  const selected = Array.isArray(selectedWeekdays) ? selectedWeekdays.length : 0
  const expected = Number(expectedWeekdayCount || 0)
  return selected > 0 && (!expected || selected === expected)
}
