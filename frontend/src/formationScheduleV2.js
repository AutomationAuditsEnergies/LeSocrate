import { normalizeScheduleTemplate } from './dayScheduleTemplates.js'

export const TRAINING_WEEKDAYS = Object.freeze([
  Object.freeze({ id: 1, short: 'Lun.', label: 'Lundi' }),
  Object.freeze({ id: 2, short: 'Mar.', label: 'Mardi' }),
  Object.freeze({ id: 3, short: 'Mer.', label: 'Mercredi' }),
  Object.freeze({ id: 4, short: 'Jeu.', label: 'Jeudi' }),
  Object.freeze({ id: 5, short: 'Ven.', label: 'Vendredi' }),
  Object.freeze({ id: 6, short: 'Sam.', label: 'Samedi' }),
  Object.freeze({ id: 7, short: 'Dim.', label: 'Dimanche' }),
])

const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/

function asUtcDate(value) {
  if (!ISO_DATE_PATTERN.test(String(value || ''))) return null
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  if (
    date.getUTCFullYear() !== year
    || date.getUTCMonth() !== month - 1
    || date.getUTCDate() !== day
  ) return null
  return date
}

export function isValidCalendarDate(value) {
  return Boolean(asUtcDate(value))
}

function toIsoDate(date) {
  return date.toISOString().slice(0, 10)
}

export function addCalendarDays(value, amount) {
  const date = asUtcDate(value)
  if (!date) return ''
  date.setUTCDate(date.getUTCDate() + Number(amount || 0))
  return toIsoDate(date)
}

export function normalizeSelectedTrainingDates(values) {
  return [...new Set(
    (Array.isArray(values) ? values : [])
      .map((value) => String(value || '').trim())
      .filter((value) => asUtcDate(value)),
  )].sort()
}

export function prefillTrainingDates({
  startDate,
  weeks,
  daysPerWeek,
  preferredWeekdays,
  limit = null,
}) {
  const first = asUtcDate(startDate)
  const weekCount = Math.max(0, Math.trunc(Number(weeks) || 0))
  const weeklyCount = Math.max(0, Math.min(7, Math.trunc(Number(daysPerWeek) || 0)))
  const preferred = [...new Set(
    (Array.isArray(preferredWeekdays) ? preferredWeekdays : [])
      .map(Number)
      .filter((day) => day >= 1 && day <= 7),
  )]
  const maximum = limit === null
    ? Number.POSITIVE_INFINITY
    : Math.max(0, Math.trunc(Number(limit) || 0))
  if (!first || !weekCount || !weeklyCount || preferred.length !== weeklyCount || !maximum) {
    return []
  }

  const dates = []
  const horizon = weekCount * 7
  for (let offset = 0; offset < horizon && dates.length < maximum; offset += 1) {
    const date = new Date(first)
    date.setUTCDate(first.getUTCDate() + offset)
    const isoWeekday = date.getUTCDay() === 0 ? 7 : date.getUTCDay()
    if (preferred.includes(isoWeekday)) dates.push(toIsoDate(date))
  }
  return dates
}

export function getCalendarMonthDays(year, monthIndex) {
  const first = new Date(Date.UTC(year, monthIndex, 1))
  const firstIsoWeekday = first.getUTCDay() === 0 ? 7 : first.getUTCDay()
  const gridStart = new Date(first)
  gridStart.setUTCDate(first.getUTCDate() - (firstIsoWeekday - 1))

  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(gridStart)
    date.setUTCDate(gridStart.getUTCDate() + index)
    return {
      date: toIsoDate(date),
      day: date.getUTCDate(),
      inMonth: date.getUTCMonth() === monthIndex,
      isoWeekday: date.getUTCDay() === 0 ? 7 : date.getUTCDay(),
    }
  })
}

export function getTemplateFirstStartMinute(template) {
  const normalized = normalizeScheduleTemplate(template || {})
  return Number(normalized.blocks[0]?.start_minute ?? (9 * 60))
}

function timeZoneParts(date, timeZone) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  return Object.fromEntries(
    parts
      .filter((part) => part.type !== 'literal')
      .map((part) => [part.type, Number(part.value)]),
  )
}

function sameWallTime(parts, desired) {
  return (
    parts.year === desired.year
    && parts.month === desired.month
    && parts.day === desired.day
    && parts.hour === desired.hour
    && parts.minute === desired.minute
  )
}

export function dateTimeInTimeZone(
  dateValue,
  startMinute,
  timeZone = 'Europe/Paris',
) {
  const day = asUtcDate(dateValue)
  const minute = Number(startMinute)
  if (!day || !Number.isInteger(minute) || minute < 0 || minute >= 24 * 60) {
    return null
  }
  const desired = {
    year: day.getUTCFullYear(),
    month: day.getUTCMonth() + 1,
    day: day.getUTCDate(),
    hour: Math.floor(minute / 60),
    minute: minute % 60,
  }
  const wallClockUtc = Date.UTC(
    desired.year,
    desired.month - 1,
    desired.day,
    desired.hour,
    desired.minute,
  )
  let candidate = wallClockUtc
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const observed = timeZoneParts(new Date(candidate), timeZone)
    const observedWallClockUtc = Date.UTC(
      observed.year,
      observed.month - 1,
      observed.day,
      observed.hour,
      observed.minute,
    )
    candidate += wallClockUtc - observedWallClockUtc
  }
  const result = new Date(candidate)
  if (!sameWallTime(timeZoneParts(result, timeZone), desired)) return null

  // A repeated wall-clock time during the autumn DST transition is
  // intentionally rejected, matching the server's ``is_dst=None`` policy.
  for (const delta of [-3_600_000, 3_600_000]) {
    if (sameWallTime(timeZoneParts(new Date(candidate + delta), timeZone), desired)) {
      return null
    }
  }
  return result
}

