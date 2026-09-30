export function stopMediaPlayback(media, { reset = true, unload = false } = {}) {
  if (!media) return

  try {
    media.pause?.()
  } catch {
    // Le média peut déjà avoir été détruit par le navigateur ou WaveSurfer.
  }

  if (reset) {
    try {
      media.currentTime = 0
    } catch {
      // Certains médias ne permettent pas de seek tant que leurs métadonnées manquent.
    }
  }

  if (unload) {
    try {
      media.removeAttribute?.('src')
      media.load?.()
    } catch {
      // Le nettoyage doit rester idempotent pendant un démontage React.
    }
  }
}

export function stopWaveSurferPlayback(waveSurfer) {
  if (!waveSurfer) return

  try {
    waveSurfer.pause?.()
  } catch {
    // L'instance peut être entre deux chargements ou déjà détruite.
  }

  stopMediaPlayback(waveSurfer.getMediaElement?.(), { reset: false })
}
