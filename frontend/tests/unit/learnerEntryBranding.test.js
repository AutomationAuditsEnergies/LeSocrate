import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const entrySource = readFileSync(new URL('../../src/pages/Index.jsx', import.meta.url), 'utf8')
const classEntrySource = readFileSync(new URL('../../src/pages/ClassEntry.jsx', import.meta.url), 'utf8')
const authStyles = readFileSync(new URL('../../src/pages/Auth.css', import.meta.url), 'utf8')

test('removes Cadrenza branding from learner entry surfaces', () => {
  assert.doesNotMatch(entrySource, /CadrenzaLogo|Accès apprenant Cadrenza/)
  assert.doesNotMatch(classEntrySource, /CadrenzaLogo|Retour à l’accueil Cadrenza/)
})

test('uses the study image as the full learner visual panel', () => {
  assert.match(entrySource, /className="auth-study-image"/)
  assert.match(authStyles, /\.auth-visual--learner-login\s*\{[\s\S]*padding: 0;/)
  assert.match(authStyles, /\.auth-study-image\s*\{[\s\S]*position: absolute;[\s\S]*object-fit: cover;/)
})
