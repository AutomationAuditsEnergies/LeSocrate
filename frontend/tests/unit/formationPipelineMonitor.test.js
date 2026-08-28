import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../../src/pages/FormationPipeline.jsx', import.meta.url),
  'utf8',
)

test('restores the complete historical pipeline interface', () => {
  assert.match(source, /Pipeline Formation/)
  assert.match(source, /Nouveau pipeline/)
  assert.match(source, /Pipelines existants/)
  assert.match(source, /Stepper currentStep/)
  assert.match(source, /PipelineVisualMap/)
  assert.match(source, /Roadmap auto-pilot API/)
})

test('restores every detailed debugging surface', () => {
  assert.match(source, /Recherche RNCP & initialisation/)
  assert.match(source, /Téléchargement REAC/)
  assert.match(source, /Enrichissement Knowledge Base/)
  assert.match(source, /Programme global/)
  assert.match(source, /Programmes journée/)
  assert.match(source, /Génération des cours \(texte\)/)
  assert.match(source, /Rapport conformité/)
  assert.match(source, /Reprendre depuis une étape/)
})

test('keeps the current authenticated API client and durable resume', () => {
  assert.match(source, /import \{ apiDownload, apiFetch \} from '\.\.\/api'/)
  assert.match(source, /\/run-auto\/status/)
  assert.match(source, /\/run-auto\/resume/)
  assert.match(source, /\/diagnostic\?events_limit=80/)
  assert.match(source, /hasDetachedQueue/)
  assert.match(source, /voice_reference_calibration/)
  assert.match(source, /le téléchargement REAC n’a pas commencé/)
  assert.match(source, /la tâche durable est terminée en échec/)
})

test('restores document, slides and audio inspection controls', () => {
  assert.match(source, /Word 2/)
  assert.match(source, /Slides anchor-first/)
  assert.match(source, /Slide2/)
  assert.match(source, /Fish \+ synchro/)
  assert.match(source, /Edge \+ synchro/)
  assert.match(source, /FolderTextModal/)
})

test('keeps the selected pipeline in the URL', () => {
  assert.match(source, /setPipelineJobInUrl/)
  assert.match(source, /url\.searchParams\.set\('job'/)
})
