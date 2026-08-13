const BREAK_AUDIO_TYPES = new Set(['qa', 'pause', 'pause_midi'])

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
