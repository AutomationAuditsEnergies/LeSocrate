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

  return rows.sort((a, b) => a.start - b.start || a.slideIndex - b.slideIndex)
}

export function findActiveAudioSlideTiming(timings = [], currentTimeMs = 0) {
  if (!timings.length) return null
  const seconds = Number(currentTimeMs || 0) / 1000
  return timings.find(item => seconds >= item.start && seconds < item.end)
    || (seconds < timings[0].start ? timings[0] : null)
}
