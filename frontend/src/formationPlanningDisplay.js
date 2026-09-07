const positiveNumber = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

const pluralize = (value, singular, plural = `${singular}s`) => (
  `${value} ${Number(value) > 1 ? plural : singular}`
)

export function formatCourseMinutes(value) {
  const minutes = positiveNumber(value)
  if (!minutes) return null
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return remainder ? `${hours} h ${remainder}` : `${hours} h`
}

export function formatPlanningSummary(
  summary,
  { fallbackHours = null, fallbackDays = null, scheduleSchemaVersion = 1 } = {},
) {
  const dayCount = positiveNumber(summary?.day_count)
  const courseCount = positiveNumber(summary?.course_count)
  const courseMinutes = positiveNumber(summary?.course_minutes)

  if (summary?.source === 'schedule_v2' && dayCount && courseCount && courseMinutes) {
    const segments = [pluralize(dayCount, 'journée')]
    const dailyCount = positiveNumber(summary.uniform_daily_course_count)
    const courseDuration = positiveNumber(summary.uniform_course_duration_minutes)

    if (dailyCount) {
      const perDay = pluralize(dailyCount, 'cours', 'cours')
      segments.push(courseDuration
        ? `${perDay} de ${formatCourseMinutes(courseDuration)}/jour`
        : `${perDay}/jour`)
    } else {
      segments.push(`${pluralize(courseCount, 'cours', 'cours')} planifiés`)
    }
    segments.push(`${formatCourseMinutes(courseMinutes)} de cours`)
    return segments.join(' · ')
  }

  const days = positiveNumber(fallbackDays)
  if (Number(scheduleSchemaVersion) === 2) {
    return days
      ? `${pluralize(days, 'journée')} · durée des cours indisponible`
      : 'Planning détaillé indisponible'
  }

  const hours = positiveNumber(fallbackHours)
  const segments = []
  if (hours) segments.push(`${hours} h`)
  if (days) segments.push(pluralize(days, 'journée'))
  return segments.join(' · ') || 'Durée à confirmer'
}

export function formatJobPlanning(job) {
  return formatPlanningSummary(job?.planning_summary, {
    fallbackHours: job?.total_hours,
    fallbackDays: job?.nb_days,
    scheduleSchemaVersion: job?.schedule_schema_version,
  })
}
