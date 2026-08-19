import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const sourceUrl = new URL('../../src/pages/AIVoicesView.jsx', import.meta.url)

test('allows a cloned voice to be validated without calibrating its speaking rate', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /const confirmVoice = async \(\) =>/)
  assert.match(source, /method: 'PATCH'/)
  assert.match(source, /body: JSON\.stringify\(\{ playback_speed: speed \}\)/)
  assert.match(source, /Valider la voix/)
  assert.match(source, /L’analyse du débit est facultative/)
})
