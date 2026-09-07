import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
  'utf8',
)

test('keeps the account menu limited to settings and sign-out', () => {
  const menu = source.slice(source.indexOf('ref={accountDetailsRef}'), source.indexOf('const SETTINGS_TABS'))
  assert.match(menu, />Paramètres</)
  assert.match(menu, /Se déconnecter/)
  assert.doesNotMatch(menu, />Profil</)
})

test('provides account and billing settings as the two primary tabs', () => {
  assert.match(source, /id: 'account', label: 'Compte'/)
  assert.match(source, /id: 'billing', label: 'Facturation'/)
  assert.match(source, /auth\.updateUser\(\{ password: newPassword \}\)/)
  assert.match(source, /apiFetch\('\/api\/admin\/account'/)
  assert.match(source, /apiFetch\('\/api\/hr\/billing\/history'/)
  assert.match(source, /billing\/orders\/\$\{orderId\}\/invoice/)
  assert.match(source, /Aucune dépense à ce jour/)
  assert.doesNotMatch(source, />Historique indisponible</)
})

test('requires the exact workspace name before destructive deletion', () => {
  assert.match(source, /deleteConfirmation !== accountName/)
  assert.match(source, /JSON\.stringify\(\{ confirmation: deleteConfirmation \}\)/)
})
