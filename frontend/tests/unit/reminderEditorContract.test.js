import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const dashboardUrl = new URL('../../src/pages/HRDashboard.jsx', import.meta.url)

test('offers the personal and ordinary access paths in the predefined reminder', async () => {
  const source = await readFile(dashboardUrl, 'utf8')

  assert.match(source, /Votre cours commence le \{date\} à \{time\}/)
  assert.match(source, /\{class_url_connexion\}/)
  assert.match(source, /\{session_code\}/)
  assert.match(source, /\{class_url_accueil\}/)
})

test('lets the center restore the default and insert variables at the cursor', async () => {
  const source = await readFile(dashboardUrl, 'utf8')

  assert.match(source, /Rétablir le message par défaut/)
  assert.match(source, /selectionStart/)
  assert.match(source, /setSelectionRange/)
  assert.match(source, /Insérer :/)
  assert.match(source, /Lien personnel/)
  assert.match(source, /Code personnel/)
  assert.match(source, /Lien habituel/)
})
