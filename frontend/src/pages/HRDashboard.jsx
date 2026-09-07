import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { createPortal } from 'react-dom'
import {
  ArrowUp,
  AudioWaveform,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  ClipboardCheck,
  Copy,
  CreditCard,
  ExternalLink,
  FileCheck2,
  FolderOpen,
  Globe2,
  Info,
  KeyRound,
  LayoutTemplate,
  LogIn,
  LogOut,
  Mail,
  PanelLeft,
  PenLine,
  ReceiptText,
  RotateCcw,
  Settings,
  ShieldCheck,
  Trash2,
  UserPlus,
  UsersRound,
  X,
} from 'lucide-react'
import { apiFetch } from '../api'
import { clearSupabaseSession, getSupabaseClient } from '../supabaseClient'
import AppLoader from '../components/AppLoader.jsx'
import CoursFoldersModal from '../components/CoursFolders'
import TeacherOrderReviewInbox from '../components/TeacherOrderReviewInbox.jsx'
import DayScheduleTemplates from './DayScheduleTemplates.jsx'
import AIVoicesView from './AIVoicesView.jsx'
import FormationSchedulePlanner from './FormationSchedulePlanner.jsx'
import { SlidePreviewFrame } from '../components/slides/PipelineSlidePreview.jsx'
import './CreatePlatformView.css'
import { getHiddenPipelineProgress, getTeacherPreparation } from '../teacherPreparation'
import { getAudioStatusMeta, getNextCourseSession } from '../courseSchedule'
import { getReusableTeacherDefaults } from '../centerWorkspace'
import { buildTeacherDescription } from '../teacherIdentity'
import { classifyFormationAudios } from '../audioLibrary'
import { calculateTrainingDays, RECRUITMENT_STEPS } from '../recruitmentConversation'
import { getMinimumNewModuleStartDate, prefillTrainingDates } from '../formationScheduleV2'

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
const loadTeacherCreationDraft = () => {
  try {
    return JSON.parse(window.sessionStorage.getItem('teacher_creation_draft') || 'null')
  } catch {
    window.sessionStorage.removeItem('teacher_creation_draft')
    return null
  }
}
const formatPrice = (amountCents, currency = 'eur') => (
  typeof amountCents === 'number'
    ? new Intl.NumberFormat('fr-FR', { style: 'currency', currency: currency.toUpperCase() }).format(amountCents / 100)
    : 'Tarif indisponible'
)

const PLATFORM_LOAD_TIMEOUT_MS = 30000
const ORDER_REVIEW_CENTER_EMAIL = 'newpiprod@gmail.com'
const isOrderReviewCenter = () => (
  String(localStorage.getItem('center_account_email') || '').trim().toLowerCase()
  === ORDER_REVIEW_CENTER_EMAIL
)

// Fixtures purement visuelles pour travailler le roster en local sans recopier
// de données réelles. Elles ne sont utilisées qu'en mode Vite DEV.
const buildLocalDesignTeachers = () => {
  const buildSession = (id, sessionIndex, daysFromNow) => {
    const scheduledAt = new Date()
    scheduledAt.setDate(scheduledAt.getDate() + daysFromNow)
    scheduledAt.setHours(9, 0, 0, 0)
    return { id, session_index: sessionIndex, scheduled_at: scheduledAt.toISOString(), audio_status: 'scheduled' }
  }
  const upcomingSessions = [
    buildSession(-1001, 2, 1),
    buildSession(-1002, 3, 2),
    buildSession(-1003, 4, 8),
  ]

  return [
    {
      id: -101,
      center_platform_number: 1,
      name: 'TP CRCD',
      teacher_name: 'Pierre',
      source_tp_name: 'TP CRCD',
      teacher_color: 'violet',
      active: true,
      status: 'ready',
      lifecycle_status: 'archived',
      total_session_count: 0,
      remaining_session_count: 0,
      teacher_preparation: { status: 'ready', progress: 100, stage: 'Professeur prêt' },
      course_schedule: { next_session: null, upcoming_sessions: [] },
    },
    {
      id: -102,
      center_platform_number: 2,
      name: 'TP EC',
      teacher_name: 'oktest',
      source_tp_name: 'TP EC',
      teacher_color: 'violet',
      active: true,
      status: 'ready',
      lifecycle_status: 'active',
      total_session_count: 5,
      remaining_session_count: 4,
      teacher_preparation: { status: 'ready', progress: 100, stage: 'Professeur prêt' },
      course_schedule: {
        next_session: upcomingSessions[0],
        upcoming_sessions: upcomingSessions,
      },
    },
  ]
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
  const [audiosLoading, setAudiosLoading] = useState(null)
  const [darkMode, setDarkMode] = useState(false)
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
  const [createOrderError, setCreateOrderError] = useState('')
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
  const [initialScheduleV2, setInitialScheduleV2] = useState(null)
  const [templateCreationDraft, setTemplateCreationDraft] = useState(loadTeacherCreationDraft)
  const [templateRedirecting, setTemplateRedirecting] = useState(false)
  const templateRedirectTimerRef = useRef(null)
  const [aiVoices, setAiVoices] = useState([])
  const [selectedAiVoiceId, setSelectedAiVoiceId] = useState('')
  const creatingRef = useRef(false)
  const creationRequestRef = useRef({ fingerprint: '', id: '' })
  const animatedTeacherOrdersRef = useRef(new Set())
  const [cardPage, setCardPage] = useState(0)
  const [teacherRosterFilter, setTeacherRosterFilter] = useState('all')
  const [workspaceSection, setWorkspaceSection] = useState(() => {
    const savedSection = localStorage.getItem('center_workspace_section')
    return ['recruit', 'teachers', 'schedule-templates', 'ai-voices', 'messages'].includes(savedSection)
      ? savedSection
      : 'recruit'
  })
  const [recruitmentPrefilled, setRecruitmentPrefilled] = useState(false)
  const [attendancePlatformId, setAttendancePlatformId] = useState('')
  const [attendanceDate, setAttendanceDate] = useState(todayDateInput)
  const [attendanceData, setAttendanceData] = useState(null)
  const [attendanceLoading, setAttendanceLoading] = useState(false)
  const [attendanceError, setAttendanceError] = useState('')
  const [loggingOut, setLoggingOut] = useState(false)
  const [billing, setBilling] = useState(null)
  const [billingLoading, setBillingLoading] = useState(true)
  const [activeTeacherOrderId, setActiveTeacherOrderId] = useState(null)
  const [failedTeacherOrderId, setFailedTeacherOrderId] = useState(null)
  const [retryingTeacherOrderId, setRetryingTeacherOrderId] = useState(null)
  const [orderNotice, setOrderNotice] = useState(null)
  const [centerMessages, setCenterMessages] = useState([])
  const [messagesUnreadCount, setMessagesUnreadCount] = useState(0)
  const [messagesLoading, setMessagesLoading] = useState(true)
  const [messagesError, setMessagesError] = useState('')
  const [showMobileSettings, setShowMobileSettings] = useState(false)
  const CARDS_PER_PAGE = 10

  const handleLogout = async () => {
    if (loggingOut) return
    setLoggingOut(true)
    try {
      await apiFetch('/api/admin/logout', { method: 'POST' })
    } catch (error) {
      console.warn('Déconnexion serveur indisponible, nettoyage local appliqué.', error)
    } finally {
      await clearSupabaseSession().catch((error) => {
        console.warn('Déconnexion Supabase locale indisponible.', error)
      })
      localStorage.removeItem('admin_auth_token')
      localStorage.removeItem('auth_token')
      localStorage.removeItem('center_account_email')
      localStorage.removeItem('center_account_name')
      window.location.assign('/connexion-centre')
    }
  }

  // ─── Fetch data ──────────────────────────────────────────────────────
  const fetchPlatforms = async () => {
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
        const loadedPlatforms = data.platforms || []
        setPlatforms(import.meta.env.DEV ? [...buildLocalDesignTeachers(), ...loadedPlatforms] : loadedPlatforms)
      } else {
        setPlatformsErrorTone('error')
        setPlatformsError(data.error || 'Impossible de charger les plateformes.')
      }
    } catch (e) {
      console.error('Erreur chargement plateformes:', e)
      if (import.meta.env.DEV) {
        setPlatforms(buildLocalDesignTeachers())
        setPlatformsError('')
        return
      }
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

  const fetchAiVoices = async () => {
    try {
      const response = await apiFetch('/api/hr/ai-voices')
      const data = await response.json().catch(() => ({}))
      if (response.ok && data.success) setAiVoices(data.voices || [])
    } catch (error) {
      console.warn('Chargement des voix IA indisponible.', error)
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

  const handleStudentEmailDraftChange = (platformId, field, value) => {
    setStudentEmailDrafts(prev => ({
      ...prev,
      [platformId]: { prenom: '', nom: '', email: '', ...(prev[platformId] || {}), [field]: value },
    }))
  }

  const handleAddStudentEmails = async (platformId) => {
    const draft = { prenom: '', nom: '', email: '', ...(studentEmailDrafts[platformId] || {}) }
    if (!draft.prenom.trim() || !draft.nom.trim() || !draft.email.trim()) return
    setStudentEmailsSaving(platformId)
    try {
      const resp = await apiFetch(`/api/hr/platforms/${platformId}/student-emails`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ students: [{ prenom: draft.prenom, nom: draft.nom, email: draft.email }] }),
      })
      const data = await resp.json()
      if (data.success) {
        setStudentEmailsByPlatform(prev => ({ ...prev, [platformId]: data.recipients || [] }))
        setStudentEmailDrafts(prev => ({ ...prev, [platformId]: { prenom: '', nom: '', email: '' } }))
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
    const root = document.documentElement
    const body = document.body
    const previousStyles = {
      rootOverflow: root.style.overflow,
      rootOverscrollBehavior: root.style.overscrollBehavior,
      bodyOverflow: body.style.overflow,
      bodyOverscrollBehavior: body.style.overscrollBehavior,
    }

    root.style.overflow = 'hidden'
    root.style.overscrollBehavior = 'none'
    body.style.overflow = 'hidden'
    body.style.overscrollBehavior = 'none'

    return () => {
      root.style.overflow = previousStyles.rootOverflow
      root.style.overscrollBehavior = previousStyles.rootOverscrollBehavior
      body.style.overflow = previousStyles.bodyOverflow
      body.style.overscrollBehavior = previousStyles.bodyOverscrollBehavior
    }
  }, [])

  useEffect(() => {
    fetchPlatforms()
    fetchAiVoices()
  }, [])

  const fetchCenterMessages = useCallback(async () => {
    try {
      const reviewMode = isOrderReviewCenter()
      const response = await apiFetch(
        reviewMode ? '/api/admin/teacher-order-validations' : '/api/hr/messages',
      )
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || !payload.success) throw new Error(payload.error || 'Chargement impossible')
      setCenterMessages(reviewMode ? [] : (payload.messages || []))
      setMessagesUnreadCount(Number(payload.unread_count || 0))
      setMessagesError('')
    } catch (requestError) {
      setMessagesError(requestError.message || 'Impossible de charger la messagerie.')
    } finally {
      setMessagesLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchCenterMessages()
    const timer = window.setInterval(() => void fetchCenterMessages(), 20000)
    return () => window.clearInterval(timer)
  }, [fetchCenterMessages])

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
    const checkoutSessionId = params.get('session_id')
    if (!checkout || !orderId) return
    setFailedTeacherOrderId(null)
    if (checkout === 'success') {
      setActiveTeacherOrderId(orderId)
      setWorkspaceSection('teachers')
      setTeacherRosterFilter('all')
      setCardPage(0)
      setOrderNotice({
        tone: 'info',
        title: 'Confirmation du paiement',
        message: 'Stripe confirme actuellement votre paiement. La préparation démarrera automatiquement dans quelques instants.',
      })
      setShowCreateModal(false)
      setShowModulesModal(false)
      void apiFetch(`/api/hr/teacher-orders/${orderId}/confirm-payment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(checkoutSessionId ? { session_id: checkoutSessionId } : {}),
      })
        .then(async (response) => ({
          response,
          data: await response.json().catch(() => ({})),
        }))
        .then(({ response, data }) => {
          if (!response.ok || !data.success) {
            throw new Error(data.error || 'Confirmation Stripe indisponible')
          }
          if (data.order?.payment_status === 'paid') {
            setOrderNotice({
              tone: 'info',
              title: 'Paiement confirmé',
              message: 'Votre commande est payée et sa préparation est maintenant prise en charge.',
              action: 'view_teacher',
            })
          }
        })
        .catch((error) => {
          console.error('Confirmation Stripe de secours impossible:', error)
        })
    } else if (checkout === 'cancelled') {
      setActiveTeacherOrderId(null)
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
          setSelectedAiVoiceId(String(project.ai_voice_id || ''))
          setNewPlatformName(project.name || '')
          if (project.module_id) setSelectedModuleId(String(project.module_id))
          if (project.new_formation) {
            setNewFormTpName(project.new_formation.tp_name || '')
            setNewFormRncp(project.new_formation.rncp_code || '')
            setNewFormHours(String(Math.ceil(Number(project.new_formation.total_hours || 0) / 7)))
          }
          const schedule = project.new_formation?.schedule || project.schedule
          if (schedule) {
            if (
              Number(schedule.schedule_schema_version || schedule.schema_version) === 2
              && Array.isArray(schedule.selected_dates)
              && project.new_formation
            ) {
              setNewFormHours(String(schedule.selected_dates.length))
            }
            setWeeklyCourseCount(String(schedule.weekly_course_count || 2))
            setTeachingDays(schedule.weekdays || [])
            setScheduleStartDate(schedule.start_date || todayDateInput())
            setScheduleStartTime('09:00')
            setInitialScheduleV2(
              Number(schedule.schedule_schema_version || schedule.schema_version) === 2
                ? schedule
                : null,
            )
          }
          creationRequestRef.current = {
            fingerprint: JSON.stringify({
              operation_type: data.order.operation_type,
              project,
            }),
            id: data.order.creation_request_id || '',
          }
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
        if (order.review_status === 'pending') {
          setOrderNotice({
            tone: 'info',
            title: 'Demande en cours d’étude',
            message: 'Notre équipe vérifie votre projet et les crédits API nécessaires. Vous recevrez le lien de paiement par e-mail après validation.',
          })
        } else if (order.review_status === 'rejected') {
          setOrderNotice({
            tone: 'warning',
            title: 'Demande non retenue',
            message: 'Aucun paiement ne sera demandé. Contactez notre équipe si vous souhaitez ajuster votre projet.',
          })
          setActiveTeacherOrderId(null)
        } else if (order.fulfillment_status === 'fulfilled') {
          const shouldAnimateTeacher = Boolean(order.platform_id)
            && !animatedTeacherOrdersRef.current.has(order.id || activeTeacherOrderId)
          if (shouldAnimateTeacher) {
            animatedTeacherOrdersRef.current.add(order.id || activeTeacherOrderId)
            setNewlyCreatedPlatformId(order.platform_id)
          }
          setFailedTeacherOrderId(null)
          setOrderNotice({
            tone: 'success',
            title: 'Votre professeur IA se prépare',
            message: 'Il apparaît maintenant dans Mes professeurs IA. Les cours sont produits en arrière-plan.',
          })
          setActiveTeacherOrderId(null)
          setShowCreateModal(false)
          setShowModulesModal(false)
          setWorkspaceSection('teachers')
          setTeacherRosterFilter('all')
          setCardPage(0)
          await fetchPlatforms()
        } else if (order.fulfillment_status === 'failed') {
          setFailedTeacherOrderId(order.id || activeTeacherOrderId)
          setOrderNotice({
            tone: 'error',
            title: 'Pipeline interrompue',
            message: 'Votre paiement est conservé. Notre système n’effectuera aucun second prélèvement.',
          })
          setActiveTeacherOrderId(null)
        } else if (['failed', 'expired'].includes(order.payment_status)) {
          setFailedTeacherOrderId(null)
          setOrderNotice({
            tone: 'error',
            title: 'Paiement non finalisé',
            message: 'La commande n’a pas été débitée. Reprenez la création pour ouvrir une nouvelle page de paiement.',
          })
          setActiveTeacherOrderId(null)
        } else if (order.payment_status === 'refunded') {
          setFailedTeacherOrderId(null)
          setOrderNotice({
            tone: 'warning',
            title: 'Paiement remboursé',
            message: 'Cette commande ne sera pas préparée. Contactez l’équipe technique si vous avez besoin d’aide.',
          })
          setActiveTeacherOrderId(null)
        } else if (
          order.payment_status === 'paid'
          && ['not_started', 'queued', 'running'].includes(order.fulfillment_status)
        ) {
          setOrderNotice({
            tone: 'info',
            title: 'Paiement confirmé',
            message: 'Votre commande est payée et sa préparation est maintenant prise en charge.',
          })
          if (
            order.platform_id
            && !animatedTeacherOrdersRef.current.has(order.id || activeTeacherOrderId)
          ) {
            animatedTeacherOrdersRef.current.add(order.id || activeTeacherOrderId)
            setNewlyCreatedPlatformId(order.platform_id)
            setWorkspaceSection('teachers')
            setTeacherRosterFilter('all')
            setCardPage(0)
            await fetchPlatforms()
          }
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
        title: 'Pipeline reprise',
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
    setExpandedPlatform(platformId)
    if (!platformAudios[platformId]) fetchAudios(platformId)
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

  const handleOpenCoursFolders = (platform) => {
    closeCardPanels()
    return platform
  }

  const fetchAttendance = async (platformId = attendancePlatformId, courseDate = attendanceDate) => {
    if (!platformId || !courseDate) return
    if (import.meta.env.DEV && Number(platformId) < 0) {
      setAttendanceData({ students: [], daily_exports: [] })
      setAttendanceError('')
      setAttendanceLoading(false)
      return
    }
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
    setInitialScheduleV2(null)
    setSelectedAiVoiceId('')
    setCreateOrderError('')
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

  const showScheduleTemplatesView = () => {
    setWorkspaceSection('schedule-templates')
    setShowModulesModal(false)
    setShowCreateModal(false)
    setRecruitmentPrefilled(false)
    setModuleSearchQuery('')
  }

  const showAiVoicesView = () => {
    setWorkspaceSection('ai-voices')
    setShowModulesModal(false)
    setShowCreateModal(false)
    setRecruitmentPrefilled(false)
    setModuleSearchQuery('')
  }

  const showMessagesView = () => {
    setWorkspaceSection('messages')
    setShowModulesModal(false)
    setShowCreateModal(false)
    setRecruitmentPrefilled(false)
    setModuleSearchQuery('')
    void fetchCenterMessages()
  }

  const markCenterMessageSeen = async (messageId) => {
    const wasUnread = centerMessages.some((message) => message.id === messageId && !message.read)
    setCenterMessages((current) => current.map((message) => (
      message.id === messageId ? { ...message, read: true } : message
    )))
    if (wasUnread) setMessagesUnreadCount((current) => Math.max(0, current - 1))
    await apiFetch(`/api/hr/messages/${messageId}/seen`, { method: 'POST' }).catch(() => {})
  }

  const createTemplateFromFormationDraft = (calendarState) => {
    if (templateRedirectTimerRef.current) return
    const scheduleDraft = {
      schedule_schema_version: 2,
      selected_dates: calendarState.selected_dates || [],
      template_assignments: calendarState.template_assignments || {},
    }
    const draft = {
      teacherFirstName,
      teacherColor,
      weeklyCourseCount,
      teachingDays,
      scheduleStartDate: calendarState.start_date || scheduleStartDate,
      newFormTpName,
      newFormRncp,
      newFormHours,
      formationMode,
      selectedModuleId,
      selectedAiVoiceId,
      schedule: scheduleDraft,
    }
    window.sessionStorage.setItem('teacher_creation_draft', JSON.stringify(draft))
    setInitialScheduleV2(scheduleDraft)
    setTemplateCreationDraft(draft)
    setTemplateRedirecting(true)

    const openTemplateEditor = () => {
      templateRedirectTimerRef.current = null
      setTemplateRedirecting(false)
      showScheduleTemplatesView()
    }
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    templateRedirectTimerRef.current = window.setTimeout(
      openTemplateEditor,
      reduceMotion ? 1100 : 1750,
    )
  }

  const resumeFormationDraftWithTemplate = () => {
    const draft = templateCreationDraft || loadTeacherCreationDraft()
    if (draft) {
      setTeacherFirstName(draft.teacherFirstName || '')
      setTeacherColor(draft.teacherColor || 'violet')
      setWeeklyCourseCount(String(draft.weeklyCourseCount || '2'))
      setTeachingDays(Array.isArray(draft.teachingDays) ? draft.teachingDays : ['mardi', 'jeudi'])
      setScheduleStartDate(draft.scheduleStartDate || todayDateInput())
      setNewFormTpName(draft.newFormTpName || '')
      setNewFormRncp(draft.newFormRncp || '')
      setNewFormHours(String(draft.newFormHours || ''))
      setFormationMode(draft.formationMode || 'new')
      setSelectedModuleId(String(draft.selectedModuleId || ''))
      setSelectedAiVoiceId(String(draft.selectedAiVoiceId || ''))
      setInitialScheduleV2(draft.schedule || null)
    }
    window.sessionStorage.removeItem('teacher_creation_draft')
    setTemplateCreationDraft(null)
    setTemplateRedirecting(false)
    setWorkspaceSection('recruit')
    setShowModulesModal(false)
    setShowCreateModal(true)
  }

  const startNewManualRecruitment = () => {
    window.sessionStorage.removeItem('teacher_creation_draft')
    setTemplateCreationDraft(null)
  }

  useEffect(() => () => {
    if (templateRedirectTimerRef.current) {
      window.clearTimeout(templateRedirectTimerRef.current)
    }
  }, [])

  useEffect(() => {
    localStorage.setItem('center_workspace_section', workspaceSection)
  }, [workspaceSection])

  const handleAssistantComplete = (draft) => {
    resetCreateForm()
    const weekdayNumbers = {
      lundi: 1,
      mardi: 2,
      mercredi: 3,
      jeudi: 4,
      vendredi: 5,
    }
    const preferredWeekdays = draft.teachingDays
      .map((day) => weekdayNumbers[day])
      .filter(Boolean)
    const selectedDates = prefillTrainingDates({
      startDate: draft.startDate,
      weeks: Number(draft.trainingWeeks) + 1,
      daysPerWeek: Number(draft.weeklyCourseCount),
      preferredWeekdays,
      limit: Number(draft.trainingDays),
    })

    setTeacherFirstName(draft.teacherName)
    setTeacherColor(draft.teacherColor)
    setNewFormTpName(draft.trainingName)
    setNewFormRncp(draft.rncpCode)
    setNewFormHours(String(draft.trainingDays))
    setWeeklyCourseCount(String(draft.weeklyCourseCount))
    setTeachingDays(draft.teachingDays)
    setScheduleStartDate(draft.startDate)
    setInitialScheduleV2({
      schedule_schema_version: 2,
      selected_dates: selectedDates,
      template_assignments: {},
    })
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

  const handleCreatePlatform = async (teacherDescription = '', schedule = null, slideBrandName = 'Le Socrate') => {
    if (creatingRef.current) return
    setCreateOrderError('')
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
      teacher_description: String(teacherDescription || '').trim(),
      slide_brand_name: slideBrandName == null ? 'Le Socrate' : String(slideBrandName).trim(),
      ai_voice_id: selectedAiVoiceId ? Number(selectedAiVoiceId) : null,
    }
    let operationType = 'new_teacher'
    const scheduleVersion = Number(
      schedule?.schedule_schema_version
      || schedule?.schema_version
      || (Array.isArray(schedule?.selected_dates) ? 2 : 1),
    )
    const selectedDates = Array.isArray(schedule?.selected_dates)
      ? schedule.selected_dates
      : []
    if (
      formationMode !== 'existing'
      && (scheduleVersion !== 2 || selectedDates.length === 0)
    ) {
      setCreateOrderError('Validez le calendrier et l’organisation des journées avant de continuer.')
      return
    }
    if (formationMode === 'existing') {
      if (!selectedModuleId) {
        setCreateOrderError('Sélectionnez un ancien professeur IA.')
        return
      }
      const moduleScheduleVersion = Number(selectedModule?.schedule_schema_version || 1)
      if (moduleScheduleVersion >= 2) {
        if (scheduleVersion !== 2 || selectedDates.length === 0) {
          setCreateOrderError('Sélectionnez toutes les nouvelles dates de ce module.')
          return
        }
      } else {
        const weeklyCount = Number(schedule?.weekly_course_count || 0)
        const weekdays = Array.isArray(schedule?.weekdays) ? schedule.weekdays : []
        if (
          weeklyCount <= 0
          || weeklyCount !== weekdays.length
          || !schedule?.start_date
          || schedule?.start_time !== '09:00'
        ) {
          setCreateOrderError('Complétez le calendrier classique de cet ancien module.')
          return
        }
      }
      operationType = 'reuse_teacher'
      project = {
        ...project,
        module_id: parseInt(selectedModuleId, 10),
        schedule,
      }
    } else {
      const rncp = newFormRncp.trim()
      const trainingDaysCount = selectedDates.length
      if (!trainingTitle || !rncp || !trainingDaysCount) {
        setCreateOrderError('Nom de formation, code RNCP et calendrier validé requis.')
        return
      }
      project.new_formation = {
        tp_name: trainingTitle,
        rncp_code: rncp,
        // Champ de compatibilité V1. En V2, selected_dates est l’unique
        // autorité pour le nombre de journées.
        total_hours: trainingDaysCount * 7,
        schedule,
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
      const data = await resp.json().catch(() => ({}))
      if (resp.ok && data.success) {
        if (data.next_action === 'redirect' && data.checkout_url) {
          window.location.assign(data.checkout_url)
          return
        }
        const pendingReview = data.next_action === 'pending_review'
        setActiveTeacherOrderId(pendingReview ? null : data.order.id)
        setOrderNotice({
          tone: 'info',
          title: pendingReview
            ? 'Demande envoyée'
            : billing?.payment_required === false ? 'Préparation lancée' : 'Paiement confirmé',
          message: pendingReview
            ? 'Votre demande a bien été envoyée à nos équipes. Nous la traiterons dans les plus bref délais. Veuillez consulter votre messagerie.'
            : 'Votre professeur IA va apparaître dans Mes professeurs IA et se préparer en arrière-plan.',
        })
        setShowCreateModal(false)
        resetCreateForm()
        setShowModulesModal(false)
        void fetchCenterMessages()
      } else {
        throw new Error(data.error || data.message || 'Impossible de lancer la commande.')
      }
    } catch (e) {
      console.error('Erreur commande professeur IA:', e)
      setCreateOrderError(e.message || 'Impossible de lancer la commande.')
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
    return <AppLoader label="Chargement du tableau de bord" surface={darkMode ? 'dark' : 'light'} />
  }

  // Palette neutre commune au nouvel espace centre.
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
    primary: '#18181B',
    gridOpacity: '0',
  }
  const platformsAlertIsWarning = platformsErrorTone === 'warning'
  const teacherRosterVisible = !showModulesModal && !showCreateModal && workspaceSection === 'teachers'
  const recruitmentAssistantVisible = !showModulesModal && !showCreateModal && workspaceSection === 'recruit'
  const scheduleTemplatesVisible = !showModulesModal && !showCreateModal && workspaceSection === 'schedule-templates'
  const aiVoicesVisible = !showModulesModal && !showCreateModal && workspaceSection === 'ai-voices'
  const messagesVisible = !showModulesModal && !showCreateModal && workspaceSection === 'messages'
  const centerAccountEmail = localStorage.getItem('center_account_email') || 'Compte centre'
  const centerAccountName = localStorage.getItem('center_account_name') || 'Centre de formation'

  return (
    <div className={darkMode ? 'dark' : ''}>
      <div className="relative flex h-dvh overflow-hidden" style={{ backgroundColor: colors.bg, fontFamily: 'Inter, sans-serif' }}>
        <CenterWorkspaceSidebar
          colors={colors}
          activeSection={workspaceSection}
          collapseOnCreate={showCreateModal}
          onShowTeachers={showDashboardView}
          onShowRecruit={showRecruitView}
          onShowScheduleTemplates={showScheduleTemplatesView}
          onShowAiVoices={showAiVoicesView}
          onShowMessages={showMessagesView}
          messagesUnreadCount={messagesUnreadCount}
          onLogout={handleLogout}
          loggingOut={loggingOut}
        />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className="flex h-14 items-center justify-between border-b px-4 md:hidden" style={{ borderColor: colors.borderLight, backgroundColor: colors.cardBg }}>
            <span className="hidden min-w-0 truncate pr-2 text-sm font-semibold min-[520px]:block" style={{ color: colors.text }}>
              {workspaceSection === 'teachers'
                ? 'Mes professeurs'
                : workspaceSection === 'schedule-templates'
                  ? 'Organisation des cours'
                  : workspaceSection === 'ai-voices'
                    ? 'Mes voix IA'
                    : workspaceSection === 'messages'
                      ? 'Messagerie'
                  : 'Recruter un professeur'}
            </span>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={showRecruitView}
                className="flex h-11 w-11 items-center justify-center rounded-lg transition-colors hover:bg-[#F3F4F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
                aria-label="Recruter un professeur"
                aria-current={workspaceSection === 'recruit' ? 'page' : undefined}
                style={{ color: '#3F3F46', backgroundColor: workspaceSection === 'recruit' ? '#E9E9E7' : 'transparent' }}
              >
                <Icon name="person_add_alt_1" className="text-lg" />
              </button>
              <button
                type="button"
                onClick={showDashboardView}
                className="flex h-11 w-11 items-center justify-center rounded-lg transition-colors hover:bg-[#F3F4F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
                aria-label="Mes professeurs"
                aria-current={workspaceSection === 'teachers' ? 'page' : undefined}
                style={{ color: '#3F3F46', backgroundColor: workspaceSection === 'teachers' ? '#E9E9E7' : 'transparent' }}
              >
                <Icon name="groups" className="text-lg" />
              </button>
              <button
                type="button"
                onClick={showScheduleTemplatesView}
                className="flex h-11 w-11 items-center justify-center rounded-lg transition-colors hover:bg-[#F3F4F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
                aria-label="Organisation des cours"
                aria-current={workspaceSection === 'schedule-templates' ? 'page' : undefined}
                style={{ color: '#3F3F46', backgroundColor: workspaceSection === 'schedule-templates' ? '#E9E9E7' : 'transparent' }}
              >
                <Icon name="calendar_view_day" className="text-lg" />
              </button>
              <button
                type="button"
                onClick={showAiVoicesView}
                className="flex h-11 w-11 items-center justify-center rounded-lg transition-colors hover:bg-[#F3F4F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
                aria-label="Mes voix IA"
                aria-current={workspaceSection === 'ai-voices' ? 'page' : undefined}
                style={{ color: '#3F3F46', backgroundColor: workspaceSection === 'ai-voices' ? '#E9E9E7' : 'transparent' }}
              >
                <Icon name="graphic_eq" className="text-lg" />
              </button>
              <button
                type="button"
                onClick={showMessagesView}
                className="relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors hover:bg-[#F3F4F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
                aria-label="Messagerie"
                aria-current={workspaceSection === 'messages' ? 'page' : undefined}
                style={{ color: '#3F3F46', backgroundColor: workspaceSection === 'messages' ? '#E9E9E7' : 'transparent' }}
              >
                <Mail size={18} strokeWidth={1.7} aria-hidden="true" />
                {messagesUnreadCount > 0 && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-[#18181B] ring-2 ring-white" />}
              </button>
              <button
                type="button"
                onClick={() => setShowMobileSettings(true)}
                className="flex h-11 w-11 items-center justify-center rounded-lg text-[#3F3F46] transition-colors hover:bg-[#F3F4F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
                aria-label="Paramètres du compte"
              >
                <Settings size={18} strokeWidth={1.7} aria-hidden="true" />
              </button>
            </div>
          </div>

        <main className={`relative z-10 min-h-0 min-w-0 flex-1 bg-white ${
          showCreateModal
            ? 'overflow-hidden'
            : `px-4 sm:px-6 lg:px-8 ${scheduleTemplatesVisible ? 'overflow-hidden' : teacherRosterVisible || recruitmentAssistantVisible || aiVoicesVisible || messagesVisible ? 'overflow-hidden' : 'overflow-y-auto pb-12'}`
        }`}>
          <div className={`mx-auto flex h-full min-h-0 w-full flex-col ${
            showCreateModal ? 'max-w-none' : 'max-w-[1480px] pt-4 md:pt-6'
          }`}>
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
                    {retryingTeacherOrderId ? 'Reprise en cours…' : 'Reprendre la pipeline'}
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
              initialScheduleV2={initialScheduleV2}
              aiVoices={aiVoices}
              selectedAiVoiceId={selectedAiVoiceId}
              setSelectedAiVoiceId={setSelectedAiVoiceId}
              onCreateTemplate={createTemplateFromFormationDraft}
              templateRedirecting={templateRedirecting}
              creating={creating}
              billing={billing}
              billingLoading={billingLoading}
              prefilledFromAssistant={recruitmentPrefilled}
              submissionError={createOrderError}
              onCreate={handleCreatePlatform}
              onCancel={() => { setShowCreateModal(false); setRecruitmentPrefilled(false); resetCreateForm() }}
            />
          ) : workspaceSection === 'recruit' ? (
            <RecruitmentAssistant
              colors={colors}
              modules={modules}
              onComplete={handleAssistantComplete}
              hasSavedDraft={Boolean(templateCreationDraft)}
              onResumeDraft={resumeFormationDraftWithTemplate}
              onManualStart={startNewManualRecruitment}
            />
          ) : workspaceSection === 'schedule-templates' ? (
            <DayScheduleTemplates
              createOnMount={Boolean(templateCreationDraft)}
              onUseTemplate={templateCreationDraft ? resumeFormationDraftWithTemplate : undefined}
            />
          ) : workspaceSection === 'ai-voices' ? (
            <AIVoicesView onVoicesChange={setAiVoices} />
          ) : workspaceSection === 'messages' ? (
            isOrderReviewCenter() ? (
              <TeacherOrderReviewInbox onUnreadCountChange={setMessagesUnreadCount} />
            ) : (
              <CenterMessagesPanel
                messages={centerMessages}
                loading={messagesLoading}
                error={messagesError}
                onRetry={fetchCenterMessages}
                onOpen={markCenterMessageSeen}
              />
            )
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
              onRecruit={showRecruitView}
              expandedPlatform={expandedPlatform}
              platformAudios={platformAudios}
              audiosLoading={audiosLoading}
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
              onExpand={handleExpandPlatform}
              onRefreshAudios={fetchAudios}
              onToggleStudentEmails={handleToggleStudentEmails}
              onToggleAttendance={handleToggleAttendance}
              onStudentEmailDraftChange={handleStudentEmailDraftChange}
              onAddStudentEmails={handleAddStudentEmails}
              onDeleteStudentEmail={handleDeleteStudentEmail}
              onAttendanceDateChange={setAttendanceDate}
              onRefreshAttendance={(platformId) => fetchAttendance(platformId, attendanceDate)}
              onExportAttendance={(week, platformId) => handleExportAttendance(week, platformId)}
              onOpenCourseTimeModal={async (platform) => {
                closeCardPanels()
                setCourseTimePlatformId(platform.id)
                try {
                  const resp = await apiFetch(`/api/hr/platforms/${platform.id}/course-time`)
                  const data = await resp.json()
                  if (data.success) setCurrentCourseTime(data)
                  else setCurrentCourseTime(null)
                } catch { setCurrentCourseTime(null) }
              }}
              onOpenCoursFolders={handleOpenCoursFolders}
              onCloseCardPanels={closeCardPanels}
              currentCourseTime={currentCourseTime}
              onSetCourseTime={handleSetCourseTime}
              onRetrySessionAudio={handleRetrySessionAudio}
              onPreviewSessionPostponement={handlePreviewSessionPostponement}
              onPostponeSession={handlePostponeSession}
              onAudiosPublished={handleAudiosPublished}
              newlyCreatedPlatformId={newlyCreatedPlatformId}
              retryingPlatformId={retryingPlatformId}
              onRetryPreparation={handleRetryTeacherPreparation}
              onTestClockChanged={fetchPlatforms}
            />
          )}
          </div>
        </main>
      </div>

      {/* Modal confirmation suppression — branche par type :
          - audio : confirmation simple (atomique, peu d'impact)
          - platform : confirmation enrichie + type-to-confirm (cascade,
            irréversibilité, registre Examiner's Desk per DESIGN.md). */}
      {deleteConfirm && deleteConfirm.type === 'audio' && (
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
                Supprimer cet audio ?
              </h3>
              <p className="text-sm mb-6" style={{ color: '#64748b' }}>
                Voulez-vous vraiment supprimer <strong>"{deleteConfirm.filename}"</strong> ? Cette action est irréversible.
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

      {showMobileSettings && createPortal(
        <CenterSettingsModal
          accountName={centerAccountName}
          accountEmail={centerAccountEmail}
          onClose={() => setShowMobileSettings(false)}
        />,
        document.body,
      )}

    </div>
    </div>
  )
}

function CenterMessagesPanel({ messages, loading, error, onRetry, onOpen }) {
  const [selectedId, setSelectedId] = useState(null)
  const [paymentLoadingId, setPaymentLoadingId] = useState(null)
  const [paymentError, setPaymentError] = useState('')

  useEffect(() => {
    if (!messages.length) {
      setSelectedId(null)
      return
    }
    setSelectedId((current) => (
      messages.some((message) => message.id === current) ? current : messages[0].id
    ))
  }, [messages])

  const selected = messages.find((message) => message.id === selectedId) || messages[0] || null
  useEffect(() => {
    if (selected && !selected.read) void onOpen(selected.id)
  }, [selected?.id, selected?.read])

  const openMessage = (message) => {
    setSelectedId(message.id)
    setPaymentError('')
    if (!message.read) void onOpen(message.id)
  }

  const openPayment = async (message) => {
    if (paymentLoadingId) return
    setPaymentError('')
    setPaymentLoadingId(message.order_id)
    try {
      const response = await apiFetch(`/api/hr/billing/orders/${message.order_id}/checkout`, {
        method: 'POST',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.url) {
        throw new Error(data.error || 'Impossible d’ouvrir le paiement.')
      }
      window.location.assign(data.url)
    } catch (paymentRequestError) {
      setPaymentError(paymentRequestError.message || 'Impossible d’ouvrir le paiement.')
      setPaymentLoadingId(null)
    }
  }

  if (loading) {
    return <div className="flex h-full items-center justify-center"><AppLoader label="Chargement de la messagerie" /></div>
  }

  return (
    <section className="flex h-full min-h-0 flex-col" aria-labelledby="center-messages-title">
      <header className="flex shrink-0 items-start justify-between gap-4 border-b border-[#E9E9EC] pb-4">
        <div>
          <h1 id="center-messages-title" className="text-xl font-semibold tracking-tight text-[#18181B]">Messagerie</h1>
          <p className="mt-1 text-sm text-[#6B6B72]">Suivez ici la validation et la préparation de vos professeurs.</p>
        </div>
        <button type="button" onClick={onRetry} className="flex min-h-10 items-center gap-2 rounded-lg border border-[#D9D9DE] px-3 text-sm font-medium text-[#3F3F46] hover:bg-[#F5F5F6]">
          <Icon name="refresh" className="text-base" /> Actualiser
        </button>
      </header>

      {error && (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">
          <span>{error}</span>
          <button type="button" onClick={onRetry} className="font-semibold">Réessayer</button>
        </div>
      )}

      {messages.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-[#F1F1EF] text-[#5F5E5A]"><Mail size={21} aria-hidden="true" /></span>
          <h2 className="mt-4 text-base font-semibold text-[#18181B]">Aucun message pour le moment</h2>
          <p className="mt-1 max-w-sm text-sm leading-6 text-[#6B6B72]">Les confirmations liées à vos demandes de professeurs apparaîtront ici.</p>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(280px,390px)_1fr]">
          <div className="max-h-[36dvh] overflow-y-auto border-b border-[#E9E9EC] lg:max-h-none lg:border-b-0 lg:border-r">
            {messages.map((message) => (
              <button
                key={message.id}
                type="button"
                onClick={() => openMessage(message)}
                className="flex w-full items-start gap-3 border-b border-[#EFEFF1] px-3 py-4 text-left transition-colors hover:bg-[#F8F8F7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#18181B]/40 sm:px-4"
                style={{ backgroundColor: selected?.id === message.id ? '#F4F4F2' : '#fff' }}
              >
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${message.read ? 'bg-transparent' : 'bg-[#18181B]'}`} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-[#18181B]">{message.title}</span>
                  <span className="mt-1 block truncate text-xs text-[#6B6B72]">{message.training_title}</span>
                  <span className="mt-1 block text-[11px] text-[#8A8A91]">{formatRelativeTime(message.updated_at) || 'À l’instant'}</span>
                </span>
                <Icon name="chevron_right" className="mt-0.5 text-base text-[#A1A1AA]" />
              </button>
            ))}
          </div>

          <article className="min-h-0 overflow-y-auto px-2 py-6 sm:px-6 lg:px-10 lg:py-8">
            {selected && (
              <div className="mx-auto max-w-2xl">
                <p className="text-xs text-[#6B6B72]">{formatScheduleDateTime(selected.updated_at)}</p>
                <p className="mt-4 max-w-[68ch] text-sm leading-6 text-[#3F3F46]">{selected.body}</p>
                {selected.action === 'payment' && (
                  <div className="mt-4">
                    <button
                      type="button"
                      onClick={() => openPayment(selected)}
                      disabled={paymentLoadingId === selected.order_id}
                      className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[#18181B] px-4 text-sm font-medium text-white transition-[background-color,transform] duration-150 hover:bg-[#2C2C30] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/45 focus-visible:ring-offset-2 active:scale-[0.98] disabled:cursor-wait disabled:opacity-60"
                    >
                      <CreditCard size={17} aria-hidden="true" />
                      {paymentLoadingId === selected.order_id ? 'Ouverture…' : 'Payer'}
                    </button>
                    {paymentError && <p className="mt-2 text-sm text-rose-700" role="alert">{paymentError}</p>}
                  </div>
                )}
                <p className="mt-6 text-sm font-semibold text-[#18181B]">{selected.title}</p>
              </div>
            )}
          </article>
        </div>
      )}
    </section>
  )
}

