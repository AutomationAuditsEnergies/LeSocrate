import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  getActiveTeachers,
  getReusableTeacherDefaults,
} from '../../src/centerWorkspace.js'

const dashboardSource = readFileSync(
  new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
  'utf8',
)

test('opens the centre workspace without a first-login onboarding', () => {
  assert.doesNotMatch(dashboardSource, /\/api\/hr\/onboarding/)
  assert.doesNotMatch(dashboardSource, /CenterOnboarding/)
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
