const BREAK_AUDIO_TYPES = new Set(['qa', 'pause', 'pause_midi'])
const STUDENT_COURSE_VIEW_KEY = 'student-course-view'
const MEDIA_METADATA_READY_STATE = 1

export function isBreakAudioType(type) {
  return BREAK_AUDIO_TYPES.has(type)
}

export function getStudentAudioProxyPath(audioInfo, audioName = '') {
  if (
    audioInfo?.status !== 'playing'
    || !audioInfo.streamToken
  ) return ''
  const version = `${audioInfo.id || audioName}-${audioInfo.duration || 0}`
  return `/api/audio/stream?stream_token=${encodeURIComponent(audioInfo.streamToken)}&v=${encodeURIComponent(version)}`
}

export function getStudentCourseView(storage) {
  try {
    const courseStorage = storage ?? globalThis.sessionStorage
    return courseStorage?.getItem(STUDENT_COURSE_VIEW_KEY) === 'professor' ? 'professor' : 'slides'
  } catch {
    return 'slides'
  }
}

export function saveStudentCourseView(view, storage) {
  const normalizedView = view === 'professor' ? 'professor' : 'slides'
  try {
    const courseStorage = storage ?? globalThis.sessionStorage
    courseStorage?.setItem(STUDENT_COURSE_VIEW_KEY, normalizedView)
  } catch {
    // sessionStorage may be unavailable in hardened/private browser contexts.
  }
  return normalizedView
}

export function clampStudentAudioOffset(offset, duration) {
  const requestedOffset = Math.max(0, Number(offset) || 0)
  const decodedDuration = Number(duration)
  if (!Number.isFinite(decodedDuration) || decodedDuration <= 0) return requestedOffset
  return Math.min(requestedOffset, Math.max(0, decodedDuration - 0.05))
}

export function getStudentLiveAudioOffset(
  initialOffset,
  startedAtMs,
  {
    nowMs = Date.now(),
    duration = 0,
  } = {},
) {
  const elapsedSeconds = Math.max(0, (Number(nowMs) - Number(startedAtMs)) / 1000) || 0
  return clampStudentAudioOffset((Number(initialOffset) || 0) + elapsedSeconds, duration)
}

export function synchronizeStudentAudioToLiveOffset(
  media,
  liveOffset,
  {
    knownDuration = 0,
    toleranceSeconds = 1.25,
  } = {},
) {
  if (!media || Number(media.readyState) < MEDIA_METADATA_READY_STATE || media.seeking) return false

  const mediaDuration = Number.isFinite(Number(media.duration))
    ? Number(media.duration)
    : Number(knownDuration)
  const targetOffset = clampStudentAudioOffset(liveOffset, mediaDuration)
  const currentOffset = Math.max(0, Number(media.currentTime) || 0)
  const tolerance = Math.max(0, Number(toleranceSeconds) || 0)
  if (Math.abs(currentOffset - targetOffset) <= tolerance) return false

  try {
    media.currentTime = targetOffset
    return true
  } catch {
    return false
  }
}

function abortError() {
  const error = new Error('Audio positioning cancelled')
  error.name = 'AbortError'
  return error
}

export function positionStudentAudio(
  media,
  offset,
  {
    knownDuration = 0,
    signal,
    timeoutMs = 8000,
    toleranceSeconds = 0.5,
  } = {},
) {
  if (!media) return Promise.reject(new TypeError('A media element is required'))

  const requestedOffset = Math.max(0, Number(offset) || 0)
  const tolerance = Math.max(0, Number(toleranceSeconds) || 0)
  const eventNames = ['loadedmetadata', 'durationchange', 'progress', 'canplay', 'seeked', 'timeupdate']

  return new Promise((resolve, reject) => {
    let finished = false
    let seekRequested = false
    let targetOffset = requestedOffset

    const cleanup = () => {
      eventNames.forEach((eventName) => media.removeEventListener(eventName, handleMediaEvent))
      if (signal) signal.removeEventListener('abort', handleAbort)
      globalThis.clearTimeout(timeout)
    }

    const finish = (callback, value) => {
      if (finished) return
      finished = true
      cleanup()
      callback(value)
    }

    const currentPositionMatches = () => (
      Math.abs((Number(media.currentTime) || 0) - targetOffset) <= tolerance
    )

    const resolveTargetOffset = () => {
      const mediaDuration = Number.isFinite(Number(media.duration))
        ? Number(media.duration)
        : Number(knownDuration)
      targetOffset = clampStudentAudioOffset(requestedOffset, mediaDuration)
    }

    const tryPosition = () => {
      if (Number(media.readyState) < MEDIA_METADATA_READY_STATE) return
      resolveTargetOffset()

      if (currentPositionMatches() && !media.seeking) {
        finish(resolve, targetOffset)
        return
      }
      if (media.seeking) return

      try {
        seekRequested = true
        media.currentTime = targetOffset
      } catch {
        return
      }

      // Browsers set `seeking` synchronously for a real seek. This fallback
      // handles media implementations that apply an already-buffered seek at once.
      globalThis.queueMicrotask(() => {
        if (seekRequested && !media.seeking && currentPositionMatches()) {
          finish(resolve, targetOffset)
        }
      })
    }

    function handleMediaEvent(event) {
      if (event.type === 'seeked' && currentPositionMatches()) {
        finish(resolve, targetOffset)
        return
      }
      tryPosition()
    }

    function handleAbort() {
      finish(reject, abortError())
    }

    eventNames.forEach((eventName) => media.addEventListener(eventName, handleMediaEvent))
    if (signal) signal.addEventListener('abort', handleAbort, { once: true })

    const timeout = globalThis.setTimeout(() => {
      finish(reject, new Error(`Audio positioning timed out at ${targetOffset}s`))
    }, Math.max(0, Number(timeoutMs) || 0))

    if (signal?.aborted) {
      handleAbort()
      return
    }
    tryPosition()
  })
}
