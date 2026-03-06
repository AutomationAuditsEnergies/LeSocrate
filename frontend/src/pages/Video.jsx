import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import ChatPanel from '../components/ChatPanel.jsx'
import LeftSidebar from '../components/LeftSidebar.jsx'
import { apiUrl } from '../api'

export default function Video() {
  const navigate = useNavigate()
  const [chatOpen, setChatOpen] = useState(false)
  const [muted, setMuted] = useState(false)
  const [audioInfo, setAudioInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showPlayPrompt, setShowPlayPrompt] = useState(false)
  const audioRef = useRef(null)

  // Synchroniser la propriété muted directement sur l'élément DOM
  // (React ne met pas à jour muted sur <audio> après le rendu initial)
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
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
      await fetch(apiUrl('/api/auth/logout'), {
        method: 'POST',
        credentials: 'include'
      })
      navigate('/')
    } catch (err) {
      console.error('Erreur déconnexion:', err)
      navigate('/')
    }
  }

  // Fonction pour ouvrir/fermer le chat
  const handleToggleChat = () => {
    setChatOpen(!chatOpen)
  }

  // Gestionnaire de clic pour dé-muter l'audio si autoplay bloqué
  const handlePageClick = () => {
    if (!showPlayPrompt) return
    if (!audioRef.current || audioInfo?.status !== 'playing') return
    const audio = audioRef.current
    audio.muted = false
    setMuted(false)
    if (audio.paused) {
      audio.play().catch((err) => {
        console.error('Impossible de lire l\'audio:', err)
      })
    }
    setShowPlayPrompt(false)
  }

  // Charger les informations audio depuis l'API
  useEffect(() => {
    const fetchAudioStatus = async () => {
      try {
        const response = await fetch(apiUrl('/api/video/status'), {
          credentials: 'include',
        })
        const data = await response.json()

        if (!data.authenticated) {
          navigate('/')
          return
        }

        if (data.status === 'waiting') {
          // Rediriger vers la page d'attente
          navigate('/attente')
          return
        }

        if (data.status === 'finished') {
          setAudioInfo({ status: 'finished' })
          setLoading(false)
          return
        }

        if (data.status === 'playing') {
          setAudioInfo({
            status: 'playing',
            filename: data.audio_filename,
            title: data.audio_title,
            offset: data.offset,
            id: data.audio_id,
            type: data.audio_type,
          })
          setLoading(false)
        }
      } catch (err) {
        console.error('Erreur chargement audio:', err)
        setError('Impossible de charger le cours')
        setLoading(false)
      }
    }

    fetchAudioStatus()
  }, [navigate])

  // Positionner l'audio à l'offset correct quand il est chargé
  useEffect(() => {
    if (audioInfo?.status === 'playing' && audioRef.current) {
      const audio = audioRef.current
      const targetOffset = audioInfo.offset || 0

      console.log(`[Audio] Initialisation — offset: ${targetOffset}s`)

      const handleCanPlay = () => {
        console.log(`[Audio] canplay — currentTime: ${audio.currentTime}s`)
        if (audio.paused) {
          audio.play().catch((err) => {
            if (err.name === 'NotAllowedError') {
              audio.muted = true
              setMuted(true)
              audio.play().then(() => {
                console.log('[Audio] Lancé en muet (autoplay policy)')
                setShowPlayPrompt(true)
              }).catch((e) => {
                console.error('[Audio] Impossible de lire même en muet:', e)
                setShowPlayPrompt(true)
              })
            } else {
              console.error('[Audio] Erreur lecture:', err)
            }
          })
        }
      }

      const handleError = () => {
        console.error('[Audio] Erreur chargement:', audio.error)
      }

      audio.addEventListener('canplay', handleCanPlay)
      audio.addEventListener('error', handleError)

      // Utiliser Media Fragment URI pour démarrer à l'offset
      // Le navigateur gère le positionnement au niveau réseau
      const srcUrl = targetOffset > 0
        ? `${audioInfo.filename}#t=${targetOffset}`
        : audioInfo.filename
      console.log(`[Audio] Source: ${srcUrl}`)
      audio.src = srcUrl
      audio.load()

      return () => {
        audio.removeEventListener('canplay', handleCanPlay)
        audio.removeEventListener('error', handleError)
      }
    }
  }, [audioInfo])

  // Afficher le chargement
  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-900">
        <div className="text-white text-xl">Chargement du cours...</div>
      </div>
    )
  }

  // Afficher une erreur
  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-900">
        <div className="text-red-500 text-xl">{error}</div>
      </div>
    )
  }

  // Cours terminé
  if (audioInfo?.status === 'finished') {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-900">
        <div className="text-white text-2xl">Le cours est terminé</div>
      </div>
    )
  }

  return (
    <>
      <div
        className="h-screen w-full flex"
        style={{ backgroundColor: '#f8fafc' }}
        onClick={handlePageClick}
      >
        {/* Carte principale */}
        <div
          className="flex-1 flex flex-col overflow-hidden"
          style={{ backgroundColor: '#f8fafc' }}
        >

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-8 flex items-center justify-between flex-shrink-0" style={{ height: '64px' }}>
        <div>
          <h1 className="text-xl font-semibold text-gray-800">{import.meta.env.VITE_FORMATION_NAME || 'TP CRCD'}</h1>
          <p className="text-sm text-gray-500">{new Date().toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })}</p>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col items-center justify-center p-8 overflow-hidden">
        <div className="w-full max-w-4xl">
          <div
            id="video-zone"
            className="relative aspect-video w-full rounded-3xl overflow-hidden flex items-center justify-center shadow-2xl border-4 border-pink-200 bg-gradient-to-br from-gray-700 to-gray-900"
            style={{ transform: 'translateY(-20px)' }}
          >
            <div className="flex flex-col items-center justify-center">
              <div className="w-40 h-40 rounded-full bg-white flex items-center justify-center">
                <svg xmlns="http://www.w3.org/2000/svg" className="w-24 h-24 text-gray-800" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
                </svg>
              </div>
              <span className="mt-4 text-white text-xl font-medium">Professeur</span>
            </div>

            <div className="absolute bottom-6 left-6 bg-black/60 text-white text-xs px-3 py-1.5 rounded-lg backdrop-blur-sm">
              Professeur
            </div>

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

            {audioInfo?.status === 'playing' && (
              <audio
                ref={audioRef}
                id="audio"
                controlsList="nodownload noplaybackrate noremoteplayback"
                disablePictureInPicture
                style={{ display: 'none' }}
              />
            )}
          </div>

          {/* Boutons de contrôle */}
          <div className="flex items-center justify-center gap-4 mt-6">
            {/* Bouton micro/son */}
            <button
              onClick={handleToggleMute}
              className="w-14 h-14 rounded-xl bg-white hover:shadow-lg flex items-center justify-center transition-all duration-200 border-2 border-gray-300 hover:border-gray-400 ring-2 ring-purple-100"
              style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08), 0 0 0 4px rgba(0,0,0,0.02)' }}
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
              className="w-16 h-16 rounded-xl bg-purple-600 hover:bg-purple-700 flex items-center justify-center transition-all duration-200 ring-2 ring-purple-200"
              style={{ boxShadow: '0 4px 12px rgba(147, 51, 234, 0.3), 0 0 0 4px rgba(147, 51, 234, 0.1)' }}
              title="Quitter le cours"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-7 h-7 text-white" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 9c-1.6 0-3.15.25-4.6.72v3.1c0 .39-.23.74-.56.9-.98.49-1.87 1.12-2.66 1.85-.18.18-.43.28-.7.28-.28 0-.53-.11-.71-.29L.29 13.08c-.18-.17-.29-.42-.29-.7 0-.28.11-.53.29-.71C3.34 8.78 7.46 7 12 7s8.66 1.78 11.71 4.67c.18.18.29.43.29.71 0 .28-.11.53-.29.71l-2.48 2.48c-.18.18-.43.29-.71.29-.27 0-.52-.11-.7-.28-.79-.74-1.68-1.36-2.66-1.85-.33-.16-.56-.5-.56-.9v-3.1C15.15 9.25 13.6 9 12 9z"/>
              </svg>
            </button>

            {/* Bouton chat */}
            <button
              onClick={handleToggleChat}
              className="w-14 h-14 rounded-xl flex items-center justify-center transition-all duration-200 border-2 bg-white border-gray-300 hover:shadow-lg hover:border-gray-400 ring-2 ring-purple-100"
              style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08), 0 0 0 4px rgba(0,0,0,0.02)' }}
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
