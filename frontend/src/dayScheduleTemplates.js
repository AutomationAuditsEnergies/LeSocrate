export const DAY_SCHEDULE_RULES = Object.freeze({
  course: Object.freeze({ min: 35, max: 90, default: 60 }),
  qa: Object.freeze({ min: 10, max: 30, default: 15 }),
  shortPause: Object.freeze({ min: 10, max: 30, default: 15 }),
  lunchPause: Object.freeze({ min: 60, max: 180, default: 60 }),
  minCourses: 1,
  maxCourses: 10,
  minCourseMinutes: 35,
  minDayMinutes: 35,
})

const DEFAULT_START_MINUTE = 9 * 60
const BLOCK_TYPES = new Set(['course', 'qa', 'pause'])

function finiteMinute(value, fallback = 0) {
  if (value === null || value === undefined || value === '') return fallback
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.round(parsed) : fallback
}

export function formatScheduleMinute(value) {
  const minute = finiteMinute(value)
  const hours = Math.floor(minute / 60)
  const minutes = Math.abs(minute % 60)
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

export function parseScheduleTime(value) {
  const match = String(value || '').match(/^(\d{1,2}):(\d{2})$/)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null
  return (hours * 60) + minutes
}

function blockLabel(type, pauseKind = null) {
  if (type === 'course') return 'Cours vocal'
  if (type === 'qa') return 'Questions-réponses'
  return pauseKind === 'lunch' ? 'Pause déjeuner' : 'Pause'
}

function canonicalBlock(block, index, startMinute) {
  const blockType = BLOCK_TYPES.has(block?.block_type) ? block.block_type : 'course'
  const pauseKind = blockType === 'pause'
    ? (block?.pause_kind === 'lunch' ? 'lunch' : 'short')
    : null
  const duration = Math.max(1, finiteMinute(
    block?.duration_minutes,
    finiteMinute(block?.end_minute) - finiteMinute(block?.start_minute),
  ))
  const start = Number.isFinite(Number(startMinute))
    ? finiteMinute(startMinute)
    : finiteMinute(block?.start_minute, DEFAULT_START_MINUTE)
  return {
    id: block?.id,
    block_key: block?.block_key || `block-${index + 1}`,
    position: index,
    block_type: blockType,
    pause_kind: pauseKind,
    start_minute: start,
    end_minute: start + duration,
    duration_minutes: duration,
    metadata: block?.metadata && typeof block.metadata === 'object' ? block.metadata : {},
    label: blockLabel(blockType, pauseKind),
  }
}

export function reflowScheduleBlocks(blocks, startMinute = null) {
  const source = Array.isArray(blocks) ? blocks : []
  let cursor = startMinute === null
    ? finiteMinute(source[0]?.start_minute, DEFAULT_START_MINUTE)
    : finiteMinute(startMinute, DEFAULT_START_MINUTE)
  return source.map((block, index) => {
    const next = canonicalBlock(block, index, cursor)
    cursor = next.end_minute
    return next
  })
}

function newScheduleBlock(type, pauseKind = null, ordinal = 1) {
  const isLunch = type === 'pause' && pauseKind === 'lunch'
  const duration = type === 'course'
    ? DAY_SCHEDULE_RULES.course.default
    : type === 'qa'
      ? DAY_SCHEDULE_RULES.qa.default
      : isLunch
        ? DAY_SCHEDULE_RULES.lunchPause.default
        : DAY_SCHEDULE_RULES.shortPause.default
  return {
    block_key: `${type}-${Date.now()}-${ordinal}`,
    block_type: type,
    pause_kind: type === 'pause' ? (isLunch ? 'lunch' : 'short') : null,
    duration_minutes: duration,
  }
}

export function createDefaultScheduleBlocks(startMinute = DEFAULT_START_MINUTE) {
  return reflowScheduleBlocks([newScheduleBlock('course')], startMinute)
}

export function createScheduleTemplateDraft(name = '') {
  return {
    id: null,
    name,
    status: 'draft',
    used_at: null,
    locked_at: null,
    blocks: createDefaultScheduleBlocks(),
  }
}

export function createEmptyScheduleTemplateDraft(name = '') {
  return { ...createScheduleTemplateDraft(name), blocks: [] }
}

export function isScheduleTemplateUsed(template) {
  return Boolean(
    template?.used_at
    || template?.locked_at
    || ['used', 'locked', 'immutable'].includes(String(template?.status || '').toLowerCase()),
  )
}

export function normalizeScheduleTemplate(template) {
  const blocks = [...(Array.isArray(template?.blocks) ? template.blocks : [])]
    .sort((left, right) => finiteMinute(left?.position) - finiteMinute(right?.position))
  let cursor = DEFAULT_START_MINUTE
  const normalizedBlocks = blocks.map((block, index) => {
    const hasStart = Number.isFinite(Number(block?.start_minute))
    const hasEnd = Number.isFinite(Number(block?.end_minute))
    const normalized = canonicalBlock(block, index, hasStart ? Number(block.start_minute) : cursor)
    const next = hasEnd ? { ...normalized, end_minute: finiteMinute(block.end_minute) } : normalized
    cursor = next.end_minute
    return next
  })
  return {
    ...template,
    id: template?.id ?? null,
    name: String(template?.name || ''),
    status: template?.status || (isScheduleTemplateUsed(template) ? 'used' : 'draft'),
    blocks: normalizedBlocks,
  }
}

export function cloneScheduleTemplateAsDraft(template) {
  const source = normalizeScheduleTemplate(template)
  return {
    ...createScheduleTemplateDraft(`Copie de ${source.name || 'modèle sans nom'}`),
    blocks: source.blocks.map((block) => ({
      ...block,
      id: undefined,
      metadata: { ...block.metadata },
    })),
  }
}

export function getScheduleStats(blocks) {
  const source = Array.isArray(blocks) ? blocks : []
  const courses = source.filter((block) => block.block_type === 'course')
  const first = source[0]
  const last = source[source.length - 1]
  return {
    blockCount: source.length,
    courseCount: courses.length,
    courseMinutes: courses.reduce((sum, block) => sum + finiteMinute(block.duration_minutes), 0),
    dayMinutes: first && last
      ? finiteMinute(last.end_minute) - finiteMinute(first.start_minute)
      : 0,
    lunchCount: source.filter(
      (block) => block.block_type === 'pause' && block.pause_kind === 'lunch',
    ).length,
    hasFinalPause: source.at(-1)?.block_type === 'pause',
  }
}

export function getScheduleBlockDurationBounds(block) {
  if (block.block_type === 'course') return DAY_SCHEDULE_RULES.course
  if (block.block_type === 'qa') return DAY_SCHEDULE_RULES.qa
  return block.pause_kind === 'lunch'
    ? DAY_SCHEDULE_RULES.lunchPause
    : DAY_SCHEDULE_RULES.shortPause
}

function validateSequence(blocks, blockErrors, errors) {
  const auxiliarySinceCourse = new Set()
  blocks.forEach((block, index) => {
    const key = block.block_key || `block-${index + 1}`
    const messages = blockErrors[key] || []
    if (index === 0 && block.block_type !== 'course') {
      messages.push('La journée doit commencer par un cours vocal.')
    }
    if (block.block_type === 'course') {
      auxiliarySinceCourse.clear()
    } else if (auxiliarySinceCourse.has(block.block_type)) {
      messages.push('Ce bloc facultatif est déjà présent depuis le dernier cours.')
    } else if (auxiliarySinceCourse.size >= 2) {
      messages.push('Deux blocs facultatifs au maximum sont autorisés entre deux cours.')
    } else {
      auxiliarySinceCourse.add(block.block_type)
    }
    if (messages.length) blockErrors[key] = messages
  })
  if (blocks.at(-1)?.block_type === 'pause') {
    errors.push('Une journée peut finir par un cours ou un Q&R, jamais par une pause.')
  }
}

export function validateScheduleTemplate(template) {
  const normalized = normalizeScheduleTemplate(template)
  const { blocks } = normalized
  const stats = getScheduleStats(blocks)
  const errors = []
  const blockErrors = {}

  if (!normalized.name.trim()) errors.push('Donnez un nom au template.')
  if (!blocks.length) errors.push('Ajoutez au moins un cours vocal.')
  if (stats.courseCount < DAY_SCHEDULE_RULES.minCourses) {
    errors.push(`Ajoutez au moins ${DAY_SCHEDULE_RULES.minCourses} cours vocal.`)
  }
  if (stats.courseCount > DAY_SCHEDULE_RULES.maxCourses) {
    errors.push(`Limitez la journée à ${DAY_SCHEDULE_RULES.maxCourses} cours vocaux.`)
  }
  if (stats.lunchCount > 1) errors.push('Une seule pause déjeuner est autorisée.')

  blocks.forEach((block, index) => {
    const key = block.block_key || `block-${index + 1}`
    const messages = []
    const rule = getScheduleBlockDurationBounds(block)
    const duration = finiteMinute(block.duration_minutes)
    if (duration < rule.min || duration > rule.max) {
      messages.push(`Durée autorisée : ${rule.min} à ${rule.max} min.`)
    }
    if (block.start_minute < 0 || block.start_minute >= 24 * 60) {
      messages.push('L’heure de début doit appartenir à la journée.')
    }
    if (block.end_minute > 24 * 60) messages.push('Le bloc doit se terminer avant minuit.')
    if (block.end_minute - block.start_minute !== duration) {
      messages.push('Les horaires ne correspondent pas à la durée.')
    }
    if (index > 0 && blocks[index - 1].end_minute !== block.start_minute) {
      messages.push('Aucun espace ni chevauchement n’est autorisé.')
    }
    if (messages.length) blockErrors[key] = messages
  })
  validateSequence(blocks, blockErrors, errors)

  return {
    valid: errors.length === 0 && Object.keys(blockErrors).length === 0,
    errors,
    blockErrors,
    stats,
    template: normalized,
  }
}

export function getAllowedNextScheduleBlocks(blocks) {
  const source = reflowScheduleBlocks(blocks)
  const stats = getScheduleStats(source)
  const sinceLastCourse = []
  for (let index = source.length - 1; index >= 0; index -= 1) {
    if (source[index].block_type === 'course') break
    sinceLastCourse.unshift(source[index].block_type)
  }
  const auxiliary = new Set(sinceLastCourse)
  const hasCourse = stats.courseCount > 0
  const atCourseLimit = stats.courseCount >= DAY_SCHEDULE_RULES.maxCourses
  const atMidnight = source.at(-1)?.end_minute >= 24 * 60

  return {
    course: {
      allowed: !atCourseLimit && !atMidnight,
      reason: atCourseLimit
        ? `Maximum ${DAY_SCHEDULE_RULES.maxCourses} cours par journée.`
        : atMidnight ? 'La journée atteint déjà minuit.' : '',
    },
    qa: {
      allowed: hasCourse && !auxiliary.has('qa') && auxiliary.size < 2 && !atMidnight,
      reason: !hasCourse
        ? 'Commencez la journée par un cours.'
        : auxiliary.has('qa')
          ? 'Un seul Q&R est autorisé entre deux cours.'
          : auxiliary.size >= 2
            ? 'Ajoutez maintenant un cours.'
            : atMidnight ? 'La journée atteint déjà minuit.' : '',
    },
    pause: {
      allowed: hasCourse && !auxiliary.has('pause') && auxiliary.size < 2 && !atMidnight,
      reason: !hasCourse
        ? 'Commencez la journée par un cours.'
        : auxiliary.has('pause')
          ? 'Une seule pause est autorisée entre deux cours.'
          : auxiliary.size >= 2
            ? 'Ajoutez maintenant un cours.'
            : atMidnight ? 'La journée atteint déjà minuit.' : '',
    },
    lunch: {
      allowed: hasCourse
        && !auxiliary.has('pause')
        && auxiliary.size < 2
        && stats.lunchCount === 0
        && !atMidnight,
      reason: stats.lunchCount > 0
        ? 'Une seule pause déjeuner est autorisée.'
        : !hasCourse
          ? 'Commencez la journée par un cours.'
          : auxiliary.has('pause')
            ? 'Une pause est déjà présente depuis le dernier cours.'
            : auxiliary.size >= 2
              ? 'Ajoutez maintenant un cours.'
              : atMidnight ? 'La journée atteint déjà minuit.' : '',
    },
  }
}

export function appendScheduleBlock(blocks, blockType, pauseKind = null, startMinute = null) {
  const source = reflowScheduleBlocks(blocks)
  const choice = blockType === 'pause' && pauseKind === 'lunch' ? 'lunch' : blockType
  const permission = getAllowedNextScheduleBlocks(source)[choice]
  if (!permission?.allowed) return source
  const updated = [...source, newScheduleBlock(blockType, pauseKind, source.length + 1)]
  const firstStart = source.length
    ? source[0].start_minute
    : finiteMinute(startMinute, DEFAULT_START_MINUTE)
  const flowed = reflowScheduleBlocks(updated, firstStart)
  return flowed.at(-1)?.end_minute <= 24 * 60 ? flowed : source
}

export function tryRemoveScheduleBlock(blocks, blockIndex) {
  const source = reflowScheduleBlocks(blocks)
  if (!source[blockIndex]) return { blocks: source, removed: false, error: 'Bloc introuvable.' }
  // A deletion may briefly reveal an invalid suffix (for example course → pause)
  // while the user removes blocks from the end. Saving still validates the whole draft.
  const candidate = reflowScheduleBlocks(
    source.filter((_, index) => index !== blockIndex),
    source[0]?.start_minute ?? DEFAULT_START_MINUTE,
  )
  return { blocks: candidate, removed: true, error: '' }
}

export function updateScheduleBlockDuration(blocks, blockIndex, durationMinutes) {
  const source = reflowScheduleBlocks(blocks)
  if (!source[blockIndex]) return source
  const updated = source.map((block, index) => (
    index === blockIndex
      ? { ...block, duration_minutes: Math.max(1, finiteMinute(durationMinutes, 1)) }
      : block
  ))
  const flowed = reflowScheduleBlocks(updated, source[0]?.start_minute)
  return flowed.at(-1)?.end_minute <= 24 * 60 ? flowed : source
}

export function updateScheduleBlockStart(blocks, blockIndex, startMinute) {
  const source = reflowScheduleBlocks(blocks)
  const nextStart = finiteMinute(startMinute, source[blockIndex]?.start_minute)
  if (!source[blockIndex]) return source
  if (blockIndex === 0) {
    const flowed = reflowScheduleBlocks(source, nextStart)
    return nextStart >= 0 && flowed.at(-1)?.end_minute <= 24 * 60 ? flowed : source
  }
  const previous = source[blockIndex - 1]
  return updateScheduleBlockDuration(source, blockIndex - 1, nextStart - previous.start_minute)
}

export function setSchedulePauseKind(blocks, blockIndex, pauseKind) {
  const source = reflowScheduleBlocks(blocks)
  if (source[blockIndex]?.block_type !== 'pause') return source
  const nextKind = pauseKind === 'lunch' ? 'lunch' : 'short'
  const updated = source.map((block, index) => {
    if (block.block_type !== 'pause') return block
    if (index === blockIndex) {
      return {
        ...block,
        pause_kind: nextKind,
        duration_minutes: nextKind === 'lunch'
          ? Math.max(DAY_SCHEDULE_RULES.lunchPause.min, block.duration_minutes)
          : Math.min(DAY_SCHEDULE_RULES.shortPause.max, block.duration_minutes),
      }
    }
    if (nextKind === 'lunch' && block.pause_kind === 'lunch') {
      return {
        ...block,
        pause_kind: 'short',
        duration_minutes: Math.min(DAY_SCHEDULE_RULES.shortPause.max, block.duration_minutes),
      }
    }
    return block
  })
  const flowed = reflowScheduleBlocks(updated, source[0]?.start_minute)
  return flowed.at(-1)?.end_minute <= 24 * 60 ? flowed : source
}

// A sequence starts with a course and includes every optional block that follows
// it, up to (but not including) the next course.
export function addScheduleSequence(blocks) {
  return appendScheduleBlock(blocks, 'course')
}

export function getScheduleSequenceDropMinute(pointerMinute, blocks = []) {
  const source = reflowScheduleBlocks(blocks)
  if (source.length) return source.at(-1).end_minute
  const snapped = Math.round(finiteMinute(pointerMinute) / 5) * 5
  return Math.min((24 * 60) - DAY_SCHEDULE_RULES.course.default, Math.max(0, snapped))
}

export function removeLastScheduleSequence(blocks) {
  const source = reflowScheduleBlocks(blocks)
  const lastCourseIndex = source.findLastIndex((block) => block.block_type === 'course')
  if (lastCourseIndex < 0) return source
  return reflowScheduleBlocks(
    source.slice(0, lastCourseIndex),
    source[0]?.start_minute ?? DEFAULT_START_MINUTE,
  )
}

// Final pauses are invalid now. The compatibility export only removes one.
export function setScheduleFinalPause(blocks, enabled) {
  const source = reflowScheduleBlocks(blocks)
  if (enabled) return source
  return source.at(-1)?.block_type === 'pause'
    ? reflowScheduleBlocks(source.slice(0, -1), source[0]?.start_minute)
    : source
}

export function serializeScheduleTemplate(template) {
  const normalized = normalizeScheduleTemplate(template)
  return {
    name: normalized.name.trim(),
    schedule_schema_version: 2,
    blocks: normalized.blocks.map((block, position) => ({
      block_key: block.block_key,
      position,
      block_type: block.block_type,
      pause_kind: block.block_type === 'pause' ? block.pause_kind : null,
      start_minute: block.start_minute,
      end_minute: block.end_minute,
      duration_minutes: block.duration_minutes,
      metadata: block.metadata || {},
    })),
  }
}
