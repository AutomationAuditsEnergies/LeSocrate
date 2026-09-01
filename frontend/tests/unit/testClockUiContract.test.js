import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(
  fileURLToPath(new URL('../../src/pages/HRDashboard.jsx', import.meta.url)),
  'utf8',
)

test('limits the test clock UI to the designated admin account', () => {
  assert.match(source, /ORDER_REVIEW_CENTER_EMAIL = 'newpiprod@gmail\.com'/)
  assert.match(source, /testClockAvailable = isOrderReviewCenter\(\)/)
  assert.match(source, /testClockAvailable && !rosterSearchOpen/)
})

test('supports setting and resetting the durable server test clock', () => {
  assert.match(source, /apiFetch\('\/api\/hr\/test-clock'/)
  assert.match(source, /method: 'PUT'/)
  assert.match(source, /method: 'DELETE'/)
  assert.match(source, /Revenir à l’heure réelle/)
})
