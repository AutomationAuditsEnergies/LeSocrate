import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../../src/pages/FormationPipeline.jsx', import.meta.url),
  'utf8',
)

test('keeps the Formation3 pipeline page read-only apart from global resume', () => {
  assert.match(source, /Reprendre la pipeline/)
  assert.match(source, /\/run-auto\/resume/)

  assert.doesNotMatch(source, /\/api\/formation\/init/)
  assert.doesNotMatch(source, /continue-after-text/)
  assert.doesNotMatch(source, /generate-audio/)
  assert.doesNotMatch(source, /resume-content/)
  assert.doesNotMatch(source, /Nouveau pipeline/)
  assert.doesNotMatch(source, /Stopper auto-pilot/)
  assert.doesNotMatch(source, /Reprendre depuis une étape/)
})

test('keeps the selected pipeline and URL in sync', () => {
  assert.match(source, /url\.searchParams\.set\('job', String\(selectedJobId\)\)/)
  assert.match(source, /\}, \[selectedJobId\]\)/)
})

test('does not disguise a server failure as a missing pipeline', () => {
  assert.match(source, /response\.status >= 500/)
  assert.match(source, /Le job existe toujours et peut être repris/)
  assert.doesNotMatch(source, /Pipeline introuvable\./)
})

test('does not report future health checks as current blockers', () => {
  assert.match(source, /healthChecksPending/)
  assert.match(source, /Contrôles à venir/)
})

test('explains that teacher orders are the only pipeline entry point', () => {
  assert.match(
    source,
    /déclenchés automatiquement après la validation d’une commande de professeur IA/,
  )
  assert.match(source, /sans validation ou relance intermédiaire/)
})

test('restores the detailed 17-step auto-pilot roadmap', () => {
  assert.match(source, /Roadmap auto-pilot API/)
  assert.match(source, /DETAILED_PIPELINE_STAGES/)
  assert.match(source, /Plan JSON verrouillé/)
  assert.match(source, /Micro-conformité éthique/)
  assert.match(source, /Curation IA des slides/)
  assert.match(source, /Slides anchor-first/)
  assert.match(source, /stages\.length/)
})

test('shows durable queue, health checks and matching stage events for debugging', () => {
  assert.match(source, /File durable/)
  assert.match(source, /queue\.attempt/)
  assert.match(source, /Contrôles de santé/)
  assert.match(source, /Événements correspondants/)
  assert.match(source, /folder_resolution/)
  assert.match(source, /volume_audit/)
})

test('detects an active job left without a durable work item', () => {
  assert.match(source, /hasDetachedQueue/)
  assert.match(source, /QUEUE_TERMINAL_STATUSES/)
  assert.match(source, /Worker sans tâche active/)
  assert.match(source, /Utilisez « Reprendre la pipeline »/)
})
