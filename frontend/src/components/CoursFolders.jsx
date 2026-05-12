import { useState, useEffect, useRef } from 'react'
import { apiUrl } from '../api'
import AudioEditor from './AudioEditor'

// ─── Material Icon Component ─────────────────────────────────────────────────
const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`}>{name}</span>
)

const hasCrCdTitle = (title = '') => /\bCRCD\b/i.test(title)

const COURS_DURATIONS_MAP = { 1: 45, 2: 45, 3: 55, 4: 45, 5: 60, 6: 60, 7: 50 }

const AUDIO_PLAYLIST_ITEMS = [
  { filename: 'cours_9h00_9h45.mp3', type: 'cours', label: '9h00 → 9h45' },
  { filename: 'qa_9h45_9h55.mp3', type: 'qa', label: '9h45 → 9h55' },
  { filename: 'pause_9h55_10h05.mp3', type: 'pause', label: '9h55 → 10h05' },
  { filename: 'cours_10h05_10h50.mp3', type: 'cours', label: '10h05 → 10h50' },
  { filename: 'qa_10h50_11h00.mp3', type: 'qa', label: '10h50 → 11h00' },
  { filename: 'pause_11h00_11h05.mp3', type: 'pause', label: '11h00 → 11h05' },
  { filename: 'cours_11h05_12h00.mp3', type: 'cours', label: '11h05 → 12h00' },
  { filename: 'qa_12h00_12h10.mp3', type: 'qa', label: '12h00 → 12h10' },
  { filename: 'pause_12h10_12h20.mp3', type: 'pause', label: '12h10 → 12h20' },
  { filename: 'pause_midi_13h15_14h45.mp3', type: 'pause', label: 'Midi 13h15 → 14h45' },
  { filename: 'cours_12h20_13h05.mp3', type: 'cours', label: '12h20 → 13h05' },
  { filename: 'qa_13h05_13h15.mp3', type: 'qa', label: '13h05 → 13h15' },
  { filename: 'cours_14h45_15h45.mp3', type: 'cours', label: '14h45 → 15h45' },
  { filename: 'qa_15h45_16h00.mp3', type: 'qa', label: '15h45 → 16h00' },
  { filename: 'cours_16h00_17h00.mp3', type: 'cours', label: '16h00 → 17h00' },
  { filename: 'qa_17h00_17h15.mp3', type: 'qa', label: '17h00 → 17h15' },
  { filename: 'pause_17h15_17h25.mp3', type: 'pause', label: '17h15 → 17h25' },
  { filename: 'cours_17h25_18h15.mp3', type: 'cours', label: '17h25 → 18h15' },
  { filename: 'qa_18h15_18h30.mp3', type: 'qa', label: '18h15 → 18h30' },
]

const AUDIO_FILTERS = [
  { value: 'cours', label: 'Cours' },
  { value: 'qa', label: 'Q&A' },
  { value: 'pause', label: 'Pauses' },
  { value: 'all', label: 'Tous' },
]

const AUDIO_TYPE_META = {
  cours: { label: 'Cours', icon: 'record_voice_over', color: '#16a34a', lightBg: '#f0fdf4', darkBg: '#14532d22', lightBorder: '#bbf7d0', darkBorder: '#166534' },
  qa: { label: 'Q&A', icon: 'forum', color: '#2563eb', lightBg: '#eff6ff', darkBg: '#1d4ed822', lightBorder: '#bfdbfe', darkBorder: '#1d4ed8' },
  pause: { label: 'Pause', icon: 'free_breakfast', color: '#f59e0b', lightBg: '#fffbeb', darkBg: '#92400e22', lightBorder: '#fde68a', darkBorder: '#b45309' },
}

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
  const [wordAnalysis, setWordAnalysis] = useState(null) // résultat analyse mots
  const [analysing, setAnalysing] = useState(false)
  const [generatedAudios, setGeneratedAudios] = useState([]) // MP3 générés du dossier
  const [dragFolderIdx, setDragFolderIdx] = useState(null)
  const [dragOverFolderIdx, setDragOverFolderIdx] = useState(null)
  // ── Génération de contenu ──
  const [contentJob, setContentJob] = useState(null)
  const [programText, setProgramText] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [showPromptPreview, setShowPromptPreview] = useState(false)
  const [promptPreview, setPromptPreview] = useState(null)
  const [contentScriptModal, setContentScriptModal] = useState(null)
  const [scriptAnnotations, setScriptAnnotations] = useState([])
  const [scriptSelection, setScriptSelection] = useState(null)
  const [annotationComment, setAnnotationComment] = useState('')
  const [annotationError, setAnnotationError] = useState('')
  const [savingAnnotation, setSavingAnnotation] = useState(false)
  const [scriptRules, setScriptRules] = useState(null)
  const [rulesPanelOpen, setRulesPanelOpen] = useState(false)
  const [extractingRules, setExtractingRules] = useState(false)
  const [rulesError, setRulesError] = useState('')
  const [reviewingRules, setReviewingRules] = useState(false)
  const [rulesReviewSummary, setRulesReviewSummary] = useState(null)
  const [loadingContentScript, setLoadingContentScript] = useState(false)
  const [, setLoadingScript] = useState(false)
  const [contentScriptView, setContentScriptView] = useState('source') // 'source' | 'courses'
  const [scriptActiveSubPart, setScriptActiveSubPart] = useState(0)
  const [scriptActiveCourse, setScriptActiveCourse] = useState(1)
  const [scriptActiveBreak, setScriptActiveBreak] = useState(null)
  const [editingSegment, setEditingSegment] = useState(null) // {sub_part_index, passe}
  const [editText, setEditText] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)
  const [dirtyBlocs, setDirtyBlocs] = useState(null) // {dirty_blocs, total_blocs, has_script}
  const [audioEditorFile, setAudioEditorFile] = useState(null) // filename ouvert dans l'éditeur
  const [audioTypeFilter, setAudioTypeFilter] = useState('cours')
  const [mockUploading, setMockUploading] = useState(false)
  const [mockUploadQueue, setMockUploadQueue] = useState([]) // [{name, status, error}]
  const contentPollingRef = useRef(null)
  const fileInputRef = useRef(null)
  const mockAudioInputRef = useRef(null)
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
    bg: '#F8F7F5',
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

  // ─── Génération de contenu TTS-direct ─────────────────────────────────
  const fetchContentJob = async (folderId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${folderId}/content-job`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) setContentJob(data.job)
    } catch (e) { console.error('Erreur fetchContentJob:', e) }
  }

  const startContentPolling = (folderId) => {
    if (contentPollingRef.current) return
    contentPollingRef.current = setInterval(async () => {
      try {
        const resp = await fetch(apiUrl(`/api/hr/cours-folders/${folderId}/content-job`), { credentials: 'include' })
        const data = await resp.json()
        if (data.success) {
          setContentJob(data.job)
          if (data.job?.status !== 'running') {
            clearInterval(contentPollingRef.current)
            contentPollingRef.current = null
            if (data.job?.status === 'completed') fetchDocuments(folderId)
          }
        }
      } catch (e) { console.error('Erreur polling contenu:', e) }
    }, 3000)
  }

  const stopContentPolling = () => {
    if (contentPollingRef.current) {
      clearInterval(contentPollingRef.current)
      contentPollingRef.current = null
    }
  }

  const handleExtractSubParts = async () => {
    if (!programText.trim() || !selectedFolder) return
    setExtracting(true)
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ program_text: programText }),
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        await fetchContentJob(selectedFolder.id)
      } else {
        alert(data.error || "Erreur lors de l'extraction")
      }
    } catch (e) {
      console.error('Erreur extraction:', e)
      alert('Erreur réseau lors de l\'extraction')
    } finally {
      setExtracting(false)
    }
  }

  const handleStartContentGeneration = async (mode = 'normal') => {
    if (!selectedFolder) return
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/start`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        setContentJob(prev => ({ ...prev, status: 'running' }))
        startContentPolling(selectedFolder.id)
      } else {
        alert(data.error || 'Erreur lors du lancement')
      }
    } catch (e) {
      console.error('Erreur start generation:', e)
    }
  }

  const handleCancelContentGeneration = async () => {
    if (!selectedFolder) return
    stopContentPolling()
    try {
      await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/cancel`), {
        method: 'POST',
        credentials: 'include',
      })
      await fetchContentJob(selectedFolder.id)
    } catch (e) { console.error('Erreur cancel:', e) }
  }

  const handlePreviewPrompt = async () => {
    if (!selectedFolder) return
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/preview`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setPromptPreview(data.prompt_preview)
        setShowPromptPreview(true)
      }
    } catch (e) { console.error('Erreur preview:', e) }
  }

  const handleViewContentScript = async () => {
    if (!selectedFolder) return
    setLoadingContentScript(true)
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/script`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setContentScriptModal(data)
        setScriptAnnotations(data.annotations || [])
        setScriptSelection(null)
        setAnnotationComment('')
        setAnnotationError('')
        setContentScriptView('source')
        setScriptActiveSubPart(0)
        setScriptActiveCourse(data.course_blocs?.[0]?.bloc_number || 1)
        setScriptActiveBreak(null)
        setEditingSegment(null)
        setRulesPanelOpen(false)
        setRulesError('')
        loadScriptRules()
      } else {
        alert(data.error || 'Script non disponible')
      }
    } catch (e) { console.error('Erreur script:', e) }
    finally { setLoadingContentScript(false) }
  }

  const resetScriptAnnotationDraft = () => {
    setScriptSelection(null)
    setAnnotationComment('')
    setAnnotationError('')
  }

  const closeContentScriptModal = () => {
    setContentScriptModal(null)
    setEditingSegment(null)
    resetScriptAnnotationDraft()
    setScriptAnnotations([])
  }

  const captureScriptSelection = (event, context) => {
    const selection = window.getSelection()
    const rawText = selection?.toString() || ''
    const selectedText = rawText.replace(/\s+/g, ' ').trim()

    if (!selectedText || selectedText.length < 3) return
    if (
      selection?.anchorNode &&
      selection?.focusNode &&
      (!event.currentTarget.contains(selection.anchorNode) || !event.currentTarget.contains(selection.focusNode))
    ) {
      return
    }

    const containerText = (event.currentTarget?.textContent || '').replace(/\s+/g, ' ').trim()
    setScriptSelection({
      ...context,
      selected_text: selectedText.slice(0, 4000),
      paragraph_context: containerText.slice(0, 8000),
    })
    setAnnotationComment('')
    setAnnotationError('')
  }

  const saveScriptAnnotation = async () => {
    if (!selectedFolder || !scriptSelection || savingAnnotation) return
    const comment = annotationComment.trim()
    if (!comment) {
      setAnnotationError('Ajoutez le commentaire de correction.')
      return
    }

    setSavingAnnotation(true)
    setAnnotationError('')
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/annotations`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_type: scriptSelection.source_type,
          sub_part_index: scriptSelection.sub_part_index,
          passe: scriptSelection.passe,
          bloc_number: scriptSelection.bloc_number,
          filename: scriptSelection.filename,
          selected_text: scriptSelection.selected_text,
          paragraph_context: scriptSelection.paragraph_context || '',
          comment,
        }),
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        setScriptAnnotations(data.annotations || [])
        setContentScriptModal(prev => prev ? {
          ...prev,
          annotations: data.annotations || [],
          annotations_count: data.annotations_count || 0,
          annotations_markdown_path: data.markdown_path,
        } : prev)
        resetScriptAnnotationDraft()
        window.getSelection()?.removeAllRanges()
      } else {
        setAnnotationError(data.error || 'Annotation impossible.')
      }
    } catch (e) {
      console.error('Erreur annotation script:', e)
      setAnnotationError('Erreur réseau pendant la sauvegarde.')
    } finally {
      setSavingAnnotation(false)
    }
  }

  const deleteScriptAnnotation = async (annotationId) => {
    if (!selectedFolder || !annotationId) return
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/annotations/${annotationId}`), {
        method: 'DELETE',
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        setScriptAnnotations(data.annotations || [])
        setContentScriptModal(prev => prev ? {
          ...prev,
          annotations: data.annotations || [],
          annotations_count: data.annotations_count || 0,
          annotations_markdown_path: data.markdown_path,
        } : prev)
      }
    } catch (e) {
      console.error('Erreur suppression annotation:', e)
    }
  }

  const downloadAnnotationsMarkdown = () => {
    if (!selectedFolder) return
    window.open(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/annotations/markdown`), '_blank')
  }

  const loadScriptRules = async () => {
    if (!selectedFolder) return
    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/rules`),
        { credentials: 'include' }
      )
      const data = await resp.json()
      if (data.success) setScriptRules(data)
    } catch (e) {
      console.error('Erreur chargement règles:', e)
    }
  }

  const extractScriptRules = async () => {
    if (!selectedFolder || extractingRules) return
    setExtractingRules(true)
    setRulesError('')
    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/rules/extract`),
        { method: 'POST', credentials: 'include' }
      )
      const data = await resp.json()
      if (data.success) {
        setScriptRules(data)
        setRulesPanelOpen(true)
      } else {
        setRulesError(data.error || 'Extraction impossible.')
      }
    } catch (e) {
      console.error('Erreur extract rules:', e)
      setRulesError('Erreur réseau pendant l\'extraction.')
    } finally {
      setExtractingRules(false)
    }
  }

  const downloadRulesMarkdown = () => {
    if (!selectedFolder) return
    window.open(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/rules/markdown`), '_blank')
  }

  const runRulesReview = async (dryRun) => {
    if (!selectedFolder || reviewingRules) return
    if (!dryRun) {
      const ok = window.confirm(
        'Cette action va lire les MP3 du dossier, vérifier chaque chunk audio contre les règles, et patcher en place les portions non conformes. Continuer ?'
      )
      if (!ok) return
    }
    setReviewingRules(true)
    setRulesError('')
    setRulesReviewSummary(null)
    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/rules/review-post-tts`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dry_run: !!dryRun }),
          credentials: 'include',
        }
      )
      const data = await resp.json()
      if (data.success) {
        setRulesReviewSummary(data)
      } else {
        setRulesError(data.error || 'Revérif impossible.')
      }
    } catch (e) {
      console.error('Erreur review post-tts:', e)
      setRulesError('Erreur réseau pendant la revérif.')
    } finally {
      setReviewingRules(false)
    }
  }

  const applyAnnotationCorrection = async (annotationId) => {
    if (!selectedFolder || !annotationId) return
    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/annotations/${annotationId}/apply`),
        { method: 'POST', credentials: 'include' }
      )
      const data = await resp.json()
      if (data.success) {
        setScriptAnnotations(data.annotations || [])
        setContentScriptModal(prev => prev ? {
          ...prev,
          annotations: data.annotations || [],
          annotations_count: data.annotations_count || 0,
          annotations_markdown_path: data.markdown_path,
        } : prev)
      }
    } catch (e) {
      console.error('Erreur apply annotation:', e)
    }
  }

  const rejectAnnotationCorrection = async (annotationId) => {
    if (!selectedFolder || !annotationId) return
    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/annotations/${annotationId}/reject`),
        { method: 'POST', credentials: 'include' }
      )
      const data = await resp.json()
      if (data.success) {
        setScriptAnnotations(data.annotations || [])
        setContentScriptModal(prev => prev ? {
          ...prev,
          annotations: data.annotations || [],
          annotations_count: data.annotations_count || 0,
          annotations_markdown_path: data.markdown_path,
        } : prev)
      }
    } catch (e) {
      console.error('Erreur reject annotation:', e)
    }
  }

  const handleStartEdit = (subIdx, passe, currentText) => {
    setEditingSegment({ sub_part_index: subIdx, passe })
    setEditText(currentText)
  }

  const handleCancelEdit = () => {
    setEditingSegment(null)
    setEditText('')
  }

  const handleSaveEdit = async () => {
    if (!selectedFolder || !editingSegment) return
    setSavingEdit(true)
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/content-job/segment`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sub_part_index: editingSegment.sub_part_index, passe: editingSegment.passe, text: editText }),
        credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) {
        // Mettre à jour le modal localement
        setContentScriptModal(prev => ({
          ...prev,
          total_words: data.new_total_words,
          sub_parts: prev.sub_parts.map(sp => {
            if (sp.index !== editingSegment.sub_part_index) return sp
            return {
              ...sp,
              total_words: sp.total_words - (sp.passes.find(p => p.passe === editingSegment.passe)?.word_count || 0) + data.new_word_count,
              passes: sp.passes.map(p =>
                p.passe === editingSegment.passe
                  ? { ...p, text: editText, word_count: data.new_word_count }
                  : p
              )
            }
          })
        }))
        setEditingSegment(null)
        setEditText('')
        // Rafraîchir le compteur de blocs dirty après modification
        fetchDirtyBlocs(selectedFolder.id)
      } else {
        alert(data.error || 'Erreur lors de la sauvegarde')
      }
    } catch (e) { console.error('Erreur save edit:', e) }
    finally { setSavingEdit(false) }
  }

  const fetchDirtyBlocs = async (folderId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${folderId}/content-job/dirty-blocs`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) setDirtyBlocs(data)
    } catch (e) { /* silencieux */ }
  }

  // ─── Drag & drop réordonnancement des dossiers ────────────────────────
  const handleFolderDragStart = (e, idx) => {
    setDragFolderIdx(idx)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleFolderDragOver = (e, idx) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (idx !== dragFolderIdx) setDragOverFolderIdx(idx)
  }

  const handleFolderDragLeave = () => {
    setDragOverFolderIdx(null)
  }

  const handleFolderDrop = async (e, dropIdx) => {
    e.preventDefault()
    setDragOverFolderIdx(null)
    if (dragFolderIdx === null || dragFolderIdx === dropIdx) {
      setDragFolderIdx(null)
      return
    }
    // Recalcule l'ordre local
    const reordered = [...folders]
    const [moved] = reordered.splice(dragFolderIdx, 1)
    reordered.splice(dropIdx, 0, moved)
    // Mise à jour optimiste
    setFolders(reordered)
    setDragFolderIdx(null)
    // Persistance côté serveur
    const order = reordered.map((f, i) => ({ id: f.id, position: i }))
    try {
      await fetch(apiUrl(`/api/hr/platforms/${platformId}/cours-folders/reorder`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order }),
        credentials: 'include',
      })
    } catch (e) {
      console.error('Erreur réordonnancement:', e)
      fetchFolders() // rollback en cas d'erreur
    }
  }

  const handleFolderDragEnd = () => {
    setDragFolderIdx(null)
    setDragOverFolderIdx(null)
  }

  const handleOpenFolder = (folder) => {
    setSelectedFolder(folder)
    setView('documents')
    setDocuments([])
    setTtsStatus(null)
    setWordAnalysis(null)
    setGeneratedAudios([])
    setContentJob(null)
    setProgramText('')
    stopContentPolling()
    fetchGeneratedAudios(folder.id)
    fetchContentJob(folder.id)
    fetchDirtyBlocs(folder.id)
  }

  const handleBackToFolders = () => {
    setView('folders')
    setSelectedFolder(null)
    setDocuments([])
    setTtsStatus(null)
    stopContentPolling()
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
    const allowed = files.filter(f => {
      const name = f.name.toLowerCase()
      return name.endsWith('.pdf') || name.endsWith('.txt') || name.endsWith('.md')
    })

    if (allowed.length === 0) {
      alert('Formats acceptés : PDF, TXT, Markdown (.md)')
      return
    }

    await uploadFiles(allowed)
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
          // Rafraîchir les audios générés une fois la pipeline terminée
          if (data.status === 'completed') fetchGeneratedAudios(folderId)
        }
      }
    } catch (e) {
      console.error('Erreur statut playlist:', e)
    }
  }

  const handleGeneratePlaylist = async ({ mock = false, scriptMock = false, forceAll = false } = {}) => {
    if (!selectedFolder) return
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/generate-playlist`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mock, script_mock: scriptMock, force_all: forceAll }),
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

  const fetchGeneratedAudios = async (folderId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${folderId}/generated-audios`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) setGeneratedAudios(data.audios)
    } catch (e) {
      console.error('Erreur chargement audios générés:', e)
    }
  }

  // ─── Mock upload (dev only) : copie les MP3 locaux depuis output_jour1 ──
  const handleMockAudioUpload = async () => {
    if (!selectedFolder || mockUploading) return

    // Garde-fou : si des audios existent déjà dans le dossier, demander confirmation
    const existingCours = generatedAudios.filter(a => a.filename?.startsWith('cours_'))
    if (existingCours.length > 0) {
      const confirmed = window.confirm(
        `⚠️ Attention\n\n` +
        `Ce dossier contient déjà ${existingCours.length} audio(s) de cours.\n` +
        `Si tu as fait des modifications (coupes, remplacements) sur ces audios, ` +
        `elles seront ÉCRASÉES par les fichiers originaux de output_jour1/.\n\n` +
        `Cette action est irréversible. Continuer ?`
      )
      if (!confirmed) return
    }

    setMockUploading(true)
    setMockUploadQueue([{ name: 'Lecture de output_jour1/...', status: 'uploading' }])

    try {
      const resp = await fetch(
        apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/mock-upload-local`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source_dir: 'output_jour1' }),
        }
      )
      const data = await resp.json()

      if (data.success) {
        const uploaded = (data.uploaded || []).map(u => ({
          name: `${u.filename} (${u.size_mb} Mo)`,
          status: 'done',
        }))
        const failed = (data.failed || []).map(f => ({
          name: f.filename,
          status: 'error',
          error: f.error,
        }))
        setMockUploadQueue([...uploaded, ...failed])
      } else {
        setMockUploadQueue([{ name: 'Erreur', status: 'error', error: data.error || 'Inconnue' }])
      }
    } catch (err) {
      setMockUploadQueue([{ name: 'Erreur réseau', status: 'error', error: err.message }])
    }

    await fetchGeneratedAudios(selectedFolder.id)
    setMockUploading(false)

    // Nettoyer la file après 6s
    setTimeout(() => setMockUploadQueue([]), 6000)
  }

  const handleAnalyse = async () => {
    if (!selectedFolder) return
    setAnalysing(true)
    setWordAnalysis(null)
    try {
      const resp = await fetch(apiUrl(`/api/hr/cours-folders/${selectedFolder.id}/analyse`), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setWordAnalysis(data)
      } else {
        alert(data.error || 'Erreur lors de l\'analyse')
      }
    } catch (e) {
      console.error('Erreur analyse:', e)
    } finally {
      setAnalysing(false)
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

  const annotationMatchesContext = (annotation, context) => {
    if (!annotation || !context || annotation.source_type !== context.source_type) return false
    if (context.source_type === 'segment') {
      return Number(annotation.sub_part_index) === Number(context.sub_part_index) &&
        Number(annotation.passe) === Number(context.passe)
    }
    if (context.source_type === 'course') {
      return Number(annotation.bloc_number) === Number(context.bloc_number)
    }
    return false
  }

  const annotationsForContext = (context) =>
    scriptAnnotations.filter(annotation => annotationMatchesContext(annotation, context))

  const formatAnnotationSource = (annotation) => {
    if (annotation.source_type === 'segment') {
      return `Sous-partie ${Number(annotation.sub_part_index) + 1} · passe ${annotation.passe}`
    }
    if (annotation.source_type === 'course') {
      return `Cours ${annotation.bloc_number}${annotation.filename ? ` · ${annotation.filename}` : ''}`
    }
    return 'Script TTS'
  }

  const ScriptAnnotationComposer = ({ context }) => {
    if (!scriptSelection || !annotationMatchesContext(scriptSelection, context)) return null
    return (
      <div
        className="mb-3 rounded-xl p-3"
        style={{
          backgroundColor: darkMode ? '#211a3b' : '#f5f3ff',
          border: `1px solid ${darkMode ? '#4c1d95' : '#c4b5fd'}`,
        }}
      >
        <div className="mb-2 flex items-start gap-2">
          <Icon name="rate_review" style={{ color: '#7c3aed', fontSize: '18px' }} />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold" style={{ color: darkMode ? '#ddd6fe' : '#5b21b6' }}>
              Sélection à annoter
            </p>
            <p className="mt-1 line-clamp-3 text-xs leading-relaxed" style={{ color: colors.textSecondary }}>
              “{scriptSelection.selected_text}”
            </p>
          </div>
          <button
            type="button"
            onClick={resetScriptAnnotationDraft}
            className="rounded-lg p-1 transition-colors"
            style={{ color: colors.textMuted }}
            title="Annuler l'annotation"
          >
            <Icon name="close" style={{ fontSize: '16px' }} />
          </button>
        </div>
        <textarea
          value={annotationComment}
          onChange={(e) => setAnnotationComment(e.target.value)}
          rows={3}
          className="w-full rounded-lg px-3 py-2 text-xs outline-none"
          placeholder="Ex. Ce passage ne va pas en introduction, le déplacer après le cadrage et reformuler l'accroche."
          style={{
            backgroundColor: colors.cardBg,
            color: colors.text,
            border: `1px solid ${annotationError ? '#dc2626' : colors.border}`,
          }}
        />
        <div className="mt-2 flex items-center justify-between gap-3">
          <p className="min-h-4 text-xs" style={{ color: annotationError ? '#dc2626' : colors.textMuted }}>
            {annotationError || 'Le markdown de revue est régénéré à la sauvegarde.'}
          </p>
          <button
            type="button"
            onClick={saveScriptAnnotation}
            disabled={savingAnnotation}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60"
            style={{ backgroundColor: '#7c3aed', color: 'white' }}
          >
            <Icon name="save" style={{ fontSize: '14px' }} />
            {savingAnnotation ? 'Sauvegarde...' : 'Noter'}
          </button>
        </div>
      </div>
    )
  }

  const correctionBadge = (status) => {
    const map = {
      pending: { label: 'Correction en cours…', bg: '#fef3c7', color: '#92400e' },
      proposed: { label: 'Proposition prête', bg: '#dbeafe', color: '#1e40af' },
      applied: { label: 'Appliquée', bg: '#dcfce7', color: '#166534' },
      rejected: { label: 'Rejetée', bg: '#fee2e2', color: '#991b1b' },
      error: { label: 'Erreur DeepSeek', bg: '#fee2e2', color: '#991b1b' },
    }
    return map[status] || map.pending
  }

  const ScriptAnnotationsList = ({ context }) => {
    const items = annotationsForContext(context)
    if (!items.length) return null
    return (
      <div className="mt-3 space-y-2">
        {items.map(annotation => {
          const status = annotation.correction_status || 'pending'
          const badge = correctionBadge(status)
          const canAct = status === 'proposed'
          return (
            <div
              key={annotation.id}
              className="rounded-lg p-3"
              style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}` }}
            >
              <div className="mb-1 flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <p className="text-xs font-semibold" style={{ color: colors.textSecondary }}>
                    {formatAnnotationSource(annotation)}
                  </p>
                  <span
                    className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                    style={{ backgroundColor: badge.bg, color: badge.color }}
                  >
                    {badge.label}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => deleteScriptAnnotation(annotation.id)}
                  className="rounded-md p-1 transition-colors"
                  style={{ color: colors.textMuted }}
                  title="Retirer cette annotation"
                >
                  <Icon name="delete" style={{ fontSize: '15px' }} />
                </button>
              </div>
              <p className="text-xs leading-relaxed" style={{ color: colors.text }}>
                {annotation.comment}
              </p>
              <p className="mt-2 line-clamp-2 text-xs leading-relaxed" style={{ color: colors.textMuted }}>
                “{annotation.selected_text}”
              </p>

              {status === 'applied' && annotation.splice_status && (
                <p
                  className="mt-2 text-[10px] font-semibold uppercase tracking-wide"
                  style={{
                    color: annotation.splice_status === 'done' ? '#166534'
                      : annotation.splice_status === 'error' ? '#991b1b'
                      : colors.textMuted,
                  }}
                >
                  {annotation.splice_status === 'done'
                    ? '🎯 MP3 patché ms-précis'
                    : annotation.splice_status === 'error'
                    ? `Splice échoué : ${annotation.splice_error || 'erreur'}`
                    : `Splice ${annotation.splice_status}`}
                </p>
              )}

              {(annotation.original_paragraph || annotation.proposed_text) && status !== 'pending' && (
                <div className="mt-3 grid gap-2 md:grid-cols-2">
                  <div
                    className="rounded-md p-2 text-[11px] leading-relaxed"
                    style={{ backgroundColor: '#fef9c3', color: '#713f12', border: '1px solid #fde047' }}
                  >
                    <p className="mb-1 text-[10px] font-bold uppercase tracking-wide">Avant</p>
                    <p className="whitespace-pre-wrap">{annotation.original_paragraph || annotation.selected_text}</p>
                  </div>
                  <div
                    className="rounded-md p-2 text-[11px] leading-relaxed"
                    style={{
                      backgroundColor: status === 'error' ? '#fee2e2' : '#dcfce7',
                      color: status === 'error' ? '#991b1b' : '#166534',
                      border: `1px solid ${status === 'error' ? '#fecaca' : '#86efac'}`,
                    }}
                  >
                    <p className="mb-1 text-[10px] font-bold uppercase tracking-wide">
                      {status === 'error' ? 'Erreur' : 'Après (DeepSeek)'}
                    </p>
                    <p className="whitespace-pre-wrap">
                      {status === 'error'
                        ? (annotation.correction_error || 'Correction indisponible.')
                        : (annotation.proposed_text || '—')}
                    </p>
                  </div>
                </div>
              )}

              {canAct && (
                <div className="mt-2 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => rejectAnnotationCorrection(annotation.id)}
                    className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors"
                    style={{ backgroundColor: colors.innerBg, color: colors.textSecondary, border: `1px solid ${colors.border}` }}
                  >
                    Rejeter
                  </button>
                  <button
                    type="button"
                    onClick={() => applyAnnotationCorrection(annotation.id)}
                    className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold text-white transition-colors"
                    style={{ backgroundColor: '#16a34a' }}
                  >
                    Appliquer
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>
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
                <>
                  <p className="text-xs mb-3 flex items-center gap-1.5" style={{ color: colors.textMuted }}>
                    <Icon name="drag_indicator" style={{ fontSize: '14px' }} />
                    Glissez les cours pour changer leur ordre chronologique
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                    {folders.map((folder, idx) => (
                      <div
                        key={folder.id}
                        draggable
                        onDragStart={(e) => handleFolderDragStart(e, idx)}
                        onDragOver={(e) => handleFolderDragOver(e, idx)}
                        onDragLeave={handleFolderDragLeave}
                        onDrop={(e) => handleFolderDrop(e, idx)}
                        onDragEnd={handleFolderDragEnd}
                        onClick={() => handleOpenFolder(folder)}
                        className="group relative rounded-2xl p-5 transition-all cursor-pointer select-none"
                        style={{
                          backgroundColor: colors.innerBg,
                          border: `2px solid ${dragOverFolderIdx === idx ? '#8B5CF6' : colors.border}`,
                          opacity: dragFolderIdx === idx ? 0.4 : 1,
                          transform: dragOverFolderIdx === idx ? 'scale(1.02)' : 'none',
                        }}
                        onMouseEnter={(e) => {
                          if (dragFolderIdx === null) {
                            e.currentTarget.style.borderColor = '#8B5CF6'
                            e.currentTarget.style.transform = 'translateY(-2px)'
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (dragFolderIdx === null) {
                            e.currentTarget.style.borderColor = colors.border
                            e.currentTarget.style.transform = 'translateY(0)'
                          }
                        }}
                      >
                        {hasCrCdTitle(folder.name) && (
                          <div
                            className="mb-4 overflow-hidden rounded-xl"
                            style={{
                              aspectRatio: '16 / 7.2',
                              border: `1px solid ${darkMode ? '#334155' : '#E4E4E4'}`,
                              backgroundColor: darkMode ? '#0f172a' : '#F8F7F5',
                            }}
                          >
                            <img
                              src="/tp-crcd-thumbnail.svg"
                              alt="TP CRCD"
                              className="h-full w-full object-cover"
                              draggable={false}
                            />
                          </div>
                        )}

                        {/* Badge Jour X */}
                        <div
                          className="absolute top-2 right-2 text-xs font-bold px-2 py-0.5 rounded-full"
                          style={{ backgroundColor: darkMode ? '#312e81' : '#ede9fe', color: '#8B5CF6' }}
                        >
                          Jour {idx + 1}
                        </div>

                        {/* Handle drag */}
                        <div
                          className="absolute top-2 left-2 opacity-0 group-hover:opacity-50 transition-opacity cursor-grab"
                          style={{ color: colors.textMuted }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Icon name="drag_indicator" style={{ fontSize: '16px' }} />
                        </div>

                        <div className="flex items-start justify-between mt-2">
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
                            className="opacity-0 group-hover:opacity-100 transition-all p-2 rounded-full hover:bg-red-100 mt-4"
                            style={{ color: '#ef4444' }}
                          >
                            <Icon name="delete" className="text-sm" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          ) : (
            <>
              {/* Breadcrumb / Back */}
              <button
                onClick={handleBackToFolders}
                className="mb-5 flex items-center gap-2 text-sm font-medium transition-colors"
                style={{ color: colors.textSecondary }}
                onMouseEnter={(e) => e.currentTarget.style.color = '#8B5CF6'}
                onMouseLeave={(e) => e.currentTarget.style.color = colors.textSecondary}
              >
                <Icon name="arrow_back" />
                Retour aux cours
              </button>

              {/* ── Deux panneaux côte à côte ── */}
              <div className="grid grid-cols-2 gap-4 mb-5">

                {/* ── Panneau gauche : Textes sources ── */}
                <div className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
                  <div className="px-4 py-3 flex items-center gap-2" style={{ backgroundColor: darkMode ? '#1e293b' : '#f1f5f9', borderBottom: `1px solid ${colors.border}` }}>
                    <Icon name="description" style={{ color: '#8B5CF6', fontSize: '18px' }} />
                    <span className="text-sm font-semibold" style={{ color: colors.text }}>Textes sources</span>
                    {documents.length > 0 && (
                      <span className="ml-auto text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: darkMode ? '#312e81' : '#ede9fe', color: '#8B5CF6' }}>
                        {documents.length}
                      </span>
                    )}
                  </div>

                  {/* Zone drag & drop */}
                  <div
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    onClick={() => fileInputRef.current?.click()}
                    className={`m-3 rounded-xl p-5 text-center transition-all cursor-pointer border-2 ${dragOver ? 'border-purple-500' : 'border-dashed'}`}
                    style={{
                      backgroundColor: dragOver ? (darkMode ? '#312e81' : '#ede9fe') : 'transparent',
                      borderColor: dragOver ? '#8B5CF6' : colors.border,
                    }}
                  >
                    <input ref={fileInputRef} type="file" accept=".pdf,.txt,.md" multiple onChange={handleFileSelect} className="hidden" />
                    {uploading ? (
                      <div className="flex items-center justify-center gap-2" style={{ color: colors.textSecondary }}>
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-400 border-t-purple-500" />
                        <span className="text-xs">Upload...</span>
                      </div>
                    ) : (
                      <>
                        <Icon name="cloud_upload" className="text-2xl" style={{ color: '#8B5CF6' }} />
                        <p className="text-xs mt-1" style={{ color: colors.textMuted }}>PDF, TXT ou MD</p>
                      </>
                    )}
                  </div>

                  {/* Liste des documents */}
                  <div className="px-3 pb-3 space-y-1.5 max-h-64 overflow-y-auto">
                    {documents.length === 0 ? (
                      <div className="py-6 text-center" style={{ color: colors.textMuted }}>
                        <p className="text-xs">Aucun fichier déposé</p>
                      </div>
                    ) : (
                      documents.map((doc) => {
                        const ext = doc.original_name?.split('.').pop()?.toLowerCase() || 'pdf'
                        const fileIcon = ext === 'pdf' ? 'picture_as_pdf' : ext === 'md' ? 'description' : 'article'
                        const fileColor = ext === 'pdf' ? '#dc2626' : ext === 'md' ? '#16a34a' : '#2563eb'
                        return (
                          <div
                            key={doc.id}
                            className="rounded-xl px-3 py-2.5 flex items-center gap-2.5 transition-all"
                            style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}` }}
                          >
                            <Icon name={fileIcon} style={{ color: fileColor, fontSize: '18px', flexShrink: 0 }} />
                            <div className="flex-1 min-w-0">
                              <p className="text-xs font-medium truncate" style={{ color: colors.text }}>{doc.original_name}</p>
                              <StatusBadge status={doc.status} />
                            </div>
                            <button
                              onClick={() => handleDeleteDocument(doc.id, doc.original_name)}
                              className="p-1 rounded-lg transition-colors flex-shrink-0"
                              style={{ color: '#ef4444' }}
                            >
                              <Icon name="delete" style={{ fontSize: '14px' }} />
                            </button>
                          </div>
                        )
                      })
                    )}
                  </div>

                  {/* Analyser le contenu — dans le panneau Textes sources */}
                  {documents.length > 0 && (
                    <div className="px-3 pb-3 pt-1 border-t" style={{ borderColor: colors.border }}>
                      <button
                        onClick={handleAnalyse}
                        disabled={analysing}
                        className="w-full flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                        style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}`, color: colors.textSecondary }}
                      >
                        <Icon name="analytics" style={{ fontSize: '14px' }} />
                        {analysing ? 'Analyse en cours...' : 'Analyser le contenu'}
                      </button>

                      {wordAnalysis && (
                        <div
                          className="mt-2 rounded-xl p-3"
                          style={{
                            backgroundColor: wordAnalysis.sufficient ? (darkMode ? '#14532d' : '#dcfce7') : (darkMode ? '#431407' : '#fff7ed'),
                            border: `1px solid ${wordAnalysis.sufficient ? (darkMode ? '#166534' : '#86efac') : (darkMode ? '#7c2d12' : '#fed7aa')}`,
                          }}
                        >
                          <div className="flex items-center gap-1.5 mb-1">
                            <Icon name={wordAnalysis.sufficient ? 'check_circle' : 'warning'} style={{ color: wordAnalysis.sufficient ? '#22c55e' : '#f97316', fontSize: '14px' }} />
                            <p className="text-xs font-bold" style={{ color: wordAnalysis.sufficient ? (darkMode ? '#86efac' : '#166534') : (darkMode ? '#fdba74' : '#c2410c') }}>
                              {wordAnalysis.total_words.toLocaleString('fr-FR')} mots
                              {wordAnalysis.sufficient
                                ? ` · ${wordAnalysis.days_coverable >= 2 ? `${Math.floor(wordAnalysis.days_coverable)} j.` : '1 journée ✓'}`
                                : ` · ${Math.round(wordAnalysis.days_coverable * 100)}%`}
                            </p>
                          </div>
                          {!wordAnalysis.sufficient && (
                            <p className="text-xs" style={{ color: darkMode ? '#fdba74' : '#c2410c' }}>
                              Manque ~{wordAnalysis.words_missing.toLocaleString('fr-FR')} mots
                            </p>
                          )}
                          {wordAnalysis.sufficient && wordAnalysis.surplus_words > 500 && (
                            <p className="text-xs" style={{ color: darkMode ? '#86efac' : '#166534' }}>
                              +{wordAnalysis.surplus_words.toLocaleString('fr-FR')} mots tronqués auto
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* ── Panneau droit : Audios générés ── */}
                <div className="rounded-2xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
                  <div className="px-4 py-3 flex items-center gap-2" style={{ backgroundColor: darkMode ? '#1e293b' : '#f1f5f9', borderBottom: `1px solid ${colors.border}` }}>
                    <Icon name="music_note" style={{ color: '#7c3aed', fontSize: '18px' }} />
                    <span className="text-sm font-semibold" style={{ color: colors.text }}>Audios générés</span>
                    <select
                      value={audioTypeFilter}
                      onChange={(e) => setAudioTypeFilter(e.target.value)}
                      className="ml-auto text-xs rounded-lg px-2 py-1 outline-none"
                      style={{
                        backgroundColor: darkMode ? '#0f172a' : '#ffffff',
                        border: `1px solid ${colors.border}`,
                        color: colors.textSecondary,
                        cursor: 'pointer',
                      }}
                      title="Filtrer les audios générés"
                    >
                      {AUDIO_FILTERS.map(option => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                    {generatedAudios.length > 0 && (() => {
                      const generatedMap = Object.fromEntries(generatedAudios.map(a => [a.filename, a]))
                      const expected = AUDIO_PLAYLIST_ITEMS.filter(item => audioTypeFilter === 'all' || item.type === audioTypeFilter)
                      const readyCount = expected.filter(item => generatedMap[item.filename]).length
                      const badgeLabel = audioTypeFilter === 'all'
                        ? `${readyCount}/${expected.length}`
                        : `${readyCount}/${expected.length} ${AUDIO_FILTERS.find(f => f.value === audioTypeFilter)?.label.toLowerCase()}`
                      return (
                        <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: darkMode ? '#14532d' : '#dcfce7', color: '#16a34a' }}>
                          {badgeLabel}
                        </span>
                      )
                    })()}
                  </div>

                  <div className="px-3 py-3 space-y-1.5 max-h-80 overflow-y-auto">
                    {(() => {
                      const generatedMap = Object.fromEntries(generatedAudios.map(a => [a.filename, a]))
                      const visibleItems = AUDIO_PLAYLIST_ITEMS.filter(item => audioTypeFilter === 'all' || item.type === audioTypeFilter)
                      return visibleItems.map((item) => {
                        const audio = generatedMap[item.filename]
                        const meta = AUDIO_TYPE_META[item.type] || AUDIO_TYPE_META.cours
                        return (
                          <div
                            key={item.filename}
                            className="rounded-xl px-3 py-2.5 flex items-center gap-2.5"
                            style={{
                              backgroundColor: audio ? (darkMode ? meta.darkBg : meta.lightBg) : colors.innerBg,
                              border: `1px solid ${audio ? (darkMode ? meta.darkBorder : meta.lightBorder) : colors.border}`,
                            }}
                          >
                            <Icon
                              name={audio ? 'check_circle' : 'radio_button_unchecked'}
                              style={{ color: audio ? meta.color : colors.textMuted, fontSize: '16px', flexShrink: 0 }}
                            />
                            <div className="flex-1 min-w-0">
                              <p className="text-xs font-medium flex items-center gap-1.5" style={{ color: audio ? (darkMode ? colors.text : '#14532d') : colors.textMuted }}>
                                <Icon name={meta.icon} style={{ color: audio ? meta.color : colors.textMuted, fontSize: '13px' }} />
                                <span>{item.label}</span>
                                <span style={{ color: audio ? meta.color : colors.textMuted, fontWeight: 700 }}>
                                  · {meta.label}
                                </span>
                              </p>
                              {audio && (
                                <p className="text-xs" style={{ color: darkMode ? colors.textMuted : '#64748b' }}>
                                  {audio.size_mb} Mo · {item.filename}
                                </p>
                              )}
                            </div>
                            {audio && (
                              <button
                                onClick={() => setAudioEditorFile(item.filename)}
                                title="Éditer cet audio (couper / remplacer)"
                                className="flex-shrink-0 rounded-lg p-1 hover:opacity-80 transition-opacity"
                                style={{ backgroundColor: darkMode ? '#2d1b69' : '#ede9fe' }}
                              >
                                <Icon name="cut" style={{ color: '#7c3aed', fontSize: '14px' }} />
                              </button>
                            )}
                          </div>
                        )
                      })
                    })()}
                  </div>

                  {/* ── Mock upload (dev only) ── */}
                  <div
                    className="px-3 py-3 border-t"
                    style={{
                      borderColor: colors.border,
                      backgroundColor: darkMode ? '#0b1020' : '#fafafa',
                    }}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <Icon name="science" style={{ color: '#f59e0b', fontSize: '14px' }} />
                      <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#f59e0b' }}>
                        Mock test
                      </span>
                      <span className="text-xs" style={{ color: colors.textMuted }}>
                        · dev only
                      </span>
                    </div>
                    <p className="text-xs mb-2" style={{ color: colors.textMuted, lineHeight: 1.4 }}>
                      Copie automatiquement les 7 MP3 depuis <code style={{ fontSize: '10px' }}>output_jour1/</code> vers Azure.
                      Les fichiers locaux ne sont pas modifiés.
                    </p>
                    <button
                      onClick={handleMockAudioUpload}
                      disabled={mockUploading}
                      className="w-full flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors"
                      style={{
                        backgroundColor: mockUploading ? colors.innerBg : (darkMode ? '#78350f33' : '#fef3c7'),
                        color: '#f59e0b',
                        border: `1px dashed #f59e0b`,
                        cursor: mockUploading ? 'wait' : 'pointer',
                      }}
                    >
                      {mockUploading ? (
                        <>
                          <div className="h-3 w-3 animate-spin rounded-full border-2 border-amber-300 border-t-amber-600" />
                          Upload en cours...
                        </>
                      ) : (
                        <>
                          <Icon name="cloud_upload" style={{ fontSize: '14px' }} />
                          Uploader output_jour1
                        </>
                      )}
                    </button>

                    {mockUploadQueue.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {mockUploadQueue.map((q, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-2 px-2 py-1 rounded text-xs"
                            style={{
                              backgroundColor:
                                q.status === 'done' ? (darkMode ? '#14532d33' : '#dcfce7') :
                                q.status === 'error' ? (darkMode ? '#7f1d1d33' : '#fee2e2') :
                                colors.innerBg,
                              color:
                                q.status === 'done' ? '#16a34a' :
                                q.status === 'error' ? '#dc2626' :
                                colors.textMuted,
                            }}
                          >
                            <Icon
                              name={
                                q.status === 'done' ? 'check_circle' :
                                q.status === 'error' ? 'error' :
                                q.status === 'uploading' ? 'hourglass_empty' :
                                'schedule'
                              }
                              style={{ fontSize: '12px' }}
                            />
                            <span className="flex-1 truncate">{q.name}</span>
                            {q.error && <span className="text-xs opacity-70 truncate">{q.error}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
              {/* ── Fin des deux panneaux ── */}

              {/* ── Génération de contenu TTS-direct ── */}
              <div className="mt-5 rounded-2xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
                {/* Header */}
                <div className="px-4 py-3 flex items-center gap-2" style={{ backgroundColor: darkMode ? '#1e1b4b' : '#f5f3ff', borderBottom: `1px solid ${colors.border}` }}>
                  <Icon name="auto_awesome" style={{ color: '#7c3aed', fontSize: '18px' }} />
                  <span className="text-sm font-semibold" style={{ color: colors.text }}>Générer le contenu depuis un programme</span>
                  <span className="ml-auto text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: darkMode ? '#312e81' : '#ede9fe', color: '#7c3aed' }}>
                    ~92 000 mots · 1 journée
                  </span>
                </div>

                <div className="p-4">
                  {/* Note utilisateur */}
                  <p className="text-xs mb-3 flex items-start gap-1.5" style={{ color: colors.textMuted }}>
                    <Icon name="info" style={{ fontSize: '14px', flexShrink: 0, marginTop: '1px' }} />
                    Chaque dossier représente une journée de formation. Collez le programme ci-dessous — Claude extraira 6 sous-parties et générera ~92 000 mots de cours oral TTS-ready.
                  </p>

                  {/* État : pas de job ou idle → afficher le formulaire */}
                  {(!contentJob || contentJob.status === 'idle') && (
                    <>
                      <textarea
                        value={programText}
                        onChange={e => setProgramText(e.target.value)}
                        placeholder="Collez ici le programme de formation (référentiel, syllabus, plan de cours...)"
                        rows={5}
                        className="w-full rounded-xl px-4 py-3 text-sm resize-none outline-none transition-colors mb-3"
                        style={{
                          backgroundColor: colors.innerBg,
                          border: `1px solid ${colors.border}`,
                          color: colors.text,
                        }}
                      />
                      <button
                        onClick={handleExtractSubParts}
                        disabled={extracting || !programText.trim()}
                        className="flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                        style={{ backgroundColor: '#7c3aed', color: 'white' }}
                      >
                        {extracting
                          ? <><div className="h-4 w-4 animate-spin rounded-full border-2 border-purple-300 border-t-white" />Extraction en cours...</>
                          : <><Icon name="psychology" style={{ fontSize: '18px' }} />Extraire les sous-parties</>
                        }
                      </button>
                    </>
                  )}

                  {/* État : sous-parties extraites → afficher la liste + boutons */}
                  {contentJob && (contentJob.status === 'idle' || contentJob.status === 'cancelled') && contentJob.sub_parts?.length > 0 && (
                    <div className="space-y-3">
                      <div>
                        <p className="text-xs font-semibold mb-2" style={{ color: colors.textSecondary }}>
                          {contentJob.program_title} — {contentJob.sub_parts.length} sous-parties identifiées
                        </p>
                        <div className="space-y-1">
                          {contentJob.sub_parts.map((sp, i) => (
                            <div key={i} className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg" style={{ backgroundColor: colors.innerBg }}>
                              <span className="font-bold" style={{ color: '#7c3aed', minWidth: '18px' }}>{i + 1}.</span>
                              <span style={{ color: colors.text }}>{sp}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div className="flex gap-2 flex-wrap">
                        <button
                          onClick={() => handleStartContentGeneration('normal')}
                          className="flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-bold transition-all"
                          style={{ backgroundColor: '#7c3aed', color: 'white' }}
                        >
                          <Icon name="play_arrow" style={{ fontSize: '18px' }} />
                          Lancer la génération
                        </button>
                        <button
                          onClick={handlePreviewPrompt}
                          className="flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-all"
                          style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}`, color: colors.textSecondary }}
                        >
                          <Icon name="visibility" style={{ fontSize: '16px' }} />
                          Prévisualiser le prompt
                        </button>
                        {/* Boutons test — visibles seulement en développement */}
                        {import.meta.env.DEV && (
                          <>
                            <button
                              onClick={() => handleStartContentGeneration('mock')}
                              title="Génère du texte factice instantanément (0€, teste polling + checkpoint + modale)"
                              className="flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition-all"
                              style={{ backgroundColor: darkMode ? '#1a2e1a' : '#dcfce7', color: '#16a34a', border: '1px dashed #16a34a' }}
                            >
                              <Icon name="science" style={{ fontSize: '14px' }} />
                              Mock (0€)
                            </button>
                            <button
                              onClick={() => handleStartContentGeneration('mini')}
                              title="Génère 1 vrai segment Claude en 300 tokens (~0.02€)"
                              className="flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition-all"
                              style={{ backgroundColor: darkMode ? '#1a2010' : '#fef9c3', color: '#ca8a04', border: '1px dashed #ca8a04' }}
                            >
                              <Icon name="bolt" style={{ fontSize: '14px' }} />
                              Mini (~0.02€)
                            </button>
                          </>
                        )}
                        <button
                          onClick={() => { setContentJob(null); setProgramText('') }}
                          className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm transition-all"
                          style={{ color: colors.textMuted }}
                        >
                          <Icon name="refresh" style={{ fontSize: '16px' }} />
                          Recommencer
                        </button>
                      </div>
                    </div>
                  )}

                  {/* État : génération en cours */}
                  {contentJob?.status === 'running' && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-3">
                        <div className="h-5 w-5 animate-spin rounded-full border-2 border-purple-300 border-t-purple-600 flex-shrink-0" />
                        <p className="text-sm" style={{ color: darkMode ? '#c4b5fd' : '#6d28d9' }}>
                          {contentJob.message}
                        </p>
                      </div>
                      {/* Barre de progression */}
                      {(() => {
                        const totalSteps = (contentJob.num_sub_parts || 6) * 3
                        const doneSteps = (contentJob.current_sub_part || 0) * 3 + ((contentJob.current_passe || 1) - 1)
                        const pct = Math.round((doneSteps / totalSteps) * 100)
                        return (
                          <>
                            <div className="w-full rounded-full h-2" style={{ backgroundColor: darkMode ? '#1e1b4b' : '#ddd6fe' }}>
                              <div className="h-2 rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: '#7c3aed' }} />
                            </div>
                            <div className="flex items-center justify-between text-xs" style={{ color: darkMode ? '#a78bfa' : '#7c3aed' }}>
                              <span>{doneSteps}/{totalSteps} passes</span>
                              <span>{(contentJob.total_words || 0).toLocaleString('fr-FR')} mots générés</span>
                            </div>
                          </>
                        )
                      })()}
                      <button
                        onClick={handleCancelContentGeneration}
                        className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-all"
                        style={{ backgroundColor: darkMode ? '#3f1d1d' : '#fee2e2', color: '#ef4444' }}
                      >
                        <Icon name="stop" style={{ fontSize: '14px' }} />
                        Annuler
                      </button>
                    </div>
                  )}

                  {/* État : terminé */}
                  {contentJob?.status === 'completed' && (
                    <div className="space-y-2">
                      <div className="rounded-xl p-3 flex items-center gap-3" style={{ backgroundColor: darkMode ? '#14532d' : '#dcfce7', border: `1px solid ${darkMode ? '#166534' : '#86efac'}` }}>
                        <Icon name="check_circle" style={{ color: '#22c55e', fontSize: '20px' }} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-bold" style={{ color: darkMode ? '#86efac' : '#166534' }}>
                            {(contentJob.total_words || 0).toLocaleString('fr-FR')} mots générés
                          </p>
                          <p className="text-xs" style={{ color: darkMode ? '#4ade80' : '#16a34a' }}>
                            Fichier .txt ajouté aux textes sources — prêt pour la pipeline audio.
                          </p>
                        </div>
                        <button
                          onClick={() => { setContentJob(null); setProgramText('') }}
                          className="text-xs underline flex-shrink-0"
                          style={{ color: darkMode ? '#86efac' : '#16a34a' }}
                        >
                          Nouveau
                        </button>
                      </div>
                      <button
                        onClick={handleViewContentScript}
                        disabled={loadingContentScript}
                        className="flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-all disabled:opacity-50"
                        style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}`, color: colors.textSecondary }}
                      >
                        <Icon name="article" style={{ fontSize: '18px' }} />
                        {loadingContentScript ? 'Chargement...' : 'Voir le script TTS généré'}
                      </button>
                    </div>
                  )}

                  {/* État : erreur */}
                  {contentJob?.status === 'error' && (
                    <div className="rounded-xl p-3 space-y-2" style={{ backgroundColor: darkMode ? '#7f1d1d' : '#fee2e2', border: `1px solid ${darkMode ? '#991b1b' : '#fca5a5'}` }}>
                      <div className="flex items-center gap-2">
                        <Icon name="error" style={{ color: '#ef4444' }} />
                        <p className="text-sm font-medium" style={{ color: '#ef4444' }}>Erreur : {contentJob.error_message}</p>
                      </div>
                      <button
                        onClick={handleStartContentGeneration}
                        className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium"
                        style={{ backgroundColor: '#ef4444', color: 'white' }}
                      >
                        <Icon name="replay" style={{ fontSize: '14px' }} />
                        Reprendre depuis le checkpoint
                      </button>
                    </div>
                  )}
                </div>
              </div>
              {/* ── Fin génération de contenu ── */}

              {/* ── Zone d'actions ── */}

              {/* Bouton générer */}
              {documents.length > 0 && (
                <div className="mb-4 flex flex-col gap-2">
                  <button
                    onClick={() => handleGeneratePlaylist({})}
                    disabled={playlistJob?.status === 'running'}
                    className="w-full flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ backgroundColor: '#8B5CF6', color: 'white' }}
                    onMouseEnter={(e) => { if (playlistJob?.status !== 'running') e.currentTarget.style.backgroundColor = '#7c3aed' }}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#8B5CF6'}
                  >
                    <Icon name="auto_awesome" className="text-lg" />
                    {playlistJob?.status === 'running'
                      ? 'Pipeline en cours...'
                      : dirtyBlocs?.has_script
                        ? dirtyBlocs.dirty_blocs > 0
                          ? `Régénérer ${dirtyBlocs.dirty_blocs}/7 bloc${dirtyBlocs.dirty_blocs > 1 ? 's' : ''} modifié${dirtyBlocs.dirty_blocs > 1 ? 's' : ''}`
                          : 'Générer les 7 cours MP3 (script)'
                        : 'Générer les 7 cours MP3'
                    }
                  </button>
                  {import.meta.env.DEV && (
                    <>
                      {dirtyBlocs?.has_script && (
                        <button
                          onClick={() => handleGeneratePlaylist({ scriptMock: true })}
                          disabled={playlistJob?.status === 'running'}
                          title="Régénère uniquement les blocs modifiés avec du silence 1s (teste la logique dirty sans appeler fish.audio)"
                          className="w-full flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition-all disabled:opacity-50"
                          style={{ backgroundColor: darkMode ? '#1a2e1a' : '#dcfce7', color: '#16a34a', border: '1px dashed #16a34a' }}
                        >
                          <Icon name="science" style={{ fontSize: '14px' }} />
                          Mock régénération script (0€ — silence, blocs dirty seulement)
                        </button>
                      )}
                      <button
                        onClick={() => handleGeneratePlaylist({ mock: true })}
                        disabled={playlistJob?.status === 'running'}
                        title="Blocs factices + silence 1s — 0€, ~10 secondes (teste upload Azure + structure playlist)"
                        className="w-full flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition-all disabled:opacity-50"
                        style={{ backgroundColor: darkMode ? '#1a2010' : '#fef9c3', color: '#ca8a04', border: '1px dashed #ca8a04' }}
                      >
                        <Icon name="science" style={{ fontSize: '14px' }} />
                        Mock playlist classique (0€ — silence 1s, sans script)
                      </button>
                    </>
                  )}
                </div>
              )}

              {/* Progression pipeline */}
              {playlistJob?.status === 'running' && (
                <div className="mb-4 rounded-2xl p-4" style={{ backgroundColor: darkMode ? '#312e81' : '#ede9fe', border: `1px solid ${darkMode ? '#4c1d95' : '#c4b5fd'}` }}>
                  <div className="flex items-center gap-3 mb-3">
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-purple-300 border-t-purple-600" />
                    <p className="text-sm font-medium" style={{ color: darkMode ? '#c4b5fd' : '#6d28d9' }}>
                      {playlistJob.message}
                    </p>
                  </div>
                  <div className="w-full rounded-full h-2" style={{ backgroundColor: darkMode ? '#1e1b4b' : '#ddd6fe' }}>
                    <div className="h-2 rounded-full transition-all" style={{ width: `${Math.round((playlistJob.step / playlistJob.total_steps) * 100)}%`, backgroundColor: '#8B5CF6' }} />
                  </div>
                  <p className="text-xs mt-1" style={{ color: darkMode ? '#a78bfa' : '#7c3aed' }}>
                    Étape {playlistJob.step}/{playlistJob.total_steps}
                  </p>
                </div>
              )}

              {/* Résultat pipeline */}
              {playlistJob?.status === 'completed' && playlistJob.result && (
                <div className="mb-4 rounded-2xl p-4" style={{ backgroundColor: darkMode ? '#14532d' : '#dcfce7', border: `1px solid ${darkMode ? '#166534' : '#86efac'}` }}>
                  <div className="flex items-center gap-2 mb-1">
                    <Icon name="check_circle" style={{ color: '#22c55e' }} />
                    <p className="text-sm font-bold" style={{ color: darkMode ? '#86efac' : '#166534' }}>
                      {playlistJob.result.filled_blocs || playlistJob.result.generated}/7 blocs générés
                      {playlistJob.result.errors > 0 && ` · ${playlistJob.result.errors} erreur(s)`}
                    </p>
                  </div>
                  <div className="flex gap-3 text-xs mt-1 flex-wrap" style={{ color: darkMode ? '#86efac' : '#166534' }}>
                    {playlistJob.result.total_duration_hours > 0 && <span><Icon name="schedule" style={{ fontSize: '12px' }} /> {playlistJob.result.total_duration_hours}h</span>}
                    {playlistJob.result.total_size_mb > 0 && <span><Icon name="storage" style={{ fontSize: '12px' }} /> {playlistJob.result.total_size_mb} Mo</span>}
                  </div>
                </div>
              )}

              {/* Erreur pipeline */}
              {playlistJob?.status === 'error' && (
                <div className="mb-4 rounded-2xl p-4" style={{ backgroundColor: darkMode ? '#7f1d1d' : '#fee2e2', border: `1px solid ${darkMode ? '#991b1b' : '#fca5a5'}` }}>
                  <div className="flex items-center gap-2">
                    <Icon name="error" style={{ color: '#ef4444' }} />
                    <p className="text-sm font-medium" style={{ color: '#ef4444' }}>Erreur : {playlistJob.message}</p>
                  </div>
                </div>
              )}

            </>
          )}
        </div>
      </div>

      {/* Modale prévisualisation prompt */}
      {showPromptPreview && promptPreview && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}
          onClick={() => setShowPromptPreview(false)}
        >
          <div
            className="w-full overflow-hidden rounded-2xl shadow-2xl flex flex-col"
            style={{ maxWidth: '800px', maxHeight: '90vh', backgroundColor: colors.cardBg }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0" style={{ borderColor: colors.border, backgroundColor: '#7c3aed' }}>
              <div className="flex items-center gap-3 text-white">
                <Icon name="visibility" className="text-2xl" />
                <div>
                  <h3 className="text-lg font-bold">Prompt Passe 1 — Aperçu</h3>
                  <p className="text-xs text-purple-200">Ce prompt sera envoyé à Claude pour chaque sous-partie</p>
                </div>
              </div>
              <button onClick={() => setShowPromptPreview(false)} className="text-white hover:bg-white/20 rounded-full p-1">
                <Icon name="close" className="text-2xl" />
              </button>
            </div>
            <div className="overflow-y-auto p-6">
              <pre className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: colors.text, fontFamily: 'monospace' }}>
                {promptPreview}
              </pre>
            </div>
          </div>
        </div>
      )}

      {/* Modale script TTS généré — 2 colonnes */}
      {contentScriptModal && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0,0,0,0.75)' }}
          onClick={closeContentScriptModal}
        >
          <div
            className="w-full overflow-hidden rounded-2xl shadow-2xl flex flex-col"
            style={{ maxWidth: '1100px', maxHeight: '92vh', backgroundColor: colors.cardBg }}
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0" style={{ borderColor: colors.border, backgroundColor: '#6d28d9' }}>
              <div className="flex items-center gap-3 text-white">
                <Icon name="article" className="text-2xl" />
                <div>
                  <h3 className="text-lg font-bold">Script TTS — {contentScriptModal.program_title}</h3>
                  <p className="text-xs" style={{ color: '#ddd6fe' }}>
                    {(contentScriptModal.total_words || 0).toLocaleString('fr-FR')} mots · {contentScriptModal.sub_parts?.length} sous-parties · {contentScriptModal.course_blocs?.length || 0} cours audio
                    {scriptAnnotations.length > 0 && ` · ${scriptAnnotations.length} note${scriptAnnotations.length > 1 ? 's' : ''}`}
                  </p>
                </div>
              </div>
              <div className="ml-auto mr-3 flex rounded-lg p-1" style={{ backgroundColor: 'rgba(255,255,255,0.14)' }}>
                {[
                  { value: 'source', label: 'Sous-parties', icon: 'segment' },
                  { value: 'courses', label: 'Cours audio', icon: 'record_voice_over' },
                ].map(option => {
                  const active = contentScriptView === option.value
                  const disabled = option.value === 'courses' && !(contentScriptModal.course_blocs?.length > 0)
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => {
                        if (disabled) return
                        setContentScriptView(option.value)
                        setEditingSegment(null)
                        resetScriptAnnotationDraft()
                      }}
                      disabled={disabled}
                      className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                      style={{
                        backgroundColor: active ? '#f8fafc' : 'transparent',
                        color: active ? '#5b21b6' : '#f5f3ff',
                      }}
                    >
                      <Icon name={option.icon} style={{ fontSize: '14px' }} />
                      {option.label}
                    </button>
                  )
                })}
              </div>
              {scriptAnnotations.length > 0 && (
                <button
                  type="button"
                  onClick={downloadAnnotationsMarkdown}
                  className="mr-2 inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors"
                  style={{ backgroundColor: 'rgba(255,255,255,0.14)', color: '#f5f3ff' }}
                  title={contentScriptModal.annotations_markdown_path || 'Télécharger le markdown de revue'}
                >
                  <Icon name="download" style={{ fontSize: '15px' }} />
                  Markdown
                </button>
              )}
              <button
                type="button"
                onClick={() => setRulesPanelOpen(prev => !prev)}
                className="mr-3 inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors"
                style={{
                  backgroundColor: rulesPanelOpen ? '#facc15' : 'rgba(255,255,255,0.14)',
                  color: rulesPanelOpen ? '#1f2937' : '#f5f3ff',
                }}
                title="Règles apprises depuis tes annotations"
              >
                <Icon name="rule" style={{ fontSize: '15px' }} />
                Règles {scriptRules?.rules_count ? `(${scriptRules.rules_count})` : ''}
              </button>
              <button onClick={closeContentScriptModal} className="text-white hover:bg-white/20 rounded-full p-1">
                <Icon name="close" className="text-2xl" />
              </button>
            </div>

            {rulesPanelOpen && (
              <div
                className="border-b px-6 py-4"
                style={{ backgroundColor: darkMode ? '#1a1332' : '#fefce8', borderColor: colors.border }}
              >
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-bold" style={{ color: colors.text }}>
                      Règles apprises depuis tes annotations
                    </p>
                    <p className="text-xs" style={{ color: colors.textMuted }}>
                      {scriptRules?.source_annotations_count
                        ? `Extraites de ${scriptRules.source_annotations_count} annotation${scriptRules.source_annotations_count > 1 ? 's' : ''} via ${scriptRules.model || 'DeepSeek'}. Généré le ${scriptRules.generated_at || '—'}.`
                        : 'Aucune extraction encore — applique au moins une correction puis clique sur Extraire.'}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={extractScriptRules}
                      disabled={extractingRules || scriptAnnotations.length === 0}
                      className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                      style={{ backgroundColor: '#7c3aed', color: 'white' }}
                    >
                      <Icon name="auto_awesome" style={{ fontSize: '14px' }} />
                      {extractingRules ? 'Extraction…' : (scriptRules?.rules_count ? 'Ré-extraire' : 'Extraire')}
                    </button>
                    {scriptRules?.rules_markdown && (
                      <button
                        type="button"
                        onClick={downloadRulesMarkdown}
                        className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors"
                        style={{ backgroundColor: colors.innerBg, color: colors.text, border: `1px solid ${colors.border}` }}
                      >
                        <Icon name="download" style={{ fontSize: '14px' }} />
                        Markdown
                      </button>
                    )}
                    {scriptRules?.rules_markdown && (
                      <>
                        <button
                          type="button"
                          onClick={() => runRulesReview(true)}
                          disabled={reviewingRules}
                          className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                          style={{ backgroundColor: colors.innerBg, color: colors.text, border: `1px solid ${colors.border}` }}
                          title="Simule la revérif sans toucher aux MP3"
                        >
                          <Icon name="visibility" style={{ fontSize: '14px' }} />
                          {reviewingRules ? 'Analyse…' : 'Simuler'}
                        </button>
                        <button
                          type="button"
                          onClick={() => runRulesReview(false)}
                          disabled={reviewingRules}
                          className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                          style={{ backgroundColor: '#16a34a' }}
                          title="Patche les MP3 non conformes en place"
                        >
                          <Icon name="auto_fix_high" style={{ fontSize: '14px' }} />
                          {reviewingRules ? 'Patch en cours…' : 'Appliquer aux MP3'}
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {rulesReviewSummary && (
                  <div
                    className="mb-2 rounded-md p-3 text-xs"
                    style={{ backgroundColor: colors.innerBg, color: colors.text, border: `1px solid ${colors.border}` }}
                  >
                    <p className="mb-2 text-[11px] font-bold uppercase tracking-wide" style={{ color: '#7c3aed' }}>
                      Résumé revérif{rulesReviewSummary.dry_run ? ' (simulation)' : ''}
                    </p>
                    <ul className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
                      <li>Examinés : <strong>{rulesReviewSummary.chunks_examined}</strong></li>
                      <li style={{ color: '#16a34a' }}>{rulesReviewSummary.dry_run ? 'À corriger' : 'Corrigés'} : <strong>{rulesReviewSummary.chunks_corrected}</strong></li>
                      <li style={{ color: colors.textMuted }}>Skipped : <strong>{rulesReviewSummary.chunks_skipped}</strong></li>
                      <li style={{ color: '#dc2626' }}>Échecs : <strong>{rulesReviewSummary.chunks_failed}</strong></li>
                    </ul>
                    {(rulesReviewSummary.details || []).filter(d => d.status !== 'conforme').slice(0, 6).map((d, i) => (
                      <div key={i} className="mt-2 rounded p-2 text-[11px]" style={{ backgroundColor: 'rgba(124,58,237,0.08)' }}>
                        <p className="font-semibold">{d.audio_filename} · bloc {d.bloc_number} · <span style={{ color: d.status === 'done' || d.status === 'would_correct' ? '#16a34a' : '#dc2626' }}>{d.status}</span></p>
                        {d.violations?.length > 0 && (
                          <p style={{ color: colors.textMuted }}>{d.violations.join(' · ')}</p>
                        )}
                        {d.reason && <p style={{ color: '#dc2626' }}>{d.reason}</p>}
                      </div>
                    ))}
                    {(rulesReviewSummary.details || []).filter(d => d.status !== 'conforme').length > 6 && (
                      <p className="mt-2 text-[11px] italic" style={{ color: colors.textMuted }}>
                        … et {(rulesReviewSummary.details || []).filter(d => d.status !== 'conforme').length - 6} autres
                      </p>
                    )}
                  </div>
                )}
                {rulesError && (
                  <p className="mb-2 text-xs font-semibold" style={{ color: '#dc2626' }}>{rulesError}</p>
                )}
                {scriptRules?.rules_markdown ? (
                  <pre
                    className="max-h-72 overflow-auto rounded-md p-3 text-xs leading-relaxed"
                    style={{ backgroundColor: colors.innerBg, color: colors.text, whiteSpace: 'pre-wrap' }}
                  >
                    {scriptRules.rules_markdown}
                  </pre>
                ) : (
                  <p className="text-xs italic" style={{ color: colors.textMuted }}>
                    Aucune règle apprise pour ce dossier. L'extraction lit toutes les annotations (appliquées et rejetées) pour produire un markdown de règles transversales.
                  </p>
                )}
              </div>
            )}

            {/* Corps : sidebar + contenu */}
            {contentScriptView === 'source' ? (
            <div className="flex flex-1 min-h-0">

              {/* Sidebar sommaire */}
              <div
                className="flex-shrink-0 overflow-y-auto border-r py-3"
                style={{ width: '260px', borderColor: colors.border, backgroundColor: darkMode ? '#1a1332' : '#f5f3ff' }}
              >
                <p className="px-4 pb-2 text-xs font-semibold uppercase tracking-widest" style={{ color: '#9333ea' }}>
                  Sommaire
                </p>
                {contentScriptModal.sub_parts?.map((sp) => {
                  const isActive = scriptActiveSubPart === sp.index
                  return (
                    <button
                      key={sp.index}
                      onClick={() => { setScriptActiveSubPart(sp.index); setEditingSegment(null); resetScriptAnnotationDraft() }}
                      className="w-full text-left px-4 py-2.5 transition-colors"
                      style={{
                        backgroundColor: isActive ? (darkMode ? '#3b0764' : '#ede9fe') : 'transparent',
                        boxShadow: isActive ? 'inset 0 0 0 1px rgba(124, 58, 237, 0.42)' : 'inset 0 0 0 1px transparent',
                      }}
                    >
                      <div className="flex items-start gap-2">
                        <span
                          className="flex-shrink-0 w-5 h-5 rounded-full text-xs font-bold flex items-center justify-center mt-0.5"
                          style={{ backgroundColor: isActive ? '#7c3aed' : (darkMode ? '#4c1d95' : '#ddd6fe'), color: isActive ? 'white' : '#6d28d9' }}
                        >
                          {sp.index + 1}
                        </span>
                        <div className="min-w-0">
                          <p className="text-xs font-medium leading-snug" style={{ color: isActive ? (darkMode ? '#e9d5ff' : '#4c1d95') : colors.textSecondary }}>
                            {sp.name}
                          </p>
                          <p className="text-xs mt-0.5" style={{ color: colors.textMuted }}>
                            {(sp.total_words || 0).toLocaleString('fr-FR')} mots
                          </p>
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>

              {/* Panneau droit — passes de la sous-partie active */}
              <div className="flex-1 overflow-y-auto p-5 space-y-4">
                {(() => {
                  const sp = contentScriptModal.sub_parts?.find(s => s.index === scriptActiveSubPart)
                  if (!sp) return null
                  return (
                    <>
                      <div className="flex items-center gap-3 pb-2" style={{ borderBottom: `1px solid ${colors.border}` }}>
                        <span className="text-sm font-bold px-2.5 py-0.5 rounded-full" style={{ backgroundColor: '#7c3aed', color: 'white' }}>
                          {sp.index + 1}
                        </span>
                        <span className="text-sm font-semibold flex-1" style={{ color: colors.text }}>{sp.name}</span>
                        <span className="text-xs" style={{ color: colors.textMuted }}>{(sp.total_words || 0).toLocaleString('fr-FR')} mots</span>
                      </div>

                      {sp.passes?.map((pass) => {
                        const isEditing = editingSegment?.sub_part_index === sp.index && editingSegment?.passe === pass.passe
                        const annotationContext = { source_type: 'segment', sub_part_index: sp.index, passe: pass.passe }
                        return (
                          <div key={pass.passe} className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
                            {/* En-tête passe */}
                            <div className="px-4 py-2 flex items-center justify-between" style={{ backgroundColor: darkMode ? '#1e1b4b' : '#ede9fe' }}>
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-bold" style={{ color: '#7c3aed' }}>Passe {pass.passe}</span>
                                <span className="text-xs" style={{ color: colors.textMuted }}>{(pass.word_count || 0).toLocaleString('fr-FR')} mots</span>
                              </div>
                              {!isEditing && (
                                <button
                                  onClick={() => handleStartEdit(sp.index, pass.passe, pass.text)}
                                  className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg transition-colors"
                                  style={{ backgroundColor: darkMode ? '#3b0764' : '#ddd6fe', color: '#7c3aed' }}
                                >
                                  <Icon name="edit" style={{ fontSize: '14px' }} />
                                  Modifier
                                </button>
                              )}
                              {isEditing && (
                                <div className="flex gap-2">
                                  <button
                                    onClick={handleCancelEdit}
                                    disabled={savingEdit}
                                    className="text-xs px-2.5 py-1 rounded-lg transition-colors"
                                    style={{ backgroundColor: colors.innerBg, color: colors.textSecondary, border: `1px solid ${colors.border}` }}
                                  >
                                    Annuler
                                  </button>
                                  <button
                                    onClick={handleSaveEdit}
                                    disabled={savingEdit}
                                    className="text-xs px-2.5 py-1 rounded-lg font-semibold transition-colors"
                                    style={{ backgroundColor: '#7c3aed', color: 'white' }}
                                  >
                                    {savingEdit ? 'Sauvegarde...' : 'Sauvegarder'}
                                  </button>
                                </div>
                              )}
                            </div>

                            {/* Corps : texte ou textarea */}
                            <div className="px-4 py-3" style={{ backgroundColor: colors.cardBg }}>
                              <ScriptAnnotationComposer context={annotationContext} />
                              {isEditing ? (
                                <textarea
                                  value={editText}
                                  onChange={e => setEditText(e.target.value)}
                                  rows={18}
                                  className="w-full text-xs leading-relaxed rounded-lg p-3 resize-y outline-none"
                                  style={{
                                    backgroundColor: darkMode ? '#0f0a1f' : '#faf5ff',
                                    color: colors.text,
                                    fontFamily: 'monospace',
                                    border: `1px solid #7c3aed`,
                                  }}
                                />
                              ) : (
                                <p
                                  className="text-xs leading-relaxed whitespace-pre-wrap"
                                  tabIndex={0}
                                  onMouseUp={(event) => captureScriptSelection(event, annotationContext)}
                                  onKeyUp={(event) => captureScriptSelection(event, annotationContext)}
                                  style={{ color: colors.text, fontFamily: 'monospace' }}
                                >
                                  {pass.text}
                                </p>
                              )}
                              <ScriptAnnotationsList context={annotationContext} />
                            </div>
                          </div>
                        )
                      })}
                    </>
                  )
                })()}
              </div>
            </div>
            ) : (
            <div className="flex flex-1 min-h-0">
              <div
                className="flex-shrink-0 overflow-y-auto border-r py-3"
                style={{ width: '280px', borderColor: colors.border, backgroundColor: darkMode ? '#111827' : '#f8fafc' }}
              >
                <p className="px-4 pb-2 text-xs font-semibold uppercase tracking-widest" style={{ color: '#7c3aed' }}>
                  Cours audio
                </p>
                {contentScriptModal.course_blocs?.map((bloc) => {
                  const isActive = !scriptActiveBreak && scriptActiveCourse === bloc.bloc_number
                  const statusLabel = {
                    generated: 'Généré',
                    preserved: 'Conservé',
                    preview: 'Prévu',
                    skipped: 'Ignoré',
                  }[bloc.status] || bloc.status
                  return (
                    <button
                      key={bloc.bloc_number}
                      type="button"
                      onClick={() => { setScriptActiveCourse(bloc.bloc_number); setScriptActiveBreak(null); resetScriptAnnotationDraft() }}
                      className="w-full text-left px-4 py-2.5 transition-colors"
                      style={{
                        backgroundColor: isActive ? (darkMode ? '#312e81' : '#ede9fe') : 'transparent',
                        boxShadow: isActive ? 'inset 0 0 0 1px rgba(124, 58, 237, 0.42)' : 'inset 0 0 0 1px transparent',
                      }}
                    >
                      <div className="flex items-start gap-2">
                        <span
                          className="flex-shrink-0 w-6 h-6 rounded-full text-xs font-bold flex items-center justify-center mt-0.5"
                          style={{ backgroundColor: isActive ? '#7c3aed' : (darkMode ? '#334155' : '#e2e8f0'), color: isActive ? 'white' : colors.textSecondary }}
                        >
                          {bloc.bloc_number}
                        </span>
                        <div className="min-w-0">
                          <p className="text-xs font-semibold leading-snug" style={{ color: isActive ? (darkMode ? '#e9d5ff' : '#4c1d95') : colors.text }}>
                            Cours {bloc.bloc_number} · {Math.round((bloc.duration_sec || 0) / 60)} min
                          </p>
                          <p className="text-xs mt-0.5 truncate" style={{ color: colors.textMuted }}>
                            {statusLabel} · {(bloc.word_count || 0).toLocaleString('fr-FR')} mots
                          </p>
                          {(bloc.closing_added || bloc.runtime_conclusions?.length > 0) && (
                            <p className="text-xs mt-0.5" style={{ color: '#7c3aed' }}>
                              conclusion ajoutée
                            </p>
                          )}
                        </div>
                      </div>
                    </button>
                  )
                })}
                {(contentScriptModal.breaks?.length > 0) && (
                  <>
                    <p className="px-4 pt-4 pb-2 text-xs font-semibold uppercase tracking-widest" style={{ color: '#7c3aed' }}>
                      Q&amp;A et pauses
                    </p>
                    {contentScriptModal.breaks.map((br) => {
                      const isActive = scriptActiveBreak === br.filename
                      const typeLabel = br.type === 'qa' ? 'Q&A' : br.type === 'pause_midi' ? 'Pause déj.' : 'Pause'
                      const iconName = br.type === 'qa' ? 'forum' : br.type === 'pause_midi' ? 'restaurant' : 'pause_circle'
                      return (
                        <button
                          key={br.filename}
                          type="button"
                          onClick={() => { setScriptActiveBreak(br.filename); resetScriptAnnotationDraft() }}
                          className="w-full text-left px-4 py-2.5 transition-colors"
                          style={{
                            backgroundColor: isActive ? (darkMode ? '#312e81' : '#ede9fe') : 'transparent',
                            boxShadow: isActive ? 'inset 0 0 0 1px rgba(124, 58, 237, 0.42)' : 'inset 0 0 0 1px transparent',
                          }}
                        >
                          <div className="flex items-start gap-2">
                            <span
                              className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5"
                              style={{ backgroundColor: isActive ? '#7c3aed' : (darkMode ? '#334155' : '#e2e8f0'), color: isActive ? 'white' : colors.textSecondary }}
                            >
                              <Icon name={iconName} style={{ fontSize: '14px' }} />
                            </span>
                            <div className="min-w-0">
                              <p className="text-xs font-semibold leading-snug" style={{ color: isActive ? (darkMode ? '#e9d5ff' : '#4c1d95') : colors.text }}>
                                {typeLabel} · {Math.round((br.duration_sec || 0) / 60)} min
                              </p>
                              <p className="text-xs mt-0.5 truncate" style={{ color: colors.textMuted }}>
                                {br.filename}
                              </p>
                            </div>
                          </div>
                        </button>
                      )
                    })}
                  </>
                )}
              </div>

              <div className="flex-1 overflow-y-auto p-5 space-y-4">
                {(() => {
                  if (scriptActiveBreak) {
                    const br = (contentScriptModal.breaks || []).find(b => b.filename === scriptActiveBreak)
                    if (!br) {
                      return (
                        <div className="rounded-xl p-4 text-sm" style={{ backgroundColor: colors.innerBg, color: colors.textMuted }}>
                          Q&amp;A ou pause introuvable.
                        </div>
                      )
                    }
                    const typeLabel = br.type === 'qa' ? 'Q&A' : br.type === 'pause_midi' ? 'Pause déjeuner' : 'Pause'
                    return (
                      <>
                        <div className="flex items-start gap-3 pb-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
                          <span className="text-sm font-bold px-2.5 py-0.5 rounded-full" style={{ backgroundColor: '#7c3aed', color: 'white' }}>
                            {typeLabel}
                          </span>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-semibold" style={{ color: colors.text }}>
                              {br.filename}
                            </p>
                            <p className="text-xs mt-1" style={{ color: colors.textMuted }}>
                              Texte générique · {Math.round((br.duration_sec || 0) / 60)} min · variant bloc {br.bloc_number}
                            </p>
                          </div>
                        </div>

                        <div className="rounded-xl px-4 py-3 text-xs leading-relaxed" style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}`, color: colors.textSecondary }}>
                          Textes statiques utilisés pour ce {typeLabel.toLowerCase()}. Le reste du créneau est rempli par un silence Edge TTS calé sur la durée cible.
                        </div>

                        <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
                          <div className="px-4 py-2" style={{ backgroundColor: darkMode ? '#0f172a' : '#f8fafc' }}>
                            <span className="text-xs font-bold" style={{ color: colors.textSecondary }}>Intro (au début du fichier)</span>
                          </div>
                          <div className="px-4 py-3" style={{ backgroundColor: colors.cardBg }}>
                            <p className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: colors.text, fontFamily: 'monospace' }}>
                              {br.intro || '—'}
                            </p>
                          </div>
                        </div>

                        <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
                          <div className="px-4 py-2" style={{ backgroundColor: darkMode ? '#0f172a' : '#f8fafc' }}>
                            <span className="text-xs font-bold" style={{ color: colors.textSecondary }}>Outro (à la fin du fichier)</span>
                          </div>
                          <div className="px-4 py-3" style={{ backgroundColor: colors.cardBg }}>
                            <p className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: colors.text, fontFamily: 'monospace' }}>
                              {br.outro || '—'}
                            </p>
                          </div>
                        </div>
                      </>
                    )
                  }
                  const blocs = contentScriptModal.course_blocs || []
                  const active = blocs.find(b => b.bloc_number === scriptActiveCourse) || blocs[0]
                  if (!active) {
                    return (
                      <div className="rounded-xl p-4 text-sm" style={{ backgroundColor: colors.innerBg, color: colors.textMuted }}>
                        Aucun cours audio disponible.
                      </div>
                    )
                  }
                  const activeAnnotationContext = { source_type: 'course', bloc_number: active.bloc_number, filename: active.filename }
                  const sourceLabel = contentScriptModal.course_blocs_source === 'last_audio_generation'
                    ? 'Dernière génération TTS'
                    : 'Prévisualisation'
                  const statusLabel = {
                    generated: 'Généré',
                    preserved: 'Conservé',
                    preview: 'Prévu',
                    skipped: 'Ignoré',
                  }[active.status] || active.status
                  const conclusionBlocks = []
                  if (active.closing_text) {
                    conclusionBlocks.push({ label: 'Conclusion de partie', text: active.closing_text })
                  }
                  ;(active.runtime_conclusions || []).forEach((item, idx) => {
                    if (item.text) conclusionBlocks.push({ label: `Conclusion Edge TTS ${idx + 1}`, text: item.text })
                  })
                  return (
                    <>
                      <div className="flex items-start gap-3 pb-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
                        <span className="text-sm font-bold px-2.5 py-0.5 rounded-full" style={{ backgroundColor: '#7c3aed', color: 'white' }}>
                          Cours {active.bloc_number}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-semibold" style={{ color: colors.text }}>
                            {active.filename}
                          </p>
                          <p className="text-xs mt-1" style={{ color: colors.textMuted }}>
                            {sourceLabel} · {statusLabel} · {(active.word_count || 0).toLocaleString('fr-FR')} mots · {Math.round((active.duration_sec || 0) / 60)} min
                          </p>
                        </div>
                        {active.final_duration_sec && (
                          <span className="text-xs rounded-full px-2 py-1" style={{ backgroundColor: darkMode ? '#334155' : '#f1f5f9', color: colors.textSecondary }}>
                            audio {Math.round(active.final_duration_sec / 60)} min
                          </span>
                        )}
                      </div>

                      {contentScriptModal.course_blocs_note && (
                        <div
                          className="rounded-xl px-4 py-3 text-xs leading-relaxed"
                          style={contentScriptModal.course_blocs_stale ? {
                            backgroundColor: darkMode ? '#431407' : '#fff7ed',
                            border: `1px solid ${darkMode ? '#7c2d12' : '#fed7aa'}`,
                            color: darkMode ? '#fdba74' : '#c2410c',
                          } : {
                            backgroundColor: colors.innerBg,
                            border: `1px solid ${colors.border}`,
                            color: colors.textSecondary,
                          }}
                        >
                          {contentScriptModal.course_blocs_note}
                        </div>
                      )}

                      {active.opening_rewritten && (
                        <div className="rounded-xl px-4 py-3 text-xs" style={{ backgroundColor: darkMode ? '#312e81' : '#ede9fe', border: `1px solid ${darkMode ? '#4c1d95' : '#c4b5fd'}`, color: darkMode ? '#ddd6fe' : '#5b21b6' }}>
                          L'ouverture de ce cours a été réécrite pour enchaîner naturellement avec le fichier précédent.
                        </div>
                      )}

                      {active.overflow_unresolved && (
                        <div className="rounded-xl px-4 py-3 text-xs" style={{ backgroundColor: darkMode ? '#431407' : '#fff7ed', border: `1px solid ${darkMode ? '#7c2d12' : '#fed7aa'}`, color: darkMode ? '#fdba74' : '#c2410c' }}>
                          Ce bloc dépasse encore le budget de {active.overflow_words?.toLocaleString('fr-FR')} mots dans la prévisualisation.
                        </div>
                      )}

                      {conclusionBlocks.length > 0 && (
                        <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
                          <div className="px-4 py-2 flex items-center gap-2" style={{ backgroundColor: darkMode ? '#1e1b4b' : '#ede9fe' }}>
                            <Icon name="flag" style={{ color: '#7c3aed', fontSize: '16px' }} />
                            <span className="text-xs font-bold" style={{ color: '#7c3aed' }}>Conclusions ajoutées</span>
                          </div>
                          <div className="p-4 space-y-3" style={{ backgroundColor: colors.cardBg }}>
                            {conclusionBlocks.map((item, idx) => (
                              <div key={idx} className="rounded-lg p-3" style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}` }}>
                                <p className="mb-2 text-xs font-semibold" style={{ color: '#7c3aed' }}>{item.label}</p>
                                <p className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: colors.text, fontFamily: 'monospace' }}>
                                  {item.text}
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${colors.border}` }}>
                        <div className="px-4 py-2 flex items-center justify-between" style={{ backgroundColor: darkMode ? '#0f172a' : '#f8fafc' }}>
                          <span className="text-xs font-bold" style={{ color: colors.textSecondary }}>Texte complet du cours audio</span>
                          <span className="text-xs" style={{ color: colors.textMuted }}>
                            budget {(active.word_budget || 0).toLocaleString('fr-FR')} mots
                          </span>
                        </div>
                        <div className="px-4 py-3" style={{ backgroundColor: colors.cardBg }}>
                          <ScriptAnnotationComposer context={activeAnnotationContext} />
                          <p
                            className="text-xs leading-relaxed whitespace-pre-wrap"
                            tabIndex={0}
                            onMouseUp={(event) => captureScriptSelection(event, activeAnnotationContext)}
                            onKeyUp={(event) => captureScriptSelection(event, activeAnnotationContext)}
                            style={{ color: colors.text, fontFamily: 'monospace' }}
                          >
                            {active.text || 'Aucun texte pour ce cours.'}
                          </p>
                          <ScriptAnnotationsList context={activeAnnotationContext} />
                        </div>
                      </div>
                    </>
                  )
                })()}
              </div>
            </div>
            )}
          </div>
        </div>
      )}

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
                    style={{ backgroundColor: bloc.skipped ? (darkMode ? '#7f1d1d' : '#fee2e2') : (darkMode ? '#1e293b' : '#F8F7F5') }}
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

      {audioEditorFile && selectedFolder && (
        <AudioEditor
          folderId={selectedFolder.id}
          filename={audioEditorFile}
          darkMode={darkMode}
          colors={colors}
          onClose={() => setAudioEditorFile(null)}
        />
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
