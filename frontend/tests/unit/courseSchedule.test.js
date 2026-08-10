import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getAudioStatusMeta,
  getNextCourseSession,
  scheduleSelectionIsValid,
} from '../../src/courseSchedule.js'

test('shows the durable next occurrence and its audio state', () => {
  const session = { id: 9, audio_status: 'preparing' }
  assert.equal(getNextCourseSession({ course_schedule: { next_session: session } }), session)
  assert.equal(getAudioStatusMeta(session.audio_status).label, 'Audios en cours de génération')
})

test('falls back to a missing-audio label for an unknown backend state', () => {
  assert.equal(getAudioStatusMeta('legacy').label, 'Audios manquants')
})

test('requires the configured number of weekdays', () => {
  assert.equal(scheduleSelectionIsValid({ selectedWeekdays: [1, 3], expectedWeekdayCount: 2 }), true)
  assert.equal(scheduleSelectionIsValid({ selectedWeekdays: [1], expectedWeekdayCount: 2 }), false)
})
