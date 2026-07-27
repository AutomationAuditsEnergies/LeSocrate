import assert from 'node:assert/strict'
import test from 'node:test'

import {
  addScheduleSequence,
  cloneScheduleTemplateAsDraft,
  createEmptyScheduleTemplateDraft,
  createScheduleTemplateDraft,
  formatScheduleMinute,
  getScheduleStats,
  isScheduleTemplateUsed,
  parseScheduleTime,
  removeLastScheduleSequence,
  serializeScheduleTemplate,
  setScheduleFinalPause,
  setSchedulePauseKind,
  updateScheduleBlockDuration,
  updateScheduleBlockStart,
  validateScheduleTemplate,
} from '../../src/dayScheduleTemplates.js'

test('creates a valid full-day template with four course sequences', () => {
  const draft = createScheduleTemplateDraft('Journée standard')
  const result = validateScheduleTemplate(draft)

  assert.equal(result.valid, true)
  assert.deepEqual(result.stats, {
    blockCount: 12,
    courseCount: 4,
    courseMinutes: 240,
    dayMinutes: 405,
    lunchCount: 1,
    hasFinalPause: true,
  })
})

test('adds and removes complete course, Q&R and pause sequences', () => {
  const draft = createScheduleTemplateDraft('Journée longue')
  const withFifthCourse = addScheduleSequence(draft.blocks)

  assert.equal(getScheduleStats(withFifthCourse).courseCount, 5)
  assert.equal(withFifthCourse.length, 15)
  assert.equal(withFifthCourse.at(-1).block_type, 'pause')

  const restored = removeLastScheduleSequence(withFifthCourse)
  assert.equal(getScheduleStats(restored).courseCount, 4)
  assert.equal(restored.length, 12)
})

test('starts the interactive builder empty and adds one locked trio at a time', () => {
  const emptyDraft = createEmptyScheduleTemplateDraft('Nouvelle journée')
  const firstSequence = addScheduleSequence(emptyDraft.blocks)

  assert.equal(emptyDraft.blocks.length, 0)
  assert.deepEqual(firstSequence.map((block) => block.block_type), ['course', 'qa', 'pause'])
  assert.equal(removeLastScheduleSequence(firstSequence).length, 0)
})

test('supports an optional final short pause', () => {
  const draft = createScheduleTemplateDraft('Avec pause finale')
  const withPause = setScheduleFinalPause(draft.blocks, true)

  assert.equal(withPause.length, 12)
  assert.equal(withPause.at(-1).block_type, 'pause')
  assert.equal(withPause.at(-1).pause_kind, 'short')
  assert.equal(validateScheduleTemplate({ ...draft, blocks: withPause }).valid, true)
  assert.equal(setScheduleFinalPause(withPause, false).length, 11)
})

test('moves the unique lunch designation and keeps both pause durations valid', () => {
  const draft = createScheduleTemplateDraft('Déjeuner tardif')
  const pauseIndexes = draft.blocks
    .map((block, index) => block.block_type === 'pause' ? index : -1)
    .filter((index) => index >= 0)
  const updated = setSchedulePauseKind(draft.blocks, pauseIndexes[2], 'lunch')

  assert.equal(updated[pauseIndexes[2]].pause_kind, 'lunch')
  assert.equal(updated[pauseIndexes[2]].duration_minutes, 60)
  assert.equal(updated[pauseIndexes[1]].pause_kind, 'short')
  assert.equal(updated[pauseIndexes[1]].duration_minutes, 30)
  assert.equal(getScheduleStats(updated).lunchCount, 1)
})

test('reflows subsequent blocks after duration and boundary changes', () => {
  const draft = createScheduleTemplateDraft('Horaires libres')
  const longerCourse = updateScheduleBlockDuration(draft.blocks, 0, 75)

  assert.equal(longerCourse[0].end_minute, 10 * 60 + 15)
  assert.equal(longerCourse[1].start_minute, 10 * 60 + 15)

  const movedQa = updateScheduleBlockStart(longerCourse, 1, 10 * 60 + 7)
  assert.equal(movedQa[0].duration_minutes, 67)
  assert.equal(movedQa[1].start_minute, 10 * 60 + 7)
})

test('rejects invalid block durations and an undersized day', () => {
  const draft = createScheduleTemplateDraft('Journée invalide')
  const blocks = updateScheduleBlockDuration(draft.blocks, 0, 20)
  const result = validateScheduleTemplate({ ...draft, blocks })

  assert.equal(result.valid, false)
  assert.match(result.blockErrors['course-1'][0], /35 à 90/)
  assert.ok(result.errors.some((message) => message.includes('4 h')))
})

test('rejects gaps instead of silently moving the following block', () => {
  const draft = createScheduleTemplateDraft('Journée avec un trou')
  const blocks = draft.blocks.map((block, index) => (
    index === 1
      ? { ...block, start_minute: block.start_minute + 7, end_minute: block.end_minute + 7 }
      : block
  ))
  const result = validateScheduleTemplate({ ...draft, blocks })

  assert.equal(result.valid, false)
  assert.match(result.blockErrors['qa-1'].join(' '), /Aucun espace/)
})

test('serializes only the stable V2 data contract', () => {
  const draft = createScheduleTemplateDraft('  Journée stable  ')
  const payload = serializeScheduleTemplate(draft)

  assert.equal(payload.name, 'Journée stable')
  assert.equal(payload.schedule_schema_version, 2)
  assert.equal(payload.blocks[0].position, 0)
  assert.equal(payload.blocks[0].block_type, 'course')
  assert.equal(payload.blocks[0].start_minute, 540)
})

test('recognizes immutable templates and duplicates them into editable drafts', () => {
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
  assert.equal(duplicate.blocks.length, used.blocks.length)
})

test('parses and formats schedule times at minute precision', () => {
  assert.equal(parseScheduleTime('10:07'), 607)
  assert.equal(parseScheduleTime('24:00'), null)
  assert.equal(formatScheduleMinute(607), '10:07')
})
