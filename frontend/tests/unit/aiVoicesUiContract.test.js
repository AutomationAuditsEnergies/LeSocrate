import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const sourceUrl = new URL('../../src/pages/AIVoicesView.jsx', import.meta.url)

test('validates the voice while presenting automatic post-payment calibration', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /const confirmVoice = async \(\) =>/)
  assert.match(source, /method: 'PATCH'/)
  assert.match(source, /body: JSON\.stringify\(\{ playback_speed: speed \}\)/)
  assert.match(source, /Valider la voix/)
  assert.match(source, /texte éducatif de référence de 7 069 mots/)
  assert.match(source, /Tous les objectifs de mots des modules seront ensuite ajustés proportionnellement/)
  assert.doesNotMatch(source, /calibration_sample/)
  assert.doesNotMatch(source, /Analyser le débit/)
})
