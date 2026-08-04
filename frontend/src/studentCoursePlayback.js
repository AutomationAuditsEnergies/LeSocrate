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

export function buildBreakPlaybackPlan({
  effectiveOffset = 0,
  effectiveDuration = 0,
  assetDuration = 0,
} = {}) {
  const offset = Math.max(0, Number(effectiveOffset) || 0)
  const effective = Math.max(0, Number(effectiveDuration) || 0)
  const asset = Math.max(0, Number(assetDuration) || 0)
  const extraSilentLead = Math.max(0, effective - asset)

  if (offset < extraSilentLead) {
    return {
      preRollRemaining: extraSilentLead - offset,
      mediaOffset: 0,
      extraSilentLead,
    }
  }

  const shortenedAssetOffset = Math.max(0, asset - effective)
  const elapsedInsideAsset = Math.max(0, offset - extraSilentLead)
  return {
    preRollRemaining: 0,
    mediaOffset: Math.min(asset, shortenedAssetOffset + elapsedInsideAsset),
    extraSilentLead,
  }
}
