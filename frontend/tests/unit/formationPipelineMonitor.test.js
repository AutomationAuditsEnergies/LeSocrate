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

test('explains that teacher orders are the only pipeline entry point', () => {
  assert.match(
    source,
    /déclenchés automatiquement après la validation d’une commande de professeur IA/,
  )
  assert.match(source, /sans validation ou relance intermédiaire/)
})
