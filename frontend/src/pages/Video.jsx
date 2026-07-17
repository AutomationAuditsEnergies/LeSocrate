import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import ChatPanel from '../components/ChatPanel.jsx'
import { apiFetch, apiUrl, getPlatformId, getPlatformName, getStudentLoginPath, setPlatformId } from '../api'
import { SlidePreviewFrame } from '../components/slides/PipelineSlidePreview.jsx'
import {
  audioBasename,
  breakDurationLabel,
  buildAudioSlideTimings,
  findActiveAudioSlideTiming,
} from '../components/slides/audioSlideSync'
import { getStudentAudioProxyPath, isBreakAudioType } from '../studentCoursePlayback.js'

function formatCountdown(seconds) {
  const total = Math.max(0, Math.ceil(Number(seconds) || 0))
  const minutes = Math.floor(total / 60)
  const secs = total % 60
  return `${minutes}:${String(secs).padStart(2, '0')}`
}

function slideTemplateType(slide) {
  return String(slide?.template_type || slide?.type || slide?.template || '').toLowerCase()
}

function CourseStatusScreen({ tone = 'loading', title, message }) {
  const isError = tone === 'error'
  const isDone = tone === 'done'

  return (
    <div
      className="flex h-screen w-full items-center justify-center px-6"
      style={{ backgroundColor: '#F8F7F5', fontFamily: 'Inter, sans-serif' }}
    >
      <div className="w-full max-w-sm rounded-2xl border border-gray-200 bg-white px-7 py-8 text-center shadow-sm">
        <div
          className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-full"
          style={{
            backgroundColor: isError ? '#fee2e2' : isDone ? '#ecfdf5' : '#f3e8ff',
            color: isError ? '#dc2626' : isDone ? '#059669' : '#7c3aed',
          }}
        >
          {tone === 'loading' ? (
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-violet-200 border-t-violet-600" />
          ) : (
            <span className="material-icons text-xl">{isError ? 'warning' : 'check'}</span>
          )}
        </div>
        <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
        {message && <p className="mt-2 text-sm leading-6 text-gray-500">{message}</p>}
      </div>
    </div>
  )
}

