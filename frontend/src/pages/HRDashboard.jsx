import { useState, useEffect, useRef, useMemo } from 'react'
import { apiFetch } from '../api'
import CoursFoldersModal from '../components/CoursFolders'
import SlideToConfirm, { BackupPipeline } from '../components/SlideToConfirm'

// ─── Material Icon Component ─────────────────────────────────────────────────
const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`}>{name}</span>
)

const hasCrCdTitle = (title = '') => /\bCRCD\b/i.test(title)
const hasEcTitle = (title = '') => /\bEC\b/i.test(title)
const normalizeRncpCode = (value = '') => String(value).trim().replace(/^RNCP\s*/i, '')
const getPlatformThumbnail = (platform = {}) => {
  const title = platform.name || ''
  const sourceTitle = platform.source_tp_name || ''
  const rncpCode = normalizeRncpCode(platform.source_rncp_code || platform.rncp_code)

  if (rncpCode === '35304' || hasCrCdTitle(title) || hasCrCdTitle(sourceTitle)) {
    return { src: '/tp-crcd-thumbnail.svg', alt: 'TP CRCD' }
  }
  if (hasEcTitle(title) || hasEcTitle(sourceTitle)) return { src: '/tp-ec-thumbnail.svg', alt: 'TP EC' }
  return null
}

// Chaque plateforme a son robot prof IA attitré : un PNG transparent pré-coloré
// (variantes de teinte cuites depuis l'asset rose détouré) + une couleur de halo
// assortie. Déterministe sur platform_id → P1 garde toujours le même robot.
const ROBOT_THEMES = [
  { src: '/robot-blue.png', glow: '#3b82f6' },   // bleu
  { src: '/robot-violet.png', glow: '#8b5cf6' }, // violet
  { src: '/robot-pink.png', glow: '#ec4899' },   // rose
  { src: '/robot-green.png', glow: '#10b981' },  // vert
  { src: '/robot-amber.png', glow: '#f59e0b' },  // ambre
]
const getRobotTheme = (id = 0) => ROBOT_THEMES[((Number(id) || 1) - 1) % ROBOT_THEMES.length]
const todayDateInput = () => {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}

const PIPELINE_PROGRESS_BY_STEP = {
  reac: 12,
  kb: 24,
  global: 36,
  daily: 48,
  content: 64,
  review: 78,
  post_review_docs: 88,
  slides: 96,
  audio: 98,
  done: 100,
}

const PIPELINE_PROGRESS_BY_STATUS = {
  init: 8,
  reac_ready: 18,
  kb_building: 24,
  global_generating: 34,
  global_ready: 42,
  global_validated: 46,
  daily_splitting: 50,
  daily_ready: 56,
  daily_validated: 60,
  tts_launched: 62,
  text_ready: 100,
  audio_running: 98,
  audio_launched: 100,
  audio_completed: 100,
  completed: 100,
}

const PLATFORM_LOAD_TIMEOUT_MS = 30000

const getHiddenPipelineProgress = (platform = {}) => {
  if (platform.pipeline_auto_pilot_error) return 100
  const step = String(platform.pipeline_auto_pilot_step || '').trim()
  if (step && Object.prototype.hasOwnProperty.call(PIPELINE_PROGRESS_BY_STEP, step)) {
    return PIPELINE_PROGRESS_BY_STEP[step]
  }
  const status = String(platform.pipeline_status || platform.status || '').trim()
  if (status && Object.prototype.hasOwnProperty.call(PIPELINE_PROGRESS_BY_STATUS, status)) {
    return PIPELINE_PROGRESS_BY_STATUS[status]
  }
  return 8
}

// ─── Component ───────────────────────────────────────────────────────────────
export default function HRDashboard() {
  const [platforms, setPlatforms] = useState([])
  const [loading, setLoading] = useState(true)
  const [platformsError, setPlatformsError] = useState('')
  const [platformsErrorTone, setPlatformsErrorTone] = useState('error')
  const [expandedPlatform, setExpandedPlatform] = useState(null)
  const [platformAudios, setPlatformAudios] = useState({})
  const [studentEmailsByPlatform, setStudentEmailsByPlatform] = useState({})
  const [studentEmailsLoading, setStudentEmailsLoading] = useState(null)
  const [studentEmailsSaving, setStudentEmailsSaving] = useState(null)
  const [studentEmailDrafts, setStudentEmailDrafts] = useState({})
  const [expandedStudentsPlatform, setExpandedStudentsPlatform] = useState(null)
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
  // Type-to-confirm pour le delete plateforme : l'admin doit retaper le nom
  // exact pour activer le bouton destructif (registre GitHub/Stripe — friction
  // proportionnelle à l'irréversibilité de l'action).
  const [deleteConfirmTypedName, setDeleteConfirmTypedName] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [expandedAttendancePlatform, setExpandedAttendancePlatform] = useState(null)
  const [newPlatformName, setNewPlatformName] = useState('')
  const [creating, setCreating] = useState(false)
  // Modules formation disponibles (produits persistants des pipelines terminées).
  // Principe "1 RNCP = 1 module durable" : le select liste les modules, pas les
  // pipelines ni les plateformes sources.
  const [modules, setModules] = useState([])
  const [showModulesModal, setShowModulesModal] = useState(false)
  // Filtre live de la modale Modules — efface au close pour que chaque ouverture
  // reparte propre. La modale liste 1 à ~30 modules selon le RNCP roster, le
  // filtre devient utile au-delà de 5.
  const [moduleSearchQuery, setModuleSearchQuery] = useState('')
  const [formationMode, setFormationMode] = useState('existing') // 'existing' | 'new' | 'none'
  const [selectedModuleId, setSelectedModuleId] = useState('')
  const [teacherFirstName, setTeacherFirstName] = useState('')
  const [teacherColor, setTeacherColor] = useState('violet')
  const [weeklyCourseCount, setWeeklyCourseCount] = useState('2')
  const [teachingDays, setTeachingDays] = useState(['mardi', 'jeudi'])
  const [newFormTpName, setNewFormTpName] = useState('')
  const [newFormRncp, setNewFormRncp] = useState('')
  const [newFormHours, setNewFormHours] = useState('')
  // Auto-pilot : si activé, une fois le job pipeline initié on appelle l'endpoint
  // /run-auto qui chaîne toutes les étapes (REAC → KB → global → daily → content
  // → conformité locale → Word 2). L'audio se lance ensuite à la demande.
  // Sinon, comportement historique : redirection vers
  // /formation-pipeline pour validation manuelle étape par étape.
  const [autoPilot, setAutoPilot] = useState(false)
  // Mode d'exécution des étapes IA (KB, global, daily, content, review) :
  // - 'api'          : appels directs à l'API Anthropic (consomme ANTHROPIC_API_KEY)
  // - 'api_deepseek' : appels directs à l'API DeepSeek (consomme DEEPSEEK_API_KEY)
  // - 'claude_code'  : subprocess `claude` local (forfait Pro/Max via OAuth, gratuit côté API)
  // - 'test'         : skip KB/global/daily/content, injecte des DOCX/TXT pré-rédigés.
  //                    La pipeline ne tourne que finalize + conformité locale + Word 2.
  //                    Permet de valider les étapes en aval en ~5 min au lieu de 30-60.
  const [autoPilotMode, setAutoPilotMode] = useState('api')  // 'api' | 'api_deepseek' | 'claude_code' | 'test'
  const [testDocs, setTestDocs] = useState([])  // File[] uploadés pour le mode test
  const backupPollingRef = useRef({})
  const audioRef = useRef(null)
  const [showCoursFoldersModal, setShowCoursFoldersModal] = useState(false)
  const [selectedCoursPlatform, setSelectedCoursPlatform] = useState(null)
  const [cardPage, setCardPage] = useState(0)
  const [attendancePlatformId, setAttendancePlatformId] = useState('')
  const [attendanceDate, setAttendanceDate] = useState(todayDateInput)
  const [attendanceData, setAttendanceData] = useState(null)
  const [attendanceLoading, setAttendanceLoading] = useState(false)
  const [attendanceError, setAttendanceError] = useState('')
  const [attendanceSavingStudentId, setAttendanceSavingStudentId] = useState(null)
  const CARDS_PER_PAGE = 3

  // ─── Fetch data ──────────────────────────────────────────────────────
  const fetchPlatforms = async (refreshSelectedId = null) => {
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), PLATFORM_LOAD_TIMEOUT_MS)
    try {
      setPlatformsError('')
      const resp = await apiFetch('/api/hr/platforms?include_blob_stats=0', {
        signal: controller.signal,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      if (data.success) {
        setPlatforms(data.platforms)
        if (refreshSelectedId !== null) {
          const updated = data.platforms.find(p => p.id === refreshSelectedId)
          if (updated) setSelectedPlatform(updated)
        }
        // Sync selectedCoursPlatform si la modale Cours est ouverte sur la
        // plateforme rafraîchie (sinon le slide-to-confirm restait sur l'ancien
        // upload_locked après lock/unlock).
        setSelectedCoursPlatform((prev) => {
          if (!prev) return prev
          const fresh = data.platforms.find(p => p.id === prev.id)
          return fresh || prev
        })
      } else {
        setPlatformsErrorTone('error')
        setPlatformsError(data.error || 'Impossible de charger les plateformes.')
      }
    } catch (e) {
      console.error('Erreur chargement plateformes:', e)
      setPlatformsErrorTone(e.name === 'AbortError' ? 'warning' : 'error')
      setPlatformsError(
        e.name === 'AbortError'
          ? 'Actualisation des plateformes encore en cours. Vous pouvez relancer le chargement.'
          : 'Impossible de charger les plateformes.'
      )
    } finally {
      window.clearTimeout(timeoutId)
      setLoading(false)
    }
  }

  const fetchAudios = async (platformId) => {
    setAudiosLoading(platformId)
    try {
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/audios`)
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

  const fetchStudentEmails = async (platformId) => {
    setStudentEmailsLoading(platformId)
    try {
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/student-emails`)
      const data = await resp.json()
      if (data.success) {
        setStudentEmailsByPlatform(prev => ({ ...prev, [platformId]: data.recipients || [] }))
      }
    } catch (e) {
      console.error('Erreur chargement emails élèves:', e)
    } finally {
      setStudentEmailsLoading(null)
    }
  }

  const handleToggleStudentEmails = (platformId) => {
    setExpandedStudentsPlatform(prev => {
      const next = prev === platformId ? null : platformId
      if (next && !studentEmailsByPlatform[platformId]) fetchStudentEmails(platformId)
      return next
    })
  }

  const handleToggleAttendance = (platformId) => {
    setExpandedAttendancePlatform(prev => {
      const next = prev === platformId ? null : platformId
      if (next) {
        setAttendancePlatformId(String(platformId))
        fetchAttendance(platformId, attendanceDate)
      }
      return next
    })
  }

  const handleStudentEmailDraftChange = (platformId, value) => {
    setStudentEmailDrafts(prev => ({ ...prev, [platformId]: value }))
  }

  const handleAddStudentEmails = async (platformId) => {
    const draft = studentEmailDrafts[platformId] || ''
    if (!draft.trim()) return
    setStudentEmailsSaving(platformId)
    try {
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/student-emails`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emails: draft }),
      })
      const data = await resp.json()
      if (data.success) {
        setStudentEmailsByPlatform(prev => ({ ...prev, [platformId]: data.recipients || [] }))
        setStudentEmailDrafts(prev => ({ ...prev, [platformId]: '' }))
      } else {
        alert(data.error || 'Impossible d’ajouter les emails')
      }
    } catch (e) {
      console.error('Erreur ajout emails élèves:', e)
      alert('Impossible d’ajouter les emails')
    } finally {
      setStudentEmailsSaving(null)
    }
  }

  const handleDeleteStudentEmail = async (platformId, recipientId) => {
    try {
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/student-emails/${recipientId}`, {
        method: 'DELETE',
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || data.success === false) {
        alert(data.error || 'Impossible de supprimer cet email')
        return
      }
      setStudentEmailsByPlatform(prev => ({
        ...prev,
        [platformId]: (prev[platformId] || []).filter((item) => item.id !== recipientId),
      }))
    } catch (e) {
      console.error('Erreur suppression email élève:', e)
      alert('Impossible de supprimer cet email')
    }
  }

  const handleAudiosPublished = (platformId) => {
    fetchAudios(platformId)
    fetchPlatforms(platformId)
  }

  useEffect(() => {
    fetchPlatforms()
  }, [])

  useEffect(() => {
    if (platforms.length > 0 && !attendancePlatformId) {
      setAttendancePlatformId(String(platforms[0].id))
    }
  }, [platforms, attendancePlatformId])

  useEffect(() => {
    const bg = darkMode ? '#0f172a' : '#F8F7F5'
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
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/toggle-lock`, {
        method: 'POST',
      })
      const data = await resp.json()
      if (data.success) fetchPlatforms()
    } catch (e) {
      console.error('Erreur lock:', e)
    }
  }

  const handleBackupAndUnlock = async (platformId) => {
    try {
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/backup-and-unlock`, {
        method: 'POST',
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
        const resp = await apiFetch(`/api/hr/platforms/${platformId}/backup-status`)
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
        const resp = await apiFetch(`/api/hr/platforms/${deleteConfirm.platformId}/audios/${encodeURIComponent(deleteConfirm.filename)}`, {
          method: 'DELETE',
        })
        const data = await resp.json()
        if (data.success) {
          fetchAudios(deleteConfirm.platformId)
          fetchPlatforms()
          setDeleteConfirm(null)
        }
      } else if (deleteConfirm.type === 'pdf') {
        const resp = await apiFetch(`/api/hr/platforms/${deleteConfirm.platformId}/pdf`, {
          method: 'DELETE',
        })
        const data = await resp.json()
        if (data.success) {
          fetchPlatforms(deleteConfirm.platformId)
          setDeleteConfirm(null)
        }
      } else if (deleteConfirm.type === 'module') {
        if (deleteConfirmTypedName !== deleteConfirm.confirmKey) return
        const resp = await apiFetch(`/api/hr/formation-modules/${deleteConfirm.moduleId}`, {
          method: 'DELETE',
        })
        const data = await resp.json()
        if (data.success) {
          fetchModules()
          setDeleteConfirm(null)
          setDeleteConfirmTypedName('')
        } else {
          alert(data.error || 'Erreur lors de la suppression du module')
        }
      } else if (deleteConfirm.type === 'platform') {
        if (deleteConfirmTypedName !== deleteConfirm.platformName) return
        const resp = await apiFetch(`/api/hr/platforms/${deleteConfirm.platformId}`, {
          method: 'DELETE',
        })
        const data = await resp.json()
        if (data.success) {
          fetchPlatforms()
          fetchModules()  // les modules "fait main" associés ont aussi été supprimés
          setDeleteConfirm(null)
          setDeleteConfirmTypedName('')
          if (selectedPlatform?.id === deleteConfirm.platformId) setSelectedPlatform(null)
          if (expandedPlatform === deleteConfirm.platformId) setExpandedPlatform(null)
        } else {
          alert(data.error || 'Erreur lors de la suppression de la plateforme')
        }
      }
    } catch (e) {
      console.error('Erreur suppression:', e)
    } finally {
      setDeletingItem(false)
    }
  }

  const handleDeleteModule = (moduleId) => {
    const mod = modules.find((m) => m.id === moduleId)
    if (!mod) return
    // Clé de confirmation = "TP CRCD · 2026-v5" — assez précise pour
    // forcer une lecture attentive sans rendre la saisie pénible.
    const confirmKey = `${mod.tp_name} · ${mod.version}`
    setDeleteConfirmTypedName('')
    setDeleteConfirm({
      type: 'module',
      moduleId,
      tpName: mod.tp_name,
      version: mod.version,
      rncpCode: mod.rncp_code,
      confirmKey,
    })
  }

  const handleDeletePlatform = (platformId) => {
    const platform = platforms.find((p) => p.id === platformId)
    if (!platform) return
    setDeleteConfirmTypedName('')
    setDeleteConfirm({
      type: 'platform',
      platformId,
      platformName: platform.name,
    })
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

      const resp = await apiFetch(`/api/hr/platforms/${platformId}/upload-pdf-rag`, {
        method: 'POST',
        body: formData,
      })
      const data = await resp.json()
      if (data.success) fetchPlatforms(platformId)
    } catch (e) {
      console.error('Erreur upload PDF:', e)
    } finally {
      setPdfUploading(null)
    }
  }

  const handleSetCourseTime = async (dateCours, heureCours, weekdays = null) => {
    try {
      const payload = { date_cours: dateCours, heure_cours: heureCours }
      if (Array.isArray(weekdays)) payload.weekdays = weekdays
      const resp = await apiFetch(`/api/hr/platforms/${courseTimePlatformId}/config-cours`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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

  const fetchAttendance = async (platformId = attendancePlatformId, courseDate = attendanceDate) => {
    if (!platformId || !courseDate) return
    setAttendanceLoading(true)
    setAttendanceError('')
    try {
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/attendance?course_date=${encodeURIComponent(courseDate)}`)
      const data = await resp.json()
      if (resp.ok && data.success) {
        setAttendanceData(data)
      } else {
        setAttendanceError(data.error || 'Impossible de charger les présences')
      }
    } catch (e) {
      console.error('Erreur chargement présences:', e)
      setAttendanceError('Impossible de charger les présences')
    } finally {
      setAttendanceLoading(false)
    }
  }

  const updateAttendanceDraft = (studentId, updater) => {
    setAttendanceData((current) => {
      if (!current) return current
      return {
        ...current,
        students: current.students.map((student) => {
          if (student.id !== studentId) return student
          const nextAttendance = typeof updater === 'function'
            ? updater(student.attendance)
            : { ...student.attendance, ...updater }
          return { ...student, attendance: nextAttendance }
        }),
      }
    })
  }

  const handleSaveAttendance = async (student, platformId = attendancePlatformId, courseDate = attendanceDate) => {
    setAttendanceSavingStudentId(student.id)
    setAttendanceError('')
    try {
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/attendance/${student.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          course_date: courseDate,
          slots: student.attendance?.slots || [],
          status: student.attendance?.status || '',
          notes: student.attendance?.notes || '',
        }),
      })
      const data = await resp.json()
      if (resp.ok && data.success) {
        updateAttendanceDraft(student.id, { ...data.record, source: 'saved' })
      } else {
        setAttendanceError(data.error || 'Impossible d’enregistrer la présence')
      }
    } catch (e) {
      console.error('Erreur sauvegarde présence:', e)
      setAttendanceError('Impossible d’enregistrer la présence')
    } finally {
      setAttendanceSavingStudentId(null)
    }
  }

  const handleExportAttendance = async (week = null, platformId = attendancePlatformId) => {
    if (!platformId) return
    try {
      const params = week?.week_start
        ? `?week_start=${encodeURIComponent(week.week_start)}&week_end=${encodeURIComponent(week.week_end || week.week_start)}`
        : ''
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/attendance/export${params}`)
      if (!resp.ok) {
        setAttendanceError('Impossible de générer l’export Excel')
        return
      }
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = week?.week_start
        ? `presences-${platformId}-semaine-${week.week_start}.xlsx`
        : `presences-${platformId}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Erreur export présences:', e)
      setAttendanceError('Impossible de générer l’export Excel')
    }
  }

  const fetchModules = async () => {
    try {
      const resp = await apiFetch('/api/hr/formation-modules')
      const data = await resp.json()
      if (data.success) setModules(data.modules || [])
    } catch (e) {
      console.error('Erreur chargement modules:', e)
    }
  }

  // Modules filtrés + triés pour la modale Catalogue. Réutilisables d'abord
  // (les modules actionnables remontent), puis créés en dernier (récents en
  // haut, plus pertinent que par tp_name pour l'admin qui suit la production).
  const filteredModules = useMemo(() => {
    const q = moduleSearchQuery.trim().toLowerCase()
    const base = q
      ? modules.filter(m =>
          (m.tp_name || '').toLowerCase().includes(q) ||
          String(m.rncp_code || '').toLowerCase().includes(q)
        )
      : modules
    return [...base].sort((a, b) => {
      if (!!a.reusable !== !!b.reusable) return a.reusable ? -1 : 1
      return String(b.created_at || '').localeCompare(String(a.created_at || ''))
    })
  }, [modules, moduleSearchQuery])

  const closeModulesModal = () => {
    setShowModulesModal(false)
    setModuleSearchQuery('')
  }

  const resetCreateForm = () => {
    setNewPlatformName('')
    setFormationMode('new')
    setSelectedModuleId('')
    setTeacherFirstName('')
    setTeacherColor('violet')
    setWeeklyCourseCount('2')
    setTeachingDays(['mardi', 'jeudi'])
    setNewFormTpName('')
    setNewFormRncp('')
    setNewFormHours('')
    setAutoPilot(true)
    setAutoPilotMode('api_deepseek')
  }

  // Ouvre la modale en pré-sélectionnant le mode "Nouvelle formation".
  // Utilisé par le bouton "+ Créer un nouveau module" dans la modale Modules.
  const openCreateModuleFlow = () => {
    resetCreateForm()
    fetchModules()
    setFormationMode('new')
    setShowModulesModal(false)
    setShowCreateModal(true)
  }

  const openCreateModal = () => {
    resetCreateForm()
    fetchModules()
    setShowModulesModal(false)
    setShowCreateModal(true)
  }

  const showDashboardView = () => {
    setShowModulesModal(false)
    setShowCreateModal(false)
    setModuleSearchQuery('')
  }

  const showModulesView = () => {
    fetchModules()
    setShowCreateModal(false)
    setShowModulesModal(true)
  }

  useEffect(() => {
    if (expandedAttendancePlatform) {
      fetchAttendance(expandedAttendancePlatform, attendanceDate)
    }
  }, [expandedAttendancePlatform, attendanceDate])

  const handleCreatePlatform = async () => {
    const teacherName = teacherFirstName.trim()
    const trainingTitle = newFormTpName.trim()
    const platformName = newPlatformName.trim() || (teacherName && trainingTitle ? `${teacherName} · ${trainingTitle}` : '')
    if (!platformName) return

    // ─── Branche TEST : bypass /api/hr/platforms, envoie multipart à /init-test ─
    // Crée plateforme + job + folders + segments depuis les DOCX, lance auto-pilot
    // qui skippera KB/global/daily/content. Test ~5 min pipeline en aval.
    if (formationMode === 'new' && autoPilot && autoPilotMode === 'test') {
      const tpName = newFormTpName.trim()
      const rncp = newFormRncp.trim()
      const trainingDaysCount = parseInt(newFormHours, 10)
      if (!tpName || !rncp || !trainingDaysCount || trainingDaysCount <= 0) {
        alert('Nom du TP, code RNCP et nombre de journées requis')
        return
      }
      const totalHours = trainingDaysCount * 7
      const expectedDocs = trainingDaysCount
      if (testDocs.length !== expectedDocs) {
        alert(`Tu dois fournir exactement ${expectedDocs} fichier(s) (1 par journée de 7h). Reçu : ${testDocs.length}`)
        return
      }

      setCreating(true)
      try {
        const fd = new FormData()
        fd.append('platform_name', newPlatformName.trim())
        fd.append('tp_name', tpName)
        fd.append('rncp_code', rncp)
        fd.append('total_hours', String(totalHours))
        fd.append('tts_mode', 'mock')  // forcé en test
        fd.append('auto_pilot', 'true')
        testDocs.forEach((f) => fd.append('docs', f))

        const resp = await apiFetch('/api/formation/init-test', {
          method: 'POST',
          body: fd,
        })
        const data = await resp.json()
        if (resp.status === 202 && data.ok) {
          setShowCreateModal(false)
          resetCreateForm()
          setTestDocs([])
          fetchPlatforms()
          window.open(`/formation-pipeline?job=${data.job_id}`, '_blank')
        } else {
          alert(`Erreur init-test : ${data.error || 'inconnue'}`)
        }
      } catch (e) {
        console.error('init-test failed:', e)
        alert('Impossible de lancer le test : ' + e.message)
      } finally {
        setCreating(false)
      }
      return
    }

    // ─── Flow normal (API ou Claude Code) ─────────────────────────────────────
    // Validation selon le mode
    let body = { name: platformName }
    if (formationMode === 'existing') {
      if (!selectedModuleId) {
        alert('Sélectionne un module ou bascule sur "Nouvelle formation"')
        return
      }
      body.module_id = parseInt(selectedModuleId, 10)
    } else if (formationMode === 'new') {
      const tpName = trainingTitle
      const rncp = newFormRncp.trim()
      const trainingDaysCount = parseInt(newFormHours, 10)
      const weeklyCount = parseInt(weeklyCourseCount, 10)
      if (!teacherName || !tpName || !rncp || !trainingDaysCount || trainingDaysCount <= 0) {
        alert('Prénom du professeur IA, nom de formation, code RNCP et nombre de journées requis')
        return
      }
      if (!weeklyCount || weeklyCount <= 0 || teachingDays.length === 0) {
        alert('Indique la fréquence de cours et au moins un jour')
        return
      }
      if (weeklyCount !== teachingDays.length) {
        alert('Le nombre de cours par semaine doit correspondre aux jours sélectionnés')
        return
      }
      body.new_formation = {
        tp_name: tpName,
        rncp_code: rncp,
        total_hours: trainingDaysCount * 7,
        schedule: {
          total_training_days: trainingDaysCount,
          weekly_course_count: weeklyCount,
          weekdays: teachingDays,
          start_time: '09:00',
        },
      }
    }
    // formationMode === 'none' → body reste {name} (plateforme vide, comportement historique)

    setCreating(true)
    try {
      const resp = await apiFetch('/api/hr/platforms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await resp.json()
      if (data.success) {
        const pipelineJobId = data.platform?.pipeline_job_id
        // Si une pipeline a été lancée et que l'auto-pilot est demandé, on
        // déclenche l'enchaînement automatique avant de fermer la modale.
        if (pipelineJobId && formationMode === 'new' && autoPilot) {
          try {
            const autoResp = await apiFetch(
              `/api/formation/${pipelineJobId}/run-auto`,
              {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  tts_mode: 'fish_audio',
                  use_claude_code: false,
                  model: 'pro',
                  generate_audio: false,
                }),
              },
            )
            const autoData = await autoResp.json()
            if (autoResp.status !== 202 && autoData.error) {
              alert(`Auto-pilot non démarré : ${autoData.error}`)
            }
          } catch (e) {
            console.error('Auto-pilot start failed:', e)
            alert('Plateforme créée, mais l\'auto-pilot n\'a pas pu démarrer.')
          }
        }
        setShowCreateModal(false)
        resetCreateForm()
        setShowModulesModal(false)
        setCardPage(Math.floor(platforms.length / CARDS_PER_PAGE))
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

  // Polling des plateformes en pending (clone blobs en cours, ou pipeline en cours)
  // pour rafraîchir l'UI quand elles passent à 'ready' ou 'error'.
  useEffect(() => {
    const hasPending = platforms.some(p => p.status === 'pending')
    if (!hasPending) return
    const interval = setInterval(fetchPlatforms, 5000)
    return () => clearInterval(interval)
  }, [platforms])

  // ─── Render ──────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center" style={{ backgroundColor: darkMode ? '#0f172a' : '#F8F7F5', fontFamily: 'Inter, sans-serif' }}>
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
    bg: '#F8F7F5',
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
  const platformsAlertIsWarning = platformsErrorTone === 'warning'

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
          <div className="mx-auto max-w-7xl px-6 pt-4">
            <div className="flex items-center justify-end gap-4">
              <div className="flex items-center gap-2">
                {/* Back to admin — tertiary navigation, muted text */}
                <a
                  href="/admin"
                  className="flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
                  style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
                  title="Revenir à l'administration P1"
                >
                  <Icon name="arrow_back" className="text-base" />
                  <span>Retour Admin</span>
                </a>
              </div>
            </div>

            <nav className="mt-5 flex items-end gap-10" aria-label="Navigation dashboard formations">
              <SkoolTab
                active={!showModulesModal && !showCreateModal}
                onClick={showDashboardView}
                label="Mes professeurs IA"
                colors={colors}
              />
              <SkoolTab
                active={showModulesModal}
                onClick={showModulesView}
                label="Réutiliser un ancien professeur IA"
                colors={colors}
              />
              <SkoolTab
                active={showCreateModal}
                onClick={openCreateModal}
                label="Nouveau professeur IA"
                colors={colors}
              />
            </nav>
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
          {platformsError && (
            <div
              className="mb-6 flex flex-col gap-3 rounded-lg border px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
              style={{
                backgroundColor: platformsAlertIsWarning
                  ? (darkMode ? 'rgba(146, 64, 14, 0.18)' : '#fffbeb')
                  : (darkMode ? 'rgba(127, 29, 29, 0.18)' : '#fef2f2'),
                borderColor: platformsAlertIsWarning
                  ? (darkMode ? 'rgba(251, 191, 36, 0.32)' : '#fde68a')
                  : (darkMode ? 'rgba(248, 113, 113, 0.28)' : '#fecaca'),
                color: platformsAlertIsWarning
                  ? (darkMode ? '#fde68a' : '#92400e')
                  : (darkMode ? '#fecaca' : '#991b1b'),
              }}
            >
              <div className="flex min-w-0 items-center gap-3">
                <Icon name="warning" className="text-base" />
                <span>{platformsError}</span>
              </div>
              <button
                type="button"
                onClick={() => fetchPlatforms()}
                disabled={loading}
                className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                style={{
                  backgroundColor: platformsAlertIsWarning
                    ? (darkMode ? 'rgba(146, 64, 14, 0.28)' : '#fff')
                    : (darkMode ? 'rgba(127, 29, 29, 0.28)' : '#fff'),
                  borderColor: platformsAlertIsWarning
                    ? (darkMode ? 'rgba(251, 191, 36, 0.4)' : '#fde68a')
                    : (darkMode ? 'rgba(248, 113, 113, 0.36)' : '#fecaca'),
                  color: platformsAlertIsWarning
                    ? (darkMode ? '#fde68a' : '#92400e')
                    : (darkMode ? '#fecaca' : '#991b1b'),
                }}
              >
                <Icon name="refresh" className="text-sm" />
                {loading ? 'Chargement...' : 'Réessayer'}
              </button>
            </div>
          )}

          {showModulesModal ? (
            <ModulesCatalogueView
              colors={colors}
              modules={filteredModules}
              moduleSearchQuery={moduleSearchQuery}
              onModuleSearchChange={setModuleSearchQuery}
              onBack={closeModulesModal}
              onCreateModule={openCreateModuleFlow}
              onUseModule={(moduleId) => {
                openCreateModal()
                setFormationMode('existing')
                setSelectedModuleId(String(moduleId))
              }}
              onDeleteModule={handleDeleteModule}
            />
          ) : showCreateModal ? (
            <CreatePlatformView
              colors={colors}
              darkMode={darkMode}
              modules={modules}
              newPlatformName={newPlatformName}
              setNewPlatformName={setNewPlatformName}
              teacherFirstName={teacherFirstName}
              setTeacherFirstName={setTeacherFirstName}
              teacherColor={teacherColor}
              setTeacherColor={setTeacherColor}
              weeklyCourseCount={weeklyCourseCount}
              setWeeklyCourseCount={setWeeklyCourseCount}
              teachingDays={teachingDays}
              setTeachingDays={setTeachingDays}
              formationMode={formationMode}
              setFormationMode={setFormationMode}
              selectedModuleId={selectedModuleId}
              setSelectedModuleId={setSelectedModuleId}
              newFormTpName={newFormTpName}
              setNewFormTpName={setNewFormTpName}
              newFormRncp={newFormRncp}
              setNewFormRncp={setNewFormRncp}
              newFormHours={newFormHours}
              setNewFormHours={setNewFormHours}
              autoPilot={autoPilot}
              setAutoPilot={setAutoPilot}
              autoPilotMode={autoPilotMode}
              setAutoPilotMode={setAutoPilotMode}
              testDocs={testDocs}
              setTestDocs={setTestDocs}
              creating={creating}
              onCreate={handleCreatePlatform}
              onCancel={() => { setShowCreateModal(false); resetCreateForm() }}
            />
          ) : (
            <PlatformCardsView
              platforms={platforms}
              cardPage={cardPage}
              setCardPage={setCardPage}
              cardsPerPage={CARDS_PER_PAGE}
              expandedPlatform={expandedPlatform}
              platformAudios={platformAudios}
              audiosLoading={audiosLoading}
              playingAudio={playingAudio}
              pdfUploading={pdfUploading}
              audioRef={audioRef}
              colors={colors}
              darkMode={darkMode}
              studentEmailsByPlatform={studentEmailsByPlatform}
              expandedStudentsPlatform={expandedStudentsPlatform}
              expandedAttendancePlatform={expandedAttendancePlatform}
              studentEmailsLoading={studentEmailsLoading}
              studentEmailsSaving={studentEmailsSaving}
              studentEmailDrafts={studentEmailDrafts}
              attendanceDate={attendanceDate}
              attendanceData={attendanceData}
              attendanceLoading={attendanceLoading}
              attendanceError={attendanceError}
              attendanceSavingStudentId={attendanceSavingStudentId}
              onExpand={handleExpandPlatform}
              onToggleStudentEmails={handleToggleStudentEmails}
              onToggleAttendance={handleToggleAttendance}
              onStudentEmailDraftChange={handleStudentEmailDraftChange}
              onAddStudentEmails={handleAddStudentEmails}
              onDeleteStudentEmail={handleDeleteStudentEmail}
              onAttendanceDateChange={setAttendanceDate}
              onRefreshAttendance={(platformId) => fetchAttendance(platformId, attendanceDate)}
              onUpdateAttendanceDraft={updateAttendanceDraft}
              onSaveAttendance={(student, platformId) => handleSaveAttendance(student, platformId, attendanceDate)}
              onExportAttendance={(week, platformId) => handleExportAttendance(week, platformId)}
              onOpenPdfModal={(platform) => {
                setSelectedPlatform(platform)
                setShowPdfModal(true)
              }}
              onOpenCourseTimeModal={async (platform) => {
                setCourseTimePlatformId(platform.id)
                try {
                  const resp = await apiFetch(`/api/hr/platforms/${platform.id}/course-time`)
                  const data = await resp.json()
                  if (data.success) setCurrentCourseTime(data)
                  else setCurrentCourseTime(null)
                } catch { setCurrentCourseTime(null) }
                setShowCourseTimeModal(true)
              }}
              onDeleteAudio={handleDeleteAudio}
              onOpenCoursFolders={handleOpenCoursFolders}
              onPlayAudio={handlePlayAudio}
              onPdfUpload={handlePdfUpload}
              onDeletePdf={handleDeletePdf}
              onDeletePlatform={handleDeletePlatform}
            />
          )}
        </div>
      </div>

      {/* Modal Audios */}
      {showAudiosModal && selectedPlatformId && (() => {
        const audiosPlatform = platforms.find(p => p.id === selectedPlatformId)
        return (
          <AudiosModal
            platformId={selectedPlatformId}
            audios={platformAudios[selectedPlatformId] || []}
            loading={audiosLoading === selectedPlatformId}
            onClose={() => setShowAudiosModal(false)}
            darkMode={darkMode}
            recorderUrl={`${(audiosPlatform?.frontend_url || window.location.origin)}/recorder?p=${selectedPlatformId}`}
            onRefreshAudios={() => fetchAudios(selectedPlatformId)}
            uploadLocked={!!audiosPlatform?.upload_locked}
            backupJob={backupJobs[selectedPlatformId] || null}
            onLock={() => handleLock(selectedPlatformId)}
            onBackupAndUnlock={() => handleBackupAndUnlock(selectedPlatformId)}
          />
        )
      })()}

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
          schedule={currentCourseTime?.schedule}
        />
      )}

      {/* Modal Cours Folders */}
      {showCoursFoldersModal && selectedCoursPlatform && (
        <CoursFoldersModal
          platformId={selectedCoursPlatform.id}
          platformName={selectedCoursPlatform.name}
          onClose={() => setShowCoursFoldersModal(false)}
          onAudiosPublished={handleAudiosPublished}
        />
      )}

      {/* Modal confirmation suppression — branche par type :
          - audio/pdf : confirmation simple (atomique, peu d'impact)
          - platform : confirmation enrichie + type-to-confirm (cascade,
            irréversibilité, registre Examiner's Desk per DESIGN.md). */}
      {deleteConfirm && deleteConfirm.type !== 'platform' && (
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

      {/* ── Modal de suppression plateforme — registre Examiner's Desk ─────
          Cascade : tout le contenu pédagogique (cours, segments, KB, jobs
          pipeline) + les modules "fait main" liés (la plateforme = le module).
          Les modules pipeline qui pointaient vers cette plateforme restent au
          catalogue (source_platform_id devient NULL côté backend). */}
      {deleteConfirm && deleteConfirm.type === 'platform' && (() => {
        const matched = deleteConfirmTypedName === deleteConfirm.platformName
        return (
          <div
            className="fixed inset-0 z-[60] flex items-center justify-center p-4"
            style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
            onClick={() => {
              if (!deletingItem) {
                setDeleteConfirm(null)
                setDeleteConfirmTypedName('')
              }
            }}
          >
            <div
              className="bg-white rounded-2xl shadow-2xl overflow-hidden"
              style={{ width: '100%', maxWidth: '480px' }}
              onClick={(e) => e.stopPropagation()}
            >
              <div
                className="flex items-start gap-3 px-6 py-5"
                style={{ borderBottom: '1px solid #e2e8f0' }}
              >
                <div
                  className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg"
                  style={{ backgroundColor: '#fee2e2' }}
                >
                  <Icon name="delete_forever" style={{ color: '#dc2626', fontSize: '20px' }} />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-semibold leading-snug tracking-tight" style={{ color: '#0f172a' }}>
                    Supprimer la plateforme
                  </h3>
                  <p className="mt-0.5 text-xs" style={{ color: '#64748b' }}>
                    Action définitive · ne peut pas être annulée
                  </p>
                </div>
              </div>

              <div className="px-6 py-5 space-y-4">
                <p className="text-sm leading-relaxed" style={{ color: '#334155' }}>
                  Vous allez supprimer définitivement la plateforme{' '}
                  <strong style={{ color: '#0f172a' }}>{deleteConfirm.platformName}</strong>{' '}
                  et son contenu pédagogique en base.
                </p>

                <div
                  className="rounded-lg px-4 py-3"
                  style={{ backgroundColor: '#fef2f2', border: '1px solid #fee2e2' }}
                >
                  <p
                    className="text-[10px] font-semibold uppercase mb-2"
                    style={{ color: '#b91c1c', letterSpacing: '0.18em' }}
                  >
                    Sera supprimé
                  </p>
                  <ul className="space-y-1 text-xs leading-relaxed" style={{ color: '#7f1d1d' }}>
                    <li>· Cours générés (textes, segments, passes IA)</li>
                    <li>· Knowledge base et programmes journées</li>
                    <li>· Dossiers cours, configuration horaire</li>
                    <li>· Jobs de pipeline liés à cette promo</li>
                    <li>· Module "fait main" associé (si la plateforme en a un)</li>
                  </ul>
                </div>

                <div
                  className="rounded-lg px-4 py-3"
                  style={{ backgroundColor: '#f8fafc', border: '1px solid #e2e8f0' }}
                >
                  <p
                    className="text-[10px] font-semibold uppercase mb-2"
                    style={{ color: '#64748b', letterSpacing: '0.18em' }}
                  >
                    Préservé
                  </p>
                  <ul className="space-y-1 text-xs leading-relaxed" style={{ color: '#475569' }}>
                    <li>· Modules pipeline réutilisables (restent au catalogue)</li>
                    <li>· Logs et historique des visites (audit trail)</li>
                    <li>· Blobs Azure (PDFs, audios) — à nettoyer manuellement si besoin</li>
                  </ul>
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor="delete-platform-confirm-input"
                    className="block text-xs font-medium"
                    style={{ color: '#334155' }}
                  >
                    Pour confirmer, tapez le nom exact de la plateforme :{' '}
                    <span
                      className="font-mono text-xs px-1.5 py-0.5 rounded"
                      style={{ backgroundColor: '#f1f5f9', color: '#0f172a' }}
                    >
                      {deleteConfirm.platformName}
                    </span>
                  </label>
                  <input
                    id="delete-platform-confirm-input"
                    type="text"
                    autoFocus
                    autoComplete="off"
                    value={deleteConfirmTypedName}
                    onChange={(e) => setDeleteConfirmTypedName(e.target.value)}
                    disabled={deletingItem}
                    placeholder={deleteConfirm.platformName}
                    className="w-full rounded-lg px-3 py-2 text-sm outline-none transition-colors focus:ring-2"
                    style={{
                      backgroundColor: '#ffffff',
                      color: '#0f172a',
                      border: `1px solid ${matched ? '#86efac' : '#e2e8f0'}`,
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && matched && !deletingItem) confirmDelete()
                      if (e.key === 'Escape' && !deletingItem) {
                        setDeleteConfirm(null)
                        setDeleteConfirmTypedName('')
                      }
                    }}
                  />
                </div>
              </div>

              <div
                className="flex gap-3 px-6 py-4"
                style={{ borderTop: '1px solid #e2e8f0', backgroundColor: '#fafafa' }}
              >
                <button
                  onClick={() => {
                    setDeleteConfirm(null)
                    setDeleteConfirmTypedName('')
                  }}
                  disabled={deletingItem}
                  className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                  style={{ backgroundColor: 'transparent', color: '#334155', border: '1px solid #e2e8f0' }}
                >
                  Annuler
                </button>
                <button
                  onClick={confirmDelete}
                  disabled={deletingItem || !matched}
                  className="flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-colors disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: matched ? '#dc2626' : '#fca5a5',
                    opacity: deletingItem ? 0.6 : 1,
                  }}
                  onMouseEnter={(e) => { if (matched && !deletingItem) e.currentTarget.style.backgroundColor = '#b91c1c' }}
                  onMouseLeave={(e) => { if (matched && !deletingItem) e.currentTarget.style.backgroundColor = '#dc2626' }}
                >
                  {deletingItem ? 'Suppression…' : 'Supprimer définitivement'}
                </button>
              </div>
            </div>
          </div>
        )
      })()}

      {/* ── Modal de suppression module catalogue — registre Examiner's Desk ─
          Le module est un produit durable (1 RNCP = 1 module) — supprimer
          le retire du catalogue mais préserve la pipeline source et la
          plateforme source. Bloqué côté backend si une plateforme l'utilise
          encore (réponse 409 explicite). Type-to-confirm sur "<TP> · <vN>"
          pour forcer une lecture attentive du module à supprimer. */}
      {deleteConfirm && deleteConfirm.type === 'module' && (() => {
        const matched = deleteConfirmTypedName === deleteConfirm.confirmKey
        return (
          <div
            className="fixed inset-0 z-[60] flex items-center justify-center p-4"
            style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
            onClick={() => {
              if (!deletingItem) {
                setDeleteConfirm(null)
                setDeleteConfirmTypedName('')
              }
            }}
          >
            <div
              className="bg-white rounded-2xl shadow-2xl overflow-hidden"
              style={{ width: '100%', maxWidth: '480px' }}
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div
                className="flex items-start gap-3 px-6 py-5"
                style={{ borderBottom: '1px solid #e2e8f0' }}
              >
                <div
                  className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg"
                  style={{ backgroundColor: '#fee2e2' }}
                >
                  <Icon name="delete_forever" style={{ color: '#dc2626', fontSize: '20px' }} />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-semibold leading-snug tracking-tight" style={{ color: '#0f172a' }}>
                    Retirer ce module du catalogue
                  </h3>
                  <p className="mt-0.5 text-xs" style={{ color: '#64748b' }}>
                    Le module disparaît de la liste · pipeline source préservée
                  </p>
                </div>
              </div>

              {/* Body */}
              <div className="px-6 py-5 space-y-4">
                <div
                  className="rounded-lg px-4 py-3"
                  style={{ backgroundColor: '#f8fafc', border: '1px solid #e2e8f0' }}
                >
                  <p
                    className="text-[10px] font-semibold uppercase mb-1.5"
                    style={{ color: '#64748b', letterSpacing: '0.18em' }}
                  >
                    Module concerné
                  </p>
                  <p className="text-sm font-semibold" style={{ color: '#0f172a' }}>
                    {deleteConfirm.tpName}
                  </p>
                  <p
                    className="mt-0.5 text-xs"
                    style={{ color: '#64748b', fontVariantNumeric: 'tabular-nums' }}
                  >
                    RNCP {deleteConfirm.rncpCode || '—'} · version{' '}
                    <span style={{ fontFamily: '"Fira Code", monospace', color: '#334155' }}>
                      {deleteConfirm.version}
                    </span>
                  </p>
                </div>

                <div
                  className="rounded-lg px-4 py-3"
                  style={{ backgroundColor: '#fef2f2', border: '1px solid #fee2e2' }}
                >
                  <p
                    className="text-[10px] font-semibold uppercase mb-2"
                    style={{ color: '#b91c1c', letterSpacing: '0.18em' }}
                  >
                    Sera retiré
                  </p>
                  <ul className="space-y-1 text-xs leading-relaxed" style={{ color: '#7f1d1d' }}>
                    <li>· L'entrée du module dans le catalogue</li>
                    <li>· La possibilité de l'utiliser pour créer de nouvelles promos</li>
                  </ul>
                </div>

                <div
                  className="rounded-lg px-4 py-3"
                  style={{ backgroundColor: '#f8fafc', border: '1px solid #e2e8f0' }}
                >
                  <p
                    className="text-[10px] font-semibold uppercase mb-2"
                    style={{ color: '#64748b', letterSpacing: '0.18em' }}
                  >
                    Préservé
                  </p>
                  <ul className="space-y-1 text-xs leading-relaxed" style={{ color: '#475569' }}>
                    <li>· La pipeline source (jobs, KB, programmes journées)</li>
                    <li>· La plateforme source et ses cours générés</li>
                    <li>· Les blobs Azure (PDFs, audios) du module</li>
                    <li>· Les promos déjà créées qui utilisent ce module continuent de fonctionner</li>
                  </ul>
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor="delete-module-confirm-input"
                    className="block text-xs font-medium"
                    style={{ color: '#334155' }}
                  >
                    Pour confirmer, tapez :{' '}
                    <span
                      className="font-mono text-xs px-1.5 py-0.5 rounded"
                      style={{ backgroundColor: '#f1f5f9', color: '#0f172a' }}
                    >
                      {deleteConfirm.confirmKey}
                    </span>
                  </label>
                  <input
                    id="delete-module-confirm-input"
                    type="text"
                    autoFocus
                    autoComplete="off"
                    value={deleteConfirmTypedName}
                    onChange={(e) => setDeleteConfirmTypedName(e.target.value)}
                    disabled={deletingItem}
                    placeholder={deleteConfirm.confirmKey}
                    className="w-full rounded-lg px-3 py-2 text-sm outline-none transition-colors focus:ring-2"
                    style={{
                      backgroundColor: '#ffffff',
                      color: '#0f172a',
                      border: `1px solid ${matched ? '#86efac' : '#e2e8f0'}`,
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && matched && !deletingItem) confirmDelete()
                      if (e.key === 'Escape' && !deletingItem) {
                        setDeleteConfirm(null)
                        setDeleteConfirmTypedName('')
                      }
                    }}
                  />
                </div>
              </div>

              {/* Footer */}
              <div
                className="flex gap-3 px-6 py-4"
                style={{ borderTop: '1px solid #e2e8f0', backgroundColor: '#fafafa' }}
              >
                <button
                  onClick={() => {
                    setDeleteConfirm(null)
                    setDeleteConfirmTypedName('')
                  }}
                  disabled={deletingItem}
                  className="flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                  style={{ backgroundColor: 'transparent', color: '#334155', border: '1px solid #e2e8f0' }}
                >
                  Annuler
                </button>
                <button
                  onClick={confirmDelete}
                  disabled={deletingItem || !matched}
                  className="flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-colors disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: matched ? '#dc2626' : '#fca5a5',
                    opacity: deletingItem ? 0.6 : 1,
                  }}
                  onMouseEnter={(e) => { if (matched && !deletingItem) e.currentTarget.style.backgroundColor = '#b91c1c' }}
                  onMouseLeave={(e) => { if (matched && !deletingItem) e.currentTarget.style.backgroundColor = '#dc2626' }}
                >
                  {deletingItem ? 'Suppression…' : 'Retirer du catalogue'}
                </button>
              </div>
            </div>
          </div>
        )
      })()}

    </div>
  )
}

