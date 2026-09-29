import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(
  fileURLToPath(new URL('../../src/pages/HRDashboard.jsx', import.meta.url)),
  'utf8',
)

test('limits the test clock UI to platform operators', () => {
  assert.doesNotMatch(source, /newpiprod@gmail\.com/)
  assert.match(source, /PLATFORM_OPERATOR_PERMISSIONS = \['platform_operator'\]/)
  assert.match(source, /testClockAvailable=\{orderReviewCenter\}/)
  assert.match(source, /testClockAvailable && !rosterSearchOpen/)
})

test('supports setting and resetting the durable server test clock', () => {
  assert.match(source, /apiFetch\('\/api\/hr\/test-clock'/)
  assert.match(source, /method: 'PUT'/)
  assert.match(source, /method: 'DELETE'/)
  assert.match(source, /Revenir à l’heure réelle/)
})
