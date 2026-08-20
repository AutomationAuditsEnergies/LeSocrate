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

test('keeps emoji artwork out of the formation planner', async () => {
  const source = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )

  assert.doesNotMatch(source, /\/figma-week\//)
  assert.doesNotMatch(source, /<img/)
})

test('keeps time labels in a clean gutter before the weekly grid', async () => {
  const styles = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.css', import.meta.url),
    'utf8',
  )

  assert.match(styles, /--fsp-time-axis-width: 64px/)
  assert.match(styles, /\.formation-schedule__time-axis\s*\{[^}]*border-right: 1px solid var\(--fsp-border\)[^}]*background: #fff/)
  assert.match(styles, /\.formation-schedule__time-axis span\s*\{[^}]*width: 100%[^}]*justify-content: flex-end[^}]*background: #fff/)
  assert.doesNotMatch(styles, /\.formation-schedule__week-column:first-child\s*\{[^}]*border-left/)
})

test('uses compact month names and a short calendar fill action', async () => {
  const source = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /function monthLabel[\s\S]*?month: 'short'/)
  assert.match(source, /\{prefillOpen \? 'Retour' : 'Remplir'\}/)
  assert.match(source, /Remplir automatiquement les dates/)
})

test('gives the sidebar calendar a little more room', async () => {
  const styles = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.css', import.meta.url),
    'utf8',
  )

  assert.match(styles, /--fsp-sidebar-width: 272px/)
  assert.match(styles, /grid-template-columns: var\(--fsp-sidebar-width\) minmax\(0, 1fr\)/)
  assert.match(styles, /@media \(max-width: 980px\)[\s\S]*?--fsp-sidebar-width: 240px/)
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

test('creates a missing template without losing the current formation draft', async () => {
  const plannerSource = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )
  const templateSource = await readFile(
    new URL('../../src/pages/DayScheduleTemplates.jsx', import.meta.url),
    'utf8',
  )
  const dashboardSource = await readFile(
    new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
    'utf8',
  )
  const createPlatformStyles = await readFile(
    new URL('../../src/pages/CreatePlatformView.css', import.meta.url),
    'utf8',
  )

  assert.equal((plannerSource.match(/Créer un template/g) || []).length >= 2, true)
  assert.match(plannerSource, /onCreateTemplate\?\.\(\{/)
  assert.match(templateSource, /createOnMount \? createEmptyScheduleTemplateDraft\(\) : null/)
  assert.match(templateSource, /createdNow && onUseTemplate/)
  assert.match(dashboardSource, /teacher_creation_draft/)
  assert.match(dashboardSource, /useState\(loadTeacherCreationDraft\)/)
  assert.match(dashboardSource, /createTemplateFromFormationDraft/)
  assert.match(dashboardSource, /resumeFormationDraftWithTemplate/)
  assert.match(dashboardSource, /Votre progression est enregistrée/)
  assert.match(dashboardSource, /Vous pourrez reprendre votre progression après avoir créé votre template/)
  assert.match(dashboardSource, /Reprendre ma progression/)
  assert.match(dashboardSource, /Recruter manuellement/)
  assert.match(dashboardSource, /startNewManualRecruitment/)
  assert.match(dashboardSource, /hasSavedDraft=\{Boolean\(templateCreationDraft\)\}/)
  assert.match(dashboardSource, /prefers-reduced-motion: reduce/)
  assert.match(createPlatformStyles, /create-platform-draft-travel/)
  assert.match(createPlatformStyles, /recruitment-saved-draft-enter/)
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
  assert.match(source, /Retirer la dernière séquence/)
  assert.match(source, /removeLastScheduleSequence\(draft\.blocks\)/)
  assert.doesNotMatch(source, /<small>1 h 30<\/small>/)
  assert.doesNotMatch(source, /index < blocks\.length - 1/)
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
