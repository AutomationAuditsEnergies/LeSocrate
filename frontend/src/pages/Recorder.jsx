import { useState, useEffect, useRef, useCallback } from 'react'
import Sidebar from '../components/Sidebar.jsx'
import { apiUrl } from '../api'

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
  const [azureError, setAzureError] = useState('')
  const [playingAudio, setPlayingAudio] = useState(null)
  const [sortMode, setSortMode] = useState('default')
  const audioPlayerRef = useRef(null)

  const AUDIO_EXTENSIONS = ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma', '.webm']

  const cleanAudioFilename = (filename) => {
    const dotIdx = filename.lastIndexOf('.')
    let name = dotIdx > 0 ? filename.substring(0, dotIdx) : filename
    name = name.trim()

    // Cas 1 : extraire le pattern playlist (séparateurs _ ou - tolérés partout)
    const match = name.match(/(cours|qa|pause_midi|pause)[_-](\d{1,2}h\d{2})[_-](\d{1,2}h\d{2})/i)
    if (match) return `${match[1].toLowerCase()}_${match[2].toLowerCase()}_${match[3].toLowerCase()}.mp3`

    // Cas 2 : nettoyage générique
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

    if (data.status === 'converting') {
      setAudioMessage(data.message)
      setAudioMessageType('info')
      setAudioUploading(true)
    } else if (data.status === 'uploading') {
      setAudioMessage(data.message)
      setAudioMessageType('info')
      setAudioUploading(true)
    } else if (data.status === 'saving') {
      setAudioMessage(data.message)
      setAudioMessageType('info')
      setAudioUploading(true)
    } else if (data.status === 'completed') {
      setAudioMessage(data.message)
      setAudioMessageType('success')
      setAudioReport(data.report)
      setAudioUploading(false)
      setAudioFiles([])
      stopPolling()
    } else if (data.status === 'error') {
      setAudioMessage(data.message || "Erreur lors du traitement")
      setAudioMessageType('error')
      if (data.report) setAudioReport(data.report)
      setAudioUploading(false)
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

  // Au chargement : vérifier s'il y a un job en cours
  useEffect(() => {
    const checkExistingJob = async () => {
      try {
        const resp = await fetch(apiUrl('/api/admin/audio-upload-status'), { credentials: 'include' })
        const data = await resp.json()
        if (!data.success) return

        if (['saving', 'converting', 'uploading'].includes(data.status)) {
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
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

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
      setAudioMessage('Aucun fichier audio valide detecte')
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
    setAzureError('')
    try {
      const resp = await fetch(apiUrl('/api/admin/audio-list'), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setAzureAudios(data.audios)
      } else {
        setAzureError(data.error || 'Erreur lors du chargement')
      }
    } catch {
      setAzureError('Erreur de connexion au serveur')
    } finally {
      setAzureLoading(false)
    }
  }

  useEffect(() => {
    fetchAzureAudios()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handlePlay = (audio) => {
    if (playingAudio?.name === audio.name) {
      setPlayingAudio(null)
    } else {
      setPlayingAudio(audio)
    }
  }

  const parseStartMinutes = (name) => {
    const m = name.match(/(\d{1,2})h(\d{2})/)
    if (!m) return 9999
    return parseInt(m[1]) * 60 + parseInt(m[2])
  }

  const getGroup = (name) => {
    if (name.startsWith('cours')) return 0
    if (name.startsWith('pause')) return 1
    if (name.startsWith('qa')) return 2
    return 3
  }

  const sortedAudios = [...azureAudios].sort((a, b) => {
    if (sortMode === 'time') {
      return parseStartMinutes(a.name) - parseStartMinutes(b.name)
    }
    if (sortMode === 'group') {
      const gDiff = getGroup(a.name) - getGroup(b.name)
      if (gDiff !== 0) return gDiff
      return parseStartMinutes(a.name) - parseStartMinutes(b.name)
    }
    return 0 // default : ordre API (déjà trié par nom)
  })

  const formatSize = (bytes) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  const isJobActive = ['saving', 'converting', 'uploading'].includes(jobStatus)

  const progressPercent = jobTotal > 0 ? Math.round((jobProgress / jobTotal) * 100) : 0

  return (
    <div className="min-h-screen bg-gray-900 px-4 py-8 md:px-8">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-center justify-between rounded-2xl border border-gray-700 bg-gray-800/90 px-5 py-5 shadow-lg backdrop-blur-sm">
          <div>
            <h2 className="text-2xl font-semibold text-white">Mise a jour des audios</h2>
            <p className="mt-1 text-sm text-gray-400">Glissez vos fichiers pour remplacer les audios du cours</p>
          </div>
          <a
            href="/admin"
            className="rounded-lg border border-gray-600 bg-gray-700 px-4 py-2 text-sm text-gray-100 transition hover:bg-gray-600"
          >
            Retour admin
          </a>
        </div>

        <Sidebar>
          <div
            onDragOver={(e) => { e.preventDefault(); setAudioDragOver(true) }}
            onDragLeave={() => setAudioDragOver(false)}
            onDrop={handleAudioDrop}
            onClick={() => !isJobActive && document.getElementById('audio-input').click()}
            className={`cursor-pointer rounded-lg border border-dashed p-12 text-center transition ${
              isJobActive ? 'cursor-not-allowed opacity-50 border-gray-600 bg-gray-900/50' :
              audioDragOver ? 'border-gray-500 bg-gray-700/60' : 'border-gray-600 bg-gray-900/50 hover:bg-gray-700/40'
            }`}
          >
            <input
              type="file"
              id="audio-input"
              accept=".mp3,.wav,.ogg,.m4a,.flac,.aac,.wma,.webm"
              multiple
              className="hidden"
              onChange={handleAudioSelect}
              disabled={isJobActive}
            />
            <p className="text-sm font-medium text-gray-200">
              {audioFiles.length > 0
                ? `${audioFiles.length} fichier(s) selectionne(s)`
                : 'Glissez vos fichiers audio ici ou cliquez pour selectionner'}
            </p>
            <p className="mt-1 text-xs text-gray-400">Formats acceptes : mp3, wav, ogg, m4a, flac, aac, wma, webm</p>
          </div>

          {audioFiles.length > 0 && !isJobActive && (
            <div className="mt-4 space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-400">Apercu des fichiers :</p>
              <div className="max-h-64 overflow-y-auto rounded-lg border border-gray-700 bg-gray-900/60 p-3 space-y-1">
                {audioFiles.map((f, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="max-w-[45%] truncate text-gray-400">{f.name}</span>
                    <span className="mx-2 text-gray-500">→</span>
                    <span className="max-w-[45%] truncate text-emerald-300">{cleanAudioFilename(f.name)}</span>
                  </div>
                ))}
              </div>

              <button
                onClick={handleAudioUpload}
                disabled={audioUploading}
                className="mt-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-500"
              >
                {audioUploading ? 'Upload en cours...' : 'Uploader les audios'}
              </button>
            </div>
          )}

          {audioMessage && (
            <div className={`mt-4 rounded-lg border p-3 text-sm ${
              audioMessageType === 'success'
                ? 'border-emerald-400/40 bg-emerald-900/30 text-emerald-200'
                : audioMessageType === 'error'
                  ? 'border-rose-400/40 bg-rose-900/30 text-rose-200'
                  : 'border-blue-400/40 bg-blue-900/30 text-blue-200'
            }`}>
              <p>{audioMessage}</p>
              {isJobActive && (
                <div className="mt-3 space-y-2">
                  <div className="h-2 w-full overflow-hidden rounded-full bg-gray-700">
                    <div
                      className="h-full rounded-full bg-blue-500 transition-all duration-500"
                      style={{ width: `${progressPercent}%` }}
                    />
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-300">
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-500 border-t-gray-100" />
                    <span>
                      {jobStatus === 'saving' && 'Sauvegarde des fichiers...'}
                      {jobStatus === 'converting' && `Conversion ${jobProgress}/${jobTotal}...`}
                      {jobStatus === 'uploading' && `Upload Azure ${jobProgress}/${jobTotal}...`}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}

          {audioReport && (
            <div className="mt-4 rounded-lg border border-gray-700 bg-gray-900/60 p-3">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">Rapport :</p>
              <div className="space-y-1">
                {audioReport.map((r, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    {r.skipped ? (
                      <>
                        <span className="text-rose-400">✗</span>
                        <span className="truncate text-gray-400">{r.original}</span>
                        <span className="text-rose-400">— {r.reason}</span>
                      </>
                    ) : (
                      <>
                        <span className="text-emerald-400">✓</span>
                        <span className="truncate text-gray-400">{r.original}</span>
                        <span className="text-gray-500">→</span>
                        <span className="text-emerald-300">{r.cleaned}</span>
                        {r.converted && <span className="text-blue-300">(converti)</span>}
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Sidebar>

        {/* Playlist Azure */}
        <div className="rounded-2xl border border-gray-700 bg-gray-800/90 shadow-lg">
          <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-gray-700 flex-wrap">
            <div>
              <h3 className="text-lg font-semibold text-white">Playlist Azure</h3>
              <p className="text-xs text-gray-400 mt-0.5">{azureAudios.length} fichier(s) dans le conteneur</p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={() => setSortMode('time')}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition ${sortMode === 'time' ? 'border-blue-500 bg-blue-600 text-white' : 'border-gray-600 bg-gray-700 text-gray-200 hover:bg-gray-600'}`}
                title="Trier par horaire croissant"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="9" y2="18"/>
                </svg>
                Horaire
              </button>
              <button
                onClick={() => setSortMode('group')}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition ${sortMode === 'group' ? 'border-violet-500 bg-violet-600 text-white' : 'border-gray-600 bg-gray-700 text-gray-200 hover:bg-gray-600'}`}
                title="Trier par groupe (cours / pause / qa)"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
                </svg>
                Groupes
              </button>
              <button
                onClick={fetchAzureAudios}
                disabled={azureLoading}
                className="flex items-center gap-2 rounded-lg border border-gray-600 bg-gray-700 px-3 py-1.5 text-sm text-gray-200 transition hover:bg-gray-600 disabled:opacity-50"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className={`w-4 h-4 ${azureLoading ? 'animate-spin' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="23 4 23 10 17 10"></polyline>
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                </svg>
                Actualiser
              </button>
            </div>
          </div>

          {azureError && (
            <div className="px-5 py-3 text-sm text-rose-300 bg-rose-900/20 border-b border-gray-700">
              {azureError}
            </div>
          )}

          {azureLoading && azureAudios.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-500 border-t-gray-200" />
              Chargement...
            </div>
          ) : sortedAudios.length === 0 ? (
            <div className="py-10 text-center text-sm text-gray-500">
              Aucun fichier audio dans le conteneur
            </div>
          ) : (
            <div className="divide-y divide-gray-700/60">
              {sortedAudios.map((audio, i) => (
                <div key={i}>
                {sortMode === 'group' && (i === 0 || getGroup(sortedAudios[i-1].name) !== getGroup(audio.name)) && (
                  <div className="px-5 py-1.5 bg-gray-700/40 text-xs font-semibold uppercase tracking-widest text-gray-400">
                    {audio.name.startsWith('cours') ? 'Cours' : audio.name.startsWith('pause') ? 'Pause' : audio.name.startsWith('qa') ? 'Q&A' : 'Autres'}
                  </div>
                )}
                <div className="px-5 py-3 space-y-2">
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3 min-w-0">
                      <button
                        onClick={() => handlePlay(audio)}
                        className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 hover:bg-blue-700 flex items-center justify-center transition"
                        title={playingAudio?.name === audio.name ? 'Pause' : 'Lire'}
                      >
                        {playingAudio?.name === audio.name ? (
                          <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5 text-white" viewBox="0 0 24 24" fill="currentColor">
                            <rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" />
                          </svg>
                        ) : (
                          <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5 text-white ml-0.5" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M8 5v14l11-7z" />
                          </svg>
                        )}
                      </button>
                      <span className="text-sm text-gray-200 truncate">{audio.name}</span>
                    </div>
                    <span className="flex-shrink-0 text-xs text-gray-500">{formatSize(audio.size)}</span>
                  </div>
                  {playingAudio?.name === audio.name && (
                    <audio
                      ref={audioPlayerRef}
                      src={audio.url}
                      controls
                      autoPlay
                      className="w-full h-8"
                      style={{ colorScheme: 'dark' }}
                      onEnded={() => setPlayingAudio(null)}
                    />
                  )}
                </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
