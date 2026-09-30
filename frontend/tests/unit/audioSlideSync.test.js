import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildAudioSlideTimings,
  isCourseAudioFilename,
} from '../../src/components/slides/audioSlideSync.js'

test('recognizes both V1 cours_ and V2 course_ audio names', () => {
  assert.equal(isCourseAudioFilename('cours_9h00_9h45.mp3'), true)
  assert.equal(isCourseAudioFilename('course_01.mp3'), true)
  assert.equal(isCourseAudioFilename('/folder/COURSE-02.MP3?x=1'), true)
  assert.equal(isCourseAudioFilename('qa_01.mp3'), false)
})

test('builds V2 slide timings for course_ filenames', () => {
  const slides = [
    { slide_id: 's1', template_type: 'definition', data: {} },
  ]
  const timings = buildAudioSlideTimings(slides, {
    timings: [{
      slide_id: 's1',
      audio_filename: 'course_01.mp3',
      start_time: 0,
      end_time: 12.5,
    }],
  }, 'course_01.mp3')

  assert.equal(timings.length, 1)
  assert.equal(timings[0].audioName, 'course_01.mp3')
  assert.equal(timings[0].end, 12.5)
})
