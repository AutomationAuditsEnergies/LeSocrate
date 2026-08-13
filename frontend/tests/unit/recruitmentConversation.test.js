import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyKnownRncpTraining,
  validateRecruitmentAnswer,
} from '../../src/recruitmentConversation.js'

test('asks again when the training answer only describes its duration', () => {
  const result = validateRecruitmentAnswer('trainingName', 'une formation longue')

  assert.equal(result.valid, false)
  assert.match(result.message, /pas un intitulé précis/)
})

test('rejects a certification category instead of confirming it as a title', () => {
  const result = validateRecruitmentAnswer('trainingName', 'Un titre professionnel')

  assert.equal(result.valid, false)
  assert.match(result.message, /nom exact du titre professionnel/)
})

test('accepts a short but specific training title', () => {
  assert.equal(validateRecruitmentAnswer('trainingName', 'Développeur web').valid, true)
  assert.equal(validateRecruitmentAnswer('trainingName', 'Vente').valid, true)
})

test('requires a plausible teacher name and RNCP code', () => {
  assert.equal(validateRecruitmentAnswer('teacherName', 'un professeur').valid, false)
  assert.equal(validateRecruitmentAnswer('teacherName', 'Pierre').valid, true)
  assert.equal(validateRecruitmentAnswer('rncpCode', '12').valid, false)
  assert.equal(validateRecruitmentAnswer('rncpCode', '35304').valid, true)
})

test('uses the official training title when the RNCP is already known', () => {
  const result = applyKnownRncpTraining(
    { trainingName: 'Conseiller clients', rncpCode: '' },
    [{ rncp_code: 'RNCP 35304', tp_name: 'TP Conseiller relation client à distance' }],
    '35304',
  )

  assert.equal(result.draft.trainingName, 'TP Conseiller relation client à distance')
  assert.equal(result.matchingModule.tp_name, 'TP Conseiller relation client à distance')
})
