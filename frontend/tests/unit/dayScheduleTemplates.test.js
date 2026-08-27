import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DAY_SCHEDULE_RULES,
  appendScheduleBlock,
  cloneScheduleTemplateAsDraft,
  createEmptyScheduleTemplateDraft,
  createScheduleTemplateDraft,
  formatScheduleMinute,
  getAllowedNextScheduleBlocks,
  getScheduleBlockDurationBounds,
  getScheduleSequenceDropMinute,
  getScheduleStats,
  isScheduleTemplateUsed,
  parseScheduleTime,
  serializeScheduleTemplate,
  setSchedulePauseKind,
  tryRemoveScheduleBlock,
  updateScheduleBlockDuration,
  updateScheduleBlockStart,
  validateScheduleTemplate,
} from '../../src/dayScheduleTemplates.js'

function append(blocks, type, pauseKind = null) {
  return appendScheduleBlock(blocks, type, pauseKind)
}

test('creates a valid one-course day without mandatory Q&R or pause', () => {
  const draft = createScheduleTemplateDraft('Séance courte')
  const result = validateScheduleTemplate(draft)

  assert.equal(result.valid, true)
  assert.deepEqual(result.stats, {
    blockCount: 1,
    courseCount: 1,
    courseMinutes: 60,
    dayMinutes: 60,
    lunchCount: 0,
    hasFinalPause: false,
  })
})

test('adds every block independently in either optional-block order', () => {
  let qaThenPause = append([], 'course')
  qaThenPause = append(qaThenPause, 'qa')
  qaThenPause = append(qaThenPause, 'pause', 'short')
  qaThenPause = append(qaThenPause, 'course')
  assert.deepEqual(
    qaThenPause.map((block) => block.block_type),
    ['course', 'qa', 'pause', 'course'],
  )

  let pauseThenQa = append([], 'course')
  pauseThenQa = append(pauseThenQa, 'pause', 'short')
  pauseThenQa = append(pauseThenQa, 'qa')
  assert.equal(
    validateScheduleTemplate({ name: 'Pause puis Q&R', blocks: pauseThenQa }).valid,
    true,
  )
})

test('enforces the allowed-next grammar in the builder', () => {
  assert.equal(getAllowedNextScheduleBlocks([]).course.allowed, true)
  assert.equal(getAllowedNextScheduleBlocks([]).qa.allowed, false)
  assert.equal(getAllowedNextScheduleBlocks([]).pause.allowed, false)

  let blocks = append([], 'course')
  blocks = append(blocks, 'qa')
  assert.equal(getAllowedNextScheduleBlocks(blocks).qa.allowed, false)
  assert.equal(getAllowedNextScheduleBlocks(blocks).pause.allowed, true)
  blocks = append(blocks, 'pause', 'short')
  assert.equal(getAllowedNextScheduleBlocks(blocks).qa.allowed, false)
  assert.equal(getAllowedNextScheduleBlocks(blocks).pause.allowed, false)
  assert.equal(getAllowedNextScheduleBlocks(blocks).course.allowed, true)
})

test('allows a final Q&R but rejects a final pause', () => {
  let withQa = append([], 'course')
  withQa = append(withQa, 'qa')
  assert.equal(validateScheduleTemplate({ name: 'Final Q&R', blocks: withQa }).valid, true)

  let withPause = append([], 'course')
  withPause = append(withPause, 'pause', 'short')
  const result = validateScheduleTemplate({ name: 'Final pause', blocks: withPause })
  assert.equal(result.valid, false)
  assert.ok(result.errors.some((message) => message.includes('jamais par une pause')))
})

test('refuses a course deletion that would orphan its attached optional blocks', () => {
  let blocks = append([], 'course')
  blocks = append(blocks, 'qa')
  const result = tryRemoveScheduleBlock(blocks, 0)

  assert.equal(result.removed, false)
  assert.match(result.error, /Suppression refusée/)
  assert.equal(result.blocks.length, 2)
})

test('keeps at most one lunch and allows it up to three hours', () => {
  let blocks = append([], 'course')
  blocks = append(blocks, 'pause', 'lunch')
  blocks = append(blocks, 'course')
  blocks = append(blocks, 'pause', 'short')
  blocks = append(blocks, 'qa')
  const secondPause = blocks.findLastIndex((block) => block.block_type === 'pause')
  const movedLunch = setSchedulePauseKind(blocks, secondPause, 'lunch')
  const lunchIndexes = movedLunch.flatMap((block, index) => (
    block.pause_kind === 'lunch' ? [index] : []
  ))
  assert.deepEqual(lunchIndexes, [secondPause])

  const stretched = updateScheduleBlockDuration(movedLunch, secondPause, 180)
  assert.equal(stretched[secondPause].duration_minutes, 180)
  assert.equal(validateScheduleTemplate({ name: 'Déjeuner long', blocks: stretched }).valid, true)
})

