import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createRecruitmentDraft,
  deleteActiveRecruitmentDraft,
  isNewRecruitmentRequest,
  loadActiveRecruitmentDraft,
  recruitmentApproximateDayCount,
  recruitmentMissingFields,
  saveActiveRecruitmentDraft,
} from '../../src/recruitmentDraft.js'

const memory = new Map()
globalThis.localStorage = {
  getItem: (key) => memory.get(key) ?? null,
  setItem: (key, value) => memory.set(key, String(value)),
  removeItem: (key) => memory.delete(key),
}

test('keeps one resumable draft across conversation, calendar and template steps', () => {
  memory.clear()
  const draft = createRecruitmentDraft({
    trainingName: 'TP Conseiller relation client',
    rncpCode: 'RNCP 35304',
    startDate: '2030-09-02',
    durationValue: 4,
    durationUnit: 'semaines',
    weeklyCourseCount: 2,
    teachingDays: ['lundi', 'mercredi'],
    selectedDates: ['2030-09-02', '2030-09-04'],
    templateAssignments: { '2030-09-02': 'template-7' },
    progress: 'template',
  })

  const saved = saveActiveRecruitmentDraft(draft)
  const restored = loadActiveRecruitmentDraft()

  assert.equal(restored.id, saved.id)
  assert.equal(restored.progress, 'template')
  assert.deepEqual(restored.selectedDates, ['2030-09-02', '2030-09-04'])
  assert.deepEqual(restored.templateAssignments, { '2030-09-02': 'template-7' })
  assert.deepEqual(recruitmentMissingFields(restored), [])
  assert.equal(recruitmentApproximateDayCount(restored), 8)
})

test('gives independent recruitments distinct identifiers and detects restart requests', () => {
  const first = createRecruitmentDraft()
  const second = createRecruitmentDraft()

  assert.notEqual(first.id, second.id)
  assert.equal(isNewRecruitmentRequest('Je veux commencer un nouveau recrutement'), true)
  assert.equal(isNewRecruitmentRequest('Continuons cette configuration'), false)
})

test('deletes an abandoned unvalidated draft instead of archiving it', () => {
  saveActiveRecruitmentDraft(createRecruitmentDraft({ trainingName: 'À supprimer' }))
  deleteActiveRecruitmentDraft()

  assert.equal(loadActiveRecruitmentDraft(), null)
})
