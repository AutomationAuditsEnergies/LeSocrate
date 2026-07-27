import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const scheduleUiFiles = [
  '../../src/pages/DayScheduleTemplates.jsx',
  '../../src/pages/DayScheduleTemplates.css',
  '../../src/pages/FormationSchedulePlanner.jsx',
  '../../src/pages/FormationSchedulePlanner.css',
]

const chromaticColorName = /\b(?:violet|purple|indigo|blue|cyan|teal|green|emerald|lime|yellow|amber|orange|red|rose|pink)(?:-\d+)?\b/i

test('keeps the planning and template UI strictly monochrome', async () => {
  for (const relativePath of scheduleUiFiles) {
    const source = await readFile(new URL(relativePath, import.meta.url), 'utf8')
    assert.doesNotMatch(source, chromaticColorName, `${relativePath} contains a chromatic color token`)
  }
})

test('renders the audio modal from the real playlist instead of the legacy 19-file list', async () => {
  const source = await readFile(new URL('../../src/pages/HRDashboard.jsx', import.meta.url), 'utf8')
  const modalStart = source.indexOf('function AudiosModal(')
  const modalEnd = source.indexOf('// ─── PDF Modal', modalStart)
  const modalSource = source.slice(modalStart, modalEnd)

  assert.ok(modalStart >= 0 && modalEnd > modalStart)
  assert.doesNotMatch(modalSource, /EXPECTED_AUDIOS|cours_9h00_9h45/)
  assert.doesNotMatch(modalSource, chromaticColorName)
  assert.match(modalSource, /classifyFormationAudios/)
})
