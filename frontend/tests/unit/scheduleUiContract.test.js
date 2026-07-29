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

test('reviews the definitive schedule only when preparation is requested', async () => {
  const plannerSource = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )
  const dashboardSource = await readFile(
    new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
    'utf8',
  )

  assert.doesNotMatch(plannerSource, /Je confirme ce calendrier définitif/)
  assert.doesNotMatch(plannerSource, /formation-schedule__date-list/)
  assert.match(plannerSource, /Naviguer entre les journées/)
  assert.match(plannerSource, /Appliquer le même template à toutes les journées/)
  assert.match(plannerSource, /formation-schedule__day-navigation/)
  assert.match(dashboardSource, /Confirmer le planning définitif/)
  assert.match(dashboardSource, /La première date doit être au minimum à J\+2/)
  assert.match(dashboardSource, /Associez un template à/)
})

test('uses locked sequence drops and resize handles instead of per-block forms', async () => {
  const source = await readFile(new URL('../../src/pages/DayScheduleTemplates.jsx', import.meta.url), 'utf8')

  assert.match(source, /draggable=\{!atMaximum\}/)
  assert.match(source, /application\/x-day-sequence/)
  assert.match(source, /Séquence pédagogique/)
  assert.equal(
    (source.match(/className="day-schedule-add-task day-schedule-sequence-source"/g) || []).length,
    1,
  )
  assert.doesNotMatch(source, /sequence-card-/)
  assert.doesNotMatch(source, /day-schedule-editor-progress/)
  assert.doesNotMatch(source, /Construisez votre journée/)
  assert.doesNotMatch(source, /day-schedule-editor-stats/)
  assert.doesNotMatch(source, /day-schedule-rule-strip/)
  assert.doesNotMatch(source, /day-schedule-editor-validation/)
  assert.doesNotMatch(source, /day-schedule-editor-header/)
  assert.match(source, /day-schedule-page-actions/)
  assert.match(source, /day-schedule-editor-name-row/)
  assert.match(source, /day-schedule-template-card/)
  assert.match(source, /day-schedule-layout--overview/)
  assert.match(source, /day-schedule-empty-state/)
  assert.match(source, /onPointerDown=\{\(event\) => beginAdjustment\(event, index\)\}/)
  assert.match(source, /deltaSteps \* 5/)
  assert.doesNotMatch(source, /schedule-duration-/)
  assert.doesNotMatch(source, /Déplacer le début du bloc/)
})

test('locks the template editor page and scrolls only the calendar', async () => {
  const templateSource = await readFile(
    new URL('../../src/pages/DayScheduleTemplates.jsx', import.meta.url),
    'utf8',
  )
  const templateStyles = await readFile(
    new URL('../../src/pages/DayScheduleTemplates.css', import.meta.url),
    'utf8',
  )
  const dashboardSource = await readFile(
    new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
    'utf8',
  )

  assert.match(templateSource, /day-schedule-page--editor/)
  assert.match(templateSource, /day-schedule-calendar-scroll/)
  assert.match(templateSource, /const CALENDAR_START_MINUTE = 0/)
  assert.match(templateSource, /const CALENDAR_END_MINUTE = 24 \* 60/)
  assert.match(templateSource, /const CALENDAR_INITIAL_MINUTE = 8 \* 60/)
  assert.match(templateSource, /ref=\{calendarScrollRef\}/)
  assert.match(templateStyles, /\.day-schedule-page--editor\s*\{[\s\S]*?overflow: hidden/)
  assert.match(templateStyles, /\.day-schedule-page--editor \.day-schedule-calendar-scroll\s*\{[\s\S]*?overflow-y: auto/)
  assert.match(templateStyles, /box-shadow: inset 0 0 0 1px #292824/)
  assert.match(dashboardSource, /scheduleTemplatesVisible \? 'overflow-hidden'/)
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
