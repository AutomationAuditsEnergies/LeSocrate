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

test('offers the inactive RNCP title and every replacement as explicit choices', () => {
  assert.match(dashboardSource, /replacement_certifications/)
  assert.match(dashboardSource, /setPendingRncpDecision\(\{ certification, replacements \}\)/)
  assert.match(dashboardSource, /pendingRncpDecision\.replacements\.map/)
  assert.match(dashboardSource, /index \+ 2/)
  assert.match(dashboardSource, /Conserver RNCP/)
  assert.match(dashboardSource, /Utiliser RNCP/)
  assert.match(dashboardSource, /skipRncpConfirmation: true/)
})

test('explains inactive titles differently for one or several replacements', () => {
  assert.match(dashboardSource, /Ce titre professionnel n’est désormais plus d’actualité/)
  assert.match(dashboardSource, /replacements\.length === 1/)
  assert.match(dashboardSource, /replacements\.length > 1/)
  assert.match(dashboardSource, /les certifications suivantes/)
})
