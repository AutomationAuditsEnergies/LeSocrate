import { useState, useEffect, useRef, useCallback } from 'react'
import { apiUrl } from '../api'
import CoursFoldersModal from '../components/CoursFolders'

// ─── Material Icon Component ─────────────────────────────────────────────────
const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`}>{name}</span>
)

// ─── Component ───────────────────────────────────────────────────────────────
export default function HRDashboard() {
  const [platforms, setPlatforms] = useState([])
  const [loading, setLoading] = useState(true)
  const [expandedPlatform, setExpandedPlatform] = useState(null)
  const [platformAudios, setPlatformAudios] = useState({})
  const [playingAudio, setPlayingAudio] = useState(null)
  const [pdfUploading, setPdfUploading] = useState(null)
  const [audiosLoading, setAudiosLoading] = useState(null)
  const [backupJobs, setBackupJobs] = useState({})
  const [darkMode, setDarkMode] = useState(false)
  const [showAudiosModal, setShowAudiosModal] = useState(false)
  const [selectedPlatformId, setSelectedPlatformId] = useState(null)
  const [showPdfModal, setShowPdfModal] = useState(false)
  const [selectedPlatform, setSelectedPlatform] = useState(null)
  const [showCourseTimeModal, setShowCourseTimeModal] = useState(false)
  const [currentCourseTime, setCurrentCourseTime] = useState(null)
  const [courseTimePlatformId, setCourseTimePlatformId] = useState(1)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [deletingItem, setDeletingItem] = useState(false)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newPlatformName, setNewPlatformName] = useState('')
  const [creating, setCreating] = useState(false)
  const backupPollingRef = useRef({})
  const audioRef = useRef(null)
  const [showCoursFoldersModal, setShowCoursFoldersModal] = useState(false)
  const [selectedCoursPlatform, setSelectedCoursPlatform] = useState(null)
  const [cardPage, setCardPage] = useState(0)
  const CARDS_PER_PAGE = 3

  // ─── Fetch data ──────────────────────────────────────────────────────
  const fetchPlatforms = async (refreshSelectedId = null) => {
    try {
      const resp = await fetch(apiUrl('/api/hr/platforms'), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setPlatforms(data.platforms)
        if (refreshSelectedId !== null) {
          const updated = data.platforms.find(p => p.id === refreshSelectedId)
          if (updated) setSelectedPlatform(updated)
        }
      }
    } catch (e) {
      console.error('Erreur chargement plateformes:', e)
    } finally {
      setLoading(false)
    }
  }

  const fetchAudios = async (platformId) => {
    setAudiosLoading(platformId)
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/audios`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setPlatformAudios(prev => ({ ...prev, [platformId]: data.audios }))
      }
    } catch (e) {
      console.error('Erreur chargement audios:', e)
    } finally {
      setAudiosLoading(null)
    }
  }

  useEffect(() => {
    fetchPlatforms()
  }, [])

  useEffect(() => {
    const bg = darkMode ? '#0f172a' : '#f8fafc'
    document.documentElement.style.backgroundColor = bg
    document.body.style.backgroundColor = bg
    return () => {
      document.documentElement.style.backgroundColor = ''
      document.body.style.backgroundColor = ''
    }
  }, [darkMode])

  // ─── Actions ─────────────────────────────────────────────────────────
  const handleLock = async (platformId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/toggle-lock`), {
        method: 'POST', credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) fetchPlatforms()
    } catch (e) {
      console.error('Erreur lock:', e)
    }
  }

  const handleBackupAndUnlock = async (platformId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/backup-and-unlock`), {
        method: 'POST', credentials: 'include',
      })
      const data = await resp.json()
      if (!data.success) {
        setBackupJobs(prev => ({ ...prev, [platformId]: { step_status: 'error', error: data.error } }))
        return
      }
      setBackupJobs(prev => ({ ...prev, [platformId]: { step: 1, step_status: 'running', progress: 0, total: 0 } }))
      startBackupPolling(platformId)
    } catch (e) {
      console.error('Erreur backup-and-unlock:', e)
    }
  }

  const startBackupPolling = (platformId) => {
    if (backupPollingRef.current[platformId]) clearInterval(backupPollingRef.current[platformId])
    backupPollingRef.current[platformId] = setInterval(async () => {
      try {
        const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/backup-status`), { credentials: 'include' })
        const data = await resp.json()
        if (!data.success) return
        setBackupJobs(prev => ({ ...prev, [platformId]: data }))
        if (data.step_status === 'done' || data.step_status === 'error') {
          clearInterval(backupPollingRef.current[platformId])
          if (data.step_status === 'done') fetchPlatforms()
        }
      } catch { /* silencieux */ }
    }, 1500)
  }

  const handleExpandPlatform = (platformId) => {
    setSelectedPlatformId(platformId)
    setShowAudiosModal(true)
    if (!platformAudios[platformId]) fetchAudios(platformId)
  }

  const handleDeleteAudio = (platformId, filename) => {
    setDeleteConfirm({ type: 'audio', platformId, filename })
  }

  const confirmDelete = async () => {
    if (!deleteConfirm || deletingItem) return

    setDeletingItem(true)

    try {
      if (deleteConfirm.type === 'audio') {
        const resp = await fetch(apiUrl(`/api/hr/platforms/${deleteConfirm.platformId}/audios/${encodeURIComponent(deleteConfirm.filename)}`), {
          method: 'DELETE', credentials: 'include',
        })
        const data = await resp.json()
        if (data.success) {
          fetchAudios(deleteConfirm.platformId)
          fetchPlatforms()
          setDeleteConfirm(null)
        }
      } else if (deleteConfirm.type === 'pdf') {
        const resp = await fetch(apiUrl(`/api/hr/platforms/${deleteConfirm.platformId}/pdf`), {
          method: 'DELETE', credentials: 'include',
        })
        const data = await resp.json()
        if (data.success) {
          fetchPlatforms(deleteConfirm.platformId)
          setDeleteConfirm(null)
        }
      }
    } catch (e) {
      console.error('Erreur suppression:', e)
    } finally {
      setDeletingItem(false)
    }
  }

  const handlePlayAudio = (audio) => {
    if (playingAudio?.name === audio.name) {
      setPlayingAudio(null)
    } else {
      setPlayingAudio(audio)
    }
  }

  const handlePdfUpload = async (platformId, file) => {
    setPdfUploading(platformId)
    try {
      const formData = new FormData()
      formData.append('file', file)

      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/upload-pdf-rag`), {
        method: 'POST', credentials: 'include', body: formData,
      })
      const data = await resp.json()
      if (data.success) fetchPlatforms(platformId)
    } catch (e) {
      console.error('Erreur upload PDF:', e)
    } finally {
      setPdfUploading(null)
    }
  }

  const handleSetCourseTime = async (dateCours, heureCours) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${courseTimePlatformId}/config-cours`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date_cours: dateCours, heure_cours: heureCours }),
      })
      const data = await resp.json()
      return data
    } catch (e) {
      console.error('Erreur config cours:', e)
      return { success: false, error: e.message }
    }
  }

  const handleDeletePdf = (platformId) => {
    const platformName = platforms.find((platform) => platform.id === platformId)?.name
    setDeleteConfirm({ type: 'pdf', platformId, platformName })
  }

  const handleOpenCoursFolders = (platform) => {
    setSelectedCoursPlatform(platform)
    setShowCoursFoldersModal(true)
  }

  const handleCreatePlatform = async () => {
    if (!newPlatformName.trim()) return
    setCreating(true)
    try {
      const resp = await fetch(apiUrl('/api/hr/platforms'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name: newPlatformName.trim() }),
      })
      const data = await resp.json()
      if (data.success) {
        setShowCreateModal(false)
        setNewPlatformName('')
        fetchPlatforms()
      } else {
        alert(data.error || 'Erreur lors de la création')
      }
    } catch (e) {
      console.error('Erreur création plateforme:', e)
      alert('Impossible de créer la plateforme')
    } finally {
      setCreating(false)
    }
  }

  // ─── Render ──────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center" style={{ backgroundColor: darkMode ? '#0f172a' : '#f8fafc', fontFamily: 'Inter, sans-serif' }}>
        <div className="h-10 w-10 animate-spin rounded-full border-3 border-gray-700 border-t-purple-500" />
      </div>
    )
  }

  const colors = darkMode ? {
    bg: '#0f172a',
    cardBg: '#1e293b',
    innerBg: '#0f172a',
    text: '#f1f5f9',
    textSecondary: '#cbd5e1',
    textMuted: '#64748b',
    border: '#334155',
    borderLight: '#1e293b',
    hoverBg: '#1e293b',
    gridOpacity: '0.03'
  } : {
    bg: '#f8fafc',
    cardBg: '#ffffff',
    innerBg: '#f1f5f9',
    text: '#0f172a',
    textSecondary: '#334155',
    textMuted: '#64748b',
    border: '#e2e8f0',
    borderLight: '#cbd5e1',
    hoverBg: '#f1f5f9',
    gridOpacity: '0.5'
  }

  return (
    <div className={darkMode ? 'dark' : ''}>
      <div className="relative min-h-screen overflow-hidden" style={{ backgroundColor: colors.bg, fontFamily: 'Inter, sans-serif' }}>
        {/* Top Navigation Bar */}
        <div
          className="sticky top-0 z-20 border-b"
          style={{
            backgroundColor: colors.cardBg,
            borderColor: colors.border,
            backdropFilter: 'blur(8px)'
          }}
        >
          <div className="mx-auto max-w-7xl px-6 py-4">
            <div className="flex items-center justify-between gap-4">
              <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Inter, sans-serif', color: colors.text }}>
                Dashboard <span style={{ color: '#8B5CF6' }}>Formations</span>
              </h1>
              <div className="flex items-center gap-3">
                {/* Dark mode toggle */}
                <button
                  onClick={() => setDarkMode(!darkMode)}
                  className="flex items-center gap-2 rounded-lg px-4 py-2 transition-colors"
                  style={{ backgroundColor: colors.innerBg, color: colors.textMuted, border: `1px solid ${colors.border}` }}
                >
                  <Icon name={darkMode ? 'light_mode' : 'dark_mode'} className="text-base" />
                  <span className="text-sm font-medium">{darkMode ? 'Clair' : 'Sombre'}</span>
                </button>
                {/* Nouvelle plateforme */}
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all text-white"
                  style={{ backgroundColor: '#8B5CF6' }}
                >
                  <Icon name="add" className="text-base" />
                  <span>Nouvelle plateforme</span>
                </button>
                {/* Back to admin */}
                <a
                  href="/admin"
                  className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all"
                  style={{ backgroundColor: colors.innerBg, color: colors.textSecondary, border: `1px solid ${colors.border}` }}
                >
                  <Icon name="arrow_back" className="text-base" />
                  <span>Retour Admin</span>
                </a>
              </div>
            </div>
          </div>
        </div>

        {/* Background grid pattern */}
        {darkMode && (
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage: `radial-gradient(circle at 20% 30%, rgba(139, 92, 246, 0.1) 0%, transparent 50%),
                 radial-gradient(circle at 80% 70%, rgba(139, 92, 246, 0.08) 0%, transparent 50%),
                 linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
                 linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px)`,
              backgroundSize: '100% 100%, 100% 100%, 32px 32px, 32px 32px',
            }}
          />
        )}

        <div className="relative z-10 mx-auto max-w-7xl px-6 py-8">
          {/* Platform Cards Grid with Pagination */}
          {platforms.length > CARDS_PER_PAGE && (
            <div className="flex items-center justify-center gap-3 mb-6">
              <button
                onClick={() => setCardPage(p => Math.max(0, p - 1))}
                disabled={cardPage === 0}
                className="flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                style={{
                  backgroundColor: colors.innerBg,
                  border: `1px solid ${colors.border}`,
                  color: colors.textPrimary,
                }}
              >
                <Icon name="chevron_left" className="text-lg" />
                Précédent
              </button>
              <div className="flex gap-1.5">
                {Array.from({ length: Math.ceil(platforms.length / CARDS_PER_PAGE) }).map((_, i) => (
                  <button
                    key={i}
                    onClick={() => setCardPage(i)}
                    className="w-8 h-8 rounded-full text-sm font-semibold transition-all"
                    style={{
                      backgroundColor: cardPage === i ? '#8b5cf6' : colors.innerBg,
                      color: cardPage === i ? '#fff' : colors.textSecondary,
                      border: `1px solid ${cardPage === i ? '#8b5cf6' : colors.border}`,
                    }}
                  >
                    {i + 1}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setCardPage(p => Math.min(Math.ceil(platforms.length / CARDS_PER_PAGE) - 1, p + 1))}
                disabled={cardPage >= Math.ceil(platforms.length / CARDS_PER_PAGE) - 1}
                className="flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                style={{
                  backgroundColor: colors.innerBg,
                  border: `1px solid ${colors.border}`,
                  color: colors.textPrimary,
                }}
              >
                Suivant
                <Icon name="chevron_right" className="text-lg" />
              </button>
            </div>
          )}

          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {platforms.slice(cardPage * CARDS_PER_PAGE, (cardPage + 1) * CARDS_PER_PAGE).map((p) => (
              <PlatformCard
                key={p.id}
                platform={p}
                expanded={expandedPlatform === p.id}
                audios={platformAudios[p.id] || []}
                audiosLoading={audiosLoading === p.id}
                playingAudio={playingAudio}
                pdfUploading={pdfUploading === p.id}
                backupJob={backupJobs[p.id] || null}
                audioRef={audioRef}
                colors={colors}
                darkMode={darkMode}
                onLock={() => handleLock(p.id)}
                onBackupAndUnlock={() => handleBackupAndUnlock(p.id)}
                onExpand={() => handleExpandPlatform(p.id)}
                onOpenPdfModal={() => {
                  setSelectedPlatform(p)
                  setShowPdfModal(true)
                }}
                onOpenCourseTimeModal={async () => {
                  setCourseTimePlatformId(p.id)
                  try {
                    const resp = await fetch(apiUrl(`/api/hr/platforms/${p.id}/course-time`), { credentials: 'include' })
                    const data = await resp.json()
                    if (data.success) setCurrentCourseTime(data)
                    else setCurrentCourseTime(null)
                  } catch { setCurrentCourseTime(null) }
                  setShowCourseTimeModal(true)
                }}
                onDeleteAudio={(fn) => handleDeleteAudio(p.id, fn)}
                onOpenCoursFolders={() => handleOpenCoursFolders(p)}
                onPlayAudio={handlePlayAudio}
                onPdfUpload={(file) => handlePdfUpload(p.id, file)}
                onDeletePdf={() => handleDeletePdf(p.id)}
              />
            ))}
          </div>

          {/* Footer */}
          <footer className="mt-24 border-t pt-8 pb-8" style={{ borderColor: colors.borderLight }}>
            <div className="flex items-center justify-center">
              <p className="text-sm" style={{ color: darkMode ? '#94a3b8' : '#475569' }}>
                © 2026 Sales Hacking. Tous droits réservés.
              </p>
            </div>
          </footer>
        </div>
      </div>

      {/* Modal Audios */}
      {showAudiosModal && selectedPlatformId && (
        <AudiosModal
          platformId={selectedPlatformId}
          audios={platformAudios[selectedPlatformId] || []}
          loading={audiosLoading === selectedPlatformId}
          onClose={() => setShowAudiosModal(false)}
          darkMode={darkMode}
          recorderUrl={`${(platforms.find(p => p.id === selectedPlatformId)?.frontend_url || window.location.origin)}/recorder?p=${selectedPlatformId}`}
          onRefreshAudios={() => fetchAudios(selectedPlatformId)}
        />
      )}

      {/* Modal PDF */}
      {showPdfModal && selectedPlatform && (
        <PDFModal
          platform={selectedPlatform}
          onClose={() => setShowPdfModal(false)}
          onUpload={(file) => handlePdfUpload(selectedPlatform.id, file)}
          onDelete={() => handleDeletePdf(selectedPlatform.id)}
          darkMode={darkMode}
          uploading={pdfUploading === selectedPlatform.id}
        />
      )}

      {/* Modal Heure du cours */}
      {showCourseTimeModal && (
        <CourseTimeModal
          onClose={() => setShowCourseTimeModal(false)}
          onSubmit={handleSetCourseTime}
          initialDate={currentCourseTime?.date_cours}
          initialHeure={currentCourseTime?.heure_cours}
        />
      )}

      {/* Modal Cours Folders */}
      {showCoursFoldersModal && selectedCoursPlatform && (
        <CoursFoldersModal
          platformId={selectedCoursPlatform.id}
          platformName={selectedCoursPlatform.name}
          onClose={() => setShowCoursFoldersModal(false)}
        />
      )}

      {/* Modal confirmation suppression */}
      {deleteConfirm && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
          onClick={() => {
            if (!deletingItem) setDeleteConfirm(null)
          }}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl overflow-hidden"
            style={{ width: '100%', maxWidth: '400px' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 text-center">
              <h3 className="text-lg font-bold mb-2" style={{ color: '#0f172a' }}>
                {deleteConfirm.type === 'audio' ? 'Supprimer cet audio ?' : 'Supprimer ce PDF ?'}
              </h3>
              <p className="text-sm mb-6" style={{ color: '#64748b' }}>
                {deleteConfirm.type === 'audio' ? (
                  <>
                    Voulez-vous vraiment supprimer <strong>"{deleteConfirm.filename}"</strong> ? Cette action est irréversible.
                  </>
                ) : (
                  <>
                    Voulez-vous vraiment supprimer le PDF de <strong>{deleteConfirm.platformName || 'cette plateforme'}</strong> ? Cette action est irréversible.
                  </>
                )}
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setDeleteConfirm(null)}
                  disabled={deletingItem}
                  className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors"
                  style={{ backgroundColor: '#f1f5f9', color: '#475569', border: '1px solid #e2e8f0' }}
                >
                  Annuler
                </button>
                <button
                  onClick={confirmDelete}
                  disabled={deletingItem}
                  className="flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                  style={{ backgroundColor: '#dc2626' }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#b91c1c' }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#dc2626' }}
                >
                  {deletingItem ? 'Suppression...' : 'Supprimer'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal Nouvelle Plateforme */}
      {showCreateModal && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
          onClick={() => { if (!creating) setShowCreateModal(false) }}
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: darkMode ? '#1e293b' : '#ffffff' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 mb-6">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ backgroundColor: '#8B5CF6' }}>
                <Icon name="add_business" className="text-white text-xl" />
              </div>
              <h3 className="text-lg font-semibold" style={{ color: darkMode ? '#f1f5f9' : '#1e293b' }}>
                Nouvelle plateforme
              </h3>
            </div>

            <div className="mb-6">
              <label className="block text-sm font-medium mb-2" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
                Nom de la plateforme
              </label>
              <input
                type="text"
                value={newPlatformName}
                onChange={(e) => setNewPlatformName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleCreatePlatform() }}
                placeholder="Ex: Formation Vente B2B"
                autoFocus
                className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-all"
                style={{
                  backgroundColor: darkMode ? '#0f172a' : '#f8fafc',
                  color: darkMode ? '#f1f5f9' : '#1e293b',
                  border: `1px solid ${darkMode ? '#334155' : '#e2e8f0'}`,
                }}
              />
              <p className="mt-2 text-xs" style={{ color: darkMode ? '#64748b' : '#94a3b8' }}>
                Les containers Azure Blob seront créés automatiquement.
              </p>
            </div>

            <div className="flex gap-3 justify-end">
              <button
                onClick={() => { setShowCreateModal(false); setNewPlatformName('') }}
                disabled={creating}
                className="rounded-lg px-4 py-2 text-sm font-medium transition-all"
                style={{ backgroundColor: darkMode ? '#334155' : '#f1f5f9', color: darkMode ? '#94a3b8' : '#64748b' }}
              >
                Annuler
              </button>
              <button
                onClick={handleCreatePlatform}
                disabled={creating || !newPlatformName.trim()}
                className="rounded-lg px-5 py-2 text-sm font-medium text-white transition-all"
                style={{
                  backgroundColor: creating || !newPlatformName.trim() ? '#a78bfa' : '#8B5CF6',
                  opacity: creating || !newPlatformName.trim() ? 0.6 : 1,
                }}
              >
                {creating ? 'Création...' : 'Créer la plateforme'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Audios Modal ────────────────────────────────────────────────────────────
function AudiosModal({ platformId, audios, loading, onClose, darkMode, recorderUrl, onRefreshAudios }) {
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

  const uploadedMap = Object.fromEntries(audios.map(a => [a.name, a]))
  const mergedAudios = EXPECTED_AUDIOS.map(name => uploadedMap[name]
    ? { ...uploadedMap[name], uploaded: true }
    : { name, uploaded: false }
  )

  const coursAudios = mergedAudios.filter(a => a.name.startsWith('cours_'))

  // ─── Remplir avec les audios ─────────────────────────────────────────
  const [showFillModal, setShowFillModal] = useState(false)
  const [folders, setFolders] = useState([])
  const [loadingFolders, setLoadingFolders] = useState(false)
  const [selectedFillFolderId, setSelectedFillFolderId] = useState('')
  const [filling, setFilling] = useState(false)
  const [fillResult, setFillResult] = useState(null)

  const handleOpenFillModal = async () => {
    setShowFillModal(true)
    setFillResult(null)
    setSelectedFillFolderId('')
    setLoadingFolders(true)
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/cours-folders`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) setFolders(data.folders)
    } catch (e) {
      console.error('Erreur chargement dossiers:', e)
    } finally {
      setLoadingFolders(false)
    }
  }

  const handleFill = async () => {
    if (!selectedFillFolderId) return
    setFilling(true)
    setFillResult(null)
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/fill-from-folder`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ folder_id: parseInt(selectedFillFolderId) }),
      })
      const data = await resp.json()
      setFillResult(data)
      if (data.success && onRefreshAudios) {
        onRefreshAudios()
      }
    } catch (e) {
      console.error('Erreur remplissage:', e)
      setFillResult({ success: false, error: 'Erreur réseau' })
    } finally {
      setFilling(false)
    }
  }
  const pauseAudios = mergedAudios.filter(a => a.name.startsWith('pause_'))
  const qaAudios = mergedAudios.filter(a => a.name.startsWith('qa_'))

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full overflow-hidden"
        style={{ maxWidth: '1400px', maxHeight: '90vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#e2e8f0', backgroundColor: '#137fec' }}>
          <div className="flex items-center gap-3 text-white">
            <Icon name="audiotrack" className="text-2xl" />
            <h3 className="text-lg font-bold">AUDIOS FORMATION</h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleOpenFillModal}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
              style={{ backgroundColor: 'rgba(255,255,255,0.2)', color: 'white' }}
              onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.3)'}
              onMouseLeave={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.2)'}
            >
              <Icon name="drive_folder_upload" className="text-base" />
              <span>Remplir avec les audios</span>
            </button>
            <a
              href={recorderUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
              style={{ backgroundColor: 'rgba(255,255,255,0.2)', color: 'white' }}
              onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.3)'}
              onMouseLeave={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.2)'}
            >
              <Icon name="upload" className="text-base" />
              <span>Uploader</span>
            </a>
            <button
              onClick={onClose}
              className="text-white hover:bg-white/20 rounded-full p-1 transition-colors"
            >
              <Icon name="close" className="text-2xl" />
            </button>
          </div>

          {/* Modal sélection dossier */}
          {showFillModal && (
            <div
              className="fixed inset-0 z-60 flex items-center justify-center p-4"
              style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
              onClick={() => setShowFillModal(false)}
            >
              <div
                className="bg-white rounded-2xl shadow-2xl w-full p-6"
                style={{ maxWidth: '460px' }}
                onClick={e => e.stopPropagation()}
              >
                <div className="flex items-center gap-3 mb-5">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ backgroundColor: '#137fec' }}>
                    <Icon name="drive_folder_upload" className="text-white text-xl" />
                  </div>
                  <h4 className="text-base font-bold text-slate-800">Remplir avec les audios</h4>
                </div>

                <p className="text-sm text-slate-500 mb-4">
                  Choisissez le dossier de cours à utiliser. Les 7 fichiers cours générés + les Q&A et pauses seront copiés dans la plateforme.
                </p>

                {loadingFolders ? (
                  <div className="flex justify-center py-4">
                    <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-blue-500" />
                  </div>
                ) : (
                  <select
                    value={selectedFillFolderId}
                    onChange={e => setSelectedFillFolderId(e.target.value)}
                    className="w-full rounded-lg px-3 py-2.5 text-sm mb-4 outline-none"
                    style={{ border: '1px solid #e2e8f0', color: '#1e293b', backgroundColor: '#f8fafc' }}
                  >
                    <option value="">— Sélectionner un dossier —</option>
                    {folders.map(f => (
                      <option key={f.id} value={f.id}>{f.name}</option>
                    ))}
                  </select>
                )}

                {fillResult && (
                  <div
                    className="rounded-xl p-3 mb-4 text-sm"
                    style={{
                      backgroundColor: fillResult.success ? '#dcfce7' : '#fee2e2',
                      color: fillResult.success ? '#166534' : '#991b1b',
                    }}
                  >
                    {fillResult.success
                      ? `✓ ${fillResult.copied} fichiers copiés${fillResult.errors > 0 ? ` (${fillResult.errors} erreur(s))` : ''} depuis "${fillResult.folder_name}"`
                      : `✗ ${fillResult.error}`}
                  </div>
                )}

                <div className="flex gap-3 justify-end">
                  <button
                    onClick={() => setShowFillModal(false)}
                    className="rounded-lg px-4 py-2 text-sm font-medium"
                    style={{ backgroundColor: '#f1f5f9', color: '#64748b' }}
                  >
                    {fillResult?.success ? 'Fermer' : 'Annuler'}
                  </button>
                  {!fillResult?.success && (
                    <button
                      onClick={handleFill}
                      disabled={!selectedFillFolderId || filling}
                      className="rounded-lg px-5 py-2 text-sm font-medium text-white transition-all disabled:opacity-50"
                      style={{ backgroundColor: filling || !selectedFillFolderId ? '#93c5fd' : '#137fec' }}
                    >
                      {filling ? 'Copie en cours...' : 'Remplir'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto" style={{ maxHeight: 'calc(90vh - 80px)' }}>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-500" />
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Carte COURS */}
              <AudioCard
                title="Cours"
                icon="/cours.jpg"
                bgColor="#eff6ff"
                audios={coursAudios}
                iconColor="#3b82f6"
                buttonColor="#3b82f6"
              />

              {/* Carte PAUSES */}
              <AudioCard
                title="Pauses"
                icon="/break-time.jpg"
                bgColor="#fef3c7"
                audios={pauseAudios}
                iconColor="#f59e0b"
                buttonColor="#f59e0b"
              />

              {/* Carte Q&A */}
              <AudioCard
                title="Q&A"
                icon="/qa.jpg"
                bgColor="#f0fdf4"
                audios={qaAudios}
                iconColor="#16a34a"
                buttonColor="#16a34a"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── PDF Modal ───────────────────────────────────────────────────────────────
function PDFModal({ platform, onClose, onUpload, onDelete, darkMode, uploading }) {
  const [dragOver, setDragOver] = useState(false)
  const [justUploaded, setJustUploaded] = useState(false)
  const [iframeKey, setIframeKey] = useState(0)
  const fileInputRef = useRef(null)
  const prevUploading = useRef(uploading)

  useEffect(() => {
    if (prevUploading.current && !uploading) {
      setJustUploaded(true)
    }
    prevUploading.current = uploading
  }, [uploading])

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file && file.type === 'application/pdf') {
      onUpload(file)
    }
  }

  const handleFileSelect = (e) => {
    const file = e.target.files[0]
    if (file) {
      onUpload(file)
      e.target.value = ''
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full overflow-hidden"
        style={{ maxWidth: '1200px', maxHeight: '90vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#e2e8f0', backgroundColor: '#137fec' }}>
          <div className="flex items-center gap-3 text-white">
            <Icon name="picture_as_pdf" className="text-2xl" />
            <h3 className="text-lg font-bold">GESTION DU PDF</h3>
          </div>
          <button
            onClick={onClose}
            className="text-white hover:bg-white/20 rounded-full p-1 transition-colors"
          >
            <Icon name="close" className="text-2xl" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto" style={{ maxHeight: 'calc(90vh - 80px)' }}>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* PDF Viewer */}
            <div className="flex flex-col">
              <h4 className="text-sm font-bold mb-3" style={{ color: '#111418' }}>PDF ACTUEL</h4>
              {platform.pdf_filename && platform.pdf_url ? (
                <div className="flex-1 flex flex-col border rounded-lg overflow-hidden" style={{ borderColor: '#e2e8f0', minHeight: '500px' }}>
                  <div className="flex items-center justify-between px-4 py-2 border-b" style={{ borderColor: '#e2e8f0', backgroundColor: '#f8fafc' }}>
                    <span className="text-sm font-medium truncate" style={{ color: '#64748b' }}>{platform.pdf_filename}</span>
                    <button
                      onClick={() => setIframeKey(k => k + 1)}
                      className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg transition-colors ml-2 flex-shrink-0"
                      style={{ color: '#64748b', backgroundColor: '#f1f5f9' }}
                      onMouseEnter={e => e.currentTarget.style.backgroundColor = '#e2e8f0'}
                      onMouseLeave={e => e.currentTarget.style.backgroundColor = '#f1f5f9'}
                      title="Recharger le PDF"
                    >
                      <Icon name="refresh" className="text-sm" />
                      <span>Recharger</span>
                    </button>
                  </div>
                  <iframe
                    key={iframeKey}
                    src={`https://docs.google.com/viewer?url=${encodeURIComponent(platform.pdf_url)}&embedded=true`}
                    className="flex-1 w-full"
                    style={{ minHeight: '450px' }}
                    title="PDF Viewer"
                  />
                </div>
              ) : (
                <div className="flex-1 flex items-center justify-center border-2 border-dashed rounded-lg" style={{ borderColor: '#e2e8f0', minHeight: '500px' }}>
                  <div className="text-center">
                    <Icon name="picture_as_pdf" className="text-6xl mb-3" style={{ color: '#cbd5e1' }} />
                    <p className="text-sm" style={{ color: '#94a3b8' }}>Aucun PDF uploadé</p>
                  </div>
                </div>
              )}
            </div>

            {/* Upload Section */}
            <div className="flex flex-col">
              <h4 className="text-sm font-bold mb-3" style={{ color: '#111418' }}>UPLOADER UN NOUVEAU PDF</h4>

              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => !uploading && fileInputRef.current?.click()}
                className="flex-1 flex flex-col items-center justify-center border-2 border-dashed rounded-lg cursor-pointer transition-all"
                style={{
                  borderColor: dragOver ? '#137fec' : '#e2e8f0',
                  backgroundColor: dragOver ? 'rgba(19, 127, 236, 0.05)' : 'transparent',
                  minHeight: '500px',
                  cursor: uploading ? 'not-allowed' : 'pointer',
                  opacity: uploading ? 0.6 : 1
                }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  className="hidden"
                  onChange={handleFileSelect}
                  disabled={uploading}
                />
                <div className="flex flex-col items-center gap-4 text-center px-6">
                  {uploading ? (
                    <>
                      <div className="h-16 w-16 animate-spin rounded-full border-4 border-gray-200 border-t-blue-500" />
                      <p className="text-sm font-medium" style={{ color: '#64748b' }}>Upload en cours...</p>
                    </>
                  ) : justUploaded ? (
                    <div className="flex flex-row items-center gap-4 px-4">
                      <img
                        src="/speed-arrow.png"
                        alt=""
                        className="w-24 h-20 flex-shrink-0 object-contain"
                        style={{ transform: 'scaleX(-1)' }}
                      />
                      <p className="text-base font-semibold leading-snug text-left" style={{ color: '#1d4ed8' }}>
                        Le chatbot a bien été alimenté à partir du contenu du cours de cette semaine !
                      </p>
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center justify-center size-20 rounded-full" style={{ backgroundColor: 'rgba(19, 127, 236, 0.1)' }}>
                        <Icon name="cloud_upload" className="text-5xl" style={{ color: '#137fec' }} />
                      </div>
                      <div>
                        <h3 className="font-bold text-lg mb-2" style={{ color: '#111418' }}>
                          Glissez votre PDF ici
                        </h3>
                        <p className="text-sm" style={{ color: '#64748b' }}>ou cliquez pour parcourir</p>
                        <p className="text-xs mt-2" style={{ color: '#94a3b8' }}>Format supporté : PDF uniquement</p>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Audio Card Component ────────────────────────────────────────────────────
function AudioCard({ title, icon, bgColor, audios, iconColor, buttonColor }) {
  return (
    <div className="rounded-2xl bg-white border shadow-sm p-6 flex flex-col" style={{ borderColor: '#e2e8f0' }}>
      <div className="flex items-center gap-3 mb-4 pb-4 border-b" style={{ borderColor: '#e2e8f0' }}>
        <div className="flex items-center justify-center size-12 rounded-xl overflow-hidden border-2" style={{ backgroundColor: bgColor, borderColor: '#000000' }}>
          <img src={icon} alt={title} className="w-full h-full object-cover" />
        </div>
        <div>
          <h3 className="text-lg font-bold" style={{ color: '#111418' }}>{title}</h3>
          <p className="text-xs" style={{ color: '#64748b' }}>{audios.filter(a => a.uploaded).length}/{audios.length} fichiers</p>
        </div>
      </div>
      <div className="flex-1 space-y-2">
        {audios.map((audio, index) => (
          <div key={index} className={`rounded-lg p-3 transition-all ${!audio.uploaded ? 'opacity-40' : ''}`}>
            <div className="flex items-center gap-2">
              {audio.uploaded ? (
                <div className="flex-shrink-0 flex items-center justify-center size-7 rounded-full" style={{ backgroundColor: buttonColor, color: 'white' }}>
                  <Icon name="check" className="text-sm" />
                </div>
              ) : (
                <div className="flex-shrink-0 flex items-center justify-center size-7 rounded-full" style={{ backgroundColor: '#f1f5f9', color: '#cbd5e1' }}>
                  <Icon name="play_arrow" className="text-sm" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <p className={`text-xs truncate ${audio.uploaded ? 'font-medium' : ''}`} style={{ color: audio.uploaded ? '#111418' : '#94a3b8' }}>
                  {audio.name.replace('cours_', '').replace('pause_', '').replace('pause_midi_', 'midi ').replace('qa_', '').replace('.mp3', '')}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Platform Card ───────────────────────────────────────────────────────────
function PlatformCard({
  platform: p, expanded, audios, audiosLoading, playingAudio, pdfUploading, backupJob,
  audioRef, colors, darkMode, onLock, onBackupAndUnlock, onExpand, onOpenPdfModal, onOpenCourseTimeModal, onDeleteAudio, onPlayAudio, onPdfUpload, onDeletePdf, onOpenCoursFolders,
}) {
  const isBackupRunning = backupJob && backupJob.step_status === 'running'
  const isBackupDone = backupJob && backupJob.step_status === 'done'
  const isBackupError = backupJob && backupJob.step_status === 'error'
  const pdfInputId = `pdf-input-${p.id}`

  return (
    <div
      className="relative rounded-2xl overflow-hidden transition-all duration-300"
      style={{
        backgroundColor: colors.cardBg,
        border: p.active ? '1px solid #8B5CF6' : `1px solid ${colors.border}`,
        boxShadow: darkMode ? 'none' : '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1)'
      }}
    >
      {/* Inactive overlay */}
      {!p.active && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center rounded-2xl"
          style={{ backgroundColor: darkMode ? 'rgba(15, 23, 42, 0.85)' : 'rgba(248, 250, 252, 0.95)', backdropFilter: 'blur(4px)' }}
        >
          <div className="text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full" style={{ backgroundColor: darkMode ? '#334155' : '#e2e8f0' }}>
              <Icon name="schedule" className="text-2xl" style={{ color: colors.textMuted }} />
            </div>
            <p className="text-sm font-semibold" style={{ color: colors.textSecondary }}>BIENTÔT DISPONIBLE</p>
          </div>
        </div>
      )}

      <div className="p-6">
        {/* Header */}
        <div className="mb-6 flex items-start justify-between">
          <h3 className="text-lg font-semibold" style={{ color: colors.text }}>{p.name}</h3>
        </div>

        {/* Slide to confirm */}
        <div className="mb-5 space-y-3">
          <SlideToConfirm
            locked={p.upload_locked}
            onConfirm={p.upload_locked ? onBackupAndUnlock : onLock}
            disabled={isBackupRunning}
            darkMode={darkMode}
            colors={colors}
          />

          {/* Pipeline de backup */}
          {(isBackupRunning || isBackupDone || isBackupError) && (
            <BackupPipeline job={backupJob} colors={colors} darkMode={darkMode} />
          )}
        </div>

        {/* PDF Section */}
        <button
          onClick={onOpenPdfModal}
          className="mb-5 flex w-full items-center justify-between rounded-lg px-4 py-2.5 text-sm font-medium transition-all"
          style={{
            backgroundColor: colors.innerBg,
            border: `1px solid ${colors.border}`,
            color: colors.textSecondary,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = colors.hoverBg
            e.currentTarget.style.borderColor = darkMode ? '#475569' : '#94a3b8'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = colors.innerBg
            e.currentTarget.style.borderColor = colors.border
          }}
        >
          <div className="flex items-center gap-2.5">
            <Icon name="picture_as_pdf" className="text-lg" style={{ color: '#8B5CF6' }} />
            <span>Voir le PDF</span>
          </div>
          <Icon name="chevron_right" className="text-xl" />
        </button>

        {/* Expand audios (only for active platforms) */}
        {/* Lien vers le cours */}
        {p.active && (
          <a
            href={`${p.frontend_url || window.location.origin}/?p=${p.id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex w-full items-center justify-between rounded-lg px-4 py-2.5 text-sm font-medium transition-all mb-3"
            style={{
              backgroundColor: colors.innerBg,
              border: `1px solid ${colors.border}`,
              color: colors.textSecondary,
              textDecoration: 'none',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = colors.hoverBg
              e.currentTarget.style.borderColor = darkMode ? '#475569' : '#94a3b8'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = colors.innerBg
              e.currentTarget.style.borderColor = colors.border
            }}
          >
            <span>Accéder au cours</span>
            <Icon name="open_in_new" className="text-xl" />
          </a>
        )}

        {/* Bouton heure du cours */}
        {p.active && (
          <button
            onClick={onOpenCourseTimeModal}
            className="flex w-full items-center justify-between rounded-lg px-4 py-2.5 text-sm font-medium transition-all mb-3"
            style={{
              backgroundColor: colors.innerBg,
              border: `1px solid ${colors.border}`,
              color: colors.textSecondary,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = colors.hoverBg
              e.currentTarget.style.borderColor = darkMode ? '#475569' : '#94a3b8'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = colors.innerBg
              e.currentTarget.style.borderColor = colors.border
            }}
          >
            <span>Heure du cours</span>
            <Icon name="chevron_right" className="text-xl" />
          </button>
        )}

        {p.active && (
          <button
            onClick={onExpand}
            className="flex w-full items-center justify-between rounded-lg px-4 py-2.5 text-sm font-medium transition-all"
            style={{
              backgroundColor: colors.innerBg,
              border: `1px solid ${colors.border}`,
              color: colors.textSecondary,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = colors.hoverBg
              e.currentTarget.style.borderColor = darkMode ? '#475569' : '#94a3b8'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = colors.innerBg
              e.currentTarget.style.borderColor = colors.border
            }}
          >
            <span>Voir les audios</span>
            <Icon
              name="chevron_right"
              className="text-xl"
            />
          </button>
        )}

        {/* Audio list */}
        {expanded && p.active && (
          <div className="mt-4 max-h-80 space-y-2 overflow-y-auto pr-1">
            {audiosLoading ? (
              <div className="flex items-center justify-center py-8">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-700 border-t-purple-500" />
              </div>
            ) : audios.length === 0 ? (
              <p className="py-6 text-center text-xs" style={{ color: colors.textMuted }}>Aucun audio</p>
            ) : (
              audios.map((audio) => (
                <div key={audio.name} className="space-y-2">
                  <div
                    className="flex items-center gap-2.5 rounded-lg px-3 py-2 transition-colors"
                    style={{ backgroundColor: colors.innerBg }}
                  >
                    <button
                      onClick={() => onPlayAudio(audio)}
                      className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full transition-colors"
                      style={{ backgroundColor: '#8B5CF6', color: 'white' }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = '#7c3aed'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = '#8B5CF6'
                      }}
                    >
                      <Icon name={playingAudio?.name === audio.name ? 'pause' : 'play_arrow'} className="text-sm" />
                    </button>
                    <span className="min-w-0 flex-1 truncate text-xs" style={{ color: colors.textSecondary }} title={audio.name}>
                      {audio.name}
                    </span>
                    <span className="flex-shrink-0 text-[10px]" style={{ color: colors.textMuted }}>
                      {formatSize(audio.size)}
                    </span>
                    <button
                      onClick={() => onDeleteAudio(audio.name)}
                      className="flex-shrink-0 rounded-md p-1 transition-colors"
                      style={{ color: colors.textMuted }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = darkMode ? '#450a0a' : '#fee2e2'
                        e.currentTarget.style.color = '#f87171'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent'
                        e.currentTarget.style.color = colors.textMuted
                      }}
                      title="Supprimer"
                    >
                      <Icon name="delete" className="text-sm" />
                    </button>
                  </div>
                  {playingAudio?.name === audio.name && (
                    <audio
                      ref={audioRef}
                      src={audio.url}
                      controls
                      autoPlay
                      className="w-full h-8 rounded"
                      style={{ colorScheme: 'dark' }}
                      onEnded={() => onPlayAudio(audio)}
                    />
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {/* Cours Folders button */}
        {p.active && (
          <button
            onClick={onOpenCoursFolders}
            className="mt-3 flex w-full items-center justify-between rounded-lg px-4 py-2.5 text-sm font-medium transition-all"
            style={{
              backgroundColor: colors.innerBg,
              border: `1px solid ${colors.border}`,
              color: colors.textSecondary,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = colors.hoverBg
              e.currentTarget.style.borderColor = darkMode ? '#475569' : '#94a3b8'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = colors.innerBg
              e.currentTarget.style.borderColor = colors.border
            }}
          >
            <div className="flex items-center gap-2.5">
              <Icon name="folder_special" className="text-lg" style={{ color: '#8B5CF6' }} />
              <span>Gérer les cours</span>
            </div>
            <Icon name="chevron_right" className="text-xl" />
          </button>
        )}

      </div>
    </div>
  )
}

function formatSize(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDateShort(dateStr) {
  if (!dateStr) return '—'
  const parts = dateStr.split(' ')[0].split('-')
  if (parts.length === 3) return `${parts[2]}/${parts[1]}`
  return dateStr
}

// ─── Slide To Confirm ────────────────────────────────────────────────────────
function SlideToConfirm({ locked, onConfirm, disabled, darkMode, colors }) {
  const [dragX, setDragX] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const containerRef = useRef(null)
  const isDraggingRef = useRef(false)
  const startXRef = useRef(0)
  const dragXRef = useRef(0)
  const onConfirmRef = useRef(onConfirm)

  useEffect(() => { onConfirmRef.current = onConfirm }, [onConfirm])

  const THUMB_SIZE = 36
  const THRESHOLD = 0.85

  const getMax = useCallback(() => {
    if (!containerRef.current) return 200
    return containerRef.current.offsetWidth - THUMB_SIZE - 8
  }, [])

  useEffect(() => {
    const onMouseMove = (e) => {
      if (!isDraggingRef.current) return
      const newX = Math.max(0, Math.min(e.clientX - startXRef.current, getMax()))
      dragXRef.current = newX
      setDragX(newX)
    }
    const onMouseUp = () => {
      if (!isDraggingRef.current) return
      isDraggingRef.current = false
      setIsDragging(false)
      const max = getMax()
      if (dragXRef.current / max >= THRESHOLD) {
        dragXRef.current = max
        setDragX(max)
        setConfirmed(true)
        onConfirmRef.current()
        setTimeout(() => {
          setConfirmed(false)
          dragXRef.current = 0
          setDragX(0)
        }, 1200)
      } else {
        dragXRef.current = 0
        setDragX(0)
      }
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [getMax])

  const handleMouseDown = (e) => {
    e.preventDefault()
    if (disabled || confirmed) return
    isDraggingRef.current = true
    setIsDragging(true)
    startXRef.current = e.clientX - dragXRef.current
  }

  const handleTouchStart = (e) => {
    if (disabled || confirmed) return
    isDraggingRef.current = true
    setIsDragging(true)
    startXRef.current = e.touches[0].clientX - dragXRef.current
  }

  const handleTouchMove = (e) => {
    if (!isDraggingRef.current) return
    e.preventDefault()
    const newX = Math.max(0, Math.min(e.touches[0].clientX - startXRef.current, getMax()))
    dragXRef.current = newX
    setDragX(newX)
  }

  const handleTouchEnd = () => {
    if (!isDraggingRef.current) return
    isDraggingRef.current = false
    setIsDragging(false)
    const max = getMax()
    if (dragXRef.current / max >= THRESHOLD) {
      dragXRef.current = max
      setDragX(max)
      setConfirmed(true)
      onConfirmRef.current()
      setTimeout(() => {
        setConfirmed(false)
        dragXRef.current = 0
        setDragX(0)
      }, 1200)
    } else {
      dragXRef.current = 0
      setDragX(0)
    }
  }

  const progress = dragX / Math.max(1, getMax())

  const trackColor = locked
    ? (darkMode ? 'rgba(139, 92, 246, 0.15)' : 'rgba(16, 185, 129, 0.08)')
    : (darkMode ? 'rgba(71, 85, 105, 0.4)' : '#e8edf2')
  const fillColor = locked
    ? (darkMode ? '#8B5CF6' : '#10b981')
    : (darkMode ? '#8B5CF6' : '#10b981')
  const borderColor = locked
    ? (darkMode ? 'rgba(139, 92, 246, 0.3)' : 'rgba(16, 185, 129, 0.3)')
    : colors.border
  const iconColor = locked
    ? (darkMode ? '#8B5CF6' : '#10b981')
    : (darkMode ? '#64748b' : '#94a3b8')
  const textColor = locked
    ? (darkMode ? '#a78bfa' : '#059669')
    : colors.textMuted

  return (
    <div
      ref={containerRef}
      className="relative overflow-hidden rounded-full select-none"
      style={{
        height: 44,
        backgroundColor: trackColor,
        border: `1px solid ${borderColor}`,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'default',
      }}
    >
      {/* Fill */}
      <div
        className="absolute inset-y-0 left-0 rounded-full"
        style={{
          width: dragX + THUMB_SIZE + 4,
          backgroundColor: fillColor,
          opacity: 0.12 + progress * 0.2,
          transition: isDragging ? 'none' : 'width 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)',
        }}
      />

      {/* Label */}
      <div
        className="absolute inset-0 flex items-center justify-center pointer-events-none"
        style={{ paddingLeft: THUMB_SIZE + 16, paddingRight: 12 }}
      >
        <span
          className="text-xs font-medium whitespace-nowrap"
          style={{
            fontFamily: 'Inter, sans-serif',
            color: confirmed ? fillColor : textColor,
            opacity: confirmed ? 1 : Math.max(0, 1 - progress * 2.2),
            transition: isDragging ? 'none' : 'opacity 0.3s',
          }}
        >
          {confirmed
            ? '✓ Confirmé'
            : locked
              ? "Glisser pour déverrouiller l'accès aux audios →"
              : "Glisser pour verrouiller l'accès aux audios →"}
        </span>
      </div>

      {/* Thumb */}
      <div
        className="absolute top-1 flex items-center justify-center rounded-full"
        style={{
          left: 4 + dragX,
          width: THUMB_SIZE,
          height: THUMB_SIZE,
          backgroundColor: 'white',
          cursor: disabled ? 'not-allowed' : isDragging ? 'grabbing' : 'grab',
          transition: isDragging ? 'none' : 'left 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)',
          boxShadow: isDragging ? '0 4px 12px rgba(0,0,0,0.2)' : '0 2px 6px rgba(0,0,0,0.12)',
          transform: isDragging ? 'scale(1.1)' : 'scale(1)',
        }}
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        <Icon
          name={confirmed ? 'check' : locked ? 'lock' : 'lock_open'}
          className="text-base"
          style={{ color: iconColor }}
        />
      </div>
    </div>
  )
}

// ─── Course Time Modal ───────────────────────────────────────────────────────
function CourseTimeModal({ onClose, onSubmit, initialDate, initialHeure }) {
  const today = new Date().toISOString().split('T')[0]
  const [date, setDate] = useState(initialDate || today)
  const [heure, setHeure] = useState(initialHeure || '')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!date || !heure) return
    setLoading(true)
    setResult(null)
    const data = await onSubmit(date, heure)
    setResult(data)
    setLoading(false)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl overflow-hidden"
        style={{ width: '100%', maxWidth: '420px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#e2e8f0', backgroundColor: '#137fec' }}>
          <div className="flex items-center gap-3 text-white">
            <Icon name="schedule" className="text-2xl" />
            <h3 className="text-lg font-bold">HEURE DU COURS</h3>
          </div>
          <button
            onClick={onClose}
            className="text-white hover:bg-white/20 rounded-full p-1 transition-colors"
          >
            <Icon name="close" className="text-2xl" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6">
          {result?.success ? (
            <div className="flex flex-col items-center gap-4 py-4 text-center">
              <div className="flex items-center justify-center size-14 rounded-full" style={{ backgroundColor: 'rgba(16, 185, 129, 0.1)' }}>
                <Icon name="check_circle" className="text-4xl" style={{ color: '#10b981' }} />
              </div>
              <p className="text-sm font-medium" style={{ color: '#0f172a' }}>{result.message}</p>
              <button
                onClick={onClose}
                className="mt-2 rounded-lg px-5 py-2 text-sm font-semibold text-white transition-colors"
                style={{ backgroundColor: '#137fec' }}
              >
                Fermer
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <div>
                <label className="block text-xs font-semibold mb-1.5" style={{ color: '#334155' }}>Date du cours</label>
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                  required
                  className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                  style={{ borderColor: '#e2e8f0', color: '#0f172a', backgroundColor: '#f8fafc' }}
                  onFocus={(e) => { e.currentTarget.style.borderColor = '#137fec' }}
                  onBlur={(e) => { e.currentTarget.style.borderColor = '#e2e8f0' }}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1.5" style={{ color: '#334155' }}>Heure de début</label>
                <input
                  type="time"
                  value={heure}
                  onChange={(e) => setHeure(e.target.value)}
                  required
                  className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                  style={{ borderColor: '#e2e8f0', color: '#0f172a', backgroundColor: '#f8fafc' }}
                  onFocus={(e) => { e.currentTarget.style.borderColor = '#137fec' }}
                  onBlur={(e) => { e.currentTarget.style.borderColor = '#e2e8f0' }}
                />
              </div>

              {result && !result.success && (
                <p className="text-xs rounded-lg px-3 py-2" style={{ color: '#dc2626', backgroundColor: '#fee2e2' }}>
                  {result.error || 'Une erreur est survenue'}
                </p>
              )}

              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={onClose}
                  className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors"
                  style={{ backgroundColor: '#f1f5f9', color: '#475569', border: '1px solid #e2e8f0' }}
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  disabled={loading || !date || !heure}
                  className="flex-1 flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-opacity"
                  style={{ backgroundColor: '#137fec', opacity: (loading || !date || !heure) ? 0.6 : 1 }}
                >
                  {loading ? (
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  ) : (
                    <Icon name="save" className="text-base" />
                  )}
                  {loading ? 'Enregistrement...' : 'Enregistrer'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Backup Pipeline ─────────────────────────────────────────────────────────
function BackupPipeline({ job, colors, darkMode }) {
  const steps = [
    { label: 'Sauvegarde de tous les fichiers', step: 1 },
    { label: 'Suppression des audios actuels', step: 2 },
    { label: 'Les intervenants peuvent déposer des audios', step: 3 },
  ]

  const getStepState = (stepNum) => {
    if (job.step_status === 'error' && job.step === stepNum) return 'error'
    if (job.step > stepNum) return 'done'
    if (job.step === stepNum && job.step_status === 'running') return 'running'
    if (job.step === stepNum && job.step_status === 'done') return 'done'
    return 'pending'
  }

  return (
    <div
      className="rounded-xl p-4"
      style={{
        backgroundColor: colors.innerBg,
        border: `1px solid ${colors.border}`,
      }}
    >
      <div className="flex items-start gap-0">
        {steps.map((s, i) => {
          const state = getStepState(s.step)
          return (
            <div key={s.step} className="flex flex-1 flex-col items-center">
              {/* Connecteur + cercle */}
              <div className="flex w-full items-center">
                {i > 0 && (
                  <div
                    className="h-px flex-1 transition-colors duration-500"
                    style={{ backgroundColor: getStepState(steps[i - 1].step) === 'done' ? (darkMode ? '#8B5CF6' : '#10b981') : colors.border }}
                  />
                )}
                <div
                  className="relative flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border-2 transition-all duration-500"
                  style={{
                    borderColor:
                      state === 'done' ? (darkMode ? '#8B5CF6' : '#10b981') :
                      state === 'running' ? '#8B5CF6' :
                      state === 'error' ? '#dc2626' :
                      (darkMode ? '#475569' : '#cbd5e1'),
                    backgroundColor:
                      state === 'done' ? (darkMode ? '#8B5CF6' : '#10b981') :
                      state === 'running' ? colors.innerBg :
                      state === 'error' ? (darkMode ? '#450a0a' : '#fee2e2') :
                      colors.cardBg,
                  }}
                >
                  {state === 'done' && (
                    <Icon name="check" className="text-sm" style={{ color: 'white' }} />
                  )}
                  {state === 'running' && (
                    <div
                      className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-t-transparent"
                      style={{ borderColor: darkMode ? '#a855f7' : '#10b981', borderTopColor: 'transparent' }}
                    />
                  )}
                  {state === 'error' && (
                    <Icon name="close" className="text-sm" style={{ color: '#f87171' }} />
                  )}
                  {state === 'pending' && (
                    <div className="h-2 w-2 rounded-full" style={{ backgroundColor: darkMode ? '#475569' : '#cbd5e1' }} />
                  )}
                </div>
                {i < steps.length - 1 && (
                  <div
                    className="h-px flex-1 transition-colors duration-500"
                    style={{ backgroundColor: state === 'done' ? (darkMode ? '#8B5CF6' : '#10b981') : colors.border }}
                  />
                )}
              </div>
              {/* Label */}
              <p
                className="mt-2 text-center text-[10px] leading-tight transition-colors duration-300"
                style={{
                  color:
                    state === 'done' ? (darkMode ? '#c084fc' : '#0f172a') :
                    state === 'running' ? colors.text :
                    state === 'error' ? (darkMode ? '#fca5a5' : '#dc2626') :
                    colors.textMuted,
                }}
              >
                {s.label}
                {state === 'running' && s.step === 1 && job.total > 0 && (
                  <span className="block" style={{ color: colors.textMuted }}>
                    {job.progress}/{job.total}
                  </span>
                )}
              </p>
            </div>
          )
        })}
      </div>

      {job.error && (
        <p className="mt-3 text-xs" style={{ color: darkMode ? '#fca5a5' : '#dc2626' }}>{job.error}</p>
      )}
    </div>
  )
}
