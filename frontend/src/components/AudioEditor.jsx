import { useState, useEffect, useRef, useCallback } from 'react'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.js'
import { apiUrl } from '../api'

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
  const [analyzing, setAnalyzing] = useState(false)
  const [bugRegions, setBugRegions] = useState([])    // [{start, end, severity}] en secondes
  const bugRegionRefsRef = useRef([])                 // instances WaveSurfer Region pour cleanup

  const sasUrlRef = useRef(null)   // SAS URL courante (mise à jour après cut/replace)

  // Récupère une SAS URL fraîche depuis le backend
  const fetchSasUrl = useCallback(async () => {
    const resp = await fetch(
      apiUrl(`/api/hr/cours-folders/${folderId}/audio-url/${filename}`),
      { credentials: 'include' }
    )
    const data = await resp.json()
    if (!data.success) throw new Error(data.error || 'SAS URL indisponible')
    sasUrlRef.current = data.url
    return data.url
  }, [folderId, filename])

  // ── Init WaveSurfer ──
  useEffect(() => {
    if (!waveRef.current) return

    const regions = RegionsPlugin.create()
    regionsRef.current = regions

    const ws = WaveSurfer.create({
      container: waveRef.current,
      waveColor: darkMode ? '#6d28d9' : '#a78bfa',
      progressColor: darkMode ? '#c4b5fd' : '#7c3aed',
      cursorColor: '#f59e0b',
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      height: 80,
      normalize: true,
      minPxPerSec: 0, // auto-fit au chargement
      autoScroll: true,
      fillParent: true,
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

    // Charger via SAS URL (stream direct Azure, pas de proxy)
    fetchSasUrl()
      .then(url => ws.load(url))
      .catch(e => setError('Impossible de charger l\'audio : ' + e.message))

    ws.on('ready', () => {
      setDuration(ws.getDuration() * 1000)
      setLoading(false)
    })
    ws.on('timeupdate', (t) => setCurrentTime(t * 1000))
    ws.on('play', () => setPlaying(true))
    ws.on('pause', () => setPlaying(false))
    ws.on('finish', () => setPlaying(false))

    // Permettre la création de régions par drag
    regions.enableDragSelection({ color: 'rgba(124, 58, 237, 0.25)' })

    regions.on('region-created', (r) => {
      // Supprimer seulement la région utilisateur précédente (pas les régions bugs)
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
      waveEl?.removeEventListener('wheel', handleWheel)
      ws.destroy()
      stopStitchedPlayback()
      bugRegionRefsRef.current = []
    }
  }, [darkMode, fetchSasUrl])

  // Changer la couleur de la région selon le mode
  useEffect(() => {
    activeRegionRef.current?.setOptions({
      color: mode === 'cut'
        ? 'rgba(239, 68, 68, 0.25)'
        : 'rgba(124, 58, 237, 0.25)',
    })
  }, [mode])

  const togglePlay = () => {
    wsRef.current?.playPause()
  }

  const clearRegion = () => {
    // Ne supprimer que la région utilisateur, pas les régions bugs
    if (activeRegionRef.current) {
      activeRegionRef.current.remove()
      activeRegionRef.current = null
    }
    setRegion(null)
    setPreviewId(null)
    setPreviewAudio(null)
  }

  const clearBugRegions = () => {
    bugRegionRefsRef.current.forEach(r => { try { r.remove() } catch (e) {} })
    bugRegionRefsRef.current = []
    setBugRegions([])
  }

  const handleDetectBugs = async () => {
    setAnalyzing(true)
    setError(null)
    clearBugRegions()
    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${folderId}/audio/${filename}/detect-bugs`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ seuil: 3.0, duree_min: 0.3 }),
          credentials: 'include',
        }
      )
      const data = await resp.json()
      if (!data.success) {
        setError(data.error || 'Erreur lors de l\'analyse')
        return
      }
      setBugRegions(data.bugs)
      // Ajouter les régions colorées sur la waveform
      const refs = []
      data.bugs.forEach(bug => {
        const color = bug.severity >= 3
          ? 'rgba(239, 68, 68, 0.30)'    // rouge vif → bug sévère
          : bug.severity === 2
          ? 'rgba(251, 146, 60, 0.30)'   // orange → bug modéré
          : 'rgba(250, 204, 21, 0.25)'   // jaune → anomalie légère
        const r = regionsRef.current?.addRegion({
          start: bug.start,
          end: bug.end,
          color,
          drag: false,
          resize: false,
        })
        if (r) refs.push(r)
      })
      bugRegionRefsRef.current = refs
      if (data.bugs.length === 0) {
        setStatus('✅ Aucune anomalie détectée dans cet audio.')
        setTimeout(() => setStatus(null), 4000)
      }
    } catch (e) {
      setError('Erreur réseau lors de l\'analyse')
    } finally {
      setAnalyzing(false)
    }
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
        apiUrl(`/api/hr/cours-folders/${folderId}/audio/${filename}/cut`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
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
            const freshUrl = await fetchSasUrl()
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
        apiUrl(`/api/hr/cours-folders/${folderId}/audio/${filename}/replace-preview`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
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
        apiUrl(`/api/hr/cours-folders/${folderId}/audio/${filename}/replace-confirm`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
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
            const freshUrl = await fetchSasUrl()
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

  const bg = darkMode ? '#0f0a1f' : '#faf5ff'
  const border = darkMode ? '#2d1b69' : '#ede9fe'
  const textPrimary = darkMode ? '#e9d5ff' : '#1e1b4b'
  const textMuted = darkMode ? '#7c3aed' : '#9333ea'
  const headerBg = '#6d28d9'

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0,0,0,0.8)' }}
      onClick={onClose}
    >
      <div
        className="w-full rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        style={{ maxWidth: '820px', maxHeight: '90vh', backgroundColor: bg }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-3 flex-shrink-0"
          style={{ backgroundColor: headerBg }}
        >
          <div className="flex items-center gap-3 text-white">
            <Icon name="cut" style={{ fontSize: '20px' }} />
            <div>
              <p className="text-sm font-bold">{filename}</p>
              <p className="text-xs" style={{ color: '#ddd6fe' }}>
                Éditeur audio · {formatTime(duration)}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-white hover:bg-white/20 rounded-full p-1">
            <Icon name="close" style={{ fontSize: '22px' }} />
          </button>
        </div>

        {/* Corps */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">

          {/* Waveform */}
          <div
            className="rounded-xl p-3 relative"
            style={{ backgroundColor: darkMode ? '#1a0a3a' : '#f3e8ff', border: `1px solid ${border}` }}
          >
            {loading && (
              <div className="absolute inset-0 flex items-center justify-center rounded-xl" style={{ backgroundColor: darkMode ? '#1a0a3a' : '#f3e8ff' }}>
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

          {/* Contrôles lecture */}
          <div className="flex items-center gap-3">
            <button
              onClick={togglePlay}
              disabled={loading}
              className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              style={{ backgroundColor: '#7c3aed' }}
            >
              <Icon name={playing ? 'pause' : 'play_arrow'} style={{ fontSize: '18px' }} />
              {playing ? 'Pause' : 'Écouter'}
            </button>

            {region && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium" style={{ backgroundColor: darkMode ? '#2d1b69' : '#ede9fe', color: '#7c3aed' }}>
                <Icon name="crop_free" style={{ fontSize: '14px' }} />
                Sélection : {formatTime(region.start)} → {formatTime(region.end)}
                <span style={{ color: textMuted }}>({formatTime(region.end - region.start)})</span>
                <button onClick={clearRegion} className="ml-1 hover:opacity-70">
                  <Icon name="close" style={{ fontSize: '14px' }} />
                </button>
              </div>
            )}

            {!region && !loading && (
              <p className="text-xs" style={{ color: textMuted }}>
                Faites glisser sur la forme d'onde pour sélectionner une région
              </p>
            )}
          </div>

          {/* Détection bugs */}
          <div className="flex items-center gap-3 flex-wrap">
            <button
              onClick={handleDetectBugs}
              disabled={loading || analyzing}
              className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50 transition-all"
              style={{ backgroundColor: analyzing ? '#78350f' : '#92400e', color: '#fef3c7', border: '1px solid #d97706' }}
            >
              <Icon name={analyzing ? 'hourglass_empty' : 'troubleshoot'} style={{ fontSize: '16px' }} />
              {analyzing ? 'Analyse en cours...' : 'Détecter les bugs vocaux'}
            </button>

            {bugRegions.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium px-3 py-1.5 rounded-lg" style={{ backgroundColor: 'rgba(239,68,68,0.15)', color: '#f87171' }}>
                  {bugRegions.length} anomalie{bugRegions.length > 1 ? 's' : ''} détectée{bugRegions.length > 1 ? 's' : ''}
                  {' '}·{' '}
                  <span style={{ color: '#ef4444' }}>■</span> sévère{' '}
                  <span style={{ color: '#fb923c' }}>■</span> modéré{' '}
                  <span style={{ color: '#facc15' }}>■</span> léger
                </span>
                <button
                  onClick={clearBugRegions}
                  className="text-xs px-2 py-1 rounded-lg hover:opacity-70"
                  style={{ color: textMuted }}
                >
                  <Icon name="close" style={{ fontSize: '13px' }} /> Effacer
                </button>
              </div>
            )}
          </div>

          {/* Mode toggle */}
          <div className="flex gap-2">
            {['cut', 'replace'].map(m => (
              <button
                key={m}
                onClick={() => { setMode(m); setError(null) }}
                className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-all"
                style={{
                  backgroundColor: mode === m ? '#7c3aed' : (darkMode ? '#1a0a3a' : '#f3e8ff'),
                  color: mode === m ? 'white' : textMuted,
                  border: `1px solid ${mode === m ? '#7c3aed' : border}`,
                }}
              >
                <Icon name={m === 'cut' ? 'content_cut' : 'edit'} style={{ fontSize: '16px' }} />
                {m === 'cut' ? 'Couper' : 'Remplacer'}
              </button>
            ))}
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
                  backgroundColor: darkMode ? '#0f0a1f' : '#fff',
                  color: textPrimary,
                  border: `1px solid ${border}`,
                }}
              />
              <div className="flex gap-2 flex-wrap">
                <button
                  onClick={handlePreviewTTS}
                  disabled={!replaceText.trim() || generating}
                  className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50"
                  style={{ backgroundColor: darkMode ? '#2d1b69' : '#ede9fe', color: '#7c3aed' }}
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
                      style={{ backgroundColor: '#7c3aed' }}
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
    </div>
  )
}
