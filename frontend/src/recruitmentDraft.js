const STORAGE_KEY = 'center_active_recruitment_draft_v2'

export const RECRUITMENT_REQUIRED_FIELDS = Object.freeze([
  'trainingName',
  'rncpCode',
  'startDate',
  'durationValue',
  'durationUnit',
  'weeklyCourseCount',
  'teachingDays',
])

const makeId = () => (
  globalThis.crypto?.randomUUID?.()
  || `recruitment_${Date.now()}_${Math.random().toString(36).slice(2)}`
)

export function createRecruitmentDraft(overrides = {}) {
  return {
    id: makeId(),
    status: 'active',
    trainingName: '',
    rncpCode: '',
    startDate: '',
    durationValue: '',
    durationUnit: '',
    weeklyCourseCount: '',
    teachingDays: [],
    selectedDates: [],
    templateAssignments: {},
    progress: 'conversation',
    teacherName: 'Professeur IA',
    teacherColor: 'violet',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...overrides,
  }
}

export function normalizeRecruitmentDraft(value) {
  if (!value || typeof value !== 'object' || value.status !== 'active') return null
  return createRecruitmentDraft({
    ...value,
    id: String(value.id || makeId()),
    rncpCode: String(value.rncpCode || '').replace(/\D/g, ''),
    teachingDays: Array.isArray(value.teachingDays) ? [...new Set(value.teachingDays)] : [],
    selectedDates: Array.isArray(value.selectedDates) ? [...new Set(value.selectedDates)].sort() : [],
    templateAssignments: value.templateAssignments && typeof value.templateAssignments === 'object'
      ? { ...value.templateAssignments }
      : {},
  })
}

export function loadActiveRecruitmentDraft() {
  try {
    return normalizeRecruitmentDraft(JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'))
  } catch {
    return null
  }
}

export function saveActiveRecruitmentDraft(draft) {
  const normalized = normalizeRecruitmentDraft({
    ...draft,
    status: 'active',
    updatedAt: new Date().toISOString(),
  })
  if (normalized) localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized))
  return normalized
}

export function deleteActiveRecruitmentDraft() {
  localStorage.removeItem(STORAGE_KEY)
}

export function recruitmentMissingFields(draft) {
  const value = normalizeRecruitmentDraft(draft) || createRecruitmentDraft()
  return RECRUITMENT_REQUIRED_FIELDS.filter((field) => {
    if (field === 'teachingDays') {
      return value.teachingDays.length !== Number(value.weeklyCourseCount || 0)
    }
    if (field === 'durationValue') return Number(value.durationValue || 0) <= 0
    return !String(value[field] || '').trim()
  })
}

export function recruitmentApproximateDayCount(draft) {
  const duration = Math.max(0, Number(draft?.durationValue || 0))
  const weeks = draft?.durationUnit === 'mois' ? duration * 4.345 : duration
  return Math.max(1, Math.round(weeks * Math.max(1, Number(draft?.weeklyCourseCount || 1))))
}

export function isNewRecruitmentRequest(message) {
  const text = String(message || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  return /\b(nouveau|nouvelle|autre)\b.{0,32}\b(recrutement|formation|professeur|journee)\b|\b(recommencer|repartir de zero)\b/.test(text)
}

export const RECRUITMENT_DRAFT_STORAGE_KEY = STORAGE_KEY
