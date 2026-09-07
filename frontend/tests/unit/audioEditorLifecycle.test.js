import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  stopMediaPlayback,
  stopWaveSurferPlayback,
} from '../../src/components/audioPlaybackLifecycle.js'

const editorSource = readFileSync(
  new URL('../../src/components/AudioEditor.jsx', import.meta.url),
  'utf8',
)
const foldersSource = readFileSync(
  new URL('../../src/components/CoursFolders.jsx', import.meta.url),
  'utf8',
)

test('stops and unloads a temporary audio element idempotently', () => {
  const calls = []
  const media = {
    currentTime: 19,
    pause: () => calls.push('pause'),
    removeAttribute: name => calls.push(`remove:${name}`),
    load: () => calls.push('load'),
  }

  stopMediaPlayback(media, { unload: true })
  stopMediaPlayback(media, { unload: true })

  assert.equal(media.currentTime, 0)
  assert.deepEqual(calls, [
    'pause', 'remove:src', 'load',
    'pause', 'remove:src', 'load',
  ])
})

test('pauses both WaveSurfer and its underlying media', () => {
  let wavePauses = 0
  let mediaPauses = 0
  const waveSurfer = {
    pause: () => { wavePauses += 1 },
    getMediaElement: () => ({ pause: () => { mediaPauses += 1 } }),
  }

  stopWaveSurferPlayback(waveSurfer)

  assert.equal(wavePauses, 1)
  assert.equal(mediaPauses, 1)
})

test('stops every audio source before editor unmount and browser navigation', () => {
  assert.match(editorSource, /const stopAllPlayback = useCallback/)
  assert.match(editorSource, /stopPreviewPlayback\(\)/)
  assert.match(editorSource, /stopStitchedPlayback\(\{ updateState \}\)/)
  assert.match(editorSource, /stopWaveSurferPlayback\(ws\)/)
  assert.match(editorSource, /window\.addEventListener\('pagehide', stopForNavigation\)/)
  assert.match(editorSource, /window\.addEventListener\('popstate', stopForNavigation\)/)
  assert.match(editorSource, /stopAllPlayback\(\{ destroyWaveSurfer: true, updateState: false \}\)/)
})

test('returns to the audio list from the parent header without a duplicate editor action', () => {
  assert.match(foldersSource, /onClick=\{\(\) => setAudioEditorFile\(null\)\}[\s\S]*name="chevron_left"[\s\S]*Audios/)
  assert.doesNotMatch(editorSource, /Retour aux audios/)
})

test('prevents asynchronous playback from restarting after unmount', () => {
  assert.match(editorSource, /playbackEpochRef\.current !== playbackEpoch/)
  assert.match(editorSource, /!mountedRef\.current[\s\S]*wsRef\.current !== ws/)
  assert.match(editorSource, /resumePlayback[\s\S]*!cancelled[\s\S]*mountedRef\.current/)
})

test('streams large audio from precomputed peaks without fetching a full blob', () => {
  assert.match(editorSource, /audio-playback-manifest/)
  assert.match(editorSource, /await ws\.load\(manifest\.url, \[peaks\], manifestDuration\)/)
  assert.doesNotMatch(editorSource, /await resp\.blob\(\)/)
  assert.doesNotMatch(editorSource, /ws\.loadBlob\(/)
  assert.doesNotMatch(editorSource, /backend: 'WebAudio'/)
})

test('refreshes the signed stream URL and resumes after a media error', () => {
  assert.match(editorSource, /for \(let attempt = 0; attempt < 3; attempt \+= 1\)/)
  assert.match(editorSource, /loadAudioIntoWaveSurfer\(ws, \{ resumeAt, resumePlayback \}\)/)
  assert.match(editorSource, /if \(safeResumeAt > 0\) ws\.setTime\(safeResumeAt\)/)
})
