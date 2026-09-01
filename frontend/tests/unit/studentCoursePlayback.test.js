import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clampStudentAudioOffset,
  getStudentAudioProxyPath,
  getStudentCourseView,
  getStudentLiveAudioOffset,
  positionStudentAudio,
  saveStudentCourseView,
  synchronizeStudentAudioToLiveOffset,
} from '../../src/studentCoursePlayback.js'

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

test('streams the timed MP3 for Q&A and break segments', () => {
  for (const type of ['qa', 'pause', 'pause_midi']) {
    assert.equal(
      getStudentAudioProxyPath({
        status: 'playing',
        id: 5,
        duration: 900,
        type,
        streamToken: `ticket-${type}`,
      }, 'pause.mp3'),
      `/api/audio/stream?stream_token=ticket-${type}&v=5-900`,
    )
  }
})

test('does not fall back to a raw or unauthenticated teaching URL', () => {
  assert.equal(
    getStudentAudioProxyPath({ status: 'playing', id: 4, duration: 2700, type: 'cours' }, 'cours.mp3'),
    '',
  )
})

test('restores the slide view and defaults new sessions to slides', () => {
  const values = new Map()
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  }

  assert.equal(getStudentCourseView(storage), 'slides')
  assert.equal(saveStudentCourseView('professor', storage), 'professor')
  assert.equal(getStudentCourseView(storage), 'professor')
  assert.equal(saveStudentCourseView('slides', storage), 'slides')
  assert.equal(getStudentCourseView(storage), 'slides')
})

test('clamps a resumed offset inside the decoded audio duration', () => {
  assert.equal(clampStudentAudioOffset(120, 600), 120)
  assert.equal(clampStudentAudioOffset(700, 600), 599.95)
  assert.equal(clampStudentAudioOffset(-10, 600), 0)
})

test('keeps a late arrival and a refreshed player on the live course clock', () => {
  const courseStartedAt = Date.UTC(2026, 8, 1, 8, 5, 0)
  const liveOffset = getStudentLiveAudioOffset(300, courseStartedAt, {
    nowMs: courseStartedAt + 2500,
    duration: 2100,
  })
  assert.equal(liveOffset, 302.5)

  const media = {
    readyState: 4,
    duration: 2100,
    seeking: false,
    currentTime: 0,
  }
  assert.equal(synchronizeStudentAudioToLiveOffset(media, liveOffset), true)
  assert.equal(media.currentTime, 302.5)
  assert.equal(synchronizeStudentAudioToLiveOffset(media, 303), false)
})

test('waits for metadata and a completed seek before resuming audio', async () => {
  class DeferredSeekMedia extends EventTarget {
    constructor() {
      super()
      this.readyState = 0
      this.duration = Number.NaN
      this.seeking = false
      this._currentTime = 0
    }

    get currentTime() {
      return this._currentTime
    }

    set currentTime(value) {
      this.seeking = true
      globalThis.setTimeout(() => {
        this._currentTime = value
        this.seeking = false
        this.dispatchEvent(new Event('seeked'))
      }, 5)
    }
  }

  const media = new DeferredSeekMedia()
  let resolved = false
  const positioned = positionStudentAudio(media, 165, { timeoutMs: 200 })
    .then((offset) => {
      resolved = true
      return offset
    })

  await new Promise((resolve) => globalThis.setTimeout(resolve, 5))
  assert.equal(resolved, false)

  media.readyState = 1
  media.duration = 900
  media.dispatchEvent(new Event('loadedmetadata'))

  assert.equal(await positioned, 165)
  assert.equal(media.currentTime, 165)
  assert.equal(resolved, true)
})
