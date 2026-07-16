import assert from 'node:assert/strict'
import test from 'node:test'

import { getStudentAudioProxyPath } from '../../src/studentCoursePlayback.js'

test('streams teaching audio through the authenticated API proxy', () => {
  assert.equal(
    getStudentAudioProxyPath({
      status: 'playing',
      id: 4,
      duration: 2700,
      type: 'cours',
      streamToken: 'signed ticket',
    }, 'cours.mp3'),
    '/api/audio/stream?stream_token=signed%20ticket&v=4-2700',
  )
})

test('does not download an audio file for silent break segments', () => {
  for (const type of ['qa', 'pause', 'pause_midi']) {
    assert.equal(
      getStudentAudioProxyPath({ status: 'playing', id: 5, duration: 900, type }, 'pause.mp3'),
      '',
    )
  }
})

test('does not fall back to a raw or unauthenticated teaching URL', () => {
  assert.equal(
    getStudentAudioProxyPath({ status: 'playing', id: 4, duration: 2700, type: 'cours' }, 'cours.mp3'),
    '',
  )
})
