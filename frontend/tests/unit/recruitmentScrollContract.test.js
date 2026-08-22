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
})
