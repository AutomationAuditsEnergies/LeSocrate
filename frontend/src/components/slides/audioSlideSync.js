export function audioBasename(value = '') {
  const clean = String(value || '').split('?')[0].split('#')[0]
  const last = clean.split('/').pop() || clean
  try {
    return decodeURIComponent(last)
  } catch {
    return last
  }
}

function toNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const COURSE_AUDIO_DURATIONS = {
  'cours_9h00_9h45.mp3': 2700,
  'cours_10h05_10h50.mp3': 2700,
  'cours_11h05_12h00.mp3': 3300,
  'cours_12h20_13h05.mp3': 2700,
  'cours_14h45_15h45.mp3': 3600,
  'cours_16h00_17h00.mp3': 3600,
  'cours_17h25_18h15.mp3': 3000,
}

function buildFallbackWordTimings(slides = [], filename = '') {
  const targetName = audioBasename(filename)
  const duration = COURSE_AUDIO_DURATIONS[targetName]
  if (!duration || !slides.length) return []

  const parsed = slides.map((slide, index) => {
    const sourceRef = slide?.source_ref || {}
    const startWord = Math.max(0, toNumber(sourceRef.word_start ?? sourceRef.start_word) ?? 0)
    const endWord = Math.max(0, toNumber(sourceRef.word_end ?? sourceRef.end_word) ?? 0)
    return { slide, index, startWord, endWord }
  })

  let maxWord = parsed.reduce((max, item) => Math.max(max, item.startWord, item.endWord), 0)
  if (maxWord <= 0) {
    maxWord = Math.max(1, parsed.length)
    parsed.forEach((item, index) => {
      item.startWord = index
      item.endWord = index + 1
    })
  }

  let previousEnd = 0
  return parsed.map((item, index) => {
    let start = Math.max(previousEnd, (item.startWord / maxWord) * duration)
    let endWord = item.endWord
    if (endWord <= item.startWord) {
      const nextStart = parsed[index + 1]?.startWord ?? maxWord
      endWord = Math.max(item.startWord + 1, nextStart)
    }
    let end = Math.min(duration, Math.max(start + 0.5, (endWord / maxWord) * duration))
    if (index + 1 < parsed.length) {
      const nextStart = (parsed[index + 1].startWord / maxWord) * duration
      end = Math.min(end, Math.max(start + 0.5, nextStart))
    }
    previousEnd = end
    return {
      slide: item.slide,
      slideIndex: item.index,
      audioName: targetName,
      start,
      end,
      duration: end - start,
      fallback: true,
    }
  })
}

// Libellé de durée pour le slide pause dédié : 600 → "10 minutes", 5400 → "1h30".
export function breakDurationLabel(seconds) {
  const minutes = Math.round(Math.max(0, Number(seconds) || 0) / 60)
  if (!minutes) return null
  if (minutes === 1) return '1 minute'
  if (minutes < 60) return `${minutes} minutes`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m ? `${h}h${String(m).padStart(2, '0')}` : `${h} heure${h > 1 ? 's' : ''}`
}

export function buildAudioSlideTimings(slides = [], audioSync = {}, filename = '') {
  const targetName = audioBasename(filename)
  const slideById = new Map()
  const rows = []
  const seen = new Set()

  slides.forEach((slide, index) => {
    if (slide?.slide_id) slideById.set(slide.slide_id, { slide, index })
  })

  const addTiming = (rawTiming, fallbackSlide, fallbackIndex) => {
    if (!rawTiming) return
    const slideId = rawTiming.slide_id || fallbackSlide?.slide_id
    const resolved = slideId ? slideById.get(slideId) : null
    const slide = resolved?.slide || fallbackSlide
    const slideIndex = Number.isInteger(resolved?.index) ? resolved.index : fallbackIndex
    if (!slide || !Number.isInteger(slideIndex)) return

    const rawAudioName = rawTiming.audio_filename || rawTiming.filename || slide.audio_filename
    const audioName = audioBasename(rawAudioName)
    if (targetName && audioName && audioName !== targetName) return
    if (targetName && !audioName) return

    const start = toNumber(rawTiming.start_time ?? rawTiming.audio_start_time ?? rawTiming.trigger_time)
    const end = toNumber(rawTiming.end_time ?? rawTiming.audio_end_time)
    if (start === null || end === null || end <= start) return

    const key = `${slide.slide_id || slideIndex}:${audioName}:${start}:${end}`
    if (seen.has(key)) return
    seen.add(key)
    rows.push({
      slide,
      slideIndex,
      audioName,
      start,
      end,
      duration: end - start,
    })
  }

  slides.forEach((slide, index) => {
    const segments = Array.isArray(slide?.audio_segments) ? slide.audio_segments : []
    segments.forEach(segment => addTiming(segment, slide, index))
    if (!segments.length && slide?.audio_filename) {
      addTiming(slide, slide, index)
    }
  })

  const syncTimings = Array.isArray(audioSync?.timings) ? audioSync.timings : []
  syncTimings.forEach(timing => {
    const resolved = timing?.slide_id ? slideById.get(timing.slide_id) : null
    addTiming(timing, resolved?.slide, resolved?.index)
  })

  if (!rows.length) {
    return buildFallbackWordTimings(slides, filename)
  }

  return rows.sort((a, b) => a.start - b.start || a.slideIndex - b.slideIndex)
}

export function findActiveAudioSlideTiming(timings = [], currentTimeMs = 0) {
  if (!timings.length) return null
  const seconds = Number(currentTimeMs || 0) / 1000
  return timings.find(item => seconds >= item.start && seconds < item.end)
    || [...timings].reverse().find(item => seconds >= item.start)
    || timings[0]
}
