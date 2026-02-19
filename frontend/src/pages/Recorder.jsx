import { useState, useEffect, useRef, useCallback } from 'react'
import { apiUrl } from '../api'

// Material Icon Component
const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`}>{name}</span>
)

export default function Recorder() {
  const [audioFiles, setAudioFiles] = useState([])
  const [audioDragOver, setAudioDragOver] = useState(false)
  const [audioUploading, setAudioUploading] = useState(false)
  const [audioMessage, setAudioMessage] = useState('')
  const [audioMessageType, setAudioMessageType] = useState('')
  const [audioReport, setAudioReport] = useState(null)
  const [jobStatus, setJobStatus] = useState('idle')
  const [jobProgress, setJobProgress] = useState(0)
  const [jobTotal, setJobTotal] = useState(0)
  const pollingRef = useRef(null)
  const [azureAudios, setAzureAudios] = useState([])
  const [azureLoading, setAzureLoading] = useState(false)
  const [playingAudio, setPlayingAudio] = useState(null)
  const audioPlayerRef = useRef(null)
  const [uploadLocked, setUploadLocked] = useState(false)
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [submittedFiles, setSubmittedFiles] = useState(new Set())
  const [filesStatus, setFilesStatus] = useState({})

  const AUDIO_EXTENSIONS = ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma', '.webm']

  const EXPECTED_AUDIOS = [
    'cours_9h00_9h45.mp3',
    'qa_9h45_9h55.mp3',
    'pause_9h55_10h05.mp3',
    'cours_10h05_10h50.mp3',
    'qa_10h50_11h00.mp3',
    'pause_11h00_11h05.mp3',
    'cours_11h05_12h00.mp3',
    'qa_12h00_12h10.mp3',
    'pause_12h10_12h20.mp3',
    'pause_midi_13h15_14h45.mp3',
    'cours_12h20_13h05.mp3',
    'qa_13h05_13h15.mp3',
    'cours_14h45_15h45.mp3',
    'qa_15h45_16h00.mp3',
    'cours_16h00_17h00.mp3',
    'qa_17h00_17h15.mp3',
    'pause_17h15_17h25.mp3',
    'cours_17h25_18h00.mp3',
    'qa_18h15_18h30.mp3',
  ]

  const cleanAudioFilename = (filename) => {
    const dotIdx = filename.lastIndexOf('.')
    let name = dotIdx > 0 ? filename.substring(0, dotIdx) : filename
    name = name.trim()

    const match = name.match(/(cours|qa|pause_midi|pause)[_-](\d{1,2}h\d{2})[_-](\d{1,2}h\d{2})/i)
    if (match) return `${match[1].toLowerCase()}_${match[2].toLowerCase()}_${match[3].toLowerCase()}.mp3`

    name = name.replace(/\s+/g, '_')
    name = name.replace(/\.{2,}/g, '.')
    name = name.replace(/[^\w.\-]/g, '')
    name = name.replace(/^\.+|\.+$/g, '')
    if (!name) name = 'audio'
    return `${name}.mp3`
  }

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }, [])

  const handleStatusUpdate = useCallback((data) => {
    if (!data.success) return

    setJobStatus(data.status)
    setJobProgress(data.progress)
    setJobTotal(data.total)
    if (data.files_status) setFilesStatus(data.files_status)

    if (data.status === 'saving' || data.status === 'processing') {
      setAudioMessage(data.message)
      setAudioMessageType('info')
      setAudioUploading(true)
    } else if (data.status === 'completed') {
      setAudioMessage(data.message)
      setAudioMessageType('success')
      setAudioReport(data.report)
      setAudioUploading(false)
      setAudioFiles([])
      setSubmittedFiles(new Set())
      setFilesStatus({})
      stopPolling()
      fetchAzureAudios()
    } else if (data.status === 'error') {
      setAudioMessage(data.message || "Erreur lors du traitement")
      setAudioMessageType('error')
      if (data.report) setAudioReport(data.report)
      setAudioUploading(false)
      setSubmittedFiles(new Set())
      setFilesStatus({})
      stopPolling()
    }
  }, [stopPolling])

  const startPolling = useCallback(() => {
    stopPolling()
    pollingRef.current = setInterval(async () => {
      try {
        const resp = await fetch(apiUrl('/api/admin/audio-upload-status'), { credentials: 'include' })
        const data = await resp.json()
        handleStatusUpdate(data)
      } catch {
        // Erreur réseau, on continue le polling
      }
    }, 2000)
  }, [stopPolling, handleStatusUpdate])

  useEffect(() => {
    document.documentElement.style.backgroundColor = '#f8fafc'
    document.body.style.backgroundColor = '#f8fafc'
    return () => {
      document.documentElement.style.backgroundColor = ''
      document.body.style.backgroundColor = ''
    }
  }, [])

  useEffect(() => {
    const checkExistingJob = async () => {
      try {
        const resp = await fetch(apiUrl('/api/admin/audio-upload-status'), { credentials: 'include' })
        const data = await resp.json()
        if (!data.success) return

        if (['saving', 'processing'].includes(data.status)) {
          handleStatusUpdate(data)
          startPolling()
        } else if (data.status === 'completed') {
          handleStatusUpdate(data)
        } else if (data.status === 'error') {
          handleStatusUpdate(data)
        }
      } catch {
        // Pas de connexion, on ignore
      }
    }
    checkExistingJob()
    return () => stopPolling()
  }, [])

  const handleAudioDrop = (e) => {
    e.preventDefault()
    setAudioDragOver(false)
    const droppedFiles = Array.from(e.dataTransfer.files).filter(f => {
      const ext = '.' + f.name.split('.').pop().toLowerCase()
      return AUDIO_EXTENSIONS.includes(ext)
    })
    if (droppedFiles.length > 0) {
      setAudioFiles(droppedFiles)
      setAudioMessage('')
      setAudioReport(null)
    } else {
      setAudioMessage('Aucun fichier audio valide détecté')
      setAudioMessageType('error')
    }
  }

  const handleAudioSelect = (e) => {
    const files = Array.from(e.target.files)
    if (files.length > 0) {
      setAudioFiles(files)
      setAudioMessage('')
      setAudioReport(null)
    }
  }

  const handleAudioUpload = async () => {
    if (audioFiles.length === 0) return

    // Calculer les noms nettoyés pour les tracker pendant l'upload
    const cleanedNames = new Set(audioFiles.map(f => cleanAudioFilename(f.name)))
    setSubmittedFiles(cleanedNames)

    setAudioUploading(true)
    setAudioMessage('Envoi des fichiers...')
    setAudioMessageType('info')
    setAudioReport(null)

    try {
      const formData = new FormData()
      audioFiles.forEach(f => formData.append('files', f))

      const resp = await fetch(apiUrl('/api/admin/upload-audios'), {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })

      const data = await resp.json()

      if (resp.ok && data.success) {
        setAudioMessage(data.message)
        setAudioMessageType('info')
        startPolling()
      } else {
        setAudioMessage(data.error || "Erreur lors de l'upload")
        setAudioMessageType('error')
        if (data.report) setAudioReport(data.report)
        setAudioUploading(false)
      }
    } catch {
      setAudioMessage('Erreur de connexion au serveur')
      setAudioMessageType('error')
      setAudioUploading(false)
    }
  }

  const fetchAzureAudios = async () => {
    setAzureLoading(true)
    try {
      const resp = await fetch(apiUrl('/api/admin/audio-list'), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setAzureAudios(data.audios)
      }
    } catch {
      // Silencieux
    } finally {
      setAzureLoading(false)
    }
  }

  useEffect(() => {
    fetchAzureAudios()
  }, [])

  // Pendant le traitement, rafraîchir la liste toutes les 2s
  // pour activer chaque fichier dès qu'il est uploadé
  useEffect(() => {
    if (jobStatus !== 'processing') return
    const interval = setInterval(() => { fetchAzureAudios() }, 2000)
    return () => clearInterval(interval)
  }, [jobStatus]) // eslint-disable-line

  useEffect(() => {
    const checkPermission = async () => {
      try {
        const resp = await fetch(apiUrl('/api/hr/upload-permission/1'), { credentials: 'include' })
        const data = await resp.json()
        if (data.success && data.upload_locked) setUploadLocked(true)
      } catch { /* silencieux */ }
    }
    checkPermission()
  }, [])

  const handleDeleteAudio = (filename) => {
    setDeleteConfirm(filename)
  }

  const confirmDeleteAudio = async () => {
    if (!deleteConfirm) return
    const filename = deleteConfirm
    setDeleteConfirm(null)
    try {
      const resp = await fetch(apiUrl(`/api/admin/audios/${encodeURIComponent(filename)}`), {
        method: 'DELETE',
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) fetchAzureAudios()
    } catch {
      // Silencieux
    }
  }

  const handlePlay = (audio) => {
    if (playingAudio?.name === audio.name) {
      setPlayingAudio(null)
    } else {
      setPlayingAudio(audio)
    }
  }

  const formatSize = (bytes) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  const parseDuration = (name) => {
    const match = name.match(/(\d{1,2})h(\d{2})[_-](\d{1,2})h(\d{2})/)
    if (!match) return null
    const [_, h1, m1, h2, m2] = match
    const start = parseInt(h1) * 60 + parseInt(m1)
    const end = parseInt(h2) * 60 + parseInt(m2)
    const duration = end - start
    if (duration <= 0) return null
    const hours = Math.floor(duration / 60)
    const mins = duration % 60
    if (hours > 0) return `${hours}h${mins.toString().padStart(2, '0')}`
    return `${mins}min`
  }

  const isJobActive = ['saving', 'processing'].includes(jobStatus)
  const progressPercent = jobTotal > 0 ? Math.round((jobProgress / jobTotal) * 100) : 0

  // Vrai si ce fichier est en cours de traitement (pas encore terminé)
  const isFileProcessing = (name) => {
    if (!isJobActive) return false
    const fs = filesStatus[name]
    if (fs) return fs !== 'done' && fs !== 'error'
    return submittedFiles.has(name) && !uploadedMap[name]
  }
  // Vrai si ce fichier est activement en conversion ou upload (le cercle coloré)
  const isFileActive = (name) => {
    if (!isJobActive) return false
    const fs = filesStatus[name]
    return fs === 'converting' || fs === 'uploading'
  }

  const uploadedMap = Object.fromEntries(azureAudios.map(a => [a.name, a]))
  const mergedAudios = EXPECTED_AUDIOS.map(name => uploadedMap[name]
    ? { ...uploadedMap[name], uploaded: true }
    : { name, uploaded: false }
  )

  const uploadedCount = mergedAudios.filter(a => a.uploaded).length
  const completionPercent = Math.round((uploadedCount / EXPECTED_AUDIOS.length) * 100)

  // Séparer les audios par catégorie
  const coursAudios = mergedAudios.filter(a => a.name.startsWith('cours_'))
  const pauseAudios = mergedAudios.filter(a => a.name.startsWith('pause_'))
  const qaAudios = mergedAudios.filter(a => a.name.startsWith('qa_'))

  return (
    <div className="min-h-screen overflow-x-hidden flex flex-col" style={{ backgroundColor: '#f8fafc', fontFamily: 'Inter, sans-serif' }}>
      {/* Main Content */}
      <main className="flex-1 w-full max-w-[1400px] mx-auto p-6 lg:p-10 flex flex-col gap-8">

        {/* Upload Section */}
        <section className="flex flex-col items-center gap-6">
          {/* Texte descriptif centré */}
          <p className="text-base text-center max-w-2xl" style={{ color: uploadLocked ? '#dc2626' : '#64748b' }}>
            {uploadLocked
              ? 'Actuellement vous ne pouvez ajouter aucun audio. Cette fonctionnalité a été bloquée par nos équipes RH. Veuillez attendre que l\'équipe RH vous permette de remettre des audios.'
              : `Gérez et uploadez vos ${EXPECTED_AUDIOS.length} pistes audio. Assurez-vous que tous les fichiers sont au format .wav ou .mp3.`
            }
          </p>

          {/* Flèche décorative */}
          <img
            src="/arrow.png"
            alt="Flèche décorative"
            className="w-24 h-16 object-contain"
            style={{
              transform: 'rotate(90deg)',
              filter: uploadLocked ? 'hue-rotate(140deg) saturate(1.8)' : 'none',
            }}
          />

          {/* Bouton upload */}
          <button
            onClick={() => !isJobActive && !uploadLocked && setShowUploadModal(true)}
            disabled={isJobActive || uploadLocked}
            className="rounded-xl px-8 py-4 text-base font-bold text-white transition-all duration-200 flex items-center gap-3 shadow-md hover:shadow-lg"
            style={{
              backgroundColor: isJobActive || uploadLocked ? '#94a3b8' : '#137fec',
              cursor: isJobActive || uploadLocked ? 'not-allowed' : 'pointer',
              opacity: isJobActive || uploadLocked ? 0.6 : 1
            }}
          >
            <Icon name="upload" className="text-xl" />
            <span>DÉPOSEZ VOS FICHIERS</span>
          </button>
        </section>

        {/* Progress Bar */}
        <section className="flex flex-col gap-2 w-full px-2">
          <div className="flex justify-between items-baseline">
            <span className="text-xs font-medium" style={{ color: '#94a3b8' }}>
              {uploadedCount} / {EXPECTED_AUDIOS.length} fichiers
            </span>
            <span className="text-xs font-medium" style={{ color: '#94a3b8' }}>
              {completionPercent}%
            </span>
          </div>
          <div className="h-1 w-full rounded-full overflow-hidden" style={{ backgroundColor: '#e2e8f0' }}>
            <div
              className="h-full rounded-full transition-all duration-500 ease-out"
              style={{
                width: `${completionPercent}%`,
                backgroundColor: '#137fec',
                boxShadow: completionPercent > 0 ? '0 0 8px rgba(19, 127, 236, 0.3)' : 'none'
              }}
            ></div>
          </div>
        </section>

        {/* Upload Modal */}
        {showUploadModal && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
            onClick={() => setShowUploadModal(false)}
          >
            <div
              className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Modal Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#e2e8f0', backgroundColor: '#137fec' }}>
                <div className="flex items-center gap-3 text-white">
                  <Icon name="upload" className="text-2xl" />
                  <h3 className="text-lg font-bold">DÉPOSER DES AUDIOS </h3>
                </div>
                <button
                  onClick={() => setShowUploadModal(false)}
                  className="text-white hover:bg-white/20 rounded-full p-1 transition-colors"
                >
                  <Icon name="close" className="text-2xl" />
                </button>
              </div>

              {/* Modal Body */}
              <div className="p-6">
                <div
                  onDragOver={(e) => { e.preventDefault(); if (!isJobActive && !uploadLocked) setAudioDragOver(true) }}
                  onDragLeave={() => setAudioDragOver(false)}
                  onDrop={handleAudioDrop}
                  onClick={() => !isJobActive && !uploadLocked && document.getElementById('audio-input').click()}
                  className="cursor-pointer rounded-xl border-2 border-dashed p-12 text-center transition"
                  style={{
                    backgroundColor: audioDragOver ? 'rgba(19, 127, 236, 0.1)' : 'rgba(19, 127, 236, 0.05)',
                    borderColor: '#137fec',
                    cursor: 'pointer'
                  }}
                >
                  <input
                    type="file"
                    id="audio-input"
                    accept=".mp3,.wav,.ogg,.m4a,.flac,.aac,.wma,.webm"
                    multiple
                    className="hidden"
                    onChange={handleAudioSelect}
                    disabled={isJobActive || uploadLocked}
                  />
                  <div className="flex flex-col items-center gap-4">
                    <div className="flex items-center justify-center size-16 rounded-full" style={{ backgroundColor: 'rgba(19, 127, 236, 0.1)', color: '#137fec' }}>
                      <Icon name="cloud_upload" className="text-3xl" />
                    </div>
                    <div>
                      <h3 className="font-bold text-lg" style={{ color: '#111418' }}>
                        {audioFiles.length > 0 ? `${audioFiles.length} fichier(s) sélectionné(s)` : 'Glissez vos fichiers ici'}
                      </h3>
                      <p className="text-sm mt-2" style={{ color: '#64748b' }}>ou cliquez pour parcourir</p>
                      <p className="text-xs mt-1" style={{ color: '#94a3b8' }}>Formats supportés : WAV, MP3, OGG, M4A, FLAC, AAC, WMA, WEBM</p>
                    </div>
                    {audioFiles.length > 0 && !isJobActive && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleAudioUpload()
                          setShowUploadModal(false)
                        }}
                        disabled={audioUploading}
                        className="rounded-lg px-8 py-3 text-sm font-bold text-white transition-colors mt-2"
                        style={{ backgroundColor: '#137fec' }}
                      >
                        {audioUploading ? 'Upload en cours...' : 'Uploader les fichiers'}
                      </button>
                    )}
                    {isJobActive && (
                      <div className="w-full max-w-md mt-4">
                        <div className="h-2 w-full overflow-hidden rounded-full" style={{ backgroundColor: '#e2e8f0' }}>
                          <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${progressPercent}%`, backgroundColor: '#137fec' }}
                          />
                        </div>
                        <p className="text-xs mt-2" style={{ color: '#64748b' }}>
                          {jobStatus === 'saving' && 'Sauvegarde...'}
                          {jobStatus === 'processing' && `${jobProgress}/${jobTotal} fichier(s) traité(s)`}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Audio Cards - 3 catégories */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Carte COURS */}
          <div className="rounded-2xl bg-white border shadow-sm p-6 flex flex-col" style={{ borderColor: '#e2e8f0' }}>
            <div className="flex items-center gap-3 mb-4 pb-4 border-b" style={{ borderColor: '#e2e8f0' }}>
              <div className="flex items-center justify-center size-12 rounded-xl overflow-hidden border-2" style={{ backgroundColor: '#eff6ff', borderColor: '#000000' }}>
                <img src="/cours.jpg" alt="Cours" className="w-full h-full object-cover" />
              </div>
              <div>
                <h3 className="text-lg font-bold" style={{ color: '#111418' }}>Cours</h3>
                <p className="text-xs" style={{ color: '#64748b' }}>{coursAudios.filter(a => a.uploaded).length}/{coursAudios.length} fichiers</p>
              </div>
            </div>
            <div className="flex-1 space-y-2">
              {coursAudios.map((audio, index) => {
                const duration = parseDuration(audio.name)
                const processing = isFileProcessing(audio.name)
                const activeUpload = isFileActive(audio.name)
                return (
                  <div key={index} className={`rounded-lg p-3 transition-all duration-300 ${audio.uploaded ? 'hover:bg-gray-50' : processing ? 'opacity-70' : 'opacity-40'}`}>
                    <div className="flex items-center gap-2">
                      {audio.uploaded ? (
                        <button
                          onClick={() => handlePlay(audio)}
                          className="flex-shrink-0 flex items-center justify-center size-7 rounded-full transition-colors"
                          style={{ backgroundColor: '#3b82f6', color: 'white' }}
                        >
                          <Icon name={playingAudio?.name === audio.name ? 'pause' : 'play_arrow'} className="text-sm" />
                        </button>
                      ) : activeUpload ? (
                        <div className="flex-shrink-0 size-7 rounded-full animate-spin" style={{ border: '2.5px solid #9ca3af', borderTopColor: 'transparent' }} />
                      ) : processing ? (
                        <div className="flex-shrink-0 flex items-center justify-center size-7 rounded-full" style={{ border: '2px solid #d1d5db', backgroundColor: '#f9fafb' }}>
                          <div className="size-2 rounded-full" style={{ backgroundColor: '#9ca3af' }} />
                        </div>
                      ) : (
                        <div className="flex-shrink-0 flex items-center justify-center size-7 rounded-full" style={{ backgroundColor: '#f1f5f9', color: '#cbd5e1' }}>
                          <Icon name="play_arrow" className="text-sm" />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className={`text-xs truncate ${audio.uploaded || processing ? 'font-medium' : ''}`} style={{ color: audio.uploaded ? '#111418' : processing ? '#3b82f6' : '#94a3b8' }}>
                          {audio.name.replace('cours_', '').replace('.mp3', '')}
                        </p>
                        {audio.uploaded && duration && <p className="text-xs" style={{ color: '#94a3b8' }}>{duration}</p>}
                        {processing && !audio.uploaded && <p className="text-xs" style={{ color: '#93c5fd' }}>{activeUpload ? 'Upload...' : 'En attente...'}</p>}
                      </div>
                      {!uploadLocked && audio.uploaded && (
                        <button
                          onClick={() => handleDeleteAudio(audio.name)}
                          className="flex-shrink-0 p-1 rounded transition-colors"
                          style={{ color: '#cbd5e1' }}
                          onMouseEnter={(e) => { e.currentTarget.style.color = '#ef4444' }}
                          onMouseLeave={(e) => { e.currentTarget.style.color = '#cbd5e1' }}
                        >
                          <Icon name="delete" className="text-sm" />
                        </button>
                      )}
                    </div>
                    {audio.uploaded && playingAudio?.name === audio.name && (
                      <div className="mt-2">
                        <audio ref={audioPlayerRef} src={audio.url} controls autoPlay className="w-full h-7 rounded" style={{ colorScheme: 'light' }} onEnded={() => setPlayingAudio(null)} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Carte PAUSES */}
          <div className="rounded-2xl bg-white border shadow-sm p-6 flex flex-col" style={{ borderColor: '#e2e8f0' }}>
            <div className="flex items-center gap-3 mb-4 pb-4 border-b" style={{ borderColor: '#e2e8f0' }}>
              <div className="flex items-center justify-center size-12 rounded-xl overflow-hidden border-2" style={{ backgroundColor: '#fef3c7', borderColor: '#000000' }}>
                <img src="/break-time.jpg" alt="Break time" className="w-full h-full object-cover" />
              </div>
              <div>
                <h3 className="text-lg font-bold" style={{ color: '#111418' }}>Pauses</h3>
                <p className="text-xs" style={{ color: '#64748b' }}>{pauseAudios.filter(a => a.uploaded).length}/{pauseAudios.length} fichiers</p>
              </div>
            </div>
            <div className="flex-1 space-y-2">
              {pauseAudios.map((audio, index) => {
                const duration = parseDuration(audio.name)
                const processing = isFileProcessing(audio.name)
                const activeUpload = isFileActive(audio.name)
                return (
                  <div key={index} className={`rounded-lg p-3 transition-all duration-300 ${audio.uploaded ? 'hover:bg-gray-50' : processing ? 'opacity-70' : 'opacity-40'}`}>
                    <div className="flex items-center gap-2">
                      {audio.uploaded ? (
                        <button
                          onClick={() => handlePlay(audio)}
                          className="flex-shrink-0 flex items-center justify-center size-7 rounded-full transition-colors"
                          style={{ backgroundColor: '#f59e0b', color: 'white' }}
                        >
                          <Icon name={playingAudio?.name === audio.name ? 'pause' : 'play_arrow'} className="text-sm" />
                        </button>
                      ) : activeUpload ? (
                        <div className="flex-shrink-0 size-7 rounded-full animate-spin" style={{ border: '2.5px solid #9ca3af', borderTopColor: 'transparent' }} />
                      ) : processing ? (
                        <div className="flex-shrink-0 flex items-center justify-center size-7 rounded-full" style={{ border: '2px solid #d1d5db', backgroundColor: '#f9fafb' }}>
                          <div className="size-2 rounded-full" style={{ backgroundColor: '#9ca3af' }} />
                        </div>
                      ) : (
                        <div className="flex-shrink-0 flex items-center justify-center size-7 rounded-full" style={{ backgroundColor: '#f1f5f9', color: '#cbd5e1' }}>
                          <Icon name="play_arrow" className="text-sm" />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className={`text-xs truncate ${audio.uploaded || processing ? 'font-medium' : ''}`} style={{ color: audio.uploaded ? '#111418' : processing ? '#f59e0b' : '#94a3b8' }}>
                          {audio.name.replace('pause_', '').replace('pause_midi_', 'midi ').replace('.mp3', '')}
                        </p>
                        {audio.uploaded && duration && <p className="text-xs" style={{ color: '#94a3b8' }}>{duration}</p>}
                        {processing && !audio.uploaded && <p className="text-xs" style={{ color: '#fcd34d' }}>{activeUpload ? 'Upload...' : 'En attente...'}</p>}
                      </div>
                      {!uploadLocked && audio.uploaded && (
                        <button
                          onClick={() => handleDeleteAudio(audio.name)}
                          className="flex-shrink-0 p-1 rounded transition-colors"
                          style={{ color: '#cbd5e1' }}
                          onMouseEnter={(e) => { e.currentTarget.style.color = '#ef4444' }}
                          onMouseLeave={(e) => { e.currentTarget.style.color = '#cbd5e1' }}
                        >
                          <Icon name="delete" className="text-sm" />
                        </button>
                      )}
                    </div>
                    {audio.uploaded && playingAudio?.name === audio.name && (
                      <div className="mt-2">
                        <audio ref={audioPlayerRef} src={audio.url} controls autoPlay className="w-full h-7 rounded" style={{ colorScheme: 'light' }} onEnded={() => setPlayingAudio(null)} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Carte Q&A */}
          <div className="rounded-2xl bg-white border shadow-sm p-6 flex flex-col" style={{ borderColor: '#e2e8f0' }}>
            <div className="flex items-center gap-3 mb-4 pb-4 border-b" style={{ borderColor: '#e2e8f0' }}>
              <div className="flex items-center justify-center size-12 rounded-xl overflow-hidden border-2" style={{ backgroundColor: '#f0fdf4', borderColor: '#000000' }}>
                <img src="/qa.jpg" alt="Q&A" className="w-full h-full object-cover" />
              </div>
              <div>
                <h3 className="text-lg font-bold" style={{ color: '#111418' }}>Q&A</h3>
                <p className="text-xs" style={{ color: '#64748b' }}>{qaAudios.filter(a => a.uploaded).length}/{qaAudios.length} fichiers</p>
              </div>
            </div>
            <div className="flex-1 space-y-2">
              {qaAudios.map((audio, index) => {
                const duration = parseDuration(audio.name)
                const processing = isFileProcessing(audio.name)
                const activeUpload = isFileActive(audio.name)
                return (
                  <div key={index} className={`rounded-lg p-3 transition-all duration-300 ${audio.uploaded ? 'hover:bg-gray-50' : processing ? 'opacity-70' : 'opacity-40'}`}>
                    <div className="flex items-center gap-2">
                      {audio.uploaded ? (
                        <button
                          onClick={() => handlePlay(audio)}
                          className="flex-shrink-0 flex items-center justify-center size-7 rounded-full transition-colors"
                          style={{ backgroundColor: '#16a34a', color: 'white' }}
                        >
                          <Icon name={playingAudio?.name === audio.name ? 'pause' : 'play_arrow'} className="text-sm" />
                        </button>
                      ) : activeUpload ? (
                        <div className="flex-shrink-0 size-7 rounded-full animate-spin" style={{ border: '2.5px solid #9ca3af', borderTopColor: 'transparent' }} />
                      ) : processing ? (
                        <div className="flex-shrink-0 flex items-center justify-center size-7 rounded-full" style={{ border: '2px solid #d1d5db', backgroundColor: '#f9fafb' }}>
                          <div className="size-2 rounded-full" style={{ backgroundColor: '#9ca3af' }} />
                        </div>
                      ) : (
                        <div className="flex-shrink-0 flex items-center justify-center size-7 rounded-full" style={{ backgroundColor: '#f1f5f9', color: '#cbd5e1' }}>
                          <Icon name="play_arrow" className="text-sm" />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className={`text-xs truncate ${audio.uploaded || processing ? 'font-medium' : ''}`} style={{ color: audio.uploaded ? '#111418' : processing ? '#16a34a' : '#94a3b8' }}>
                          {audio.name.replace('qa_', '').replace('.mp3', '')}
                        </p>
                        {audio.uploaded && duration && <p className="text-xs" style={{ color: '#94a3b8' }}>{duration}</p>}
                        {processing && !audio.uploaded && <p className="text-xs" style={{ color: '#86efac' }}>{activeUpload ? 'Upload...' : 'En attente...'}</p>}
                      </div>
                      {!uploadLocked && audio.uploaded && (
                        <button
                          onClick={() => handleDeleteAudio(audio.name)}
                          className="flex-shrink-0 p-1 rounded transition-colors"
                          style={{ color: '#cbd5e1' }}
                          onMouseEnter={(e) => { e.currentTarget.style.color = '#ef4444' }}
                          onMouseLeave={(e) => { e.currentTarget.style.color = '#cbd5e1' }}
                        >
                          <Icon name="delete" className="text-sm" />
                        </button>
                      )}
                    </div>
                    {audio.uploaded && playingAudio?.name === audio.name && (
                      <div className="mt-2">
                        <audio ref={audioPlayerRef} src={audio.url} controls autoPlay className="w-full h-7 rounded" style={{ colorScheme: 'light' }} onEnded={() => setPlayingAudio(null)} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </section>

      </main>

      {/* Modal confirmation suppression audio */}
      {deleteConfirm && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
          onClick={() => setDeleteConfirm(null)}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl overflow-hidden"
            style={{ width: '100%', maxWidth: '400px' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 text-center">
              <h3 className="text-lg font-bold mb-2" style={{ color: '#0f172a' }}>Supprimer cet audio ?</h3>
              <p className="text-sm mb-6" style={{ color: '#64748b' }}>
                Voulez-vous vraiment supprimer <strong>"{deleteConfirm}"</strong> ? Cette action est irréversible.
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setDeleteConfirm(null)}
                  className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors"
                  style={{ backgroundColor: '#f1f5f9', color: '#475569', border: '1px solid #e2e8f0' }}
                >
                  Annuler
                </button>
                <button
                  onClick={confirmDeleteAudio}
                  className="flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-colors"
                  style={{ backgroundColor: '#dc2626' }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#b91c1c' }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#dc2626' }}
                >
                  Supprimer
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