function CenterWorkspaceSidebar({
  colors,
  activeSection,
  collapseOnCreate,
  onShowTeachers,
  onShowRecruit,
  onShowScheduleTemplates,
  onShowAiVoices,
  onShowMessages,
  messagesUnreadCount,
  onLogout,
  loggingOut,
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const accountDetailsRef = useRef(null)
  const accountEmail = localStorage.getItem('center_account_email') || 'Compte centre'
  const accountName = localStorage.getItem('center_account_name') || 'Centre de formation'
  const isSignedIn = Boolean(
    localStorage.getItem('admin_auth_token')
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
    { id: 'schedule-templates', label: 'Organisation des cours', icon: CalendarDays, onClick: onShowScheduleTemplates },
    { id: 'ai-voices', label: 'Mes voix IA', icon: AudioWaveform, onClick: onShowAiVoices },
    { id: 'messages', label: 'Messagerie', icon: Mail, onClick: onShowMessages, badge: messagesUnreadCount },
  ]

  useEffect(() => {
    if (collapseOnCreate) setCollapsed(true)
  }, [collapseOnCreate])

  useEffect(() => {
    const closeAccountMenu = (event) => {
      const details = accountDetailsRef.current
      if (!details?.open) return

      if (event.type === 'keydown') {
        if (event.key !== 'Escape') return
        details.open = false
        details.querySelector('summary')?.focus()
        return
      }

      if (!details.contains(event.target)) {
        details.open = false
      }
    }

    document.addEventListener('pointerdown', closeAccountMenu)
    document.addEventListener('keydown', closeAccountMenu)
    return () => {
      document.removeEventListener('pointerdown', closeAccountMenu)
      document.removeEventListener('keydown', closeAccountMenu)
    }
  }, [])

  return (
    <aside
      className={`relative z-30 hidden h-screen min-h-0 shrink-0 flex-col border-r md:flex ${collapsed ? 'w-[72px]' : 'w-[248px]'}`}
      style={{
        backgroundColor: '#F7F7F5',
        borderColor: colors.borderLight,
        transition: 'width 180ms cubic-bezier(0.16, 1, 0.3, 1)',
      }}
      aria-label="Navigation de l’espace centre"
    >
      <div className={`flex h-16 shrink-0 items-center ${collapsed ? 'justify-center px-2' : 'justify-between px-4'}`}>
        {!collapsed && (
          <img src="/socrate-mark.svg" alt="Le Socrate" className="h-8 w-8" />
        )}
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="flex h-11 w-11 items-center justify-center rounded-md text-[#6B6B68] transition-colors duration-150 hover:bg-black/[0.055] hover:text-[#191918] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
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
              className={`relative flex min-h-11 w-full items-center rounded-md py-1.5 text-left text-sm font-medium transition-colors duration-150 hover:bg-black/[0.045] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50 ${collapsed ? 'justify-center px-2' : 'gap-2.5 px-2'}`}
              style={{
                backgroundColor: selected ? '#E9E9E7' : 'transparent',
                color: selected ? '#191918' : '#5F5E5A',
              }}
              title={collapsed ? item.label : undefined}
            >
              <NavIcon size={17} strokeWidth={selected ? 1.8 : 1.6} aria-hidden="true" />
              {!collapsed && <span>{item.label}</span>}
              {item.badge > 0 && (
                <span className={`${collapsed ? 'absolute right-2 top-2 h-2 w-2 p-0' : 'ml-auto flex h-6 w-6 shrink-0 items-center justify-center p-0 tabular-nums'} rounded-full bg-[#18181B] text-[10px] font-semibold leading-none text-white`}>
                  {!collapsed && item.badge}
                </span>
              )}
            </button>
          )
        })}
      </nav>

      <div className={`mt-auto ${collapsed ? 'p-2' : 'p-2'}`}>
        <details
          ref={accountDetailsRef}
          className="group relative"
        >
          <summary className={`flex min-h-11 cursor-pointer list-none items-center rounded-md py-1.5 transition-colors duration-150 hover:bg-black/[0.045] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50 ${collapsed ? 'justify-center px-1' : 'gap-2.5 px-2'}`}>
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
            <div className="p-1.5">
              <div className="border-b border-[#ECECEA] px-2 pb-2 pt-1">
                <p className="truncate text-[13px] font-medium text-[#191918]">{accountName}</p>
                <p className="mt-0.5 truncate text-xs text-[#73736F]">{accountEmail}</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  accountDetailsRef.current.open = false
                  setShowSettings(true)
                }}
                className="mt-1 flex min-h-11 w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-[#5F5E5A] transition-colors hover:bg-[#F6F5F4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
              >
                <Settings size={16} strokeWidth={1.6} aria-hidden="true" />
                <span>Paramètres</span>
              </button>
              <button
                type="button"
                onClick={isSignedIn ? onLogout : () => window.location.assign('/connexion-centre')}
                disabled={isSignedIn && loggingOut}
                className="flex min-h-11 w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm text-[#B42318] transition-colors hover:bg-[#FFF3F2] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#B42318]/35 disabled:opacity-60"
              >
                {isSignedIn ? <LogOut size={16} strokeWidth={1.6} aria-hidden="true" /> : <LogIn size={16} strokeWidth={1.6} aria-hidden="true" />}
                {isSignedIn ? (loggingOut ? 'Déconnexion…' : 'Se déconnecter') : 'Se connecter'}
              </button>
            </div>
          </div>
        </details>
      </div>

      {showSettings && createPortal(
        <CenterSettingsModal
          accountName={accountName}
          accountEmail={accountEmail}
          onClose={() => setShowSettings(false)}
        />,
        document.body,
      )}
    </aside>
  )
}

const SETTINGS_TABS = [
  { id: 'account', label: 'Compte', icon: ShieldCheck },
  { id: 'billing', label: 'Facturation', icon: CreditCard },
]

const BILLING_OPERATION_LABELS = {
  new_teacher: 'Création d’un professeur IA',
  reuse_teacher: 'Réutilisation d’un professeur IA',
}

const formatBillingDate = (value) => {
  if (!value) return 'Date indisponible'
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  }).format(new Date(value))
}

