import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const sourceUrl = new URL('../../src/pages/AIVoicesView.jsx', import.meta.url)

test('locks the selected speed after voice validation and hides internal calibration', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /const confirmVoice = async \(\) =>/)
  assert.match(source, /method: 'PATCH'/)
  assert.match(source, /body: JSON\.stringify\(\{ playback_speed: speed \}\)/)
  assert.match(source, /Valider la voix/)
  assert.match(source, /Une fois la voix validée, cette vitesse ne pourra plus être modifiée/)
  assert.match(source, /Vitesse appliquée/)
  assert.doesNotMatch(source, /Débit de référence/)
  assert.doesNotMatch(source, /Calibration automatique des cours/)
  assert.doesNotMatch(source, /saveSpeed/)
  assert.doesNotMatch(source, /onMouseUp=/)
  assert.doesNotMatch(source, /onTouchEnd=/)
  assert.doesNotMatch(source, /calibration_sample/)
  assert.doesNotMatch(source, /Analyser le débit/)
})