export default function Video() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const pParam = searchParams.get('p')
  const [chatOpen, setChatOpen] = useState(false)
  const [muted, setMuted] = useState(false)
  const [audioInfo, setAudioInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showPlayPrompt, setShowPlayPrompt] = useState(false)
  const [breakRemaining, setBreakRemaining] = useState(null)
  const [slideDeck, setSlideDeck] = useState({ slides: [], audioSync: {} })
  const [slideView, setSlideView] = useState('professor')
  const [playbackTime, setPlaybackTime] = useState(0)
  const audioRef = useRef(null)

  // Synchroniser la propriété muted directement sur l'élément DOM
  // (React ne met pas à jour muted sur <audio> après le rendu initial)
  // Lire le platform_id depuis l'URL (?p=2) et le stocker
  useEffect(() => {
    if (pParam) {
      setPlatformId(pParam)
    }
  }, [pParam])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    document.documentElement.style.backgroundColor = '#F8F7F5'
    document.body.style.backgroundColor = '#F8F7F5'
    return () => {
      document.body.style.overflow = ''
      document.documentElement.style.backgroundColor = ''
      document.body.style.backgroundColor = ''
    }
  }, [])

  useEffect(() => {
    let stopped = false
    const signalPresence = async ({ keepalive = false } = {}) => {
      try {
        const response = await apiFetch('/api/auth/heartbeat', {
          method: 'POST',
          keepalive,
          timeoutMs: keepalive ? 0 : 10000,
        })
        const payload = await response.json().catch(() => ({}))
        if (!stopped && response.ok && payload.token) {
          localStorage.setItem('auth_token', payload.token)
        }
      } catch (error) {
        if (!stopped && !keepalive) {
          console.warn('Signal de présence momentanément indisponible', error)
        }
      }
    }

    signalPresence()
    const interval = window.setInterval(signalPresence, 30000)
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') signalPresence()
    }
    const handlePageHide = () => signalPresence({ keepalive: true })
    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('pagehide', handlePageHide)
    return () => {
      stopped = true
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('pagehide', handlePageHide)
    }
  }, [])

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.muted = muted
    }
  }, [muted])

  // Fonction pour basculer le mute
  const handleToggleMute = () => {
    setMuted(!muted)
  }

  // Fonction pour raccrocher (déconnexion)
  const handleHangup = async () => {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' })
      navigate(getStudentLoginPath())
    } catch (err) {
      console.error('Erreur déconnexion:', err)
      navigate(getStudentLoginPath())
    }
  }

  // Fonction pour ouvrir/fermer le chat
  const handleToggleChat = () => {
    setChatOpen(!chatOpen)
  }

  // Gestionnaire de clic pour dé-muter l'audio si autoplay bloqué
  const handlePageClick = () => {
    if (!showPlayPrompt) return
    const audio = audioRef.current
    if (!audio || audioInfo?.status !== 'playing') return
    audio.muted = false
    setMuted(false)
    audio.play().then(() => setShowPlayPrompt(false)).catch((err) => {
      console.error('Impossible de reprendre l\'audio:', err)
    })
  }

  const fetchAudioStatus = useCallback(async ({ silent = false } = {}) => {
    try {
      if (!silent) {
        setLoading(true)
      }
      const response = await apiFetch('/api/video/status')
      const data = await response.json()

      if (!response.ok || !data.authenticated) {
        const platformId = pParam || getPlatformId()
        const loginPath = getStudentLoginPath()
        navigate(loginPath !== '/' ? loginPath : (platformId && platformId !== '1' ? `/?p=${platformId}` : '/'), { replace: true })
        return
      }

      if (data.status === 'waiting') {
        const platformId = pParam || getPlatformId()
        navigate(platformId && platformId !== '1' ? `/attente?p=${platformId}` : '/attente', { replace: true })
        return
      }

      if (data.status === 'finished') {
        setAudioInfo({ status: 'finished' })
        setLoading(false)
        return
      }

      if (data.status === 'playing') {
        setError(null)
        setAudioInfo({
          status: 'playing',
          audioKey: data.audio_key,
          title: data.audio_title,
          offset: data.offset,
          duration: data.audio_duration,
          remaining: data.remaining,
          streamToken: data.audio_stream_token,
          id: data.audio_id,
          type: data.audio_type,
          nextAudio: {
            id: data.next_audio_id,
            title: data.next_audio_title,
            type: data.next_audio_type,
            duration: data.next_audio_duration,
          },
        })
        setPlaybackTime((Number(data.offset) || 0) * 1000)
        if (isBreakAudioType(data.audio_type)) {
          setBreakRemaining(data.remaining ?? Math.max(0, (data.audio_duration || 0) - (data.offset || 0)))
        } else {
          setBreakRemaining(null)
        }
        setLoading(false)
      }
    } catch (err) {
      console.error('Erreur chargement audio:', err)
      setError('Impossible de charger le cours')
      setLoading(false)
    }
  }, [navigate, pParam])

  // Charger les informations audio depuis l'API
  useEffect(() => {
    const timer = window.setTimeout(() => {
      fetchAudioStatus()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [fetchAudioStatus])

  const currentAudioName = audioInfo?.status === 'playing' ? audioBasename(audioInfo.audioKey) : ''
  const isCurrentBreakAudio = audioInfo?.status === 'playing' && isBreakAudioType(audioInfo.type)
  const audioProxyPath = getStudentAudioProxyPath(audioInfo, currentAudioName)
  const audioSrc = audioProxyPath ? apiUrl(audioProxyPath) : ''

  useEffect(() => {
    let cancelled = false
    const resetTimer = window.setTimeout(() => {
      if (cancelled) return
      setSlideView('professor')
      setSlideDeck({ slides: [], audioSync: {} })
    }, 0)

    if (audioInfo?.status !== 'playing' || isCurrentBreakAudio || !currentAudioName) {
      return () => {
        cancelled = true
        window.clearTimeout(resetTimer)
      }
    }

    apiFetch('/api/video/slides')
      .then(async (response) => {
        const data = await response.json().catch(() => ({}))
        if (!response.ok || (data.status !== 'success' && data.status !== 'no_data')) {
          throw new Error(data.message || data.error || 'Slides indisponibles')
        }
        if (cancelled) return
        if (data.status === 'success') {
          setSlideDeck({
            slides: Array.isArray(data.slides) ? data.slides : [],
            audioSync: data.audio_sync || {},
          })
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('Erreur chargement slides synchronisées:', err)
        }
      })

    return () => {
      cancelled = true
      window.clearTimeout(resetTimer)
    }
  }, [audioInfo?.status, currentAudioName, isCurrentBreakAudio])

  const slideTimings = buildAudioSlideTimings(slideDeck.slides, slideDeck.audioSync, currentAudioName)
  const activeSlideTiming = findActiveAudioSlideTiming(slideTimings, playbackTime)
  const hasProjectedSlides = slideTimings.length > 0 && Boolean(activeSlideTiming)
  const showProjectedSlides = slideView === 'slides' && hasProjectedSlides && !isCurrentBreakAudio
  const hasCompletedSyncedSpeech = (
    audioInfo?.status === 'playing'
    && !isCurrentBreakAudio
    && slideTimings.length > 0
    && !activeSlideTiming
  )
  const nextBreakType = isBreakAudioType(audioInfo?.nextAudio?.type) ? audioInfo.nextAudio.type : null
  const secondsRemainingInAudio = Math.max(0, Number(audioInfo?.remaining ?? 0))
  const activeSlideType = slideTemplateType(activeSlideTiming?.slide)
  const isLateMisplacedReprise = (
    slideView === 'slides'
    && Boolean(nextBreakType)
    && secondsRemainingInAudio <= 180
    && ['reprise', 'reprise_recap', 'opening_recap', 'rappel'].includes(activeSlideType)
  )
  const showNextBreakPreview = (
    slideView === 'slides'
    && Boolean(nextBreakType)
    && (hasCompletedSyncedSpeech || isLateMisplacedReprise)
  )

  // Positionner l'audio à l'offset correct quand il est chargé
  useEffect(() => {
    if (audioInfo?.status === 'playing' && !isBreakAudioType(audioInfo.type) && audioRef.current) {
      const audio = audioRef.current
      const targetOffset = Math.max(0, Number(audioInfo.offset) || 0)
      let hasAttemptedPlay = false
      let endedTimer = null
      setPlaybackTime(targetOffset * 1000)

      const syncPlaybackTime = () => {
        setPlaybackTime((Number(audio.currentTime) || 0) * 1000)
      }
      const handleLoadedMetadata = () => {
        if (targetOffset > 0) {
          const maxOffset = Number.isFinite(audio.duration)
            ? Math.max(0, audio.duration - 0.05)
            : targetOffset
          audio.currentTime = Math.min(targetOffset, maxOffset)
        }
        syncPlaybackTime()
      }
      const handleCanPlay = () => {
        if (hasAttemptedPlay || !audio.paused) return
        hasAttemptedPlay = true
        audio.play().then(() => setShowPlayPrompt(false)).catch((err) => {
          if (err.name === 'NotAllowedError') {
            audio.muted = true
            setMuted(true)
            audio.play().then(() => setShowPlayPrompt(true)).catch(() => {
              setShowPlayPrompt(true)
            })
          }
        })
      }
      const handleEnded = () => {
        setShowPlayPrompt(false)
        endedTimer = window.setTimeout(() => fetchAudioStatus({ silent: true }), 500)
      }
      const handleError = () => {
        console.error('[Audio] Erreur chargement du proxy:', audio.error)
      }

      audio.addEventListener('loadedmetadata', handleLoadedMetadata)
      audio.addEventListener('seeked', syncPlaybackTime)
      audio.addEventListener('timeupdate', syncPlaybackTime)
      audio.addEventListener('playing', syncPlaybackTime)
      audio.addEventListener('canplay', handleCanPlay)
      audio.addEventListener('ended', handleEnded)
      audio.addEventListener('error', handleError)
      audio.load()

      return () => {
        audio.pause()
        audio.removeEventListener('loadedmetadata', handleLoadedMetadata)
        audio.removeEventListener('seeked', syncPlaybackTime)
        audio.removeEventListener('timeupdate', syncPlaybackTime)
        audio.removeEventListener('playing', syncPlaybackTime)
        audio.removeEventListener('canplay', handleCanPlay)
        audio.removeEventListener('ended', handleEnded)
        audio.removeEventListener('error', handleError)
        if (endedTimer) window.clearTimeout(endedTimer)
      }
    }

    if (audioInfo?.status === 'playing' && isBreakAudioType(audioInfo.type)) {
      // A break is silence, so no blob needs to be exposed or downloaded. Its
      // countdown starts from the occurrence-bound server state and is
      // re-synchronised by fetchAudioStatus at the boundary.
      const initialRemaining = Math.max(0, Number(audioInfo.remaining) || 0)
      const initialOffset = Math.max(0, Number(audioInfo.offset) || 0)
      const startedAt = Date.now()
      let refreshed = false

      const tick = () => {
        const elapsed = Math.max(0, (Date.now() - startedAt) / 1000)
        const remaining = Math.max(0, initialRemaining - elapsed)
        setBreakRemaining(Math.ceil(remaining))
        setPlaybackTime((initialOffset + elapsed) * 1000)
        if (remaining <= 0 && !refreshed) {
          refreshed = true
          fetchAudioStatus({ silent: true })
        }
      }

      tick()
      const countdownTimer = window.setInterval(tick, 500)
      return () => window.clearInterval(countdownTimer)
    }
  }, [
    audioInfo?.status,
    audioInfo?.audioKey,
    audioInfo?.id,
    audioInfo?.type,
    audioInfo?.duration,
    audioInfo?.offset,
    audioInfo?.remaining,
    currentAudioName,
    audioSrc,
    fetchAudioStatus,
  ])

  // Afficher le chargement
  if (loading) {
    return (
      <CourseStatusScreen
        title="Chargement du cours..."
        message="Préparation de la session en cours."
      />
    )
  }

  // Afficher une erreur
  if (error) {
    return (
      <CourseStatusScreen
        tone="error"
        title={error}
        message="Réessayez dans quelques instants ou revenez à l'accueil."
      />
    )
  }

  // Cours terminé
  if (audioInfo?.status === 'finished') {
    return (
      <CourseStatusScreen
        tone="done"
        title="Le cours est terminé"
        message="Merci pour votre participation."
      />
    )
  }

  const isBreakScreen = audioInfo?.status === 'playing' && isBreakAudioType(audioInfo.type)
  const breakDuration = Math.max(1, Number(audioInfo?.duration || 0))
  const breakSecondsRemaining = Math.max(
    0,
    Number(breakRemaining ?? audioInfo?.remaining ?? 0)
  )
  const breakProgress = Math.min(
    100,
    Math.max(0, ((breakDuration - breakSecondsRemaining) / breakDuration) * 100)
  )

  return (
    <>
      <div
        className="flex h-dvh w-full overflow-hidden"
        style={{ backgroundColor: '#F8F7F5' }}
        onClick={handlePageClick}
      >
        {/* Carte principale */}
        <div
          className="flex-1 flex flex-col overflow-hidden"
          style={{ backgroundColor: '#F8F7F5' }}
        >

      {/* Header */}
      <div className="flex h-[72px] flex-shrink-0 items-center justify-between border-b border-gray-200 bg-white px-5 sm:h-16 sm:px-8">
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold text-gray-800 sm:text-xl">{getPlatformName()}</h1>
          <p className="text-sm text-gray-500">{new Date().toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })}</p>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto px-4 pb-28 pt-5 sm:flex sm:flex-col sm:items-center sm:justify-center sm:overflow-hidden sm:p-8">
        <div className="mx-auto w-full max-w-4xl">
          <div
            id="video-zone"
            className="relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-2xl border-2 bg-gradient-to-br from-gray-700 to-gray-900 shadow-lg sm:rounded-3xl sm:border-4 sm:shadow-2xl"
            style={{ borderColor: '#E4E4E4' }}
          >
            {isBreakScreen ? (
              <div className="absolute inset-0" style={{ backgroundColor: '#020617' }}>
                <SlidePreviewFrame
                  slide={{
                    template_type: audioInfo.type === 'qa' ? 'qa' : 'pause',
                    data: { duration_label: breakDurationLabel(audioInfo.duration) },
                  }}
                  maxWidth={896}
                  padding={0}
                  className="h-full w-full"
                  style={{ width: '100%', height: '100%', background: '#020617' }}
                />
                <div
                  className="absolute inset-x-0 bottom-0 flex items-center gap-4 px-6 pb-4 pt-10"
                  style={{ background: 'linear-gradient(to top, rgba(2, 6, 23, 0.85), rgba(2, 6, 23, 0))' }}
                >
                  <span className="text-sm font-medium" style={{ color: '#D8C7FF' }}>
                    Reprise dans
                  </span>
                  <span className="text-3xl font-semibold tabular-nums text-white">
                    {formatCountdown(breakSecondsRemaining)}
                  </span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full" style={{ backgroundColor: 'rgba(248, 247, 245, 0.25)' }}>
                    <div
                      className="h-full rounded-full transition-[width] duration-500 ease-out"
                      style={{ width: `${breakProgress}%`, backgroundColor: '#BFA7FF' }}
                    />
                  </div>
                </div>
              </div>
            ) : showNextBreakPreview ? (
              <div className="absolute inset-0" style={{ backgroundColor: '#020617' }}>
                <SlidePreviewFrame
                  slide={{
                    template_type: nextBreakType === 'qa' ? 'qa' : 'pause',
                    data: { duration_label: breakDurationLabel(audioInfo.nextAudio.duration) },
                  }}
                  maxWidth={896}
                  padding={0}
                  className="h-full w-full"
                  style={{ width: '100%', height: '100%', background: '#020617' }}
                />
              </div>
            ) : showProjectedSlides ? (
              <div className="absolute inset-0 flex items-center justify-center bg-[#020617]">
                <SlidePreviewFrame
                  slide={activeSlideTiming.slide}
                  maxWidth={896}
                  padding={0}
                  className="h-full w-full"
                  style={{ width: '100%', height: '100%', background: '#020617' }}
                />
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center">
                <div className="w-40 h-40 rounded-full bg-white flex items-center justify-center">
                  <svg xmlns="http://www.w3.org/2000/svg" className="w-24 h-24 text-gray-800" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
                  </svg>
                </div>
                <span className="mt-4 text-white text-xl font-medium">Professeur</span>
              </div>
            )}

            {!isBreakScreen && (
              <div className="absolute bottom-3 left-3 rounded-lg bg-black/60 px-3 py-1.5 text-xs text-white backdrop-blur-sm sm:bottom-6 sm:left-6">
                {showNextBreakPreview
                  ? (nextBreakType === 'qa' ? 'Questions-réponses' : 'Pause')
                  : showProjectedSlides ? `Slide ${activeSlideTiming.slideIndex + 1}` : 'Professeur'}
              </div>
            )}

            {audioInfo?.status === 'playing' && !isBreakScreen && (hasProjectedSlides || hasCompletedSyncedSpeech) && (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation()
                  setSlideView((showProjectedSlides || showNextBreakPreview) ? 'professor' : 'slides')
                }}
                className="absolute right-3 top-3 rounded-lg bg-white/95 px-3 py-2 text-xs font-semibold text-gray-900 shadow-md transition hover:bg-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 focus:ring-offset-gray-900 sm:right-5 sm:top-5 sm:rounded-xl sm:px-4 sm:text-sm sm:shadow-lg"
              >
                {(showProjectedSlides || showNextBreakPreview) ? 'Professeur' : 'Visualiser les slides'}
              </button>
            )}

            {showPlayPrompt && (
              <button
                onClick={handlePageClick}
                className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/40 backdrop-blur-sm transition-all duration-200 hover:bg-black/50"
              >
                <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-lg">
                  <svg xmlns="http://www.w3.org/2000/svg" className="w-6 h-6 text-purple-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                    <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path>
                  </svg>
                </span>
                <span className="text-white text-sm font-medium">Activer le son</span>
              </button>
            )}

            {audioInfo?.status === 'playing' && !isBreakAudioType(audioInfo.type) && audioSrc && (
              <audio
                ref={audioRef}
                id="audio"
                src={audioSrc}
                preload="auto"
                controlsList="nodownload noplaybackrate noremoteplayback"
                disablePictureInPicture
                style={{ display: 'none' }}
              />
            )}

          </div>

          {/* Boutons de contrôle */}
          <div className="fixed inset-x-0 bottom-[max(1rem,env(safe-area-inset-bottom))] z-20 flex items-center justify-center gap-4 px-4 sm:static sm:mt-6 sm:px-0">
            {/* Bouton micro/son */}
            <button
              onClick={handleToggleMute}
              className="flex h-14 w-14 items-center justify-center rounded-xl border-2 bg-white transition-all duration-200 hover:border-gray-400 hover:shadow-lg"
              style={{ borderColor: '#E4E4E4', boxShadow: '0 2px 8px rgba(0,0,0,0.08), 0 0 0 4px #E4E4E4' }}
              title={muted ? "Activer le son" : "Couper le son"}
            >
              {muted ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-purple-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                  <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"></path>
                  <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"></path>
                  <line x1="12" y1="19" x2="12" y2="23"></line>
                  <line x1="8" y1="23" x2="16" y2="23"></line>
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-gray-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                  <line x1="12" y1="19" x2="12" y2="23"></line>
                  <line x1="8" y1="23" x2="16" y2="23"></line>
                </svg>
              )}
            </button>

            {/* Bouton raccrocher */}
            <button
              onClick={handleHangup}
              className="flex h-16 w-16 items-center justify-center rounded-xl bg-purple-600 transition-all duration-200 hover:bg-purple-700"
              style={{ boxShadow: '0 4px 12px rgba(147, 51, 234, 0.3), 0 0 0 4px #E4E4E4' }}
              title="Quitter le cours"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-7 h-7 text-white" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 9c-1.6 0-3.15.25-4.6.72v3.1c0 .39-.23.74-.56.9-.98.49-1.87 1.12-2.66 1.85-.18.18-.43.28-.7.28-.28 0-.53-.11-.71-.29L.29 13.08c-.18-.17-.29-.42-.29-.7 0-.28.11-.53.29-.71C3.34 8.78 7.46 7 12 7s8.66 1.78 11.71 4.67c.18.18.29.43.29.71 0 .28-.11.53-.29.71l-2.48 2.48c-.18.18-.43.29-.71.29-.27 0-.52-.11-.7-.28-.79-.74-1.68-1.36-2.66-1.85-.33-.16-.56-.5-.56-.9v-3.1C15.15 9.25 13.6 9 12 9z"/>
              </svg>
            </button>

            {/* Bouton chat */}
            <button
              onClick={handleToggleChat}
              className="flex h-14 w-14 items-center justify-center rounded-xl border-2 bg-white transition-all duration-200 hover:border-gray-400 hover:shadow-lg"
              style={{ borderColor: '#E4E4E4', boxShadow: '0 2px 8px rgba(0,0,0,0.08), 0 0 0 4px #E4E4E4' }}
              title={chatOpen ? "Fermer le chat" : "Ouvrir le chat"}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className={`w-5 h-5 ${chatOpen ? 'text-purple-600' : 'text-gray-700'}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
              </svg>
            </button>
          </div>

        </div>
      </div>

      </div>

      <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
      </div>
    </>
  )
}