function CenterSettingsModal({ accountName, accountEmail, onClose }) {
  const [activeTab, setActiveTab] = useState('account')
  const [authLoading, setAuthLoading] = useState(true)
  const [authProviders, setAuthProviders] = useState([])
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordSaving, setPasswordSaving] = useState(false)
  const [passwordMessage, setPasswordMessage] = useState(null)
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false)
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const [deletingAccount, setDeletingAccount] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [billingOrders, setBillingOrders] = useState([])
  const [billingHistoryLoading, setBillingHistoryLoading] = useState(false)
  const [billingHistoryLoaded, setBillingHistoryLoaded] = useState(false)
  const [billingError, setBillingError] = useState('')
  const [invoiceLoadingId, setInvoiceLoadingId] = useState(null)
  const closeButtonRef = useRef(null)

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButtonRef.current?.focus()
    return () => { document.body.style.overflow = previousOverflow }
  }, [])

  useEffect(() => {
    const handleEscape = (event) => {
      if (event.key === 'Escape' && !deletingAccount && !passwordSaving) onClose()
    }
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('keydown', handleEscape)
    }
  }, [deletingAccount, onClose, passwordSaving])

  useEffect(() => {
    let cancelled = false
    getSupabaseClient()
      .then(async (client) => {
        if (!client) return
        const { data, error } = await client.auth.getUser()
        if (error || cancelled) return
        const providers = new Set([
          ...(Array.isArray(data.user?.app_metadata?.providers) ? data.user.app_metadata.providers : []),
          ...(data.user?.identities || []).map((identity) => identity.provider),
        ])
        setAuthProviders([...providers].filter(Boolean))
      })
      .catch((error) => console.warn('Lecture de la méthode de connexion impossible:', error))
      .finally(() => { if (!cancelled) setAuthLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (activeTab !== 'billing' || billingHistoryLoaded) return
    let cancelled = false
    setBillingHistoryLoading(true)
    setBillingError('')
    apiFetch('/api/hr/billing/history')
      .then(async (response) => ({ response, data: await response.json().catch(() => ({})) }))
      .then(({ response, data }) => {
        if (cancelled) return
        if (!response.ok || !data.success) throw new Error(data.error || 'Historique indisponible.')
        setBillingOrders(data.orders || [])
      })
      .catch((error) => {
        console.warn('Lecture de l’historique de facturation impossible:', error)
        if (!cancelled) {
          setBillingOrders([])
          setBillingError('')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setBillingHistoryLoaded(true)
          setBillingHistoryLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [activeTab, billingHistoryLoaded])

  const usesGoogle = authProviders.includes('google')
  const usesEmailPassword = authProviders.includes('email') || authProviders.length === 0
  const totalPaidCents = billingOrders
    .filter((order) => order.payment_status === 'paid')
    .reduce((sum, order) => sum + Number(order.charged_amount_cents || 0), 0)

  const updatePassword = async (event) => {
    event.preventDefault()
    setPasswordMessage(null)
    if (newPassword.length < 8) {
      setPasswordMessage({ tone: 'error', text: 'Le mot de passe doit contenir au moins 8 caractères.' })
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordMessage({ tone: 'error', text: 'Les deux mots de passe ne correspondent pas.' })
      return
    }
    setPasswordSaving(true)
    try {
      const client = await getSupabaseClient()
      if (!client) throw new Error('Le service d’authentification est indisponible.')
      const { error } = await client.auth.updateUser({ password: newPassword })
      if (error) throw error
      setNewPassword('')
      setConfirmPassword('')
      setPasswordMessage({ tone: 'success', text: 'Votre mot de passe a été modifié.' })
    } catch (error) {
      setPasswordMessage({ tone: 'error', text: error.message || 'Impossible de modifier le mot de passe.' })
    } finally {
      setPasswordSaving(false)
    }
  }

  const deleteAccount = async () => {
    if (deleteConfirmation !== accountName || deletingAccount) return
    setDeletingAccount(true)
    setDeleteError('')
    try {
      const response = await apiFetch('/api/admin/account', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmation: deleteConfirmation }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) throw new Error(data.error || 'Impossible de supprimer le compte.')
      await clearSupabaseSession().catch(() => {})
      localStorage.removeItem('admin_auth_token')
      localStorage.removeItem('auth_token')
      localStorage.removeItem('center_account_email')
      localStorage.removeItem('center_account_name')
      window.location.assign('/connexion-centre')
    } catch (error) {
      setDeleteError(error.message || 'Impossible de supprimer le compte.')
      setDeletingAccount(false)
    }
  }

  const openInvoice = async (orderId) => {
    if (invoiceLoadingId) return
    const invoiceWindow = window.open('about:blank', '_blank')
    if (invoiceWindow) invoiceWindow.opener = null
    setInvoiceLoadingId(orderId)
    setBillingError('')
    try {
      const response = await apiFetch(`/api/hr/billing/orders/${orderId}/invoice`)
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success || !data.url) {
        throw new Error(data.error || 'Facture indisponible.')
      }
      if (invoiceWindow) invoiceWindow.location.assign(data.url)
      else window.location.assign(data.url)
    } catch (error) {
      invoiceWindow?.close()
      setBillingError(error.message || 'Facture indisponible.')
    } finally {
      setInvoiceLoadingId(null)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-[#111827]/45 p-0 md:p-4"
      style={{ fontFamily: 'Inter, system-ui, -apple-system, sans-serif' }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !deletingAccount && !passwordSaving) onClose()
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        className="flex h-dvh w-full overflow-hidden bg-white md:h-[min(760px,calc(100dvh-32px))] md:max-w-[1120px] md:rounded-2xl md:shadow-[0_24px_48px_rgba(15,23,42,0.22)]"
      >
        <aside className="flex w-[230px] shrink-0 flex-col border-r border-[#E2E8F0] bg-[#F8FAFC] px-3 py-4 max-md:w-[92px] max-md:px-2">
          <div className="mb-7 flex items-center gap-3 px-2 max-md:justify-center max-md:px-0">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[#E2E8F0] bg-white text-sm font-semibold text-[#334155]">
              {accountName.slice(0, 1).toUpperCase() || 'C'}
            </span>
            <span className="min-w-0 max-md:hidden">
              <span className="block truncate text-sm font-semibold text-[#0F172A]">{accountName}</span>
              <span className="mt-0.5 block truncate text-xs text-[#64748B]">Espace de travail</span>
            </span>
          </div>
          <nav className="space-y-1" aria-label="Rubriques des paramètres">
            {SETTINGS_TABS.map((tab) => {
              const TabIcon = tab.icon
              const selected = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  aria-current={selected ? 'page' : undefined}
                  className={`flex min-h-11 w-full items-center gap-2.5 rounded-lg px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#475569]/30 max-md:flex-col max-md:justify-center max-md:gap-1 max-md:px-1 max-md:text-[11px] ${selected ? 'bg-white text-[#0F172A] shadow-[inset_0_0_0_1px_#E2E8F0]' : 'text-[#64748B] hover:bg-[#EEF2F6] hover:text-[#0F172A]'}`}
                >
                  <TabIcon size={17} strokeWidth={selected ? 2 : 1.7} aria-hidden="true" />
                  <span>{tab.label}</span>
                </button>
              )
            })}
          </nav>
        </aside>

        <div className="relative min-w-0 flex-1 overflow-y-auto bg-white">
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            className="absolute right-4 top-4 z-10 flex h-10 w-10 items-center justify-center rounded-lg text-[#64748B] transition-colors hover:bg-[#F1F5F9] hover:text-[#0F172A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#475569]/30"
            aria-label="Fermer les paramètres"
          >
            <X size={19} strokeWidth={1.8} aria-hidden="true" />
          </button>

          <div className="mx-auto w-full max-w-[760px] px-5 py-8 sm:px-8 md:px-10 md:py-10">
            {activeTab === 'account' ? (
              <div>
                <header className="pr-12">
                  <h2 id="settings-title" className="text-2xl font-semibold tracking-[-0.01em] text-[#0F172A]">Compte</h2>
                  <p className="mt-1.5 text-sm text-[#475569]">Sécurité et gestion de votre compte centre.</p>
                </header>

                <section className="mt-8">
                  <h3 className="text-sm font-semibold text-[#334155]">Méthode de connexion</h3>
                  <div className="mt-3 rounded-xl border border-[#E2E8F0]">
                    <div className="flex min-h-[76px] items-center gap-3 px-4 py-3">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#F1F5F9] text-[#475569]">
                        {usesGoogle ? <span className="text-base font-semibold text-[#4285F4]">G</span> : <Mail size={18} strokeWidth={1.7} aria-hidden="true" />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[#0F172A]">
                          {authLoading ? 'Vérification…' : usesGoogle ? 'Google' : 'Email et mot de passe'}
                          {!authLoading && <span className="rounded-full bg-[#ECFDF3] px-2 py-0.5 text-[11px] font-medium text-[#027A48]">Lié</span>}
                        </span>
                        <span className="mt-1 block truncate text-sm text-[#64748B]">{accountEmail}</span>
                      </span>
                    </div>
                  </div>
                </section>

                <section className="mt-8">
                  <h3 className="text-sm font-semibold text-[#334155]">Mot de passe</h3>
                  {usesGoogle && !usesEmailPassword ? (
                    <div className="mt-3 rounded-xl bg-[#F8FAFC] px-4 py-4 text-sm leading-6 text-[#475569]">
                      Votre connexion est gérée par Google. Modifiez votre mot de passe depuis votre compte Google.
                    </div>
                  ) : (
                    <form onSubmit={updatePassword} className="mt-3 rounded-xl border border-[#E2E8F0] p-4 sm:p-5">
                      <div className="grid gap-4 sm:grid-cols-2">
                        <label className="text-sm font-medium text-[#334155]">
                          Nouveau mot de passe
                          <input
                            type="password"
                            autoComplete="new-password"
                            value={newPassword}
                            onChange={(event) => setNewPassword(event.target.value)}
                            className="mt-2 h-11 w-full rounded-lg border border-[#CBD5E1] bg-white px-3 text-sm text-[#0F172A] outline-none transition focus:border-[#64748B] focus:ring-2 focus:ring-[#64748B]/15"
                            placeholder="8 caractères minimum"
                          />
                        </label>
                        <label className="text-sm font-medium text-[#334155]">
                          Confirmer le mot de passe
                          <input
                            type="password"
                            autoComplete="new-password"
                            value={confirmPassword}
                            onChange={(event) => setConfirmPassword(event.target.value)}
                            className="mt-2 h-11 w-full rounded-lg border border-[#CBD5E1] bg-white px-3 text-sm text-[#0F172A] outline-none transition focus:border-[#64748B] focus:ring-2 focus:ring-[#64748B]/15"
                            placeholder="Saisissez-le à nouveau"
                          />
                        </label>
                      </div>
                      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                        {passwordMessage ? (
                          <p className={`text-sm ${passwordMessage.tone === 'success' ? 'text-[#027A48]' : 'text-[#B42318]'}`} role="status">
                            {passwordMessage.text}
                          </p>
                        ) : <p className="text-xs text-[#64748B]">Utilisez un mot de passe unique.</p>}
                        <button
                          type="submit"
                          disabled={passwordSaving || !newPassword || !confirmPassword}
                          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-[#0F172A] px-4 text-sm font-medium text-white transition-colors hover:bg-[#1E293B] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#475569]/35 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-45"
                        >
                          <KeyRound size={16} strokeWidth={1.8} aria-hidden="true" />
                          {passwordSaving ? 'Modification…' : 'Modifier le mot de passe'}
                        </button>
                      </div>
                    </form>
                  )}
                </section>

                <section className="mt-10 border-t border-[#E2E8F0] pt-8">
                  <h3 className="text-sm font-semibold text-[#B42318]">Zone dangereuse</h3>
                  <div className="mt-3 rounded-xl border border-[#FECDCA] bg-[#FFF7F6] p-4 sm:flex sm:items-center sm:justify-between sm:gap-5">
                    <div>
                      <p className="text-sm font-semibold text-[#7A271A]">Supprimer le compte</p>
                      <p className="mt-1 max-w-[56ch] text-sm leading-5 text-[#912018]">Cette action supprime l’espace centre, ses professeurs, ses formations et ses données. Elle est irréversible.</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setShowDeleteConfirmation(true)}
                      className="mt-4 inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg border border-[#FDA29B] bg-white px-4 text-sm font-medium text-[#B42318] transition-colors hover:bg-[#FFF1F0] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#D92D20]/30 sm:mt-0"
                    >
                      <Trash2 size={16} strokeWidth={1.8} aria-hidden="true" />
                      Supprimer le compte
                    </button>
                  </div>
                </section>
              </div>
            ) : (
              <div>
                <header className="pr-12">
                  <h2 id="settings-title" className="text-2xl font-semibold tracking-[-0.01em] text-[#0F172A]">Facturation</h2>
                  <p className="mt-1.5 text-sm text-[#475569]">Suivez vos dépenses et téléchargez les documents associés.</p>
                </header>

                <section className="mt-8 border-y border-[#E2E8F0] py-4">
                  <div className="flex flex-wrap items-end justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-[#475569]">Total payé</p>
                      <p className="mt-1 text-2xl font-semibold tracking-[-0.01em] text-[#0F172A]">{formatPrice(totalPaidCents, 'eur')}</p>
                    </div>
                    <p className="text-sm text-[#64748B]">{billingOrders.length} opération{billingOrders.length > 1 ? 's' : ''}</p>
                  </div>
                </section>

                <section className="mt-8">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="text-sm font-semibold text-[#334155]">Historique des dépenses</h3>
                    <span className="text-xs text-[#64748B]">Factures Stripe</span>
                  </div>

                  {billingHistoryLoading ? (
                    <div className="mt-3 space-y-2" aria-label="Chargement des dépenses">
                      {[0, 1, 2].map((item) => <div key={item} className="h-[74px] animate-pulse rounded-xl bg-[#F1F5F9]" />)}
                    </div>
                  ) : billingOrders.length === 0 ? (
                    <div className="mt-3 flex min-h-[190px] flex-col items-center justify-center rounded-xl border border-dashed border-[#CBD5E1] px-5 text-center">
                      <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-[#F1F5F9] text-[#64748B]"><ReceiptText size={19} strokeWidth={1.7} aria-hidden="true" /></span>
                      <p className="mt-4 text-sm font-semibold text-[#334155]">Aucune dépense à ce jour</p>
                      <p className="mt-1 max-w-[44ch] text-sm leading-5 text-[#64748B]">Les paiements apparaîtront ici après votre première commande.</p>
                    </div>
                  ) : (
                    <div className="mt-3 overflow-hidden rounded-xl border border-[#E2E8F0]">
                      {billingOrders.map((order, index) => (
                        <div key={order.id} className={`flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center ${index > 0 ? 'border-t border-[#E2E8F0]' : ''}`}>
                          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#F1F5F9] text-[#475569] max-sm:hidden">
                            <ReceiptText size={18} strokeWidth={1.7} aria-hidden="true" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-semibold text-[#0F172A]">{order.training_title || BILLING_OPERATION_LABELS[order.operation_type] || 'Commande'}</span>
                            <span className="mt-1 block text-xs text-[#64748B]">{BILLING_OPERATION_LABELS[order.operation_type] || 'Service'} · {formatBillingDate(order.paid_at || order.created_at)}</span>
                          </span>
                          <span className="flex items-center justify-between gap-4 sm:justify-end">
                            <span className="text-sm font-semibold text-[#0F172A]">{formatPrice(Number(order.charged_amount_cents || 0), order.currency || 'eur')}</span>
                            {order.payment_status === 'refunded' ? (
                              <span className="rounded-full bg-[#FFF7ED] px-2.5 py-1 text-xs font-medium text-[#9A3412]">Remboursé</span>
                            ) : (
                              <button
                                type="button"
                                onClick={() => openInvoice(order.id)}
                                disabled={invoiceLoadingId === order.id}
                                className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-[#CBD5E1] bg-white px-3 text-xs font-medium text-[#334155] transition-colors hover:bg-[#F8FAFC] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#475569]/30 disabled:opacity-55"
                              >
                                {invoiceLoadingId === order.id ? 'Ouverture…' : 'Facture'}
                                <ExternalLink size={13} strokeWidth={1.8} aria-hidden="true" />
                              </button>
                            )}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  {billingError && billingOrders.length > 0 && <p className="mt-3 text-sm text-[#B42318]" role="alert">{billingError}</p>}
                </section>
              </div>
            )}
          </div>
        </div>
      </section>

      {showDeleteConfirmation && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-[#0F172A]/50 p-4">
          <section role="alertdialog" aria-modal="true" aria-labelledby="delete-account-title" className="w-full max-w-[460px] rounded-2xl bg-white p-6 shadow-[0_24px_48px_rgba(15,23,42,0.25)]">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 id="delete-account-title" className="text-lg font-semibold text-[#7A271A]">Supprimer définitivement le compte ?</h3>
                <p className="mt-2 text-sm leading-6 text-[#475569]">Saisissez <strong className="font-semibold text-[#0F172A]">{accountName}</strong> pour confirmer la suppression de toutes les données du centre.</p>
              </div>
              <button type="button" onClick={() => setShowDeleteConfirmation(false)} disabled={deletingAccount} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F1F5F9] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8B5CF6]/40" aria-label="Annuler la suppression"><X size={18} aria-hidden="true" /></button>
            </div>
            <label className="mt-5 block text-sm font-medium text-[#334155]">
              Nom du centre
              <input
                type="text"
                value={deleteConfirmation}
                onChange={(event) => setDeleteConfirmation(event.target.value)}
                autoFocus
                className="mt-2 h-11 w-full rounded-lg border border-[#FDA29B] px-3 text-sm text-[#0F172A] outline-none focus:border-[#D92D20] focus:ring-2 focus:ring-[#D92D20]/15"
              />
            </label>
            {deleteError && <p className="mt-3 text-sm text-[#B42318]" role="alert">{deleteError}</p>}
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setShowDeleteConfirmation(false)} disabled={deletingAccount} className="min-h-11 rounded-lg border border-[#CBD5E1] px-4 text-sm font-medium text-[#334155] hover:bg-[#F8FAFC] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8B5CF6]/35 disabled:opacity-50">Annuler</button>
              <button type="button" onClick={deleteAccount} disabled={deleteConfirmation !== accountName || deletingAccount} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-[#D92D20] px-4 text-sm font-medium text-white hover:bg-[#B42318] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#D92D20]/35 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-45"><Trash2 size={16} aria-hidden="true" />{deletingAccount ? 'Suppression…' : 'Supprimer définitivement'}</button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

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

const RECRUITMENT_CHOICE_TYPES = new Set(['confirm', 'frequency', 'days'])
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
    const title = draft.trainingName || matchingModule?.tp_name
    const code = draft.rncpCode || matchingModule?.rncp_code
    return `Le code RNCP ${String(code).replace(/\D/g, '')} correspond au titre professionnel « ${title} ». Est-ce bien ce titre que vous souhaitez dispenser ?`
  }
  if (step.id === 'weeklyCourseCount') return 'Choisissons maintenant le rythme hebdomadaire habituel de la formation. Pour l’instant, indiquez simplement un nombre moyen de jours par semaine. Ne vous inquiétez pas si certaines semaines diffèrent : même si vous choisissez deux jours, une semaine pourra n’en compter qu’un et la suivante trois. Vous pourrez ajuster précisément le calendrier plus tard.'
  if (step.id === 'teachingDays') return 'Choisissez maintenant les jours habituels de formation, ceux qui s’appliqueront pendant la majorité du parcours. Ne vous inquiétez pas pour les semaines particulières : en cas de jour férié ou d’exception, vous pourrez déplacer les séances sur d’autres jours lorsque vous préciserez le calendrier.'
  if (step.id === 'startDate') return 'Quand débutera la formation ?'
  return step.question
}

function ManualRecruitmentForm({ colors, onBack, onComplete }) {
  const earliestStartDate = getMinimumNewModuleStartDate()
  const [form, setForm] = useState({
    rncpCode: '',
    startDate: earliestStartDate,
    weeklyCourseCount: 2,
    trainingWeeks: 3,
    teachingDays: ['mardi', 'jeudi'],
    teacherName: '',
  })
  const [rncpResult, setRncpResult] = useState({
    status: 'idle',
    certification: null,
    message: '',
  })
  const [inactiveInfoOpen, setInactiveInfoOpen] = useState(false)
  const [startDateInfoOpen, setStartDateInfoOpen] = useState(false)
  const startDateInfoRef = useRef(null)
  const startDateInfoButtonRef = useRef(null)
  const lookupVersionRef = useRef(0)

  useEffect(() => {
    const code = String(form.rncpCode || '').replace(/\D/g, '')
    setInactiveInfoOpen(false)
    lookupVersionRef.current += 1
    const lookupVersion = lookupVersionRef.current

    if (!/^\d{4,6}$/.test(code)) {
      setRncpResult({ status: 'idle', certification: null, message: '' })
      return undefined
    }

    setRncpResult({ status: 'loading', certification: null, message: '' })
    const timeoutId = window.setTimeout(async () => {
      try {
        const response = await apiFetch(`/api/hr/recruitment/rncp/${encodeURIComponent(code)}`, {
          timeoutMs: 25000,
        })
        const payload = await response.json().catch(() => ({}))
        if (lookupVersion !== lookupVersionRef.current) return

        if (!response.ok || !payload.success) {
          setRncpResult({
            status: 'error',
            certification: null,
            message: payload.error || 'Impossible de vérifier ce code RNCP pour le moment.',
          })
          return
        }

        const certification = payload.certification
        if (!certification?.active) {
          setRncpResult({
            status: 'inactive',
            certification: { ...certification, reac_available: payload.available },
            message: '',
          })
          return
        }

        if (!payload.available) {
          setRncpResult({
            status: 'unavailable',
            certification,
            message: payload.reply || 'Le référentiel nécessaire à cette formation n’est pas disponible.',
          })
          return
        }

        setRncpResult({ status: 'valid', certification, message: '' })
      } catch {
        if (lookupVersion !== lookupVersionRef.current) return
        setRncpResult({
          status: 'error',
          certification: null,
          message: 'France Compétences est temporairement inaccessible. Réessayez dans quelques instants.',
        })
      }
    }, 450)

    return () => window.clearTimeout(timeoutId)
  }, [form.rncpCode])

  useEffect(() => {
    if (!inactiveInfoOpen) return undefined

    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setInactiveInfoOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [inactiveInfoOpen])

  useEffect(() => {
    if (!startDateInfoOpen) return undefined

    const closeStartDateInfo = (event) => {
      if (event.type === 'keydown' && event.key === 'Escape') {
        setStartDateInfoOpen(false)
        startDateInfoButtonRef.current?.focus()
        return
      }
      if (event.type === 'pointerdown' && !startDateInfoRef.current?.contains(event.target)) {
        setStartDateInfoOpen(false)
      }
    }

    window.addEventListener('keydown', closeStartDateInfo)
    document.addEventListener('pointerdown', closeStartDateInfo)
    return () => {
      window.removeEventListener('keydown', closeStartDateInfo)
      document.removeEventListener('pointerdown', closeStartDateInfo)
    }
  }, [startDateInfoOpen])

  const updateWeeklyCourseCount = (value) => {
    const weeklyCourseCount = Number(value)
    setForm((current) => {
      const teachingDays = current.teachingDays.slice(0, weeklyCourseCount)
      for (const option of RECRUITMENT_DAY_OPTIONS) {
        if (teachingDays.length >= weeklyCourseCount) break
        if (!teachingDays.includes(option.id)) teachingDays.push(option.id)
      }
      return { ...current, weeklyCourseCount, teachingDays }
    })
  }

  const toggleManualDay = (day) => {
    setForm((current) => {
      const selected = current.teachingDays.includes(day)
      const teachingDays = selected
        ? current.teachingDays.filter((item) => item !== day)
        : current.teachingDays.length < Number(current.weeklyCourseCount)
          ? [...current.teachingDays, day]
          : current.teachingDays
      return { ...current, teachingDays }
    })
  }

  const certificationIsConfirmed = ['valid', 'validInactive'].includes(rncpResult.status)
  const weeklyDaysAreComplete = form.teachingDays.length === Number(form.weeklyCourseCount)
  const canContinue = Boolean(
    certificationIsConfirmed
    && form.startDate >= earliestStartDate
    && Number(form.trainingWeeks) >= 1
    && weeklyDaysAreComplete
    && form.teacherName.trim(),
  )

  const submitManualRecruitment = (event) => {
    event.preventDefault()
    if (!canContinue) return
    const certification = rncpResult.certification
    onComplete({
      teacherName: form.teacherName.trim(),
      trainingName: certification.title,
      rncpCode: String(certification.rncp_code || form.rncpCode).replace(/\D/g, ''),
      trainingWeeks: Number(form.trainingWeeks),
      weeklyCourseCount: Number(form.weeklyCourseCount),
      trainingDays: calculateTrainingDays(form.trainingWeeks, form.weeklyCourseCount),
      teachingDays: form.teachingDays,
      startDate: form.startDate,
      teacherColor: 'violet',
    })
  }

  const certification = rncpResult.certification
  const replacements = Array.isArray(certification?.replacement_certifications)
    ? certification.replacement_certifications
    : []
  const fieldClassName = 'mt-2 h-11 w-full rounded-lg border border-[#D7D9DD] bg-white px-3.5 text-sm text-[#191918] outline-none transition-[border-color,box-shadow] placeholder:text-[#73736F] focus:border-[#097FE8] focus:ring-2 focus:ring-[#097FE8]/15'

  return (
    <>
      <section className="manual-recruitment-enter mx-auto flex min-h-0 w-full max-w-5xl flex-1 flex-col" aria-labelledby="manual-recruitment-title">
      <header className="flex min-h-14 shrink-0 items-center gap-3 border-b" style={{ borderColor: colors.borderLight }}>
        <button type="button" onClick={onBack} className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-[#5F5E5A] transition-colors hover:bg-[#F1F1EF] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/45" aria-label="Revenir au recrutement conversationnel">
          <ChevronLeft size={20} strokeWidth={1.8} aria-hidden="true" />
        </button>
        <div>
          <h1 id="manual-recruitment-title" className="text-sm font-semibold" style={{ color: colors.text }}>Configurer le professeur</h1>
        </div>
      </header>

      <div className={`rncp-form-content min-h-0 flex-1 overflow-y-auto ${inactiveInfoOpen ? 'rncp-form-content--shifted' : ''}`} style={{ scrollbarGutter: 'stable' }}>
        <form onSubmit={submitManualRecruitment} className="manual-recruitment-form mx-auto w-full max-w-3xl py-8 sm:py-10">
          <div className="mb-8">
            <h2 className="text-2xl font-semibold tracking-[-0.02em] text-[#191918]">Informations de la formation</h2>
            <p className="mt-2 max-w-[68ch] text-sm leading-6 text-[#5F5E5A]">Renseignez les éléments nécessaires pour préparer automatiquement les premières dates du calendrier.</p>
          </div>

          <div className="space-y-7">
            <div>
              <label htmlFor="manual-rncp-code" className="text-sm font-medium text-[#2C2C2A]">Code RNCP</label>
              <div className={`mt-2 grid items-start ${rncpResult.status === 'inactive' ? 'grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]' : 'gap-3 sm:grid-cols-2'}`}>
                <div>
                  <input
                    id="manual-rncp-code"
                    type="text"
                    inputMode="numeric"
                    value={form.rncpCode}
                    onChange={(event) => setForm((current) => ({
                      ...current,
                      rncpCode: event.target.value.replace(/\D/g, '').slice(0, 6),
                    }))}
                    placeholder="Ex. 37099"
                    className="h-11 w-full rounded-lg border border-[#D7D9DD] bg-white px-3.5 text-sm text-[#191918] outline-none transition-[border-color,box-shadow] placeholder:text-[#73736F] focus:border-[#097FE8] focus:ring-2 focus:ring-[#097FE8]/15"
                    aria-describedby="manual-rncp-status"
                    autoFocus
                  />
                  {form.rncpCode && form.rncpCode.length < 4 && <p className="mt-1.5 text-xs text-[#68625B]">Saisissez entre 4 et 6 chiffres.</p>}
                </div>

                <div id="manual-rncp-status" className={rncpResult.status === 'idle' ? 'hidden' : 'min-h-11'} aria-live="polite">
                  {rncpResult.status === 'loading' && (
                    <div className="flex min-h-11 items-center gap-2 rounded-lg bg-[#F5F5F3] px-3.5 text-sm text-[#5F5E5A]">
                      <span className="recruitment-thinking-dot h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
                      Vérification auprès de France Compétences…
                    </div>
                  )}
                  {rncpResult.status === 'valid' && (
                    <div className="flex h-11 min-w-0 items-center rounded-lg bg-[#EAF7EF] px-3.5 text-sm text-[#17633A]">
                      <p className="flex min-w-0 items-center gap-2">
                        <Icon name="check_circle" className="shrink-0 text-base" />
                        <span className="shrink-0 font-semibold">Code RNCP valide</span>
                        <span aria-hidden="true">·</span>
                        <span className="truncate text-[#24583B]" title={certification.title}>{certification.title}</span>
                      </p>
                    </div>
                  )}
                  {rncpResult.status === 'validInactive' && (
                    <div className="flex h-11 min-w-0 items-center rounded-lg bg-[#FFF4D6] px-3.5 text-sm text-[#755600]">
                      <p className="flex min-w-0 items-center gap-2">
                        <Icon name="check_circle" className="shrink-0 text-base" />
                        <span className="shrink-0 font-semibold">Fiche inactive conservée</span>
                        <span aria-hidden="true">·</span>
                        <span className="truncate" title={certification.title}>{certification.title}</span>
                      </p>
                    </div>
                  )}
                  {['error', 'unavailable'].includes(rncpResult.status) && (
                    <div className="rounded-lg bg-[#FDECEC] px-3.5 py-2.5 text-sm leading-5 text-[#9F2D2D]" role="alert">{rncpResult.message}</div>
                  )}
                  {rncpResult.status === 'inactive' && (
                    <div className="flex h-11 items-center">
                      <button
                        type="button"
                        onClick={() => setInactiveInfoOpen((open) => !open)}
                        aria-expanded={inactiveInfoOpen}
                        aria-controls="manual-rncp-update-details"
                        aria-label="Afficher les informations sur la mise à jour RNCP"
                        className="inline-flex h-11 w-7 items-center justify-center text-xl font-bold leading-none text-[#EA580C] transition-colors hover:text-[#C2410C] focus-visible:outline-none focus-visible:underline focus-visible:decoration-2 focus-visible:underline-offset-4"
                      >
                        <span aria-hidden="true">!</span>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="grid gap-5 sm:grid-cols-2">
              <div className="text-sm font-medium text-[#2C2C2A]">
                <div
                  ref={startDateInfoRef}
                  className="relative flex items-center gap-1.5"
                  onBlur={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget)) setStartDateInfoOpen(false)
                  }}
                >
                  <label htmlFor="manual-start-date">Date de début</label>
                  <button
                    ref={startDateInfoButtonRef}
                    type="button"
                    className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-[#B9BDC5] text-[#626773] outline-none transition-colors hover:border-[#191918] hover:text-[#191918] focus-visible:border-[#191918] focus-visible:text-[#191918] focus-visible:ring-2 focus-visible:ring-[#191918]/20"
                    onClick={() => setStartDateInfoOpen((open) => !open)}
                    aria-label="Informations sur la date de début"
                    aria-expanded={startDateInfoOpen}
                    aria-controls="manual-start-date-help"
                  >
                    <Info size={13} aria-hidden="true" />
                  </button>
                  {startDateInfoOpen && (
                    <div
                      id="manual-start-date-help"
                      role="tooltip"
                      className="absolute left-0 top-[calc(100%+8px)] z-30 w-72 max-w-[calc(100vw-3rem)] rounded-lg bg-[#191918] px-3 py-2.5 text-xs font-normal leading-5 text-white shadow-[0_4px_8px_rgba(25,25,24,0.18)]"
                    >
                      La formation peut débuter au plus tôt demain. Le délai minimal de 24 heures sera vérifié selon l’heure du premier cours définie dans le planning.
                    </div>
                  )}
                </div>
                <input id="manual-start-date" type="date" min={earliestStartDate} value={form.startDate} onChange={(event) => setForm((current) => ({ ...current, startDate: event.target.value }))} className={fieldClassName} />
              </div>
              <label className="text-sm font-medium text-[#2C2C2A]" htmlFor="manual-training-weeks">
                Durée de la formation
                <div className="relative">
                  <input id="manual-training-weeks" type="number" min="1" max="104" value={form.trainingWeeks} onChange={(event) => setForm((current) => ({ ...current, trainingWeeks: event.target.value }))} className={`${fieldClassName} pr-24`} />
                  <span className="pointer-events-none absolute bottom-3 right-3 text-sm text-[#68625B]">semaines</span>
                </div>
              </label>
            </div>

            <div>
              <label className="text-sm font-medium text-[#2C2C2A]" htmlFor="manual-weekly-count">Rythme hebdomadaire</label>
              <select id="manual-weekly-count" value={form.weeklyCourseCount} onChange={(event) => updateWeeklyCourseCount(event.target.value)} className={`${fieldClassName} block sm:max-w-xs`}>
                {[1, 2, 3, 4, 5].map((count) => <option key={count} value={count}>{count} journée{count > 1 ? 's' : ''} par semaine</option>)}
              </select>
            </div>

            <fieldset>
              <legend className="text-sm font-medium text-[#2C2C2A]">Jours habituels de formation</legend>
              <p className="mt-1 text-xs leading-5 text-[#68625B]">Choisissez exactement {form.weeklyCourseCount} jour{Number(form.weeklyCourseCount) > 1 ? 's' : ''}. Vous pourrez déplacer les exceptions dans le planning.</p>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                {RECRUITMENT_DAY_OPTIONS.map((day) => {
                  const selected = form.teachingDays.includes(day.id)
                  return (
                    <button key={day.id} type="button" onClick={() => toggleManualDay(day.id)} aria-pressed={selected} className={`min-h-11 rounded-lg border px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#191918]/40 ${selected ? 'border-[#191918] bg-[#191918] text-white' : 'border-[#D7D9DD] bg-white text-[#3F3F3C] hover:bg-[#F5F5F3]'}`}>
                      {day.label}
                    </button>
                  )
                })}
              </div>
              {!weeklyDaysAreComplete && <p className="mt-2 text-xs font-medium text-[#9F2D2D]" role="status">Sélectionnez encore {Number(form.weeklyCourseCount) - form.teachingDays.length} jour.</p>}
            </fieldset>

            <label className="block text-sm font-medium text-[#2C2C2A]" htmlFor="manual-teacher-name">
              Nom du professeur IA
              <input id="manual-teacher-name" type="text" value={form.teacherName} onChange={(event) => setForm((current) => ({ ...current, teacherName: event.target.value }))} placeholder="Ex. Pierre" className={fieldClassName} />
            </label>
          </div>

          <footer className="mt-10 flex flex-col-reverse gap-3 border-t pt-5 sm:flex-row sm:items-center sm:justify-between" style={{ borderColor: colors.borderLight }}>
            <button type="button" onClick={onBack} className="min-h-11 rounded-lg px-4 text-sm font-medium text-[#5F5E5A] transition-colors hover:bg-[#F1F1EF] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#191918]/30">Retour au chat</button>
            <button type="submit" disabled={!canContinue} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-[#191918] px-5 text-sm font-semibold text-white transition-colors hover:bg-[#30302E] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#191918]/45 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-[#C7C7C4]">
              Configurer le planning
              <Icon name="arrow_forward" className="text-base" />
            </button>
          </footer>
        </form>
        </div>
      </section>

      {rncpResult.status === 'inactive' && inactiveInfoOpen && typeof document !== 'undefined' && createPortal(
        <>
          <button type="button" className="fixed inset-0 z-40 cursor-default bg-transparent" onClick={() => setInactiveInfoOpen(false)} aria-label="Fermer le panneau RNCP" />
          <aside id="manual-rncp-update-details" className="rncp-side-panel-enter fixed inset-y-0 right-0 z-50 flex w-full max-w-[420px] flex-col border-l border-[#DEDCD8] bg-white text-sm text-[#2C2C2A] shadow-[-16px_0_40px_rgba(25,25,24,0.08)]" role="dialog" aria-modal="false" aria-labelledby="manual-rncp-update-title">
            <header className="flex items-start justify-between gap-4 px-5 py-[13px]">
              <div className="min-w-0">
                <p className="mb-1 text-xs font-medium uppercase tracking-[0.08em] text-[#EA580C]">Code RNCP</p>
                <h2 id="manual-rncp-update-title" className="text-lg font-semibold tracking-[-0.01em] text-[#191918]">Certification mise à jour</h2>
              </div>
              <button type="button" onClick={() => setInactiveInfoOpen(false)} className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#73736F] transition-colors hover:bg-[#F1F1EF] hover:text-[#191918] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#191918]/30" aria-label="Fermer les informations RNCP">
                <X size={18} strokeWidth={1.8} aria-hidden="true" />
              </button>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6">
              {replacements.length === 1 ? (
                <>
                  <p className="leading-6 text-[#5F5E5A]">Le titre professionnel enregistré sous le code RNCP {certification.rncp_code} a été remplacé par la nouvelle certification RNCP {replacements[0].rncp_code}.</p>
                  {certification.reac_available && <p className="mt-4 font-medium leading-6 text-[#2C2C2A]">Souhaitez-vous conserver le titre RNCP {certification.rncp_code} ou utiliser le titre RNCP {replacements[0].rncp_code} ?</p>}
                </>
              ) : (
                <>
                  <p className="leading-6 text-[#5F5E5A]">
                    Le titre RNCP {certification.rncp_code}
                    {replacements.length > 1
                      ? ' a été remplacé par plusieurs certifications plus récentes.'
                      : ' ne dispose d’aucune certification de remplacement référencée.'}
                  </p>
                  {replacements.length > 1 && certification.reac_available && <p className="mt-4 font-medium leading-6 text-[#2C2C2A]">Souhaitez-vous conserver le titre RNCP {certification.rncp_code} ou utiliser l’une de ses certifications de remplacement ?</p>}
                </>
              )}
            </div>

            <footer className="grid gap-2 border-t border-[#E8E7E4] p-5">
              {replacements.map((replacement) => (
                <button key={replacement.rncp_code} type="button" onClick={() => { setInactiveInfoOpen(false); setForm((current) => ({ ...current, rncpCode: String(replacement.rncp_code).replace(/\D/g, '') })) }} className="min-h-12 rounded-lg bg-[#191918] px-3.5 py-2.5 text-left text-sm font-medium text-white transition-colors hover:bg-[#30302E] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#191918]/40 focus-visible:ring-offset-2">
                  <span className="mb-0.5 block text-[11px] font-normal text-white/60">Certification actuelle</span>
                  <span className="block">Utiliser RNCP {replacement.rncp_code}</span>
                </button>
              ))}
              {certification.reac_available && (
                <button type="button" onClick={() => { setRncpResult((current) => ({ ...current, status: 'validInactive' })); setInactiveInfoOpen(false) }} className="min-h-12 rounded-lg border border-[#CFCFCB] bg-white px-3.5 py-2.5 text-left text-sm font-medium text-[#2C2C2A] transition-colors hover:border-[#A8A8A3] hover:bg-[#F7F7F5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#191918]/30">
                  <span className="mb-0.5 block text-[11px] font-normal text-[#73736F]">Ancienne certification</span>
                  <span className="block">Conserver RNCP {certification.rncp_code}</span>
                </button>
              )}
              {!certification.reac_available && replacements.length === 0 && <p className="text-xs leading-5">Cette fiche ne peut pas être utilisée. Saisissez un autre code RNCP.</p>}
            </footer>
          </aside>
        </>,
        document.body,
      )}
    </>
  )
}

function RecruitmentAssistant({
  colors,
  modules,
  onComplete,
  hasSavedDraft = false,
  onResumeDraft,
  onManualStart,
}) {
  const [manualMode, setManualMode] = useState(false)
  const [started, setStarted] = useState(false)
  const [brief, setBrief] = useState('')
  const [stepIndex, setStepIndex] = useState(0)
  const [answer, setAnswer] = useState('')
  const [draft, setDraft] = useState({
    teacherName: '',
    trainingName: '',
    rncpCode: '',
    trainingDays: '',
    trainingWeeks: '',
    weeklyCourseCount: 2,
    teachingDays: ['mardi', 'jeudi'],
    startDate: getMinimumNewModuleStartDate(),
    teacherColor: 'violet',
  })
  const [history, setHistory] = useState([])
  const [isThinking, setIsThinking] = useState(false)
  const [pendingConfirmation, setPendingConfirmation] = useState(null)
  const [pendingRncpDecision, setPendingRncpDecision] = useState(null)
  const [clarificationAttempts, setClarificationAttempts] = useState({})
  const chatScrollRef = useRef(null)
  const responseStreamRef = useRef({ timeoutId: null, intervalId: null })
  const responseMessageIdRef = useRef(0)
  const [streamingMessageId, setStreamingMessageId] = useState(null)
  const prefersReducedMotionRef = useRef(
    typeof window !== 'undefined'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  const animatedPlaceholder = useAnimatedPlaceholder(RECRUITMENT_PLACEHOLDER_EXAMPLES)
  const currentStep = RECRUITMENT_STEPS[stepIndex]
  const matchingModule = modules.find((module) => String(module.rncp_code || '').replace(/\D/g, '') === String(draft.rncpCode || '').replace(/\D/g, ''))
  const completed = stepIndex >= RECRUITMENT_STEPS.length
  const currentIsChoice = Boolean(currentStep && RECRUITMENT_CHOICE_TYPES.has(currentStep.type))

  const clearResponseStream = () => {
    window.clearTimeout(responseStreamRef.current.timeoutId)
    window.clearInterval(responseStreamRef.current.intervalId)
    responseStreamRef.current = { timeoutId: null, intervalId: null }
  }

  useEffect(() => () => clearResponseStream(), [])

  useEffect(() => {
    const scrollArea = chatScrollRef.current
    if (!scrollArea) return
    const frameId = window.requestAnimationFrame(() => {
      scrollArea.scrollTo({
        top: scrollArea.scrollHeight,
        behavior: prefersReducedMotionRef.current ? 'auto' : 'smooth',
      })
    })
    return () => window.cancelAnimationFrame(frameId)
  }, [history, isThinking, stepIndex])

  const revealAssistantMessages = (messages) => {
    clearResponseStream()
    setStreamingMessageId(null)
    setIsThinking(true)

    if (prefersReducedMotionRef.current) {
      setHistory((current) => [...current, ...messages])
      setIsThinking(false)
      return
    }

    let messageIndex = 0
    const revealNextMessage = () => {
      if (messageIndex >= messages.length) {
        setStreamingMessageId(null)
        setIsThinking(false)
        return
      }

      const message = messages[messageIndex]
      messageIndex += 1

      if (message.role !== 'assistant') {
        setHistory((current) => [...current, message])
        revealNextMessage()
        return
      }

      const messageId = `recruitment-assistant-${responseMessageIdRef.current + 1}`
      responseMessageIdRef.current += 1
      const fullText = String(message.text || '')
      const textChunks = fullText.match(/\S+\s*/g) || [fullText]
      const chunkSize = Math.max(1, Math.ceil(textChunks.length / 28))
      let revealedChunkCount = 0

      setStreamingMessageId(messageId)
      setHistory((current) => [...current, { ...message, id: messageId, text: '' }])

      const finishMessage = () => {
        window.clearInterval(responseStreamRef.current.intervalId)
        responseStreamRef.current.intervalId = null
        setHistory((current) => current.map((item) => (
          item.id === messageId ? { ...item, text: fullText } : item
        )))
        responseStreamRef.current.timeoutId = window.setTimeout(revealNextMessage, 90)
      }

      responseStreamRef.current.timeoutId = window.setTimeout(() => {
        responseStreamRef.current.timeoutId = null
        responseStreamRef.current.intervalId = window.setInterval(() => {
          revealedChunkCount = Math.min(textChunks.length, revealedChunkCount + chunkSize)
          setHistory((current) => current.map((item) => (
            item.id === messageId
              ? { ...item, text: textChunks.slice(0, revealedChunkCount).join('') }
              : item
          )))
          if (revealedChunkCount >= textChunks.length) finishMessage()
        }, 32)
      }, 180)
    }

    revealNextMessage()
  }

  const displayAnswer = (step, value) => {
    if (step.id === 'teachingDays') return value.map((day) => RECRUITMENT_DAY_OPTIONS.find((option) => option.id === day)?.label || day).join(', ')
    if (step.id === 'weeklyCourseCount') return `${value} jour${Number(value) > 1 ? 's' : ''} par semaine`
    if (step.id === 'trainingDays') return `${value} journées`
    if (step.id === 'trainingWeeks') return `${value} semaine${Number(value) > 1 ? 's' : ''}`
    if (step.id === 'rncpCode') return `RNCP ${String(value).replace(/\D/g, '')}`
    return String(value)
  }

  const advance = (
    value,
    {
      recordUser = true,
      verifiedCertification = null,
      skipRncpConfirmation = false,
    } = {},
  ) => {
    if (!currentStep) return
    if (currentStep.id === 'startDate' && String(value || '') < getMinimumNewModuleStartDate()) {
      revealAssistantMessages([{
        role: 'assistant',
        text: `La formation peut commencer au plus tôt le ${new Intl.DateTimeFormat('fr-FR').format(new Date(`${getMinimumNewModuleStartDate()}T12:00:00`))}. Choisissez une date à partir de ce jour.`,
      }])
      return
    }
    if (currentStep.id === 'rncpConfirm' && value === 'Corriger') {
      const correctedDraft = { ...draft, trainingName: '', rncpCode: '' }
      setDraft(correctedDraft)
      setHistory((current) => [...current, { role: 'user', text: value }])
      setStepIndex(RECRUITMENT_STEPS.findIndex((step) => step.id === 'rncpCode'))
      setAnswer('')
      revealAssistantMessages([
        { role: 'assistant', text: 'D’accord. Quel est le code RNCP du titre professionnel que vous souhaitez dispenser ?' },
      ])
      return
    }
    const normalizedValue = currentStep.id === 'rncpCode' ? String(value).replace(/\D/g, '') : value
    let nextDraft = currentStep.id === 'rncpConfirm'
      ? draft
      : { ...draft, [currentStep.id]: normalizedValue }
    if (currentStep.id === 'rncpCode') {
      nextDraft = {
        ...nextDraft,
        trainingName: verifiedCertification?.title || nextDraft.trainingName,
      }
    }
    if (currentStep.id === 'trainingWeeks') {
      nextDraft = {
        ...nextDraft,
        trainingDays: calculateTrainingDays(normalizedValue, nextDraft.weeklyCourseCount),
      }
    }
    const nextIndex = stepIndex + (
      currentStep.id === 'rncpCode' && skipRncpConfirmation ? 2 : 1
    )
    const nextStep = RECRUITMENT_STEPS[nextIndex]
    const nextMatchingModule = modules.find((module) => String(module.rncp_code || '').replace(/\D/g, '') === String(nextDraft.rncpCode || '').replace(/\D/g, ''))
    setDraft(nextDraft)
    if (recordUser) {
      setHistory((current) => [...current, {
        role: 'user',
        text: displayAnswer(currentStep, currentStep.id === 'rncpConfirm' ? 'Oui, continuer' : normalizedValue),
      }])
    }
    setStepIndex(nextIndex)
    setAnswer('')
    const nextAssistantText = nextStep
      ? getRecruitmentAssistantText(nextStep, nextDraft, nextMatchingModule)
      : 'La configuration est prête. Vérifiez les informations avant de poursuivre.'

    if (nextAssistantText) {
      revealAssistantMessages([{ role: 'assistant', text: nextAssistantText }])
    } else {
      setIsThinking(false)
    }
  }

  const presentVerifiedCertification = (
    certification,
    { skipRncpConfirmation = false } = {},
  ) => {
    const replacements = Array.isArray(certification?.replacement_certifications)
      ? certification.replacement_certifications
      : []

    if (!certification?.active) {
      const formattedReplacements = replacements
        .map((replacement) => `RNCP ${replacement.rncp_code} « ${replacement.title} »`)
        .join(', ')
      setPendingRncpDecision({ certification, replacements })
      revealAssistantMessages([{
        role: 'assistant',
        text: replacements.length === 1
          ? `Ce titre professionnel n’est désormais plus d’actualité. Il a été remplacé par ${formattedReplacements}, qui correspond à une version plus à jour. Êtes-vous sûr de vouloir quand même dispenser une formation pour le titre professionnel RNCP ${certification.rncp_code} « ${certification.title} », ou souhaitez-vous dispenser la formation du titre RNCP ${replacements[0].rncp_code} ?`
          : replacements.length > 1
            ? `Ce titre professionnel n’est désormais plus d’actualité. Il a été remplacé par les certifications suivantes, qui correspondent à des versions plus à jour : ${formattedReplacements}. Êtes-vous sûr de vouloir quand même dispenser une formation pour le titre professionnel RNCP ${certification.rncp_code} « ${certification.title} », ou souhaitez-vous dispenser la formation de l’un de ces nouveaux titres RNCP ?`
          : `La fiche RNCP ${certification.rncp_code} « ${certification.title} » est inactive, mais son REAC reste disponible. Êtes-vous sûr de vouloir dispenser ce titre professionnel ?`,
      }])
      return
    }

    advance(certification.rncp_code, {
      recordUser: false,
      verifiedCertification: certification,
      skipRncpConfirmation,
    })
  }

  const verifyRncpCode = async (
    rncpCode,
    { skipRncpConfirmation = false } = {},
  ) => {
    setIsThinking(true)
    try {
      const response = await apiFetch(`/api/hr/recruitment/rncp/${encodeURIComponent(rncpCode)}`, {
        timeoutMs: 25000,
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || !payload.success) {
        revealAssistantMessages([{
          role: 'assistant',
          text: payload.error || 'Je ne peux pas vérifier ce code RNCP pour le moment. Réessayez dans quelques instants.',
        }])
        return
      }
      if (!payload.available) {
        revealAssistantMessages([{
          role: 'assistant',
          text: payload.reply || 'Désolé, nous n’avons pas encore de professeur disponible pour dispenser cette formation.',
        }])
        return
      }
      presentVerifiedCertification(payload.certification, { skipRncpConfirmation })
    } catch {
      revealAssistantMessages([{
        role: 'assistant',
        text: 'France Compétences est temporairement inaccessible. Réessayez la vérification dans quelques instants.',
      }])
    }
  }

  const interpretFreeTextAnswer = async (field, value, turnHistory = null) => {
    setIsThinking(true)
    const conversationHistory = turnHistory || [
      ...history,
      { role: 'user', text: value },
    ]

    let interpretation
    try {
      const response = await apiFetch('/api/hr/recruitment/interpret', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          field,
          message: value,
          draft,
          history: conversationHistory.slice(-12),
          attempt: clarificationAttempts[field] || 0,
        }),
        timeoutMs: 25000,
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || !payload.success) throw new Error(payload.error || 'Analyse indisponible')
      interpretation = payload
    } catch {
      interpretation = {
        answered: false,
        value: null,
        reply: 'Je ne peux pas interpréter votre réponse pour le moment. Réessayez dans quelques instants.',
      }
    }

    if (!interpretation.answered) {
      setClarificationAttempts((current) => ({
        ...current,
        [field]: (current[field] || 0) + 1,
      }))
      revealAssistantMessages([{
        role: 'assistant',
        text: interpretation.reply || getRecruitmentAssistantText(currentStep, draft, matchingModule),
      }])
      return
    }

    setClarificationAttempts((current) => ({ ...current, [field]: 0 }))
    const interpretedValue = interpretation.value
    if (field === 'teacherName') {
      setPendingConfirmation({ field, value: interpretedValue })
      revealAssistantMessages([{
        role: 'assistant',
        text: `J’ai compris « ${interpretedValue} ». Est-ce bien le nom que vous souhaitez donner au professeur IA ?`,
      }])
      return
    }

    if (field === 'rncpCode') {
      await verifyRncpCode(interpretedValue)
      return
    }

    advance(interpretedValue, { recordUser: false })
  }

  const submitInitialBrief = (event) => {
    event.preventDefault()
    const value = brief.trim()
    if (!value) return
    setStarted(true)
    setHistory([{ role: 'user', text: value }])
    setBrief('')
    interpretFreeTextAnswer('rncpCode', value, [{ role: 'user', text: value }])
  }

  const submitAnswer = (event) => {
    event.preventDefault()
    const value = answer.trim()
    if (!value) return
    const field = currentStep?.id
    setHistory((current) => [...current, { role: 'user', text: value }])
    setAnswer('')
    interpretFreeTextAnswer(field, value, [...history, { role: 'user', text: value }])
  }

  const resolvePendingConfirmation = (confirmed) => {
    if (!pendingConfirmation) return
    const { value } = pendingConfirmation
    setPendingConfirmation(null)
    if (confirmed) {
      setHistory((current) => [...current, { role: 'user', text: 'Oui, c’est bien cela' }])
      advance(value, { recordUser: false })
      return
    }

    setHistory((current) => [...current, { role: 'user', text: 'Non, je veux le corriger' }])
    revealAssistantMessages([{
      role: 'assistant',
      text: 'D’accord. Quel prénom ou quel nom voulez-vous précisément donner au professeur IA ? Par exemple « Pierre » ou « Sofia ».',
    }])
  }

  const resolvePendingRncpDecision = async (replacement = null) => {
    if (!pendingRncpDecision) return
    const { certification } = pendingRncpDecision
    setPendingRncpDecision(null)

    if (replacement && replacement !== 'other') {
      setHistory((current) => [...current, {
        role: 'user',
        text: `Utiliser RNCP ${replacement.rncp_code} « ${replacement.title} »`,
      }])
      await verifyRncpCode(replacement.rncp_code, { skipRncpConfirmation: true })
      return
    }

    if (replacement === 'other') {
      setHistory((current) => [...current, { role: 'user', text: 'Saisir un autre code RNCP' }])
      setAnswer('')
      revealAssistantMessages([{
        role: 'assistant',
        text: 'D’accord. Quel autre code RNCP souhaitez-vous utiliser ?',
      }])
      return
    }

    setHistory((current) => [...current, {
      role: 'user',
      text: `Conserver RNCP ${certification.rncp_code} « ${certification.title} »`,
    }])
    advance(certification.rncp_code, {
      recordUser: false,
      verifiedCertification: certification,
      skipRncpConfirmation: true,
    })
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

  if (manualMode) {
    return (
      <ManualRecruitmentForm
        colors={colors}
        onBack={() => setManualMode(false)}
        onComplete={onComplete}
      />
    )
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
            <h1 className="workspace-display-title text-[2rem] font-semibold leading-tight tracking-[-0.025em] sm:text-[2.4rem]" style={{ color: colors.text }}>
              Quel professeur recruterez-vous&nbsp;?
            </h1>
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

          <div
            className={`recruitment-draft-actions mx-auto mt-3 flex max-w-[760px] flex-col gap-3 rounded-lg bg-[#F7F7F5] px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between${hasSavedDraft ? ' recruitment-draft-actions--saved' : ''}`}
          >
            <div>
              <p className="text-[13px] font-medium text-[#191918]">
                {hasSavedDraft ? 'Une progression est enregistrée' : 'Vous préférez renseigner les informations vous-même ?'}
              </p>
              <p className="mt-0.5 text-xs text-[#73736F]">
                {hasSavedDraft
                  ? 'Reprenez votre recrutement ou recommencez avec un nouveau formulaire.'
                  : 'Ouvrez directement le formulaire complet.'}
              </p>
            </div>
            <div className="flex shrink-0 flex-col gap-2 sm:flex-row">
              {hasSavedDraft && (
                <button
                  type="button"
                  onClick={onResumeDraft}
                  className="recruitment-draft-actions__resume inline-flex min-h-9 items-center justify-center gap-2 rounded-md bg-[#191918] px-3 text-[13px] font-medium text-white transition-[background-color,transform] duration-150 hover:bg-[#2C2C2A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#191918]/45 focus-visible:ring-offset-2 active:scale-[0.98]"
                >
                  <RotateCcw size={15} strokeWidth={1.7} aria-hidden="true" />
                  <span>Reprendre ma progression</span>
                </button>
              )}
              <button type="button" onClick={() => { onManualStart?.(); setManualMode(true) }} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-black/10 bg-white px-3 text-[13px] font-medium text-[#191918] transition-colors duration-150 hover:bg-[#ECEBE8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#191918]/35 focus-visible:ring-offset-2">
                <PenLine size={15} strokeWidth={1.6} aria-hidden="true" />
                <span>Recruter manuellement</span>
              </button>
            </div>
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
    <section className="mx-auto flex min-h-0 w-full max-w-5xl flex-1 flex-col">
      <div className="flex h-14 shrink-0 items-center justify-between gap-4 border-b" style={{ borderColor: colors.borderLight }}>
        <div>
          <h1 className="text-sm font-semibold" style={{ color: colors.text }}>Nouveau professeur IA</h1>
          <p className="mt-0.5 text-[11px]" style={{ color: colors.textMuted }}>{completed ? 'Configuration prête à planifier' : `Question ${Math.min(stepIndex + 1, RECRUITMENT_STEPS.length)} sur ${RECRUITMENT_STEPS.length}`}</p>
        </div>
      </div>

      <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col px-1 sm:px-3">
        <div
          ref={chatScrollRef}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-2"
          style={{ scrollbarGutter: 'stable' }}
          aria-live="polite"
        >
          <div className="flex min-h-full flex-col justify-start py-8 sm:py-10">
          {history.map((message, index) => (
            <div
              key={message.id || `${message.role}-${index}`}
              className={`group relative flex flex-col ${message.role === 'user' ? 'items-end' : 'items-start'} ${index === 0 ? '' : history[index - 1]?.role === message.role ? 'mt-2' : 'mt-6'}`}
            >
              {message.role === 'user' ? (
                <div className="max-w-[82%] rounded-2xl bg-[#F1F1EF] px-4 py-2.5 text-sm leading-6" style={{ color: colors.text }}>
                  {message.text}
                </div>
              ) : (
                <p className="max-w-[68ch] text-sm leading-6" style={{ color: colors.text }}>{message.text}</p>
              )}
              {message.text && message.id !== streamingMessageId && <button
                type="button"
                onClick={() => navigator.clipboard?.writeText(message.text)}
                className={`absolute top-full mt-0.5 flex h-7 w-7 items-center justify-center rounded-md opacity-0 transition-opacity duration-150 hover:bg-[#F3F3F1] group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#097FE8]/40 ${message.role === 'user' ? 'right-0' : 'left-0'}`}
                style={{ color: colors.textMuted }}
                aria-label="Copier le message"
              >
                <Copy size={14} strokeWidth={1.6} aria-hidden="true" />
              </button>}
            </div>
          ))}
          {isThinking && !streamingMessageId && (
            <div className="mt-6 flex items-center gap-2 py-1 text-sm" style={{ color: colors.textMuted }}>
              <span className="recruitment-thinking-dot h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
              <span>Réflexion…</span>
            </div>
          )}
          {!completed && <div aria-hidden="true" className="h-[clamp(72px,14vh,144px)] shrink-0" />}
          </div>
        </div>

        {completed && !isThinking ? (
          <div className="recruitment-review-enter mt-4 max-h-[48vh] shrink-0 overflow-y-auto rounded-xl border bg-white p-5 sm:p-6" style={{ borderColor: colors.borderLight, scrollbarGutter: 'stable' }}>
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <div><dt style={{ color: colors.textMuted }}>Professeur</dt><dd className="mt-0.5 font-medium" style={{ color: colors.text }}>{draft.teacherName}</dd></div>
              <div><dt style={{ color: colors.textMuted }}>Formation</dt><dd className="mt-0.5 font-medium" style={{ color: colors.text }}>{draft.trainingName}</dd></div>
              <div><dt style={{ color: colors.textMuted }}>Référence</dt><dd className="mt-0.5 font-medium" style={{ color: colors.text }}>RNCP {draft.rncpCode}</dd></div>
              <div><dt style={{ color: colors.textMuted }}>Calendrier</dt><dd className="mt-0.5 font-medium" style={{ color: colors.text }}>{draft.trainingWeeks} semaines, {draft.weeklyCourseCount} journée{Number(draft.weeklyCourseCount) > 1 ? 's' : ''}/semaine</dd></div>
            </dl>
            <button type="button" onClick={() => onComplete(draft)} className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#191714] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-[#302D28]">
              Configurer le planning
              <Icon name="arrow_forward" className="text-base" />
            </button>
          </div>
        ) : !completed ? (
          <div className="shrink-0 border-t bg-white py-3 sm:py-4" style={{ borderColor: colors.borderLight }}>
            {!isThinking && pendingConfirmation && (
              <div className="overflow-hidden rounded-xl border bg-white" style={{ borderColor: colors.border }}>
                <div className="px-4 py-3.5 sm:px-5">
                  <p className="text-sm font-semibold leading-5" style={{ color: colors.text }}>
                    Confirmer le nom du professeur
                  </p>
                  <p className="mt-1 text-sm" style={{ color: colors.textMuted }}>{pendingConfirmation.value}</p>
                </div>
                <button type="button" onClick={() => resolvePendingConfirmation(true)} className="flex w-full items-center gap-3 border-t px-4 py-3 text-left text-sm transition-colors hover:bg-[#F8F6F2] sm:px-5" style={{ borderColor: colors.borderLight, color: colors.text }}>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: colors.innerBg, color: colors.textMuted }}>1</span>
                  Confirmer ce nom
                </button>
                <button type="button" onClick={() => resolvePendingConfirmation(false)} className="flex w-full items-center gap-3 border-t px-4 py-3 text-left text-sm transition-colors hover:bg-[#F8F6F2] sm:px-5" style={{ borderColor: colors.borderLight, color: colors.text }}>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: colors.innerBg, color: colors.textMuted }}>2</span>
                  Modifier le nom
                </button>
              </div>
            )}
            {!isThinking && pendingRncpDecision && (
              <div className="overflow-hidden rounded-xl border bg-white" style={{ borderColor: colors.border }}>
                <div className="px-4 py-3.5 sm:px-5">
                  <p className="text-sm font-semibold leading-5" style={{ color: colors.text }}>
                    Choisir la certification RNCP
                  </p>
                  <p className="mt-1 text-xs leading-5" style={{ color: colors.textMuted }}>
                    Le REAC de la fiche inactive reste disponible pour préparer le professeur.
                  </p>
                </div>
                <button type="button" onClick={() => resolvePendingRncpDecision()} className="flex w-full items-center gap-3 border-t px-4 py-3 text-left text-sm transition-colors hover:bg-[#F8F6F2] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#097FE8]/45 sm:px-5" style={{ borderColor: colors.borderLight, color: colors.text }}>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: colors.innerBg, color: colors.textMuted }}>1</span>
                  <span>
                    <span className="block font-medium">Conserver RNCP {pendingRncpDecision.certification.rncp_code}</span>
                    <span className="mt-0.5 block text-xs" style={{ color: colors.textMuted }}>{pendingRncpDecision.certification.title}</span>
                  </span>
                </button>
                {pendingRncpDecision.replacements.map((replacement, index) => (
                  <button key={replacement.rncp_code} type="button" onClick={() => resolvePendingRncpDecision(replacement)} className="flex w-full items-center gap-3 border-t px-4 py-3 text-left text-sm transition-colors hover:bg-[#F8F6F2] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#097FE8]/45 sm:px-5" style={{ borderColor: colors.borderLight, color: colors.text }}>
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: colors.innerBg, color: colors.textMuted }}>{index + 2}</span>
                    <span>
                      <span className="block font-medium">Utiliser RNCP {replacement.rncp_code}</span>
                      <span className="mt-0.5 block text-xs" style={{ color: colors.textMuted }}>{replacement.title}</span>
                    </span>
                  </button>
                ))}
                {pendingRncpDecision.replacements.length === 0 && (
                  <button type="button" onClick={() => resolvePendingRncpDecision('other')} className="flex w-full items-center gap-3 border-t px-4 py-3 text-left text-sm transition-colors hover:bg-[#F8F6F2] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#097FE8]/45 sm:px-5" style={{ borderColor: colors.borderLight, color: colors.text }}>
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: colors.innerBg, color: colors.textMuted }}>2</span>
                    Saisir un autre code RNCP
                  </button>
                )}
              </div>
            )}
            {!pendingConfirmation && !pendingRncpDecision && (currentStep.type === 'text' || currentStep.type === 'number') && (
              <form onSubmit={submitAnswer} className="flex items-center gap-2 rounded-xl border bg-white p-2 pl-4" style={{ borderColor: colors.borderLight }}>
                <input type="text" inputMode={currentStep.type === 'number' ? 'numeric' : undefined} value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder={isThinking ? 'Réflexion en cours…' : currentStep.placeholder} disabled={isThinking} className="min-w-0 flex-1 bg-transparent py-2.5 text-sm outline-none placeholder:text-[#68625B] disabled:cursor-wait disabled:text-[#73736F]" style={{ color: colors.text }} autoFocus={!isThinking} />
                <button type="submit" disabled={isThinking || !answer.trim()} className="flex h-9 w-9 items-center justify-center rounded-full bg-[#191918] text-white transition-colors hover:bg-[#30302E] disabled:cursor-not-allowed disabled:bg-[#C7C7C4]" aria-label="Valider la réponse"><ArrowUp size={17} strokeWidth={1.8} aria-hidden="true" /></button>
              </form>
            )}
            {!isThinking && !pendingConfirmation && !pendingRncpDecision && currentIsChoice && (
              <div className="overflow-hidden rounded-xl border bg-white" style={{ borderColor: colors.border }}>
                <div className="flex items-start justify-between gap-4 px-4 py-3.5 sm:px-5">
                  <div>
                    <p className="text-sm font-semibold leading-5" style={{ color: colors.text }}>{currentStep.question}</p>
                    {currentStep.id === 'rncpConfirm' && (
                      <p className="mt-1 text-xs" style={{ color: colors.textMuted }}>
                        {`${draft.trainingName || matchingModule?.tp_name} · RNCP ${draft.rncpCode || matchingModule?.rncp_code}`}
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
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-medium" style={{ backgroundColor: selected ? '#097FE8' : colors.innerBg, color: selected ? '#fff' : colors.textMuted }}>{selected ? <Icon name="check" className="text-sm" /> : index + 1}</span>
                      {day.label}
                    </button>
                  )
                })}

                {currentStep.type === 'days' && (
                  <div className="flex items-center justify-between gap-3 border-t px-4 py-3 sm:px-5" style={{ borderColor: colors.borderLight }}>
                    <span className="text-xs" style={{ color: colors.textMuted }}>
                      {`${draft.teachingDays.length} jour${draft.teachingDays.length > 1 ? 's' : ''} sélectionné${draft.teachingDays.length > 1 ? 's' : ''}`}
                    </span>
                    <button type="button" disabled={draft.teachingDays.length !== Number(draft.weeklyCourseCount)} onClick={() => advance(draft.teachingDays)} className="rounded-lg bg-[#191714] px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-35">
                      Valider ce choix
                    </button>
                  </div>
                )}
              </div>
            )}
            {!isThinking && !pendingConfirmation && currentStep.type === 'date' && (
              <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-white p-3" style={{ borderColor: colors.border }}>
                <input type="date" min={getMinimumNewModuleStartDate()} value={draft.startDate} onChange={(event) => setDraft((current) => ({ ...current, startDate: event.target.value }))} className="min-w-0 flex-1 rounded-lg border px-4 py-2.5 text-sm" style={{ borderColor: colors.borderLight, color: colors.text }} />
                <span
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[#B9BDC5] text-[#626773] outline-none transition-colors hover:border-[#191918] hover:text-[#191918] focus-visible:border-[#191918] focus-visible:text-[#191918]"
                  role="img"
                  aria-label="Vous pouvez choisir dès demain. Les 24 heures exactes seront contrôlées selon l’heure du premier cours dans le planning."
                  title="Vous pouvez choisir dès demain. Les 24 heures exactes seront contrôlées selon l’heure du premier cours dans le planning."
                  tabIndex="0"
                >
                  <Info size={14} aria-hidden="true" />
                </span>
                <button type="button" disabled={draft.startDate < getMinimumNewModuleStartDate()} onClick={() => advance(draft.startDate)} className="rounded-lg bg-[#191714] px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-35">Valider la date</button>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </section>
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

function TeacherArrivalAnimation({ platform, targetRef }) {
  const layerRef = useRef(null)
  const haloRef = useRef(null)
  const robotRef = useRef(null)

  useEffect(() => {
    const layer = layerRef.current
    const halo = haloRef.current
    const robot = robotRef.current
    let frameId = 0
    let retryTimer = 0
    let attempts = 0
    const animations = []

    const playArrival = () => {
      const target = targetRef.current
      if (!layer || !halo || !robot || !target) {
        attempts += 1
        if (attempts < 20) retryTimer = window.setTimeout(playArrival, 50)
        return
      }

      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        layer.hidden = true
        return
      }

      const targetRect = target.getBoundingClientRect()
      const robotSize = Math.min(190, Math.max(112, targetRect.width * 0.72))
      const startLeft = Math.min(
        window.innerWidth - robotSize - 24,
        Math.max(24, window.innerWidth * 0.7),
      )
      const startTop = Math.max(72, window.innerHeight * 0.12)
      const endLeft = targetRect.left + (targetRect.width - robotSize) / 2
      const endTop = targetRect.top + (targetRect.height - robotSize) / 2
      const startTransform = `translate3d(${startLeft}px, ${startTop}px, 0)`
      const hoverTransform = `translate3d(${endLeft}px, ${endTop - 18}px, 0)`
      const endTransform = `translate3d(${endLeft}px, ${endTop}px, 0)`

      robot.style.width = `${robotSize}px`
      robot.style.height = `${robotSize}px`
      halo.style.width = `${robotSize * 1.24}px`
      halo.style.height = `${robotSize * 1.24}px`

      animations.push(robot.animate([
        { opacity: 0, transform: `${startTransform} scale(.46) rotate(-7deg)`, filter: 'blur(9px) saturate(1.45)' },
        { opacity: 1, offset: 0.18, transform: `${startTransform} scale(.88) rotate(-3deg)`, filter: 'blur(0) saturate(1.25)' },
        { opacity: 1, offset: 0.76, transform: `${hoverTransform} scale(1.08) rotate(1deg)`, filter: 'blur(0) saturate(1.12)' },
        { opacity: 1, transform: `${endTransform} scale(1) rotate(0)`, filter: 'blur(0) saturate(1)' },
      ], {
        duration: 1080,
        easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
        fill: 'forwards',
      }))

      animations.push(halo.animate([
        { opacity: 0, transform: `${startTransform} translate(-10%, -10%) scale(.28)` },
        { opacity: 0.82, offset: 0.2, transform: `${startTransform} translate(-10%, -10%) scale(1)` },
        { opacity: 0.5, offset: 0.72, transform: `${hoverTransform} translate(-10%, -10%) scale(.72)` },
        { opacity: 0, transform: `${endTransform} translate(-10%, -10%) scale(.45)` },
      ], {
        duration: 1080,
        easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
        fill: 'forwards',
      }))

      animations.push(target.animate([
        { boxShadow: 'inset 0 0 0 0 rgba(108, 99, 255, 0)' },
        { boxShadow: 'inset 0 0 0 2px rgba(108, 99, 255, .55), 0 0 30px rgba(108, 99, 255, .22)', offset: 0.55 },
        { boxShadow: 'inset 0 0 0 0 rgba(108, 99, 255, 0)' },
      ], {
        delay: 720,
        duration: 560,
        easing: 'cubic-bezier(0.25, 1, 0.5, 1)',
      }))

      Promise.allSettled(animations.map((animation) => animation.finished)).then(() => {
        if (layer) layer.hidden = true
      })
    }

    frameId = window.requestAnimationFrame(playArrival)
    return () => {
      window.cancelAnimationFrame(frameId)
      window.clearTimeout(retryTimer)
      animations.forEach((animation) => animation.cancel())
    }
  }, [platform.id, targetRef])

  const robotTheme = getRobotTheme(
    platform.center_platform_number || platform.id,
    platform.teacher_color,
  )

  return createPortal(
    <div ref={layerRef} className="teacher-arrival-layer" aria-hidden="true">
      <div ref={haloRef} className="teacher-arrival-halo">
        <span className="teacher-arrival-ring teacher-arrival-ring--outer" />
        <span className="teacher-arrival-ring teacher-arrival-ring--inner" />
      </div>
      <img
        ref={robotRef}
        src={robotTheme.src}
        alt=""
        draggable={false}
        className="teacher-arrival-robot"
      />
    </div>,
    document.body,
  )
}

function PlatformCardsView({
  platforms,
  cardPage,
  setCardPage,
  cardsPerPage,
  rosterFilter,
  onRosterFilterChange,
  onRecruit,
  expandedPlatform,
  platformAudios,
  audiosLoading,
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
  onExpand,
  onRefreshAudios,
  onToggleStudentEmails,
  onToggleAttendance,
  onStudentEmailDraftChange,
  onAddStudentEmails,
  onDeleteStudentEmail,
  onAttendanceDateChange,
  onRefreshAttendance,
  onExportAttendance,
  onOpenCourseTimeModal,
  onOpenCoursFolders,
  onCloseCardPanels,
  currentCourseTime,
  onSetCourseTime,
  onRetrySessionAudio,
  onPreviewSessionPostponement,
  onPostponeSession,
  onAudiosPublished,
  newlyCreatedPlatformId,
  retryingPlatformId,
  onRetryPreparation,
  onTestClockChanged,
}) {
  const [rosterSearch, setRosterSearch] = useState('')
  const [rosterSearchOpen, setRosterSearchOpen] = useState(false)
  const [selectedTeacherId, setSelectedTeacherId] = useState(null)
  const teacherArrivalTargetRef = useRef(null)
  const [testClockOpen, setTestClockOpen] = useState(false)
  const [testClock, setTestClock] = useState(null)
  const [testClockValue, setTestClockValue] = useState('')
  const [testClockLoading, setTestClockLoading] = useState(false)
  const [testClockError, setTestClockError] = useState('')
  const [testClockNotice, setTestClockNotice] = useState('')
  const testClockAvailable = isOrderReviewCenter()

  const toLocalDateTimeInput = (value) => {
    const date = value ? new Date(value) : new Date()
    const pad = (part) => String(part).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
  }

  const loadTestClock = useCallback(async () => {
    if (!testClockAvailable) return
    setTestClockLoading(true)
    setTestClockError('')
    try {
      const response = await apiFetch('/api/hr/test-clock')
      const data = await response.json()
      if (!response.ok || !data.success) throw new Error(data.error || 'Impossible de lire l’heure de test')
      setTestClock(data)
      setTestClockValue(toLocalDateTimeInput(data.current_time))
    } catch (error) {
      setTestClockError(error.message || 'Impossible de lire l’heure de test')
    } finally {
      setTestClockLoading(false)
    }
  }, [testClockAvailable])

  const openTestClock = () => {
    setTestClockOpen(true)
    setTestClockNotice('')
    loadTestClock()
  }

  const saveTestClock = async (event) => {
    event.preventDefault()
    if (!testClockValue) return
    setTestClockLoading(true)
    setTestClockError('')
    setTestClockNotice('')
    try {
      const response = await apiFetch('/api/hr/test-clock', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ datetime: new Date(testClockValue).toISOString() }),
        timeoutMs: 60000,
      })
      const data = await response.json()
      if (!response.ok || !data.success) throw new Error(data.error || 'Impossible de modifier l’heure')
      setTestClock(data)
      setTestClockValue(toLocalDateTimeInput(data.current_time))
      setTestClockNotice(data.scheduler?.reminder_count
        ? `${data.scheduler.reminder_count} rappel(s) traité(s).`
        : 'Heure appliquée. Les séances et rappels utilisent maintenant cette horloge.')
      onTestClockChanged?.()
    } catch (error) {
      setTestClockError(error.message || 'Impossible de modifier l’heure')
    } finally {
      setTestClockLoading(false)
    }
  }

  const resetTestClock = async () => {
    setTestClockLoading(true)
    setTestClockError('')
    setTestClockNotice('')
    try {
      const response = await apiFetch('/api/hr/test-clock', { method: 'DELETE' })
      const data = await response.json()
      if (!response.ok || !data.success) throw new Error(data.error || 'Impossible de rétablir l’heure réelle')
      setTestClock(data)
      setTestClockValue(toLocalDateTimeInput(data.current_time))
      setTestClockNotice('Heure réelle rétablie.')
      onTestClockChanged?.()
    } catch (error) {
      setTestClockError(error.message || 'Impossible de rétablir l’heure réelle')
    } finally {
      setTestClockLoading(false)
    }
  }
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
  const arrivingTeacher = newlyCreatedPlatformId
    ? platforms.find((platform) => String(platform.id) === String(newlyCreatedPlatformId))
    : null
  const orderedPlatforms = arrivingTeacher && filteredPlatforms.some(
    (platform) => String(platform.id) === String(arrivingTeacher.id),
  )
    ? [
        arrivingTeacher,
        ...filteredPlatforms.filter((platform) => String(platform.id) !== String(arrivingTeacher.id)),
      ]
    : filteredPlatforms
  const filterCounts = Object.fromEntries(
    TEACHER_ROSTER_FILTERS.map((filter) => [
      filter.id,
      filter.id === 'all'
        ? platforms.length
        : platforms.filter((platform) => getTeacherRosterFilterGroup(platform) === filter.id).length,
    ]),
  )
  const totalPages = Math.ceil(orderedPlatforms.length / cardsPerPage)
  const safeCardPage = Math.min(cardPage, Math.max(0, totalPages - 1))
  const visiblePlatforms = orderedPlatforms.slice(
    safeCardPage * cardsPerPage,
    (safeCardPage + 1) * cardsPerPage,
  )

  return (
    <section className="mx-auto flex h-full min-h-0 w-full max-w-[90rem] flex-col overflow-hidden pt-4 sm:pt-6">
      {!selectedTeacherId && <><header className="relative mx-auto w-full max-w-[1204px] px-4 text-center sm:px-12">
        <h1 className="workspace-display-title text-[1.75rem] font-semibold leading-tight tracking-[-0.02em] sm:text-[2rem]" style={{ color: colors.text }}>
          Mes professeurs
        </h1>
        <p className="mt-1 text-sm" style={{ color: colors.textMuted }}>Retrouvez vos professeurs, leurs formations et leur prochaine séance.</p>

        <div className="absolute right-0 top-0 flex h-11 items-center justify-end gap-1">
          {testClockAvailable && !rosterSearchOpen && (
            <button
              type="button"
              onClick={openTestClock}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border bg-white px-2.5 text-xs font-semibold shadow-sm transition-colors hover:bg-[#F5F5F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/25"
              style={{ borderColor: testClock?.active ? '#8B5CF6' : colors.borderLight, color: testClock?.active ? '#6D28D9' : colors.textSecondary }}
              aria-label="Modifier l’heure de test"
            >
              <Icon name="schedule" className="text-base" />
              <span className="hidden lg:inline">{testClock?.active ? 'Heure test active' : 'Heure de test'}</span>
            </button>
          )}
          {rosterSearchOpen ? (
            <div className="flex h-9 w-[min(12.5rem,calc(100vw-7rem))] items-center gap-1.5 rounded-md border bg-white px-2.5 shadow-sm" style={{ borderColor: colors.borderLight }} role="search">
              <Icon name="search" className="text-base" style={{ color: colors.textMuted }} />
              <label htmlFor="teacher-roster-search" className="sr-only">Rechercher un professeur ou une formation</label>
              <input
                id="teacher-roster-search"
                type="search"
                value={rosterSearch}
                onChange={(event) => {
                  setRosterSearch(event.target.value)
                  setCardPage(0)
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Escape') {
                    setRosterSearch('')
                    setRosterSearchOpen(false)
                    setCardPage(0)
                  }
                }}
                placeholder="Rechercher…"
                className="min-w-0 flex-1 bg-transparent py-1.5 text-[13px] outline-none placeholder:text-[#626269]"
                style={{ color: colors.text }}
                autoFocus
              />
              <button
                type="button"
                onClick={() => {
                  setRosterSearch('')
                  setRosterSearchOpen(false)
                  setCardPage(0)
                }}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[#F3F3F1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/25"
                aria-label="Fermer la recherche"
                style={{ color: colors.textMuted }}
              >
                <Icon name="close" className="text-sm" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setRosterSearchOpen(true)}
              className="flex h-11 w-11 items-center justify-center rounded-lg transition-colors hover:bg-[#F3F3F1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/25"
              aria-label="Rechercher un professeur"
              aria-expanded="false"
              style={{ color: colors.textMuted }}
            >
              <Icon name="search" className="text-xl" />
            </button>
          )}
        </div>
      </header>

      {testClockOpen && createPortal(
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !testClockLoading) setTestClockOpen(false)
          }}
        >
          <div className="w-full max-w-md rounded-xl border bg-white p-5 text-left shadow-2xl" style={{ borderColor: colors.borderLight }} role="dialog" aria-modal="true" aria-labelledby="test-clock-title">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="test-clock-title" className="text-lg font-semibold" style={{ color: colors.text }}>Horloge de test</h2>
                <p className="mt-1 text-sm leading-5" style={{ color: colors.textMuted }}>
                  Simulez la date et l’heure de ce centre pour vérifier le lancement des séances et l’envoi des rappels.
                </p>
              </div>
              <button type="button" onClick={() => setTestClockOpen(false)} disabled={testClockLoading} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md hover:bg-[#F3F3F1] disabled:opacity-50" aria-label="Fermer">
                <X size={18} />
              </button>
            </div>

            <form className="mt-5" onSubmit={saveTestClock}>
              <label htmlFor="test-clock-value" className="block text-xs font-semibold uppercase tracking-[0.12em]" style={{ color: colors.textMuted }}>Date et heure simulées</label>
              <input
                id="test-clock-value"
                type="datetime-local"
                value={testClockValue}
                onChange={(event) => setTestClockValue(event.target.value)}
                disabled={testClockLoading}
                className="mt-2 h-11 w-full rounded-md border bg-white px-3 text-sm outline-none focus:ring-2 focus:ring-violet-500/30 disabled:opacity-60"
                style={{ borderColor: colors.border }}
                required
              />
              <p className="mt-2 text-xs leading-5" style={{ color: colors.textMuted }}>
                L’horloge continuera d’avancer normalement à partir de cette heure. Seules les plateformes de ce centre sont concernées.
              </p>

              {testClockError && <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{testClockError}</p>}
              {testClockNotice && <p className="mt-3 rounded-md bg-violet-50 px-3 py-2 text-sm text-violet-800" role="status">{testClockNotice}</p>}

              <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={resetTestClock}
                  disabled={testClockLoading || !testClock?.active}
                  className="inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium hover:bg-[#F3F3F1] disabled:cursor-not-allowed disabled:opacity-40"
                  style={{ color: colors.textSecondary }}
                >
                  <RotateCcw size={15} /> Revenir à l’heure réelle
                </button>
                <button type="submit" disabled={testClockLoading || !testClockValue} className="h-10 rounded-md bg-[#18181B] px-4 text-sm font-semibold text-white hover:bg-black disabled:cursor-not-allowed disabled:opacity-50">
                  {testClockLoading ? 'Application…' : 'Appliquer l’heure'}
                </button>
              </div>
            </form>
          </div>
        </div>,
        document.body,
      )}

      <div className="mx-auto mt-5 flex w-full max-w-[980px] items-center gap-5" aria-hidden="true">
        <span className="h-px flex-1" style={{ backgroundColor: colors.borderLight }} />
        <span className="text-[10px] font-semibold uppercase tracking-[0.22em]" style={{ color: colors.textMuted }}>Filtrer par statut</span>
        <span className="h-px flex-1" style={{ backgroundColor: colors.borderLight }} />
      </div>

      <div className="mx-auto mt-3 flex w-full max-w-[1204px] flex-wrap items-center justify-center gap-2" role="group" aria-label="Filtrer les professeurs IA">
        {TEACHER_ROSTER_FILTERS.map((filter) => {
          const selected = rosterFilter === filter.id
          return (
            <button
              key={filter.id}
              type="button"
              onClick={() => onRosterFilterChange(filter.id)}
              aria-pressed={selected}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30"
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

      </>}

      {!selectedTeacherId && filteredPlatforms.length > cardsPerPage && (
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

      {!selectedTeacherId && platforms.length === 0 && (
        <div className="flex min-h-0 flex-1 flex-col items-center pb-16 pt-10 text-center sm:pb-20 sm:pt-14">
          <img src="/robot-blue.png" alt="" className="h-[200px] w-[200px] object-contain" />
          <h2 className="mt-3 text-xl font-bold" style={{ color: colors.text }}>Aucun professeur recruté</h2>
          <p className="mt-2 max-w-xl text-sm leading-6" style={{ color: colors.textMuted }}>
            Recrutez votre premier professeur IA pour préparer et dispenser une formation.
          </p>
          <button
            type="button"
            onClick={onRecruit}
            className="mt-6 inline-flex min-h-11 items-center gap-2 rounded-lg border border-[#18181B] bg-white px-4 py-2 text-sm font-semibold text-[#18181B] transition-colors hover:bg-[#F4F4F5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/35 focus-visible:ring-offset-2"
          >
            <UserPlus size={16} strokeWidth={1.8} aria-hidden="true" />
            Recruter un professeur
          </button>
        </div>
      )}

      {(selectedTeacherId || filteredPlatforms.length > 0) && (
        <div className="mt-4 min-h-0 flex-1 overflow-y-auto overscroll-contain pb-6 pr-1">
        <div className={`mx-auto grid w-full items-start gap-3 sm:gap-4 ${selectedTeacherId ? 'max-w-[90rem] grid-cols-1' : 'max-w-[1204px] grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5'}`}>
        {(selectedTeacherId ? platforms.filter((platform) => platform.id === selectedTeacherId) : visiblePlatforms).map((p) => (
          <PlatformCard
            key={p.id}
            platform={p}
            expanded={expandedPlatform === p.id}
            audios={platformAudios[p.id] || []}
            audiosLoading={audiosLoading === p.id}
            colors={colors}
            darkMode={darkMode}
            studentEmails={studentEmailsByPlatform[p.id] || []}
            studentsExpanded={expandedStudentsPlatform === p.id}
            attendanceExpanded={expandedAttendancePlatform === p.id}
            attendanceDate={attendanceDate}
            attendanceData={expandedAttendancePlatform === p.id ? attendanceData : null}
            attendanceLoading={attendanceLoading && expandedAttendancePlatform === p.id}
            attendanceError={expandedAttendancePlatform === p.id ? attendanceError : ''}
            studentEmailsLoading={studentEmailsLoading === p.id}
            studentEmailsSaving={studentEmailsSaving === p.id}
            studentEmailDraft={studentEmailDrafts[p.id] || { prenom: '', nom: '', email: '' }}
            onExpand={() => onExpand(p.id)}
            onRefreshAudios={() => onRefreshAudios(p.id)}
            onToggleStudentEmails={() => onToggleStudentEmails(p.id)}
            onToggleAttendance={() => onToggleAttendance(p.id)}
            onStudentEmailDraftChange={(field, value) => onStudentEmailDraftChange(p.id, field, value)}
            onAddStudentEmails={() => onAddStudentEmails(p.id)}
            onDeleteStudentEmail={(recipientId) => onDeleteStudentEmail(p.id, recipientId)}
            onAttendanceDateChange={onAttendanceDateChange}
            onRefreshAttendance={() => onRefreshAttendance(p.id)}
            onExportAttendance={(week) => onExportAttendance(week, p.id)}
            onOpenCourseTimeModal={() => onOpenCourseTimeModal(p)}
            onOpenCoursFolders={() => onOpenCoursFolders(p)}
            onBeforeFlip={onCloseCardPanels}
            currentCourseTime={currentCourseTime}
            onSetCourseTime={onSetCourseTime}
            onRetrySessionAudio={onRetrySessionAudio}
            onPreviewSessionPostponement={onPreviewSessionPostponement}
            onPostponeSession={onPostponeSession}
            onAudiosPublished={() => onAudiosPublished(p.id)}
            newlyCreated={String(newlyCreatedPlatformId) === String(p.id)}
            arrivalTargetRef={String(newlyCreatedPlatformId) === String(p.id) ? teacherArrivalTargetRef : undefined}
            retryingPreparation={retryingPlatformId === p.id}
            onRetryPreparation={() => onRetryPreparation(p)}
            detailsOpen={selectedTeacherId === p.id}
            onOpenDetails={() => setSelectedTeacherId(p.id)}
            onCloseDetails={() => setSelectedTeacherId(null)}
          />
        ))}
        </div>
        </div>
      )}
      {arrivingTeacher && (
        <TeacherArrivalAnimation
          key={arrivingTeacher.id}
          platform={arrivingTeacher}
          targetRef={teacherArrivalTargetRef}
        />
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
            ) : (data?.students || []).length > 0 ? (
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
            ) : null}
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
  onExport,
}) {
  const dailyExports = data?.daily_exports || []

  const formatDate = (value) => {
    if (!value) return ''
    return new Date(`${value}T00:00:00`).toLocaleDateString('fr-FR')
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-3 sm:px-6">
      <div className="mb-5 flex items-center justify-between gap-3 border-b pb-4" style={{ borderColor: colors.border }}>
        <h4 className="text-sm font-semibold" style={{ color: colors.text }}>Présence de la journée</h4>
        <label
          className="relative flex h-9 w-9 flex-shrink-0 cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-black/5 focus-within:ring-2 focus-within:ring-black/30 dark:hover:bg-white/5"
          style={{ color: colors.textMuted }}
          title={`Rechercher une journée, date actuelle : ${formatDate(courseDate)}`}
        >
          <Icon name="search" className="text-base" />
          <span className="sr-only">Rechercher une journée</span>
          <input
            type="date"
            value={courseDate}
            onChange={(e) => onCourseDateChange(e.target.value)}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
            aria-label="Rechercher une journée"
          />
        </label>
      </div>

      {error && (
        <div
          className="mb-4 flex items-center gap-2 border-y px-1 py-3 text-xs"
          style={{
            backgroundColor: darkMode ? 'rgba(127, 29, 29, 0.18)' : '#fef2f2',
            borderColor: darkMode ? 'rgba(248, 113, 113, 0.28)' : '#fecaca',
            color: darkMode ? '#fecaca' : '#991b1b',
          }}
        >
          <Icon name="warning" className="text-sm" />
          <span>{error}</span>
        </div>
      )}

      <section className="mb-4">
        <h5 className="mb-3 text-sm font-semibold" style={{ color: colors.text }}>
          Fichiers Excel par journée
        </h5>
        {loading ? (
          <div className="flex items-center justify-center py-5" aria-label="Chargement des fichiers Excel">
            <div className="h-5 w-5 animate-spin rounded-full border-2" style={{ borderColor: colors.border, borderTopColor: '#121212' }} />
          </div>
        ) : dailyExports.length === 0 ? (
          <p className="text-xs leading-5" style={{ color: colors.textMuted }}>
            Le premier fichier apparaîtra ici le lendemain d’une journée de formation, à partir de 6 h.
          </p>
        ) : (
          <div className="max-h-[392px] space-y-1 overflow-y-auto pr-1">
            {dailyExports.map((dailyExport) => (
              <button
                key={dailyExport.id}
                type="button"
                onClick={() => dailyExport.status === 'ready' && onExport(dailyExport)}
                disabled={dailyExport.status !== 'ready'}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-black/5 disabled:cursor-default disabled:opacity-60 dark:hover:bg-white/5"
                style={{ color: colors.textSecondary, border: `1px solid ${colors.border}` }}
              >
                <img
                  src="/attendance-calendar.png"
                  alt=""
                  aria-hidden="true"
                  className="h-7 w-7 flex-shrink-0 object-contain"
                />
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
    </div>
  )
}

function TeacherToolPanel({
  title,
  subtitle,
  icon,
  onBack,
  colors,
  darkMode,
  children,
  showHeader = true,
}) {
  return (
    <section
      className="flex h-full min-h-0 flex-col"
      aria-label={title}
      style={{ backgroundColor: colors.cardBg }}
    >
      {showHeader && <header className="flex flex-shrink-0 items-center gap-2 border-b px-3 py-2 pr-10" style={{ borderColor: colors.border }}>
        <button
          type="button"
          onClick={onBack}
          autoFocus
          aria-label="Revenir aux outils du professeur"
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30 dark:hover:bg-white/5"
          style={{ color: colors.textMuted }}
        >
          <Icon name="arrow_back" className="text-lg" />
        </button>
        <span
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg"
          style={{ backgroundColor: darkMode ? '#ffffff' : '#121212', color: darkMode ? '#121212' : '#ffffff' }}
          aria-hidden="true"
        >
          <Icon name={icon} className="text-base" />
        </span>
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold tracking-tight" style={{ color: colors.text }}>
            {title}
          </h2>
          <p className="truncate text-[11px]" style={{ color: colors.textMuted }}>{subtitle}</p>
        </div>
      </header>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {children}
      </div>
    </section>
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
  if (Number(module.schedule_schema_version || 1) >= 2) {
    const total = module.nb_days || schedule?.total_training_days || module.nb_folders || 0
    return `${total} journée${total > 1 ? 's' : ''} · planning personnalisé`
  }
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
          style={{ backgroundColor: '#18181B' }}
          onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#27272A' }}
          onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#18181B' }}
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
                          backgroundColor: '#F4F4F5',
                          color: '#3F3F46',
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
                          backgroundColor: '#F4F4F5',
                          color: '#52525B',
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
                      style={{ backgroundColor: '#18181B' }}
                      onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#27272A' }}
                      onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#18181B' }}
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

export function CreatePlatformView({
  modules,
  formationMode,
  selectedModuleId,
  teacherFirstName,
  setTeacherFirstName,
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
  initialScheduleV2,
  aiVoices,
  selectedAiVoiceId,
  setSelectedAiVoiceId,
  onCreateTemplate,
  templateRedirecting = false,
  creating,
  billing,
  billingLoading,
  prefilledFromAssistant,
  submissionError,
  onCreate,
  onCancel,
}) {
  const weekDays = [
    { id: 'lundi', label: 'Lun.' },
    { id: 'mardi', label: 'Mar.' },
    { id: 'mercredi', label: 'Mer.' },
    { id: 'jeudi', label: 'Jeu.' },
    { id: 'vendredi', label: 'Ven.' },
  ]
  const selectedModule = modules.find((module) => String(module.id) === String(selectedModuleId))
  const usesLegacyReuseSchedule = (
    formationMode === 'existing'
    && Number(selectedModule?.schedule_schema_version || 1) < 2
  )
  const trainingTitle = formationMode === 'existing'
    ? String(selectedModule?.tp_name || '').trim()
    : newFormTpName.trim()
  const generatedDescription = useMemo(
    () => buildTeacherDescription(trainingTitle),
    [trainingTitle],
  )
  const [teacherDescription, setTeacherDescription] = useState(generatedDescription)
  const [identityEditorOpen, setIdentityEditorOpen] = useState(false)
  const [schedulePlan, setSchedulePlan] = useState({
    payload: null,
    valid: false,
    dayCount: 0,
    days: [],
    validation: null,
  })
  const [scheduleAttemptErrors, setScheduleAttemptErrors] = useState([])
  const [scheduleReviewOpen, setScheduleReviewOpen] = useState(false)
  const [postPlanningStep, setPostPlanningStep] = useState('voice')
  const [slideBrandEnabled, setSlideBrandEnabled] = useState(true)
  const [slideBrandName, setSlideBrandName] = useState('')
  const descriptionEditedRef = useRef(false)
  const operationType = formationMode === 'existing' ? 'reuse_teacher' : 'new_teacher'
  const product = billing?.products?.[operationType]
  const trainingDays = formationMode === 'existing'
    ? Math.max(
      1,
      Number(
        selectedModule?.nb_days
        || selectedModule?.schedule?.total_training_days
        || Math.ceil(Number(selectedModule?.total_hours || 7) / 7),
      ),
    )
    : schedulePlan.dayCount
  const estimatedAmountCents = typeof product?.unit_amount_cents === 'number'
    ? product.unit_amount_cents * trainingDays
    : null
  const paymentRequired = billing?.payment_required !== false
  const billingReady = Boolean(billing && (!paymentRequired || product?.configured))
  const legacyScheduleValid = (
    Number(weeklyCourseCount) > 0
    && Number(weeklyCourseCount) === teachingDays.length
    && teachingDays.length > 0
    && scheduleStartDate
    && scheduleStartTime === '09:00'
  )
  const canCreateTeacher = (
    teacherFirstName.trim()
    && (formationMode === 'existing' ? selectedModule : (newFormTpName.trim() && newFormRncp.trim()))
    && (usesLegacyReuseSchedule ? legacyScheduleValid : schedulePlan.payload)
    && teacherDescription.trim()
    && billingReady
  )

  const handleSchedulePlanChange = useCallback((nextPlan) => {
    setSchedulePlan(nextPlan)
    setScheduleAttemptErrors([])
  }, [])

  const openPostPlanningFlow = () => {
    const selectedVoiceStillExists = !selectedAiVoiceId || (aiVoices || []).some(
      (voice) => String(voice.id) === String(selectedAiVoiceId),
    )
    if (!selectedVoiceStillExists) setSelectedAiVoiceId('')
    setPostPlanningStep('voice')
    setScheduleReviewOpen(true)
  }

  const handleLaunchRequest = () => {
    if (usesLegacyReuseSchedule) {
      setScheduleAttemptErrors([])
      openPostPlanningFlow()
      return
    }

    const missingDays = (schedulePlan.days || []).filter(
      (day) => formationMode !== 'existing' && !day.templateName,
    )
    const errors = []
    if (missingDays.length) {
      errors.push(
        `Associez un template à ${missingDays.map(
          (day) => `la journée ${day.dayNumber} (${day.label})`,
        ).join(', ')}.`,
      )
    }
    for (const error of schedulePlan.validation?.errors || []) {
      if (missingDays.length && error.startsWith('Affectez un template')) continue
      errors.push(error)
    }

    const uniqueErrors = [...new Set(errors)]
    if (uniqueErrors.length) {
      setScheduleAttemptErrors(uniqueErrors)
      setScheduleReviewOpen(false)
      return
    }

    setScheduleAttemptErrors([])
    openPostPlanningFlow()
  }

  const confirmScheduleAndCreate = () => {
    if (slideBrandEnabled && !slideBrandName.trim()) return
    setScheduleReviewOpen(false)
    onCreate(
      teacherDescription,
      usesLegacyReuseSchedule ? legacySchedulePayload : schedulePlan.payload,
      slideBrandEnabled ? slideBrandName.trim() : '',
    )
  }

  useEffect(() => {
    if (!descriptionEditedRef.current) setTeacherDescription(generatedDescription)
  }, [generatedDescription])

  useEffect(() => {
    if (!scheduleReviewOpen) return undefined
    const closeOnEscape = (event) => {
      if (event.key === 'Escape' && !creating) setScheduleReviewOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [creating, scheduleReviewOpen])

  const toggleTeachingDay = (dayId) => {
    setTeachingDays((current) => (
      current.includes(dayId)
        ? current.filter((day) => day !== dayId)
        : [...current, dayId]
    ))
  }
  const legacySchedulePayload = {
    schedule_schema_version: 1,
    total_training_days: trainingDays,
    weekly_course_count: Number(weeklyCourseCount),
    weekdays: teachingDays,
    start_date: scheduleStartDate,
    start_time: scheduleStartTime,
  }
  const inputClassName = 'teacher-identity-control w-full rounded-lg border border-[#E1E5EA] bg-white px-3.5 py-2.5 text-sm text-[#0F172A] transition-[border-color,box-shadow,background-color] placeholder:text-[#64748B]'

  return (
    <section
      className={`create-platform-workspace${identityEditorOpen ? ' create-platform-workspace--identity-open' : ''}${templateRedirecting ? ' create-platform-workspace--template-redirecting' : ''}`}
      aria-busy={templateRedirecting || undefined}
    >
      <div className="create-platform-workspace__layout">
        <div className="create-platform-workspace__editor">
          <div className="create-platform-workspace__schedule">
            {usesLegacyReuseSchedule ? (
              <section className="create-platform-workspace__legacy" aria-labelledby="legacy-schedule-title">
                <h2 id="legacy-schedule-title" className="text-lg font-semibold text-[#18181B]">
                  Calendrier du module historique
                </h2>
                <p className="mt-1.5 text-sm leading-6 text-[#52525B]">
                  Ce professeur conserve son déroulé historique. Choisissez uniquement les nouvelles dates selon son calendrier classique.
                </p>

                <div className="mt-5 grid gap-4 md:grid-cols-2">
                  <div>
                    <label htmlFor="legacy-weekly-count" className="mb-2 block text-sm font-medium text-[#3F3F46]">
                      Journées par semaine
                    </label>
                    <input
                      id="legacy-weekly-count"
                      type="number"
                      value={weeklyCourseCount}
                      onChange={(event) => setWeeklyCourseCount(event.target.value)}
                      min="1"
                      max="5"
                      className={inputClassName}
                    />
                  </div>
                  <div>
                    <label htmlFor="legacy-start-date" className="mb-2 block text-sm font-medium text-[#3F3F46]">
                      Début de la formation
                    </label>
                    <input
                      id="legacy-start-date"
                      type="date"
                      value={scheduleStartDate}
                      min={todayDateInput()}
                      onChange={(event) => setScheduleStartDate(event.target.value)}
                      className={inputClassName}
                    />
                  </div>
                </div>

                <fieldset className="mt-5">
                  <legend className="mb-2 text-sm font-medium text-[#3F3F46]">
                    Jours de formation
                  </legend>
                  <div className="grid grid-cols-5 gap-2">
                    {weekDays.map((day) => {
                      const selected = teachingDays.includes(day.id)
                      return (
                        <button
                          key={day.id}
                          type="button"
                          onClick={() => toggleTeachingDay(day.id)}
                          aria-pressed={selected}
                          className={`min-h-11 rounded-lg border px-2 py-2 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/40 ${
                            selected
                              ? 'border-[#18181B] bg-[#18181B] text-white'
                              : 'border-[#D4D4D8] bg-white text-[#3F3F46] hover:bg-[#F4F4F5]'
                          }`}
                        >
                          {day.label}
                        </button>
                      )
                    })}
                  </div>
                  {Number(weeklyCourseCount) !== teachingDays.length && (
                    <p className="mt-2 text-xs font-medium text-[#52525B]" role="status">
                      Choisissez {weeklyCourseCount || 0} jour{Number(weeklyCourseCount) > 1 ? 's' : ''} pour correspondre au rythme hebdomadaire.
                    </p>
                  )}
                </fieldset>

                <div className="mt-5 flex min-h-11 items-center justify-between rounded-lg border border-[#D4D4D8] bg-[#F4F4F5] px-3.5 py-2.5 text-sm">
                  <span className="font-semibold text-[#18181B]">09:00</span>
                  <span className="text-xs text-[#71717A]">Horaire historique fixe</span>
                </div>
              </section>
            ) : (
              <FormationSchedulePlanner
                key={`${formationMode}:${selectedModuleId || 'new'}`}
                reuse={formationMode === 'existing'}
                expectedDayCount={formationMode === 'existing' ? trainingDays : null}
                initialSchedule={initialScheduleV2}
                startDateHint={scheduleStartDate}
                approximateDayCount={formationMode === 'existing' ? trainingDays : newFormHours}
                daysPerWeekHint={weeklyCourseCount}
                preferredWeekdaysHint={teachingDays}
                identityComplete={Boolean(
                  teacherFirstName.trim()
                  && (formationMode === 'existing' ? selectedModule : newFormTpName.trim() && newFormRncp.trim())
                )}
                onRequestIdentity={() => setIdentityEditorOpen(true)}
                onCreateTemplate={onCreateTemplate}
                onChange={handleSchedulePlanChange}
                onValidate={handleLaunchRequest}
                validating={creating}
              />
            )}
          </div>

          {scheduleAttemptErrors.length > 0 && (
            <div className="create-platform-workspace__error" role="alert">
              <button
                type="button"
                className="create-platform-workspace__error-close"
                onClick={() => setScheduleAttemptErrors([])}
                aria-label="Masquer les erreurs du planning"
              >
                <X size={16} strokeWidth={1.8} aria-hidden="true" />
              </button>
              <strong>Planning à compléter</strong>
              <ul>
                {scheduleAttemptErrors.map((error) => <li key={error}>{error}</li>)}
              </ul>
            </div>
          )}

          {submissionError && (
            <div className="create-platform-workspace__error" role="alert">
              <div className="flex items-start gap-2.5">
                <Icon name="error_outline" className="mt-0.5 text-base" />
                <span>{submissionError}</span>
              </div>
            </div>
          )}

        </div>
      </div>

      {identityEditorOpen && (
        <section
          id="teacher-identity-editor"
          className="create-platform-workspace__identity-panel"
          aria-labelledby="teacher-identity-editor-title"
        >
          <header>
            <div>
              <h2 id="teacher-identity-editor-title">Identité du professeur</h2>
              <p>Ces informations apparaissent sur sa fiche.</p>
            </div>
            <button
              type="button"
              onClick={() => setIdentityEditorOpen(false)}
            >
              Terminer
            </button>
          </header>

          <div className="create-platform-workspace__identity-fields">
            <div>
              <label htmlFor="teacher-first-name">Prénom</label>
              <input id="teacher-first-name" type="text" value={teacherFirstName} onChange={(event) => setTeacherFirstName(event.target.value)} placeholder="Ex. Pierre" autoFocus className={inputClassName} />
            </div>

            {formationMode === 'existing' ? (
              <div className="create-platform-workspace__existing-module">
                <span>Formation conservée</span>
                <div>
                  <p className="text-sm font-semibold text-[#0F172A]">{selectedModule?.tp_name || 'Professeur introuvable'}</p>
                  <p className="text-xs text-[#64748B]">{selectedModule?.rncp_code ? `RNCP ${selectedModule.rncp_code}` : 'Formation archivée'}</p>
                </div>
              </div>
            ) : (
              <>
                <div>
                  <label htmlFor="teacher-training-name">Formation</label>
                  <input id="teacher-training-name" type="text" value={newFormTpName} onChange={(event) => setNewFormTpName(event.target.value)} placeholder="Ex. TP CRCD" className={inputClassName} />
                </div>
                <div>
                  <label htmlFor="teacher-rncp">Code RNCP</label>
                  <input id="teacher-rncp" type="text" value={newFormRncp} onChange={(event) => setNewFormRncp(event.target.value)} placeholder="Ex. 35304" className={inputClassName} />
                </div>
              </>
            )}
          </div>

          {prefilledFromAssistant && (
            <p className="create-platform-workspace__prefilled recruitment-review-enter" role="status">
              <Icon name="check_circle" className="text-base" />
              Informations préremplies
            </p>
          )}

          <footer className="create-platform-workspace__identity-actions">
            <div>
              <p>{paymentRequired ? (billing?.review_required === false ? 'Tarif à régler maintenant' : 'Tarif après validation') : 'Compte interne'}</p>
              <strong>{paymentRequired ? formatPrice(estimatedAmountCents, product?.currency) : 'Paiement non requis'}</strong>
            </div>
            <div>
              <button type="button" onClick={onCancel} disabled={creating}>Annuler</button>
              <button type="button" onClick={handleLaunchRequest} disabled={creating || !canCreateTeacher}>
                {creating ? 'Envoi de la demande…' : billingLoading ? 'Chargement du tarif…' : paymentRequired ? billing ? (billing.review_required === false ? 'Continuer vers le paiement' : 'Envoyer la demande') : 'Service temporairement indisponible' : formationMode === 'existing' ? 'Réutiliser ce professeur' : 'Lancer la préparation'}
              </button>
            </div>
          </footer>

        </section>
      )}

      {templateRedirecting && (
        <div className="create-platform-workspace__draft-transition" role="status" aria-live="polite">
          <div className="create-platform-workspace__draft-transition-content">
            <span className="create-platform-workspace__draft-transition-icon" aria-hidden="true">
              <FileCheck2 size={26} strokeWidth={1.8} />
            </span>
            <p className="create-platform-workspace__draft-transition-kicker">Brouillon sauvegardé</p>
            <h2>Votre progression est enregistrée</h2>
            <p className="create-platform-workspace__draft-transition-copy">
              Vous pourrez reprendre votre progression après avoir créé votre template.
            </p>

            <div className="create-platform-workspace__draft-route" aria-hidden="true">
              <span className="create-platform-workspace__draft-route-node create-platform-workspace__draft-route-node--saved">
                <FileCheck2 size={17} strokeWidth={1.8} />
                Brouillon
              </span>
              <span className="create-platform-workspace__draft-route-track">
                <span />
              </span>
              <span className="create-platform-workspace__draft-route-node create-platform-workspace__draft-route-node--target">
                <LayoutTemplate size={17} strokeWidth={1.8} />
                Organisation des cours
              </span>
            </div>

            <p className="create-platform-workspace__draft-transition-status">
              Ouverture de l’éditeur de template…
            </p>
          </div>
        </div>
      )}

      {scheduleReviewOpen && createPortal(
        <div className="fixed inset-0 z-[90] flex items-end justify-center bg-black/45 sm:items-center sm:p-5">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby={postPlanningStep === 'voice' ? 'teacher-voice-title' : 'slide-brand-title'}
            className="flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-2xl bg-white text-[#18181B] sm:max-w-[760px] sm:rounded-2xl"
          >
            <header className="border-b border-[#E4E4E7] px-5 py-4 sm:px-6">
              <ol className="flex items-center gap-2 text-xs font-semibold text-[#71717A]" aria-label="Étapes de finalisation">
                <li className={postPlanningStep === 'voice' ? 'text-[#18181B]' : ''}>1. Voix</li>
                <li aria-hidden="true">›</li>
                <li className={postPlanningStep === 'slides' ? 'text-[#18181B]' : ''}>2. Diapositives</li>
              </ol>
            </header>

            {postPlanningStep === 'voice' ? (
              <>
                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
                  <h2 id="teacher-voice-title" className="text-lg font-semibold tracking-[-0.02em] text-[#18181B]">
                    Choisissez la voix du professeur
                  </h2>
                  <p className="mt-1.5 max-w-[65ch] text-sm leading-6 text-[#52525B]">
                    Cette voix sera utilisée pour tous les cours, les transitions et les séquences audio de la formation.
                  </p>

                  <div className="mt-5 grid gap-2" role="radiogroup" aria-labelledby="teacher-voice-title">
                    {[
                      {
                        id: '',
                        name: 'Voix Fish Audio par défaut',
                        description: 'Voix standard disponible immédiatement',
                      },
                      ...(aiVoices || []).map((voice) => ({
                        id: String(voice.id),
                        name: voice.name,
                        description: voice.measured_wpm
                          ? `Débit calibré à ${Math.round(voice.measured_wpm)} mots par minute`
                          : 'Voix personnalisée de votre centre',
                      })),
                    ].map((voice) => {
                      const selected = String(selectedAiVoiceId || '') === voice.id
                      return (
                        <button
                          key={voice.id || 'default'}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          onClick={() => setSelectedAiVoiceId(voice.id)}
                          className={`flex min-h-16 w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/35 ${selected ? 'border-[#18181B] bg-[#F4F4F5]' : 'border-[#D4D4D8] bg-white hover:bg-[#FAFAFA]'}`}
                        >
                          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${selected ? 'bg-[#18181B] text-white' : 'bg-[#F1F1F0] text-[#52525B]'}`} aria-hidden="true">
                            <AudioWaveform size={17} strokeWidth={1.8} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <strong className="block truncate text-sm font-semibold text-[#18181B]">{voice.name}</strong>
                            <span className="mt-0.5 block text-xs leading-5 text-[#52525B]">{voice.description}</span>
                          </span>
                          <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${selected ? 'border-[#18181B] bg-[#18181B] text-white' : 'border-[#A1A1AA] text-transparent'}`} aria-hidden="true">
                            <Icon name="check" className="text-sm" />
                          </span>
                        </button>
                      )
                    })}
                  </div>

                  {(aiVoices || []).length === 0 && (
                    <p className="mt-3 text-xs leading-5 text-[#64748B]">
                      Aucune voix personnalisée n’est enregistrée. Vous pouvez continuer avec la voix par défaut.
                    </p>
                  )}
                </div>

                <footer className="flex flex-wrap justify-end gap-2 border-t border-[#E4E4E7] bg-[#FAFAFA] px-5 py-4 sm:px-6">
                  <button
                    type="button"
                    onClick={() => setScheduleReviewOpen(false)}
                    disabled={creating}
                    className="min-h-11 rounded-lg border border-[#D4D4D8] bg-white px-4 text-sm font-semibold text-[#3F3F46] hover:bg-[#F4F4F5] disabled:opacity-50"
                  >
                    Revenir au planning
                  </button>
                  <button
                    type="button"
                    onClick={() => setPostPlanningStep('slides')}
                    disabled={creating}
                    className="min-h-11 rounded-lg bg-[#18181B] px-4 text-sm font-semibold text-white hover:bg-[#27272A] disabled:bg-[#A1A1AA]"
                  >
                    Continuer vers les diapositives
                  </button>
                </footer>
              </>
            ) : (
              <>
                <div className="min-h-0 flex-1 overflow-y-auto">
                  <section className="grid gap-5 px-5 py-5 sm:grid-cols-[minmax(0,1fr)_240px] sm:px-6" aria-labelledby="slide-brand-title">
                    <div>
                      <h2 id="slide-brand-title" className="text-lg font-semibold tracking-[-0.02em] text-[#18181B]">
                        Nom de votre centre de formation sur les diapositives
                      </h2>
                      <p className="mt-1.5 text-sm leading-6 text-[#52525B]">
                        Souhaitez-vous afficher le nom de votre centre de formation en haut à gauche des diapositives présentées par le professeur ?
                      </p>

                      <div className="mt-4 flex gap-2" role="group" aria-label="Personnaliser les diapositives">
                        <button
                          type="button"
                          aria-pressed={slideBrandEnabled}
                          onClick={() => setSlideBrandEnabled(true)}
                          className={`min-h-10 rounded-lg border px-3.5 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/30 ${slideBrandEnabled ? 'border-[#18181B] bg-[#18181B] text-white' : 'border-[#D4D4D8] bg-white text-[#52525B] hover:bg-[#F4F4F5]'}`}
                        >
                          Oui, personnaliser
                        </button>
                        <button
                          type="button"
                          aria-pressed={!slideBrandEnabled}
                          onClick={() => setSlideBrandEnabled(false)}
                          className={`min-h-10 rounded-lg border px-3.5 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/30 ${!slideBrandEnabled ? 'border-[#18181B] bg-[#18181B] text-white' : 'border-[#D4D4D8] bg-white text-[#52525B] hover:bg-[#F4F4F5]'}`}
                        >
                          Non
                        </button>
                      </div>

                      {slideBrandEnabled ? (
                        <div className="mt-4">
                          <label htmlFor="slide-brand-name" className="mb-1.5 block text-sm font-medium text-[#3F3F46]">
                            Nom du centre de formation
                          </label>
                          <input
                            id="slide-brand-name"
                            type="text"
                            value={slideBrandName}
                            maxLength={120}
                            onChange={(event) => setSlideBrandName(event.target.value)}
                            placeholder="Ex. Atelier Martin"
                            autoComplete="organization"
                            className={inputClassName}
                            aria-describedby="slide-brand-hint"
                          />
                          <p id="slide-brand-hint" className="mt-1.5 text-xs leading-5 text-[#64748B]">
                            Ce nom sera reproduit à l’identique sur toutes les diapositives de cette formation.
                          </p>
                        </div>
                      ) : (
                        <p className="mt-4 text-xs leading-5 text-[#64748B]">
                          Aucun nom ne sera affiché sur les diapositives.
                        </p>
                      )}
                    </div>

                    <div>
                      <p className="mb-2 text-xs font-semibold text-[#52525B]">Aperçu</p>
                      <div className="overflow-hidden rounded-lg border border-[#D4D4D8] bg-[#020617]">
                        <SlidePreviewFrame
                          slide={{
                            template_type: 'reprise_recap',
                            data: {
                              title: 'On reprend le fil.',
                              points: ['Double obligation de prix', 'Une étiquette claire', 'La confiance du client'],
                            },
                          }}
                          renderProps={{ brandName: slideBrandEnabled ? (slideBrandName.trim() || 'Votre centre') : '' }}
                          maxWidth={240}
                          padding={0}
                        />
                      </div>
                      <p className="mt-2 text-xs leading-5 text-[#71717A]">Le contenu de la diapositive reste inchangé.</p>
                    </div>
                  </section>
                </div>

                <footer className="flex flex-wrap justify-end gap-2 border-t border-[#E4E4E7] bg-[#FAFAFA] px-5 py-4 sm:px-6">
                  <button
                    type="button"
                    onClick={() => setPostPlanningStep('voice')}
                    disabled={creating}
                    className="min-h-11 rounded-lg border border-[#D4D4D8] bg-white px-4 text-sm font-semibold text-[#3F3F46] hover:bg-[#F4F4F5] disabled:opacity-50"
                  >
                    Revenir au choix de la voix
                  </button>
                  <button
                    type="button"
                    onClick={confirmScheduleAndCreate}
                    disabled={creating || (slideBrandEnabled && !slideBrandName.trim())}
                    className="min-h-11 rounded-lg bg-[#18181B] px-4 text-sm font-semibold text-white hover:bg-[#27272A] disabled:bg-[#A1A1AA]"
                  >
                    {creating ? 'Préparation en cours…' : 'Valider la demande'}
                  </button>
                </footer>
              </>
            )}
          </section>
        </div>,
        document.body,
      )}
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
  embedded = false,
}) {
  const audioGroups = classifyFormationAudios(audios)
  const audioCount = Object.values(audioGroups).reduce((total, group) => total + group.length, 0)

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
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || !data.success) {
        throw new Error(data.error || data.message || 'Impossible de charger les dossiers audio.')
      }
      setFolders(Array.isArray(data.folders) ? data.folders : [])
    } catch (e) {
      console.error('Erreur chargement dossiers:', e)
      setFolders([])
      setFillResult({ success: false, error: e.message || 'Impossible de charger les dossiers audio.' })
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
        body: JSON.stringify({ folder_id: Number.parseInt(selectedFillFolderId, 10) }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || !data.success) {
        throw new Error(data.error || data.message || 'Impossible de copier les audios.')
      }
      setFillResult(data)
      if (onRefreshAudios) {
        onRefreshAudios()
      }
    } catch (e) {
      console.error('Erreur remplissage:', e)
      setFillResult({ success: false, error: e.message || 'Impossible de copier les audios.' })
    } finally {
      setFilling(false)
    }
  }
  return (
    <div
      className={embedded ? 'h-full min-h-0 w-full' : 'fixed inset-0 z-50 flex items-center justify-center p-4'}
      style={embedded ? undefined : { backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={embedded ? undefined : onClose}
      role={embedded ? 'region' : 'dialog'}
      aria-modal={embedded ? undefined : 'true'}
      aria-labelledby="formation-audios-title"
    >
      <div
        className={embedded ? 'flex h-full min-h-0 w-full flex-col overflow-hidden bg-white' : 'w-full overflow-hidden rounded-2xl bg-white shadow-2xl'}
        style={embedded ? undefined : { maxWidth: '1400px', maxHeight: '90vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className={`flex items-center justify-between border-b border-[#E4E4E7] bg-white ${embedded ? 'gap-2 px-3 py-2' : 'flex-wrap gap-3 px-4 py-4 sm:px-6'}`}>
          {embedded ? (
            <p className="text-[11px] font-medium text-[#71717A]">
              {audioCount} fichier{audioCount > 1 ? 's' : ''}
            </p>
          ) : (
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#18181B] text-white">
              <Icon name="audiotrack" className="text-xl" />
            </div>
            <div>
              <h3 id="formation-audios-title" className="text-base font-semibold text-[#18181B]">
                {embedded ? 'Playlist de la formation' : 'Audios de la formation'}
              </h3>
              <p className="text-sm text-[#71717A]">
                {audioCount} fichier{audioCount > 1 ? 's' : ''} dans la playlist
              </p>
            </div>
          </div>
          )}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleOpenFillModal}
              className={`flex items-center gap-1.5 rounded-lg bg-[#18181B] font-medium text-white transition-colors hover:bg-[#27272A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50 focus-visible:ring-offset-2 ${embedded ? 'min-h-8 px-2.5 py-1 text-xs' : 'min-h-11 px-3 py-2 text-sm sm:px-4'}`}
            >
              <Icon name="drive_folder_upload" className="text-base" />
              <span>{embedded ? 'Remplir' : 'Remplir avec les audios'}</span>
            </button>
            {!embedded && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Fermer"
                className="flex h-11 w-11 items-center justify-center rounded-lg text-[#71717A] transition-colors hover:bg-[#F4F4F5] hover:text-[#18181B] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50 active:scale-[0.98]"
              >
                <Icon name="close" className="text-xl" />
              </button>
            )}
          </div>

          {/* Modal sélection dossier */}
          {showFillModal && (
            <div
              className="fixed inset-0 z-60 flex items-center justify-center p-4"
              style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
              onClick={() => setShowFillModal(false)}
              role="dialog"
              aria-modal="true"
              aria-labelledby="fill-formation-audios-title"
            >
              <div
                className="w-full rounded-2xl bg-white p-5 shadow-2xl sm:p-6"
                style={{ maxWidth: '460px' }}
                onClick={e => e.stopPropagation()}
              >
                <div className="mb-5 flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#18181B]">
                    <Icon name="drive_folder_upload" className="text-white text-xl" />
                  </div>
                  <h4 id="fill-formation-audios-title" className="text-base font-bold text-[#18181B]">Remplir avec les audios</h4>
                </div>

                <p className="mb-4 text-sm leading-6 text-[#71717A]">
                  Choisissez le dossier de cours à utiliser. Tous les fichiers audio réellement présents dans ce dossier seront copiés.
                </p>

                {loadingFolders ? (
                  <div className="flex justify-center py-4">
                    <div className="h-6 w-6 animate-spin rounded-full border-2 border-[#D4D4D8] border-t-[#18181B]" />
                  </div>
                ) : (
                  <select
                    value={selectedFillFolderId}
                    onChange={e => setSelectedFillFolderId(e.target.value)}
                    className="mb-4 min-h-11 w-full rounded-lg px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
                    style={{ border: '1px solid #D4D4D8', color: '#18181B', backgroundColor: '#F4F4F5' }}
                  >
                    <option value="">— Sélectionner un dossier —</option>
                    {folders.map(f => (
                      <option key={f.id} value={f.id}>{f.name}</option>
                    ))}
                  </select>
                )}

                {fillResult && (
                  <div
                    className="mb-4 rounded-xl border border-[#D4D4D8] bg-[#F4F4F5] p-3 text-sm text-[#3F3F46]"
                    role={fillResult.success ? 'status' : 'alert'}
                    style={{
                      borderStyle: fillResult.success ? 'solid' : 'dashed',
                    }}
                  >
                    {fillResult.success
                      ? `✓ ${fillResult.copied} fichiers copiés${fillResult.errors > 0 ? ` (${fillResult.errors} erreur(s))` : ''} depuis "${fillResult.folder_name}"`
                      : `✗ ${fillResult.error}`}
                  </div>
                )}

                <div className="flex justify-end gap-3">
                  <button
                    type="button"
                    onClick={() => setShowFillModal(false)}
                    className="min-h-11 rounded-lg bg-[#F4F4F5] px-4 py-2 text-sm font-medium text-[#52525B] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50"
                  >
                    {fillResult?.success ? 'Fermer' : 'Annuler'}
                  </button>
                  {!fillResult?.success && (
                    <button
                      type="button"
                      onClick={handleFill}
                      disabled={!selectedFillFolderId || filling}
                      className="min-h-11 rounded-lg bg-[#18181B] px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-[#27272A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/50 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-[#A1A1AA]"
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
        <div className={`min-h-0 flex-1 overflow-y-auto ${embedded ? 'p-3' : 'p-4 sm:p-5'}`} style={embedded ? undefined : { maxHeight: 'calc(90vh - 80px)' }}>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#D4D4D8] border-t-[#18181B]" />
            </div>
          ) : audioCount === 0 ? (
            <div className="rounded-xl border border-dashed border-[#D4D4D8] bg-[#FAFAFA] px-5 py-10 text-center">
              <Icon name="graphic_eq" className="text-3xl text-[#71717A]" />
              <p className="mt-3 text-sm font-semibold text-[#18181B]">Aucun audio disponible</p>
              <p className="mt-1 text-sm text-[#71717A]">
                Remplissez la plateforme depuis un dossier généré pour afficher sa playlist.
              </p>
            </div>
          ) : (
            embedded ? (
              <div className="space-y-3">
                {[
                  ['Cours', audioGroups.courses],
                  ['Pauses', audioGroups.pauses],
                  ['Questions-réponses', audioGroups.questions],
                  ...(audioGroups.other.length ? [['Autres audios', audioGroups.other]] : []),
                ].map(([title, audios]) => (
                  <section key={title}>
                    <div className="mb-1.5 flex items-center justify-between">
                      <h3 className="text-xs font-semibold text-[#18181B]">{title}</h3>
                      <span className="text-[10px] tabular-nums text-[#71717A]">{audios.length}</span>
                    </div>
                    {audios.length ? (
                      <div className="divide-y divide-[#E4E4E7] overflow-hidden rounded-lg border border-[#E4E4E7]">
                        {audios.map((audio) => (
                          <div key={audio.name} className="flex items-center gap-2 bg-white px-2.5 py-2">
                            <Icon name="check_circle" className="text-sm text-[#71717A]" />
                            <span className="min-w-0 flex-1 truncate text-[11px] text-[#3F3F46]" title={audio.name}>
                              {audio.displayName}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="rounded-lg bg-[#FAFAFA] px-2.5 py-2 text-[11px] text-[#A1A1AA]">Aucun fichier</p>
                    )}
                  </section>
                ))}
              </div>
            ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {/* Carte COURS */}
              <AudioCard
                title="Cours"
                icon="/cours.jpg"
                audios={audioGroups.courses}
              />

              {/* Carte PAUSES */}
              <AudioCard
                title="Pauses"
                icon="/break-time.jpg"
                audios={audioGroups.pauses}
              />

              {/* Carte Q&A */}
              <AudioCard
                title="Questions-réponses"
                icon="/qa.jpg"
                audios={audioGroups.questions}
              />
              {audioGroups.other.length > 0 && (
                <AudioCard
                  title="Autres audios"
                  icon="/cours.jpg"
                  audios={audioGroups.other}
                />
              )}
            </div>
            )
          )}
        </div>
      </div>
    </div>
  )
}

// ─── PDF Modal ───────────────────────────────────────────────────────────────
function PDFModal({ platform, onClose, onUpload, onDelete, uploading, embedded = false }) {
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
      className={embedded ? 'h-full min-h-0 w-full' : 'fixed inset-0 z-50 flex items-center justify-center p-4'}
      style={embedded ? undefined : { backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={embedded ? undefined : onClose}
    >
      <div
        className={embedded ? 'flex h-full min-h-0 w-full flex-col overflow-hidden bg-white' : 'w-full overflow-hidden rounded-2xl bg-white shadow-2xl'}
        style={embedded ? undefined : { maxWidth: '1200px', maxHeight: '90vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        {!embedded && (
        <div className="flex items-center justify-between border-b px-6 py-4" style={{ borderColor: '#e2e8f0', backgroundColor: '#ffffff' }}>
          <div className="flex items-center gap-3" style={{ color: '#0f172a' }}>
            <Icon name="picture_as_pdf" className="text-2xl" />
            <h3 className="text-lg font-semibold">Gestion du PDF</h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100"
            aria-label="Fermer la gestion du PDF"
          >
            <Icon name="close" className="text-2xl" />
          </button>
        </div>
        )}

        {/* Modal Body */}
        <div className={`min-h-0 flex-1 overflow-y-auto ${embedded ? 'p-3' : 'p-5 sm:p-6'}`} style={embedded ? undefined : { maxHeight: 'calc(90vh - 80px)' }}>
          <section className={`rounded-xl border ${embedded ? 'mb-3 p-3' : 'mb-6 p-4'}`} style={{ borderColor: '#e2e8f0', backgroundColor: '#F8F7F5' }}>
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <h4 className="text-sm font-semibold" style={{ color: '#111418' }}>Supports de cours générés</h4>
                <p className={`mt-1 text-xs ${embedded ? 'leading-4' : 'leading-5'}`} style={{ color: '#64748b' }}>
                  Un PDF sans balises techniques est créé pour chaque journée dès la fin de la pipeline.
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
                  className="flex min-h-9 items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-[#121212] transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30"
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
                    className="flex items-center justify-between gap-3 rounded-lg bg-white px-3 py-2.5 text-sm transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30"
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
          <div className={`grid grid-cols-1 ${embedded ? 'gap-4' : 'gap-6 2xl:grid-cols-2'}`}>
            {/* PDF Viewer */}
            <div className="flex flex-col">
              <h4 className={`${embedded ? 'mb-2 text-xs font-semibold' : 'mb-3 text-sm font-bold'}`} style={{ color: '#111418' }}>{embedded ? 'PDF actuel' : 'PDF ACTUEL'}</h4>
              {platform.pdf_filename && platform.pdf_url ? (
                embedded ? (
                  <div className="flex items-center gap-2 rounded-lg border border-[#E2E8F0] bg-white p-2.5">
                    <Icon name="picture_as_pdf" className="text-lg text-[#64748B]" />
                    <span className="min-w-0 flex-1 truncate text-xs font-medium text-[#334155]">{platform.pdf_filename}</span>
                    <a
                      href={platform.pdf_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-md bg-[#F1F5F9] px-2 py-1 text-[11px] font-medium text-[#475569]"
                    >
                      Ouvrir
                    </a>
                    <button type="button" onClick={onDelete} aria-label="Supprimer le PDF actuel" className="flex size-7 items-center justify-center rounded-md text-[#64748B] hover:bg-rose-50 hover:text-rose-600">
                      <Icon name="delete_outline" className="text-sm" />
                    </button>
                  </div>
                ) : (
                <div className="flex flex-1 flex-col overflow-hidden rounded-lg border" style={{ borderColor: '#e2e8f0', minHeight: embedded ? '360px' : '500px' }}>
                  <div className="flex items-center justify-between px-4 py-2 border-b" style={{ borderColor: '#e2e8f0', backgroundColor: '#F8F7F5' }}>
                    <span className="text-sm font-medium truncate" style={{ color: '#64748b' }}>{platform.pdf_filename}</span>
                    <div className="ml-2 flex flex-shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => setIframeKey(k => k + 1)}
                        className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs transition-colors hover:bg-slate-200"
                        style={{ color: '#64748b', backgroundColor: '#f1f5f9' }}
                        title="Recharger le PDF"
                      >
                        <Icon name="refresh" className="text-sm" />
                        <span>Recharger</span>
                      </button>
                      <button
                        type="button"
                        onClick={onDelete}
                        className="flex h-7 w-7 items-center justify-center rounded-lg transition-colors hover:bg-rose-50 hover:text-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40"
                        style={{ color: '#64748b' }}
                        aria-label="Supprimer le PDF actuel"
                      >
                        <Icon name="delete_outline" className="text-sm" />
                      </button>
                    </div>
                  </div>
                  <iframe
                    key={iframeKey}
                    src={`https://docs.google.com/viewer?url=${encodeURIComponent(platform.pdf_url)}&embedded=true`}
                    className="flex-1 w-full"
                    style={{ minHeight: embedded ? '310px' : '450px' }}
                    title="PDF Viewer"
                  />
                </div>
                )
              ) : (
                <div className="flex flex-1 items-center justify-center rounded-lg border-2 border-dashed" style={{ borderColor: '#e2e8f0', minHeight: embedded ? '72px' : '500px' }}>
                  <div className="text-center">
                    <Icon name="picture_as_pdf" className={embedded ? 'mb-1 text-2xl' : 'mb-3 text-6xl'} style={{ color: '#cbd5e1' }} />
                    <p className="text-sm" style={{ color: '#94a3b8' }}>Aucun PDF uploadé</p>
                  </div>
                </div>
              )}
            </div>

            {/* Upload Section */}
            <div className="flex flex-col">
              <h4 className={`${embedded ? 'mb-2 text-xs font-semibold' : 'mb-3 text-sm font-bold'}`} style={{ color: '#111418' }}>{embedded ? 'Ajouter un PDF' : 'UPLOADER UN NOUVEAU PDF'}</h4>

              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => !uploading && fileInputRef.current?.click()}
                className="flex-1 flex flex-col items-center justify-center border-2 border-dashed rounded-lg cursor-pointer transition-all"
                style={{
                  borderColor: dragOver ? '#121212' : '#e2e8f0',
                  backgroundColor: dragOver ? 'rgba(18, 18, 18, 0.04)' : 'transparent',
                  minHeight: embedded ? '120px' : '500px',
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
                <div className={`flex flex-col items-center text-center ${embedded ? 'gap-2 px-3' : 'gap-4 px-6'}`}>
                  {uploading ? (
                    <>
                      <div className="h-16 w-16 animate-spin rounded-full border-4 border-slate-200 border-t-[#121212]" />
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
                      <p className="text-left text-base font-semibold leading-snug" style={{ color: '#121212' }}>
                        Le chatbot a bien été alimenté à partir du contenu du cours de cette semaine !
                      </p>
                    </div>
                  ) : (
                    <>
                      <div className={`flex items-center justify-center rounded-full ${embedded ? 'size-10' : 'size-20'}`} style={{ backgroundColor: 'rgba(18, 18, 18, 0.08)' }}>
                        <Icon name="cloud_upload" className={embedded ? 'text-2xl' : 'text-5xl'} style={{ color: '#121212' }} />
                      </div>
                      <div>
                        <h3 className={`${embedded ? 'text-xs font-semibold' : 'mb-2 text-lg font-bold'}`} style={{ color: '#111418' }}>
                          {embedded ? 'Déposer ou choisir un PDF' : 'Glissez votre PDF ici'}
                        </h3>
                        {!embedded && <p className="text-sm" style={{ color: '#64748b' }}>ou cliquez pour parcourir</p>}
                        <p className={embedded ? 'mt-1 text-[10px]' : 'mt-2 text-xs'} style={{ color: '#94a3b8' }}>PDF uniquement</p>
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
function AudioCard({ title, icon, audios }) {
  return (
    <section className="flex flex-col rounded-2xl border border-[#E4E4E7] bg-white p-5 shadow-sm sm:p-6">
      <div className="mb-4 flex items-center gap-3 border-b border-[#E4E4E7] pb-4">
        <div className="flex size-12 items-center justify-center overflow-hidden rounded-xl border border-[#A1A1AA] bg-[#F4F4F5]">
          <img src={icon} alt="" className="h-full w-full object-cover grayscale" />
        </div>
        <div>
          <h3 className="text-lg font-bold text-[#18181B]">{title}</h3>
          <p className="text-xs text-[#71717A]">
            {audios.length} fichier{audios.length > 1 ? 's' : ''}
          </p>
        </div>
      </div>
      <div className="flex-1 space-y-2">
        {audios.length === 0 ? (
          <p className="rounded-lg bg-[#FAFAFA] px-3 py-4 text-xs text-[#71717A]">
            Aucun fichier de ce type.
          </p>
        ) : audios.map((audio) => (
          <div key={audio.name} className="rounded-lg bg-[#FAFAFA] p-3">
            <div className="flex items-center gap-2">
              <div className="flex size-7 flex-shrink-0 items-center justify-center rounded-full bg-[#18181B] text-white">
                <Icon name="check" className="text-sm" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-[#18181B]" title={audio.name}>
                  {audio.displayName}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

// ─── Platform Card ───────────────────────────────────────────────────────────
// Slide-to-confirm + backup pipeline ne sont plus rendus ici : ils ont été
// déménagés dans CoursFoldersModal (la vue où l'admin voit les audios).
const DEFAULT_REMINDER_SUBJECT = 'Votre cours commence le {date} à {time}'
const DEFAULT_REMINDER_SIGNATURE = "L’équipe Le Socrate"
const DEFAULT_REMINDER_MESSAGE = `Votre cours commence le {date} à {time}.

Cliquez ici pour vous connecter directement : {class_url_connexion}

Cliquez ici pour vous connecter avec votre code {session_code} : {class_url_accueil}`

const REMINDER_VARIABLES = [
  { token: '{date}', label: 'Date' },
  { token: '{time}', label: 'Heure' },
  { token: '{class_url_connexion}', label: 'Lien personnel' },
  { token: '{session_code}', label: 'Code personnel' },
  { token: '{class_url_accueil}', label: 'Lien habituel' },
]

const newReminderRule = () => ({
  name: '',
  trigger_mode: 'relative_minutes',
  days_before: 1,
  minutes_before: 60,
  local_time: '18:00',
  subject_template: DEFAULT_REMINDER_SUBJECT,
  content_template: DEFAULT_REMINDER_MESSAGE,
  signature_template: DEFAULT_REMINDER_SIGNATURE,
  recipient_scope: 'all',
  recipient_ids: [],
  is_active: true,
})

function ReminderRulesPanel({ platformId, recipients, recipientsLoading = false, colors, standalone = false }) {
  const [rules, setRules] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(newReminderRule)
  const [error, setError] = useState('')
  const messageRef = useRef(null)

  useEffect(() => {
    if (import.meta.env.DEV && Number(platformId) < 0) {
      setRules([])
      setError('')
      setLoading(false)
      return undefined
    }
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

  const restoreDefaultMessage = () => {
    setForm((current) => ({
      ...current,
      content_template: DEFAULT_REMINDER_MESSAGE,
    }))
  }

  const insertMessageVariable = (token) => {
    const textarea = messageRef.current
    const start = textarea?.selectionStart ?? form.content_template.length
    const end = textarea?.selectionEnd ?? start
    const nextMessage = `${form.content_template.slice(0, start)}${token}${form.content_template.slice(end)}`
    setForm((current) => ({ ...current, content_template: nextMessage }))
    window.requestAnimationFrame(() => {
      textarea?.focus()
      textarea?.setSelectionRange(start + token.length, start + token.length)
    })
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
    <section
      className={standalone ? '' : 'mt-4 border-t pt-4'}
      style={{ borderColor: colors.border }}
      aria-label="Rappels automatiques"
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold" style={{ color: colors.text }}>Rappels automatiques</h4>
          <p className="mt-0.5 text-xs" style={{ color: colors.textMuted }}>
            Chaque élève reçoit son propre lien d’accès. Tous les rappels cochés seront envoyés.
          </p>
        </div>
        {!editingId && (
          <button
            type="button"
            onClick={() => setEditingId('new')}
            className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black"
            style={{ backgroundColor: colors.cardBg, color: colors.text, border: `1px solid ${colors.border}` }}
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
                className="h-4 w-4 accent-black"
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
              <input required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-black/25" style={inputStyle} />
            </label>
            <label className="text-xs font-medium" style={{ color: colors.textSecondary }}>
              Déclenchement
              <select value={form.trigger_mode} onChange={(e) => setForm({ ...form, trigger_mode: e.target.value })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-black/25" style={inputStyle}>
                <option value="relative_minutes">Délai avant le cours</option>
                <option value="local_day_time">Jour et heure précis</option>
              </select>
            </label>
          </div>

          {form.trigger_mode === 'local_day_time' ? (
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs font-medium" style={{ color: colors.textSecondary }}>
                Jours avant
                <input type="number" min="0" max="365" required value={form.days_before} onChange={(e) => setForm({ ...form, days_before: Number(e.target.value) })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-black/25" style={inputStyle} />
              </label>
              <label className="text-xs font-medium" style={{ color: colors.textSecondary }}>
                Heure d’envoi
                <input type="time" required max={Number(form.days_before) === 0 ? '08:59' : undefined} value={form.local_time} onChange={(e) => setForm({ ...form, local_time: e.target.value })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-black/25" style={inputStyle} />
              </label>
            </div>
          ) : (
            <label className="block text-xs font-medium" style={{ color: colors.textSecondary }}>
              Minutes avant le cours
              <input type="number" min="1" max="525600" required value={form.minutes_before} onChange={(e) => setForm({ ...form, minutes_before: Number(e.target.value) })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-black/25" style={inputStyle} />
            </label>
          )}

          <label className="block text-xs font-medium" style={{ color: colors.textSecondary }}>
            Objet de l’e-mail
            <input required maxLength={200} value={form.subject_template} onChange={(e) => setForm({ ...form, subject_template: e.target.value })} placeholder="Votre formation commence bientôt" className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none placeholder:text-slate-500 focus:ring-2 focus:ring-black/25" style={inputStyle} />
          </label>
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <label htmlFor={`reminder-message-${editingId}`} className="text-xs font-medium" style={{ color: colors.textSecondary }}>
                Message
              </label>
              <button
                type="button"
                onClick={restoreDefaultMessage}
                className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] font-semibold transition-colors hover:bg-black/5 focus:outline-none focus:ring-2 focus:ring-black/25"
                style={{ color: colors.textSecondary }}
              >
                <RotateCcw size={13} aria-hidden="true" />
                Rétablir le message par défaut
              </button>
            </div>
            <textarea
              ref={messageRef}
              id={`reminder-message-${editingId}`}
              required
              maxLength={5000}
              rows={7}
              value={form.content_template}
              onChange={(e) => setForm({ ...form, content_template: e.target.value })}
              placeholder="Rédigez le message envoyé aux élèves."
              className="mt-1 w-full resize-y rounded-lg px-2.5 py-2 text-sm leading-6 outline-none placeholder:text-slate-500 focus:ring-2 focus:ring-black/25"
              style={inputStyle}
            />
            <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-label="Variables à insérer dans le message">
              <span className="mr-1 text-[11px]" style={{ color: colors.textMuted }}>Insérer :</span>
              {REMINDER_VARIABLES.map((variable) => (
                <button
                  key={variable.token}
                  type="button"
                  onClick={() => insertMessageVariable(variable.token)}
                  title={variable.token}
                  className="rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors hover:bg-black/5 focus:outline-none focus:ring-2 focus:ring-black/25"
                  style={{ border: `1px solid ${colors.border}`, color: colors.textSecondary }}
                >
                  + {variable.label}
                </button>
              ))}
            </div>
          </div>

          <label className="block text-xs font-medium" style={{ color: colors.textSecondary }}>
            Signature
            <input
              maxLength={500}
              value={form.signature_template ?? DEFAULT_REMINDER_SIGNATURE}
              onChange={(e) => setForm({ ...form, signature_template: e.target.value })}
              placeholder="L’équipe Le Socrate"
              className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none placeholder:text-slate-500 focus:ring-2 focus:ring-black/25"
              style={inputStyle}
            />
            <span className="mt-1 block text-[11px] font-normal leading-4" style={{ color: colors.textMuted }}>
              Laissez ce champ vide pour ne pas afficher de signature.
            </span>
          </label>

          <label className="block text-xs font-medium" style={{ color: colors.textSecondary }}>
            Destinataires
            <select value={form.recipient_scope} onChange={(e) => setForm({ ...form, recipient_scope: e.target.value, recipient_ids: e.target.value === 'all' ? [] : form.recipient_ids })} className="mt-1 h-9 w-full rounded-lg px-2.5 outline-none focus:ring-2 focus:ring-black/25" style={inputStyle}>
              <option value="all">Tous les élèves inscrits</option>
              <option value="selected_explicit">Une sélection d’élèves</option>
            </select>
          </label>

          {form.recipient_scope === 'selected_explicit' && (
            <fieldset className="max-h-48 overflow-y-auto rounded-lg" style={{ border: `1px solid ${colors.border}` }}>
              <legend className="ml-2 px-1 text-xs font-medium" style={{ color: colors.textSecondary }}>Élèves inscrits</legend>
              {recipientsLoading ? (
                <div className="space-y-2 p-3" aria-label="Chargement des élèves inscrits">
                  {[0, 1].map((item) => (
                    <div key={item} className="h-9 animate-pulse rounded-lg" style={{ backgroundColor: colors.innerBg }} />
                  ))}
                </div>
              ) : recipients.length === 0 ? (
                <div className="px-3 py-4">
                  <p className="text-xs font-medium" style={{ color: colors.textSecondary }}>Aucun élève inscrit.</p>
                  <p className="mt-1 text-[11px] leading-4" style={{ color: colors.textMuted }}>Ajoutez d’abord un élève depuis l’onglet Élèves.</p>
                </div>
              ) : (
                <div className="divide-y" style={{ borderColor: colors.border }}>
                  {recipients.map((recipient) => {
                    const studentName = [recipient.prenom, recipient.nom].filter(Boolean).join(' ').trim()
                      || `Élève enregistré n°${recipient.id}`
                    return (
                      <label key={recipient.id} className="flex min-h-11 cursor-pointer items-center gap-3 px-3 py-2 text-xs transition-colors hover:bg-black/5" style={{ color: colors.textSecondary }}>
                        <input
                          type="checkbox"
                          checked={form.recipient_ids.includes(recipient.id)}
                          onChange={(e) => setForm({
                            ...form,
                            recipient_ids: e.target.checked
                              ? [...form.recipient_ids, recipient.id]
                              : form.recipient_ids.filter((id) => id !== recipient.id),
                          })}
                          className="h-4 w-4 flex-shrink-0 accent-black"
                        />
                        <Icon name="person" className="text-base" style={{ color: colors.textMuted }} />
                        <span className="min-w-0 flex-1 truncate font-semibold">{studentName}</span>
                      </label>
                    )
                  })}
                </div>
              )}
            </fieldset>
          )}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={resetForm} className="rounded-lg px-3 py-2 text-xs font-semibold" style={{ color: colors.textSecondary }}>Annuler</button>
            <button type="submit" disabled={saving || (form.recipient_scope === 'selected_explicit' && form.recipient_ids.length === 0)} className="rounded-lg bg-[#121212] px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">
              {saving ? 'Enregistrement…' : editingId === 'new' ? 'Créer le rappel' : 'Enregistrer le rappel'}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}

function InvitationsToolContent({ platformId, studentEmails, studentEmailsLoading, colors }) {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-3 sm:px-6">
      <ReminderRulesPanel
        standalone
        platformId={platformId}
        recipients={studentEmails}
        recipientsLoading={studentEmailsLoading}
        colors={colors}
      />
    </div>
  )
}

function StudentsToolContent({
  studentEmails,
  studentEmailsLoading,
  studentEmailsSaving,
  studentEmailDraft,
  onStudentEmailDraftChange,
  onAddStudentEmails,
  onDeleteStudentEmail,
  colors,
}) {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-3 sm:px-6">
      <div className="mb-5 flex items-start justify-between gap-4 border-b pb-4" style={{ borderColor: colors.border }}>
        <div>
          <h3 className="text-sm font-semibold" style={{ color: colors.text }}>Élèves</h3>
          <p className="mt-1 max-w-[62ch] text-xs leading-5" style={{ color: colors.textMuted }}>
            Ajoutez uniquement les élèves qui participeront à cette formation.
          </p>
        </div>
        <span className="text-xs font-semibold tabular-nums" style={{ color: colors.textMuted }}>{studentEmails.length} élève{studentEmails.length > 1 ? 's' : ''}</span>
      </div>

      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1.5fr_auto]">
        {[
          ['prenom', 'Prénom', 'Prénom de l’élève'],
          ['nom', 'Nom', 'Nom de l’élève'],
          ['email', 'Adresse e-mail', 'eleve@exemple.fr'],
        ].map(([field, label, placeholder]) => (
          <label key={field} className="block text-xs font-semibold" style={{ color: colors.textSecondary }}>
            {label}
            <input
              value={studentEmailDraft[field] || ''}
              onChange={(event) => onStudentEmailDraftChange(field, event.target.value)}
              type={field === 'email' ? 'email' : 'text'}
              autoComplete={field === 'email' ? 'email' : field === 'prenom' ? 'given-name' : 'family-name'}
              placeholder={placeholder}
              className="mt-2 h-10 w-full rounded-lg px-3 text-sm outline-none transition-shadow placeholder:text-slate-500 focus:ring-2 focus:ring-black/25"
              style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}`, color: colors.text }}
            />
          </label>
        ))}
        <div className="flex items-end justify-end">
          <button
            type="button"
            onClick={onAddStudentEmails}
            disabled={!studentEmailDraft.prenom?.trim() || !studentEmailDraft.nom?.trim() || !studentEmailDraft.email?.trim() || studentEmailsSaving}
            aria-label="Ajouter l’élève"
            title="Ajouter l’élève"
            className="inline-flex h-10 w-10 flex-none items-center justify-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30 disabled:cursor-not-allowed disabled:opacity-50"
            style={{ backgroundColor: '#121212', color: 'white' }}
          >
            {studentEmailsSaving ? (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
            ) : (
              <Icon name="person_add" style={{ fontSize: '19px' }} />
            )}
          </button>
        </div>
      </div>
      <div className="mb-5 mt-2">
        <p className="text-[11px] leading-4" style={{ color: colors.textMuted }}>
          Le lien et le code personnels utiliseront cette identité.
        </p>
      </div>

      {studentEmailsLoading ? (
        <div className="flex items-center justify-center py-5">
          <div className="h-5 w-5 animate-spin rounded-full border-2" style={{ borderColor: colors.border, borderTopColor: '#121212' }} />
        </div>
      ) : studentEmails.length === 0 ? (
        <div className="border-y px-4 py-7 text-center" style={{ borderColor: colors.border }}>
          <p className="text-xs" style={{ color: colors.textMuted }}>Aucune adresse ajoutée pour le moment.</p>
        </div>
      ) : (
        <div className="max-h-48 space-y-1.5 overflow-y-auto pr-1">
          {studentEmails.map((recipient) => (
            <div
              key={recipient.id}
              className="flex items-center gap-2 rounded-lg px-2.5 py-2"
              style={{ backgroundColor: colors.innerBg, border: `1px solid ${colors.border}` }}
            >
              <Icon name="mail" className="text-sm" style={{ color: colors.textMuted }} />
              <span className="min-w-0 flex-1 truncate text-xs" style={{ color: colors.textSecondary }} title={recipient.email}>
                <strong>{recipient.prenom} {recipient.nom}</strong><span style={{ color: colors.textMuted }}> · {recipient.email}</span>
              </span>
              <button
                type="button"
                onClick={() => onDeleteStudentEmail(recipient.id)}
                className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md transition-colors hover:bg-rose-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/40"
                style={{ color: colors.textMuted }}
                aria-label={`Retirer ${recipient.email}`}
              >
                <Icon name="close" className="text-sm" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function PlatformCard({
  platform: p, audios, audiosLoading,
  colors, darkMode, studentEmails = [], studentEmailsLoading = false,
  studentEmailsSaving = false, studentEmailDraft = '',
  attendanceDate, attendanceData, attendanceLoading = false, attendanceError = '',
  onExpand, onRefreshAudios, onToggleStudentEmails, onToggleAttendance,
  onStudentEmailDraftChange, onAddStudentEmails, onDeleteStudentEmail,
  onAttendanceDateChange, onRefreshAttendance,
  onExportAttendance, onOpenCourseTimeModal, onOpenCoursFolders,
  currentCourseTime, onSetCourseTime, onRetrySessionAudio, onPreviewSessionPostponement,
  onPostponeSession, onAudiosPublished, newlyCreated = false, retryingPreparation = false, onRetryPreparation,
  arrivalTargetRef,
  onBeforeFlip, detailsOpen = false, onOpenDetails, onCloseDetails,
}) {
  const [activeTool, setActiveTool] = useState(null)
  const [fallbackSessionId, setFallbackSessionId] = useState(null)
  const [courseScriptExpanded, setCourseScriptExpanded] = useState(false)
  const creationProgress = getHiddenPipelineProgress(p)
  const preparation = getTeacherPreparation(p)
  const isPreparing = preparation.status === 'preparing'
  const hasFailed = preparation.status === 'failed'
  const nextCourseSession = getNextCourseSession(p)
  const nextCourseSessionLabel = nextCourseSession?.session_index
    ? `Journée ${nextCourseSession.session_index}`
    : 'Prochaine journée'
  const upcomingCourseSessions = (
    Array.isArray(p.course_schedule?.upcoming_sessions)
      ? p.course_schedule.upcoming_sessions
      : nextCourseSession ? [nextCourseSession] : []
  )
  const pastCourseSessions = Array.isArray(p.course_schedule?.past_sessions)
    ? p.course_schedule.past_sessions
    : []
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
    ...(p.active ? [
      { key: 'planning', label: 'Planning', icon: 'schedule', IconComponent: CalendarDays, onOpen: onOpenCourseTimeModal },
      { key: 'courses', label: 'Cours', icon: 'folder_open', IconComponent: FolderOpen, onOpen: onOpenCoursFolders },
      { key: 'invitations', label: 'Mail(s) d’invitation', icon: 'mail', IconComponent: Mail, onOpen: onToggleStudentEmails },
      { key: 'students', label: 'Élèves', icon: 'group', IconComponent: UsersRound, onOpen: onToggleStudentEmails },
      { key: 'attendance', label: 'Présence', icon: 'fact_check', IconComponent: ClipboardCheck, onOpen: onToggleAttendance },
    ] : []),
  ]
  const activeToolMeta = actionItems.find((item) => item.key === activeTool)

  const openTool = async (action, { targetSessionId = null } = {}) => {
    if (!action) return
    if (action.key === 'courses') setFallbackSessionId(targetSessionId)
    await action.onOpen?.()
    setActiveTool(action.key)
  }

  const closeTool = () => {
    onBeforeFlip?.()
    setCourseScriptExpanded(false)
    setActiveTool(null)
  }
  const closeDetails = useCallback(() => {
    onBeforeFlip?.()
    setCourseScriptExpanded(false)
    setActiveTool(null)
    onCloseDetails?.()
  }, [onBeforeFlip, onCloseDetails])

  return (
    <>
      {/* Carte de roster : toute la surface ouvre la fiche, comme chez Delos. */}
      {!detailsOpen && <div className={`w-full self-start ${newlyCreated ? 'teacher-card-enter' : ''}`}>
        <div
          role="button"
          tabIndex={0}
          aria-label={`Ouvrir le professeur ${p.teacher_name || p.name || 'IA'}`}
          onClick={() => {
            onBeforeFlip?.()
            onOpenDetails?.()
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onBeforeFlip?.()
              onOpenDetails?.()
            }
          }}
          className="group relative flex min-h-[332px] cursor-pointer flex-col gap-2 overflow-hidden rounded-2xl p-3 text-left transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/50"
          style={faceStyle}
        >
          <div
            ref={arrivalTargetRef}
            className="relative h-[218px] w-full shrink-0 overflow-hidden rounded-xl"
            style={{ backgroundColor: `${robotTheme.glow}12` }}
            aria-hidden="true"
          >
            <img
              src={robotTheme.src}
              alt=""
              draggable={false}
              className="teacher-card-robot-image h-full w-full select-none object-contain px-2 pt-2 transition-transform duration-200 ease-out group-hover:scale-[1.025] motion-reduce:transition-none"
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

          <ul className="mt-1 h-[52px] space-y-1 overflow-hidden text-[11px] leading-[1.45]" style={{ color: colors.textSecondary }}>
            <li className="flex min-w-0 items-start gap-2">
              <span className="mt-[5px] h-1 w-1 flex-shrink-0 rounded-full" style={{ backgroundColor: rosterMeta.color }} />
              <span className="min-w-0 flex-1 truncate whitespace-nowrap">{rosterMeta.label}{isPreparing ? ` · ${creationProgress}%` : ''}</span>
            </li>
            <li className="flex min-w-0 items-start gap-2">
              <span className="mt-[5px] h-1 w-1 flex-shrink-0 rounded-full" style={{ backgroundColor: '#6C63FF' }} />
              <span className="min-w-0 flex-1 truncate whitespace-nowrap" title={nextCourseSession ? `Prochaine séance ${formatScheduleDateTime(nextCourseSession.scheduled_at)}` : 'Aucune séance programmée'}>
                {nextCourseSession ? `Prochaine séance ${formatScheduleDateTime(nextCourseSession.scheduled_at)}` : 'Aucune séance programmée'}
              </span>
            </li>
            <li className="flex min-w-0 items-start gap-2">
              <span className="mt-[5px] h-1 w-1 flex-shrink-0 rounded-full" style={{ backgroundColor: '#6C63FF' }} />
              <span className="min-w-0 flex-1 truncate whitespace-nowrap">{Number(p.remaining_session_count || 0)} séance(s) restante(s)</span>
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
              {retryingPreparation ? 'Reprise en cours…' : 'Reprendre la pipeline'}
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
      </div>}

      {detailsOpen && (
        <div className={`mx-auto w-full ${courseScriptExpanded ? 'max-w-none px-0' : 'max-w-4xl px-2 sm:px-6'}`}>
          {activeTool !== 'courses' && (
            <button type="button" onClick={activeTool ? closeTool : closeDetails} className="mb-6 inline-flex min-h-11 items-center gap-2 rounded-lg px-2 text-sm font-semibold text-[#52525B] transition-colors hover:bg-[#F4F4F5] hover:text-[#18181B] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30">
              <ChevronLeft size={18} /> {activeTool ? activeToolMeta?.label : 'Mes professeurs'}
            </button>
          )}
          <section
            aria-labelledby={`teacher-details-${p.id}`}
            className="relative flex w-full flex-col overflow-hidden bg-white"
          >
            <div className="relative min-h-0 flex-1 overflow-hidden" style={{ backgroundColor: colors.cardBg }}>
              <div className="relative h-full overflow-hidden">

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
              style={{ borderColor: darkMode ? '#334155' : '#e2e8f0', borderTopColor: '#121212' }} />
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
                className="mt-4 inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-xs font-semibold text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30 disabled:cursor-wait disabled:opacity-60"
                style={{ backgroundColor: '#121212' }}
              >
                <Icon name={retryingPreparation ? 'hourglass_top' : 'refresh'} className="text-[16px]" aria-hidden="true" />
                {retryingPreparation ? 'Reprise en cours…' : 'Reprendre la pipeline'}
              </button>
            )}
          </div>
        </div>
      )}

      {!activeTool && <div className="h-full overflow-y-auto p-6">
        {/* Header — SKU chip + name + status pill, optional meta line below */}
        <div className="mb-5 space-y-2">
          <div className="flex min-w-0 items-center gap-2">
            <h2 id={`teacher-details-${p.id}`} className="truncate text-lg font-semibold leading-tight tracking-tight" style={{ color: '#2563EB' }}>
              {p.teacher_name || p.name || 'Professeur IA'}
            </h2>
          </div>
          <p className="text-xs font-medium" style={{ color: colors.textSecondary }}>
            Professeur du {p.source_tp_name || p.name || 'parcours'}
          </p>
        </div>

        <div className="min-w-0">

        {/* Slide-to-confirm + backup pipeline déménagés vers CoursFoldersModal :
            l'action lock/unlock cohabite désormais avec la vue où on voit
            les audios (modale "Cours"). Le card reste épuré. */}

        <section className="max-w-2xl" aria-label="Outils du professeur">
          <p className="mb-3 text-sm font-semibold text-[#64748B]">Outils</p>
          <div className="divide-y divide-[#E2E8F0] border-y border-[#E2E8F0]">
            {actionItems.map((action) => {
              const ActionIcon = action.IconComponent
              return (
                <button key={action.key} type="button" onClick={() => openTool(action)} className="group flex min-h-14 w-full items-center gap-4 px-1 py-3.5 text-left text-base font-medium text-[#334155] transition-colors hover:text-[#0F172A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/25">
                  <ActionIcon size={20} strokeWidth={1.8} className="text-[#64748B] transition-colors group-hover:text-[#0F172A]" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate">{action.label}</span>
                  <ChevronRight size={16} strokeWidth={1.8} className="text-[#94A3B8]" aria-hidden="true" />
                </button>
              )
            })}
            {p.active && (
              <a href={p.public_url || `${p.frontend_url || window.location.origin}/?p=${p.id}`} target="_blank" rel="noopener noreferrer" className="group flex min-h-14 w-full items-center gap-4 px-1 py-3.5 text-left text-base font-medium text-[#334155] transition-colors hover:text-[#0F172A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/25">
                <Globe2 size={20} strokeWidth={1.8} className="text-[#64748B] transition-colors group-hover:text-[#0F172A]" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate">Lien du cours</span>
                <ExternalLink size={16} strokeWidth={1.8} className="text-[#94A3B8]" aria-hidden="true" />
              </a>
            )}
          </div>
        </section>

        </div>
      </div>}

      {activeTool && (
        <div className={`${courseScriptExpanded ? 'h-[calc(100dvh-7rem)] min-h-[44rem]' : 'h-full min-h-[32rem]'} overflow-hidden bg-white`}>
        <TeacherToolPanel
          title={activeToolMeta?.label || 'Outil'}
          subtitle={`${p.teacher_name || p.name} · Plateforme ${p.center_platform_number || p.id}`}
          icon={activeToolMeta?.icon || 'tune'}
          onBack={closeTool}
          colors={colors}
          darkMode={darkMode}
          showHeader={false}
        >
          {activeTool === 'planning' && (
            <section className="px-4 py-3" aria-labelledby={`teacher-schedule-${p.id}`}>
              <h2 id={`teacher-schedule-${p.id}`} className="text-base font-semibold" style={{ color: colors.text }}>Prochaines séances</h2>
              <p className="mt-1 text-sm leading-6" style={{ color: colors.textSecondary }}>Les séances sont générées automatiquement 72 heures avant leur début.</p>
              {upcomingCourseSessions.length > 0 ? (
                <div className="mt-3 divide-y" style={{ borderColor: colors.border }}>
                  {upcomingCourseSessions.map((session) => (
                    <div key={session.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                      <div>
                        <p className="text-sm font-semibold" style={{ color: colors.text }}>J{session.session_index}</p>
                        <p className="mt-0.5 text-sm" style={{ color: colors.textSecondary }}>{formatScheduleLongDateTime(session.scheduled_at)}</p>
                      </div>
                      <CalendarDays size={18} strokeWidth={1.8} style={{ color: colors.textMuted }} aria-hidden="true" />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm" style={{ color: colors.textSecondary }}>Aucune prochaine séance programmée.</p>
              )}
              <details className="group mt-4 border-t pt-2" style={{ borderColor: colors.border }}>
                <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-1 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/30 [&::-webkit-details-marker]:hidden" style={{ color: colors.text }}>
                  <span>Anciennes séances ({pastCourseSessions.length})</span>
                  <Icon name="expand_more" className="text-xl transition-transform group-open:rotate-180" />
                </summary>
                {pastCourseSessions.length > 0 ? (
                  <div className="divide-y" style={{ borderColor: colors.border }}>
                    {pastCourseSessions.map((session) => (
                      <div key={session.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                        <div>
                          <p className="text-sm font-semibold" style={{ color: colors.text }}>J{session.session_index}</p>
                          <p className="mt-0.5 text-sm" style={{ color: colors.textSecondary }}>{formatScheduleLongDateTime(session.scheduled_at)}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="pb-3 pt-1 text-sm" style={{ color: colors.textSecondary }}>Aucune ancienne séance.</p>
                )}
              </details>
            </section>
          )}
          {activeTool === 'courses' && (
            <CoursFoldersModal
              embedded
              platformId={p.id}
              platformName={p.name}
              targetSessionId={fallbackSessionId}
              onBack={closeTool}
              onAudiosPublished={onAudiosPublished}
              onScriptViewChange={setCourseScriptExpanded}
            />
          )}
          {activeTool === 'students' && (
            <StudentsToolContent
              studentEmails={studentEmails}
              studentEmailsLoading={studentEmailsLoading}
              studentEmailsSaving={studentEmailsSaving}
              studentEmailDraft={studentEmailDraft}
              onStudentEmailDraftChange={onStudentEmailDraftChange}
              onAddStudentEmails={onAddStudentEmails}
              onDeleteStudentEmail={onDeleteStudentEmail}
              colors={colors}
            />
          )}
          {activeTool === 'invitations' && (
            <InvitationsToolContent
              platformId={p.id}
              studentEmails={studentEmails}
              studentEmailsLoading={studentEmailsLoading}
              colors={colors}
            />
          )}
          {activeTool === 'attendance' && (
            <div className="p-3">
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
            </div>
          )}
        </TeacherToolPanel>
        </div>
      )}
            </div>
            </div>
          </section>
        </div>
      )}
    </>
  )
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

function formatScheduleLongDateTime(value) {
  if (!value) return 'Non programmé'
  const normalized = String(value).includes('T') ? value : String(value).replace(' ', 'T')
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Paris',
  })
}

function formatScheduleDateTimeOffset(value, hoursBefore) {
  if (!value) return 'date à confirmer'
  const normalized = String(value).includes('T') ? value : String(value).replace(' ', 'T')
  const scheduledAt = new Date(normalized)
  if (Number.isNaN(scheduledAt.getTime())) return 'date à confirmer'
  const offsetDate = new Date(scheduledAt.getTime() - Number(hoursBefore || 0) * 60 * 60 * 1000)
  return formatScheduleLongDateTime(offsetDate.toISOString())
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
    scheduled: 'L’audio sera préparé automatiquement 72 h avant la nouvelle date.',
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
                <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-[#121212] text-white">
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
                    className="flex min-h-[72px] w-full items-start gap-3 rounded-xl border p-4 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-black/25"
                    style={{ borderColor: mode === 'next_occurrence' ? '#121212' : '#e2e8f0', backgroundColor: '#fff' }}
                  >
                    <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border" style={{ borderColor: mode === 'next_occurrence' ? '#121212' : '#cbd5e1' }}>
                      {mode === 'next_occurrence' && <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: '#121212' }} />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold" style={{ color: '#0f172a' }}>Au prochain créneau prévu</span>
                        <span className="rounded-full bg-[#121212] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">Recommandé</span>
                      </span>
                      <span className="mt-1 block text-xs leading-5" style={{ color: '#64748b' }}>Le cours suivant prend sa place et toute la suite se décale naturellement.</span>
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setMode('specific_date')}
                    className="flex min-h-[68px] w-full items-start gap-3 rounded-xl border p-4 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-black/25"
                    style={{ borderColor: mode === 'specific_date' ? '#121212' : '#e2e8f0', backgroundColor: '#fff' }}
                  >
                    <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border" style={{ borderColor: mode === 'specific_date' ? '#121212' : '#cbd5e1' }}>
                      {mode === 'specific_date' && <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: '#121212' }} />}
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
                    style={{ borderColor: '#cbd5e1', color: '#0f172a', '--tw-ring-color': 'rgba(18, 18, 18, 0.25)' }}
                  />
                  <p className="mt-1.5 text-xs" style={{ color: '#64748b' }}>Le cours commencera à 09:00.</p>
                </div>
              )}

              <div className="rounded-xl border p-4" style={{ borderColor: '#e2e8f0', backgroundColor: '#f8fafc' }} aria-live="polite">
                {previewLoading ? (
                  <div className="flex items-center gap-3 text-sm" style={{ color: '#64748b' }}>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-[#121212]" />
                    Calcul de l’impact sur le planning…
                  </div>
                ) : preview ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: '#94a3b8' }}>Date actuelle</p>
                        <p className="mt-1 text-sm font-semibold capitalize" style={{ color: '#475569' }}>{formatPostponementDay(preview.previous_scheduled_at)}</p>
                      </div>
                      <Icon name="arrow_forward" className="text-lg" style={{ color: '#121212' }} />
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: '#64748b' }}>Nouvelle date</p>
                        <p className="mt-1 text-sm font-semibold capitalize" style={{ color: '#0f172a' }}>{formatPostponementDay(preview.new_scheduled_at)}</p>
                      </div>
                    </div>
                    <div className="flex items-start gap-2 border-t pt-3 text-xs leading-5" style={{ borderColor: '#e9e2ff', color: '#475569' }}>
                      <Icon name="verified" className="mt-0.5 text-base" style={{ color: '#121212' }} />
                      <p><strong style={{ color: '#334155' }}>Aucun cours ne sera perdu.</strong> {preview.affected_session_count > 1 ? `Les ${preview.affected_session_count - 1} cours suivants seront décalés d’un créneau.` : 'Seule cette date sera déplacée.'}</p>
                    </div>
                    <div className="flex items-start gap-2 text-xs leading-5" style={{ color: '#475569' }}>
                      <Icon name="graphic_eq" className="mt-0.5 text-base" style={{ color: '#121212' }} />
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
                  style={{ borderColor: '#cbd5e1', color: '#0f172a', '--tw-ring-color': 'rgba(18, 18, 18, 0.25)' }}
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
                style={{ backgroundColor: '#121212' }}
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
function CourseTimeModal({ onClose, onSubmit, initialDate, schedule, onRetryAudio, onPreviewPostponement, onPostponeSession, embedded = false }) {
  const today = new Date().toISOString().split('T')[0]
  const hasSchedule = !!schedule
  const [date, setDate] = useState(initialDate || today)
  const [heure] = useState('09:00')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [busySessionId, setBusySessionId] = useState(null)
  const [actionError, setActionError] = useState('')
  const [sessionToPostpone, setSessionToPostpone] = useState(null)
  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!date || !heure) return
    setLoading(true)
    setResult(null)
    const data = await onSubmit(date, heure)
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
      className={embedded ? 'h-full min-h-0 w-full' : 'fixed inset-0 z-50 flex items-center justify-center p-4'}
      style={embedded ? undefined : { backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={embedded ? undefined : onClose}
    >
      <div
        role={embedded ? 'region' : 'dialog'}
        aria-modal={embedded ? undefined : 'true'}
        aria-labelledby="course-planning-title"
        className={embedded ? 'flex h-full min-h-0 w-full flex-col overflow-hidden bg-white' : 'overflow-hidden rounded-2xl bg-white'}
        style={embedded ? undefined : { width: '100%', maxWidth: '760px', maxHeight: '92vh', boxShadow: '0 8px 24px rgba(15, 23, 42, 0.18)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        {!embedded && (
        <div className="flex items-center justify-between border-b px-6 py-4" style={{ borderColor: '#e2e8f0', backgroundColor: '#ffffff' }}>
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#121212] text-white">
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
        )}

        {/* Body */}
        <div className={`min-h-0 flex-1 overflow-y-auto ${embedded ? 'p-3' : 'p-5 sm:p-6'}`} style={embedded ? undefined : { maxHeight: 'calc(92vh - 74px)' }}>
          {hasSchedule ? null : result?.success ? (
            <div className="flex flex-col items-center gap-4 py-4 text-center">
              <div className="flex items-center justify-center size-14 rounded-full" style={{ backgroundColor: 'rgba(16, 185, 129, 0.1)' }}>
                <Icon name="check_circle" className="text-4xl" style={{ color: '#10b981' }} />
              </div>
              <p className="text-sm font-medium" style={{ color: '#0f172a' }}>{result.message}</p>
              <button
                onClick={embedded ? () => setResult(null) : onClose}
                className="mt-2 rounded-lg px-5 py-2 text-sm font-semibold text-white transition-colors"
                style={{ backgroundColor: '#121212' }}
              >
                {embedded ? 'Voir le planning' : 'Fermer'}
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
                  style={{ borderColor: '#e2e8f0', color: '#0f172a', backgroundColor: '#F8F7F5' }}
                  onFocus={(e) => { e.currentTarget.style.borderColor = '#121212' }}
                  onBlur={(e) => { e.currentTarget.style.borderColor = '#e2e8f0' }}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1.5" style={{ color: '#334155' }}>
                  Heure de début
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
                  disabled={loading || !date || !heure}
                  className="flex-1 flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition-opacity"
                  style={{ backgroundColor: '#121212', opacity: (loading || !date || !heure) ? 0.6 : 1 }}
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

          {hasSchedule && Array.isArray(schedule.sessions) && (
            <section>
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h4 className="text-sm font-semibold" style={{ color: '#0f172a' }}>Prochaines journées programmées</h4>
                  <p className="mt-0.5 text-xs" style={{ color: '#64748b' }}>
                    Les fichiers sont préparés 72 h avant chaque séance.
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
                        style={{ backgroundColor: '#121212' }}
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
                        style={{ color: '#ffffff', backgroundColor: '#121212' }}
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
