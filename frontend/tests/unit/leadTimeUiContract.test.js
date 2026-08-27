import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

test('allows tomorrow during configuration and explains the exact 24-hour planning rule', async () => {
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
  assert.match(plannerSource, /leadTimeIsTooShort/)
  assert.match(plannerSource, /Le premier cours commence trop tôt/)
  assert.match(plannerSource, /Le lendemain peut être sélectionné/)
})
