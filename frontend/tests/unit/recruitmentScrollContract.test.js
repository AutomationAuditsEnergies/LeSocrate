import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const dashboardSource = readFileSync(
  new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
  'utf8',
)
const recruitmentSource = readFileSync(
  new URL('../../src/recruitmentConversation.js', import.meta.url),
  'utf8',
)

test('streams recruitment replies by words and keeps the latest exchange above the composer', () => {
  assert.match(dashboardSource, /scrollArea\.scrollTo\(\{/)
  assert.match(
    dashboardSource,
    /behavior: prefersReducedMotionRef\.current \? 'auto' : 'smooth'/,
  )
  assert.match(dashboardSource, /h-\[clamp\(72px,14vh,144px\)\]/)
  assert.match(dashboardSource, /justify-start py-8 sm:py-10/)
  assert.match(dashboardSource, /window\.setInterval\(\(\) => \{/)
  assert.match(dashboardSource, /fullText\.match\(\/\\S\+\\s\*\/g\)/)
  assert.match(dashboardSource, /textChunks\.slice\(0, revealedChunkCount\)\.join\(''\)/)
  assert.doesNotMatch(dashboardSource, /recruitment-assistant-message--streaming/)
  assert.doesNotMatch(
    dashboardSource,
    /scrollArea\.scrollTop = scrollArea\.scrollHeight/,
  )
  assert.match(dashboardSource, /style=\{\{ scrollbarGutter: 'stable' \}\}/)
})

test('keeps the completion review compact and free of decorative robot imagery', () => {
  assert.doesNotMatch(
    dashboardSource,
    /teacher-robot-float[^]*Vérifiez la configuration proposée/,
  )
  assert.match(
    dashboardSource,
    /borderColor: colors\.borderLight, scrollbarGutter: 'stable'/,
  )
  assert.doesNotMatch(dashboardSource, /Vérifiez la configuration proposée/)
  assert.doesNotMatch(dashboardSource, /Le formulaire de recrutement sera déjà complété/)
  assert.match(dashboardSource, />\s*Configurer le planning\s*</)
  assert.match(dashboardSource, /Configuration prête à planifier/)
})

test('opens the planning with dates prefilled from the assistant answers', () => {
  assert.match(dashboardSource, /const selectedDates = prefillTrainingDates\(\{/)
  assert.match(dashboardSource, /preferredWeekdays,/)
  assert.match(dashboardSource, /limit: Number\(draft\.trainingDays\)/)
  assert.match(
    dashboardSource,
    /setInitialScheduleV2\(\{[^]*selected_dates: selectedDates/,
  )
})

test('switches manual recruitment to a full-page form before the planning', () => {
  assert.match(dashboardSource, /function ManualRecruitmentForm/)
  assert.match(dashboardSource, /const \[manualMode, setManualMode\] = useState\(false\)/)
  assert.match(dashboardSource, /manual-recruitment-enter/)
  assert.match(dashboardSource, /Configurer le professeur/)
  assert.match(dashboardSource, /Date de début/)
  assert.match(dashboardSource, /Rythme hebdomadaire/)
  assert.match(dashboardSource, /Durée de la formation/)
  assert.match(dashboardSource, /Jours habituels de formation/)
  assert.match(dashboardSource, /Nom du professeur IA/)
  assert.match(
    dashboardSource,
    /selected \? 'border-\[#191918\] bg-\[#191918\] text-white'/,
  )
  assert.doesNotMatch(dashboardSource, /onManualStart\?\.\(\); setShowCreateModal/)
})

test('validates active and inactive RNCP records before manual planning', () => {
  assert.match(dashboardSource, /api\/hr\/recruitment\/rncp/)
  assert.match(dashboardSource, /Code RNCP valide/)
  assert.match(dashboardSource, /Le titre professionnel enregistré sous le code RNCP/)
  assert.match(dashboardSource, /a été remplacé par la nouvelle certification RNCP/)
  assert.match(dashboardSource, /Certification mise à jour/)
  assert.match(dashboardSource, /Ancienne certification/)
  assert.match(dashboardSource, /Certification actuelle/)
  assert.doesNotMatch(dashboardSource, /bg-\[#FFF9E8\]/)
  assert.match(dashboardSource, /Afficher les informations sur la mise à jour RNCP/)
  assert.match(dashboardSource, /rncpResult\.status === 'inactive' && inactiveInfoOpen/)
  assert.doesNotMatch(dashboardSource, /border-\[#FDBA74\] bg-\[#FFF7ED\]/)
  assert.match(dashboardSource, /grid-cols-\[minmax\(0,1fr\)_auto\]/)
  assert.match(dashboardSource, /rncp-side-panel-enter fixed inset-y-0 right-0/)
  assert.match(dashboardSource, /inactiveInfoOpen \? 'rncp-form-content--shifted' : ''/)
  assert.match(dashboardSource, /aria-label="Fermer le panneau RNCP"/)
  assert.match(dashboardSource, /Souhaitez-vous conserver le titre RNCP/)
  assert.match(dashboardSource, /Conserver RNCP \{certification\.rncp_code\}/)
  assert.match(dashboardSource, /Utiliser RNCP \{replacement\.rncp_code\}/)
  assert.match(dashboardSource, /\['valid', 'validInactive'\]\.includes/)
  assert.match(dashboardSource, /rncpResult\.status === 'inactive' \? 'grid-cols-\[minmax\(0,1fr\)_auto\]/)
  assert.match(dashboardSource, /flex h-11 min-w-0 items-center rounded-lg bg-\[#EAF7EF\]/)
})

test('explains the flexible weekly rhythm and removes color selection from recruitment', () => {
  assert.match(
    dashboardSource,
    /Pour l’instant, indiquez simplement un nombre moyen de jours par semaine/,
  )
  assert.match(
    dashboardSource,
    /une semaine pourra n’en compter qu’un et la suivante trois/,
  )
  assert.doesNotMatch(
    dashboardSource,
    /id: 'teacherColor'.*question:/,
  )
  assert.doesNotMatch(
    dashboardSource,
    /currentStep\.type === 'color'/,
  )
})

test('presents teaching days as flexible defaults for most weeks', () => {
  assert.match(
    recruitmentSource,
    /Quels jours de la semaine souhaitez-vous prévoir habituellement/,
  )
  assert.match(
    dashboardSource,
    /ceux qui s’appliqueront pendant la majorité du parcours/,
  )
  assert.match(
    dashboardSource,
    /en cas de jour férié ou d’exception, vous pourrez déplacer les séances/,
  )
  assert.match(
    dashboardSource,
    /backgroundColor: selected \? '#097FE8' : colors\.innerBg/,
  )
})
