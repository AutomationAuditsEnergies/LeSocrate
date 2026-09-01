import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

test('allows tomorrow during configuration and only surfaces the 24-hour rule after an invalid drop', async () => {
  const dashboardSource = await readFile(
    new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
    'utf8',
  )
  const plannerSource = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )

  assert.match(dashboardSource, /min=\{earliestStartDate\}/)
  assert.match(dashboardSource, /Vous pouvez choisir dès demain/)
  assert.doesNotMatch(plannerSource, /formation-schedule__lead-time-note/)
  assert.match(plannerSource, /rejectTooEarlyDrop\(date, startMinute\)/)
  assert.match(plannerSource, /dateTimeInTimeZone\(date, startMinute, 'Europe\/Paris'\)/)
  assert.match(plannerSource, /formation-schedule__lead-time-error/)
  assert.match(plannerSource, /Pour respecter le délai de traitement/)
  assert.match(plannerSource, /24 heures après l’heure actuelle/)
  assert.match(plannerSource, /Le lendemain peut être sélectionné/)
})