function SkoolTab({ active, onClick, label, colors }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative pb-4 text-base font-semibold transition-colors"
      style={{ color: active ? colors.text : '#8A8A8A' }}
    >
      {label}
      {active && (
        <span
          className="absolute bottom-[-1px] left-0 h-[3px] w-full"
          style={{ backgroundColor: colors.text }}
        />
      )}
    </button>
  )
}

function PlatformCardsView({
  platforms,
  cardPage,
  setCardPage,
  cardsPerPage,
  expandedPlatform,
  platformAudios,
  audiosLoading,
  playingAudio,
  pdfUploading,
  audioRef,
  colors,
  darkMode,
  studentEmailsByPlatform,
  expandedStudentsPlatform,
  expandedAttendancePlatform,
  studentEmailsLoading,
  studentEmailsSaving,
  studentEmailDrafts,
  attendanceDate,
  attendanceData,
  attendanceLoading,
  attendanceError,
  attendanceSavingStudentId,
  onExpand,
  onToggleStudentEmails,
  onToggleAttendance,
  onStudentEmailDraftChange,
  onAddStudentEmails,
  onDeleteStudentEmail,
  onAttendanceDateChange,
  onRefreshAttendance,
  onUpdateAttendanceDraft,
  onSaveAttendance,
  onExportAttendance,
  onOpenPdfModal,
  onOpenCourseTimeModal,
  onDeleteAudio,
  onOpenCoursFolders,
  onPlayAudio,
  onPdfUpload,
  onDeletePdf,
  onDeletePlatform,
}) {
  const totalPages = Math.ceil(platforms.length / cardsPerPage)

  return (
    <>
      {platforms.length > cardsPerPage && (
        <div className="mb-6 flex items-center justify-center gap-3">
          <span className="text-sm" style={{ color: colors.textMuted, fontVariantNumeric: 'tabular-nums' }}>
            Page <span className="font-semibold" style={{ color: colors.text }}>{cardPage + 1}</span> / {totalPages}
          </span>
          <button
            onClick={() => setCardPage(p => Math.max(0, p - 1))}
            disabled={cardPage === 0}
            aria-label="Page précédente"
            className="flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-black/5 dark:hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-30"
            style={{ border: `1px solid ${colors.border}`, color: colors.textSecondary }}
          >
            <Icon name="chevron_left" className="text-xl" />
          </button>
          <button
            onClick={() => setCardPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={cardPage >= totalPages - 1}
            aria-label="Page suivante"
            className="flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-black/5 dark:hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-30"
            style={{ border: `1px solid ${colors.border}`, color: colors.textSecondary }}
          >
            <Icon name="chevron_right" className="text-xl" />
          </button>
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {platforms.slice(cardPage * cardsPerPage, (cardPage + 1) * cardsPerPage).map((p) => (
          <PlatformCard
            key={p.id}
            platform={p}
            expanded={expandedPlatform === p.id}
            audios={platformAudios[p.id] || []}
            audiosLoading={audiosLoading === p.id}
            playingAudio={playingAudio}
            pdfUploading={pdfUploading === p.id}
            audioRef={audioRef}
            colors={colors}
            darkMode={darkMode}
            studentEmails={studentEmailsByPlatform[p.id] || []}
            studentsExpanded={expandedStudentsPlatform === p.id}
            attendanceExpanded={expandedAttendancePlatform === p.id}
            attendanceDate={attendanceDate}
            attendanceData={expandedAttendancePlatform === p.id ? attendanceData : null}
            attendanceLoading={attendanceLoading && expandedAttendancePlatform === p.id}
            attendanceError={expandedAttendancePlatform === p.id ? attendanceError : ''}
            attendanceSavingStudentId={attendanceSavingStudentId}
            studentEmailsLoading={studentEmailsLoading === p.id}
            studentEmailsSaving={studentEmailsSaving === p.id}
            studentEmailDraft={studentEmailDrafts[p.id] || ''}
            onExpand={() => onExpand(p.id)}
            onToggleStudentEmails={() => onToggleStudentEmails(p.id)}
            onToggleAttendance={() => onToggleAttendance(p.id)}
            onStudentEmailDraftChange={(value) => onStudentEmailDraftChange(p.id, value)}
            onAddStudentEmails={() => onAddStudentEmails(p.id)}
            onDeleteStudentEmail={(recipientId) => onDeleteStudentEmail(p.id, recipientId)}
            onAttendanceDateChange={onAttendanceDateChange}
            onRefreshAttendance={() => onRefreshAttendance(p.id)}
            onUpdateAttendanceDraft={onUpdateAttendanceDraft}
            onSaveAttendance={(student) => onSaveAttendance(student, p.id)}
            onExportAttendance={(week) => onExportAttendance(week, p.id)}
            onOpenPdfModal={() => onOpenPdfModal(p)}
            onOpenCourseTimeModal={() => onOpenCourseTimeModal(p)}
            onDeleteAudio={(fn) => onDeleteAudio(p.id, fn)}
            onOpenCoursFolders={() => onOpenCoursFolders(p)}
            onPlayAudio={onPlayAudio}
            onPdfUpload={(file) => onPdfUpload(p.id, file)}
            onDeletePdf={() => onDeletePdf(p.id)}
            onDeletePlatform={() => onDeletePlatform(p.id)}
          />
        ))}
      </div>
    </>
  )
}

const ATTENDANCE_STATUS_LABELS = {
  present: 'Présent',
  partial: 'Partiel',
  absent: 'Absent',
  excused: 'Absence justifiée',
}

function attendanceMinutes(slots = []) {
  return slots.reduce((total, slot) => {
    if (!slot?.start || !slot?.end) return total
    const [sh, sm] = slot.start.split(':').map(Number)
    const [eh, em] = slot.end.split(':').map(Number)
    if ([sh, sm, eh, em].some((value) => Number.isNaN(value))) return total
    const start = sh * 60 + sm
    const end = eh * 60 + em
    return end > start ? total + (end - start) : total
  }, 0)
}

function formatAttendanceMinutes(totalMinutes = 0) {
  const total = Number(totalMinutes) || 0
  const hours = Math.floor(total / 60)
  const minutes = total % 60
  if (hours && minutes) return `${hours}h ${String(minutes).padStart(2, '0')}`
  if (hours) return `${hours}h`
  return `${minutes}min`
}

function AttendanceRegisterView({
  colors,
  darkMode,
  platforms,
  selectedPlatformId,
  onPlatformChange,
  courseDate,
  onCourseDateChange,
  data,
  loading,
  error,
  savingStudentId,
  onRefresh,
  onUpdateDraft,
  onSaveStudent,
  onExport,
}) {
  const inputStyle = {
    backgroundColor: colors.innerBg,
    color: colors.text,
    border: `1px solid ${colors.border}`,
  }

  const updateSlot = (studentId, index, field, value) => {
    onUpdateDraft(studentId, (attendance) => {
      const slots = [...(attendance?.slots || [])]
      slots[index] = { ...(slots[index] || {}), [field]: value }
      const total = attendanceMinutes(slots)
      const nextStatus = total > 0 && attendance.status === 'absent' ? 'present' : attendance.status
      return { ...attendance, slots, total_minutes: total, status: nextStatus }
    })
  }

  const addSlot = (studentId) => {
    onUpdateDraft(studentId, (attendance) => ({
      ...attendance,
      slots: [...(attendance?.slots || []), { start: '09:00', end: '12:00' }],
    }))
  }

  const removeSlot = (studentId, index) => {
    onUpdateDraft(studentId, (attendance) => {
      const slots = (attendance?.slots || []).filter((_, slotIndex) => slotIndex !== index)
      const total = attendanceMinutes(slots)
      return {
        ...attendance,
        slots,
        total_minutes: total,
        status: total > 0 ? attendance.status : 'absent',
      }
    })
  }

  const totals = (data?.students || []).reduce((acc, student) => {
    acc.minutes += Number(student.attendance?.total_minutes || 0)
    acc.saved += student.attendance?.source === 'saved' ? 1 : 0
    return acc
  }, { minutes: 0, saved: 0 })

  return (
    <section className="mx-auto w-full max-w-6xl">
      <header
        className="mb-6 flex flex-wrap items-end justify-between gap-4"
        style={{ borderBottom: `1px solid ${colors.border}` }}
      >
        <div className="pb-5">
          <span
            className="text-[10px] font-semibold uppercase"
            style={{ color: colors.textMuted, letterSpacing: '0.22em' }}
          >
            Dossier formation
          </span>
          <h2 className="mt-1 text-xl font-semibold tracking-tight" style={{ color: colors.text }}>
            Présences élèves
          </h2>
          <p className="mt-1 text-xs" style={{ color: colors.textMuted }}>
            Relevé journalier par élève, consolidé sur toute la durée de la formation.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 pb-4">
          <select
            value={selectedPlatformId}
            onChange={(e) => onPlatformChange(e.target.value)}
            className="rounded-lg px-3 py-2 text-sm outline-none transition-colors"
            style={inputStyle}
          >
            {platforms.map((platform) => (
              <option key={platform.id} value={platform.id}>
                {platform.name}
              </option>
            ))}
          </select>
          <input
            type="date"
            value={courseDate}
            onChange={(e) => onCourseDateChange(e.target.value)}
            className="rounded-lg px-3 py-2 text-sm outline-none transition-colors"
            style={inputStyle}
          />
          <button
            type="button"
            onClick={onRefresh}
            className="flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
            style={{ color: colors.textSecondary, border: `1px solid ${colors.border}` }}
          >
            <Icon name="refresh" className="text-base" />
            <span>Actualiser</span>
          </button>
          <button
            type="button"
            onClick={onExport}
            className="flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium text-white transition-colors"
            style={{ backgroundColor: '#8B5CF6' }}
            onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#7c3aed' }}
            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#8B5CF6' }}
          >
            <Icon name="download" className="text-base" />
            <span>Exporter Excel</span>
          </button>
        </div>
      </header>

      {error && (
        <div
          className="mb-4 flex items-center gap-2 rounded-lg px-4 py-3 text-sm"
          style={{
            backgroundColor: darkMode ? 'rgba(127, 29, 29, 0.18)' : '#fef2f2',
            border: darkMode ? '1px solid rgba(248, 113, 113, 0.28)' : '1px solid #fecaca',
            color: darkMode ? '#fecaca' : '#991b1b',
          }}
        >
          <Icon name="warning" className="text-base" />
          <span>{error}</span>
        </div>
      )}

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        {[
          ['Élèves', data?.students?.length || 0],
          ['Relevés enregistrés', totals.saved],
          ['Temps total du jour', formatAttendanceMinutes(totals.minutes)],
        ].map(([label, value]) => (
          <div
            key={label}
            className="rounded-xl px-4 py-3"
            style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}` }}
          >
            <p className="text-[10px] font-semibold uppercase" style={{ color: colors.textMuted, letterSpacing: '0.18em' }}>
              {label}
            </p>
            <p className="mt-1 text-lg font-semibold" style={{ color: colors.text }}>{value}</p>
          </div>
        ))}
      </div>

      <div
        className="overflow-x-auto rounded-2xl"
        style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}` }}
      >
        <table className="w-full min-w-[1080px] border-separate border-spacing-0 text-sm">
          <thead>
            <tr className="text-left text-[10px] font-semibold uppercase" style={{ color: colors.textMuted, letterSpacing: '0.16em' }}>
              <th className="border-b px-4 py-3" style={{ borderColor: colors.border }}>Élève</th>
              <th className="border-b px-4 py-3" style={{ borderColor: colors.border }}>Créneaux</th>
              <th className="border-b px-4 py-3" style={{ borderColor: colors.border }}>Statut</th>
              <th className="border-b px-4 py-3" style={{ borderColor: colors.border }}>Total</th>
              <th className="border-b px-4 py-3" style={{ borderColor: colors.border }}>Notes</th>
              <th className="border-b px-4 py-3 text-right" style={{ borderColor: colors.border }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-sm" style={{ color: colors.textMuted }}>
                  Chargement des présences...
                </td>
              </tr>
            ) : (data?.students || []).length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-sm" style={{ color: colors.textMuted }}>
                  Aucun compte élève n’est rattaché à cette formation.
                </td>
              </tr>
            ) : (
              data.students.map((student) => {
                const attendance = student.attendance || {}
                const slots = attendance.slots || []
                return (
                  <tr key={student.id} className="align-top transition-colors hover:bg-black/5 dark:hover:bg-white/5">
                    <td className="border-b px-4 py-4" style={{ borderColor: colors.border }}>
                      <div className="font-semibold" style={{ color: colors.text }}>
                        {student.prenom} {student.nom}
                      </div>
                      <div className="mt-0.5 text-xs" style={{ color: colors.textMuted }}>{student.email}</div>
                      <div className="mt-2 text-xs" style={{ color: colors.textMuted }}>
                        Cumul: {formatAttendanceMinutes(student.totals?.total_minutes || 0)}
                      </div>
                    </td>
                    <td className="border-b px-4 py-4" style={{ borderColor: colors.border }}>
                      <div className="space-y-2">
                        {slots.map((slot, index) => (
                          <div key={`${student.id}-${index}`} className="flex items-center gap-2">
                            <input
                              type="time"
                              value={slot.start || ''}
                              onChange={(e) => updateSlot(student.id, index, 'start', e.target.value)}
                              className="w-28 rounded-lg px-2 py-1.5 text-sm outline-none"
                              style={inputStyle}
                            />
                            <span className="text-xs" style={{ color: colors.textMuted }}>à</span>
                            <input
                              type="time"
                              value={slot.end || ''}
                              onChange={(e) => updateSlot(student.id, index, 'end', e.target.value)}
                              className="w-28 rounded-lg px-2 py-1.5 text-sm outline-none"
                              style={inputStyle}
                            />
                            <button
                              type="button"
                              onClick={() => removeSlot(student.id, index)}
                              aria-label="Retirer le créneau"
                              className="flex h-8 w-8 items-center justify-center rounded-lg transition-colors hover:bg-rose-500/10"
                              style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
                            >
                              <Icon name="close" className="text-base" />
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          onClick={() => addSlot(student.id)}
                          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
                          style={{ color: colors.textSecondary, border: `1px solid ${colors.border}` }}
                        >
                          <Icon name="add" className="text-sm" />
                          <span>Ajouter un créneau</span>
                        </button>
                        {attendance.source === 'logs' && (
                          <p className="text-xs" style={{ color: colors.textMuted }}>
                            Prérempli depuis les logs de connexion.
                          </p>
                        )}
                      </div>
                    </td>
                    <td className="border-b px-4 py-4" style={{ borderColor: colors.border }}>
                      <select
                        value={attendance.status || 'absent'}
                        onChange={(e) => onUpdateDraft(student.id, { ...attendance, status: e.target.value })}
                        className="rounded-lg px-3 py-2 text-sm outline-none"
                        style={inputStyle}
                      >
                        {Object.entries(ATTENDANCE_STATUS_LABELS).map(([value, label]) => (
                          <option key={value} value={value}>{label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="border-b px-4 py-4 font-semibold" style={{ borderColor: colors.border, color: colors.text }}>
                      {formatAttendanceMinutes(attendance.total_minutes || 0)}
                    </td>
                    <td className="border-b px-4 py-4" style={{ borderColor: colors.border }}>
                      <input
                        type="text"
                        value={attendance.notes || ''}
                        onChange={(e) => onUpdateDraft(student.id, { ...attendance, notes: e.target.value })}
                        placeholder="Retard, départ anticipé..."
                        className="w-full rounded-lg px-3 py-2 text-sm outline-none"
                        style={inputStyle}
                      />
                    </td>
                    <td className="border-b px-4 py-4 text-right" style={{ borderColor: colors.border }}>
                      <button
                        type="button"
                        onClick={() => onSaveStudent(student)}
                        disabled={savingStudentId === student.id}
                        className="rounded-lg px-3.5 py-2 text-xs font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                        style={{ backgroundColor: '#8B5CF6' }}
                      >
                        {savingStudentId === student.id ? 'Enregistrement...' : 'Enregistrer'}
                      </button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {(data?.recent_dates || []).length > 0 && (
        <div className="mt-5">
          <h3 className="mb-2 text-sm font-semibold" style={{ color: colors.text }}>Journées déjà consignées</h3>
          <div className="flex flex-wrap gap-2">
            {data.recent_dates.map((item) => (
              <button
                key={item.course_date}
                type="button"
                onClick={() => onCourseDateChange(item.course_date)}
                className="rounded-lg px-3 py-2 text-xs font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
                style={{ color: colors.textSecondary, border: `1px solid ${colors.border}` }}
              >
                {new Date(`${item.course_date}T00:00:00`).toLocaleDateString('fr-FR')} · {item.student_count} élève{item.student_count > 1 ? 's' : ''}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

function AttendanceCardPanel({
  colors,
  darkMode,
  courseDate,
  data,
  loading,
  error,
  savingStudentId,
  onCourseDateChange,
  onRefresh,
  onUpdateDraft,
  onSaveStudent,
  onExport,
}) {
  const inputStyle = {
    backgroundColor: colors.cardBg,
    color: colors.text,
    border: `1px solid ${colors.border}`,
  }
  const students = data?.students || []
  const weeks = data?.recent_weeks || []
  const totals = students.reduce((acc, student) => {
    acc.minutes += Number(student.attendance?.total_minutes || 0)
    acc.saved += student.attendance?.source === 'saved' ? 1 : 0
    return acc
  }, { minutes: 0, saved: 0 })

  const formatDate = (value) => {
    if (!value) return ''
    return new Date(`${value}T00:00:00`).toLocaleDateString('fr-FR')
  }

  const updateSlot = (studentId, index, field, value) => {
    onUpdateDraft(studentId, (attendance = {}) => {
      const slots = [...(attendance.slots || [])]
      slots[index] = { ...(slots[index] || {}), [field]: value }
      const total = attendanceMinutes(slots)
      const nextStatus = total > 0 && attendance.status === 'absent' ? 'present' : attendance.status
      return { ...attendance, slots, total_minutes: total, status: nextStatus || (total > 0 ? 'present' : 'absent') }
    })
  }

  const addSlot = (studentId) => {
    onUpdateDraft(studentId, (attendance = {}) => ({
      ...attendance,
      slots: [...(attendance.slots || []), { start: '09:00', end: '12:00' }],
    }))
  }

  const removeSlot = (studentId, index) => {
    onUpdateDraft(studentId, (attendance = {}) => {
      const slots = (attendance.slots || []).filter((_, slotIndex) => slotIndex !== index)
      const total = attendanceMinutes(slots)
      return {
        ...attendance,
        slots,
        total_minutes: total,
        status: total > 0 ? (attendance.status || 'present') : 'absent',
      }
    })
  }

  return (
    <div
      className="mb-3 rounded-xl p-3"
      style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}` }}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="text-sm font-semibold" style={{ color: colors.text }}>
            Présence
          </span>
          <p className="mt-0.5 text-xs" style={{ color: colors.textMuted }}>
            {students.length} élève{students.length > 1 ? 's' : ''} · {totals.saved} relevé{totals.saved > 1 ? 's' : ''} enregistré{totals.saved > 1 ? 's' : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onExport(null)}
          className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold text-white transition-colors"
          style={{ backgroundColor: '#8B5CF6' }}
        >
          <Icon name="download" className="text-sm" />
          Excel complet
        </button>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          type="date"
          value={courseDate}
          onChange={(e) => onCourseDateChange(e.target.value)}
          className="min-w-0 flex-1 rounded-lg px-3 py-2 text-sm outline-none transition-shadow focus:ring-2 focus:ring-violet-500/30"
          style={inputStyle}
        />
        <button
          type="button"
          onClick={onRefresh}
          className="flex h-10 w-10 items-center justify-center rounded-lg transition-colors hover:bg-black/5 dark:hover:bg-white/5"
          style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
          title="Actualiser les présences"
          aria-label="Actualiser les présences"
        >
          <Icon name="refresh" className="text-base" />
        </button>
      </div>

      {error && (
        <div
          className="mb-3 flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
          style={{
            backgroundColor: darkMode ? 'rgba(127, 29, 29, 0.18)' : '#fef2f2',
            border: darkMode ? '1px solid rgba(248, 113, 113, 0.28)' : '1px solid #fecaca',
            color: darkMode ? '#fecaca' : '#991b1b',
          }}
        >
          <Icon name="warning" className="text-sm" />
          <span>{error}</span>
        </div>
      )}

      <div className="mb-3 rounded-lg p-2" style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}` }}>
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-xs font-semibold" style={{ color: colors.text }}>
            Fichiers Excel par semaine
          </span>
          <span className="text-[10px] tabular-nums" style={{ color: colors.textMuted }}>
            {weeks.length}
          </span>
        </div>
        {weeks.length === 0 ? (
          <p className="py-2 text-xs" style={{ color: colors.textMuted }}>
            Aucune semaine exportable pour le moment.
          </p>
        ) : (
          <div className="max-h-32 space-y-1 overflow-y-auto pr-1">
            {weeks.map((week) => (
              <button
                key={week.week_start}
                type="button"
                onClick={() => onExport(week)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-black/5 dark:hover:bg-white/5"
                style={{ color: colors.textSecondary, border: `1px solid ${colors.border}` }}
              >
                <Icon name="table_chart" className="text-sm" style={{ color: colors.textMuted }} />
                <span className="min-w-0 flex-1 truncate text-xs">
                  Semaine du {formatDate(week.week_start)} au {formatDate(week.week_end)}
                </span>
                <Icon name="download" className="text-sm" style={{ color: colors.textMuted }} />
              </button>
            ))}
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-5">
          <div className="h-5 w-5 animate-spin rounded-full border-2" style={{ borderColor: colors.border, borderTopColor: '#8B5CF6' }} />
        </div>
      ) : students.length === 0 ? (
        <p className="py-3 text-xs" style={{ color: colors.textMuted }}>
          Aucun compte élève n’est rattaché à cette formation.
        </p>
      ) : (
        <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
          {students.map((student) => {
            const attendance = student.attendance || {}
            const slots = attendance.slots || []
            return (
              <div
                key={student.id}
                className="rounded-lg p-2"
                style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}` }}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold" style={{ color: colors.text }}>
                      {student.prenom} {student.nom}
                    </p>
                    <p className="truncate text-xs" style={{ color: colors.textMuted }} title={student.email}>
                      {student.email}
                    </p>
                  </div>
                  <span className="flex-shrink-0 text-xs font-semibold tabular-nums" style={{ color: colors.textSecondary }}>
                    {formatAttendanceMinutes(attendance.total_minutes || 0)}
                  </span>
                </div>

                <div className="space-y-2">
                  {slots.map((slot, index) => (
                    <div key={`${student.id}-${index}`} className="flex items-center gap-1.5">
                      <input
                        type="time"
                        value={slot.start || ''}
                        onChange={(e) => updateSlot(student.id, index, 'start', e.target.value)}
                        className="min-w-0 flex-1 rounded-lg px-2 py-1.5 text-xs outline-none"
                        style={inputStyle}
                      />
                      <span className="text-xs" style={{ color: colors.textMuted }}>à</span>
                      <input
                        type="time"
                        value={slot.end || ''}
                        onChange={(e) => updateSlot(student.id, index, 'end', e.target.value)}
                        className="min-w-0 flex-1 rounded-lg px-2 py-1.5 text-xs outline-none"
                        style={inputStyle}
                      />
                      <button
                        type="button"
                        onClick={() => removeSlot(student.id, index)}
                        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-rose-500/10"
                        style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
                        aria-label="Retirer le créneau"
                      >
                        <Icon name="close" className="text-sm" />
                      </button>
                    </div>
                  ))}

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => addSlot(student.id)}
                      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
                      style={{ color: colors.textSecondary, border: `1px solid ${colors.border}` }}
                    >
                      <Icon name="add" className="text-sm" />
                      Créneau
                    </button>
                    <select
                      value={attendance.status || 'absent'}
                      onChange={(e) => onUpdateDraft(student.id, { ...attendance, status: e.target.value })}
                      className="min-w-0 flex-1 rounded-lg px-2.5 py-1.5 text-xs outline-none"
                      style={inputStyle}
                    >
                      {Object.entries(ATTENDANCE_STATUS_LABELS).map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                  </div>

                  <input
                    type="text"
                    value={attendance.notes || ''}
                    onChange={(e) => onUpdateDraft(student.id, { ...attendance, notes: e.target.value })}
                    placeholder="Retard, départ anticipé..."
                    className="w-full rounded-lg px-2.5 py-1.5 text-xs outline-none"
                    style={inputStyle}
                  />

                  <button
                    type="button"
                    onClick={() => onSaveStudent(student)}
                    disabled={savingStudentId === student.id}
                    className="w-full rounded-lg px-3 py-2 text-xs font-semibold text-white transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                    style={{ backgroundColor: '#8B5CF6' }}
                  >
                    {savingStudentId === student.id ? 'Enregistrement...' : 'Enregistrer la présence'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// Bouton icône-seule pour supprimer un module du catalogue.
// Slate au repos pour ne pas crier "danger" en permanence ; vire rose au
// hover (cf. DESIGN.md §Audio Item delete : muted at rest → rose on hover).
function ModuleDeleteButton({ onClick, colors, label }) {
  const [hover, setHover] = useState(false)
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="flex h-8 w-8 items-center justify-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40"
      style={{
        backgroundColor: hover ? 'rgba(220, 38, 38, 0.08)' : 'transparent',
        color: hover ? '#dc2626' : colors.textMuted,
        border: `1px solid ${hover ? 'rgba(220, 38, 38, 0.25)' : colors.border}`,
      }}
    >
      <Icon name="delete_outline" className="text-base" />
    </button>
  )
}

const MODULE_WEEKDAY_LABELS = ['Lun.', 'Mar.', 'Mer.', 'Jeu.', 'Ven.', 'Sam.', 'Dim.']

function inferTeacherName(module = {}) {
  const source = module.source_platform_name || ''
  if (source.includes('·')) return source.split('·')[0].trim()
  if (source && source !== module.tp_name) return source
  return 'Professeur IA'
}

function formatModuleCadence(module = {}) {
  const schedule = module.schedule
  if (!schedule) {
    return `${module.nb_folders || 0} journée${(module.nb_folders || 0) > 1 ? 's' : ''}`
  }
  const days = (schedule.weekdays || [])
    .map((day) => MODULE_WEEKDAY_LABELS[Number(day)])
    .filter(Boolean)
    .join(', ')
  const total = schedule.total_training_days || module.nb_folders || 0
  const weekly = schedule.weekly_course_count || (schedule.weekdays || []).length
  return `${total} journée${total > 1 ? 's' : ''} · ${weekly}/semaine${days ? ` · ${days}` : ''} · ${schedule.start_time || '09:00'}`
}

function ModulesCatalogueView({
  colors,
  modules,
  moduleSearchQuery,
  onModuleSearchChange,
  onBack,
  onCreateModule,
  onUseModule,
  onDeleteModule,
}) {
  return (
    <section className="mx-auto w-full max-w-5xl">
      <header
        className="mb-7 flex items-end justify-between gap-4"
        style={{ borderBottom: `1px solid ${colors.border}` }}
      >
        <div className="flex flex-col pb-5 leading-tight">
          <span
            className="text-[10px] font-semibold uppercase"
            style={{ color: colors.textMuted, letterSpacing: '0.22em' }}
          >
            Bibliothèque
          </span>
          <h2 className="mt-1 text-xl font-semibold tracking-tight" style={{ color: colors.text }}>
            Anciens professeurs IA
          </h2>
          <p className="mt-1 text-xs" style={{ color: colors.textMuted }}>
            Professeurs terminés ou réutilisables pour lancer une nouvelle période de formation.
          </p>
        </div>
        <button
          onClick={onBack}
          className="mb-4 flex flex-shrink-0 items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
          style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
        >
          <Icon name="school" className="text-base" />
          <span>Mes professeurs IA</span>
        </button>
      </header>

      <div
        className="mb-5 flex items-center gap-3"
      >
        <div className="relative flex-1">
          <Icon
            name="search"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-base"
            style={{ color: colors.textMuted }}
          />
          <input
            type="text"
            value={moduleSearchQuery}
            onChange={(e) => onModuleSearchChange(e.target.value)}
            placeholder="Rechercher par professeur, formation ou code RNCP..."
            className="w-full rounded-lg py-2 pl-10 pr-3 text-sm outline-none transition-colors"
            style={{
              backgroundColor: colors.innerBg,
              color: colors.text,
              border: `1px solid ${colors.border}`,
            }}
          />
        </div>
        <button
          onClick={onCreateModule}
          className="flex flex-shrink-0 items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors"
          style={{ backgroundColor: '#8B5CF6' }}
          onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#7c3aed' }}
          onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#8B5CF6' }}
          title="Créer un nouveau professeur IA"
        >
          <Icon name="add" className="text-base" />
          <span>Nouveau professeur IA</span>
        </button>
      </div>

      <div>
        {modules.length === 0 ? (
          <div
            className="py-16 text-center"
            style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}`, borderRadius: 14 }}
          >
            <p className="text-sm font-medium" style={{ color: colors.text }}>
              {moduleSearchQuery
                ? 'Aucun professeur IA ne correspond à ce filtre.'
                : 'Aucun ancien professeur IA disponible pour l’instant.'}
            </p>
            <p className="mt-2 text-xs" style={{ color: colors.textMuted }}>
              {moduleSearchQuery
                ? 'Essaie un prénom, un titre de formation ou un code RNCP.'
                : 'Les professeurs terminés apparaîtront ici pour être réutilisés.'}
            </p>
          </div>
        ) : (
          <ul className="space-y-3">
            {modules.map((m, idx) => (
              <li
                key={m.id}
                className="flex items-center gap-4 rounded-2xl px-4 py-3"
                style={{
                  backgroundColor: colors.cardBg,
                  border: `1px solid ${colors.border}`,
                  opacity: m.reusable ? 1 : 0.55,
                }}
              >
                <div className="relative flex h-20 w-20 flex-shrink-0 items-center justify-center">
                  <div
                    className="absolute inset-2 rounded-full blur-xl"
                    style={{ backgroundColor: getRobotTheme(m.source_platform_id || m.id).glow, opacity: 0.22 }}
                  />
                  <img
                    src={getRobotTheme(m.source_platform_id || m.id).src}
                    alt=""
                    className="relative h-20 w-20 object-contain"
                    draggable={false}
                  />
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <h3 className="truncate text-base font-semibold" style={{ color: colors.text }}>
                      {inferTeacherName(m)}
                    </h3>
                    {m.status === 'validated' && (
                      <span
                        className="flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
                        style={{
                          backgroundColor: 'rgba(16, 185, 129, 0.12)',
                          color: '#10b981',
                          letterSpacing: '0.15em',
                        }}
                      >
                        Réutilisable
                      </span>
                    )}
                    {m.status === 'draft' && (
                      <span
                        className="flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase"
                        style={{
                          backgroundColor: 'rgba(245, 158, 11, 0.15)',
                          color: '#f59e0b',
                          letterSpacing: '0.15em',
                        }}
                      >
                        En préparation
                      </span>
                    )}
                  </div>
                  <p className="mt-1 truncate text-sm font-medium" style={{ color: colors.textSecondary }}>
                    {m.tp_name}
                  </p>
                  <p
                    className="mt-1 truncate text-xs"
                    style={{ color: colors.textMuted, fontVariantNumeric: 'tabular-nums' }}
                  >
                    RNCP {m.rncp_code || '—'} · {formatModuleCadence(m)}
                    {m.created_at && (
                      <>
                        {' · créé le '}
                        {new Date(m.created_at).toLocaleDateString('fr-FR')}
                      </>
                    )}
                  </p>
                </div>

                <div className="flex flex-shrink-0 items-center gap-2">
                  {m.reusable ? (
                    <button
                      onClick={() => onUseModule(m.id)}
                      className="flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold text-white transition-colors"
                      style={{ backgroundColor: '#8B5CF6' }}
                      onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#7c3aed' }}
                      onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#8B5CF6' }}
                      title="Restaurer ce professeur IA dans Mes professeurs IA"
                    >
                      <span>Réutiliser</span>
                      <Icon name="arrow_forward" className="text-sm" />
                    </button>
                  ) : (
                    <span className="text-xs" style={{ color: colors.textMuted }}>
                      {m.nb_folders === 0 ? 'Cours non générés' : 'Bientôt'}
                    </span>
                  )}
                  {/* Bouton supprimer module — icône seule, slate au repos,
                      tinte rose au hover. La confirmation passe par la modale
                      type-to-confirm (registre Examiner's Desk). */}
                  {onDeleteModule && (
                    <ModuleDeleteButton
                      onClick={() => onDeleteModule(m.id)}
                      colors={colors}
                      label={`Retirer ${m.tp_name} ${m.version} du catalogue`}
                    />
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

function CreatePlatformView({
  colors,
  darkMode,
  teacherFirstName,
  setTeacherFirstName,
  teacherColor,
  setTeacherColor,
  weeklyCourseCount,
  setWeeklyCourseCount,
  teachingDays,
  setTeachingDays,
  newFormTpName,
  setNewFormTpName,
  newFormRncp,
  setNewFormRncp,
  newFormHours,
  setNewFormHours,
  creating,
  onCreate,
  onCancel,
}) {
  const teacherColors = [
    { id: 'violet', label: 'Violet', swatch: '#8B5CF6', image: '/robot-violet.png' },
    { id: 'blue', label: 'Bleu', swatch: '#3B82F6', image: '/robot-blue.png' },
    { id: 'pink', label: 'Rose', swatch: '#EC4899', image: '/robot-pink.png' },
    { id: 'amber', label: 'Ambre', swatch: '#F59E0B', image: '/robot-amber.png' },
  ]
  const weekDays = [
    { id: 'lundi', label: 'Lun.' },
    { id: 'mardi', label: 'Mar.' },
    { id: 'mercredi', label: 'Mer.' },
    { id: 'jeudi', label: 'Jeu.' },
    { id: 'vendredi', label: 'Ven.' },
  ]
  const selectedColor = teacherColors.find((color) => color.id === teacherColor) || teacherColors[0]
  const canCreateTeacher = (
    teacherFirstName.trim()
    && newFormTpName.trim()
    && newFormRncp.trim()
    && Number(newFormHours) > 0
    && Number(weeklyCourseCount) > 0
    && teachingDays.length > 0
  )
  const inputStyle = {
    backgroundColor: darkMode ? '#0f172a' : '#F8F7F5',
    color: darkMode ? '#f1f5f9' : '#1e293b',
    border: `1px solid ${darkMode ? '#334155' : '#e2e8f0'}`,
  }
  const toggleTeachingDay = (dayId) => {
    setTeachingDays((current) => (
      current.includes(dayId)
        ? current.filter((day) => day !== dayId)
        : [...current, dayId]
    ))
  }

  return (
    <section
      className="mx-auto w-full max-w-3xl"
    >
      <header
        className="mb-7 flex items-start justify-between gap-4"
      >
        <div className="flex flex-col leading-tight">
          <span
            className="text-[10px] font-semibold uppercase"
            style={{ color: colors.textMuted, letterSpacing: '0.22em' }}
          >
            Création
          </span>
          <h2 className="mt-1 text-xl font-semibold tracking-tight" style={{ color: colors.text }}>
            Nouveau professeur IA
          </h2>
        </div>
      </header>

      <div>
        <div className="grid gap-5 md:grid-cols-[1fr_180px]">
          <div className="space-y-5">
            <div>
              <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
                Prénom du professeur IA
              </label>
              <input
                type="text"
                value={teacherFirstName}
                onChange={(e) => setTeacherFirstName(e.target.value)}
                placeholder="Ex: Lina"
                autoFocus
                className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-all"
                style={inputStyle}
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
                Nom de la formation
              </label>
              <input
                type="text"
                value={newFormTpName}
                onChange={(e) => setNewFormTpName(e.target.value)}
                placeholder="Ex: TP CRCD"
                className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-all"
                style={inputStyle}
              />
            </div>
          </div>

          <div
            className="flex items-center justify-center rounded-xl"
            style={{ backgroundColor: darkMode ? '#0f172a' : '#F8F7F5', border: `1px solid ${colors.border}` }}
          >
            <img src={selectedColor.image} alt="" className="h-36 w-36 object-contain" draggable="false" />
          </div>
        </div>

        <div className="mt-5">
          <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
            Couleur du professeur IA
          </label>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {teacherColors.map((color) => {
              const selected = teacherColor === color.id
              return (
                <button
                  key={color.id}
                  type="button"
                  onClick={() => setTeacherColor(color.id)}
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all"
                  style={{
                    color: selected ? colors.text : colors.textSecondary,
                    border: `1px solid ${selected ? color.swatch : colors.border}`,
                    backgroundColor: selected ? `${color.swatch}14` : 'transparent',
                  }}
                >
                  <span className="h-3 w-3 rounded-full" style={{ backgroundColor: color.swatch }} />
                  {color.label}
                </button>
              )
            })}
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
              Code RNCP
            </label>
            <input
              type="text"
              value={newFormRncp}
              onChange={(e) => setNewFormRncp(e.target.value)}
              placeholder="Ex: 35304"
              className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-all"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="mb-2 flex items-center gap-2 text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
              <span>Nombre de journées que doit durer la formation</span>
              <span className="group relative inline-flex">
                <button
                  type="button"
                  className="inline-flex h-5 w-5 items-center justify-center rounded-full text-xs font-bold"
                  style={{ color: '#8B5CF6', border: '1px solid rgba(139, 92, 246, 0.35)', backgroundColor: 'rgba(139, 92, 246, 0.08)' }}
                  aria-label="Aide sur le nombre de journées"
                >
                  i
                </button>
                <span
                  className="pointer-events-none absolute bottom-7 right-0 z-30 hidden w-72 rounded-lg px-3 py-2 text-xs font-medium leading-5 shadow-lg group-hover:block group-focus-within:block"
                  style={{ color: '#334155', backgroundColor: '#ffffff', border: '1px solid #e2e8f0' }}
                >
                  Si la formation dure 52 semaines à raison de 1 jour par semaine, indiquez 52. Si elle dure 52 semaines à raison de 2 jours par semaine, indiquez 104.
                </span>
              </span>
            </label>
            <input
              type="number"
              value={newFormHours}
              onChange={(e) => setNewFormHours(e.target.value)}
              placeholder="Ex: 52"
              min="1"
              className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-all"
              style={inputStyle}
            />
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-[180px_1fr]">
          <div>
            <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
              Cours par semaine
            </label>
            <input
              type="number"
              value={weeklyCourseCount}
              onChange={(e) => setWeeklyCourseCount(e.target.value)}
              min="1"
              max="5"
              className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-all"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
              Jours de cours
            </label>
            <div className="grid grid-cols-5 gap-2">
              {weekDays.map((day) => {
                const selected = teachingDays.includes(day.id)
                return (
                  <button
                    key={day.id}
                    type="button"
                    onClick={() => toggleTeachingDay(day.id)}
                    className="rounded-lg px-2 py-3 text-xs font-semibold transition-all"
                    style={{
                      color: selected ? '#ffffff' : colors.textSecondary,
                      backgroundColor: selected ? '#8B5CF6' : darkMode ? '#0f172a' : '#F8F7F5',
                      border: `1px solid ${selected ? '#8B5CF6' : colors.border}`,
                    }}
                  >
                    {day.label}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={creating}
            className="rounded-lg px-4 py-2 text-sm font-medium transition-all"
            style={{ backgroundColor: darkMode ? '#334155' : '#f1f5f9', color: darkMode ? '#94a3b8' : '#64748b' }}
          >
            Annuler
          </button>
          <button
            onClick={onCreate}
            disabled={creating || !canCreateTeacher}
            className="rounded-lg px-5 py-2 text-sm font-medium text-white transition-all"
            style={{
              backgroundColor: creating || !canCreateTeacher ? '#a78bfa' : '#8B5CF6',
              opacity: creating || !canCreateTeacher ? 0.6 : 1,
            }}
          >
            {creating ? 'Création...' : 'Créer le professeur IA'}
          </button>
        </div>
      </div>
    </section>
  )
}

// ─── Audios Modal ────────────────────────────────────────────────────────────
function AudiosModal({
  platformId,
  audios,
  loading,
  onClose,
  darkMode,
  recorderUrl,
  onRefreshAudios,
  uploadLocked = false,
  backupJob = null,
  onLock = () => {},
  onBackupAndUnlock = () => {},
}) {
  // État dérivé du backup job pour BackupPipeline.
  const isBackupRunning = backupJob && backupJob.step_status === 'running'
  const isBackupDone = backupJob && backupJob.step_status === 'done'
  const isBackupError = backupJob && backupJob.step_status === 'error'
  // Mini colors object pour BackupPipeline (qui en attend une forme précise).
  const pipelineColors = darkMode
    ? { innerBg: '#0f172a', border: '#334155', cardBg: '#1e293b', text: '#f1f5f9', textMuted: '#64748b' }
    : { innerBg: '#F8F7F5', border: '#e2e8f0', cardBg: '#ffffff', text: '#0f172a', textMuted: '#64748b' }
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
    'cours_17h25_18h15.mp3',
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
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/cours-folders`)
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
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/fill-from-folder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
            <div style={{ width: 190 }}>
              <SlideToConfirm
                compact
                locked={uploadLocked}
                onConfirm={uploadLocked ? onBackupAndUnlock : onLock}
                disabled={isBackupRunning}
                onDark
              />
            </div>
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
              aria-label="Fermer"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-white transition-colors active:scale-[0.98]"
              style={{ backgroundColor: 'transparent' }}
              onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.16)'}
              onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
            >
              <Icon name="close" className="text-xl" />
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
                    style={{ border: '1px solid #e2e8f0', color: '#1e293b', backgroundColor: '#F8F7F5' }}
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

        {/* Backup pipeline — affiché en bandeau sous le header quand le job est actif */}
        {(isBackupRunning || isBackupDone || isBackupError) && (
          <div className="px-6 pt-4">
            <BackupPipeline job={backupJob} colors={pipelineColors} darkMode={darkMode} />
          </div>
        )}

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
                  <div className="flex items-center justify-between px-4 py-2 border-b" style={{ borderColor: '#e2e8f0', backgroundColor: '#F8F7F5' }}>
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
// Slide-to-confirm + backup pipeline ne sont plus rendus ici : ils ont été
// déménagés dans CoursFoldersModal (la vue où l'admin voit les audios).
function PlatformCard({
  platform: p, expanded, audios, audiosLoading, playingAudio, pdfUploading,
  audioRef, colors, darkMode, studentEmails = [], studentsExpanded = false, studentEmailsLoading = false,
  studentEmailsSaving = false, studentEmailDraft = '', attendanceExpanded = false,
  attendanceDate, attendanceData, attendanceLoading = false, attendanceError = '',
  attendanceSavingStudentId = null, onExpand, onToggleStudentEmails, onToggleAttendance,
  onStudentEmailDraftChange, onAddStudentEmails, onDeleteStudentEmail,
  onAttendanceDateChange, onRefreshAttendance, onUpdateAttendanceDraft, onSaveAttendance,
  onExportAttendance, onOpenPdfModal, onOpenCourseTimeModal,
  onDeleteAudio, onPlayAudio, onPdfUpload, onDeletePdf, onOpenCoursFolders, onDeletePlatform,
}) {
  const pdfInputId = `pdf-input-${p.id}`
  const platformThumbnail = getPlatformThumbnail(p)
  const [deleteHover, setDeleteHover] = useState(false)
  const [flipped, setFlipped] = useState(false)
  const theme = getRobotTheme(p.id)
  const creationProgress = getHiddenPipelineProgress(p)
  const faceStyle = {
    backgroundColor: colors.cardBg,
    border: p.active ? '1px solid #E4E4E4' : `1px solid ${colors.border}`,
    boxShadow: darkMode ? 'none' : '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1)',
  }

  return (
    // Carte robot prof IA : recto = robot coloré, au survol pivote (rotateY)
    // pour révéler au verso la fiche formation (inchangée). Les deux faces se
    // superposent dans la même cellule grid → la cellule prend la hauteur de
    // la plus grande (la fiche).
    <div className="flex flex-col">
      <div className="group [perspective:1600px]">
      <div
        className="relative grid transition-transform duration-700 ease-out"
        style={{
          transformStyle: 'preserve-3d',
          transform: flipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
        }}
      >
        {/* ═══ RECTO — le professeur IA (aucun chrome de carte : juste le robot
            qui flotte sur le fond du dashboard ; la carte n'apparaît qu'au
            survol via le flip vers le verso) ═══ */}
        <div
          className="[grid-area:1/1] relative flex flex-col items-center justify-center"
          style={{
            backfaceVisibility: 'hidden',
            WebkitBackfaceVisibility: 'hidden',
            pointerEvents: flipped ? 'none' : 'auto',
          }}
        >
          {/* Halo coloré de la plateforme derrière le robot (lueur, pas une
              carte). PNG transparent → aucun blend nécessaire, le robot flotte
              proprement sur n'importe quel fond (clair ou sombre). */}
          <div
            className="pointer-events-none absolute left-1/2 top-[46%] h-56 w-56 -translate-x-1/2 -translate-y-1/2 rounded-full blur-3xl"
            style={{ backgroundColor: theme.glow, opacity: 0.3 }}
          />

          {/* Robot — en grand, sans cadre */}
          <img
            src={theme.src}
            alt={`Professeur IA — ${p.name}`}
            draggable={false}
            className="relative z-10 w-full max-w-[88%] object-contain transition-transform duration-500 ease-out group-hover:-translate-y-2 group-hover:scale-[1.05]"
            style={{ minHeight: '290px' }}
          />

          {/* Nom plateforme sous le robot — texte seul, pas de carte */}
          <div className="relative z-10 -mt-2 flex items-center gap-2 px-4 pb-1">
            <span
              className="text-xs font-semibold tabular-nums"
              style={{ color: colors.textMuted, letterSpacing: '0.08em' }}
            >
              P{p.id}
            </span>
            <h3 className="truncate text-base font-semibold tracking-tight" style={{ color: colors.text }}>
              {p.name}
            </h3>
            {!p.active && (
              <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: '#94a3b8' }}>
                · bientôt
              </span>
            )}
          </div>
          {p.active && p.status === 'pending' && (
            <div
              className="relative z-10 mt-4 w-full max-w-[280px] rounded-xl px-4 py-3"
              style={{ backgroundColor: darkMode ? 'rgba(15, 23, 42, 0.72)' : 'rgba(255, 255, 255, 0.86)', border: `1px solid ${colors.border}`, backdropFilter: 'blur(6px)' }}
            >
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="text-xs font-semibold" style={{ color: colors.text }}>
                  Création en cours
                </span>
                <span className="inline-flex h-4 w-4 animate-spin rounded-full border-2" style={{ borderColor: '#ddd6fe', borderTopColor: '#8B5CF6' }} />
              </div>
              <div
                className="h-1.5 overflow-hidden rounded-full"
                role="progressbar"
                aria-label="Création du professeur IA"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={creationProgress}
                style={{ backgroundColor: darkMode ? '#334155' : '#ede9fe' }}
              >
                <div
                  className="h-full rounded-full transition-[width] duration-700 ease-out"
                  style={{ width: `${creationProgress}%`, backgroundColor: '#8B5CF6' }}
                />
              </div>
            </div>
          )}
        </div>

        {/* ═══ VERSO — la fiche formation (inchangée) ═══ */}
        <div
          className="[grid-area:1/1] relative overflow-hidden rounded-2xl transition-all duration-300"
          style={{
            ...faceStyle,
            backfaceVisibility: 'hidden',
            WebkitBackfaceVisibility: 'hidden',
            transform: 'rotateY(180deg)',
            pointerEvents: flipped ? 'auto' : 'none',
          }}
        >
      {/* Bouton supprimer plateforme — z-30 pour rester au-dessus des
          overlays inactif/pending/error (z-20). Slate muted au repos avec
          backdrop-blur (visible par-dessus le thumbnail), tinte rose au hover. */}
      {onDeletePlatform && (
        <button
          type="button"
          aria-label={`Supprimer la plateforme ${p.name}`}
          title="Supprimer la plateforme"
          onClick={(e) => {
            e.stopPropagation()
            onDeletePlatform()
          }}
          onMouseEnter={() => setDeleteHover(true)}
          onMouseLeave={() => setDeleteHover(false)}
          className="absolute right-3 top-3 z-30 flex h-8 w-8 items-center justify-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40"
          style={{
            backgroundColor: deleteHover ? (darkMode ? 'rgba(220, 38, 38, 0.18)' : '#fee2e2') : (darkMode ? 'rgba(15, 23, 42, 0.55)' : 'rgba(255, 255, 255, 0.85)'),
            color: deleteHover ? '#dc2626' : colors.textMuted,
            border: `1px solid ${deleteHover ? 'rgba(220, 38, 38, 0.3)' : (darkMode ? 'rgba(255,255,255,0.08)' : 'rgba(15, 23, 42, 0.06)')}`,
            backdropFilter: 'blur(4px)',
          }}
        >
          <Icon name="delete_outline" className="text-base" />
        </button>
      )}

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

      {/* Pending overlay : clone de formation en cours ou pipeline initiée */}
      {p.active && p.status === 'pending' && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center rounded-2xl"
          style={{ backgroundColor: darkMode ? 'rgba(15, 23, 42, 0.92)' : 'rgba(248, 250, 252, 0.98)', backdropFilter: 'blur(4px)' }}
        >
          <div className="text-center px-6">
            <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-[3px]"
              style={{ borderColor: darkMode ? '#334155' : '#e2e8f0', borderTopColor: '#8B5CF6' }} />
            <p className="text-sm font-semibold mb-1" style={{ color: colors.text }}>
              {p.source_formation_id ? 'Clone des cours en cours' : 'Module en construction'}
            </p>
            <p className="text-xs mb-4" style={{ color: colors.textMuted }}>
              {p.source_formation_id
                ? 'Copie des cours + blobs Azure — quelques instants…'
                : 'La pipeline est initiée. Finalise les étapes sur la page de suivi.'}
            </p>
            {!p.source_formation_id && (
              <a
                href="/formation-pipeline"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-medium transition-all"
                style={{
                  backgroundColor: '#8B5CF6',
                  color: 'white',
                  textDecoration: 'none',
                }}
              >
                <Icon name="open_in_new" className="text-sm" />
                Suivre la pipeline
              </a>
            )}
          </div>
        </div>
      )}

      {/* Error overlay : clone ou pipeline échoué */}
      {p.active && p.status === 'error' && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center rounded-2xl"
          style={{ backgroundColor: darkMode ? 'rgba(15, 23, 42, 0.92)' : 'rgba(248, 250, 252, 0.98)', backdropFilter: 'blur(4px)' }}
        >
          <div className="text-center px-6">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full" style={{ backgroundColor: '#fee2e2' }}>
              <Icon name="error" className="text-2xl" style={{ color: '#dc2626' }} />
            </div>
            <p className="text-sm font-semibold mb-1" style={{ color: colors.text }}>Erreur de setup</p>
            <p className="text-xs" style={{ color: colors.textMuted }}>Voir les logs backend pour le détail.</p>
          </div>
        </div>
      )}

      <div className="p-6">
        {platformThumbnail && (
          <div
            className="mb-5 overflow-hidden rounded-xl"
            style={{
              aspectRatio: '16 / 7.2',
              border: '1px solid #E4E4E4',
              backgroundColor: '#F8F7F5',
            }}
          >
            <img
              src={platformThumbnail.src}
              alt={platformThumbnail.alt}
              className="h-full w-full object-cover"
              draggable={false}
            />
          </div>
        )}

        {/* Header — SKU chip + name + status pill, optional meta line below */}
        <div className="mb-5 space-y-2">
          <div className="flex min-w-0 items-center gap-2">
            <span
              className="flex-shrink-0 inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase"
              style={{
                backgroundColor: colors.innerBg,
                color: colors.textMuted,
                border: `1px solid ${colors.border}`,
                letterSpacing: '0.08em',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              P{p.id}
            </span>
            <h3 className="truncate text-lg font-semibold leading-tight tracking-tight" style={{ color: colors.text }}>
              {p.name}
            </h3>
          </div>
          {p.active && (
            <p
              className="text-xs"
              style={{ color: colors.textMuted, fontVariantNumeric: 'tabular-nums' }}
            >
              {p.audio_count == null ? (
                <span>Audios consultables dans Cours</span>
              ) : (p.audio_count || 0) > 0 ? (
                <>
                  <span className="font-semibold" style={{ color: colors.textSecondary }}>
                    {p.audio_count}
                  </span>
                  {' '}audio{p.audio_count > 1 ? 's' : ''}
                  {p.last_upload_date && (
                    <>
                      {' · '}MAJ {formatRelativeTime(p.last_upload_date)}
                    </>
                  )}
                </>
              ) : (
                <span style={{ color: '#f59e0b' }}>Aucun audio chargé</span>
              )}
            </p>
          )}
        </div>

        {/* Slide-to-confirm + backup pipeline déménagés vers CoursFoldersModal :
            l'action lock/unlock cohabite désormais avec la vue où on voit
            les audios (modale "Cours"). Le card reste épuré. */}

        {/* === Group A : tuiles d'actions internes en grille 2×2 ===
            Layout horizontal compact (icône à gauche, label à droite). Les
            icônes restent slate au rest pour préserver "The One Voice Rule"
            de DESIGN.md — le seul signal violet du card body est l'état
            actif de la tuile Audios quand son panel est déplié. */}
        <div className="mb-3 grid grid-cols-2 gap-2">
          {/* PDF — toujours visible (l'overlay couvre le card si !p.active) */}
          <button
            onClick={onOpenPdfModal}
            className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
            style={{
              border: `1px solid ${colors.border}`,
              color: colors.textSecondary,
            }}
          >
            <Icon name="picture_as_pdf" className="text-lg" style={{ color: colors.textMuted }} />
            <span>PDF</span>
          </button>

          {/* Heure du cours */}
          {p.active && (
            <button
              onClick={onOpenCourseTimeModal}
              className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
              style={{
                border: `1px solid ${colors.border}`,
                color: colors.textSecondary,
              }}
            >
              <Icon name="schedule" className="text-lg" style={{ color: colors.textMuted }} />
              <span>Horaire</span>
            </button>
          )}

          {/* Audios — l'unique tuile à état actif violet (signal "panel ouvert sous la grille") */}
          {p.active && (
            <button
              onClick={onExpand}
              className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
              style={
                expanded
                  ? {
                      backgroundColor: 'rgba(139, 92, 246, 0.10)',
                      border: '1px solid rgba(139, 92, 246, 0.35)',
                      color: darkMode ? '#c4b5fd' : '#7c3aed',
                    }
                  : {
                      border: `1px solid ${colors.border}`,
                      color: colors.textSecondary,
                    }
              }
            >
              <Icon
                name="audiotrack"
                className="text-lg"
                style={{ color: expanded ? (darkMode ? '#c4b5fd' : '#7c3aed') : colors.textMuted }}
              />
              <span>Audios</span>
            </button>
          )}

          {/* Gérer les cours */}
          {p.active && (
            <button
              onClick={onOpenCoursFolders}
              className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
              style={{
                border: `1px solid ${colors.border}`,
                color: colors.textSecondary,
              }}
            >
              <Icon name="folder_special" className="text-lg" style={{ color: colors.textMuted }} />
              <span>Cours</span>
            </button>
          )}

          {/* Élèves — emails utilisés pour les rappels automatiques */}
          {p.active && (
            <button
              onClick={onToggleStudentEmails}
              className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
              style={
                studentsExpanded
                  ? {
                      backgroundColor: 'rgba(139, 92, 246, 0.10)',
                      border: '1px solid rgba(139, 92, 246, 0.35)',
                      color: darkMode ? '#c4b5fd' : '#7c3aed',
                    }
                  : {
                      border: `1px solid ${colors.border}`,
                      color: colors.textSecondary,
                    }
              }
            >
              <Icon
                name="group"
                className="text-lg"
                style={{ color: studentsExpanded ? (darkMode ? '#c4b5fd' : '#7c3aed') : colors.textMuted }}
              />
              <span>Élèves</span>
            </button>
          )}

          {/* Présence — relevés journaliers et exports Excel hebdomadaires */}
          {p.active && (
            <button
              onClick={onToggleAttendance}
              className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
              style={
                attendanceExpanded
                  ? {
                      backgroundColor: 'rgba(139, 92, 246, 0.10)',
                      border: '1px solid rgba(139, 92, 246, 0.35)',
                      color: darkMode ? '#c4b5fd' : '#7c3aed',
                    }
                  : {
                      border: `1px solid ${colors.border}`,
                      color: colors.textSecondary,
                    }
              }
            >
              <Icon
                name="fact_check"
                className="text-lg"
                style={{ color: attendanceExpanded ? (darkMode ? '#c4b5fd' : '#7c3aed') : colors.textMuted }}
              />
              <span>Présence</span>
            </button>
          )}
        </div>

        {/* Audio list — dépliée pleine largeur sous la grille quand la tuile Audios est active */}
        {expanded && p.active && (
          <div className="mb-3 max-h-80 space-y-2 overflow-y-auto pr-1">
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

        {/* Emails élèves — liste de destinataires des rappels de cours */}
        {studentsExpanded && p.active && (
          <div
            className="mb-3 rounded-xl p-3"
            style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}` }}
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-sm font-semibold" style={{ color: colors.text }}>
                Emails élèves
              </span>
              <span className="text-xs tabular-nums" style={{ color: colors.textMuted }}>
                {studentEmails.length}
              </span>
            </div>

            <textarea
              value={studentEmailDraft}
              onChange={(e) => onStudentEmailDraftChange(e.target.value)}
              rows={3}
              placeholder="prenom@exemple.com, autre@exemple.com"
              className="mb-2 w-full resize-none rounded-lg px-3 py-2 text-sm outline-none transition-shadow focus:ring-2 focus:ring-violet-500/30"
              style={{
                backgroundColor: colors.cardBg,
                border: `1px solid ${colors.border}`,
                color: colors.text,
              }}
            />
            <button
              type="button"
              onClick={onAddStudentEmails}
              disabled={!studentEmailDraft.trim() || studentEmailsSaving}
              className="mb-3 inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              style={{ backgroundColor: '#8B5CF6', color: 'white' }}
            >
              {studentEmailsSaving ? (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              ) : (
                <Icon name="add" className="text-sm" />
              )}
              Ajouter
            </button>

            {studentEmailsLoading ? (
              <div className="flex items-center justify-center py-4">
                <div className="h-5 w-5 animate-spin rounded-full border-2" style={{ borderColor: colors.border, borderTopColor: '#8B5CF6' }} />
              </div>
            ) : studentEmails.length === 0 ? (
              <p className="py-3 text-xs" style={{ color: colors.textMuted }}>
                Aucun email élève ajouté.
              </p>
            ) : (
              <div className="max-h-36 space-y-1 overflow-y-auto pr-1">
                {studentEmails.map((recipient) => (
                  <div
                    key={recipient.id}
                    className="flex items-center gap-2 rounded-lg px-2 py-1.5"
                    style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}` }}
                  >
                    <Icon name="mail" className="text-sm" style={{ color: colors.textMuted }} />
                    <span className="min-w-0 flex-1 truncate text-xs" style={{ color: colors.textSecondary }} title={recipient.email}>
                      {recipient.email}
                    </span>
                    <button
                      type="button"
                      onClick={() => onDeleteStudentEmail(recipient.id)}
                      className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md transition-colors hover:bg-rose-50"
                      style={{ color: colors.textMuted }}
                      title="Supprimer l'email"
                    >
                      <Icon name="close" className="text-sm" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {attendanceExpanded && p.active && (
          <AttendanceCardPanel
            colors={colors}
            darkMode={darkMode}
            courseDate={attendanceDate}
            data={attendanceData}
            loading={attendanceLoading}
            error={attendanceError}
            savingStudentId={attendanceSavingStudentId}
            onCourseDateChange={onAttendanceDateChange}
            onRefresh={onRefreshAttendance}
            onUpdateDraft={onUpdateAttendanceDraft}
            onSaveStudent={onSaveAttendance}
            onExport={onExportAttendance}
          />
        )}

        {/* === Divider entre groupes A (boxed) et B (linky externes) === */}
        {p.active && (
          <div
            className="my-4 h-px"
            style={{ backgroundColor: colors.border }}
            aria-hidden="true"
          />
        )}

        {/* === Group B : liens externes (linky, pas de fond, hover bg tint) === */}

        {/* Lien vers la page apprenant — l'admin clique pour vérifier ce que voit l'apprenant */}
        {p.active && (
          <a
            href={p.public_url || `${p.frontend_url || window.location.origin}/?p=${p.id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex w-full items-center justify-between rounded-md px-3 py-2 text-sm transition-colors hover:bg-black/5 dark:hover:bg-white/5"
            style={{
              color: colors.textSecondary,
              textDecoration: 'none',
            }}
          >
            <span>Accéder au cours</span>
            <Icon name="open_in_new" className="text-base" style={{ color: colors.textMuted }} />
          </a>
        )}

        {/* Accès au dashboard centre sur le domaine de la plateforme. */}
        {p.active && (
          <a
            href={`${p.frontend_url || window.location.origin}/dashboard-centre?p=${p.id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex w-full items-center justify-between rounded-md px-3 py-2 text-sm transition-colors hover:bg-black/5 dark:hover:bg-white/5"
            style={{
              color: colors.textSecondary,
              textDecoration: 'none',
            }}
          >
            <span>Dashboard centre</span>
            <Icon name="open_in_new" className="text-base" style={{ color: colors.textMuted }} />
          </a>
        )}

      </div>
        </div>
      </div>
      </div>

      {/* Flèche de bascule : un clic tourne la carte et la maintient, un
          re-clic remet le robot. Hors du flip pour rester visible des 2 côtés. */}
      <button
        type="button"
        onClick={() => setFlipped((f) => !f)}
        aria-label={flipped ? 'Revenir au robot' : 'Voir la fiche formation'}
        className="mx-auto mt-3 flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
        style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
      >
        <span>{flipped ? 'Voir le robot' : 'Voir la fiche'}</span>
        <Icon
          name="keyboard_arrow_down"
          className="text-base transition-transform duration-500"
          style={{ transform: flipped ? 'rotate(180deg)' : 'none' }}
        />
      </button>
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

// Format Europe/Paris dates ('YYYY-MM-DD HH:MM' or ISO) en relatif court ("il y a 2 j", "il y a 14 min").
// Retourne null si la date est invalide / absente — laisse l'appelant décider du fallback.
function formatRelativeTime(dateStr) {
  if (!dateStr) return null
  const isoCandidate = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T')
  const date = new Date(isoCandidate)
  if (isNaN(date.getTime())) return null
  const diffMs = Date.now() - date.getTime()
  if (diffMs < 0) return "à l'instant"
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return "à l'instant"
  if (diffMin < 60) return `il y a ${diffMin} min`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `il y a ${diffHr} h`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `il y a ${diffDay} j`
  if (diffDay < 30) return `il y a ${Math.floor(diffDay / 7)} sem`
  if (diffDay < 365) return `il y a ${Math.floor(diffDay / 30)} mois`
  const years = Math.floor(diffDay / 365)
  return `il y a ${years} an${years > 1 ? 's' : ''}`
}

// SlideToConfirm + BackupPipeline ont été déplacés vers
// `components/SlideToConfirm.jsx` pour être partagés avec CoursFoldersModal,
// qui héberge maintenant l'action lock/unlock + le pipeline de backup.

const COURSE_WEEKDAY_LABELS = ['Lun.', 'Mar.', 'Mer.', 'Jeu.', 'Ven.', 'Sam.', 'Dim.']

function formatScheduleDateTime(value) {
  if (!value) return 'Non programmé'
  const normalized = String(value).includes('T') ? value : String(value).replace(' ', 'T')
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString('fr-FR', {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ─── Course Time Modal ───────────────────────────────────────────────────────
function CourseTimeModal({ onClose, onSubmit, initialDate, initialHeure, schedule }) {
  const today = new Date().toISOString().split('T')[0]
  const hasSchedule = !!schedule
  const [date, setDate] = useState(initialDate || today)
  const [heure, setHeure] = useState(schedule?.start_time || initialHeure || '')
  const [selectedWeekdays, setSelectedWeekdays] = useState(
    (schedule?.weekdays || [])
      .map((day) => Number(day))
      .filter((day) => Number.isInteger(day) && day >= 0 && day <= 6)
      .sort((a, b) => a - b)
  )
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const expectedWeekdayCount = Number(schedule?.weekly_course_count || selectedWeekdays.length || 0)
  const weekdaySelectionError = hasSchedule && expectedWeekdayCount > 0 && selectedWeekdays.length !== expectedWeekdayCount
    ? `Sélectionnez ${expectedWeekdayCount} jour${expectedWeekdayCount > 1 ? 's' : ''}.`
    : ''

  const toggleWeekday = (day) => {
    setResult(null)
    setSelectedWeekdays((current) => {
      if (current.includes(day)) return current.filter((value) => value !== day)
      return [...current, day].sort((a, b) => a - b)
    })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if ((!hasSchedule && !date) || !heure || weekdaySelectionError) return
    setLoading(true)
    setResult(null)
    const data = await onSubmit(hasSchedule ? '' : date, heure, hasSchedule ? selectedWeekdays : undefined)
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
            <h3 className="text-lg font-bold">{hasSchedule ? 'HORAIRE DES JOURNÉES' : 'HEURE DU COURS'}</h3>
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
              {hasSchedule ? (
                <div className="rounded-xl px-4 py-3" style={{ backgroundColor: '#f8fafc', border: '1px solid #e2e8f0' }}>
                  <p className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: '#64748b' }}>
                    Planning automatique
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {COURSE_WEEKDAY_LABELS.map((label, day) => {
                      const selected = selectedWeekdays.includes(day)
                      return (
                        <button
                          type="button"
                          key={label}
                          onClick={() => toggleWeekday(day)}
                          className="rounded-full px-2.5 py-1 text-xs font-semibold transition-colors"
                          style={{
                            backgroundColor: selected ? '#ede9fe' : '#ffffff',
                            color: selected ? '#7c3aed' : '#64748b',
                            border: `1px solid ${selected ? '#c4b5fd' : '#e2e8f0'}`,
                          }}
                        >
                          {label}
                        </button>
                      )
                    })}
                  </div>
                  {weekdaySelectionError && (
                    <p className="mt-2 text-xs" style={{ color: '#dc2626' }}>
                      {weekdaySelectionError}
                    </p>
                  )}
                  <p className="mt-3 text-xs" style={{ color: '#64748b' }}>
                    Le planning est verrouillé dans les 24h avant une journée, car l'audio peut être préparé automatiquement.
                  </p>
                  <div className="mt-3 space-y-1 text-xs" style={{ color: '#64748b' }}>
                    <p>{schedule.total_training_days} journée{schedule.total_training_days > 1 ? 's' : ''} au total</p>
                    <p>Prochaine journée : {formatScheduleDateTime(schedule.next_session_at)}</p>
                    <p>Dernière journée prévue : {formatScheduleDateTime(schedule.last_session_at)}</p>
                  </div>
                </div>
              ) : (
                <div>
                  <label className="block text-xs font-semibold mb-1.5" style={{ color: '#334155' }}>Date du cours</label>
                  <input
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    required
                    className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                    style={{ borderColor: '#e2e8f0', color: '#0f172a', backgroundColor: '#F8F7F5' }}
                    onFocus={(e) => { e.currentTarget.style.borderColor = '#137fec' }}
                    onBlur={(e) => { e.currentTarget.style.borderColor = '#e2e8f0' }}
                  />
                </div>
              )}
              <div>
                <label className="block text-xs font-semibold mb-1.5" style={{ color: '#334155' }}>
                  {hasSchedule ? 'Heure de début de chaque journée' : 'Heure de début'}
                </label>
                <input
                  type="time"
                  value={heure}
                  onChange={(e) => setHeure(e.target.value)}
                  required
                  className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                  style={{ borderColor: '#e2e8f0', color: '#0f172a', backgroundColor: '#F8F7F5' }}
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
                  disabled={loading || (!hasSchedule && !date) || !heure || !!weekdaySelectionError}
                  className="flex-1 flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-opacity"
                  style={{ backgroundColor: '#137fec', opacity: (loading || (!hasSchedule && !date) || !heure || !!weekdaySelectionError) ? 0.6 : 1 }}
                >
                  {loading ? (
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  ) : (
                    <Icon name="save" className="text-base" />
                  )}
                  {loading ? 'Enregistrement...' : hasSchedule ? 'Mettre à jour' : 'Enregistrer'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
