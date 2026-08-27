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

test('greys every unscheduled day and warms selected days', async () => {
  const styles = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.css', import.meta.url),
    'utf8',
  )

  assert.match(styles, /\.formation-schedule__week-column\s*\{[^}]*background-color: #f2f2f2/)
  assert.match(styles, /\.formation-schedule__week-column\[aria-pressed="true"\]\s*\{[^}]*background-color: #fffbea/)
  assert.doesNotMatch(styles, /\.formation-schedule__week-column\[data-weekend="true"\]/)
})

test('keeps every selected lunch break black regardless of its sequence tone', async () => {
  const styles = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.css', import.meta.url),
    'utf8',
  )

  const lastToneRule = styles.lastIndexOf('.formation-schedule__week-event[data-tone="7"]')
  const lunchRule = styles.lastIndexOf('.formation-schedule__week-event[data-kind="lunch"]')

  assert.ok(lunchRule > lastToneRule, 'the lunch style must override every sequence tone')
  assert.match(styles, /\.formation-schedule__week-event\[data-kind="lunch"\]\s*\{[^}]*border-color: #373737;[^}]*background: #373737;[^}]*color: #fff;/)
})

test('saves a completed calendar day as a reusable template from its heading', async () => {
  const source = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /Enregistrer le \$\{formatLongDate\(date\)\} comme template/)
  assert.match(source, /ref=\{templateSaveDialogRef\}/)
  assert.match(source, /className="formation-schedule__prefill-dialog formation-schedule__template-save-dialog"/)
  assert.match(source, /className="formation-schedule__prefill-form formation-schedule__template-save-form"/)
  assert.match(source, /formation-template-save-title">Enregistrer comme template/)
  assert.match(source, /Enregistrer le template/)
  assert.doesNotMatch(source, /formation-schedule__template-save-popover/)
  assert.match(source, /validateScheduleTemplate\(\{/)
  assert.match(source, /await createDayScheduleTemplate\(result\.template\)/)
  assert.match(source, /Template enregistré et prêt à être réutilisé\./)

  const styles = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.css', import.meta.url),
    'utf8',
  )
  assert.match(styles, /\.formation-schedule__prefill-dialog\s*\{[^}]*width: min\(680px/)
  assert.match(styles, /\.formation-schedule__prefill-dialog::backdrop\s*\{[^}]*background: rgb\(15 18 24 \/ 52%\)/)
  assert.match(styles, /\.formation-schedule__day-heading\[data-active="true"\]\s*\{[^}]*background: #fff2bf/)
  assert.match(styles, /\.formation-schedule__week-column\[data-active="true"\]\s*\{[^}]*background-color: #fff7d6/)
  assert.doesNotMatch(styles, /\.formation-schedule__week-column\[data-active="true"\]\s*\{[^}]*var\(--fsp-accent\)/)
  assert.doesNotMatch(styles, /\.formation-schedule__template-save-popover/)
})

test('opens automatic date filling from the weekly toolbar', async () => {
  const source = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /function monthLabel[\s\S]*?month: 'long'[\s\S]*?year: 'numeric'/)
  assert.match(source, />\s*Remplir automatiquement\s*<\/button>/)
  assert.match(source, /className="formation-schedule__prefill-dialog"/)
  assert.match(source, /dialog\.showModal\(\)/)
  assert.match(source, /formation-schedule__prefill-eyebrow">Planification/)
  assert.match(source, /Remplir automatiquement les dates/)
  assert.doesNotMatch(source, /className="formation-schedule__prefill-toggle"/)

  const styles = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.css', import.meta.url),
    'utf8',
  )
  assert.match(styles, /\.formation-schedule__prefill-dialog\s*\{[^}]*width: min\(680px/)
  assert.match(styles, /\.formation-schedule__prefill-dialog::backdrop\s*\{[^}]*background: rgb\(15 18 24 \/ 52%\)[^}]*backdrop-filter: blur\(2px\)/)
  assert.match(styles, /\.formation-schedule__helper-content input\s*\{[^}]*min-height: 44px/)
})

test('gives the sidebar calendar a larger, legible monthly layout', async () => {
  const styles = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.css', import.meta.url),
    'utf8',
  )

  assert.match(styles, /--fsp-sidebar-width: 320px/)
  assert.match(styles, /grid-template-columns: var\(--fsp-sidebar-width\) minmax\(0, 1fr\)/)
  assert.match(styles, /\.formation-schedule__mini-weekdays span\s*\{[^}]*text-transform: uppercase/)
  assert.match(styles, /\.formation-schedule__mini-grid button::before\s*\{[^}]*width: 36px; height: 36px[^}]*border-radius: 50%/)
  assert.match(styles, /\.formation-schedule__mini-grid button:focus-visible::after\s*\{[^}]*width: 38px; height: 38px[^}]*border-radius: 50%/)
  assert.match(styles, /@media \(max-width: 980px\)[\s\S]*?--fsp-sidebar-width: 280px/)
})

test('aligns the template overview with the centered workspace page hierarchy', async () => {
  const templateSource = await readFile(
    new URL('../../src/pages/DayScheduleTemplates.jsx', import.meta.url),
    'utf8',
  )
  const templateStyles = await readFile(
    new URL('../../src/pages/DayScheduleTemplates.css', import.meta.url),
    'utf8',
  )

  assert.match(templateSource, /day-schedule-page--overview/)
  assert.match(templateSource, /day-schedule-section-divider/)
  assert.match(templateSource, /<strong>Mes templates<\/strong>/)
  assert.match(templateSource, /day-schedule-library-actions/)
  assert.match(templateSource, /\/assets\/calendar-template\.png/)
  assert.match(templateSource, /day-schedule-template-calendar/)
  assert.doesNotMatch(templateSource, /Modifiable/)
  assert.doesNotMatch(templateSource, />\s*Utiliser\s*<\/button>/)
  assert.match(templateSource, /Utilisé/)
  assert.match(templateSource, /onCreate=\{startCreate\}/)
  assert.match(templateStyles, /\.day-schedule-page--overview \.day-schedule-page-header\s*\{[\s\S]*?text-align: center/)
  assert.match(templateStyles, /\.day-schedule-section-divider\s*\{[\s\S]*?align-items: center/)
  assert.doesNotMatch(templateStyles, /\.day-schedule-template-calendar\s*\{[^}]*position: absolute/)
  assert.match(templateStyles, /\.day-schedule-template-card-title\s*\{[^}]*gap: 10px/)
  assert.match(templateStyles, /\.day-schedule-template-calendar img\s*\{[\s\S]*?width: 36px/)
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
  const scheduleDomainSource = await readFile(
    new URL('../../src/formationScheduleV2.js', import.meta.url),
    'utf8',
  )
  const plannerStyles = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.css', import.meta.url),
    'utf8',
  )

  assert.doesNotMatch(plannerSource, /Je confirme ce calendrier définitif/)
  assert.doesNotMatch(plannerSource, /formation-schedule__date-list/)
  assert.match(plannerSource, /Naviguer entre les journées/)
  assert.match(plannerSource, /Appliquer ce template à toutes les journées/)
  assert.match(plannerSource, /formation-schedule__day-navigation/)
  assert.match(plannerSource, /formation-schedule__template-select/)
  assert.match(plannerStyles, /\.formation-schedule__organisation\s*\{[^}]*background: rgb\(12 65 255 \/ 5%\)/)
  assert.match(plannerStyles, /\.formation-schedule__day-navigation\s*\{[^}]*background: transparent/)
  assert.match(plannerStyles, /\.formation-schedule__active-day-copy strong\s*\{[^}]*color: #27292e/)
  assert.match(plannerStyles, /\.formation-schedule__template-select select\s*\{[^}]*min-height: 44px[^}]*appearance: none/)
  assert.match(plannerSource, /formation-schedule__validate-toolbar/)
  assert.match(plannerSource, /onClick=\{onValidate\}/)
  assert.doesNotMatch(dashboardSource, /Vérifier avant le paiement/)
  assert.match(dashboardSource, /Nom de votre centre de formation sur les diapositives/)
  assert.match(dashboardSource, /aria-label="Masquer les erreurs du planning"/)
  assert.match(dashboardSource, /setScheduleAttemptErrors\(\[\]\)/)
  assert.match(scheduleDomainSource, /La première séance doit commencer au moins 24 heures après la validation/)
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

  assert.equal((plannerSource.match(/Créer un template/g) || []).length, 1)
  assert.match(plannerSource, /activeCustomBlocks \? '__custom__' : activeAssignment/)
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

test('uses independent allowed block drops with resize and atomic deletion', async () => {
  const source = await readFile(new URL('../../src/pages/DayScheduleTemplates.jsx', import.meta.url), 'utf8')

  assert.match(source, /draggable=\{allowedBlocks\[key\]\.allowed\}/)
  assert.match(source, /application\/x-day-block/)
  assert.match(source, /Q&R et pauses sont facultatifs/)
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
  assert.match(source, /Retirer le dernier cours/)
  assert.match(source, /tryRemoveScheduleBlock\(draft\.blocks, blockIndex\)/)
  assert.match(source, /onRemoveBlock\(index\)/)
  assert.doesNotMatch(source, /<small>1 h 30<\/small>/)
  assert.doesNotMatch(source, /index < blocks\.length - 1/)
  assert.match(source, /onPointerDown=\{\(event\) => beginAdjustment\(event, index\)\}/)
  assert.match(source, /deltaSteps \* 5/)
  assert.doesNotMatch(source, /schedule-duration-/)
  assert.doesNotMatch(source, /Déplacer le début du bloc/)
})

test('adds independent pedagogical blocks directly to formation days', async () => {
  const source = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )
  const templateSource = await readFile(
    new URL('../../src/pages/DayScheduleTemplates.jsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /draggable=\{!reuse && permission\.allowed\}/)
  assert.match(source, /setData\('application\/x-day-block', key\)/)
  assert.match(source, /onDrop=\{\(event\) => \{/)
  assert.match(source, /addBlockToDay\(date, \.\.\.blockDefinition, startMinute\)/)
  assert.match(source, /onClick=\{\(\) => addBlockToDay\(activeDate \|\| displayedDate, type, pauseKind\)\}/)
  assert.match(source, /tryRemoveScheduleBlock\(blocks, blockIndex\)/)
  assert.match(source, /label: 'Pause courte'/)
  assert.match(source, /label: 'Pause déjeuner'/)
  assert.match(templateSource, /label: 'Pause courte'/)
  assert.match(templateSource, /label: 'Pause déjeuner'/)
  assert.doesNotMatch(source, /toggleLunchForDay|setSchedulePauseKind|Double-cliquer/)
  assert.doesNotMatch(templateSource, /day-schedule-pause-select|setSchedulePauseKind/)
  assert.match(source, /beginEventResize/)
  assert.match(source, /updateScheduleBlockDuration\(/)
  assert.match(source, /getScheduleBlockDurationBounds/)
  assert.match(source, /onPointerDown=\{\(pointerEvent\) => beginEventResize\(/)
  assert.match(source, /getScheduleSequenceDropMinute\(pointerMinute, blocks\)/)
  assert.match(source, /Début.*formatScheduleMinute\(dropPreview\.minute\)/)
  assert.match(source, /Relâchez pour placer le bloc/)
  assert.doesNotMatch(source, /onClick=\{\(\) => assignTemplate\(activeDate \|\| helperStartDate, '__create__'\)\}/)

  const styles = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.css', import.meta.url),
    'utf8',
  )
  assert.doesNotMatch(styles, /formation-schedule__pause-toggle/)
})

test('selects training days only from the mini calendar', async () => {
  const source = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /const activateDate = \(date\) => \{\s*if \(date < today \|\| !selectedDates\.includes\(date\)\) return/)
  const activateDateSource = source.match(/const activateDate = \(date\) => \{[\s\S]*?\n {2}\}/)?.[0] || ''
  assert.doesNotMatch(activateDateSource, /setSelectedDates/)
  assert.match(source, /if \(isSelectedDay\) activateDate\(date\)/)
  assert.match(source, /aria-disabled=\{!isSelectedDay\}/)
  assert.match(source, /&& isSelectedDay/)
  assert.equal((source.match(/onClick=\{\(\) => toggleDate\(day\.date\)\}/g) || []).length, 1)
})

test('navigates the weekly calendar in French with controls and horizontal swipes', async () => {
  const source = await readFile(
    new URL('../../src/pages/FormationSchedulePlanner.jsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'/)
  assert.match(source, /aria-label="Semaine précédente"/)
  assert.match(source, /aria-label="Semaine suivante"/)
  assert.match(source, /const navigateWeek = \(offset\) =>/)
  assert.match(source, /onPointerDown=\{beginWeekSwipe\}/)
  assert.match(source, /onPointerUp=\{finishWeekSwipe\}/)
  assert.match(source, /onWheel=\{handleWeekWheel\}/)
  assert.match(source, /Math\.abs\(deltaX\) < 60/)
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