test('shares the confirmed duration bounds between both planners', () => {
  assert.deepEqual(getScheduleBlockDurationBounds({ block_type: 'course' }), DAY_SCHEDULE_RULES.course)
  assert.deepEqual(getScheduleBlockDurationBounds({ block_type: 'qa' }), DAY_SCHEDULE_RULES.qa)
  assert.deepEqual(
    getScheduleBlockDurationBounds({ block_type: 'pause', pause_kind: 'short' }),
    DAY_SCHEDULE_RULES.shortPause,
  )
  assert.deepEqual(
    getScheduleBlockDurationBounds({ block_type: 'pause', pause_kind: 'lunch' }),
    DAY_SCHEDULE_RULES.lunchPause,
  )
  assert.equal(DAY_SCHEDULE_RULES.course.min, 35)
  assert.equal(DAY_SCHEDULE_RULES.course.max, 90)
  assert.equal(DAY_SCHEDULE_RULES.qa.min, 10)
  assert.equal(DAY_SCHEDULE_RULES.lunchPause.max, 180)
})

test('snaps the first course to five minutes and appends later blocks continuously', () => {
  assert.equal(getScheduleSequenceDropMinute(8 * 60 + 17), 8 * 60 + 15)
  assert.equal(getScheduleSequenceDropMinute(23 * 60 + 55), 23 * 60)

  const existing = append([], 'course')
  assert.equal(getScheduleSequenceDropMinute(7 * 60, existing), 10 * 60)
})

test('reflows all following blocks after duration and start changes', () => {
  let blocks = append([], 'course')
  blocks = append(blocks, 'qa')
  blocks = append(blocks, 'course')
  const longerCourse = updateScheduleBlockDuration(blocks, 0, 75)

  assert.equal(longerCourse[0].end_minute, 10 * 60 + 15)
  assert.equal(longerCourse[1].start_minute, 10 * 60 + 15)
  assert.equal(longerCourse[2].start_minute, 10 * 60 + 30)

  const movedQaBoundary = updateScheduleBlockStart(longerCourse, 1, 10 * 60 + 5)
  assert.equal(movedQaBoundary[0].duration_minutes, 65)
  assert.equal(movedQaBoundary[1].start_minute, 10 * 60 + 5)
})

test('rejects invalid durations and explicit gaps', () => {
  let blocks = append([], 'course')
  blocks = append(blocks, 'qa')
  blocks[0] = { ...blocks[0], duration_minutes: 20, end_minute: blocks[0].start_minute + 20 }
  blocks[1] = {
    ...blocks[1],
    start_minute: blocks[0].end_minute + 7,
    end_minute: blocks[0].end_minute + 7 + blocks[1].duration_minutes,
  }
  const result = validateScheduleTemplate({ name: 'Invalide', blocks })
  assert.equal(result.valid, false)
  assert.match(result.blockErrors[blocks[0].block_key].join(' '), /35 à 90/)
  assert.match(result.blockErrors[blocks[1].block_key].join(' '), /Aucun espace/)
})

test('serializes only the stable V2 contract', () => {
  const draft = createScheduleTemplateDraft('  Journée stable  ')
  const payload = serializeScheduleTemplate(draft)
  assert.equal(payload.name, 'Journée stable')
  assert.equal(payload.schedule_schema_version, 2)
  assert.equal(payload.blocks[0].position, 0)
  assert.equal(payload.blocks[0].block_type, 'course')
  assert.equal(payload.blocks[0].start_minute, 540)
})

test('recognizes immutable templates and duplicates them into drafts', () => {
  const used = {
    ...createScheduleTemplateDraft('Journée certifiée'),
    id: 18,
    used_at: '2026-07-26T12:00:00Z',
  }
  const duplicate = cloneScheduleTemplateAsDraft(used)
  assert.equal(isScheduleTemplateUsed(used), true)
  assert.equal(duplicate.id, null)
  assert.equal(duplicate.used_at, null)
  assert.equal(duplicate.name, 'Copie de Journée certifiée')
})

test('parses and formats schedule times at minute precision', () => {
  assert.equal(parseScheduleTime('10:07'), 607)
  assert.equal(parseScheduleTime('24:00'), null)
  assert.equal(formatScheduleMinute(607), '10:07')
  assert.equal(createEmptyScheduleTemplateDraft('Vide').blocks.length, 0)
})
