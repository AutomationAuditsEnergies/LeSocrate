import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const dashboardSource = readFileSync(
  new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
  'utf8',
)

test('blocks recruitment only when the REAC is unavailable', () => {
  assert.match(dashboardSource, /if \(!payload\.available\)/)
  assert.match(
    dashboardSource,
    /nous n’avons pas encore de professeur disponible pour dispenser cette formation/,
  )
})

test('offers the inactive RNCP title and its replacement as explicit choices', () => {
  assert.match(dashboardSource, /replacement_certifications/)
  assert.match(dashboardSource, /setPendingRncpDecision\(\{ certification, replacement \}\)/)
  assert.match(dashboardSource, /Conserver RNCP/)
  assert.match(dashboardSource, /Utiliser RNCP/)
  assert.match(dashboardSource, /skipRncpConfirmation: true/)
})
