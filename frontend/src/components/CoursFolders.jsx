import { useState, useEffect, useRef } from 'react'
import { apiUrl } from '../api'

// ─── Material Icon Component ─────────────────────────────────────────────────
const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`}>{name}</span>
)

const COURS_DURATIONS_MAP = { 1: 45, 2: 45, 3: 55, 4: 45, 5: 60, 6: 60, 7: 50 }

// ─── Component ───────────────────────────────────────────────────────────────
export default function CoursFoldersModal({ platformId, platformName, onClose }) {
  const [view, setView] = useState('folders') // 'folders' | 'documents'
  const [folders, setFolders] = useState([])
  const [documents, setDocuments] = useState([])
  const [selectedFolder, setSelectedFolder] = useState(null)
  const [loading, setLoading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [ttsStatus, setTtsStatus] = useState(null)
  const [generatingAll, setGeneratingAll] = useState(false)
  const [darkMode, setDarkMode] = useState(false)
  const [showCreateFolderForm, setShowCreateFolderForm] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [createFolderError, setCreateFolderError] = useState('')
  const [creatingFolder, setCreatingFolder] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [deleteError, setDeleteError] = useState('')
  const [deletingItem, setDeletingItem] = useState(false)
  const [playlistJob, setPlaylistJob] = useState(null) // {status, step, total_steps, message}
  const playlistPollingRef = useRef(null)
  const [scriptModal, setScriptModal] = useState(null) // {blocs: [...]}
  const [loadingScript, setLoadingScript] = useState(false)
  const fileInputRef = useRef(null)
  const createFolderInputRef = useRef(null)
  const pollingRef = useRef(null)

  const colors = darkMode ? {
    bg: '#0f172a',
    cardBg: '#1e293b',
    innerBg: '#0f172a',
    text: '#f1f5f9',
    textSecondary: '#cbd5e1',
    textMuted: '#64748b',
    border: '#334155',
    hoverBg: '#1e293b',
  } : {
    bg: '#f8fafc',
    cardBg: '#ffffff',
    innerBg: '#f1f5f9',
    text: '#0f172a',
    textSecondary: '#334155',
    textMuted: '#64748b',
    border: '#e2e8f0',
    hoverBg: '#f1f5f9',
  }

  // ─── Initial load ─────────────────────────────────────────────────────
  useEffect(() => {
    // Détecter le mode sombre depuis le body
    const isDark = document.documentElement.classList.contains('dark') ||
                   document.body.style.backgroundColor?.includes('15, 23, 42')
    setDarkMode(isDark)

    fetchFolders()

    // Écouter les changements de mode
    const observer = new MutationObserver(() => {
      const isDark = document.documentElement.classList.contains('dark') ||
                     document.body.style.backgroundColor?.includes('15, 23, 42')
      setDarkMode(isDark)
    })
    observer.observe(document.body, { attributes: true, attributeFilter: ['style', 'class'] })
    return () => observer.disconnect()
  }, [platformId])

  useEffect(() => {
    if (showCreateFolderForm) {
      createFolderInputRef.current?.focus()
    }
  }, [showCreateFolderForm])

  // ─── Fetch folders ──────────────────────────────────────────────────────
  const fetchFolders = async () => {
    setLoading(true)
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/cours-folders`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setFolders(data.folders)
      }
    } catch (e) {
      console.error('Erreur chargement dossiers:', e)
    } finally {
      setLoading(false)
    }
  }

  // ─── Fetch documents ───────────────────────────────────────────────────
  const fetchDocuments = async (folderId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${folderId}/documents`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setDocuments(data.documents)
      }
    } catch (e) {
      console.error('Erreur chargement documents:', e)
    }
  }

  // ─── Fetch TTS status (polling) ────────────────────────────────────────
  const fetchTtsStatus = async (folderId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${folderId}/tts-status`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setTtsStatus(data)
        setDocuments(data.documents)

        const hasProcessing = data.documents.some(d => d.status === 'processing')
        if (!hasProcessing && pollingRef.current) {
          clearInterval(pollingRef.current)
          pollingRef.current = null
        }
      }
    } catch (e) {
      console.error('Erreur statut TTS:', e)
    }
  }

  // ─── Polling TTS status ────────────────────────────────────────────────
  useEffect(() => {
    if (view === 'documents' && selectedFolder) {
      fetchDocuments(selectedFolder.id)

      const checkProcessing = async () => {
        const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/tts-status`), { credentials: 'include' })
        const data = await resp.json()
        if (data.success) {
          const hasProcessing = data.documents.some(d => d.status === 'processing')
          if (hasProcessing && !pollingRef.current) {
            pollingRef.current = setInterval(() => fetchTtsStatus(selectedFolder.id), 3000)
          }
        }
      }
      checkProcessing()
    }

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [view, selectedFolder])

  // ─── Actions ─────────────────────────────────────────────────────────
  const handleCreateFolder = () => {
    setShowCreateFolderForm(true)
    setCreateFolderError('')
  }

  const handleCancelCreateFolder = () => {
    setShowCreateFolderForm(false)
    setNewFolderName('')
    setCreateFolderError('')
  }

  const handleCreateFolderSubmit = (e) => {
    e.preventDefault()
    const trimmedName = newFolderName.trim()
    if (!trimmedName) {
      setCreateFolderError('Saisissez un nom de cours.')
      createFolderInputRef.current?.focus()
      return
    }
    createFolder(trimmedName)
  }

  const createFolder = async (name) => {
    setCreatingFolder(true)
    setCreateFolderError('')
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/cours-folders`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        setShowCreateFolderForm(false)
        setNewFolderName('')
        fetchFolders()
      } else {
        setCreateFolderError(data.error || 'Erreur lors de la création')
      }
    } catch (e) {
      console.error('Erreur création dossier:', e)
      setCreateFolderError('Erreur lors de la création du cours.')
    } finally {
      setCreatingFolder(false)
    }
  }

  const handleDeleteFolder = (folderId, folderName) => {
    setDeleteError('')
    setDeleteConfirm({
      type: 'folder',
      folderId,
      folderName,
    })
  }

  const deleteFolder = async (folderId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${folderId}`), {
        method: 'DELETE',
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        await fetchFolders()
        return { success: true }
      }
      return { success: false, error: data.error || 'Erreur suppression dossier' }
    } catch (e) {
      console.error('Erreur suppression dossier:', e)
      return { success: false, error: 'Erreur lors de la suppression du cours.' }
    }
  }

  const handleOpenFolder = (folder) => {
    setSelectedFolder(folder)
    setView('documents')
    setDocuments([])
    setTtsStatus(null)
  }

  const handleBackToFolders = () => {
    setView('folders')
    setSelectedFolder(null)
    setDocuments([])
    setTtsStatus(null)
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    setDragOver(true)
  }

  const handleDragLeave = () => {
    setDragOver(false)
  }

  const handleDrop = async (e) => {
    e.preventDefault()
    setDragOver(false)

    const files = Array.from(e.dataTransfer.files)
    const pdfFiles = files.filter(f => f.type === 'application/pdf')

    if (pdfFiles.length === 0) {
      alert('Veuillez déposer uniquement des fichiers PDF')
      return
    }

    await uploadFiles(pdfFiles)
  }

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files)
    if (files.length > 0) {
      uploadFiles(files)
    }
    e.target.value = ''
  }

  const uploadFiles = async (files) => {
    setUploading(true)
    try {
      const formData = new FormData()
      files.forEach(f => formData.append('files', f))

      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/upload`), {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      const data = await resp.json()
      if (data.success) {
        fetchDocuments(selectedFolder.id)
      } else {
        alert(data.error || 'Erreur lors de l\'upload')
      }
    } catch (e) {
      console.error('Erreur upload:', e)
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteDocument = (documentId, documentName) => {
    setDeleteError('')
    setDeleteConfirm({
      type: 'document',
      documentId,
      documentName,
    })
  }

  const deleteDocument = async (documentId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-documents/${documentId}`), {
        method: 'DELETE',
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        await fetchDocuments(selectedFolder.id)
        return { success: true }
      }
      return { success: false, error: data.error || 'Erreur suppression document' }
    } catch (e) {
      console.error('Erreur suppression document:', e)
      return { success: false, error: 'Erreur lors de la suppression du document.' }
    }
  }

  const confirmDelete = async () => {
    if (!deleteConfirm || deletingItem) return

    setDeletingItem(true)
    setDeleteError('')

    let result
    if (deleteConfirm.type === 'folder') {
      result = await deleteFolder(deleteConfirm.folderId)
    } else {
      result = await deleteDocument(deleteConfirm.documentId)
    }

    if (result?.success) {
      setDeleteConfirm(null)
    } else if (result?.error) {
      setDeleteError(result.error)
    }

    setDeletingItem(false)
  }

  const handleDownloadPdf = (documentId) => {
    window.open(apiUrl(`/api/hr/cours-documents/${documentId}/download`), '_blank')
  }

  const handleDownloadAudio = (documentId) => {
    window.open(apiUrl(`/api/hr/cours-documents/${documentId}/audio`), '_blank')
  }

  const handleGenerateAudio = async (documentId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-documents/${documentId}/generate-audio`), {
        method: 'POST',
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        fetchDocuments(selectedFolder.id)
        if (!pollingRef.current) {
          pollingRef.current = setInterval(() => fetchTtsStatus(selectedFolder.id), 3000)
        }
      }
    } catch (e) {
      console.error('Erreur génération audio:', e)
    }
  }

  const handleGenerateAll = async () => {
    setGeneratingAll(true)
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/generate-all-audio`), {
        method: 'POST',
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        fetchDocuments(selectedFolder.id)
        if (!pollingRef.current) {
          pollingRef.current = setInterval(() => fetchTtsStatus(selectedFolder.id), 3000)
        }
      }
    } catch (e) {
      console.error('Erreur génération tous:', e)
    } finally {
      setGeneratingAll(false)
    }
  }

  // ─── Playlist pipeline ──────────────────────────────────────────────
  const fetchPlaylistStatus = async (folderId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${folderId}/playlist-status`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setPlaylistJob(data)
        if (data.status !== 'running' && playlistPollingRef.current) {
          clearInterval(playlistPollingRef.current)
          playlistPollingRef.current = null
        }
      }
    } catch (e) {
      console.error('Erreur statut playlist:', e)
    }
  }

  const handleGeneratePlaylist = async () => {
    if (!selectedFolder) return
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/generate-playlist`), {
        method: 'POST',
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        setPlaylistJob({ status: 'running', step: 0, total_steps: 24, message: 'Démarrage...' })
        playlistPollingRef.current = setInterval(() => fetchPlaylistStatus(selectedFolder.id), 2000)
      } else {
        alert(data.error || 'Erreur lors du lancement')
      }
    } catch (e) {
      console.error('Erreur lancement playlist:', e)
    }
  }

  const handleViewScript = async () => {
    if (!selectedFolder) return
    setLoadingScript(true)
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/playlist-script`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setScriptModal(data)
      } else {
        alert(data.error || 'Aucun script disponible')
      }
    } catch (e) {
      console.error('Erreur chargement script:', e)
    } finally {
      setLoadingScript(false)
    }
  }

  // Vérifier le statut playlist quand on entre dans un dossier
  useEffect(() => {
    if (view === 'documents' && selectedFolder) {
      fetchPlaylistStatus(selectedFolder.id)
    }
    return () => {
      if (playlistPollingRef.current) {
        clearInterval(playlistPollingRef.current)
        playlistPollingRef.current = null
      }
    }
  }, [view, selectedFolder])

  const StatusBadge = ({ status }) => {
    const statusConfig = {
      uploaded: { color: '#94a3b8', label: 'Uploadé', bg: darkMode ? '#334155' : '#f1f5f9' },
      processing: { color: '#f59e0b', label: 'En cours...', bg: darkMode ? '#78350f' : '#fef3c7' },
      done: { color: '#22c55e', label: 'Terminé', bg: darkMode ? '#14532d' : '#dcfce7' },
      error: { color: '#ef4444', label: 'Erreur', bg: darkMode ? '#7f1d1d' : '#fee2e2' },
    }
    const config = statusConfig[status] || statusConfig.uploaded
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
        style={{ backgroundColor: config.bg, color: config.color }}
      >
        <span
          className={`size-1.5 rounded-full ${status === 'processing' ? 'animate-pulse' : ''}`}
          style={{ backgroundColor: config.color }}
        />
        {config.label}
      </span>
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className="rounded-2xl shadow-2xl w-full overflow-hidden"
        style={{ maxWidth: '900px', maxHeight: '90vh', backgroundColor: colors.cardBg }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: colors.border, backgroundColor: '#8B5CF6' }}>
          <div className="flex items-center gap-3 text-white">
            <Icon name="folder_special" className="text-2xl" />
            <h3 className="text-lg font-bold">
              {view === 'folders' ? `Cours - ${platformName}` : selectedFolder?.name}
            </h3>
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
          {view === 'folders' ? (
            <>
              {showCreateFolderForm ? (
                <form
                  onSubmit={handleCreateFolderSubmit}
                  className="mb-6 rounded-2xl border p-4"
                  style={{
                    backgroundColor: colors.innerBg,
                    borderColor: colors.border,
                  }}
                >
                  <div className="mb-3 flex items-center gap-2" style={{ color: colors.text }}>
                    <Icon name="create_new_folder" className="text-xl" style={{ color: '#8B5CF6' }} />
                    <p className="text-sm font-semibold">Créer un nouveau cours</p>
                  </div>
                  <input
                    ref={createFolderInputRef}
                    type="text"
                    value={newFolderName}
                    onChange={(e) => {
                      setNewFolderName(e.target.value)
                      if (createFolderError) setCreateFolderError('')
                    }}
                    placeholder="Nom du cours"
                    className="w-full rounded-xl border px-4 py-3 text-sm outline-none transition-colors"
                    style={{
                      backgroundColor: colors.cardBg,
                      borderColor: createFolderError ? '#ef4444' : colors.border,
                      color: colors.text,
                    }}
                  />
                  {createFolderError && (
                    <p className="mt-2 text-xs font-medium" style={{ color: '#ef4444' }}>
                      {createFolderError}
                    </p>
                  )}
                  <div className="mt-4 flex justify-end gap-3">
                    <button
                      type="button"
                      onClick={handleCancelCreateFolder}
                      className="rounded-xl px-4 py-2.5 text-sm font-medium transition-colors"
                      style={{
                        backgroundColor: colors.cardBg,
                        border: `1px solid ${colors.border}`,
                        color: colors.textSecondary,
                      }}
                    >
                      Annuler
                    </button>
                    <button
                      type="submit"
                      disabled={creatingFolder}
                      className="rounded-xl px-4 py-2.5 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                      style={{ backgroundColor: '#8B5CF6' }}
                    >
                      {creatingFolder ? 'Création...' : 'Créer le cours'}
                    </button>
                  </div>
                </form>
              ) : (
                <button
                  onClick={handleCreateFolder}
                  className="mb-6 flex w-full items-center justify-center gap-2 rounded-xl px-4 py-4 text-sm font-medium transition-colors border-2"
                  style={{
                    backgroundColor: colors.innerBg,
                    borderColor: colors.border,
                    color: colors.textSecondary,
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.borderColor = '#8B5CF6'}
                  onMouseLeave={(e) => e.currentTarget.style.borderColor = colors.border}
                >
                  <Icon name="add" className="text-xl" />
                  Nouveau cours
                </button>
              )}

              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-600 border-t-purple-500" />
                </div>
              ) : folders.length === 0 ? (
                <div className="py-12 text-center" style={{ color: colors.textMuted }}>
                  <Icon name="folder_off" className="text-5xl mb-3" />
                  <p className="text-sm">Aucun cours pour le moment</p>
                  <p className="text-xs mt-1">Créez un nouveau cours pour commencer</p>
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  {folders.map((folder) => (
                    <div
                      key={folder.id}
                      onClick={() => handleOpenFolder(folder)}
                      className="group relative rounded-2xl p-5 transition-all cursor-pointer"
                      style={{
                        backgroundColor: colors.innerBg,
                        border: `1px solid ${colors.border}`,
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = '#8B5CF6'
                        e.currentTarget.style.transform = 'translateY(-2px)'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = colors.border
                        e.currentTarget.style.transform = 'translateY(0)'
                      }}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-2">
                            <Icon name="folder" style={{ color: '#8B5CF6' }} />
                            <h4 className="font-semibold truncate" style={{ color: colors.text }}>
                              {folder.name}
                            </h4>
                          </div>
                          <p className="text-sm" style={{ color: colors.textMuted }}>
                            {folder.document_count || 0} document{folder.document_count !== 1 ? 's' : ''}
                          </p>
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDeleteFolder(folder.id, folder.name)
                          }}
                          className="opacity-0 group-hover:opacity-100 transition-all p-2 rounded-full hover:bg-red-100"
                          style={{ color: '#ef4444' }}
                        >
                          <Icon name="delete" className="text-sm" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              {/* Breadcrumb / Back */}
              <button
                onClick={handleBackToFolders}
                className="mb-6 flex items-center gap-2 text-sm font-medium transition-colors"
                style={{
                  color: colors.textSecondary,
                }}
                onMouseEnter={(e) => e.currentTarget.style.color = '#8B5CF6'}
                onMouseLeave={(e) => e.currentTarget.style.color = colors.textSecondary}
              >
                <Icon name="arrow_back" />
                Retour aux cours
              </button>

              {/* Drag & drop zone */}
              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`mb-6 rounded-2xl p-8 text-center transition-all cursor-pointer border-2 ${
                  dragOver ? 'border-purple-500' : ''
                }`}
                style={{
                  backgroundColor: dragOver ? darkMode ? '#312e81' : '#ede9fe' : colors.innerBg,
                  borderColor: dragOver ? '' : colors.border,
                }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  multiple
                  onChange={handleFileSelect}
                  className="hidden"
                />
                {uploading ? (
                  <div className="flex items-center justify-center gap-3" style={{ color: colors.textSecondary }}>
                    <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-400 border-t-purple-500" />
                    <span className="text-sm">Upload en cours...</span>
                  </div>
                ) : (
                  <>
                    <Icon name="cloud_upload" className="text-5xl mb-3" style={{ color: '#8B5CF6' }} />
                    <p className="text-base font-medium mb-1" style={{ color: colors.text }}>
                      Glissez-déposez vos PDFs ici
                    </p>
                    <p className="text-sm" style={{ color: colors.textMuted }}>
                      ou cliquez pour parcourir
                    </p>
                  </>
                )}
              </div>

              {/* Boutons de génération */}
              <div className="mb-6 flex gap-3">
                {documents.some(d => d.status !== 'done') && (
                  <button
                    onClick={handleGenerateAll}
                    disabled={generatingAll}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{
                      backgroundColor: colors.innerBg,
                      border: `1px solid ${colors.border}`,
                      color: colors.textSecondary,
                    }}
                  >
                    <Icon name="graphic_eq" className="text-lg" />
                    {generatingAll ? 'En cours...' : 'Générer audios individuels'}
                  </button>
                )}
                {documents.length > 0 && (
                  <button
                    onClick={handleGeneratePlaylist}
                    disabled={playlistJob?.status === 'running'}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{
                      backgroundColor: '#8B5CF6',
                      color: 'white',
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#7c3aed'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#8B5CF6'}
                  >
                    <Icon name="auto_awesome" className="text-lg" />
                    {playlistJob?.status === 'running' ? 'Pipeline en cours...' : 'Générer la playlist (19 MP3)'}
                  </button>
                )}
              </div>

              {/* Progression pipeline playlist */}
              {playlistJob?.status === 'running' && (
                <div className="mb-6 rounded-2xl p-4" style={{ backgroundColor: darkMode ? '#312e81' : '#ede9fe', border: `1px solid ${darkMode ? '#4c1d95' : '#c4b5fd'}` }}>
                  <div className="flex items-center gap-3 mb-3">
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-purple-300 border-t-purple-600" />
                    <p className="text-sm font-medium" style={{ color: darkMode ? '#c4b5fd' : '#6d28d9' }}>
                      Pipeline en cours — {playlistJob.message}
                    </p>
                  </div>
                  <div className="w-full rounded-full h-2" style={{ backgroundColor: darkMode ? '#1e1b4b' : '#ddd6fe' }}>
                    <div
                      className="h-2 rounded-full transition-all"
                      style={{
                        width: `${Math.round((playlistJob.step / playlistJob.total_steps) * 100)}%`,
                        backgroundColor: '#8B5CF6',
                      }}
                    />
                  </div>
                  <p className="text-xs mt-2" style={{ color: darkMode ? '#a78bfa' : '#7c3aed' }}>
                    Étape {playlistJob.step}/{playlistJob.total_steps}
                  </p>
                </div>
              )}

              {/* Résultat pipeline terminée */}
              {playlistJob?.status === 'completed' && playlistJob.result && (
                <div className="mb-6 rounded-2xl p-4" style={{ backgroundColor: darkMode ? '#14532d' : '#dcfce7', border: `1px solid ${darkMode ? '#166534' : '#86efac'}` }}>
                  <div className="flex items-center gap-2 mb-2">
                    <Icon name="check_circle" style={{ color: '#22c55e' }} />
                    <p className="text-sm font-bold" style={{ color: darkMode ? '#86efac' : '#166534' }}>
                      Playlist générée : {playlistJob.result.generated}/19 fichiers
                      {playlistJob.result.errors > 0 && ` (${playlistJob.result.errors} erreur(s))`}
                    </p>
                  </div>
                  <div className="flex items-center gap-4 flex-wrap text-xs" style={{ color: darkMode ? '#86efac' : '#166534' }}>
                    <span className="flex items-center gap-1">
                      <Icon name="menu_book" className="text-sm" />
                      {playlistJob.result.filled_blocs || '?'}/7 blocs remplis
                    </span>
                    {playlistJob.result.total_duration_hours > 0 && (
                      <span className="flex items-center gap-1">
                        <Icon name="schedule" className="text-sm" />
                        {playlistJob.result.total_duration_hours}h
                      </span>
                    )}
                    {playlistJob.result.total_size_mb > 0 && (
                      <span className="flex items-center gap-1">
                        <Icon name="storage" className="text-sm" />
                        {playlistJob.result.total_size_mb} Mo
                      </span>
                    )}
                  </div>
                  {playlistJob.result.skipped > 0 && (
                    <p className="text-xs mt-2" style={{ color: darkMode ? '#fbbf24' : '#92400e' }}>
                      {playlistJob.result.skipped} fichier(s) non générés (contenu source insuffisant pour les blocs {playlistJob.result.skipped_blocs?.join(', ')})
                    </p>
                  )}
                  {playlistJob.result.remaining_source_words > 50 && (
                    <p className="text-xs mt-1" style={{ color: darkMode ? '#fbbf24' : '#92400e' }}>
                      ~{playlistJob.result.remaining_source_words} mots de contenu source non utilisés (surplus)
                    </p>
                  )}
                  <button
                    onClick={handleViewScript}
                    disabled={loadingScript}
                    className="mt-3 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50"
                    style={{ backgroundColor: darkMode ? '#166534' : '#bbf7d0', color: darkMode ? '#86efac' : '#166534' }}
                  >
                    <Icon name="article" className="text-sm" />
                    {loadingScript ? 'Chargement...' : 'Voir le script reformulé'}
                  </button>
                </div>
              )}

              {/* Bouton voir script même sans pipeline en cours */}
              {(!playlistJob || playlistJob.status !== 'running') && !playlistJob?.result && (
                <button
                  onClick={handleViewScript}
                  disabled={loadingScript}
                  className="mb-4 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50"
                  style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}`, color: colors.textMuted }}
                >
                  <Icon name="article" className="text-sm" />
                  {loadingScript ? 'Chargement...' : 'Voir le dernier script'}
                </button>
              )}

              {/* Erreur pipeline */}
              {playlistJob?.status === 'error' && (
                <div className="mb-6 rounded-2xl p-4" style={{ backgroundColor: darkMode ? '#7f1d1d' : '#fee2e2', border: `1px solid ${darkMode ? '#991b1b' : '#fca5a5'}` }}>
                  <div className="flex items-center gap-2">
                    <Icon name="error" style={{ color: '#ef4444' }} />
                    <p className="text-sm font-medium" style={{ color: '#ef4444' }}>
                      Erreur : {playlistJob.message}
                    </p>
                  </div>
                </div>
              )}

              {/* Liste des documents */}
              <div className="space-y-3 max-h-80 overflow-y-auto pr-2">
                {documents.length === 0 ? (
                  <div className="py-12 text-center" style={{ color: colors.textMuted }}>
                    <Icon name="description" className="text-5xl mb-3" />
                    <p className="text-sm">Aucun document dans ce cours</p>
                    <p className="text-xs mt-1">Déposez des PDFs pour commencer</p>
                  </div>
                ) : (
                  documents.map((doc) => (
                    <div
                      key={doc.id}
                      className="rounded-2xl p-4 transition-all"
                      style={{
                        backgroundColor: colors.innerBg,
                        border: `1px solid ${colors.border}`,
                      }}
                    >
                      <div className="flex items-start gap-3">
                        <Icon
                          name="picture_as_pdf"
                          className="text-3xl flex-shrink-0 mt-0.5"
                          style={{ color: '#dc2626' }}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-3 flex-wrap">
                            <p className="font-medium truncate text-sm" style={{ color: colors.text }}>
                              {doc.original_name}
                            </p>
                            <StatusBadge status={doc.status} />
                          </div>
                          <div className="flex items-center gap-2 flex-wrap">
                            <button
                              onClick={() => handleDownloadPdf(doc.id)}
                              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
                              style={{
                                backgroundColor: colors.hoverBg,
                                color: colors.textSecondary,
                              }}
                            >
                              <Icon name="download" className="text-sm" />
                              PDF
                            </button>
                            {doc.audio_filename && (
                              <button
                                onClick={() => handleDownloadAudio(doc.id)}
                                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
                                style={{
                                  backgroundColor: darkMode ? '#14532d' : '#dcfce7',
                                  color: '#22c55e',
                                }}
                              >
                                <Icon name="headphones" className="text-sm" />
                                Audio
                              </button>
                            )}
                            {!doc.audio_filename && doc.status !== 'processing' && doc.status !== 'error' && (
                              <button
                                onClick={() => handleGenerateAudio(doc.id)}
                                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
                                style={{
                                  backgroundColor: darkMode ? '#312e81' : '#ede9fe',
                                  color: '#8B5CF6',
                                }}
                              >
                                <Icon name="play_arrow" className="text-sm" />
                                Générer
                              </button>
                            )}
                            <button
                              onClick={() => handleDeleteDocument(doc.id, doc.original_name)}
                              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
                              style={{
                                backgroundColor: darkMode ? '#7f1d1d' : '#fee2e2',
                                color: '#ef4444',
                              }}
                            >
                              <Icon name="delete" className="text-sm" />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* Statut global */}
              {ttsStatus?.counts && (
                <div className="mt-6 pt-4 border-t rounded-xl p-4" style={{ borderColor: colors.border, backgroundColor: colors.innerBg }}>
                  <p className="text-xs font-medium mb-3" style={{ color: colors.textMuted }}>STATUT GLOBAL</p>
                  <div className="flex items-center gap-6 text-sm">
                    <span style={{ color: colors.textSecondary }}>
                      <span className="font-bold text-base">{ttsStatus.counts.uploaded || 0}</span> uploadés
                    </span>
                    <span style={{ color: colors.textSecondary }}>
                      <span className="font-bold text-base" style={{ color: '#f59e0b' }}>{ttsStatus.counts.processing || 0}</span> en cours
                    </span>
                    <span style={{ color: colors.textSecondary }}>
                      <span className="font-bold text-base" style={{ color: '#22c55e' }}>{ttsStatus.counts.done || 0}</span> terminés
                    </span>
                    {ttsStatus.counts.error > 0 && (
                      <span style={{ color: '#ef4444' }}>
                        <span className="font-bold text-base">{ttsStatus.counts.error}</span> erreurs
                      </span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Modale script reformulé */}
      {scriptModal && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}
          onClick={() => setScriptModal(null)}
        >
          <div
            className="w-full overflow-hidden rounded-2xl shadow-2xl flex flex-col"
            style={{ maxWidth: '800px', maxHeight: '90vh', backgroundColor: colors.cardBg }}
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0" style={{ borderColor: colors.border, backgroundColor: '#8B5CF6' }}>
              <div className="flex items-center gap-3 text-white">
                <Icon name="article" className="text-2xl" />
                <div>
                  <h3 className="text-lg font-bold">Script reformulé par Claude</h3>
                  <p className="text-xs text-purple-200">
                    {scriptModal.filled_blocs}/7 blocs · {scriptModal.source_words} mots source
                    {scriptModal.remaining_source_words > 50 && ` · ${scriptModal.remaining_source_words} mots surplus`}
                  </p>
                </div>
              </div>
              <button onClick={() => setScriptModal(null)} className="text-white hover:bg-white/20 rounded-full p-1">
                <Icon name="close" className="text-2xl" />
              </button>
            </div>

            {/* Contenu scrollable */}
            <div className="overflow-y-auto p-6 space-y-6">
              {scriptModal.blocs?.map(bloc => (
                <div key={bloc.bloc_number} className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
                  <div
                    className="flex items-center justify-between px-4 py-3"
                    style={{ backgroundColor: bloc.skipped ? (darkMode ? '#7f1d1d' : '#fee2e2') : (darkMode ? '#1e293b' : '#f8fafc') }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold" style={{ color: bloc.skipped ? '#ef4444' : '#8B5CF6' }}>
                        Bloc {bloc.bloc_number}
                      </span>
                      <span className="text-xs" style={{ color: colors.textMuted }}>
                        {COURS_DURATIONS_MAP[bloc.bloc_number]}min
                      </span>
                      {bloc.skipped ? (
                        <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: '#fee2e2', color: '#ef4444' }}>Vide</span>
                      ) : (
                        <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: darkMode ? '#312e81' : '#ede9fe', color: '#8B5CF6' }}>
                          {bloc.word_count} mots / {bloc.target_words} cible
                        </span>
                      )}
                    </div>
                  </div>
                  {!bloc.skipped && bloc.content && (
                    <div className="px-4 py-4" style={{ backgroundColor: colors.innerBg }}>
                      <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: colors.text, fontFamily: 'monospace', fontSize: '12px' }}>
                        {bloc.content}
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {deleteConfirm && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
          onClick={() => {
            if (!deletingItem) {
              setDeleteConfirm(null)
              setDeleteError('')
            }
          }}
        >
          <div
            className="w-full max-w-md overflow-hidden rounded-2xl shadow-2xl"
            style={{ backgroundColor: colors.cardBg }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="border-b px-6 py-4"
              style={{ borderColor: colors.border, backgroundColor: darkMode ? '#3f1d70' : '#8B5CF6' }}
            >
              <div className="flex items-center gap-3 text-white">
                <Icon name="delete" className="text-2xl" />
                <h3 className="text-lg font-bold">
                  {deleteConfirm.type === 'folder' ? 'Supprimer ce cours ?' : 'Supprimer ce document ?'}
                </h3>
              </div>
            </div>
            <div className="p-6">
              <p className="text-sm leading-6" style={{ color: colors.textSecondary }}>
                {deleteConfirm.type === 'folder' ? (
                  <>
                    Le cours <strong>{deleteConfirm.folderName}</strong> et tous ses documents seront supprimés.
                  </>
                ) : (
                  <>
                    Le document <strong>{deleteConfirm.documentName}</strong> et son audio seront supprimés.
                  </>
                )}{' '}
                Cette action est irréversible.
              </p>

              {deleteError && (
                <p
                  className="mt-4 rounded-xl px-3 py-2 text-xs font-medium"
                  style={{ backgroundColor: darkMode ? '#7f1d1d' : '#fee2e2', color: '#ef4444' }}
                >
                  {deleteError}
                </p>
              )}

              <div className="mt-6 flex gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setDeleteConfirm(null)
                    setDeleteError('')
                  }}
                  disabled={deletingItem}
                  className="flex-1 rounded-xl px-4 py-2.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                  style={{
                    backgroundColor: colors.innerBg,
                    border: `1px solid ${colors.border}`,
                    color: colors.textSecondary,
                  }}
                >
                  Annuler
                </button>
                <button
                  type="button"
                  onClick={confirmDelete}
                  disabled={deletingItem}
                  className="flex-1 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                  style={{ backgroundColor: '#dc2626' }}
                >
                  {deletingItem ? 'Suppression...' : 'Supprimer'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
