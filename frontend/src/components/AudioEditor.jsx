import { useState, useEffect, useRef, useCallback } from 'react'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.js'
import { apiUrl, getPlatformId } from '../api'

const Icon = ({ name, style, className = '' }) => (
  <span className={`material-icons ${className}`} style={style}>{name}</span>
)

function formatTime(ms) {
  if (!ms && ms !== 0) return '0:00'
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

// ─── AudioEditor ─────────────────────────────────────────────────────────────
// Props:
//   folderId      — ID du dossier
//   filename      — nom du fichier MP3 (ex: cours_9h00_9h45.mp3)
//   darkMode      — bool
//   colors        — objet colors du parent
//   onClose       — callback fermeture
export default function AudioEditor({ folderId, filename, darkMode, colors, onClose }) {
  const waveRef = useRef(null)       // div DOM pour WaveSurfer
  const wsRef = useRef(null)         // instance WaveSurfer
  const regionsRef = useRef(null)    // plugin Regions
  const activeRegionRef = useRef(null)

  const audioCtxRef = useRef(null)      // Web Audio API context pour écoute splicée
  const stitchedSourcesRef = useRef([]) // sources planifiées (pour pouvoir stopper)

  const [mode, setMode] = useState('cut')          // 'cut' | 'replace'
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [region, setRegion] = useState(null)       // {start, end} en ms
  const [replaceText, setReplaceText] = useState('')
  const [previewId, setPreviewId] = useState(null)
  const [previewB64, setPreviewB64] = useState(null)   // base64 du TTS preview
  const [previewAudio, setPreviewAudio] = useState(null)
  const [stitchedPlaying, setStitchedPlaying] = useState(false)
  const [loadingStitch, setLoadingStitch] = useState(false)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState(null)

  const audioUrlRef = useRef(null)   // URL audio courante (mise à jour après cut/replace)

  const clearAudioUrl = useCallback(() => {
    audioUrlRef.current = null
  }, [])

  const audioFetchHeaders = useCallback(() => {
    const token = localStorage.getItem('auth_token')
    const platformId = getPlatformId()
    return {
      ...(token ? { 'X-Auth-Token': token } : {}),
      'X-Platform-Id': platformId,
    }
  }, [])

  // Donner une URL backend directement à WaveSurfer évite le double chargement
  // fetch -> Blob -> WaveSurfer. Le backend streame le MP3 et supporte Range.
  const buildAudioStreamUrl = useCallback(() => {
    clearAudioUrl()
    const url = apiUrl(`/api/hr/cours-folders/${folderId}/audio-stream/${encodeURIComponent(filename)}?v=${Date.now()}`)
    audioUrlRef.current = url
    return url
  }, [clearAudioUrl, folderId, filename])

  // ── Init WaveSurfer ──
  useEffect(() => {
    if (!waveRef.current) return

    let cancelled = false
    setError(null)
    setLoading(true)

    const regions = RegionsPlugin.create()
    regionsRef.current = regions

    const ws = WaveSurfer.create({
      container: waveRef.current,
      waveColor: darkMode ? '#475569' : '#cbd5e1',
      progressColor: darkMode ? '#cbd5e1' : '#334155',
      cursorColor: '#f59e0b',
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      height: 80,
      normalize: true,
      minPxPerSec: 0, // auto-fit au chargement
      autoScroll: true,
      fillParent: true,
      blobMimeType: 'audio/mpeg',
      fetchParams: {
        credentials: 'include',
        headers: audioFetchHeaders(),
      },
      plugins: [regions],
    })
    wsRef.current = ws

    // Zoom trackpad / molette
    const ZOOM_MIN = 0          // 0 = fit-container
    const ZOOM_MAX = 800        // ~800 px/s = zoom très fin
    const ZOOM_STEP = 1.15
    let currentZoom = 0
    const handleWheel = (e) => {
      if (!wsRef.current || !duration) {
        // fallback si duration pas encore dispo : utiliser getDuration
      }
      e.preventDefault()
      const dur = wsRef.current?.getDuration() || 0
      if (!dur) return
      // pxPerSec actuel si jamais 0 → calculer d'après la largeur du container
      if (!currentZoom) {
        currentZoom = (waveRef.current?.clientWidth || 800) / dur
      }
      const delta = e.deltaY
      if (delta < 0) {
        currentZoom = Math.min(currentZoom * ZOOM_STEP, ZOOM_MAX)
      } else {
        currentZoom = Math.max(currentZoom / ZOOM_STEP, (waveRef.current?.clientWidth || 800) / dur)
      }
      try {
        wsRef.current.zoom(currentZoom)
      } catch (err) {
        // zoom peut échouer si pas prêt
      }
    }
    const waveEl = waveRef.current
    waveEl?.addEventListener('wheel', handleWheel, { passive: false })

    Promise.resolve(buildAudioStreamUrl())
      .then(url => { if (!cancelled) return ws.load(url) })
      .catch(e => {
        if (cancelled) return
        // ws.destroy() pendant un fetch en cours déclenche un AbortError que
        // Chrome propage souvent en "TypeError: Failed to fetch" — bruit qui
        // collait un faux message d'erreur sur la 2e tentative réussie.
        if (e?.name === 'AbortError') return
        setError('Impossible de charger l\'audio : ' + e.message)
      })

    ws.on('ready', () => {
      setDuration(ws.getDuration() * 1000)
      setLoading(false)
    })
    ws.on('timeupdate', (t) => setCurrentTime(t * 1000))
    ws.on('play', () => setPlaying(true))
    ws.on('pause', () => setPlaying(false))
    ws.on('finish', () => setPlaying(false))

    // Permettre la création de régions par drag
    regions.enableDragSelection({ color: darkMode ? 'rgba(203, 213, 225, 0.25)' : 'rgba(51, 65, 85, 0.18)' })

    regions.on('region-created', (r) => {
      if (activeRegionRef.current) {
        activeRegionRef.current.remove()
      }
      activeRegionRef.current = r
      setRegion({ start: r.start * 1000, end: r.end * 1000 })
      setPreviewId(null)
      setPreviewAudio(null)
    })

    regions.on('region-updated', (r) => {
      setRegion({ start: r.start * 1000, end: r.end * 1000 })
      setPreviewId(null)
      setPreviewAudio(null)
    })

    return () => {
      cancelled = true
      waveEl?.removeEventListener('wheel', handleWheel)
      ws.destroy()
      stopStitchedPlayback()
      clearAudioUrl()
    }
  }, [audioFetchHeaders, buildAudioStreamUrl, clearAudioUrl, darkMode])

  // Changer la couleur de la région selon le mode
  useEffect(() => {
    activeRegionRef.current?.setOptions({
      color: mode === 'cut'
        ? 'rgba(239, 68, 68, 0.25)'
        : darkMode ? 'rgba(203, 213, 225, 0.25)' : 'rgba(51, 65, 85, 0.18)',
    })
  }, [mode])

  const togglePlay = async () => {
    const ws = wsRef.current
    if (!ws) return

    if (ws.isPlaying()) {
      ws.pause()
      return
    }

    // Si le navigateur est encore en train de chercher la position (seek en cours
    // après un clic sur la waveform), on attend la fin avant de lancer la lecture.
    // Sinon media.play() est appelé pendant le seeking et produit du silence.
    const media = ws.getMediaElement?.()
    if (media?.seeking) {
      await new Promise(resolve => {
        const onSeeked = () => { media.removeEventListener('seeked', onSeeked); resolve() }
        media.addEventListener('seeked', onSeeked)
      })
    }

    try {
      await ws.play()
    } catch (_) {
      // Autoplay policy du navigateur — ignoré silencieusement
    }
  }

  const restartFromBeginning = async () => {
    const ws = wsRef.current
    if (!ws) return
    try {
      ws.seekTo(0)
      setCurrentTime(0)
      await ws.play()
    } catch (_) {
      setCurrentTime(0)
    }
  }

  const clearRegion = () => {
    if (activeRegionRef.current) {
      activeRegionRef.current.remove()
      activeRegionRef.current = null
    }
    setRegion(null)
    setPreviewId(null)
    setPreviewAudio(null)
  }

  // ── Écoute splicée côté client (Web Audio API) ──
  const stopStitchedPlayback = () => {
    stitchedSourcesRef.current.forEach(src => { try { src.stop() } catch (e) {} })
    stitchedSourcesRef.current = []
    try { audioCtxRef.current?.close() } catch (e) {}
    audioCtxRef.current = null
    setStitchedPlaying(false)
  }

  const handleListenWithReplacement = async () => {
    if (!previewB64 || !region) return
    stopStitchedPlayback()
    setLoadingStitch(true)
    setError(null)
    try {
      const audioCtx = new AudioContext()
      audioCtxRef.current = audioCtx

      // Récupérer le buffer décodé depuis WaveSurfer (déjà en mémoire, 0 réseau)
      const wsBuffer = wsRef.current?.getDecodedData()
      if (!wsBuffer) throw new Error('Audio non chargé')

      // Copier dans notre AudioContext (les buffers sont liés à leur context)
      const origBuffer = audioCtx.createBuffer(
        wsBuffer.numberOfChannels, wsBuffer.length, wsBuffer.sampleRate
      )
      for (let ch = 0; ch < wsBuffer.numberOfChannels; ch++) {
        origBuffer.copyToChannel(wsBuffer.getChannelData(ch), ch)
      }

      // Décoder le TTS preview depuis le base64
      const previewBytes = Uint8Array.from(atob(previewB64), c => c.charCodeAt(0))
      const previewBuffer = await audioCtx.decodeAudioData(previewBytes.buffer)

      const sr = origBuffer.sampleRate
      const startSec = region.start / 1000
      const endSec = region.end / 1000

      // Jouer 8s avant la région (ou depuis le début)
      const listenFrom = Math.max(0, startSec - 8)

      const now = audioCtx.currentTime + 0.05

      // Part 1 : original de listenFrom jusqu'au début de la région
      const src1 = audioCtx.createBufferSource()
      src1.buffer = origBuffer
      const part1Duration = startSec - listenFrom
      src1.connect(audioCtx.destination)
      src1.start(now, listenFrom, part1Duration)

      // Part 2 : TTS preview
      const src2 = audioCtx.createBufferSource()
      src2.buffer = previewBuffer
      src2.connect(audioCtx.destination)
      src2.start(now + part1Duration)

      // Part 3 : original à partir de la fin de la région, pendant 8s max
      const src3 = audioCtx.createBufferSource()
      src3.buffer = origBuffer
      const part3Duration = Math.min(8, origBuffer.duration - endSec)
      src3.connect(audioCtx.destination)
      src3.start(now + part1Duration + previewBuffer.duration, endSec, part3Duration)

      stitchedSourcesRef.current = [src1, src2, src3]

      const totalDuration = part1Duration + previewBuffer.duration + part3Duration
      setStitchedPlaying(true)
      setLoadingStitch(false)

      setTimeout(() => {
        if (audioCtxRef.current === audioCtx) {
          stopStitchedPlayback()
        }
      }, (totalDuration + 0.5) * 1000)

    } catch (e) {
      setError('Erreur lors de la lecture splicée : ' + e.message)
      setLoadingStitch(false)
    }
  }

  // ── Couper ──
  const handleCut = async () => {
    if (!region) return
    setSaving(true)
    setError(null)
    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${folderId}/audio/${encodeURIComponent(filename)}/cut`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...audioFetchHeaders() },
          body: JSON.stringify({ start_ms: Math.round(region.start), end_ms: Math.round(region.end) }),
          credentials: 'include',
        }
      )
      const data = await resp.json()
      if (data.success) {
        setStatus(`✅ Coupé : ${formatTime(region.end - region.start)} supprimés. Rechargement...`)
        clearRegion()
        // Recharger depuis une nouvelle SAS URL (le blob a changé)
        setTimeout(async () => {
          try {
            const freshUrl = buildAudioStreamUrl()
            setLoading(true)
            wsRef.current?.load(freshUrl)
          } catch (e) { /* ignore */ }
          setStatus(null)
        }, 1500)
      } else {
        setError(data.error || 'Erreur lors du cut')
      }
    } catch (e) {
      setError('Erreur réseau')
    } finally {
      setSaving(false)
    }
  }

  // ── Prévisualiser le TTS ──
  const handlePreviewTTS = async () => {
    if (!replaceText.trim()) return
    setGenerating(true)
    setError(null)
    setPreviewId(null)
    setPreviewAudio(null)
    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${folderId}/audio/${encodeURIComponent(filename)}/replace-preview`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...audioFetchHeaders() },
          body: JSON.stringify({ text: replaceText }),
          credentials: 'include',
        }
      )
      const data = await resp.json()
      if (data.success) {
        setPreviewId(data.preview_id)
        setPreviewB64(data.audio_b64)
        stopStitchedPlayback()
        // Jouer le clip TTS seul pour aperçu immédiat
        const blob = new Blob(
          [Uint8Array.from(atob(data.audio_b64), c => c.charCodeAt(0))],
          { type: 'audio/mpeg' }
        )
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        setPreviewAudio(audio)
        audio.play()
      } else {
        setError(data.error || 'Erreur lors de la génération TTS')
      }
    } catch (e) {
      setError('Erreur réseau')
    } finally {
      setGenerating(false)
    }
  }

  // ── Confirmer le remplacement ──
  const handleReplaceConfirm = async () => {
    if (!region || !previewId) return
    setSaving(true)
    setError(null)
    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${folderId}/audio/${encodeURIComponent(filename)}/replace-confirm`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...audioFetchHeaders() },
          body: JSON.stringify({
            preview_id: previewId,
            start_ms: Math.round(region.start),
            end_ms: Math.round(region.end),
          }),
          credentials: 'include',
        }
      )
      const data = await resp.json()
      if (data.success) {
        setStatus('✅ Remplacement appliqué. Rechargement...')
        clearRegion()
        setReplaceText('')
        setTimeout(async () => {
          try {
            const freshUrl = buildAudioStreamUrl()
            setLoading(true)
            wsRef.current?.load(freshUrl)
          } catch (e) { /* ignore */ }
          setStatus(null)
        }, 1500)
      } else {
        setError(data.error || 'Erreur lors du remplacement')
      }
    } catch (e) {
      setError('Erreur réseau')
    } finally {
      setSaving(false)
    }
  }

  const border = colors.border
  const textPrimary = colors.text
  const textMuted = colors.textMuted
  const panelBg = darkMode ? '#111827' : '#f8fafc'
  const actionBg = colors.text
  const actionText = colors.cardBg

  return (
    <div className="flex min-h-0 flex-col" style={{ backgroundColor: colors.cardBg }}>
        {/* Header */}
        <div
          className="flex items-center justify-between gap-3 border-b px-5 py-3 flex-shrink-0"
          style={{ backgroundColor: panelBg, borderColor: colors.border }}
        >
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors"
            style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}`, color: colors.textSecondary }}
          >
            <Icon name="arrow_back" style={{ fontSize: '16px' }} />
            Retour aux audios
          </button>
          <div className="min-w-0 flex-1 text-right">
            <p className="truncate text-xs font-medium" style={{ color: colors.textMuted }}>
              {formatTime(currentTime)} / {formatTime(duration)}
            </p>
          </div>
        </div>

        {/* Corps */}
        <div className="max-h-[calc(92vh-112px)] flex-1 overflow-y-auto p-5 space-y-4">

          {/* Waveform */}
          <div
            className="rounded-xl p-3 relative"
            style={{ backgroundColor: colors.innerBg, border: `1px solid ${border}` }}
          >
            {loading && (
              <div className="absolute inset-0 flex items-center justify-center rounded-xl" style={{ backgroundColor: colors.innerBg }}>
                <div className="flex items-center gap-2" style={{ color: textMuted }}>
                  <Icon name="hourglass_empty" style={{ fontSize: '20px' }} />
                  <span className="text-sm">Chargement de l'audio...</span>
                </div>
              </div>
            )}
            <div ref={waveRef} />
            {/* Temps */}
            <div className="flex justify-between mt-1 text-xs" style={{ color: textMuted }}>
              <span>{formatTime(currentTime)}</span>
              <span>{formatTime(duration)}</span>
            </div>
          </div>

          {/* Actions */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={togglePlay}
              disabled={loading}
              className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              style={{ backgroundColor: actionBg, color: actionText }}
            >
              <Icon name={playing ? 'pause' : 'play_arrow'} style={{ fontSize: '18px' }} />
              {playing ? 'Pause' : 'Écouter'}
            </button>

            <button
              onClick={restartFromBeginning}
              disabled={loading}
              className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50"
              style={{ backgroundColor: colors.innerBg, color: colors.textSecondary, border: `1px solid ${colors.border}` }}
            >
              <Icon name="replay" style={{ fontSize: '16px' }} />
              Depuis le début
            </button>

            {['cut', 'replace'].map(m => (
              <button
                key={m}
                onClick={() => { setMode(m); setError(null) }}
                className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-all"
                style={{
                  backgroundColor: mode === m ? actionBg : colors.innerBg,
                  color: mode === m ? actionText : colors.textSecondary,
                  border: `1px solid ${mode === m ? actionBg : border}`,
                }}
              >
                <Icon name={m === 'cut' ? 'content_cut' : 'edit'} style={{ fontSize: '16px' }} />
                {m === 'cut' ? 'Couper' : 'Remplacer'}
              </button>
            ))}

            {region && (
              <div className="ml-auto flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium" style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}`, color: colors.textSecondary }}>
                <Icon name="crop_free" style={{ fontSize: '14px' }} />
                Sélection : {formatTime(region.start)} → {formatTime(region.end)}
                <span style={{ color: textMuted }}>({formatTime(region.end - region.start)})</span>
                <button onClick={clearRegion} className="ml-1 hover:opacity-70">
                  <Icon name="close" style={{ fontSize: '14px' }} />
                </button>
              </div>
            )}

            {!region && !loading && (
              <p className="ml-auto text-xs" style={{ color: textMuted }}>
                Faites glisser sur la forme d'onde pour sélectionner une région
              </p>
            )}
          </div>

          {/* Panel Cut */}
          {mode === 'cut' && (
            <div className="rounded-xl p-4 space-y-3" style={{ border: `1px solid ${border}` }}>
              <p className="text-sm" style={{ color: textPrimary }}>
                Sélectionnez une région sur la forme d'onde, puis confirmez la suppression.
                Les deux morceaux se rejoindront directement. <strong style={{ color: '#ef4444' }}>Irréversible.</strong>
              </p>
              {region && (
                <button
                  onClick={handleCut}
                  disabled={saving}
                  className="flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-bold text-white disabled:opacity-50"
                  style={{ backgroundColor: '#dc2626' }}
                >
                  <Icon name="content_cut" style={{ fontSize: '16px' }} />
                  {saving ? 'Suppression...' : `Couper ${formatTime(region.end - region.start)}`}
                </button>
              )}
            </div>
          )}

          {/* Panel Replace */}
          {mode === 'replace' && (
            <div className="rounded-xl p-4 space-y-3" style={{ border: `1px solid ${border}` }}>
              <p className="text-sm" style={{ color: textPrimary }}>
                Sélectionnez une région, écrivez le texte à lire à la place, prévisualisez, puis confirmez.
              </p>
              <textarea
                value={replaceText}
                onChange={e => { setReplaceText(e.target.value); setPreviewId(null) }}
                rows={4}
                placeholder="Écrivez ici le texte qui sera lu par la voix TTS à la place de la région sélectionnée..."
                className="w-full rounded-xl p-3 text-sm resize-y outline-none"
                style={{
                  backgroundColor: colors.innerBg,
                  color: textPrimary,
                  border: `1px solid ${border}`,
                }}
              />
              <div className="flex gap-2 flex-wrap">
                <button
                  onClick={handlePreviewTTS}
                  disabled={!replaceText.trim() || generating}
                  className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50"
                  style={{ backgroundColor: colors.innerBg, color: colors.textSecondary, border: `1px solid ${colors.border}` }}
                >
                  <Icon name={generating ? 'hourglass_empty' : 'hearing'} style={{ fontSize: '16px' }} />
                  {generating ? 'Génération TTS...' : previewId ? 'Réécouter le clip' : 'Prévisualiser la voix'}
                </button>

                {previewId && region && (
                  <>
                    <button
                      onClick={stitchedPlaying ? stopStitchedPlayback : handleListenWithReplacement}
                      disabled={loadingStitch}
                      title="Écoute l'audio original avec votre extrait splicé dedans (8s avant → nouveau TTS → 8s après)"
                      className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50"
                      style={{ backgroundColor: darkMode ? '#1a2e1a' : '#dcfce7', color: '#16a34a', border: '1px solid #16a34a' }}
                    >
                      <Icon name={loadingStitch ? 'hourglass_empty' : stitchedPlaying ? 'stop' : 'play_circle'} style={{ fontSize: '16px' }} />
                      {loadingStitch ? 'Préparation...' : stitchedPlaying ? 'Arrêter' : 'Écouter avec l\'extrait remplacé'}
                    </button>

                    <button
                      onClick={handleReplaceConfirm}
                      disabled={saving}
                      className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold text-white disabled:opacity-50"
                      style={{ backgroundColor: actionBg, color: actionText }}
                    >
                      <Icon name="check" style={{ fontSize: '16px' }} />
                      {saving ? 'Application...' : 'Confirmer le remplacement'}
                    </button>
                  </>
                )}
              </div>

              {previewId && (
                <p className="text-xs" style={{ color: '#16a34a' }}>
                  ✅ TTS généré. Écoutez le clip seul ou l'audio complet avec l'extrait en contexte, puis confirmez.
                </p>
              )}
            </div>
          )}

          {/* Status / Error */}
          {status && (
            <div className="rounded-xl px-4 py-2.5 text-sm font-medium" style={{ backgroundColor: darkMode ? '#14532d' : '#dcfce7', color: '#16a34a' }}>
              {status}
            </div>
          )}
          {error && (
            <div className="rounded-xl px-4 py-2.5 text-sm font-medium" style={{ backgroundColor: darkMode ? '#7f1d1d' : '#fee2e2', color: '#ef4444' }}>
              {error}
            </div>
          )}
        </div>
    </div>
  )
}
