import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatCourseMinutes,
  formatJobPlanning,
  formatPlanningSummary,
} from '../../src/formationPlanningDisplay.js'

const planningSummary = {
  source: 'schedule_v2',
  day_count: 5,
  course_count: 5,
  course_minutes: 175,
  uniform_daily_course_count: 1,
  uniform_course_duration_minutes: 35,
}

test('formats the actual five-day, 35-minute course plan', () => {
  assert.equal(
    formatPlanningSummary(planningSummary),
    '5 journées · 1 cours de 35 min/jour · 2 h 55 de cours',
  )
  assert.equal(formatCourseMinutes(175), '2 h 55')
})

test('never falls back to artificial hours for an incomplete V2 response', () => {
  assert.equal(
    formatJobPlanning({
      schedule_schema_version: 2,
      planning_summary: null,
      total_hours: 35,
      nb_days: 5,
    }),
    '5 journées · durée des cours indisponible',
  )
})

test('keeps the historical hour display for legacy jobs only', () => {
  assert.equal(
    formatJobPlanning({ schedule_schema_version: 1, total_hours: 14, nb_days: 2 }),
    '14 h · 2 journées',
  )
})
