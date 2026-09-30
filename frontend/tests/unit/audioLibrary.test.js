import assert from 'node:assert/strict'
import test from 'node:test'

import { classifyFormationAudios } from '../../src/audioLibrary.js'

test('classifies the actual dynamic audio list without inventing legacy files', () => {
  const audios = [
    { name: 'day-1/cours_01.mp3', url: 'course' },
    { name: 'day-1/qa_01.mp3', url: 'qa' },
    { name: 'day-1/pause_midi_01.mp3', url: 'lunch' },
    { name: 'day-1/conclusion.mp3', url: 'other' },
  ]

  const groups = classifyFormationAudios(audios)

  assert.deepEqual(groups.courses.map((audio) => audio.displayName), ['cours_01.mp3'])
  assert.deepEqual(groups.questions.map((audio) => audio.displayName), ['qa_01.mp3'])
  assert.deepEqual(groups.pauses.map((audio) => audio.displayName), ['pause_midi_01.mp3'])
  assert.deepEqual(groups.other.map((audio) => audio.displayName), ['conclusion.mp3'])
  assert.equal(Object.values(groups).flat().length, audios.length)
})

test('accepts alternate prefixes and ignores malformed entries', () => {
  const groups = classifyFormationAudios([
    { name: 'course-02.mp3' },
    { name: 'questions-réponses-02.mp3' },
    { name: 'break-02.mp3' },
    null,
    {},
  ])

  assert.equal(groups.courses.length, 1)
  assert.equal(groups.questions.length, 1)
  assert.equal(groups.pauses.length, 1)
  assert.equal(groups.other.length, 0)
})

test('returns empty groups when no audio has been generated', () => {
  assert.deepEqual(classifyFormationAudios(undefined), {
    courses: [],
    pauses: [],
    questions: [],
    other: [],
  })
})
