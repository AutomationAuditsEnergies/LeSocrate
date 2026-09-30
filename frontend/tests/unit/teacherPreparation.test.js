import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getHiddenPipelineProgress,
  getTeacherPreparation,
} from '../../src/teacherPreparation.js'

test('uses the authoritative preparation state returned by the backend', () => {
  const platform = {
    status: 'pending',
    pipeline_auto_pilot_step: 'reac',
    teacher_preparation: {
      status: 'preparing',
      progress: 72,
      stage: 'Rédaction des cours',
      can_retry: false,
    },
  }

  assert.equal(getHiddenPipelineProgress(platform), 72)
  assert.deepEqual(getTeacherPreparation(platform), platform.teacher_preparation)
})

test('never reports an intermediate slide preparation as complete', () => {
  const progress = getHiddenPipelineProgress({
    status: 'pending',
    pipeline_status: 'tts_launched',
    pipeline_auto_pilot_step: 'slides',
  })

  assert.equal(progress, 96)
  assert.ok(progress < 100)
})

test('allows an interrupted pipeline to resume without exposing technical errors', () => {
  const state = getTeacherPreparation({
    status: 'error',
    source_formation_id: 71,
    pipeline_auto_pilot_error: 'private provider error',
  })

  assert.deepEqual(state, {
    status: 'failed',
    progress: 8,
    stage: 'Préparation interrompue',
    can_retry: true,
  })
  assert.doesNotMatch(JSON.stringify(state), /provider/)
})
