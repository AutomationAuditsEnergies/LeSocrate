import assert from 'node:assert/strict'
import test from 'node:test'

import {
  appendScheduleBlock,
} from '../../src/dayScheduleTemplates.js'
import {
  assignTemplateToAll,
  dateTimeInTimeZone,
  fillUnassignedTemplate,
  getCalendarMonthDays,
  getMinimumNewModuleStartDate,
  hasMinimumLeadTime,
  isValidCalendarDate,
  normalizeSelectedTrainingDates,
  prefillTrainingDates,
  serializeFormationScheduleV2,
  validateFormationScheduleV2,
} from '../../src/formationScheduleV2.js'

const templateHash = 'a'.repeat(64)

let customBlocks = []
customBlocks = appendScheduleBlock(customBlocks, 'course')
customBlocks = appendScheduleBlock(customBlocks, 'qa')
customBlocks = appendScheduleBlock(customBlocks, 'pause', 'lunch')
customBlocks = appendScheduleBlock(customBlocks, 'course')

const template = {
  id: 12,
  name: 'Journée standard',
  blocks_hash: templateHash,
  blocks: [
    {
      block_key: 'course-1',
      position: 0,
      block_type: 'course',
      start_minute: 9 * 60,
      end_minute: 10 * 60,
      duration_minutes: 60,
    },
  ],
}

test('prefills preferred weekdays, including weekends, within the requested horizon', () => {
  const dates = prefillTrainingDates({
    startDate: '2026-08-01',
    weeks: 2,
    daysPerWeek: 2,
    preferredWeekdays: [6, 7],
  })

  assert.deepEqual(dates, [
    '2026-08-01',
    '2026-08-02',
    '2026-08-08',
    '2026-08-09',
  ])
})

test('caps a helper prefill without turning the approximate count into schedule authority', () => {
  const dates = prefillTrainingDates({
    startDate: '2026-08-01',
    weeks: 4,
    daysPerWeek: 2,
    preferredWeekdays: [2, 4],
    limit: 3,
  })
  assert.equal(dates.length, 3)
  assert.deepEqual(dates, ['2026-08-04', '2026-08-06', '2026-08-11'])
})

test('requires the preferred weekday count to match the approximate weekly count', () => {
  assert.deepEqual(prefillTrainingDates({
    startDate: '2026-08-03',
    weeks: 4,
    daysPerWeek: 2,
    preferredWeekdays: [2],
  }), [])
})

test('rejects impossible calendar dates before attempting a prefill', () => {
  assert.equal(isValidCalendarDate('2026-09-30'), true)
  assert.equal(isValidCalendarDate('2026-09-31'), false)
  assert.deepEqual(prefillTrainingDates({
    startDate: '2026-09-31',
    weeks: 20,
    daysPerWeek: 2,
    preferredWeekdays: [3, 5],
    limit: 11,
  }), [])
})

test('keeps final checked dates authoritative and sorted', () => {
  assert.deepEqual(normalizeSelectedTrainingDates([
    '2026-09-04',
    'invalid',
    '2026-09-01',
    '2026-09-04',
  ]), ['2026-09-01', '2026-09-04'])
})

test('apply-to-all fills only dates without an assignment', () => {
  assert.deepEqual(fillUnassignedTemplate(
    { '2026-09-01': '7' },
    ['2026-09-01', '2026-09-02'],
    12,
  ), {
    '2026-09-01': '7',
    '2026-09-02': '12',
  })
})

test('applies one template to every selected day and replaces earlier choices', () => {
  assert.deepEqual(assignTemplateToAll(
    ['2026-09-02', '2026-09-01'],
    42,
  ), {
    '2026-09-01': '42',
    '2026-09-02': '42',
  })
})

test('requires J+3 by calendar date regardless of the validation time', () => {
  const result = validateFormationScheduleV2({
    selectedDates: ['2026-08-04'],
    assignments: { '2026-08-04': '12' },
    templates: [template],
    now: new Date('2026-08-01T21:59:00Z'),
  })
  assert.equal(result.valid, true)
  assert.equal(hasMinimumLeadTime(
    ['2026-08-03'],
    { '2026-08-03': '12' },
    [template],
    new Date('2026-08-01T06:00:00Z'),
  ), false)
  assert.equal(getMinimumNewModuleStartDate(new Date('2026-08-23T22:01:00Z')), '2026-08-27')
  assert.equal(getMinimumNewModuleStartDate(new Date('2026-08-23T08:00:00Z')), '2026-08-26')
})

test('evaluates Paris wall-clock times independently from the browser timezone', () => {
  assert.equal(
    dateTimeInTimeZone('2026-08-03', 9 * 60)?.toISOString(),
    '2026-08-03T07:00:00.000Z',
  )
  assert.equal(dateTimeInTimeZone('2026-03-29', 2 * 60 + 30), null)
  assert.equal(dateTimeInTimeZone('2026-10-25', 2 * 60 + 30), null)
})

test('reuse requires exactly the durable module day count and no client layout', () => {
  const invalid = validateFormationScheduleV2({
    selectedDates: ['2026-08-03'],
    reuse: true,
    expectedDayCount: 2,
  })
  assert.equal(invalid.valid, false)

  const payload = serializeFormationScheduleV2({
    selectedDates: ['2026-08-04', '2026-08-03'],
    assignments: { '2026-08-03': '12' },
    reuse: true,
  })
  assert.deepEqual(payload, {
    schedule_schema_version: 2,
    selected_dates: ['2026-08-03', '2026-08-04'],
  })
})

test('serializes only the command contract for a new module', () => {
  assert.deepEqual(serializeFormationScheduleV2({
    selectedDates: ['2026-08-03'],
    assignments: { '2026-08-03': 12 },
    templates: [template],
  }), {
    schedule_schema_version: 2,
    selected_dates: ['2026-08-03'],
    template_assignments: { '2026-08-03': '12' },
    template_hashes: { 12: templateHash },
    custom_days: {},
  })
})

test('accepts and serializes a complete custom day without creating a template', () => {
  const result = validateFormationScheduleV2({
    selectedDates: ['2026-08-03'],
    assignments: {},
    templates: [],
    customDays: { '2026-08-03': customBlocks },
    now: new Date('2026-07-31T06:59:00Z'),
  })
  assert.equal(result.valid, true)

  const payload = serializeFormationScheduleV2({
    selectedDates: ['2026-08-03'],
    assignments: {},
    customDays: { '2026-08-03': customBlocks },
  })
  assert.deepEqual(payload.template_assignments, {})
  assert.deepEqual(payload.template_hashes, {})
  assert.equal(payload.custom_days['2026-08-03'].blocks.length, 4)
  assert.equal(payload.custom_days['2026-08-03'].blocks[2].pause_kind, 'lunch')
})

test('builds a complete six-week calendar grid', () => {
  const days = getCalendarMonthDays(2026, 7)
  assert.equal(days.length, 42)
  assert.equal(days[0].date, '2026-07-27')
  assert.equal(days.at(-1).date, '2026-09-06')
})
