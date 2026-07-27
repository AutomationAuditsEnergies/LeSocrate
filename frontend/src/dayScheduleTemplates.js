export const DAY_SCHEDULE_RULES = Object.freeze({
  course: Object.freeze({ min: 35, max: 90 }),
  qa: Object.freeze({ min: 5, max: 30 }),
  shortPause: Object.freeze({ min: 5, max: 30 }),
  lunchPause: Object.freeze({ min: 60, max: 120 }),
  minCourses: 4,
  maxCourses: 10,
  minCourseMinutes: 240,
  minDayMinutes: 360,
})

const DEFAULT_START_MINUTE = 9 * 60

function finiteMinute(value, fallback = 0) {
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
  const blockType = ['course', 'qa', 'pause'].includes(block?.block_type)
    ? block.block_type
    : 'course'
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

function makeSequenceBlocks(courseNumber, includePause = true) {
  const sequence = [
    {
      block_key: `course-${courseNumber}`,
      block_type: 'course',
      pause_kind: null,
      duration_minutes: 60,
    },
    {
      block_key: `qa-${courseNumber}`,
      block_type: 'qa',
      pause_kind: null,
      duration_minutes: 15,
    },
  ]
  if (includePause) {
    sequence.push({
      block_key: `pause-${courseNumber}`,
      block_type: 'pause',
      pause_kind: courseNumber === 2 ? 'lunch' : 'short',
      duration_minutes: courseNumber === 2 ? 60 : 15,
    })
  }
  return sequence
}

export function createDefaultScheduleBlocks(startMinute = DEFAULT_START_MINUTE) {
  const blocks = []
  for (let courseNumber = 1; courseNumber <= DAY_SCHEDULE_RULES.minCourses; courseNumber += 1) {
    blocks.push(...makeSequenceBlocks(courseNumber))
  }
  return reflowScheduleBlocks(blocks, startMinute)
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
  return {
    ...createScheduleTemplateDraft(name),
    blocks: [],
  }
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

function durationRuleForBlock(block) {
  if (block.block_type === 'course') return DAY_SCHEDULE_RULES.course
  if (block.block_type === 'qa') return DAY_SCHEDULE_RULES.qa
  return block.pause_kind === 'lunch'
    ? DAY_SCHEDULE_RULES.lunchPause
    : DAY_SCHEDULE_RULES.shortPause
}

export function validateScheduleTemplate(template) {
  const normalized = normalizeScheduleTemplate(template)
  const { blocks } = normalized
  const stats = getScheduleStats(blocks)
  const errors = []
  const blockErrors = {}

  if (!normalized.name.trim()) errors.push('Donnez un nom au template.')
  if (!blocks.length) errors.push('Ajoutez au moins une séquence.')

  if (stats.courseCount < DAY_SCHEDULE_RULES.minCourses) {
    errors.push(`Ajoutez au moins ${DAY_SCHEDULE_RULES.minCourses} cours vocaux.`)
  }
  if (stats.courseCount > DAY_SCHEDULE_RULES.maxCourses) {
    errors.push(`Limitez la journée à ${DAY_SCHEDULE_RULES.maxCourses} cours vocaux.`)
  }
  if (stats.courseMinutes < DAY_SCHEDULE_RULES.minCourseMinutes) {
    errors.push(`Prévoyez au moins ${DAY_SCHEDULE_RULES.minCourseMinutes / 60} h de cours vocaux.`)
  }
  if (stats.dayMinutes < DAY_SCHEDULE_RULES.minDayMinutes) {
    errors.push(`La journée doit durer au moins ${DAY_SCHEDULE_RULES.minDayMinutes / 60} h.`)
  }
  if (stats.lunchCount !== 1) {
    errors.push('Prévoyez exactement une pause déjeuner.')
  }

  blocks.forEach((block, index) => {
    const key = block.block_key || `block-${index + 1}`
    const blockMessages = []
    const rule = durationRuleForBlock(block)
    const duration = finiteMinute(block.duration_minutes)
    if (duration < rule.min || duration > rule.max) {
      blockMessages.push(`Durée autorisée : ${rule.min} à ${rule.max} min.`)
    }

    if (block.start_minute < 0 || block.start_minute >= 24 * 60) {
      blockMessages.push('L’heure de début doit appartenir à la journée.')
    }
    if (block.end_minute > 24 * 60) {
      blockMessages.push('Le bloc doit se terminer avant minuit.')
    }
    if (block.end_minute - block.start_minute !== duration) {
      blockMessages.push('Les horaires ne correspondent pas à la durée.')
    }

    if (index > 0 && blocks[index - 1].end_minute !== block.start_minute) {
      blockMessages.push('Aucun espace ni chevauchement n’est autorisé.')
    }

    if (index % 3 === 0 && block.block_type !== 'course') {
      blockMessages.push('Cette position doit contenir un cours vocal.')
    }
    if (index % 3 === 1 && block.block_type !== 'qa') {
      blockMessages.push('Un Q&R doit suivre chaque cours vocal.')
    }
    if (index % 3 === 2 && block.block_type !== 'pause') {
      blockMessages.push('Une pause doit séparer deux séquences.')
    }

    const isLast = index === blocks.length - 1
    if (isLast && !['qa', 'pause'].includes(block.block_type)) {
      blockMessages.push('La journée doit finir après un Q&R ou une pause finale.')
    }
    if (isLast && block.pause_kind === 'lunch') {
      blockMessages.push('La pause déjeuner doit séparer deux cours.')
    }

    if (blockMessages.length) blockErrors[key] = blockMessages
  })

  if (![2, 0].includes(blocks.length % 3)) {
    errors.push('Respectez l’enchaînement cours, Q&R, puis pause facultative en fin de journée.')
  }

  return {
    valid: errors.length === 0 && Object.keys(blockErrors).length === 0,
    errors,
    blockErrors,
    stats,
    template: normalized,
  }
}

export function updateScheduleBlockDuration(blocks, blockIndex, durationMinutes) {
  const source = reflowScheduleBlocks(blocks)
  if (!source[blockIndex]) return source
  const updated = source.map((block, index) => (
    index === blockIndex
      ? { ...block, duration_minutes: Math.max(1, finiteMinute(durationMinutes, 1)) }
      : block
  ))
  return reflowScheduleBlocks(updated, source[0]?.start_minute)
}

export function updateScheduleBlockStart(blocks, blockIndex, startMinute) {
  const source = reflowScheduleBlocks(blocks)
  const nextStart = finiteMinute(startMinute, source[blockIndex]?.start_minute)
  if (!source[blockIndex]) return source
  if (blockIndex === 0) return reflowScheduleBlocks(source, nextStart)

  const previous = source[blockIndex - 1]
  const previousDuration = Math.max(1, nextStart - previous.start_minute)
  return updateScheduleBlockDuration(source, blockIndex - 1, previousDuration)
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
  return reflowScheduleBlocks(updated, source[0]?.start_minute)
}

export function addScheduleSequence(blocks) {
  const source = reflowScheduleBlocks(blocks)
  const stats = getScheduleStats(source)
  if (stats.courseCount >= DAY_SCHEDULE_RULES.maxCourses) return source

  const updated = [...source]
  // Les anciens templates pouvaient finir après le Q&R. On complète d'abord
  // leur dernière séquence afin que chaque ajout conserve le contrat Cours/Q&R/Pause.
  if (updated.at(-1)?.block_type === 'qa') {
    updated.push({
      block_key: `pause-${stats.courseCount}`,
      block_type: 'pause',
      pause_kind: 'short',
      duration_minutes: 15,
    })
  }
  updated.push(...makeSequenceBlocks(stats.courseCount + 1))
  return reflowScheduleBlocks(updated, source[0]?.start_minute ?? DEFAULT_START_MINUTE)
}

export function removeLastScheduleSequence(blocks) {
  const source = reflowScheduleBlocks(blocks)
  const stats = getScheduleStats(source)
  if (stats.courseCount === 0) return source

  const updated = [...source]
  if (updated.at(-1)?.block_type === 'pause') updated.pop()
  if (updated.at(-1)?.block_type === 'qa') updated.pop()
  if (updated.at(-1)?.block_type === 'course') updated.pop()
  return reflowScheduleBlocks(updated, source[0]?.start_minute ?? DEFAULT_START_MINUTE)
}

export function setScheduleFinalPause(blocks, enabled) {
  const source = reflowScheduleBlocks(blocks)
  const hasFinalPause = source.at(-1)?.block_type === 'pause'
  if (enabled === hasFinalPause) return source
  if (!enabled) return reflowScheduleBlocks(source.slice(0, -1), source[0]?.start_minute)

  return reflowScheduleBlocks([
    ...source,
    {
      block_key: 'pause-final',
      block_type: 'pause',
      pause_kind: 'short',
      duration_minutes: 15,
    },
  ], source[0]?.start_minute)
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
