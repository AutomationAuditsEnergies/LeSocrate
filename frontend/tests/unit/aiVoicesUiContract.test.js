import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const sourceUrl = new URL('../../src/pages/AIVoicesView.jsx', import.meta.url)

test('validates the voice with concise speed-selection guidance', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /const confirmVoice = async \(\) =>/)
  assert.match(source, /method: 'PATCH'/)
  assert.match(source, /body: JSON\.stringify\(\{ playback_speed: speed \}\)/)
  assert.match(source, /Valider la voix/)
  assert.match(source, /Écoutez le résultat et choisissez sa vitesse définitive/)
  assert.doesNotMatch(source, /texte éducatif de référence de 7 069 mots/)
  assert.doesNotMatch(source, /Calibration automatique des cours/)
  assert.doesNotMatch(source, /Tous les objectifs de mots des modules seront ensuite ajustés proportionnellement/)
  assert.doesNotMatch(source, /calibration_sample/)
  assert.doesNotMatch(source, /Analyser le débit/)
})

test('presents free recording with optional reading inspiration in a sidebar', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /Enregistrez-vous directement en disant ce que vous voulez/)
  assert.match(source, /Téléverser un audio existant/)
  assert.match(source, /Besoin d’inspiration/)
  assert.match(source, /Texte facultatif/)
  assert.match(source, /onInspiration=\{\(\) => setInspiration\(true\)\}/)
  assert.match(source, /<aside className="fixed inset-y-0 right-0/)
  assert.match(source, /inspirationPanelOpen \? 'lg:pr-\[28rem\]'/)
  assert.doesNotMatch(source, /Revenir à l’enregistrement/)
  assert.doesNotMatch(source, /Transcription envoyée avec l’audio/)
  assert.doesNotMatch(source, /form\.append\('transcript'/)
  assert.doesNotMatch(source, /setTranscript/)
})

test('uses a mandatory rights declaration without a vocal consent recording', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /Déclaration obligatoire/)
  assert.match(source, /Je certifie que cette voix est la mienne/)
  assert.match(source, /autorisation écrite, valide et suffisante/)
  assert.match(source, /rights_declaration_confirmed/)
  assert.doesNotMatch(source, /Preuve vocale du consentement/)
  assert.doesNotMatch(source, /consent_sample/)
  assert.doesNotMatch(source, /consentAudio/)
})