export function getFirstSessionDateTime(
  selectedDates,
  assignments,
  templates,
  timeZone = 'Europe/Paris',
) {
  const [firstDate] = normalizeSelectedTrainingDates(selectedDates)
  if (!firstDate) return null
  const templateId = assignments?.[firstDate]
  const template = (Array.isArray(templates) ? templates : []).find(
    (item) => String(item.id) === String(templateId),
  )
  const startMinute = getTemplateFirstStartMinute(template)
  return dateTimeInTimeZone(firstDate, startMinute, timeZone)
}

export function hasMinimumLeadTime(
  selectedDates,
  assignments,
  templates,
  now = new Date(),
  minimumHours = 48,
) {
  const firstSession = getFirstSessionDateTime(selectedDates, assignments, templates)
  if (!firstSession) return false
  return firstSession.getTime() - now.getTime() >= minimumHours * 60 * 60 * 1000
}

export function fillUnassignedTemplate(assignments, selectedDates, templateId) {
  if (templateId === null || templateId === undefined || templateId === '') {
    return { ...(assignments || {}) }
  }
  const next = { ...(assignments || {}) }
  normalizeSelectedTrainingDates(selectedDates).forEach((date) => {
    if (next[date] === undefined || next[date] === null || next[date] === '') {
      next[date] = String(templateId)
    }
  })
  return next
}

export function reconcileTemplateAssignments(assignments, selectedDates) {
  const allowedDates = new Set(normalizeSelectedTrainingDates(selectedDates))
  return Object.fromEntries(
    Object.entries(assignments || {})
      .filter(([date, templateId]) => allowedDates.has(date) && templateId !== '')
      .map(([date, templateId]) => [date, String(templateId)]),
  )
}

export function validateFormationScheduleV2({
  selectedDates,
  assignments,
  templates,
  reuse = false,
  expectedDayCount = null,
  now = new Date(),
}) {
  const dates = normalizeSelectedTrainingDates(selectedDates)
  const normalizedAssignments = reconcileTemplateAssignments(assignments, dates)
  const errors = []

  if (!dates.length) errors.push('Sélectionnez au moins une date de formation.')
  if (reuse && Number(expectedDayCount) !== dates.length) {
    errors.push(
      `Ce module contient ${Number(expectedDayCount) || 0} journées. Sélectionnez exactement le même nombre de dates.`,
    )
  }

  if (!reuse) {
    const templateIds = new Set((Array.isArray(templates) ? templates : []).map(
      (template) => String(template.id),
    ))
    const missingDates = dates.filter((date) => !normalizedAssignments[date])
    const unknownDates = dates.filter(
      (date) => normalizedAssignments[date] && !templateIds.has(normalizedAssignments[date]),
    )
    const templatesById = new Map((Array.isArray(templates) ? templates : []).map(
      (template) => [String(template.id), template],
    ))
    const unhashedDates = dates.filter((date) => {
      const template = templatesById.get(normalizedAssignments[date])
      return template && !/^[0-9a-f]{64}$/i.test(
        String(template.blocks_hash || '').trim(),
      )
    })
    if (missingDates.length) {
      errors.push(`Affectez un template aux ${missingDates.length} journée${missingDates.length > 1 ? 's' : ''} restante${missingDates.length > 1 ? 's' : ''}.`)
    }
    if (unknownDates.length) {
      errors.push('Une affectation utilise un template qui n’est plus disponible.')
    }
    if (unhashedDates.length) {
      errors.push('Rechargez la bibliothèque avant de confirmer le planning.')
    }
    if (dates.length && !hasMinimumLeadTime(dates, normalizedAssignments, templates, now)) {
      errors.push('La première journée doit commencer au moins 48 h après la validation.')
    }
  }

  return {
    valid: errors.length === 0,
    errors,
    selectedDates: dates,
    assignments: normalizedAssignments,
  }
}

export function serializeFormationScheduleV2({
  selectedDates,
  assignments,
  templates = [],
  reuse = false,
}) {
  const dates = normalizeSelectedTrainingDates(selectedDates)
  const payload = {
    schedule_schema_version: 2,
    selected_dates: dates,
  }
  if (!reuse) {
    const normalizedAssignments = reconcileTemplateAssignments(assignments, dates)
    payload.template_assignments = normalizedAssignments
    const assignedIds = new Set(Object.values(normalizedAssignments).map(String))
    payload.template_hashes = Object.fromEntries(
      (Array.isArray(templates) ? templates : [])
        .filter((template) => assignedIds.has(String(template.id)))
        .map((template) => [
          String(template.id),
          String(template.blocks_hash || '').trim(),
        ]),
    )
  }
  return payload
}
