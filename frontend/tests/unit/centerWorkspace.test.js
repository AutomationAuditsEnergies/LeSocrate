import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CENTER_ONBOARDING_VERSION,
  getActiveTeachers,
  getReusableTeacherDefaults,
  shouldShowCenterOnboarding,
} from '../../src/centerWorkspace.js'

test('shows the versioned onboarding only when the centre has not completed it', () => {
  assert.equal(shouldShowCenterOnboarding({ success: true, onboarding_version: 0 }), true)
  assert.equal(
    shouldShowCenterOnboarding({ success: true, onboarding_version: CENTER_ONBOARDING_VERSION }),
    false,
  )
})

test('keeps only active and preparing teachers in Mes professeurs IA', () => {
  const visible = getActiveTeachers([
    { id: 1, lifecycle_status: 'active' },
    { id: 2, lifecycle_status: 'completed' },
    { id: 3, lifecycle_status: 'archived' },
    { id: 4 },
  ])
  assert.deepEqual(visible.map((teacher) => teacher.id), [1, 4])
})

test('reuses the durable teacher identity from its module', () => {
  assert.deepEqual(
    getReusableTeacherDefaults({ teacher_name: 'Maya', teacher_color: 'green' }),
    { teacherName: 'Maya', teacherColor: 'green' },
  )
})
