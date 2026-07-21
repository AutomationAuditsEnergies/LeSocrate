import { useState, useEffect, useRef, useMemo } from 'react'
import { createPortal } from 'react-dom'
import {
  ArrowUp,
  CalendarDays,
  ChevronLeft,
  ChevronsUpDown,
  Copy,
  Globe2,
  LogIn,
  LogOut,
  PanelLeft,
  PenLine,
  Settings,
  ShieldCheck,
  UserPlus,
  UserRound,
  UsersRound,
} from 'lucide-react'
import { apiFetch } from '../api'
import CoursFoldersModal from '../components/CoursFolders'
import { getHiddenPipelineProgress, getTeacherPreparation } from '../teacherPreparation'
import { getAudioStatusMeta, getNextCourseSession, scheduleSelectionIsValid } from '../courseSchedule'
import {
  CENTER_ONBOARDING_VERSION,
  getReusableTeacherDefaults,
  shouldShowCenterOnboarding,
} from '../centerWorkspace'

// ─── Material Icon Component ─────────────────────────────────────────────────
const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`}>{name}</span>
)

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
const ROBOT_THEME_BY_COLOR = Object.fromEntries(
  ROBOT_THEMES.map((theme) => [theme.src.match(/robot-([a-z]+)\.png/)?.[1], theme]),
)
const getRobotTheme = (id = 0, color = '') => (
  ROBOT_THEME_BY_COLOR[color] || ROBOT_THEMES[((Number(id) || 1) - 1) % ROBOT_THEMES.length]
)
const todayDateInput = () => {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}
const formatPrice = (amountCents, currency = 'eur') => (
  typeof amountCents === 'number'
    ? new Intl.NumberFormat('fr-FR', { style: 'currency', currency: currency.toUpperCase() }).format(amountCents / 100)
    : 'Tarif indisponible'
)

const PLATFORM_LOAD_TIMEOUT_MS = 30000

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
  const [newlyCreatedPlatformId, setNewlyCreatedPlatformId] = useState(null)
  const [retryingPlatformId, setRetryingPlatformId] = useState(null)
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
  const [scheduleStartDate, setScheduleStartDate] = useState(todayDateInput)
  const [scheduleStartTime, setScheduleStartTime] = useState('09:00')
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
  const creatingRef = useRef(false)
  const creationRequestRef = useRef({ fingerprint: '', id: '' })
  const audioRef = useRef(null)
  const [showCoursFoldersModal, setShowCoursFoldersModal] = useState(false)
  const [selectedCoursPlatform, setSelectedCoursPlatform] = useState(null)
  const [cardPage, setCardPage] = useState(0)
  const [teacherRosterFilter, setTeacherRosterFilter] = useState('all')
  const [workspaceSection, setWorkspaceSection] = useState('recruit')
  const [interfaceLanguage, setInterfaceLanguage] = useState(() => localStorage.getItem('center_interface_language') || 'fr')
  const [recruitmentPrefilled, setRecruitmentPrefilled] = useState(false)
  const [attendancePlatformId, setAttendancePlatformId] = useState('')
  const [attendanceDate, setAttendanceDate] = useState(todayDateInput)
  const [attendanceData, setAttendanceData] = useState(null)
  const [attendanceLoading, setAttendanceLoading] = useState(false)
  const [attendanceError, setAttendanceError] = useState('')
  const [attendanceSavingStudentId, setAttendanceSavingStudentId] = useState(null)
  const [loggingOut, setLoggingOut] = useState(false)
  const [billing, setBilling] = useState(null)
  const [billingLoading, setBillingLoading] = useState(true)
  const [activeTeacherOrderId, setActiveTeacherOrderId] = useState(null)
  const [failedTeacherOrderId, setFailedTeacherOrderId] = useState(null)
  const [retryingTeacherOrderId, setRetryingTeacherOrderId] = useState(null)
  const [orderNotice, setOrderNotice] = useState(null)
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [onboardingStep, setOnboardingStep] = useState(0)
  const [onboardingSaving, setOnboardingSaving] = useState(false)
  const [archivingPlatformId, setArchivingPlatformId] = useState(null)
  const CARDS_PER_PAGE = 10

  const handleLogout = async () => {
    if (loggingOut) return
    setLoggingOut(true)
    try {
      await apiFetch('/api/admin/logout', { method: 'POST' })
    } catch (error) {
      console.warn('Déconnexion serveur indisponible, nettoyage local appliqué.', error)
    } finally {
      localStorage.removeItem('admin_auth_token')
      localStorage.removeItem('auth_token')
      localStorage.removeItem('center_account_email')
      localStorage.removeItem('center_account_name')
      window.location.assign('/connexion-centre')
    }
  }

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

  const closeCardPanels = () => {
    setExpandedPlatform(null)
    setExpandedStudentsPlatform(null)
    setExpandedAttendancePlatform(null)
  }

  const handleToggleStudentEmails = (platformId) => {
    const next = expandedStudentsPlatform === platformId ? null : platformId
    setExpandedPlatform(null)
    setExpandedAttendancePlatform(null)
    setExpandedStudentsPlatform(next)
    if (next && !studentEmailsByPlatform[platformId]) fetchStudentEmails(platformId)
  }

  const handleToggleAttendance = (platformId) => {
    const next = expandedAttendancePlatform === platformId ? null : platformId
    setExpandedPlatform(null)
    setExpandedStudentsPlatform(null)
    setExpandedAttendancePlatform(next)
    if (next) {
      setAttendancePlatformId(String(platformId))
    }
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
    let cancelled = false
    apiFetch('/api/hr/onboarding')
      .then(async (response) => ({ response, data: await response.json().catch(() => ({})) }))
      .then(({ response, data }) => {
        if (!cancelled && response.ok && shouldShowCenterOnboarding(data)) {
          setOnboardingStep(0)
          setShowOnboarding(true)
        }
      })
      .catch((error) => console.error('Chargement onboarding centre impossible:', error))
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    apiFetch('/api/hr/billing/catalog')
      .then(async (response) => ({ response, data: await response.json().catch(() => ({})) }))
      .then(({ response, data }) => {
        if (!cancelled && response.ok && data.success) setBilling(data)
      })
      .catch((error) => console.error('Chargement facturation impossible:', error))
      .finally(() => { if (!cancelled) setBillingLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const checkout = params.get('checkout')
    const orderId = params.get('order')
    if (!checkout || !orderId) return
    // State is intentionally initialized from the external Checkout redirect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setActiveTeacherOrderId(orderId)
    setFailedTeacherOrderId(null)
    if (checkout === 'success') {
      setOrderNotice({
        tone: 'info',
        title: 'Vérification du paiement',
        message: 'Ce retour ne vaut pas confirmation. Nous attendons le webhook Stripe signé avant de lancer la préparation de votre professeur IA.',
      })
      setShowCreateModal(false)
      setShowModulesModal(false)
    } else if (checkout === 'cancelled') {
      setOrderNotice({
        tone: 'warning',
        title: 'Paiement interrompu',
        message: 'Rien n’a été créé. Votre projet est conservé et vous pouvez reprendre le paiement.',
      })
      apiFetch(`/api/hr/teacher-orders/${orderId}`)
        .then((response) => response.json())
        .then((data) => {
          const project = data.order?.project
          if (!project) return
          setFormationMode(data.order.operation_type === 'reuse_teacher' ? 'existing' : 'new')
          setTeacherFirstName(project.teacher_name || '')
          setTeacherColor(project.teacher_color || 'violet')
          setNewPlatformName(project.name || '')
          if (project.module_id) setSelectedModuleId(String(project.module_id))
          if (project.new_formation) {
            setNewFormTpName(project.new_formation.tp_name || '')
            setNewFormRncp(project.new_formation.rncp_code || '')
            setNewFormHours(String(Math.ceil(Number(project.new_formation.total_hours || 0) / 7)))
          }
          const schedule = project.new_formation?.schedule || project.schedule
          if (schedule) {
            setWeeklyCourseCount(String(schedule.weekly_course_count || 2))
            setTeachingDays(schedule.weekdays || [])
            setScheduleStartDate(schedule.start_date || todayDateInput())
            setScheduleStartTime('09:00')
          }
          creationRequestRef.current = { fingerprint: '', id: data.order.creation_request_id || '' }
          setShowCreateModal(true)
        })
        .catch((error) => console.error('Restauration commande impossible:', error))
    }
    window.history.replaceState({}, '', window.location.pathname)
  }, [])

  useEffect(() => {
    if (!activeTeacherOrderId) return undefined
    let stopped = false
    const pollOrder = async () => {
      try {
        const response = await apiFetch(`/api/hr/teacher-orders/${activeTeacherOrderId}`)
        const data = await response.json()
        if (!response.ok || !data.success || stopped) return
        const order = data.order
        if (order.fulfillment_status === 'fulfilled') {
          setNewlyCreatedPlatformId(order.platform_id || null)
          setFailedTeacherOrderId(null)
          setOrderNotice({
            tone: 'success',
            title: 'Votre professeur IA se prépare',
            message: 'Il apparaît maintenant dans Mes professeurs IA. Les cours sont produits en arrière-plan.',
          })
          setActiveTeacherOrderId(null)
          setShowCreateModal(false)
          setShowModulesModal(false)
          await fetchPlatforms()
        } else if (order.fulfillment_status === 'failed') {
          setFailedTeacherOrderId(order.id || activeTeacherOrderId)
          setOrderNotice({
            tone: 'error',
            title: 'Préparation à relancer',
            message: 'Votre paiement est conservé. Notre système n’effectuera aucun second prélèvement.',
          })
          setActiveTeacherOrderId(null)
        }
      } catch (error) {
        console.error('Suivi commande impossible:', error)
      }
    }
    pollOrder()
    const interval = window.setInterval(pollOrder, 3000)
    return () => { stopped = true; window.clearInterval(interval) }
  }, [activeTeacherOrderId])

  const handleRetryTeacherOrder = async () => {
    const orderId = failedTeacherOrderId
    if (!orderId || retryingTeacherOrderId) return
    setRetryingTeacherOrderId(orderId)
    try {
      const response = await apiFetch(`/api/hr/teacher-orders/${orderId}/retry`, { method: 'POST' })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Impossible de relancer la préparation.')
      }
      const trackedOrderId = data.order?.id || orderId
      setFailedTeacherOrderId(null)
      setActiveTeacherOrderId(trackedOrderId)
      setOrderNotice({
        tone: 'info',
        title: 'Préparation relancée',
        message: 'Votre commande payée est remise en file, sans nouveau prélèvement.',
      })
    } catch (error) {
      setOrderNotice({
        tone: 'error',
        title: 'Relance impossible',
        message: error.message || 'La préparation n’a pas pu être relancée. Réessayez dans un instant.',
      })
    } finally {
      setRetryingTeacherOrderId(null)
    }
  }

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
  const handleExpandPlatform = (platformId) => {
    closeCardPanels()
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

  const handleArchivePlatform = async (platformId) => {
    if (archivingPlatformId) return
    setArchivingPlatformId(platformId)
    try {
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/lifecycle`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lifecycle_status: 'archived' }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || !data.success) throw new Error(data.error || 'Archivage impossible')
      setPlatforms((current) => current.map((platform) => (
        platform.id === platformId
          ? { ...platform, ...(data.platform || {}), lifecycle_status: 'archived' }
          : platform
      )))
      setExpandedPlatform((current) => (current === platformId ? null : current))
      setOrderNotice({
        tone: 'success',
        title: 'Professeur archivé',
        message: 'Il quitte l’espace actif, mais son identité, ses cours et ses audios restent disponibles pour une réutilisation future.',
      })
      await fetchModules()
    } catch (error) {
      console.error('Archivage professeur impossible:', error)
      setOrderNotice({
        tone: 'error',
        title: 'Archivage impossible',
        message: error.message || 'Le professeur n’a pas été modifié.',
      })
    } finally {
      setArchivingPlatformId(null)
    }
  }

  const completeOnboarding = async () => {
    if (onboardingSaving) return
    setOnboardingSaving(true)
    try {
      const response = await apiFetch('/api/hr/onboarding/complete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: CENTER_ONBOARDING_VERSION }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) throw new Error(data.error || 'Enregistrement impossible')
      setShowOnboarding(false)
      setOnboardingStep(0)
    } catch (error) {
      console.error('Enregistrement onboarding impossible:', error)
      setOrderNotice({
        tone: 'error',
        title: 'Guide non enregistré',
        message: 'Vous pouvez continuer à utiliser la plateforme et relancer le guide avec le bouton d’aide.',
      })
      setShowOnboarding(false)
    } finally {
      setOnboardingSaving(false)
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
      if (resp.ok && data.success) {
        const refreshed = await apiFetch(`/api/hr/platforms/${courseTimePlatformId}/course-time`)
        const refreshedData = await refreshed.json()
        if (refreshed.ok && refreshedData.success) {
          setCurrentCourseTime(refreshedData)
        } else {
          setCurrentCourseTime((current) => ({
            ...(current || {}),
            success: true,
            schedule: data.schedule,
            heure_cours: data.schedule?.start_time || heureCours,
          }))
        }
        await fetchPlatforms(courseTimePlatformId)
      }
      return data
    } catch (e) {
      console.error('Erreur config cours:', e)
      return { success: false, error: e.message }
    }
  }

  const handleRetrySessionAudio = async (sessionId) => {
    const resp = await apiFetch(
      `/api/hr/platforms/${courseTimePlatformId}/sessions/${sessionId}/audio/retry`,
      { method: 'POST' },
    )
    const data = await resp.json()
    if (!resp.ok && resp.status !== 409) throw new Error(data.error || 'Reprise impossible')
    const refreshed = await apiFetch(`/api/hr/platforms/${courseTimePlatformId}/course-time`)
    const refreshedData = await refreshed.json()
    if (refreshed.ok && refreshedData.success) setCurrentCourseTime(refreshedData)
    await fetchPlatforms(courseTimePlatformId)
    return data
  }

  const handlePreviewSessionPostponement = async (sessionId, payload) => {
    const resp = await apiFetch(
      `/api/hr/platforms/${courseTimePlatformId}/sessions/${sessionId}/postpone/preview`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    )
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.error || 'Impossible de préparer ce report')
    return data.preview
  }

  const handlePostponeSession = async (sessionId, payload, idempotencyKey) => {
    const resp = await apiFetch(
      `/api/hr/platforms/${courseTimePlatformId}/sessions/${sessionId}/postpone`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify(payload),
      },
    )
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.error || 'Le report n’a pas pu être enregistré')
    if (data.schedule) {
      setCurrentCourseTime((current) => ({ ...(current || {}), success: true, schedule: data.schedule }))
    }
    const refreshed = await apiFetch(`/api/hr/platforms/${courseTimePlatformId}/course-time`)
    const refreshedData = await refreshed.json()
    if (refreshed.ok && refreshedData.success) setCurrentCourseTime(refreshedData)
    await fetchPlatforms(courseTimePlatformId)
    return data
  }

  const handleDeletePdf = (platformId) => {
    const platformName = platforms.find((platform) => platform.id === platformId)?.name
    setDeleteConfirm({ type: 'pdf', platformId, platformName })
  }

  const handleOpenCoursFolders = (platform) => {
    closeCardPanels()
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

  const handleExportAttendance = async (dailyExport = null, platformId = attendancePlatformId) => {
    if (!platformId) return
    setAttendanceError('')
    try {
      const endpoint = dailyExport?.id
        ? `/api/hr/platforms/${platformId}/attendance/exports/${dailyExport.id}`
        : `/api/hr/platforms/${platformId}/attendance/export?course_date=${encodeURIComponent(attendanceDate)}`
      const resp = await apiFetch(endpoint)
      if (!resp.ok) {
        const payload = await resp.json().catch(() => ({}))
        setAttendanceError(payload.error || 'Le fichier de cette journée n’est pas encore disponible')
        return
      }
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = dailyExport?.filename || `presences-${platformId}-${attendanceDate}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Erreur export présences:', e)
      setAttendanceError('Impossible de télécharger le fichier de présence')
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
    setScheduleStartDate(todayDateInput())
    setScheduleStartTime('09:00')
    setNewFormTpName('')
    setNewFormRncp('')
    setNewFormHours('')
    setAutoPilot(true)
    setAutoPilotMode('api_deepseek')
    creationRequestRef.current = { fingerprint: '', id: '' }
  }

  // Ouvre la modale en pré-sélectionnant le mode "Nouvelle formation".
  // Utilisé par le bouton "+ Créer un nouveau module" dans la modale Modules.
  const openCreateModuleFlow = () => {
    resetCreateForm()
    fetchModules()
    setFormationMode('new')
    setShowModulesModal(false)
    setShowCreateModal(true)
    setWorkspaceSection('recruit')
    setRecruitmentPrefilled(false)
  }

  const openCreateModal = () => {
    resetCreateForm()
    fetchModules()
    setShowModulesModal(false)
    setShowCreateModal(true)
    setWorkspaceSection('recruit')
    setRecruitmentPrefilled(false)
  }

  const showDashboardView = () => {
    setWorkspaceSection('teachers')
    setShowModulesModal(false)
    setShowCreateModal(false)
    setRecruitmentPrefilled(false)
    setModuleSearchQuery('')
  }

  const showRecruitView = () => {
    setWorkspaceSection('recruit')
    setShowModulesModal(false)
    setShowCreateModal(false)
    setRecruitmentPrefilled(false)
    setModuleSearchQuery('')
  }

  const handleAssistantComplete = (draft) => {
    resetCreateForm()
    setTeacherFirstName(draft.teacherName)
    setTeacherColor(draft.teacherColor)
    setNewFormTpName(draft.trainingName)
    setNewFormRncp(draft.rncpCode)
    setNewFormHours(String(draft.trainingDays))
    setWeeklyCourseCount(String(draft.weeklyCourseCount))
    setTeachingDays(draft.teachingDays)
    setScheduleStartDate(draft.startDate)
    setFormationMode('new')
    fetchModules()
    setShowModulesModal(false)
    setShowCreateModal(true)
    setWorkspaceSection('recruit')
    setRecruitmentPrefilled(true)
  }

  useEffect(() => {
    if (expandedAttendancePlatform) {
      fetchAttendance(expandedAttendancePlatform, attendanceDate)
    }
  }, [expandedAttendancePlatform, attendanceDate])

  useEffect(() => {
    if (!newlyCreatedPlatformId) return undefined
    const timeoutId = window.setTimeout(() => setNewlyCreatedPlatformId(null), 8000)
    return () => window.clearTimeout(timeoutId)
  }, [newlyCreatedPlatformId])

  const handleCreatePlatform = async () => {
    if (creatingRef.current) return
    const teacherName = teacherFirstName.trim()
    const selectedModule = modules.find((module) => String(module.id) === String(selectedModuleId))
    const trainingTitle = formationMode === 'existing'
      ? String(selectedModule?.tp_name || '').trim()
      : newFormTpName.trim()
    const platformName = newPlatformName.trim() || (teacherName && trainingTitle ? `${teacherName} · ${trainingTitle}` : '')
    if (!platformName || !teacherName) return

    let project = {
      name: platformName,
      teacher_name: teacherName,
      teacher_color: teacherColor || 'violet',
    }
    let operationType = 'new_teacher'
    const weeklyCount = parseInt(weeklyCourseCount, 10)
    if (!weeklyCount || weeklyCount <= 0 || teachingDays.length === 0 || weeklyCount !== teachingDays.length) {
      alert('Choisissez autant de jours que de cours par semaine.')
      return
    }
    if (!scheduleStartDate || !scheduleStartTime) {
      alert('Indiquez la date de début et l’heure des journées.')
      return
    }
    if (formationMode === 'existing') {
      if (!selectedModuleId) {
        alert('Sélectionnez un ancien professeur IA.')
        return
      }
      operationType = 'reuse_teacher'
      const totalDays = Math.max(
        1,
        Number(selectedModule?.schedule?.total_training_days || Math.ceil(Number(selectedModule?.total_hours || 7) / 7)),
      )
      project = {
        ...project,
        module_id: parseInt(selectedModuleId, 10),
        schedule: {
          total_training_days: totalDays,
          weekly_course_count: weeklyCount,
          weekdays: teachingDays,
          start_date: scheduleStartDate,
          start_time: scheduleStartTime,
        },
      }
    } else {
      const rncp = newFormRncp.trim()
      const trainingDaysCount = parseInt(newFormHours, 10)
      if (!trainingTitle || !rncp || !trainingDaysCount || trainingDaysCount <= 0) {
        alert('Nom de formation, code RNCP et nombre de journées requis.')
        return
      }
      project.new_formation = {
        tp_name: trainingTitle,
        rncp_code: rncp,
        total_hours: trainingDaysCount * 7,
        schedule: {
          total_training_days: trainingDaysCount,
          weekly_course_count: weeklyCount,
          weekdays: teachingDays,
          start_date: scheduleStartDate,
          start_time: scheduleStartTime,
        },
      }
    }

    setCreating(true)
    creatingRef.current = true
    try {
      const requestFingerprint = JSON.stringify({ operation_type: operationType, project })
      if (
        !creationRequestRef.current.id
        || (creationRequestRef.current.fingerprint && creationRequestRef.current.fingerprint !== requestFingerprint)
      ) {
        creationRequestRef.current = {
          fingerprint: requestFingerprint,
          id: window.crypto?.randomUUID?.() || `${Date.now()}_${Math.random().toString(36).slice(2)}`,
        }
      } else {
        creationRequestRef.current.fingerprint = requestFingerprint
      }
      const resp = await apiFetch('/api/hr/teacher-orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          operation_type: operationType,
          creation_request_id: creationRequestRef.current.id,
          project,
        }),
      })
      const data = await resp.json()
      if (resp.ok && data.success) {
        if (data.next_action === 'redirect' && data.checkout_url) {
          window.location.assign(data.checkout_url)
          return
        }
        setActiveTeacherOrderId(data.order.id)
        setOrderNotice({
          tone: 'info',
          title: billing?.payment_required === false ? 'Préparation lancée' : 'Paiement confirmé',
          message: 'Votre professeur IA va apparaître dans Mes professeurs IA et se préparer en arrière-plan.',
        })
        setShowCreateModal(false)
        resetCreateForm()
        setShowModulesModal(false)
      } else {
        alert(data.error || 'Impossible de lancer la commande.')
      }
    } catch (e) {
      console.error('Erreur commande professeur IA:', e)
      alert('Impossible de lancer la commande.')
    } finally {
      creatingRef.current = false
      setCreating(false)
    }
  }

  const handleRetryTeacherPreparation = async (platform) => {
    if (!platform?.source_formation_id || retryingPlatformId) return
    setRetryingPlatformId(platform.id)
    try {
      const response = await apiFetch(
        `/api/formation/${platform.source_formation_id}/run-auto/resume`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force: false }),
        },
      )
      const payload = await response.json()
      if (![200, 202, 409].includes(response.status)) {
        throw new Error(payload.error || 'Reprise impossible')
      }
      setPlatforms((current) => current.map((item) => (
        item.id === platform.id
          ? {
              ...item,
              status: 'pending',
              pipeline_auto_pilot_error: '',
              teacher_preparation: {
                status: 'preparing',
                progress: item.teacher_preparation?.progress || 8,
                stage: payload.next_step ? 'Reprise de la préparation' : 'Initialisation',
                can_retry: false,
              },
            }
          : item
      )))
      await fetchPlatforms()
    } catch (error) {
      console.error('Erreur reprise professeur IA:', error)
      setPlatformsErrorTone('error')
      setPlatformsError(error.message || 'Impossible de reprendre la préparation.')
    } finally {
      setRetryingPlatformId(null)
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

  // Palette blanche commune aux références Coursebox et Delos. Le violet reste
  // réservé aux actions et aux états actifs de l'espace centre.
  const colors = {
    bg: '#FFFFFF',
    cardBg: '#FFFFFF',
    innerBg: '#F7F7F6',
    text: '#18181B',
    textSecondary: '#3F3F46',
    textMuted: '#6B6B72',
    border: '#D9D9DE',
    borderLight: '#E9E9EC',
    hoverBg: '#F5F5F6',
    primary: '#6D4AC7',
    gridOpacity: '0',
  }
  const platformsAlertIsWarning = platformsErrorTone === 'warning'
  const teacherRosterVisible = !showModulesModal && !showCreateModal && workspaceSection === 'teachers'

  return (
    <div className={darkMode ? 'dark' : ''}>
      <div className="relative flex h-screen overflow-hidden" style={{ backgroundColor: colors.bg, fontFamily: 'Inter, sans-serif' }}>
        <CenterWorkspaceSidebar
          colors={colors}
          activeSection={workspaceSection}
          onShowTeachers={showDashboardView}
          onShowRecruit={showRecruitView}
          onLogout={handleLogout}
          loggingOut={loggingOut}
          language={interfaceLanguage}
          onLanguageChange={(language) => {
            setInterfaceLanguage(language)
            localStorage.setItem('center_interface_language', language)
          }}
        />

        <div className="m-2 ml-0 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border" style={{ borderColor: colors.borderLight }}>
          <div className="flex h-14 items-center justify-between border-b px-4 md:hidden" style={{ borderColor: colors.borderLight, backgroundColor: colors.cardBg }}>
            <span className="text-sm font-semibold" style={{ color: colors.text }}>
              {workspaceSection === 'teachers' ? 'Mes professeurs' : 'Recruter un professeur'}
            </span>
            <div className="flex items-center gap-1">
              <button type="button" onClick={showRecruitView} className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:bg-[#F3F4F6]" aria-label="Recruter un professeur" style={{ color: '#3F3F46' }}>
                <Icon name="person_add_alt_1" className="text-lg" />
              </button>
              <button type="button" onClick={showDashboardView} className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:bg-[#F3F4F6]" aria-label="Mes professeurs" style={{ color: '#3F3F46' }}>
                <Icon name="groups" className="text-lg" />
              </button>
            </div>
          </div>

        <main className={`relative z-10 min-h-0 min-w-0 flex-1 bg-white px-4 sm:px-6 lg:px-8 ${teacherRosterVisible ? 'overflow-hidden' : 'overflow-y-auto pb-12'}`}>
          <div className="mx-auto flex h-full min-h-0 w-full max-w-[1480px] flex-col pt-4 md:pt-6">
          {orderNotice && (
            <div
              className="mb-6 flex items-start gap-3 rounded-xl border px-4 py-3.5 text-sm"
              style={{
                backgroundColor: orderNotice.tone === 'success' ? (darkMode ? 'rgba(6,78,59,.24)' : '#ecfdf5') : orderNotice.tone === 'error' ? (darkMode ? 'rgba(127,29,29,.2)' : '#fef2f2') : (darkMode ? 'rgba(76,29,149,.18)' : '#f5f3ff'),
                borderColor: orderNotice.tone === 'success' ? '#a7f3d0' : orderNotice.tone === 'error' ? '#fecaca' : '#ddd6fe',
                color: colors.text,
              }}
            >
              <Icon name={orderNotice.tone === 'success' ? 'check_circle' : orderNotice.tone === 'error' ? 'error_outline' : 'hourglass_top'} className="mt-0.5 text-lg" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold">{orderNotice.title}</p>
                <p className="mt-0.5 leading-5" style={{ color: colors.textSecondary }}>{orderNotice.message}</p>
                {failedTeacherOrderId && (
                  <button
                    type="button"
                    onClick={handleRetryTeacherOrder}
                    disabled={Boolean(retryingTeacherOrderId)}
                    className="mt-3 inline-flex items-center gap-2 rounded-lg px-3 py-2 font-semibold text-white disabled:cursor-wait disabled:opacity-60"
                    style={{ backgroundColor: colors.primary }}
                  >
                    <Icon name={retryingTeacherOrderId ? 'hourglass_top' : 'refresh'} className="text-base" />
                    {retryingTeacherOrderId ? 'Relance en cours…' : 'Relancer la préparation'}
                  </button>
                )}
              </div>
              <button type="button" onClick={() => setOrderNotice(null)} className="rounded p-1" aria-label="Fermer">
                <Icon name="close" className="text-base" />
              </button>
            </div>
          )}
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
              onUseModule={(module) => {
                const defaults = getReusableTeacherDefaults(module)
                openCreateModal()
                setFormationMode('existing')
                setSelectedModuleId(String(module.id))
                setTeacherFirstName(defaults.teacherName)
                setTeacherColor(defaults.teacherColor)
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
              scheduleStartDate={scheduleStartDate}
              setScheduleStartDate={setScheduleStartDate}
              scheduleStartTime={scheduleStartTime}
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
              billing={billing}
              billingLoading={billingLoading}
              prefilledFromAssistant={recruitmentPrefilled}
              onCreate={handleCreatePlatform}
              onCancel={() => { setShowCreateModal(false); setRecruitmentPrefilled(false); resetCreateForm() }}
            />
          ) : workspaceSection === 'recruit' ? (
            <RecruitmentAssistant
              colors={colors}
              modules={modules}
              onComplete={handleAssistantComplete}
              onManualCreate={openCreateModal}
            />
          ) : (
            <PlatformCardsView
              platforms={platforms}
              cardPage={cardPage}
              setCardPage={setCardPage}
              cardsPerPage={CARDS_PER_PAGE}
              rosterFilter={teacherRosterFilter}
              onRosterFilterChange={(value) => {
                setTeacherRosterFilter(value)
                setCardPage(0)
              }}
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
                closeCardPanels()
                setSelectedPlatform(platform)
                setShowPdfModal(true)
              }}
              onOpenCourseTimeModal={async (platform) => {
                closeCardPanels()
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
              onArchivePlatform={handleArchivePlatform}
              onCloseCardPanels={closeCardPanels}
              archivingPlatformId={archivingPlatformId}
              newlyCreatedPlatformId={newlyCreatedPlatformId}
              retryingPlatformId={retryingPlatformId}
              onRetryPreparation={handleRetryTeacherPreparation}
            />
          )}
          </div>
        </main>
      </div>

      {/* Modal Audios */}
      {showAudiosModal && selectedPlatformId && (
        <AudiosModal
          platformId={selectedPlatformId}
          audios={platformAudios[selectedPlatformId] || []}
          loading={audiosLoading === selectedPlatformId}
          onClose={() => setShowAudiosModal(false)}
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
          schedule={currentCourseTime?.schedule}
          onRetryAudio={handleRetrySessionAudio}
          onPreviewPostponement={handlePreviewSessionPostponement}
          onPostponeSession={handlePostponeSession}
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

      {showOnboarding && (
        <CenterOnboarding
          colors={colors}
          darkMode={darkMode}
          step={onboardingStep}
          onStepChange={setOnboardingStep}
          onClose={() => setShowOnboarding(false)}
          onComplete={completeOnboarding}
          saving={onboardingSaving}
        />
      )}

    </div>
    </div>
  )
}

function CenterWorkspaceSidebar({
  colors,
  activeSection,
  onShowTeachers,
  onShowRecruit,
  onLogout,
  loggingOut,
  language,
  onLanguageChange,
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [accountPanel, setAccountPanel] = useState('menu')
  const accountEmail = localStorage.getItem('center_account_email') || 'Compte centre'
  const accountName = localStorage.getItem('center_account_name') || 'Centre de formation'
  const isSignedIn = Boolean(
    localStorage.getItem('admin_auth_token')
    || localStorage.getItem('auth_token')
    || localStorage.getItem('center_account_email'),
  )
  const initials = accountName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase() || 'CF'
  const navItems = [
    { id: 'recruit', label: 'Recruter un professeur', icon: UserPlus, onClick: onShowRecruit },
    { id: 'teachers', label: 'Mes professeurs', icon: UsersRound, onClick: onShowTeachers },
  ]

  return (
    <aside
      className={`relative z-30 hidden h-screen min-h-0 shrink-0 flex-col md:flex ${collapsed ? 'w-[72px]' : 'w-[248px]'}`}
      style={{ backgroundColor: '#F7F7F5', transition: 'width 180ms cubic-bezier(0.16, 1, 0.3, 1)' }}
      aria-label="Navigation de l’espace centre"
    >
      <div className={`flex h-16 shrink-0 items-center ${collapsed ? 'justify-center px-2' : 'justify-between px-4'}`}>
        {!collapsed && (
          <img src="/cadrenza-mark.svg" alt="Cadrenza" className="h-[30px] w-[30px] rounded-md" />
        )}
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="flex h-8 w-8 items-center justify-center rounded-md text-[#6B6B68] transition-colors duration-150 hover:bg-black/[0.055] hover:text-[#191918] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60"
          aria-label={collapsed ? 'Déployer la barre latérale' : 'Réduire la barre latérale'}
          aria-expanded={!collapsed}
        >
          <PanelLeft size={17} strokeWidth={1.65} aria-hidden="true" />
        </button>
      </div>

      <nav className={`mt-4 space-y-2 ${collapsed ? 'px-2' : 'px-3'}`}>
        {navItems.map((item) => {
          const selected = activeSection === item.id
          const NavIcon = item.icon
          return (
            <button
              key={item.id}
              type="button"
              onClick={item.onClick}
              aria-current={selected ? 'page' : undefined}
              className={`flex min-h-8 w-full items-center rounded-md py-1.5 text-left text-sm font-medium transition-colors duration-150 hover:bg-black/[0.045] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60 ${collapsed ? 'justify-center px-2' : 'gap-2.5 px-2'}`}
              style={{
                backgroundColor: selected ? '#E9E9E7' : 'transparent',
                color: selected ? '#191918' : '#5F5E5A',
              }}
              title={collapsed ? item.label : undefined}
            >
              <NavIcon size={17} strokeWidth={selected ? 1.8 : 1.6} aria-hidden="true" />
              {!collapsed && <span>{item.label}</span>}
            </button>
          )
        })}
      </nav>

      <div className={`mt-auto ${collapsed ? 'p-2' : 'p-2'}`}>
        <details className="group relative" onToggle={(event) => { if (!event.currentTarget.open) setAccountPanel('menu') }}>
          <summary className={`flex cursor-pointer list-none items-center rounded-md py-1.5 transition-colors duration-150 hover:bg-black/[0.045] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60 ${collapsed ? 'justify-center px-1' : 'gap-2.5 px-2'}`}>
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#191918] text-[11px] font-semibold text-white">
              {initials}
            </span>
            {!collapsed && (
              <>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium leading-4 text-[#191918]">{accountName}</span>
                  <span className="mt-0.5 block truncate text-xs leading-4 text-[#73736F]">{accountEmail}</span>
                </span>
                <ChevronsUpDown size={15} strokeWidth={1.6} className="text-[#73736F]" aria-hidden="true" />
              </>
            )}
          </summary>

          <div className={`absolute bottom-[calc(100%+6px)] overflow-hidden rounded-lg border border-black/10 bg-white shadow-[0_2px_8px_rgba(0,0,0,0.08)] ${collapsed ? 'left-0 w-[220px]' : 'left-0 w-full'}`}>
            {accountPanel === 'menu' && (
              <div className="p-1.5">
                <button type="button" onClick={() => setAccountPanel('profile')} className="flex min-h-8 w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-[#5F5E5A] transition-colors hover:bg-[#F6F5F4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60">
                  <UserRound size={16} strokeWidth={1.6} aria-hidden="true" />
                  <span>Profil</span>
                </button>
                <button type="button" onClick={() => setAccountPanel('settings')} className="flex min-h-8 w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-[#5F5E5A] transition-colors hover:bg-[#F6F5F4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60">
                  <Settings size={16} strokeWidth={1.6} aria-hidden="true" />
                  <span>Paramètres</span>
                </button>
                <button
                  type="button"
                  onClick={isSignedIn ? onLogout : () => window.location.assign('/connexion-centre')}
                  disabled={isSignedIn && loggingOut}
                  className="flex min-h-8 w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-[#5F5E5A] transition-colors hover:bg-[#F6F5F4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60 disabled:opacity-60"
                >
                  {isSignedIn ? <LogOut size={16} strokeWidth={1.6} aria-hidden="true" /> : <LogIn size={16} strokeWidth={1.6} aria-hidden="true" />}
                  {isSignedIn ? (loggingOut ? 'Déconnexion…' : 'Se déconnecter') : 'Se connecter'}
                </button>
              </div>
            )}

            {accountPanel === 'profile' && (
              <div className="p-3">
                <button type="button" onClick={() => setAccountPanel('menu')} className="mb-3 flex items-center gap-1 rounded-md px-1 py-1 text-xs font-medium text-[#73736F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60">
                  <ChevronLeft size={14} strokeWidth={1.6} aria-hidden="true" /> Retour
                </button>
                <p className="truncate text-sm font-semibold" style={{ color: colors.text }}>{accountName}</p>
                <p className="mt-1 truncate text-xs" style={{ color: colors.textMuted }}>{accountEmail}</p>
              </div>
            )}

            {accountPanel === 'settings' && (
              <div className="p-3">
                <button type="button" onClick={() => setAccountPanel('menu')} className="mb-3 flex items-center gap-1 rounded-md px-1 py-1 text-xs font-medium text-[#73736F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60">
                  <ChevronLeft size={14} strokeWidth={1.6} aria-hidden="true" /> Retour
                </button>
                <p className="mb-2 text-xs font-semibold" style={{ color: colors.text }}>Langue de l’interface</p>
                <div className="grid grid-cols-2 gap-2">
                  {['fr', 'en'].map((option) => (
                    <button key={option} type="button" onClick={() => onLanguageChange(option)} className="rounded-md border px-3 py-2 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60" style={{ backgroundColor: language === option ? '#F2F9FF' : '#fff', borderColor: language === option ? '#97CFF8' : '#DFDCD9', color: language === option ? '#005BAB' : '#73736F' }}>
                      {option.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </details>
      </div>
    </aside>
  )
}

const RECRUITMENT_STEPS = [
  { id: 'teacherName', question: 'Comment souhaitez-vous appeler ce professeur IA ?', placeholder: 'Ex. Pierre, Lina, Sofia…', type: 'text' },
  { id: 'trainingName', question: 'Quelle formation va-t-il délivrer ?', placeholder: 'Ex. TP Conseiller relation client à distance', type: 'text' },
  { id: 'rncpCode', question: 'Quel est le code RNCP de cette formation ?', placeholder: 'Ex. 35304', type: 'number' },
  { id: 'rncpConfirm', question: 'S’agit-il bien de cette formation ?', type: 'confirm' },
  { id: 'trainingDays', question: 'Combien de journées de formation faut-il prévoir au total ?', placeholder: 'Ex. 52', type: 'number' },
  { id: 'weeklyCourseCount', question: 'Combien de journées de cours auront lieu chaque semaine ?', type: 'frequency' },
  { id: 'teachingDays', question: 'Quels jours de la semaine souhaitez-vous programmer ?', type: 'days' },
  { id: 'startDate', question: 'À quelle date la formation doit-elle commencer ?', type: 'date' },
  { id: 'teacherColor', question: 'Quelle couleur souhaitez-vous pour le robot professeur ?', type: 'color' },
]

const RECRUITMENT_DAY_OPTIONS = [
  { id: 'lundi', label: 'Lundi' },
  { id: 'mardi', label: 'Mardi' },
  { id: 'mercredi', label: 'Mercredi' },
  { id: 'jeudi', label: 'Jeudi' },
  { id: 'vendredi', label: 'Vendredi' },
]

const RECRUITMENT_COLOR_OPTIONS = [
  { id: 'violet', label: 'Violet', value: '#8B5CF6', image: '/robot-violet.png' },
  { id: 'blue', label: 'Bleu', value: '#3B82F6', image: '/robot-blue.png' },
  { id: 'pink', label: 'Rose', value: '#EC4899', image: '/robot-pink.png' },
  { id: 'green', label: 'Vert', value: '#10B981', image: '/robot-green.png' },
  { id: 'amber', label: 'Ambre', value: '#F59E0B', image: '/robot-amber.png' },
]

const RECRUITMENT_CHOICE_TYPES = new Set(['confirm', 'frequency', 'days', 'color'])
const RECRUITMENT_PLACEHOLDER_EXAMPLES = [
  'Recruter un professeur pour le TP Conseiller relation client à distance',
  'Préparer un professeur pour une nouvelle promotion en septembre',
  'Réutiliser un professeur et ses cours pour un nouveau groupe',
]

function useAnimatedPlaceholder(examples) {
  const [reducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [exampleIndex, setExampleIndex] = useState(0)
  const [characterCount, setCharacterCount] = useState(() => reducedMotion ? examples[0].length : 0)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    const example = examples[exampleIndex]
    if (reducedMotion) return undefined

    let delay = deleting ? 24 : 48
    if (!deleting && characterCount === example.length) delay = 1500
    if (deleting && characterCount === 0) delay = 420

    const timeoutId = window.setTimeout(() => {
      if (!deleting && characterCount === example.length) {
        setDeleting(true)
        return
      }
      if (deleting && characterCount === 0) {
        setDeleting(false)
        setExampleIndex((index) => (index + 1) % examples.length)
        return
      }
      setCharacterCount((count) => count + (deleting ? -1 : 1))
    }, delay)

    return () => window.clearTimeout(timeoutId)
  }, [characterCount, deleting, exampleIndex, examples, reducedMotion])

  return examples[exampleIndex].slice(0, characterCount)
}

function getRecruitmentAssistantText(step, draft, matchingModule) {
  if (!step) return ''
  if (step.id === 'rncpConfirm') {
    const reference = matchingModule
      ? `${matchingModule.tp_name}, RNCP ${matchingModule.rncp_code}`
      : `${draft.trainingName}, RNCP ${draft.rncpCode}`
    return `Je vérifie la référence avant de continuer : ${reference}.`
  }
  if (step.id === 'weeklyCourseCount') return 'Définissons maintenant le rythme hebdomadaire de la formation.'
  if (step.id === 'teachingDays') return 'Choisissez les jours qui correspondent à ce rythme.'
  if (step.id === 'startDate') return 'Il reste à fixer la date de démarrage de la formation.'
  if (step.id === 'teacherColor') return 'Dernier choix : l’identité visuelle du professeur IA.'
  return step.question
}

function RecruitmentAssistant({ colors, modules, onComplete, onManualCreate }) {
  const [started, setStarted] = useState(false)
  const [brief, setBrief] = useState('')
  const [stepIndex, setStepIndex] = useState(0)
  const [answer, setAnswer] = useState('')
  const [draft, setDraft] = useState({
    teacherName: '',
    trainingName: '',
    rncpCode: '',
    trainingDays: '',
    weeklyCourseCount: 2,
    teachingDays: ['mardi', 'jeudi'],
    startDate: todayDateInput(),
    teacherColor: 'violet',
  })
  const [history, setHistory] = useState([])
  const animatedPlaceholder = useAnimatedPlaceholder(RECRUITMENT_PLACEHOLDER_EXAMPLES)
  const currentStep = RECRUITMENT_STEPS[stepIndex]
  const matchingModule = modules.find((module) => String(module.rncp_code || '').replace(/\D/g, '') === String(draft.rncpCode || '').replace(/\D/g, ''))
  const completed = stepIndex >= RECRUITMENT_STEPS.length
  const currentIsChoice = Boolean(currentStep && RECRUITMENT_CHOICE_TYPES.has(currentStep.type))

  const displayAnswer = (step, value) => {
    if (step.id === 'teachingDays') return value.map((day) => RECRUITMENT_DAY_OPTIONS.find((option) => option.id === day)?.label || day).join(', ')
    if (step.id === 'teacherColor') return RECRUITMENT_COLOR_OPTIONS.find((color) => color.id === value)?.label || value
    if (step.id === 'weeklyCourseCount') return `${value} jour${Number(value) > 1 ? 's' : ''} par semaine`
    if (step.id === 'trainingDays') return `${value} journées`
    if (step.id === 'rncpCode') return `RNCP ${String(value).replace(/\D/g, '')}`
    return String(value)
  }

  const advance = (value) => {
    if (!currentStep) return
    if (currentStep.id === 'rncpConfirm' && value === 'Corriger') {
      const correctedDraft = { ...draft, trainingName: '', rncpCode: '' }
      setDraft(correctedDraft)
      setHistory((current) => [
        ...current,
        { role: 'user', text: value },
        { role: 'assistant', text: 'D’accord, reprenons le nom de la formation. Quelle formation va-t-il délivrer ?' },
      ])
      setStepIndex(1)
      setAnswer('')
      return
    }
    const normalizedValue = currentStep.id === 'rncpCode' ? String(value).replace(/\D/g, '') : value
    const nextDraft = currentStep.id === 'rncpConfirm'
      ? draft
      : { ...draft, [currentStep.id]: normalizedValue }
    const nextIndex = stepIndex + 1
    const nextStep = RECRUITMENT_STEPS[nextIndex]
    const nextMatchingModule = modules.find((module) => String(module.rncp_code || '').replace(/\D/g, '') === String(nextDraft.rncpCode || '').replace(/\D/g, ''))
    setDraft(nextDraft)
    setHistory((current) => [
      ...current,
      { role: 'user', text: displayAnswer(currentStep, currentStep.id === 'rncpConfirm' ? 'Oui, continuer' : normalizedValue) },
      ...(nextStep ? [{ role: 'assistant', text: getRecruitmentAssistantText(nextStep, nextDraft, nextMatchingModule) }] : []),
    ])
    setStepIndex(nextIndex)
    setAnswer('')
  }

  const submitInitialBrief = (event) => {
    event.preventDefault()
    const value = brief.trim()
    if (!value) return
    setStarted(true)
    setHistory([
      { role: 'user', text: value },
      { role: 'assistant', text: 'Pour préparer ce professeur, j’ai besoin de quelques précisions rapides.' },
      { role: 'assistant', text: getRecruitmentAssistantText(RECRUITMENT_STEPS[0], draft, null) },
    ])
    setBrief('')
  }

  const submitAnswer = (event) => {
    event.preventDefault()
    const value = answer.trim()
    if (!value) return
    if (currentStep?.type === 'number' && Number(value) <= 0) return
    advance(value)
  }

  const toggleDay = (day) => {
    setDraft((current) => {
      const selected = current.teachingDays.includes(day)
      const teachingDays = selected
        ? current.teachingDays.filter((item) => item !== day)
        : current.teachingDays.length < Number(current.weeklyCourseCount)
          ? [...current.teachingDays, day]
          : current.teachingDays
      return { ...current, teachingDays }
    })
  }

  if (!started) {
    const suggestions = [
      { icon: ShieldCheck, text: 'Recruter un professeur pour un titre professionnel RNCP' },
      { icon: UserPlus, text: 'Préparer un professeur pour une nouvelle promotion' },
      { icon: Copy, text: 'Réutiliser un professeur et ses cours existants' },
      { icon: CalendarDays, text: 'Planifier une formation dès le mois prochain' },
    ]
    return (
      <section className="mx-auto flex min-h-full w-full max-w-5xl flex-col justify-start pt-16 sm:pt-20 lg:pt-24">
        <div className="mx-auto w-full max-w-[800px]">
          <div className="mb-7 text-center">
            <h1 className="text-[2rem] font-semibold leading-tight tracking-[-0.035em] sm:text-[2.4rem]" style={{ color: colors.text }}>Quel professeur recruterez-vous ?</h1>
            <p className="mx-auto mt-2.5 max-w-2xl text-sm leading-6" style={{ color: colors.textMuted }}>Décrivez votre besoin, puis précisez la formation et son calendrier.</p>
          </div>

          <form onSubmit={submitInitialBrief} className="mx-auto max-w-[760px] rounded-xl border bg-white p-3" style={{ borderColor: '#DFDCD9' }}>
            <label htmlFor="recruitment-brief" className="sr-only">Décrire le professeur recherché</label>
            <textarea
              id="recruitment-brief"
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              placeholder={animatedPlaceholder}
              rows={3}
              className="min-h-[82px] w-full resize-none bg-transparent px-2 py-1 text-[15px] leading-6 outline-none placeholder:text-[#73736F]"
              style={{ color: colors.text }}
              autoFocus
            />
            <div className="mt-1 flex items-center justify-between pt-1">
              <span className="inline-flex items-center gap-1.5 px-2 text-xs font-medium text-[#73736F]">
                <Globe2 size={15} strokeWidth={1.6} aria-hidden="true" />
                FR
              </span>
              <button type="submit" disabled={!brief.trim()} className="flex h-9 w-9 items-center justify-center rounded-full bg-[#097FE8] text-white transition-colors duration-150 hover:bg-[#0075DE] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-[#C7C5C1]" aria-label="Commencer la configuration">
                <ArrowUp size={17} strokeWidth={1.8} aria-hidden="true" />
              </button>
            </div>
          </form>

          <div className="mx-auto mt-3 flex max-w-[760px] flex-col gap-3 rounded-lg bg-[#F7F7F5] px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[13px] font-medium text-[#191918]">Vous préférez renseigner les informations vous-même ?</p>
              <p className="mt-0.5 text-xs text-[#73736F]">Ouvrez directement le formulaire complet.</p>
            </div>
            <button type="button" onClick={onManualCreate} className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-md border border-black/10 bg-white px-3 text-[13px] font-medium text-[#191918] transition-colors duration-150 hover:bg-[#F6F5F4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60">
              <PenLine size={15} strokeWidth={1.6} aria-hidden="true" />
              <span>Recruter manuellement</span>
            </button>
          </div>

          <div className="mx-auto mt-5 max-w-[760px]">
            <div className="space-y-0.5">
              {suggestions.map((suggestion) => {
                const SuggestionIcon = suggestion.icon
                return (
                  <button key={suggestion.text} type="button" onClick={() => setBrief(suggestion.text)} className="flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left text-sm leading-5 text-[#5F5E5A] transition-colors duration-150 hover:bg-[#F7F7F5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/60">
                    <SuggestionIcon size={17} strokeWidth={1.6} aria-hidden="true" />
                    <span>{suggestion.text}</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className="mx-auto flex min-h-[calc(100vh-6rem)] w-full max-w-5xl flex-col py-6">
      <div className="flex items-center justify-between gap-4 border-b pb-4" style={{ borderColor: colors.borderLight }}>
        <div>
          <h1 className="text-lg font-semibold" style={{ color: colors.text }}>Nouveau professeur IA</h1>
          <p className="mt-0.5 text-xs" style={{ color: colors.textMuted }}>{completed ? 'Configuration prête à vérifier' : `Question ${Math.min(stepIndex + 1, RECRUITMENT_STEPS.length)} sur ${RECRUITMENT_STEPS.length}`}</p>
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-end py-8">
        <div className="space-y-6">
          {history.map((message, index) => (
            <div key={`${message.role}-${index}`} className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
              {message.role === 'user' ? (
                <div className="max-w-[78%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm leading-6" style={{ backgroundColor: '#ECE8E2', color: colors.text }}>
                  {message.text}
                </div>
              ) : (
                <div className="flex max-w-[88%] items-start gap-3">
                  <img src="/cadrenza-mark.svg" alt="" className="mt-0.5 h-8 w-8 shrink-0 rounded-lg" />
                  <p className="pt-1 text-sm leading-6" style={{ color: colors.text }}>{message.text}</p>
                </div>
              )}
            </div>
          ))}
        </div>

        {completed ? (
          <div className="recruitment-review-enter mt-8 rounded-2xl bg-white p-5 sm:p-6" style={{ boxShadow: '0 8px 24px rgba(41, 32, 24, 0.08)' }}>
            <div className="flex items-start gap-5">
              <img src={RECRUITMENT_COLOR_OPTIONS.find((color) => color.id === draft.teacherColor)?.image} alt="" className="teacher-robot-float h-24 w-24 shrink-0 object-contain" />
              <div className="min-w-0 flex-1">
                <p className="text-lg font-semibold" style={{ color: colors.text }}>Vérifiez la configuration proposée</p>
                <p className="mt-1 text-sm leading-6" style={{ color: colors.textMuted }}>Le formulaire de recrutement sera déjà complété. Vous pourrez encore tout modifier avant de lancer la préparation.</p>
              </div>
            </div>
            <dl className="mt-5 grid gap-x-6 gap-y-3 border-t pt-5 text-sm sm:grid-cols-2" style={{ borderColor: colors.borderLight }}>
              <div><dt style={{ color: colors.textMuted }}>Professeur</dt><dd className="mt-0.5 font-medium" style={{ color: colors.text }}>{draft.teacherName}</dd></div>
              <div><dt style={{ color: colors.textMuted }}>Formation</dt><dd className="mt-0.5 font-medium" style={{ color: colors.text }}>{draft.trainingName}</dd></div>
              <div><dt style={{ color: colors.textMuted }}>Référence</dt><dd className="mt-0.5 font-medium" style={{ color: colors.text }}>RNCP {draft.rncpCode}</dd></div>
              <div><dt style={{ color: colors.textMuted }}>Calendrier</dt><dd className="mt-0.5 font-medium" style={{ color: colors.text }}>{draft.trainingDays} journées, {draft.weeklyCourseCount}/semaine</dd></div>
            </dl>
            <button type="button" onClick={() => onComplete(draft)} className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#191714] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#302D28]">
              Vérifier le professeur
              <Icon name="arrow_forward" className="text-base" />
            </button>
          </div>
        ) : (
          <div className="mt-8">
            {(currentStep.type === 'text' || currentStep.type === 'number') && (
              <form onSubmit={submitAnswer} className="flex items-center gap-2 rounded-xl bg-white p-2 pl-4" style={{ boxShadow: '0 4px 12px rgba(41, 32, 24, 0.08)' }}>
                <input type={currentStep.type === 'number' ? 'number' : 'text'} min={currentStep.type === 'number' ? '1' : undefined} value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder={currentStep.placeholder} className="min-w-0 flex-1 bg-transparent py-2.5 text-sm outline-none placeholder:text-[#68625B]" style={{ color: colors.text }} autoFocus />
                <button type="submit" disabled={!answer.trim()} className="flex h-10 w-10 items-center justify-center rounded-full bg-[#6D4AC7] text-white transition-colors disabled:bg-[#B9B5AF]" aria-label="Valider la réponse"><Icon name="arrow_upward" className="text-base" /></button>
              </form>
            )}
            {currentIsChoice && (
              <div className="overflow-hidden rounded-xl border bg-white" style={{ borderColor: colors.border }}>
                <div className="flex items-start justify-between gap-4 px-4 py-3.5 sm:px-5">
                  <div>
                    <p className="text-sm font-semibold leading-5" style={{ color: colors.text }}>{currentStep.question}</p>
                    {currentStep.id === 'rncpConfirm' && (
                      <p className="mt-1 text-xs" style={{ color: colors.textMuted }}>
                        {matchingModule ? `${matchingModule.tp_name} · RNCP ${matchingModule.rncp_code}` : `${draft.trainingName} · RNCP ${draft.rncpCode}`}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 text-xs tabular-nums" style={{ color: colors.textMuted }}>{stepIndex + 1} / {RECRUITMENT_STEPS.length}</span>
                </div>

                {currentStep.type === 'confirm' && [
                  { label: 'Oui, continuer', value: 'Oui, continuer' },
                  { label: 'Corriger la formation ou le RNCP', value: 'Corriger' },
                ].map((option, index) => (
                  <button key={option.value} type="button" onClick={() => advance(option.value)} className="flex w-full items-center gap-3 border-t px-4 py-3 text-left text-sm transition-colors hover:bg-[#F8F6F2] sm:px-5" style={{ borderColor: colors.borderLight, color: colors.text }}>
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: colors.innerBg, color: colors.textMuted }}>{index + 1}</span>
                    {option.label}
                  </button>
                ))}

                {currentStep.type === 'frequency' && [1, 2, 3, 4, 5].map((count) => (
                  <button key={count} type="button" onClick={() => advance(count)} className="flex w-full items-center gap-3 border-t px-4 py-3 text-left text-sm transition-colors hover:bg-[#F8F6F2] sm:px-5" style={{ borderColor: colors.borderLight, color: colors.text }}>
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: colors.innerBg, color: colors.textMuted }}>{count}</span>
                    {count} journée{count > 1 ? 's' : ''} par semaine
                  </button>
                ))}

                {currentStep.type === 'days' && RECRUITMENT_DAY_OPTIONS.map((day, index) => {
                  const selected = draft.teachingDays.includes(day.id)
                  return (
                    <button key={day.id} type="button" onClick={() => toggleDay(day.id)} aria-pressed={selected} className="flex w-full items-center gap-3 border-t px-4 py-3 text-left text-sm transition-colors hover:bg-[#F8F6F2] sm:px-5" style={{ borderColor: colors.borderLight, color: colors.text }}>
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: selected ? '#6D4AC7' : colors.innerBg, color: selected ? '#fff' : colors.textMuted }}>{selected ? <Icon name="check" className="text-sm" /> : index + 1}</span>
                      {day.label}
                    </button>
                  )
                })}

                {currentStep.type === 'color' && RECRUITMENT_COLOR_OPTIONS.map((color, index) => {
                  const selected = draft.teacherColor === color.id
                  return (
                    <button key={color.id} type="button" onClick={() => setDraft((current) => ({ ...current, teacherColor: color.id }))} aria-pressed={selected} className="flex w-full items-center gap-3 border-t px-4 py-3 text-left text-sm transition-colors hover:bg-[#F8F6F2] sm:px-5" style={{ borderColor: colors.borderLight, color: colors.text }}>
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: selected ? `${color.value}22` : colors.innerBg, color: colors.textMuted }}>{index + 1}</span>
                      <span className="h-3 w-3 rounded-full" style={{ backgroundColor: color.value }} />
                      <span className="flex-1">{color.label}</span>
                      {selected && <Icon name="check" className="text-base" style={{ color: color.value }} />}
                    </button>
                  )
                })}

                {(currentStep.type === 'days' || currentStep.type === 'color') && (
                  <div className="flex items-center justify-between gap-3 border-t px-4 py-3 sm:px-5" style={{ borderColor: colors.borderLight }}>
                    <span className="text-xs" style={{ color: colors.textMuted }}>
                      {currentStep.type === 'days' ? `${draft.teachingDays.length} jour${draft.teachingDays.length > 1 ? 's' : ''} sélectionné${draft.teachingDays.length > 1 ? 's' : ''}` : RECRUITMENT_COLOR_OPTIONS.find((color) => color.id === draft.teacherColor)?.label}
                    </span>
                    <button type="button" disabled={currentStep.type === 'days' && draft.teachingDays.length !== Number(draft.weeklyCourseCount)} onClick={() => advance(currentStep.type === 'days' ? draft.teachingDays : draft.teacherColor)} className="rounded-lg bg-[#191714] px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-35">
                      Valider ce choix
                    </button>
                  </div>
                )}
              </div>
            )}
            {currentStep.type === 'date' && (
              <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-white p-3" style={{ borderColor: colors.border }}><input type="date" min={todayDateInput()} value={draft.startDate} onChange={(event) => setDraft((current) => ({ ...current, startDate: event.target.value }))} className="min-w-0 flex-1 rounded-lg border px-4 py-2.5 text-sm" style={{ borderColor: colors.borderLight, color: colors.text }} /><button type="button" onClick={() => advance(draft.startDate)} className="rounded-lg bg-[#191714] px-4 py-2.5 text-sm font-medium text-white">Valider la date</button></div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

const CENTER_ONBOARDING_STEPS = [
  {
    icon: 'school',
    eyebrow: 'Votre espace actif',
    title: 'Suivez vos professeurs IA en cours',
    description: 'Mes professeurs IA regroupe les professeurs en préparation et les promotions actives. La préparation continue en arrière-plan : vous pouvez quitter la page sans l’interrompre.',
    detail: 'Chaque carte donne accès au planning, aux cours, aux audios, aux élèves et aux présences.',
  },
  {
    icon: 'person_add',
    eyebrow: 'Création',
    title: 'Créez un nouveau professeur IA',
    description: 'Renseignez son identité, sa formation et son calendrier. Après le paiement Stripe confirmé par le serveur, la plateforme prépare ses cours de manière durable.',
    detail: 'Le prix est calculé selon le nombre de journées avant l’ouverture du paiement hébergé.',
  },
  {
    icon: 'content_copy',
    eyebrow: 'Réutilisation optimisée',
    title: 'Réutilisez un professeur sans dupliquer ses ressources',
    description: 'La bibliothèque conserve l’identité, les cours et les audios du professeur. Une nouvelle promotion partage le module Azure d’origine, avec une copie uniquement si vous modifiez un fichier.',
    detail: 'Cette architecture réduit le stockage, accélère la remise en service et reste adaptée à un grand nombre de centres.',
  },
  {
    icon: 'event_available',
    eyebrow: 'Exploitation',
    title: 'Planifiez, générez à J-1, puis archivez',
    description: 'Le planning pilote les séances et la génération audio à J-1. À la fin d’une promotion, archivez le professeur : il quitte l’espace actif sans perdre son module réutilisable.',
    detail: 'L’archivage n’efface ni l’historique PostgreSQL, ni les ressources Azure.',
  },
]

function CenterOnboarding({ colors, darkMode, step, onStepChange, onClose, onComplete, saving }) {
  const current = CENTER_ONBOARDING_STEPS[step] || CENTER_ONBOARDING_STEPS[0]
  const isLast = step === CENTER_ONBOARDING_STEPS.length - 1

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(15, 23, 42, 0.66)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="center-onboarding-title"
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-2xl shadow-2xl"
        style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}` }}
      >
        <div className="flex items-center justify-between gap-4 px-5 py-4 sm:px-6" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: colors.textMuted }}>
              Guide de l’espace centre
            </p>
            <p className="mt-1 text-xs tabular-nums" style={{ color: colors.textSecondary }}>
              Étape {step + 1} sur {CENTER_ONBOARDING_STEPS.length}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:bg-black/5 dark:hover:bg-white/5"
            style={{ color: colors.textMuted }}
            aria-label="Fermer le guide"
          >
            <Icon name="close" className="text-lg" />
          </button>
        </div>

        <div className="px-5 py-6 sm:px-8 sm:py-8">
          <div className="mb-6 flex gap-2" aria-hidden="true">
            {CENTER_ONBOARDING_STEPS.map((_, index) => (
              <span
                key={index}
                className="h-1.5 flex-1 rounded-full"
                style={{ backgroundColor: index <= step ? '#8B5CF6' : colors.border }}
              />
            ))}
          </div>
          <div
            className="flex h-12 w-12 items-center justify-center rounded-xl"
            style={{ backgroundColor: darkMode ? 'rgba(139, 92, 246, 0.15)' : '#f5f3ff', color: darkMode ? '#c4b5fd' : '#7c3aed' }}
          >
            <Icon name={current.icon} className="text-2xl" />
          </div>
          <p className="mt-5 text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#8B5CF6' }}>
            {current.eyebrow}
          </p>
          <h2 id="center-onboarding-title" className="mt-2 text-2xl font-semibold tracking-tight" style={{ color: colors.text }}>
            {current.title}
          </h2>
          <p className="mt-4 text-sm leading-6" style={{ color: colors.textSecondary }}>
            {current.description}
          </p>
          <div className="mt-5 flex items-start gap-3 rounded-xl px-4 py-3" style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}` }}>
            <Icon name="info_outline" className="mt-0.5 text-base" style={{ color: colors.textMuted }} />
            <p className="text-xs leading-5" style={{ color: colors.textMuted }}>{current.detail}</p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 px-5 py-4 sm:px-6" style={{ borderTop: `1px solid ${colors.border}` }}>
          <button
            type="button"
            onClick={() => onStepChange(Math.max(0, step - 1))}
            disabled={step === 0 || saving}
            className="rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:opacity-0"
            style={{ color: colors.textSecondary, border: `1px solid ${colors.border}` }}
          >
            Précédent
          </button>
          <button
            type="button"
            onClick={() => (isLast ? onComplete() : onStepChange(step + 1))}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white transition-colors disabled:cursor-wait disabled:opacity-60"
            style={{ backgroundColor: '#8B5CF6' }}
          >
            {saving ? 'Enregistrement…' : isLast ? 'Terminer le guide' : 'Continuer'}
            {!saving && <Icon name={isLast ? 'check' : 'arrow_forward'} className="text-base" />}
          </button>
        </div>
      </div>
    </div>
  )
}

function getTeacherRosterStage(platform = {}) {
  const lifecycle = String(platform.lifecycle_status || 'active').toLowerCase()
  if (lifecycle === 'archived') return 'archived'
  if (lifecycle === 'completed') return 'completed'

  const preparation = getTeacherPreparation(platform)
  if (preparation.status === 'preparing' || preparation.status === 'failed' || platform.status === 'pending') {
    return 'preparing'
  }

  const total = Number(platform.total_session_count || 0)
  const remaining = Number(platform.remaining_session_count || 0)
  if (total > 0 && remaining === 0) return 'completed'
  if (total > 0 && remaining === total) return 'upcoming'
  if (total > 0 && remaining > 0 && remaining < total) return 'in_progress'
  return 'ready'
}

function getTeacherRosterFilterGroup(platform = {}) {
  const stage = getTeacherRosterStage(platform)
  return stage === 'completed' || stage === 'archived' ? 'completed' : 'in_progress'
}

const TEACHER_ROSTER_FILTERS = [
  { id: 'all', label: 'Tous' },
  { id: 'in_progress', label: 'En cours' },
  { id: 'completed', label: 'Terminés' },
]

function PlatformCardsView({
  platforms,
  cardPage,
  setCardPage,
  cardsPerPage,
  rosterFilter,
  onRosterFilterChange,
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
  onArchivePlatform,
  onCloseCardPanels,
  archivingPlatformId,
  newlyCreatedPlatformId,
  retryingPlatformId,
  onRetryPreparation,
}) {
  const [rosterSearch, setRosterSearch] = useState('')
  const normalizedRosterSearch = rosterSearch.trim().toLocaleLowerCase('fr-FR')
  const searchedPlatforms = normalizedRosterSearch
    ? platforms.filter((platform) => [
      platform.teacher_name,
      platform.name,
      platform.source_tp_name,
      platform.rncp_code,
    ].some((value) => String(value || '').toLocaleLowerCase('fr-FR').includes(normalizedRosterSearch)))
    : platforms
  const filteredPlatforms = rosterFilter === 'all'
    ? searchedPlatforms
    : searchedPlatforms.filter((platform) => getTeacherRosterFilterGroup(platform) === rosterFilter)
  const filterCounts = Object.fromEntries(
    TEACHER_ROSTER_FILTERS.map((filter) => [
      filter.id,
      filter.id === 'all'
        ? platforms.length
        : platforms.filter((platform) => getTeacherRosterFilterGroup(platform) === filter.id).length,
    ]),
  )
  const totalPages = Math.ceil(filteredPlatforms.length / cardsPerPage)
  const safeCardPage = Math.min(cardPage, Math.max(0, totalPages - 1))
  const visiblePlatforms = filteredPlatforms.slice(
    safeCardPage * cardsPerPage,
    (safeCardPage + 1) * cardsPerPage,
  )

  return (
    <section className="mx-auto flex h-full min-h-0 w-full max-w-[90rem] flex-col overflow-hidden pt-8 sm:pt-12">
      <header className="mx-auto w-full max-w-[860px] text-center">
        <h1 className="text-[2rem] font-semibold leading-tight tracking-[-0.035em] sm:text-[2.4rem]" style={{ color: colors.text }}>Mes professeurs</h1>
        <p className="mt-2 text-sm" style={{ color: colors.textMuted }}>Retrouvez vos professeurs, leurs formations et leur prochaine séance.</p>
      </header>

      <div className="mx-auto mt-7 flex w-full max-w-[760px] items-center gap-2 rounded-full border bg-white p-2 pl-5" style={{ borderColor: colors.border, boxShadow: '0 3px 8px rgba(24, 24, 27, 0.07)' }}>
        <Icon name="search" className="text-xl" style={{ color: colors.textMuted }} />
        <label htmlFor="teacher-roster-search" className="sr-only">Rechercher un professeur ou une formation</label>
        <input
          id="teacher-roster-search"
          type="search"
          value={rosterSearch}
          onChange={(event) => {
            setRosterSearch(event.target.value)
            setCardPage(0)
          }}
          placeholder="Rechercher un professeur ou une formation…"
          className="min-w-0 flex-1 bg-transparent py-2 text-sm outline-none placeholder:text-[#626269]"
          style={{ color: colors.text }}
        />
      </div>

      <div className="mx-auto mt-8 flex w-full max-w-[980px] items-center gap-5" aria-hidden="true">
        <span className="h-px flex-1" style={{ backgroundColor: colors.borderLight }} />
        <span className="text-[10px] font-semibold uppercase tracking-[0.22em]" style={{ color: colors.textMuted }}>Filtrer par statut</span>
        <span className="h-px flex-1" style={{ backgroundColor: colors.borderLight }} />
      </div>

      <div className="mx-auto mt-5 flex w-full max-w-[1204px] flex-wrap items-center justify-center gap-2" role="group" aria-label="Filtrer les professeurs IA">
        {TEACHER_ROSTER_FILTERS.map((filter) => {
          const selected = rosterFilter === filter.id
          return (
            <button
              key={filter.id}
              type="button"
              onClick={() => onRosterFilterChange(filter.id)}
              aria-pressed={selected}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30"
              style={{
                backgroundColor: selected ? colors.text : 'transparent',
                color: selected ? '#FFFFFF' : colors.textSecondary,
                border: `1px solid ${selected ? colors.text : colors.border}`,
              }}
            >
              <span>{filter.label}</span>
              <span className="tabular-nums opacity-60">{filterCounts[filter.id]}</span>
            </button>
          )
        })}
      </div>

      {filteredPlatforms.length > cardsPerPage && (
        <div className="mx-auto mt-5 flex w-full max-w-[1204px] items-center justify-end gap-3">
          <span className="text-sm" style={{ color: colors.textMuted, fontVariantNumeric: 'tabular-nums' }}>
            Page <span className="font-semibold" style={{ color: colors.text }}>{safeCardPage + 1}</span> / {totalPages}
          </span>
          <button
            onClick={() => setCardPage(p => Math.max(0, p - 1))}
            disabled={safeCardPage === 0}
            aria-label="Page précédente"
            className="flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-black/5 dark:hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-30"
            style={{ border: `1px solid ${colors.border}`, color: colors.textSecondary }}
          >
            <Icon name="chevron_left" className="text-xl" />
          </button>
          <button
            onClick={() => setCardPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={safeCardPage >= totalPages - 1}
            aria-label="Page suivante"
            className="flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-black/5 dark:hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-30"
            style={{ border: `1px solid ${colors.border}`, color: colors.textSecondary }}
          >
            <Icon name="chevron_right" className="text-xl" />
          </button>
        </div>
      )}

      {filteredPlatforms.length > 0 && (
        <div className="mt-6 min-h-0 flex-1 overflow-y-auto overscroll-contain pb-6 pr-1">
        <div className="mx-auto grid w-full max-w-[1204px] grid-cols-1 items-start gap-3 sm:grid-cols-2 sm:gap-4 lg:grid-cols-4 xl:grid-cols-5">
        {visiblePlatforms.map((p) => (
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
            onArchivePlatform={() => onArchivePlatform(p.id)}
            onBeforeFlip={onCloseCardPanels}
            archiving={archivingPlatformId === p.id}
            newlyCreated={newlyCreatedPlatformId === p.id}
            retryingPreparation={retryingPlatformId === p.id}
            onRetryPreparation={() => onRetryPreparation(p)}
          />
        ))}
        </div>
        </div>
      )}
    </section>
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
            Entrées et sorties relevées automatiquement depuis la salle de cours.
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
          ['Participants', data?.students?.length || 0],
          ['Relevés automatiques', data?.students?.length || 0],
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
                  Aucune entrée dans la salle n’a été enregistrée pour cette journée.
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
                              readOnly
                              className="w-28 rounded-lg px-2 py-1.5 text-sm outline-none"
                              style={inputStyle}
                            />
                            <span className="text-xs" style={{ color: colors.textMuted }}>à</span>
                            <input
                              type="time"
                              value={slot.end || ''}
                              readOnly
                              className="w-28 rounded-lg px-2 py-1.5 text-sm outline-none"
                              style={inputStyle}
                            />
                            <button
                              type="button"
                              onClick={() => removeSlot(student.id, index)}
                              aria-label="Retirer le créneau"
                              className="hidden"
                              style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
                            >
                              <Icon name="close" className="text-base" />
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          onClick={() => addSlot(student.id)}
                          className="hidden"
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
                        disabled
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
                        value="Relevé depuis la salle"
                        readOnly
                        className="w-full rounded-lg px-3 py-2 text-sm outline-none"
                        style={inputStyle}
                      />
                    </td>
                    <td className="border-b px-4 py-4 text-right" style={{ borderColor: colors.border }}>
                      <button
                        type="button"
                        onClick={() => onSaveStudent(student)}
                        disabled={savingStudentId === student.id}
                        className="hidden"
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
  onCourseDateChange,
  onRefresh,
  onExport,
}) {
  const inputStyle = {
    backgroundColor: colors.cardBg,
    color: colors.text,
    border: `1px solid ${colors.border}`,
  }
  const students = data?.students || []
  const dailyExports = data?.daily_exports || []
  const readyExports = dailyExports.filter((item) => item.status === 'ready')
  const selectedExport = readyExports.find((item) => item.course_date === courseDate)

  const formatDate = (value) => {
    if (!value) return ''
    return new Date(`${value}T00:00:00`).toLocaleDateString('fr-FR')
  }

  return (
    <div
      className="p-1 sm:p-2"
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold" style={{ color: colors.text }}>Présence de la journée</h4>
          <p className="mt-1 text-xs leading-5" style={{ color: colors.textMuted }}>
            {students.length} participant{students.length > 1 ? 's' : ''}. Les entrées et sorties sont enregistrées automatiquement.
          </p>
        </div>
        <span
          className="flex-shrink-0 rounded-full px-2 py-1 text-[11px] font-semibold"
          style={{ backgroundColor: colors.cardBg, color: colors.textSecondary, border: `1px solid ${colors.border}` }}
        >
          Suivi automatique
        </span>
      </div>

      <div className="mb-4">
        <label className="block text-xs font-semibold" style={{ color: colors.textSecondary }}>
          Journée consultée
          <span className="mt-2 flex items-center gap-2">
            <input
              type="date"
              value={courseDate}
              onChange={(e) => onCourseDateChange(e.target.value)}
              className="min-w-0 flex-1 rounded-lg px-3 py-2 text-sm font-normal outline-none transition-shadow focus:ring-2 focus:ring-violet-500/30"
              style={inputStyle}
            />
            <button
              type="button"
              onClick={onRefresh}
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40 dark:hover:bg-white/5"
              style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
              title="Actualiser les présences"
              aria-label="Actualiser les présences"
            >
              <Icon name="refresh" className="text-base" />
            </button>
          </span>
        </label>
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

      <section className="mb-4 border-t pt-4" style={{ borderColor: colors.border }}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm font-semibold" style={{ color: colors.text }}>
            Fichiers Excel par journée
          </span>
          <button
            type="button"
            onClick={() => onExport(selectedExport || null)}
            disabled={!selectedExport}
            className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40 disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              backgroundColor: selectedExport ? '#8B5CF6' : colors.cardBg,
              color: selectedExport ? 'white' : colors.textMuted,
              border: selectedExport ? '1px solid #8B5CF6' : `1px solid ${colors.border}`,
            }}
            title={selectedExport ? 'Télécharger le relevé de cette journée' : 'Disponible automatiquement le lendemain matin'}
          >
            <Icon name="download" className="text-sm" />
            Télécharger l’Excel
          </button>
        </div>
        {dailyExports.length === 0 ? (
          <p className="text-xs leading-5" style={{ color: colors.textMuted }}>
            Le premier fichier apparaîtra ici le lendemain d’une journée de formation, à partir de 6 h.
          </p>
        ) : (
          <div className="max-h-32 space-y-1 overflow-y-auto pr-1">
            {dailyExports.map((dailyExport) => (
              <button
                key={dailyExport.id}
                type="button"
                onClick={() => dailyExport.status === 'ready' && onExport(dailyExport)}
                disabled={dailyExport.status !== 'ready'}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-black/5 disabled:cursor-default disabled:opacity-60 dark:hover:bg-white/5"
                style={{ color: colors.textSecondary, border: `1px solid ${colors.border}` }}
              >
                <Icon name="table_chart" className="text-sm" style={{ color: colors.textMuted }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs">Journée du {formatDate(dailyExport.course_date)}</span>
                  <span className="block text-[10px]" style={{ color: colors.textMuted }}>
                    {dailyExport.status === 'ready'
                      ? `${dailyExport.participant_count} participant${dailyExport.participant_count > 1 ? 's' : ''}`
                      : 'Préparation automatique en attente'}
                  </span>
                </span>
                <Icon name={dailyExport.status === 'ready' ? 'download' : 'schedule'} className="text-sm" style={{ color: colors.textMuted }} />
              </button>
            ))}
          </div>
        )}
      </section>

      {loading ? (
        <div className="flex items-center justify-center py-5">
          <div className="h-5 w-5 animate-spin rounded-full border-2" style={{ borderColor: colors.border, borderTopColor: '#8B5CF6' }} />
        </div>
      ) : students.length === 0 ? (
        <p className="py-3 text-xs" style={{ color: colors.textMuted }}>
          Aucune entrée dans la salle n’a été enregistrée pour cette journée.
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

                <div className="space-y-1.5">
                  {slots.map((slot, index) => (
                    <div
                      key={`${student.id}-${index}`}
                      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs tabular-nums"
                      style={{ backgroundColor: colors.innerBg, color: colors.textSecondary }}
                    >
                      <Icon name="login" className="text-sm" style={{ color: colors.textMuted }} />
                      <span>{slot.start || '—'}</span>
                      <span style={{ color: colors.textMuted }}>→</span>
                      <span>{slot.end || '—'}</span>
                    </div>
                  ))}
                  {slots.length === 0 && (
                    <p className="text-xs" style={{ color: colors.textMuted }}>Aucun intervalle terminé.</p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function CardToolModal({
  dialogId,
  title,
  subtitle,
  icon,
  onClose,
  colors,
  darkMode,
  widthClass = 'max-w-3xl',
  children,
}) {
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    const previousActiveElement = document.activeElement
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onCloseRef.current()
    }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
      previousActiveElement?.focus?.()
    }
  }, [])

  return createPortal(
    <div
      className="postpone-dialog-backdrop fixed inset-0 z-[80] flex items-end justify-center bg-slate-950/50 sm:items-center sm:p-5"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${dialogId}-title`}
        className={`postpone-dialog-sheet flex max-h-[92vh] w-full ${widthClass} flex-col overflow-hidden rounded-t-2xl sm:rounded-2xl`}
        style={{
          backgroundColor: colors.cardBg,
          border: `1px solid ${colors.border}`,
          boxShadow: darkMode ? '0 20px 60px rgba(0, 0, 0, 0.45)' : '0 20px 60px rgba(15, 23, 42, 0.18)',
        }}
      >
        <header className="flex items-start justify-between gap-4 border-b px-5 py-4 sm:px-6" style={{ borderColor: colors.border }}>
          <div className="flex min-w-0 items-start gap-3">
            <span
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl"
              style={{ backgroundColor: colors.innerBg, color: darkMode ? '#c4b5fd' : '#7c3aed' }}
              aria-hidden="true"
            >
              <Icon name={icon} className="text-xl" />
            </span>
            <div className="min-w-0">
              <h2 id={`${dialogId}-title`} className="text-lg font-semibold tracking-tight" style={{ color: colors.text }}>
                {title}
              </h2>
              <p className="mt-1 truncate text-xs" style={{ color: colors.textMuted }}>{subtitle}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            autoFocus
            aria-label={`Fermer ${title}`}
            className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40 dark:hover:bg-white/5"
            style={{ color: colors.textMuted }}
          >
            <Icon name="close" className="text-xl" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
          {children}
        </div>
      </section>
    </div>,
    document.body,
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
  if (module.teacher_name) return module.teacher_name
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
            {modules.map((m) => (
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
                    style={{ backgroundColor: getRobotTheme(m.source_platform_id || m.id, m.teacher_color).glow, opacity: 0.22 }}
                  />
                  <img
                    src={getRobotTheme(m.source_platform_id || m.id, m.teacher_color).src}
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
                    {m.storage_mode === 'shared' && (
                      <span
                        className="flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium"
                        style={{ backgroundColor: colors.innerBg, color: colors.textMuted, border: `1px solid ${colors.border}` }}
                        title="Cours et audios conservés une seule fois dans Azure, puis partagés entre les promotions"
                      >
                        Ressources partagées
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
                    {m.asset_count > 0 && ` · ${m.asset_count} ressource${m.asset_count > 1 ? 's' : ''}`}
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
                      onClick={() => onUseModule(m)}
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
  modules,
  formationMode,
  selectedModuleId,
  teacherFirstName,
  setTeacherFirstName,
  teacherColor,
  setTeacherColor,
  weeklyCourseCount,
  setWeeklyCourseCount,
  teachingDays,
  setTeachingDays,
  scheduleStartDate,
  setScheduleStartDate,
  scheduleStartTime,
  newFormTpName,
  setNewFormTpName,
  newFormRncp,
  setNewFormRncp,
  newFormHours,
  setNewFormHours,
  creating,
  billing,
  billingLoading,
  prefilledFromAssistant,
  onCreate,
  onCancel,
}) {
  const teacherColors = [
    { id: 'violet', label: 'Violet', swatch: '#8B5CF6', image: '/robot-violet.png' },
    { id: 'blue', label: 'Bleu', swatch: '#3B82F6', image: '/robot-blue.png' },
    { id: 'pink', label: 'Rose', swatch: '#EC4899', image: '/robot-pink.png' },
    { id: 'green', label: 'Vert', swatch: '#10B981', image: '/robot-green.png' },
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
  const selectedModule = modules.find((module) => String(module.id) === String(selectedModuleId))
  const operationType = formationMode === 'existing' ? 'reuse_teacher' : 'new_teacher'
  const product = billing?.products?.[operationType]
  const trainingDays = formationMode === 'existing'
    ? Math.max(1, Number(selectedModule?.schedule?.total_training_days || Math.ceil(Number(selectedModule?.total_hours || 7) / 7)))
    : Math.max(0, Number(newFormHours) || 0)
  const estimatedAmountCents = typeof product?.unit_amount_cents === 'number'
    ? product.unit_amount_cents * trainingDays
    : null
  const paymentRequired = billing?.payment_required !== false
  const billingReady = Boolean(billing && (!paymentRequired || product?.configured))
  const canCreateTeacher = (
    teacherFirstName.trim()
    && (formationMode === 'existing' ? selectedModule : (newFormTpName.trim() && newFormRncp.trim() && Number(newFormHours) > 0))
    && Number(weeklyCourseCount) > 0
    && Number(weeklyCourseCount) === teachingDays.length
    && teachingDays.length > 0
    && scheduleStartDate
    && scheduleStartTime
    && billingReady
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
      {prefilledFromAssistant && (
        <div className="recruitment-review-enter mb-6 flex items-center gap-4 rounded-xl bg-white px-4 py-3.5" role="status" style={{ boxShadow: '0 4px 12px rgba(41, 32, 24, 0.08)' }}>
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EDE8FF] text-[#6D4AC7]">
            <Icon name="auto_awesome" className="text-lg" />
          </span>
          <div>
            <p className="text-sm font-semibold" style={{ color: colors.text }}>Est-ce bien ce professeur IA que vous souhaitez recruter ?</p>
            <p className="mt-0.5 text-xs leading-5" style={{ color: colors.textMuted }}>Les réponses de la conversation sont déjà reportées ci-dessous. Vérifiez-les avant de continuer.</p>
          </div>
        </div>
      )}
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
            {formationMode === 'existing' ? 'Réutiliser un professeur IA' : 'Nouveau professeur IA'}
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

            {formationMode === 'existing' ? (
              <div>
                <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
                  Professeur à réutiliser
                </label>
                <div className="rounded-lg px-4 py-3" style={inputStyle}>
                  <p className="text-sm font-semibold">{selectedModule?.tp_name || 'Professeur introuvable'}</p>
                  <p className="mt-1 text-xs" style={{ color: colors.textMuted }}>
                    {selectedModule?.rncp_code ? `RNCP ${selectedModule.rncp_code}` : 'Formation archivée'}
                  </p>
                </div>
              </div>
            ) : (
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
            )}
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
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {teacherColors.map((color) => {
              const selected = teacherColor === color.id
              return (
                <button
                  key={color.id}
                  type="button"
                  onClick={() => setTeacherColor(color.id)}
                  aria-pressed={selected}
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

        {formationMode !== 'existing' && <div className="mt-5 grid gap-4 md:grid-cols-2">
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
        </div>}

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

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
              Début de la formation
            </label>
            <input
              type="date"
              value={scheduleStartDate}
              min={todayDateInput()}
              onChange={(event) => setScheduleStartDate(event.target.value)}
              className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-all"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
              Heure de chaque journée
            </label>
            <div className="flex h-12 items-center justify-between rounded-lg px-4 text-sm" style={inputStyle}>
              <span className="font-semibold" style={{ color: colors.text }}>09:00</span>
              <span className="text-xs" style={{ color: colors.textMuted }}>Horaire pédagogique fixe</span>
            </div>
            <p className="mt-2 text-xs leading-5" style={{ color: colors.textMuted }}>
              La journée suit la playlist de 09:00 à 18:30. L’audio est préparé automatiquement 24 h avant.
            </p>
          </div>
        </div>

        <div
          className="mt-7 rounded-xl border p-5"
          style={{ backgroundColor: darkMode ? 'rgba(15,23,42,.72)' : '#ffffff', borderColor: colors.border }}
        >
          <div className="flex items-start justify-between gap-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em]" style={{ color: colors.textMuted }}>
                Récapitulatif
              </p>
              <h3 className="mt-1.5 text-base font-semibold" style={{ color: colors.text }}>
                {teacherFirstName.trim() || 'Votre professeur'} · {formationMode === 'existing' ? (selectedModule?.tp_name || 'Formation') : (newFormTpName.trim() || 'Formation')}
              </h3>
              <p className="mt-2 text-sm leading-6" style={{ color: colors.textSecondary }}>
                {teachingDays.length ? teachingDays.join(', ') : 'Jours à choisir'} à {scheduleStartTime || '—'} · début le {scheduleStartDate || '—'}
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs" style={{ color: colors.textMuted }}>
                {paymentRequired ? 'Paiement unique' : 'Compte interne'}
              </p>
              <p className="mt-1 text-lg font-semibold" style={{ color: colors.text }}>
                {paymentRequired ? formatPrice(estimatedAmountCents, product?.currency) : 'Paiement non requis'}
              </p>
              {paymentRequired && product?.unit_amount_cents && trainingDays > 0 && (
                <p className="mt-1 text-xs" style={{ color: colors.textMuted }}>
                  {formatPrice(product.unit_amount_cents, product.currency)} × {trainingDays} journée{trainingDays > 1 ? 's' : ''}
                </p>
              )}
            </div>
          </div>
          <div className="mt-4 flex items-start gap-2 border-t pt-4 text-xs leading-5" style={{ color: colors.textMuted, borderColor: colors.border }}>
            <Icon name="verified_user" className="mt-0.5 text-sm" />
            <span>
              {paymentRequired
                ? 'Paiement sécurisé par Stripe. La préparation démarre uniquement après confirmation du paiement.'
                : (billing?.exemption_label || 'Ce compte est autorisé à lancer la préparation sans paiement.')}
            </span>
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
            {creating
              ? 'Préparation de la commande...'
              : billingLoading
                ? 'Chargement du tarif...'
                : paymentRequired
                  ? billing
                    ? `Payer ${formatPrice(estimatedAmountCents, product?.currency)} et lancer`
                    : 'Paiement temporairement indisponible'
                  : formationMode === 'existing' ? 'Réutiliser ce professeur' : 'Lancer la préparation'}
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
  onRefreshAudios,
}) {
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
        <div className="flex items-center justify-between gap-4 border-b border-slate-200 bg-white px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-600 text-white">
              <Icon name="audiotrack" className="text-xl" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-slate-900">Audios de la formation</h3>
              <p className="text-sm text-slate-500">Playlist diffusée pendant la journée de cours</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleOpenFillModal}
              className="flex min-h-10 items-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-violet-700"
            >
              <Icon name="drive_folder_upload" className="text-base" />
              <span>Remplir avec les audios</span>
            </button>
            <button
              onClick={onClose}
              aria-label="Fermer"
              className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 active:scale-[0.98]"
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
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-600">
                    <Icon name="drive_folder_upload" className="text-white text-xl" />
                  </div>
                  <h4 className="text-base font-bold text-slate-800">Remplir avec les audios</h4>
                </div>

                <p className="text-sm text-slate-500 mb-4">
                  Choisissez le dossier de cours à utiliser. Les 7 fichiers cours générés + les Q&A et pauses seront copiés dans la plateforme.
                </p>

                {loadingFolders ? (
                  <div className="flex justify-center py-4">
                    <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-violet-500" />
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
                      style={{ backgroundColor: filling || !selectedFillFolderId ? '#c4b5fd' : '#7c3aed' }}
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
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-violet-500" />
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
  const [courseMaterials, setCourseMaterials] = useState([])
  const [courseMaterialsLoading, setCourseMaterialsLoading] = useState(true)
  const [courseMaterialsError, setCourseMaterialsError] = useState('')
  const [courseMaterialsReloadKey, setCourseMaterialsReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setCourseMaterialsLoading(true)
    setCourseMaterialsError('')
    apiFetch(`/api/hr/platforms/${platform.id}/course-materials`)
      .then(async (response) => {
        const data = await response.json()
        if (!response.ok || !data.success) throw new Error(data.error || 'Chargement impossible')
        if (!cancelled) setCourseMaterials(Array.isArray(data.materials) ? data.materials : [])
      })
      .catch((error) => {
        if (!cancelled) {
          const unavailable = error instanceof TypeError || error?.message === 'Failed to fetch'
          setCourseMaterialsError(
            unavailable
              ? 'Le service des supports est momentanément indisponible.'
              : (error.message || 'Impossible de charger les supports de cours.'),
          )
        }
      })
      .finally(() => {
        if (!cancelled) setCourseMaterialsLoading(false)
    })
    return () => { cancelled = true }
  }, [platform.id, courseMaterialsReloadKey])

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
          <section className="mb-6 rounded-xl border p-4" style={{ borderColor: '#e2e8f0', backgroundColor: '#F8F7F5' }}>
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <h4 className="text-sm font-semibold" style={{ color: '#111418' }}>Supports de cours générés</h4>
                <p className="mt-1 text-xs leading-5" style={{ color: '#64748b' }}>
                  Un PDF sans balises techniques est créé avec les audios de chaque journée lors de la préparation H-24.
                </p>
              </div>
              {!courseMaterialsLoading && (
                <span className="flex-shrink-0 text-xs tabular-nums" style={{ color: '#64748b' }}>
                  {courseMaterials.length} document{courseMaterials.length > 1 ? 's' : ''}
                </span>
              )}
            </div>
            {courseMaterialsLoading ? (
              <p className="py-3 text-sm" style={{ color: '#64748b' }}>Chargement des supports…</p>
            ) : courseMaterialsError ? (
              <div
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-red-50 px-3 py-3"
                role="alert"
              >
                <div className="flex items-center gap-2 text-sm" style={{ color: '#991b1b' }}>
                  <Icon name="error_outline" className="text-lg" />
                  <span>{courseMaterialsError} Réessayez dans quelques instants.</span>
                </div>
                <button
                  type="button"
                  onClick={() => setCourseMaterialsReloadKey((key) => key + 1)}
                  className="flex min-h-9 items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-violet-700 transition-colors hover:bg-violet-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
                >
                  <Icon name="refresh" className="text-base" />
                  <span>Réessayer</span>
                </button>
              </div>
            ) : courseMaterials.length === 0 ? (
              <p className="py-3 text-sm" style={{ color: '#64748b' }}>Aucun support généré pour le moment.</p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {courseMaterials.map((material) => (
                  <a
                    key={material.session_id}
                    href={material.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-between gap-3 rounded-lg bg-white px-3 py-2.5 text-sm transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
                    style={{ border: '1px solid #e2e8f0', color: '#334155', textDecoration: 'none' }}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">Journée {material.session_index}</span>
                      <span className="block truncate text-xs" style={{ color: '#64748b' }}>
                        {material.scheduled_at ? new Date(material.scheduled_at).toLocaleDateString('fr-FR') : 'Date non renseignée'}
                      </span>
                    </span>
                    <Icon name="open_in_new" className="flex-shrink-0 text-base" style={{ color: '#64748b' }} />
                  </a>
                ))}
              </div>
            )}
          </section>
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
const newReminderRule = () => ({
  name: '',
  trigger_mode: 'relative_minutes',
  days_before: 1,
  minutes_before: 60,
  local_time: '18:00',
  subject_template: '',
  content_template: '',
  recipient_scope: 'all',
  recipient_ids: [],
  is_active: true,
})

function ReminderRulesPanel({ platformId, recipients, colors, darkMode }) {
  const [rules, setRules] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(newReminderRule)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const timeoutId = window.setTimeout(async () => {
      setLoading(true)
      setError('')
      try {
        const response = await apiFetch(`/api/hr/platforms/${platformId}/reminder-rules`)
        const data = await response.json().catch(() => ({}))
        if (!response.ok || !data.success) throw new Error(data.error || 'Impossible de charger les rappels')
        if (active) setRules(data.rules || [])
      } catch (loadError) {
        if (active) setError(loadError.message || 'Impossible de charger les rappels')
      } finally {
        if (active) setLoading(false)
      }
    }, 0)
    return () => {
      active = false
      window.clearTimeout(timeoutId)
    }
  }, [platformId])

  const editRule = (rule) => {
    setEditingId(rule.id)
    setForm({
      ...newReminderRule(),
      ...rule,
      local_time: rule.local_time || '18:00',
      recipient_ids: rule.recipient_ids || [],
    })
    setError('')
  }

  const resetForm = () => {
    setEditingId(null)
    setForm(newReminderRule())
    setError('')
  }

  const persistRule = async (rule, ruleId = null) => {
    const endpoint = ruleId
      ? `/api/hr/platforms/${platformId}/reminder-rules/${ruleId}`
      : `/api/hr/platforms/${platformId}/reminder-rules`
    const response = await apiFetch(endpoint, {
      method: ruleId ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rule),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok || !data.success) throw new Error(data.error || 'Impossible d’enregistrer le rappel')
    return data.rule
  }

  const saveRule = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const saved = await persistRule(form, editingId)
      setRules((current) => {
        const exists = current.some((rule) => rule.id === saved.id)
        return exists
          ? current.map((rule) => (rule.id === saved.id ? saved : rule))
          : [...current, saved]
      })
      resetForm()
    } catch (saveError) {
      setError(saveError.message || 'Impossible d’enregistrer le rappel')
    } finally {
      setSaving(false)
    }
  }

  const toggleRule = async (rule) => {
    setError('')
    try {
      const saved = await persistRule({ ...rule, is_active: !rule.is_active }, rule.id)
      setRules((current) => current.map((item) => (item.id === saved.id ? saved : item)))
    } catch (toggleError) {
      setError(toggleError.message || 'Impossible de modifier le rappel')
    }
  }

  const deleteRule = async (rule) => {
    if (rule.system_key || !window.confirm(`Supprimer le rappel « ${rule.name} » ?`)) return
    setError('')
    try {
      const response = await apiFetch(`/api/hr/platforms/${platformId}/reminder-rules/${rule.id}`, {
        method: 'DELETE',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) throw new Error(data.error || 'Impossible de supprimer le rappel')
      setRules((current) => current.filter((item) => item.id !== rule.id))
      if (editingId === rule.id) resetForm()
    } catch (deleteError) {
      setError(deleteError.message || 'Impossible de supprimer le rappel')
    }
  }

  const describeRule = (rule) => {
    if (rule.trigger_mode === 'local_day_time') {
      const days = Number(rule.days_before || 0)
      return `${days === 0 ? 'Le jour même' : `${days} jour${days > 1 ? 's' : ''} avant`} à ${rule.local_time}`
    }
    const minutes = Number(rule.minutes_before || 0)
    if (minutes > 0 && minutes % 1440 === 0) return `${minutes / 1440} jour${minutes > 1440 ? 's' : ''} avant`
    if (minutes >= 60 && minutes % 60 === 0) return `${minutes / 60} heure${minutes > 60 ? 's' : ''} avant`
    return `${minutes} minute${minutes > 1 ? 's' : ''} avant`
  }

  const inputStyle = {
    backgroundColor: colors.cardBg,
    border: `1px solid ${colors.border}`,
    color: colors.text,
  }

  return (
    <section className="mt-4 border-t pt-4" style={{ borderColor: colors.border }} aria-label="Rappels automatiques">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold" style={{ color: colors.text }}>Rappels automatiques</h4>
          <p className="mt-0.5 text-xs" style={{ color: colors.textMuted }}>Chaque élève reçoit son propre lien d’accès.</p>
        </div>
        {!editingId && (
          <button
            type="button"
            onClick={() => setEditingId('new')}
            className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-500"
            style={{ backgroundColor: colors.cardBg, color: darkMode ? '#c4b5fd' : '#7c3aed', border: `1px solid ${colors.border}` }}
          >
            <Icon name="add" className="text-sm" /> Créer un rappel
          </button>
        )}
      </div>

      {error && (
        <p className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700" role="alert">{error}</p>
      )}

      {loading ? (
        <div className="space-y-2" aria-label="Chargement des rappels">
          {[0, 1].map((item) => (
            <div key={item} className="h-12 animate-pulse rounded-lg" style={{ backgroundColor: colors.cardBg }} />
          ))}
        </div>
      ) : rules.length === 0 ? (
        <p className="py-3 text-xs" style={{ color: colors.textMuted }}>Ajoutez un rappel pour prévenir les élèves avant le cours.</p>
      ) : (
        <div className="space-y-2">
          {rules.map((rule) => (
            <div key={rule.id} className="flex items-center gap-2 rounded-lg px-2.5 py-2" style={inputStyle}>
              <input
                type="checkbox"
                checked={Boolean(rule.is_active)}
                onChange={() => toggleRule(rule)}
                aria-label={`${rule.is_active ? 'Désactiver' : 'Activer'} ${rule.name}`}
                className="h-4 w-4 accent-violet-600"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-semibold" style={{ color: colors.text }}>{rule.name}</p>
                <p className="truncate text-[11px]" style={{ color: colors.textMuted }}>{describeRule(rule)}</p>
              </div>
              <button type="button" onClick={() => editRule(rule)} className="rounded-md p-1" style={{ color: colors.textMuted }} title="Modifier le rappel">
                <Icon name="edit" className="text-sm" />
              </button>
              {!rule.system_key && (
                <button type="button" onClick={() => deleteRule(rule)} className="rounded-md p-1 hover:bg-rose-50" style={{ color: colors.textMuted }} title="Supprimer le rappel">
                  <Icon name="delete" className="text-sm" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {editingId && (
        <form className="mt-4 space-y-3" onSubmit={saveRule}>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium" style={{ color: colors.textSecondary }}>
              Nom du rappel
              <input required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-violet-500/30" style={inputStyle} />
            </label>
            <label className="text-xs font-medium" style={{ color: colors.textSecondary }}>
              Déclenchement
              <select value={form.trigger_mode} onChange={(e) => setForm({ ...form, trigger_mode: e.target.value })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-violet-500/30" style={inputStyle}>
                <option value="relative_minutes">Délai avant le cours</option>
                <option value="local_day_time">Jour et heure précis</option>
              </select>
            </label>
          </div>

          {form.trigger_mode === 'local_day_time' ? (
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs font-medium" style={{ color: colors.textSecondary }}>
                Jours avant
                <input type="number" min="0" max="365" required value={form.days_before} onChange={(e) => setForm({ ...form, days_before: Number(e.target.value) })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-violet-500/30" style={inputStyle} />
              </label>
              <label className="text-xs font-medium" style={{ color: colors.textSecondary }}>
                Heure d’envoi
                <input type="time" required max={Number(form.days_before) === 0 ? '08:59' : undefined} value={form.local_time} onChange={(e) => setForm({ ...form, local_time: e.target.value })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-violet-500/30" style={inputStyle} />
              </label>
            </div>
          ) : (
            <label className="block text-xs font-medium" style={{ color: colors.textSecondary }}>
              Minutes avant le cours
              <input type="number" min="1" max="525600" required value={form.minutes_before} onChange={(e) => setForm({ ...form, minutes_before: Number(e.target.value) })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-violet-500/30" style={inputStyle} />
            </label>
          )}

          <label className="block text-xs font-medium" style={{ color: colors.textSecondary }}>
            Objet de l’e-mail
            <input required maxLength={200} value={form.subject_template} onChange={(e) => setForm({ ...form, subject_template: e.target.value })} placeholder="Votre formation commence bientôt" className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none placeholder:text-slate-500 focus:ring-2 focus:ring-violet-500/30" style={inputStyle} />
          </label>
          <label className="block text-xs font-medium" style={{ color: colors.textSecondary }}>
            Message
            <textarea required maxLength={5000} rows={3} value={form.content_template} onChange={(e) => setForm({ ...form, content_template: e.target.value })} placeholder="Rendez-vous le {date} à {time}." className="mt-1 w-full resize-y rounded-lg px-2.5 py-2 outline-none placeholder:text-slate-500 focus:ring-2 focus:ring-violet-500/30" style={inputStyle} />
          </label>

          <label className="block text-xs font-medium" style={{ color: colors.textSecondary }}>
            Destinataires
            <select value={form.recipient_scope} onChange={(e) => setForm({ ...form, recipient_scope: e.target.value, recipient_ids: e.target.value === 'all' ? [] : form.recipient_ids })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-violet-500/30" style={inputStyle}>
              <option value="all">Tous les e-mails élèves</option>
              <option value="selected_explicit">Une sélection d’élèves</option>
            </select>
          </label>

          {form.recipient_scope === 'selected_explicit' && (
            <fieldset className="max-h-32 space-y-1 overflow-y-auto rounded-lg p-2" style={{ border: `1px solid ${colors.border}` }}>
              <legend className="px-1 text-xs font-medium" style={{ color: colors.textSecondary }}>Élèves sélectionnés</legend>
              {recipients.length === 0 ? (
                <p className="text-xs" style={{ color: colors.textMuted }}>Ajoutez d’abord des e-mails élèves.</p>
              ) : recipients.map((recipient) => (
                <label key={recipient.id} className="flex items-center gap-2 text-xs" style={{ color: colors.textSecondary }}>
                  <input
                    type="checkbox"
                    checked={form.recipient_ids.includes(recipient.id)}
                    onChange={(e) => setForm({
                      ...form,
                      recipient_ids: e.target.checked
                        ? [...form.recipient_ids, recipient.id]
                        : form.recipient_ids.filter((id) => id !== recipient.id),
                    })}
                    className="h-4 w-4 accent-violet-600"
                  />
                  <span className="truncate">{recipient.email}</span>
                </label>
              ))}
            </fieldset>
          )}

          <p className="text-[11px]" style={{ color: colors.textMuted }}>Variables disponibles : {'{date}'}, {'{time}'}, {'{session_code}'}, {'{class_url}'}.</p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={resetForm} className="rounded-lg px-3 py-2 text-xs font-semibold" style={{ color: colors.textSecondary }}>Annuler</button>
            <button type="submit" disabled={saving} className="rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">
              {saving ? 'Enregistrement…' : editingId === 'new' ? 'Créer le rappel' : 'Enregistrer le rappel'}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}

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
  onArchivePlatform, archiving = false, newlyCreated = false, retryingPreparation = false, onRetryPreparation,
  onBeforeFlip,
}) {
  const pdfInputId = `pdf-input-${p.id}`
  const [deleteHover, setDeleteHover] = useState(false)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const creationProgress = getHiddenPipelineProgress(p)
  const preparation = getTeacherPreparation(p)
  const isPreparing = preparation.status === 'preparing'
  const hasFailed = preparation.status === 'failed'
  const nextCourseSession = getNextCourseSession(p)
  const rosterStage = getTeacherRosterStage(p)
  const robotTheme = getRobotTheme(p.center_platform_number || p.id, p.teacher_color)
  const rosterMeta = {
    preparing: { label: hasFailed ? 'À vérifier' : 'En préparation', color: hasFailed ? '#dc2626' : '#b45309', background: hasFailed ? '#fef2f2' : '#fffbeb' },
    ready: { label: 'Prêt', color: '#047857', background: '#ecfdf5' },
    upcoming: { label: 'À venir', color: '#6d28d9', background: '#f5f3ff' },
    in_progress: { label: 'En cours', color: '#047857', background: '#ecfdf5' },
    completed: { label: 'Terminé', color: '#475569', background: '#f1f5f9' },
    archived: { label: 'Archivé', color: '#64748b', background: '#f1f5f9' },
  }[rosterStage]
  const faceStyle = {
    backgroundColor: colors.cardBg,
    border: `1px solid ${colors.border}`,
    boxShadow: '0 1px 3px rgba(0,0,0,.08), 0 1px 2px -1px rgba(0,0,0,.08)',
  }
  const actionItems = [
    { key: 'pdf', label: 'PDF', icon: 'picture_as_pdf', onClick: onOpenPdfModal },
    ...(p.active ? [
      { key: 'planning', label: 'Planning', icon: 'schedule', onClick: onOpenCourseTimeModal },
      { key: 'audios', label: 'Audios', icon: 'audiotrack', onClick: onExpand, active: expanded },
      { key: 'courses', label: 'Cours', icon: 'folder_special', onClick: onOpenCoursFolders },
      { key: 'students', label: 'Élèves', icon: 'group', onClick: onToggleStudentEmails, active: studentsExpanded, opensDialog: true },
      { key: 'attendance', label: 'Présence', icon: 'fact_check', onClick: onToggleAttendance, active: attendanceExpanded, opensDialog: true },
    ] : []),
  ]

  useEffect(() => {
    if (!detailsOpen) return undefined
    const previousOverflow = document.body.style.overflow
    const handleEscape = (event) => {
      if (event.key === 'Escape') setDetailsOpen(false)
    }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleEscape)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleEscape)
    }
  }, [detailsOpen])

  return (
    <>
      {/* Carte de roster : toute la surface ouvre la fiche, comme chez Delos. */}
      <div className={`w-full self-start ${newlyCreated ? 'teacher-card-enter' : ''}`}>
        <div
          role="button"
          tabIndex={0}
          aria-label={`Ouvrir le professeur ${p.teacher_name || p.name || 'IA'}`}
          onClick={() => {
            onBeforeFlip?.()
            setDetailsOpen(true)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onBeforeFlip?.()
              setDetailsOpen(true)
            }
          }}
          className="group relative flex min-h-[332px] cursor-pointer flex-col gap-2 overflow-hidden rounded-2xl p-3 text-left transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/50"
          style={faceStyle}
        >
          <div
            className="relative h-[218px] w-full shrink-0 overflow-hidden rounded-xl"
            style={{ backgroundColor: `${robotTheme.glow}12` }}
            aria-hidden="true"
          >
            <img
              src={robotTheme.src}
              alt=""
              draggable={false}
              className="h-full w-full select-none object-contain px-2 pt-2 transition-transform duration-200 ease-out group-hover:scale-[1.025] motion-reduce:transition-none"
            />
          </div>

          <div>
            <h3 className="truncate text-sm font-semibold leading-tight tracking-[-0.025em]" style={{ color: colors.text }}>
              {p.teacher_name || p.name || 'Professeur IA'}
            </h3>
            <p className="mt-1 truncate text-xs font-medium" style={{ color: '#6C63FF' }}>
              Professeur du {p.source_tp_name || p.name || 'parcours'}
            </p>
          </div>

          <ul className="mt-1 space-y-1 text-[11px] leading-[1.45]" style={{ color: colors.textSecondary }}>
            <li className="flex items-start gap-2">
              <span className="mt-[5px] h-1 w-1 flex-shrink-0 rounded-full" style={{ backgroundColor: rosterMeta.color }} />
              <span>{rosterMeta.label}{isPreparing ? ` · ${creationProgress}%` : ''}</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-[5px] h-1 w-1 flex-shrink-0 rounded-full" style={{ backgroundColor: '#6C63FF' }} />
              <span className="line-clamp-2">
                {nextCourseSession ? `Prochaine séance ${formatScheduleDateTime(nextCourseSession.scheduled_at)}` : 'Aucune séance programmée'}
              </span>
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-[5px] h-1 w-1 flex-shrink-0 rounded-full" style={{ backgroundColor: '#6C63FF' }} />
              <span>{Number(p.remaining_session_count || 0)} séance(s) restante(s)</span>
            </li>
          </ul>

          {hasFailed && preparation.can_retry && onRetryPreparation && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onRetryPreparation()
              }}
              disabled={retryingPreparation}
              className="w-full rounded-full border border-[#D8D4CE] py-2 text-xs font-semibold disabled:opacity-50"
              style={{ color: '#991b1b' }}
            >
              {retryingPreparation ? 'Reprise en cours…' : 'Reprendre la préparation'}
            </button>
          )}

          <span
            className="mt-auto flex w-full items-center justify-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition-opacity group-hover:opacity-85"
            style={{ backgroundColor: '#121212', color: '#F4F0E7' }}
          >
            Gérer
            <Icon name="arrow_forward" className="text-sm" />
          </span>
        </div>
      </div>

      {detailsOpen && createPortal(
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 p-4 backdrop-blur-[3px]"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDetailsOpen(false)
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby={`teacher-details-${p.id}`}
            className="relative flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl sm:h-[86vh] sm:max-h-[760px] sm:flex-row"
            style={{ border: `1px solid ${colors.border}` }}
          >
            <aside
              className="relative min-h-[300px] shrink-0 overflow-hidden sm:min-h-0 sm:w-1/2"
              style={{ backgroundColor: colors.innerBg, borderRight: `1px solid ${colors.border}` }}
            >
              <span
                className="absolute left-5 top-5 z-10 inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em]"
                style={{ color: rosterMeta.color, backgroundColor: rosterMeta.background }}
              >
                {rosterMeta.label}
              </span>
              <div className="absolute inset-0" style={{ backgroundColor: `${robotTheme.glow}12` }} aria-hidden="true">
                <span
                  className="absolute bottom-[12%] left-1/2 h-8 w-[58%] -translate-x-1/2 rounded-full opacity-20 blur-xl"
                  style={{ backgroundColor: robotTheme.glow }}
                />
                <img
                  src={robotTheme.src}
                  alt=""
                  draggable={false}
                  className="teacher-robot-float h-full w-full select-none object-contain px-7 py-10 sm:px-10 sm:py-14"
                />
              </div>
            </aside>

            <div className="relative min-h-0 flex-1 overflow-y-auto" style={{ backgroundColor: colors.cardBg }}>
              <button
                type="button"
                onClick={() => setDetailsOpen(false)}
                aria-label="Fermer la fiche du professeur"
                className="absolute right-2 top-2 z-40 flex h-7 w-7 items-center justify-center rounded-lg transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30"
                style={{ color: colors.textMuted }}
              >
                <Icon name="close" className="text-base" />
              </button>

              <div className="relative overflow-hidden">
      {/* L’archivage retire la promo de l’espace actif sans effacer le module
          durable ni ses ressources Azure. La suppression définitive reste un
          outil superadmin de dernier recours. */}
      {onArchivePlatform ? (
        <button
          type="button"
          aria-label={`Archiver le professeur ${p.teacher_name || p.name}`}
          title="Archiver sans supprimer les cours ni les audios"
          onClick={(e) => {
            e.stopPropagation()
            onArchivePlatform()
          }}
          disabled={archiving}
          className="absolute right-12 top-3 z-30 flex h-9 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/40 disabled:cursor-wait disabled:opacity-60"
          style={{
            backgroundColor: darkMode ? 'rgba(15, 23, 42, 0.7)' : 'rgba(255, 255, 255, 0.9)',
            color: colors.textSecondary,
            border: `1px solid ${colors.border}`,
            backdropFilter: 'blur(4px)',
          }}
        >
          <Icon name={archiving ? 'hourglass_top' : 'archive'} className="text-base" />
          <span>{archiving ? 'Archivage…' : 'Archiver'}</span>
        </button>
      ) : onDeletePlatform ? (
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
          className="absolute right-12 top-3 z-30 flex h-8 w-8 items-center justify-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40"
          style={{
            backgroundColor: deleteHover ? (darkMode ? 'rgba(220, 38, 38, 0.18)' : '#fee2e2') : (darkMode ? 'rgba(15, 23, 42, 0.55)' : 'rgba(255, 255, 255, 0.85)'),
            color: deleteHover ? '#dc2626' : colors.textMuted,
            border: `1px solid ${deleteHover ? 'rgba(220, 38, 38, 0.3)' : (darkMode ? 'rgba(255,255,255,0.08)' : 'rgba(15, 23, 42, 0.06)')}`,
            backdropFilter: 'blur(4px)',
          }}
        >
          <Icon name="delete_outline" className="text-base" />
        </button>
      ) : null}

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
      {p.active && isPreparing && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center rounded-2xl"
          style={{ backgroundColor: darkMode ? 'rgba(15, 23, 42, 0.92)' : 'rgba(248, 250, 252, 0.98)', backdropFilter: 'blur(4px)' }}
        >
          <div className="text-center px-6">
            <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-[3px]"
              style={{ borderColor: darkMode ? '#334155' : '#e2e8f0', borderTopColor: '#8B5CF6' }} />
            <p className="text-sm font-semibold mb-1" style={{ color: colors.text }}>
              {preparation.stage || 'Préparation du professeur'}
            </p>
            <p className="text-xs mb-4" style={{ color: colors.textMuted }}>
              Les étapes techniques sont exécutées automatiquement. Les étapes déjà terminées sont conservées après un redémarrage.
            </p>
          </div>
        </div>
      )}

      {/* Error overlay : clone ou pipeline échoué */}
      {p.active && hasFailed && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center rounded-2xl"
          style={{ backgroundColor: darkMode ? 'rgba(15, 23, 42, 0.92)' : 'rgba(248, 250, 252, 0.98)', backdropFilter: 'blur(4px)' }}
        >
          <div className="text-center px-6">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full" style={{ backgroundColor: '#fee2e2' }}>
              <Icon name="error" className="text-2xl" style={{ color: '#dc2626' }} />
            </div>
            <p className="mb-1 text-sm font-semibold" style={{ color: colors.text }}>Préparation interrompue</p>
            <p className="text-xs leading-5" style={{ color: colors.textMuted }}>
              Les étapes terminées sont conservées. Vous pouvez reprendre sans recréer le professeur.
            </p>
            {preparation.can_retry && onRetryPreparation && (
              <button
                type="button"
                onClick={onRetryPreparation}
                disabled={retryingPreparation}
                className="mt-4 inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-semibold text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40 disabled:cursor-wait disabled:opacity-60"
                style={{ backgroundColor: '#8B5CF6' }}
              >
                <Icon name={retryingPreparation ? 'hourglass_top' : 'refresh'} className="text-[16px]" aria-hidden="true" />
                {retryingPreparation ? 'Reprise en cours…' : 'Reprendre la préparation'}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="p-6">
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
              P{p.center_platform_number || p.id}
            </span>
            <h2 id={`teacher-details-${p.id}`} className="truncate text-lg font-semibold leading-tight tracking-tight" style={{ color: colors.text }}>
              {p.teacher_name || p.name || 'Professeur IA'}
            </h2>
          </div>
          <p className="text-xs font-medium" style={{ color: '#6C63FF' }}>
            Professeur du {p.source_tp_name || p.name || 'parcours'}
          </p>
          {p.active && p.audio_count != null && (
            <p
              className="text-xs"
              style={{ color: colors.textMuted, fontVariantNumeric: 'tabular-nums' }}
            >
              {(p.audio_count || 0) > 0 ? (
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

        {/* Barre d'outils de la formation. Les commandes partagent un même
            cadre afin de former une seule zone fonctionnelle, et non six
            boutons flottants sans hiérarchie. */}
        <div
          className="mb-4 grid grid-cols-2 overflow-hidden rounded-xl"
          style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.cardBg }}
        >
          {actionItems.map((action, index) => {
            const isActive = Boolean(action.active)
            return (
              <button
                key={action.key}
                type="button"
                onClick={action.onClick}
                aria-haspopup={action.opensDialog ? 'dialog' : undefined}
                className="flex min-h-12 items-center gap-2.5 px-3 py-2.5 text-left text-sm font-medium tracking-tight transition-colors hover:bg-black/5 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-violet-500/50 dark:hover:bg-white/5"
                style={{
                  backgroundColor: isActive ? 'rgba(139, 92, 246, 0.10)' : 'transparent',
                  borderTop: index >= 2 ? `1px solid ${colors.border}` : 'none',
                  borderLeft: index % 2 === 1 ? `1px solid ${colors.border}` : 'none',
                  color: isActive ? (darkMode ? '#c4b5fd' : '#7c3aed') : colors.textSecondary,
                }}
              >
                <Icon
                  name={action.icon}
                  className="text-lg"
                  style={{ color: isActive ? (darkMode ? '#c4b5fd' : '#7c3aed') : colors.textMuted }}
                />
                <span className="min-w-0 flex-1 truncate">{action.label}</span>
                {action.opensDialog && (
                  <Icon
                    name="chevron_right"
                    className="text-base"
                    style={{ color: colors.textMuted }}
                  />
                )}
              </button>
            )
          })}
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
          <CardToolModal
            dialogId={`students-modal-${p.id}`}
            title="Élèves et rappels"
            subtitle={`${p.teacher_name || p.name} · Plateforme ${p.center_platform_number || p.id}`}
            icon="group"
            onClose={onToggleStudentEmails}
            colors={colors}
            darkMode={darkMode}
          >
          <div className="p-1 sm:p-2">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h4 className="text-sm font-semibold" style={{ color: colors.text }}>Élèves et invitations</h4>
                <p className="mt-1 text-xs leading-5" style={{ color: colors.textMuted }}>
                  Ajoutez uniquement les adresses qui recevront le lien d’accès et les rappels.
                </p>
              </div>
              <span
                className="flex-shrink-0 rounded-full px-2 py-1 text-[11px] font-semibold tabular-nums"
                style={{ backgroundColor: colors.cardBg, color: colors.textSecondary, border: `1px solid ${colors.border}` }}
              >
                {studentEmails.length}
              </span>
            </div>

            <label className="block text-xs font-semibold" style={{ color: colors.textSecondary }}>
              Adresses e-mail
              <textarea
                value={studentEmailDraft}
                onChange={(e) => onStudentEmailDraftChange(e.target.value)}
                rows={2}
                placeholder="prenom@exemple.com, autre@exemple.com"
                className="mt-2 w-full resize-none rounded-lg px-3 py-2.5 text-sm outline-none transition-shadow placeholder:text-slate-500 focus:ring-2 focus:ring-violet-500/30"
                style={{
                  backgroundColor: colors.cardBg,
                  border: `1px solid ${colors.border}`,
                  color: colors.text,
                }}
              />
            </label>
            <div className="mb-4 mt-2 flex flex-wrap items-center justify-between gap-3">
              <p className="text-[11px] leading-4" style={{ color: colors.textMuted }}>
                1 000 adresses maximum par ajout.
              </p>
              <button
                type="button"
                onClick={onAddStudentEmails}
                disabled={!studentEmailDraft.trim() || studentEmailsSaving}
                className="inline-flex min-h-10 items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40 disabled:cursor-not-allowed disabled:opacity-50"
                style={{ backgroundColor: '#8B5CF6', color: 'white' }}
              >
                {studentEmailsSaving ? (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                ) : (
                  <Icon name="person_add" className="text-sm" />
                )}
                Ajouter les adresses
              </button>
            </div>

            {studentEmailsLoading ? (
              <div className="flex items-center justify-center py-4">
                <div className="h-5 w-5 animate-spin rounded-full border-2" style={{ borderColor: colors.border, borderTopColor: '#8B5CF6' }} />
              </div>
            ) : studentEmails.length === 0 ? (
              <p className="py-2 text-xs" style={{ color: colors.textMuted }}>
                Aucune adresse ajoutée pour le moment.
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
            <ReminderRulesPanel
              platformId={p.id}
              recipients={studentEmails}
              colors={colors}
              darkMode={darkMode}
            />
          </div>
          </CardToolModal>
        )}

        {attendanceExpanded && p.active && (
          <CardToolModal
            dialogId={`attendance-modal-${p.id}`}
            title="Présence et relevés"
            subtitle={`${p.teacher_name || p.name} · Plateforme ${p.center_platform_number || p.id}`}
            icon="fact_check"
            onClose={onToggleAttendance}
            colors={colors}
            darkMode={darkMode}
            widthClass="max-w-4xl"
          >
            <AttendanceCardPanel
              colors={colors}
              darkMode={darkMode}
              courseDate={attendanceDate}
              data={attendanceData}
              loading={attendanceLoading}
              error={attendanceError}
              onCourseDateChange={onAttendanceDateChange}
              onRefresh={onRefreshAttendance}
              onExport={onExportAttendance}
            />
          </CardToolModal>
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

              </div>
            </div>
            </div>
          </section>
        </div>,
        document.body,
      )}
    </>
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

function formatPostponementDay(value) {
  if (!value) return 'la nouvelle date'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'la nouvelle date'
  return date.toLocaleDateString('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
}

function formatPostponementButtonDate(value) {
  if (!value) return 'Choisir une date'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Choisir une date'
  return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })
}

function toLocalDateTimeInput(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (number) => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function AudioStatusBadge({ status, darkMode = false }) {
  const meta = getAudioStatusMeta(status)
  return (
    <span
      className="inline-flex flex-shrink-0 items-center rounded-full px-2 py-1 text-[10px] font-semibold"
      style={{
        color: darkMode ? '#f8fafc' : meta.color,
        backgroundColor: darkMode ? 'rgba(148, 163, 184, 0.16)' : meta.background,
      }}
    >
      {meta.label}
    </span>
  )
}

function PostponeSessionDialog({ session, onClose, onPreview, onConfirm }) {
  const [mode, setMode] = useState('next_occurrence')
  const [customDate, setCustomDate] = useState('')
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(true)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const idempotencyKey = useRef(
    globalThis.crypto?.randomUUID?.() || `postpone-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  )

  useEffect(() => {
    const handleEscape = (event) => {
      if (event.key === 'Escape' && !confirming) onClose()
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [confirming, onClose])

  useEffect(() => {
    if (success) return undefined
    if (mode === 'specific_date' && !customDate) {
      setPreview(null)
      setPreviewLoading(false)
      return undefined
    }
    let active = true
    const timer = window.setTimeout(async () => {
      setPreviewLoading(true)
      setError('')
      try {
        const result = await onPreview(session.id, {
          mode,
          scheduled_at: mode === 'specific_date' ? customDate : undefined,
        })
        if (active) setPreview(result)
      } catch (requestError) {
        if (active) {
          setPreview(null)
          setError(requestError.message || 'Impossible de calculer l’impact de ce report')
        }
      } finally {
        if (active) setPreviewLoading(false)
      }
    }, mode === 'specific_date' ? 250 : 0)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [customDate, mode, onPreview, session.id, success])

  const confirmPostponement = async () => {
    if (!preview || confirming) return
    setConfirming(true)
    setError('')
    try {
      await onConfirm(
        session.id,
        {
          mode,
          scheduled_at: mode === 'specific_date' ? customDate : undefined,
          reason: reason.trim() || undefined,
        },
        idempotencyKey.current,
      )
      setSuccess(true)
      window.setTimeout(onClose, 900)
    } catch (requestError) {
      setError(requestError.message || 'Le report n’a pas pu être enregistré')
    } finally {
      setConfirming(false)
    }
  }

  const audioCopy = {
    ready: 'L’audio déjà prêt sera conservé pour cette nouvelle date.',
    preparing: 'La préparation audio continue et restera liée à ce cours.',
    scheduled: 'L’audio sera préparé automatiquement 24 h avant la nouvelle date.',
  }

  return (
    <div
      className="postpone-dialog-backdrop fixed inset-0 z-[70] flex items-end justify-center sm:items-center sm:p-5"
      role="presentation"
      onClick={(event) => event.stopPropagation()}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !confirming) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="postpone-session-title"
        className="postpone-dialog-sheet w-full overflow-hidden rounded-t-2xl bg-white sm:max-w-[620px] sm:rounded-2xl"
      >
        {success ? (
          <div className="flex min-h-[330px] flex-col items-center justify-center px-8 py-12 text-center" aria-live="polite">
            <span className="mb-5 flex h-14 w-14 items-center justify-center rounded-full" style={{ backgroundColor: '#ecfdf5', color: '#059669' }}>
              <Icon name="check" className="text-3xl" />
            </span>
            <h3 className="text-lg font-semibold" style={{ color: '#0f172a' }}>Le cours {session.session_index} est reporté</h3>
            <p className="mt-2 max-w-sm text-sm leading-6" style={{ color: '#64748b' }}>
              Aucun cours n’a été perdu. Le planning et les rappels ont été mis à jour.
            </p>
          </div>
        ) : (
          <>
            <header className="flex items-start justify-between gap-4 border-b px-5 py-5 sm:px-6" style={{ borderColor: '#e2e8f0' }}>
              <div className="flex min-w-0 items-start gap-3">
                <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl" style={{ backgroundColor: '#f3f0ff', color: '#7c3aed' }}>
                  <Icon name="event_repeat" className="text-xl" />
                </span>
                <div>
                  <h3 id="postpone-session-title" className="text-base font-semibold" style={{ color: '#0f172a' }}>
                    Reporter le cours {session.session_index}
                  </h3>
                  <p className="mt-1 text-sm" style={{ color: '#64748b' }}>
                    Prévu {formatPostponementDay(session.scheduled_at)} à {new Date(session.scheduled_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                disabled={confirming}
                aria-label="Fermer sans reporter"
                className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-slate-100 disabled:opacity-50"
                style={{ color: '#64748b' }}
              >
                <Icon name="close" className="text-xl" />
              </button>
            </header>

            <div className="max-h-[68vh] space-y-5 overflow-y-auto px-5 py-5 sm:px-6">
              <fieldset>
                <legend className="mb-3 text-sm font-semibold" style={{ color: '#334155' }}>Quand souhaitez-vous le reporter ?</legend>
                <div className="space-y-2.5">
                  <button
                    type="button"
                    autoFocus
                    onClick={() => setMode('next_occurrence')}
                    className="flex min-h-[72px] w-full items-start gap-3 rounded-xl border p-4 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-violet-200"
                    style={{ borderColor: mode === 'next_occurrence' ? '#8b5cf6' : '#e2e8f0', backgroundColor: mode === 'next_occurrence' ? '#faf8ff' : '#fff' }}
                  >
                    <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border" style={{ borderColor: mode === 'next_occurrence' ? '#8b5cf6' : '#cbd5e1' }}>
                      {mode === 'next_occurrence' && <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: '#8b5cf6' }} />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold" style={{ color: '#0f172a' }}>Au prochain créneau prévu</span>
                        <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide" style={{ color: '#6d28d9', backgroundColor: '#ede9fe' }}>Recommandé</span>
                      </span>
                      <span className="mt-1 block text-xs leading-5" style={{ color: '#64748b' }}>Le cours suivant prend sa place et toute la suite se décale naturellement.</span>
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setMode('specific_date')}
                    className="flex min-h-[68px] w-full items-start gap-3 rounded-xl border p-4 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-violet-200"
                    style={{ borderColor: mode === 'specific_date' ? '#8b5cf6' : '#e2e8f0', backgroundColor: mode === 'specific_date' ? '#faf8ff' : '#fff' }}
                  >
                    <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border" style={{ borderColor: mode === 'specific_date' ? '#8b5cf6' : '#cbd5e1' }}>
                      {mode === 'specific_date' && <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: '#8b5cf6' }} />}
                    </span>
                    <span>
                      <span className="text-sm font-semibold" style={{ color: '#0f172a' }}>Choisir une nouvelle date</span>
                      <span className="mt-1 block text-xs leading-5" style={{ color: '#64748b' }}>Les cours suivants seront décalés si nécessaire.</span>
                    </span>
                  </button>
                </div>
              </fieldset>

              {mode === 'specific_date' && (
                <div>
                  <label htmlFor="postpone-specific-date" className="mb-1.5 block text-xs font-semibold" style={{ color: '#334155' }}>Nouvelle date</label>
                  <input
                    id="postpone-specific-date"
                    type="date"
                    value={customDate.slice(0, 10)}
                    min={toLocalDateTimeInput(new Date(new Date(session.scheduled_at).getTime() + 60000)).slice(0, 10)}
                    onChange={(event) => setCustomDate(event.target.value ? `${event.target.value}T09:00` : '')}
                    className="h-11 w-full rounded-lg border px-3 text-sm outline-none focus:ring-2"
                    style={{ borderColor: '#cbd5e1', color: '#0f172a', '--tw-ring-color': '#ddd6fe' }}
                  />
                  <p className="mt-1.5 text-xs" style={{ color: '#64748b' }}>Le cours commencera à 09:00.</p>
                </div>
              )}

              <div className="rounded-xl border p-4" style={{ borderColor: '#ddd6fe', backgroundColor: '#faf8ff' }} aria-live="polite">
                {previewLoading ? (
                  <div className="flex items-center gap-3 text-sm" style={{ color: '#64748b' }}>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-violet-200 border-t-violet-600" />
                    Calcul de l’impact sur le planning…
                  </div>
                ) : preview ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: '#94a3b8' }}>Date actuelle</p>
                        <p className="mt-1 text-sm font-semibold capitalize" style={{ color: '#475569' }}>{formatPostponementDay(preview.previous_scheduled_at)}</p>
                      </div>
                      <Icon name="arrow_forward" className="text-lg" style={{ color: '#8b5cf6' }} />
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: '#7c3aed' }}>Nouvelle date</p>
                        <p className="mt-1 text-sm font-semibold capitalize" style={{ color: '#5b21b6' }}>{formatPostponementDay(preview.new_scheduled_at)}</p>
                      </div>
                    </div>
                    <div className="flex items-start gap-2 border-t pt-3 text-xs leading-5" style={{ borderColor: '#e9e2ff', color: '#475569' }}>
                      <Icon name="verified" className="mt-0.5 text-base" style={{ color: '#7c3aed' }} />
                      <p><strong style={{ color: '#334155' }}>Aucun cours ne sera perdu.</strong> {preview.affected_session_count > 1 ? `Les ${preview.affected_session_count - 1} cours suivants seront décalés d’un créneau.` : 'Seule cette date sera déplacée.'}</p>
                    </div>
                    <div className="flex items-start gap-2 text-xs leading-5" style={{ color: '#475569' }}>
                      <Icon name="graphic_eq" className="mt-0.5 text-base" style={{ color: '#7c3aed' }} />
                      <p>{audioCopy[preview.audio_preservation]}</p>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm" style={{ color: '#64748b' }}>Choisissez une date pour afficher son impact.</p>
                )}
              </div>

              {preview?.warning_imminent && (
                <div className="flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-xs leading-5" style={{ color: '#92400e', backgroundColor: '#fffbeb', borderColor: '#fde68a' }}>
                  <Icon name="schedule" className="mt-0.5 text-base" />
                  <p>Cette séance est proche. Le report reste possible et l’audio déjà préparé sera conservé.</p>
                </div>
              )}

              <div>
                <label htmlFor="postpone-reason" className="mb-1.5 block text-xs font-semibold" style={{ color: '#334155' }}>Motif du report <span className="font-normal" style={{ color: '#94a3b8' }}>(facultatif)</span></label>
                <input
                  id="postpone-reason"
                  type="text"
                  maxLength={500}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Ex. indisponibilité du formateur"
                  className="h-11 w-full rounded-lg border px-3 text-sm outline-none focus:ring-2"
                  style={{ borderColor: '#cbd5e1', color: '#0f172a', '--tw-ring-color': '#ddd6fe' }}
                />
              </div>

              {error && (
                <div className="flex items-start gap-2 rounded-lg px-3 py-2.5 text-xs" role="alert" style={{ color: '#991b1b', backgroundColor: '#fef2f2' }}>
                  <Icon name="error_outline" className="text-base" />
                  <span>{error}</span>
                </div>
              )}
            </div>

            <footer className="flex flex-col-reverse gap-2.5 border-t px-5 py-4 sm:flex-row sm:justify-end sm:px-6" style={{ borderColor: '#e2e8f0', backgroundColor: '#fff' }}>
              <button
                type="button"
                onClick={onClose}
                disabled={confirming}
                className="min-h-11 rounded-lg border px-4 text-sm font-semibold transition-colors hover:bg-slate-50 disabled:opacity-50"
                style={{ color: '#475569', borderColor: '#cbd5e1' }}
              >
                Garder la date actuelle
              </button>
              <button
                type="button"
                onClick={confirmPostponement}
                disabled={!preview || previewLoading || confirming}
                className="flex min-h-11 items-center justify-center gap-2 rounded-lg px-5 text-sm font-semibold text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
                style={{ backgroundColor: '#8b5cf6' }}
              >
                {confirming && <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />}
                {confirming ? 'Mise à jour…' : preview ? `Reporter au ${formatPostponementButtonDate(preview.new_scheduled_at)}` : 'Choisir une date'}
              </button>
            </footer>
          </>
        )}
      </div>
    </div>
  )
}

// ─── Course Time Modal ───────────────────────────────────────────────────────
function CourseTimeModal({ onClose, onSubmit, initialDate, schedule, onRetryAudio, onPreviewPostponement, onPostponeSession }) {
  const today = new Date().toISOString().split('T')[0]
  const hasSchedule = !!schedule
  const [date, setDate] = useState(initialDate || today)
  const [heure] = useState('09:00')
  const [selectedWeekdays, setSelectedWeekdays] = useState(
    (schedule?.weekdays || [])
      .map((day) => Number(day))
      .filter((day) => Number.isInteger(day) && day >= 0 && day <= 6)
      .sort((a, b) => a - b)
  )
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [busySessionId, setBusySessionId] = useState(null)
  const [actionError, setActionError] = useState('')
  const [sessionToPostpone, setSessionToPostpone] = useState(null)
  const expectedWeekdayCount = Number(schedule?.weekly_course_count || selectedWeekdays.length || 0)
  const weekdaySelectionError = hasSchedule && !scheduleSelectionIsValid({ selectedWeekdays, expectedWeekdayCount })
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

  const runSessionAction = async (session) => {
    setBusySessionId(session.id)
    setActionError('')
    try {
      await onRetryAudio(session.id)
    } catch (error) {
      setActionError(error.message || 'Action impossible')
    } finally {
      setBusySessionId(null)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="course-planning-title"
        className="overflow-hidden rounded-2xl bg-white"
        style={{ width: '100%', maxWidth: '760px', maxHeight: '92vh', boxShadow: '0 8px 24px rgba(15, 23, 42, 0.18)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b px-6 py-4" style={{ borderColor: '#e2e8f0', backgroundColor: '#ffffff' }}>
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ backgroundColor: '#ede9fe', color: '#7c3aed' }}>
              <Icon name="calendar_month" className="text-xl" />
            </span>
            <div>
              <h3 id="course-planning-title" className="text-base font-semibold" style={{ color: '#0f172a' }}>Planning de la formation</h3>
              <p className="text-xs" style={{ color: '#64748b' }}>Fuseau horaire Europe/Paris</p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Fermer le planning"
            className="rounded-lg p-2 transition-colors hover:bg-slate-100"
            style={{ color: '#64748b' }}
          >
            <Icon name="close" className="text-2xl" />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto p-6" style={{ maxHeight: 'calc(92vh - 74px)' }}>
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
                    Les séances prévues dans les 72 h restent inchangées. Le nouveau planning s’applique automatiquement aux suivantes.
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
                <div className="flex h-11 items-center justify-between rounded-lg border px-3 text-sm" style={{ borderColor: '#e2e8f0', color: '#0f172a', backgroundColor: '#F8F7F5' }}>
                  <span className="font-semibold">09:00</span>
                  <span className="text-xs" style={{ color: '#64748b' }}>Fixe jusqu’à 18:30</span>
                </div>
              </div>

              {result && !result.success && (
                <p className="text-xs rounded-lg px-3 py-2" style={{ color: '#dc2626', backgroundColor: '#fee2e2' }}>
                  {result.message || result.error || 'Une erreur est survenue'}
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
                  style={{ backgroundColor: '#8B5CF6', opacity: (loading || (!hasSchedule && !date) || !heure || !!weekdaySelectionError) ? 0.6 : 1 }}
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

          {hasSchedule && Array.isArray(schedule.sessions) && (
            <section className="mt-6 border-t pt-5" style={{ borderColor: '#e2e8f0' }}>
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h4 className="text-sm font-semibold" style={{ color: '#0f172a' }}>Journées programmées</h4>
                  <p className="mt-0.5 text-xs" style={{ color: '#64748b' }}>
                    L’audio démarre 24 h avant chaque séance.
                  </p>
                </div>
                <span className="text-xs font-medium" style={{ color: '#64748b' }}>
                  {schedule.sessions.length} séance{schedule.sessions.length > 1 ? 's' : ''}
                </span>
              </div>

              {actionError && (
                <p className="mb-3 rounded-lg px-3 py-2 text-xs" style={{ color: '#b91c1c', backgroundColor: '#fee2e2' }}>
                  {actionError}
                </p>
              )}

              <div className="divide-y overflow-hidden rounded-xl" style={{ border: '1px solid #e2e8f0', borderColor: '#e2e8f0' }}>
                {schedule.sessions.map((session) => (
                  <div key={session.id} className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ borderColor: '#e2e8f0' }}>
                    <span
                      className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-xs font-semibold"
                      style={{ backgroundColor: '#f1f5f9', color: '#475569' }}
                    >
                      J{session.session_index}
                    </span>
                    <div className="min-w-[180px] flex-1">
                      <p className="text-xs font-semibold" style={{ color: '#0f172a' }}>
                        {formatScheduleDateTime(session.scheduled_at)}
                      </p>
                      <p className="mt-0.5 text-[11px]" style={{ color: '#64748b' }}>
                        {session.status === 'completed'
                          ? 'Cours terminé'
                          : session.was_postponed
                          ? `Reportée depuis le ${formatScheduleDateTime(session.postponed_from)}`
                          : session.is_locked
                            ? 'Séance proche : report exceptionnel possible'
                            : `Modifiable jusqu’au ${formatScheduleDateTime(session.change_cutoff_at)}`}
                      </p>
                    </div>
                    <AudioStatusBadge status={session.audio_status} />
                    {session.can_retry_audio && (
                      <button
                        type="button"
                        disabled={busySessionId === session.id}
                        onClick={() => runSessionAction(session)}
                        className="rounded-lg px-3 py-2 text-xs font-semibold text-white transition-opacity disabled:opacity-50"
                        style={{ backgroundColor: '#8B5CF6' }}
                      >
                        {busySessionId === session.id ? 'Relance…' : 'Relancer l’audio'}
                      </button>
                    )}
                    {session.can_postpone && (
                      <button
                        type="button"
                        disabled={busySessionId === session.id}
                        onClick={() => setSessionToPostpone(session)}
                        className="min-h-10 rounded-lg px-3 py-2 text-xs font-semibold transition-colors disabled:opacity-50"
                        style={{ color: '#6d28d9', backgroundColor: '#f5f3ff' }}
                      >
                        Reporter cette séance
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
      {sessionToPostpone && (
        <PostponeSessionDialog
          session={sessionToPostpone}
          onClose={() => setSessionToPostpone(null)}
          onPreview={onPreviewPostponement}
          onConfirm={onPostponeSession}
        />
      )}
    </div>
  )
}
