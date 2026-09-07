import assert from 'node:assert/strict'
import test from 'node:test'

import { buildTeacherDescription } from '../../src/teacherIdentity.js'

test('generates the dedicated TP CRCD teacher description', () => {
  const description = buildTeacherDescription('TP CRCD')

  assert.match(description, /Conseiller relation client à distance/)
  assert.match(description, /outils multicanaux/)
})

test('generates an editable generic description from the training title', () => {
  const description = buildTeacherDescription('TP Employé commercial')

  assert.match(description, /TP Employé commercial/)
  assert.match(description, /parcours structuré/)
})

test('waits for a meaningful title before generating copy', () => {
  assert.equal(buildTeacherDescription('TP'), '')
})
