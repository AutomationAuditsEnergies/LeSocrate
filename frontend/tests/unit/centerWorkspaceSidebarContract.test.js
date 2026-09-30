import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('closes the centre account menu on outside click and Escape', async () => {
  const source = await readFile(
    new URL('../../src/pages/HRDashboard.jsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /ref=\{accountDetailsRef\}/)
  assert.match(source, /document\.addEventListener\('pointerdown', closeAccountMenu\)/)
  assert.match(source, /document\.addEventListener\('keydown', closeAccountMenu\)/)
  assert.match(source, /if \(!details\.contains\(event\.target\)\)/)
  assert.match(source, /if \(event\.key !== 'Escape'\) return/)
  assert.match(source, /document\.removeEventListener\('pointerdown', closeAccountMenu\)/)
  assert.match(source, /document\.removeEventListener\('keydown', closeAccountMenu\)/)
})
