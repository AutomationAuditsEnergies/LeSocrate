import assert from 'node:assert/strict'
import test from 'node:test'

import { hasAdminAccess } from '../../src/adminAccess.js'

test('autorise un compte centre qui possède la permission demandée', () => {
  assert.equal(hasAdminAccess(
    {
      type: 'training_center',
      permissions: { formation_pipeline: true },
    },
    {
      allowedAccountTypes: ['training_center'],
      requiredPermissions: ['formation_pipeline'],
    },
  ), true)
})

test('refuse un compte sans permission et un ancien admin', () => {
  const requirements = {
    allowedAccountTypes: ['training_center'],
    requiredPermissions: ['formation_pipeline'],
  }

  assert.equal(hasAdminAccess({
    type: 'training_center',
    permissions: { formation_pipeline: false },
  }, requirements), false)
  assert.equal(hasAdminAccess({
    type: 'legacy_admin',
    permissions: { formation_pipeline: true },
  }, requirements), false)
})
