import { useState, useEffect, useRef, useCallback } from 'react'
import { apiUrl } from '../api'
import ReflectionTemplate from '../components/slides/templates/ReflectionTemplate'
import CaseStudyTemplate from '../components/slides/templates/CaseStudyTemplate'
import FacilitatorTemplate from '../components/slides/templates/FacilitatorTemplate'
import ChartTemplate from '../components/slides/templates/ChartTemplate'
import StatsTemplate from '../components/slides/templates/StatsTemplate'
import StoryTemplate from '../components/slides/templates/StoryTemplate'
import RecapTemplate from '../components/slides/templates/RecapTemplate'
import AnalogyTemplate from '../components/slides/templates/AnalogyTemplate'
import WarningTemplate from '../components/slides/templates/WarningTemplate'
import TipTemplate from '../components/slides/templates/TipTemplate'
import OpinionTemplate from '../components/slides/templates/OpinionTemplate'
import TransitionTemplate from '../components/slides/templates/TransitionTemplate'
import PlayfulTemplate from '../components/slides/templates/PlayfulTemplate'

const Icon = ({ name, className = '', style = {} }) => (
  <span className={`material-icons ${className}`} style={{ fontSize: 'inherit', ...style }}>{name}</span>
)

// ─── Statuts qui nécessitent un polling ───────────────────────────────────────
const POLLING_STATUSES = new Set([
  'reac_fetching', 'kb_building', 'global_generating', 'daily_splitting',
  'tts_launched', 'audio_running'
])

const AUDIO_DONE_STATUSES = new Set(['audio_completed', 'audio_launched'])
const AUDIO_ACTIVE_STATUSES = new Set(['audio_running'])
const TEXT_AVAILABLE_STATUSES = new Set([
  'text_ready',
  'tts_launched',
  'audio_running',
  'audio_completed',
  'audio_launched',
  'audio_error',
])
const CONTENT_POLLING_STATUSES = new Set(['tts_launched', 'audio_running'])

// ─── Mapping statut → étape active (0-indexed) ────────────────────────────────
function statusToStep(status, job = null) {
  // Une fois qu'une étape est validée, elle DOIT rester validée même si une
  // étape ultérieure plante (ex: audio_error ne doit pas faire perdre les
  // étapes 1-5 déjà OK). Pour ça, on déduit l'étape max atteinte à partir
  // des CHAMPS CONCRETS du job (champs `*_validated` / `*_ready`) plutôt
  // que du status enum, qui peut être cassé/erreur/inattendu.

  if (!job && !status) return -1
  if (!job) {
    // Sans job, on retombe sur l'enum status pour les premiers états
    if (status === 'init' || status === 'reac_fetching') return 1
    return -1
  }

  // ─── Cascade descendante : on prend l'étape MAX atteinte, peu importe ───
  //    le status. audio_error / audio_launched / tts_launched / etc. ne ────
  //    peuvent pas faire régresser au-delà de ce qui a été validé. ─────────

  // L'audio est désormais une action par dossier, pas une étape de fabrication.
  if (AUDIO_DONE_STATUSES.has(status)) return 6
  if (AUDIO_ACTIVE_STATUSES.has(status)) return 6
  if (status === 'text_ready') return 6

  // Étape 6 (génération texte cours). Une fois tous les textes complétés, le
  // calcul de `currentStep` plus bas avance explicitement à l'étape audio.
  if (status === 'tts_launched') return 5

  // audio_error = on était à l'étape 7 ; les textes restent validés et
  // l'utilisateur peut relancer le TTS.
  if (status === 'audio_error') return 6

  // Étape 5 (programmes journée validés)
  if (job.daily_programs_validated) return 5

  // Étape 4 (programmes journée prêts à valider — daily_programs non vide)
  if (job.daily_programs && job.daily_programs !== '[]' && job.daily_programs !== '"[]"') return 4

  // Étape 4 (global validé)
  if (job.global_program_validated) return 4

  // Étape 3 (programme global prêt à valider)
  if (job.global_program) return 3

  // Étape 3 (KB enrichie disponible)
  if ((job.kb_total || 0) > 0) return 3

  // Étape 2 (REAC téléchargé)
  if (job.reac_available) return 2

  // Status enum reconnus pour les phases en cours sans champ équivalent
  if (status === 'kb_building' || status === 'reac_fetching') return 2
  if (status === 'global_generating') return 3
  if (status === 'daily_splitting') return 4

  // Erreur générique : on cascade comme ci-dessus mais sans rien trouver
  return 1
}

const STEP_LABELS = [
  { icon: 'search', label: 'Recherche RNCP' },
  { icon: 'download', label: 'Téléchargement REAC' },
  { icon: 'psychology', label: 'Enrichissement KB' },
  { icon: 'auto_stories', label: 'Programme global' },
  { icon: 'calendar_view_week', label: 'Programmes journée' },
  { icon: 'slideshow', label: 'Texte + slides' },
]

const AUTO_PILOT_STEP_LABELS = {
  start: 'démarrage',
  reac: 'téléchargement REAC',
  kb: 'enrichissement Knowledge Base',
  global: 'programme global',
  daily: 'programmes journée',
  content: 'génération texte',
  plan_adherence_review: 'adhérence au plan',
  humanization_review: 'humanisation orale (legacy)',
  audio_word_calibration: 'calibrage blocs audio (legacy)',
  review: 'conformité locale par morceau',
  word_budget_review: 'vérification budget mots',
  post_review_docs: 'Word 2 + artefacts',
  slides: 'slides anchor-first',
  audio: 'TTS + synchronisation slides',
  done: 'texte + slides prêts',
  '?': '—',
}

const AUTO_PILOT_ORDER = [
  'start',
  'reac',
  'kb',
  'global',
  'daily',
  'content',
  'review',
  'post_review_docs',
  'slides',
  'audio',
  'done',
]
const AUTO_PILOT_ORDER_INDEX = AUTO_PILOT_ORDER.reduce((acc, key, idx) => {
  acc[key] = idx
  return acc
}, {})

// ─── Connecteurs visuels entre étapes du pipeline ─────────────────────────────
// Matérialise le flux de données : RNCP → REAC → split (API/CC) → texte + slides.
// Deux primitives :
//   - FlowArrowDown : flèche verticale ↓ entre 2 cards consécutives.
//   - FlowSplit     : Y-fork qui part d'un tronc commun vers les 2 colonnes.
const FLOW_COLOR = 'rgba(167, 139, 250, 0.35)'  // violet sobre cohérent avec l'accent
const FLOW_STROKE = 2

function FlowArrowDown({ height = 28, color = FLOW_COLOR }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'flex-end',
      height: `${height}px`,
      margin: '4px 0',
    }}>
      <div style={{
        width: `${FLOW_STROKE}px`,
        height: `${height - 7}px`,
        background: color,
        position: 'relative',
      }}>
        <div style={{
          position: 'absolute',
          bottom: '-7px',
          left: '50%',
          transform: 'translateX(-50%)',
          width: 0,
          height: 0,
          borderLeft: '5px solid transparent',
          borderRight: '5px solid transparent',
          borderTop: `7px solid ${color}`,
        }}/>
      </div>
    </div>
  )
}

// Y-fork (1 → 2) : tronc descend du centre, bifurque horizontalement vers les
// centres des deux colonnes du grid (1fr 1fr, gap 40px → centres à 25%-10px et
// 75%+10px), puis chute verticale + tête de flèche dans chaque colonne.
function FlowSplit({ color = FLOW_COLOR }) {
  const stem = 18      // tronc vertical depuis le haut
  const drop = 22      // chute dans chaque branche
  const arrow = 7      // hauteur de la tête de flèche
  const total = stem + drop + arrow
  return (
    <div style={{ position: 'relative', height: `${total}px`, margin: '4px 0' }}>
      {/* tronc central */}
      <div style={{
        position: 'absolute',
        left: '50%', top: 0,
        width: `${FLOW_STROKE}px`, height: `${stem}px`,
        background: color, transform: 'translateX(-50%)',
      }}/>
      {/* barre horizontale entre centres des 2 colonnes */}
      <div style={{
        position: 'absolute',
        left: 'calc(25% - 10px)', right: 'calc(25% - 10px)',
        top: `${stem}px`, height: `${FLOW_STROKE}px`,
        background: color,
      }}/>
      {/* chute gauche */}
      <div style={{
        position: 'absolute',
        left: `calc(25% - 10px - ${FLOW_STROKE / 2}px)`, top: `${stem}px`,
        width: `${FLOW_STROKE}px`, height: `${drop}px`,
        background: color,
      }}/>
      {/* chute droite */}
      <div style={{
        position: 'absolute',
        right: `calc(25% - 10px - ${FLOW_STROKE / 2}px)`, top: `${stem}px`,
        width: `${FLOW_STROKE}px`, height: `${drop}px`,
        background: color,
      }}/>
      {/* tête de flèche gauche */}
      <div style={{
        position: 'absolute',
        left: 'calc(25% - 10px)', top: `${stem + drop}px`,
        transform: 'translateX(-50%)',
        width: 0, height: 0,
        borderLeft: '5px solid transparent',
        borderRight: '5px solid transparent',
        borderTop: `${arrow}px solid ${color}`,
      }}/>
      {/* tête de flèche droite */}
      <div style={{
        position: 'absolute',
        right: 'calc(25% - 10px)', top: `${stem + drop}px`,
        transform: 'translateX(50%)',
        width: 0, height: 0,
        borderLeft: '5px solid transparent',
        borderRight: '5px solid transparent',
        borderTop: `${arrow}px solid ${color}`,
      }}/>
    </div>
  )
}

// ─── Voix TTS : labels + couleurs pour l'affichage du module persistant ──────
function voiceLabel(t) {
  if (t === 'fish_audio') return 'Fish Audio S2-Pro (payant)'
  if (t === 'gtts') return 'Edge TTS — voix basique gratuite'
  if (t === 'mock') return 'Mock — silence (test)'
  return t || 'inconnue'
}
function voiceColor(t) {
  if (t === 'fish_audio') return '#34d399'
  if (t === 'gtts') return '#fb923c'
  if (t === 'mock') return '#94a3b8'
  return '#94a3b8'
}
function pipelineModelLabel(model) {
  if (model === 'pro' || model === 'deepseek-v4-pro') return 'DeepSeek Pro'
  if (model === 'flash' || model === 'deepseek-v4-flash') return 'DeepSeek Flash'
  if (model === 'haiku' || String(model || '').includes('haiku')) return 'Claude Haiku'
  if (model === 'sonnet' || String(model || '').includes('sonnet')) return 'Claude Sonnet'
  return model || 'modèle par défaut'
}

// ─── Styles communs ───────────────────────────────────────────────────────────
const S = {
  page: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #0f172a 0%, #1a1035 100%)',
    color: '#e2e8f0',
    fontFamily: "'Poppins', sans-serif",
    padding: '0',
  },
  topBar: {
    background: 'rgba(30,41,59,0.8)',
    backdropFilter: 'blur(12px)',
    borderBottom: '1px solid rgba(139,92,246,0.2)',
    padding: '16px 32px',
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    position: 'sticky',
    top: 0,
    zIndex: 100,
  },
  topBarTitle: {
    fontSize: '20px',
    fontWeight: 700,
    background: 'linear-gradient(90deg, #8B5CF6, #a78bfa)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    margin: 0,
  },
  container: {
    maxWidth: '900px',
    margin: '0 auto',
    padding: '32px 24px',
  },
  card: {
    background: 'rgba(30,41,59,0.6)',
    border: '1px solid rgba(99,102,241,0.15)',
    borderRadius: '16px',
    padding: '24px',
    marginBottom: '16px',
  },
  cardTitle: {
    fontSize: '14px',
    fontWeight: 600,
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    marginBottom: '16px',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  btn: (variant = 'primary') => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    padding: '10px 18px',
    borderRadius: '10px',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    border: 'none',
    transition: 'all 0.2s',
    ...(variant === 'primary' ? {
      background: 'linear-gradient(135deg, #7c3aed, #8B5CF6)',
      color: '#fff',
      boxShadow: '0 4px 15px rgba(139,92,246,0.3)',
    } : variant === 'success' ? {
      background: 'linear-gradient(135deg, #059669, #10b981)',
      color: '#fff',
      boxShadow: '0 4px 15px rgba(16,185,129,0.3)',
    } : variant === 'ghost' ? {
      background: 'rgba(99,102,241,0.1)',
      color: '#a78bfa',
      border: '1px solid rgba(139,92,246,0.3)',
    } : {
      background: 'rgba(30,41,59,0.8)',
      color: '#94a3b8',
      border: '1px solid rgba(99,102,241,0.2)',
    }),
  }),
  input: {
    width: '100%',
    background: 'rgba(15,23,42,0.6)',
    border: '1px solid rgba(99,102,241,0.3)',
    borderRadius: '10px',
    padding: '10px 14px',
    color: '#e2e8f0',
    fontSize: '14px',
    outline: 'none',
    boxSizing: 'border-box',
  },
  label: {
    fontSize: '13px',
    color: '#94a3b8',
    fontWeight: 500,
    marginBottom: '6px',
    display: 'block',
  },
  tag: (color = 'violet') => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    padding: '3px 10px',
    borderRadius: '20px',
    fontSize: '12px',
    fontWeight: 600,
    ...(color === 'violet' ? { background: 'rgba(139,92,246,0.15)', color: '#a78bfa' }
      : color === 'green' ? { background: 'rgba(16,185,129,0.15)', color: '#34d399' }
      : color === 'blue' ? { background: 'rgba(59,130,246,0.15)', color: '#60a5fa' }
      : color === 'amber' ? { background: 'rgba(245,158,11,0.15)', color: '#fbbf24' }
      : { background: 'rgba(239,68,68,0.15)', color: '#f87171' }),
  }),
}

function formatDuration(ms) {
  if (!ms) return null
  const totalSeconds = Math.max(1, Math.round(ms / 1000))
  if (totalSeconds < 60) return `${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes < 60) return `${minutes}m${seconds ? ` ${seconds}s` : ''}`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return `${hours}h${rest ? ` ${rest}m` : ''}`
}

function formatEventTime(value) {
  if (!value) return ''
  // SQLite CURRENT_TIMESTAMP est en UTC. La string arrive sans timezone
  // ("2026-05-05 11:01:23") — on force le parsing UTC en ajoutant 'Z',
  // sinon JS l'interprète comme heure locale et l'affichage est décalé.
  const isoLike = String(value).replace(' ', 'T')
  const hasTz = isoLike.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(isoLike)
  const date = new Date(hasTz ? isoLike : `${isoLike}Z`)
  if (Number.isNaN(date.getTime())) return String(value).slice(11, 16) || String(value)
  return date.toLocaleTimeString('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Paris',
  })
}

function formatJobTimestamp(value) {
  if (!value) return ''
  const isoLike = String(value).replace(' ', 'T')
  const hasTz = isoLike.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(isoLike)
  const date = new Date(hasTz ? isoLike : `${isoLike}Z`)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Paris',
  })
}

function formatJobIdentity(job) {
  if (!job) return 'Aucun job'
  const jobLabel = job.job_label || (job.id ? `Job #${job.id}` : 'Job ?')
  const platformLabel = job.platform_label || (job.platform_id ? `P${job.platform_id}` : 'P?')
  return `${jobLabel} · ${platformLabel}`
}

function formatFolderIdentity(folder) {
  if (!folder) return 'Dossier ?'
  const dayLabel = folder.day_number ? `Jour ${folder.day_number}` : `Jour ${(folder.position ?? 0) + 1}`
  const folderLabel = folder.folder_label || (folder.folder_id ? `F${folder.folder_id}` : 'F?')
  const contentLabel = folder.content_job_id ? `Texte #${folder.content_job_id}` : 'Texte non créé'
  return `${dayLabel} · ${folderLabel} · ${contentLabel}`
}

function setPipelineJobInUrl(jobId, { replace = false } = {}) {
  if (typeof window === 'undefined') return
  const url = new URL(window.location.href)
  if (jobId) {
    url.searchParams.set('job', String(jobId))
  } else {
    url.searchParams.delete('job')
  }
  window.history[replace ? 'replaceState' : 'pushState'](
    null,
    '',
    `${url.pathname}${url.search}${url.hash}`,
  )
}

function eventTone(status) {
  if (status === 'completed') return { color: '#34d399', icon: 'check_circle' }
  if (status === 'running') return { color: '#fbbf24', icon: 'hourglass_empty' }
  if (status === 'error' || status === 'failed') return { color: '#f87171', icon: 'error_outline' }
  return { color: '#a78bfa', icon: 'radio_button_unchecked' }
}

function eventLabel(eventType) {
  const labels = {
    pipeline_started: 'Pipeline démarrée',
    pipeline_completed: 'Pipeline terminée',
    step_started: 'Étape démarrée',
    step_completed: 'Étape terminée',
    step_failed: 'Étape échouée',
    review_started: 'Review démarrée',
    review_completed: 'Review terminée',
    review_failed: 'Review échouée',
    audio_block_word_calibration_completed: 'Calibrage budget texte terminé',
    day_word_budget_verified: 'Budget mots journée vérifié',
    continue_after_text_plan_adherence_completed: 'Adhérence au plan terminée',
    continue_after_text_humanization_completed: 'Humanisation terminée (legacy)',
    continue_after_text_review_completed: 'Conformité locale terminée',
    audio_started: 'Audio démarré',
    audio_progress: 'Fichier playlist en cours',
    audio_folder_started: 'Journée audio démarrée',
    audio_folder_completed: 'Journée audio terminée',
    audio_folder_failed: 'Journée audio échouée',
    audio_completed: 'Audio terminé',
    audio_failed: 'Audio échoué',
    slides_folder_started: 'Slides journée démarrées',
    slides_folder_completed: 'Slides journée terminées',
    slides_folder_failed: 'Slides journée échouées',
    continue_after_text_started: 'Reprise aval démarrée',
    continue_after_text_completed: 'Reprise aval terminée',
    continue_after_text_failed: 'Reprise aval échouée',
  }
  return labels[eventType] || String(eventType || 'Événement').replace(/_/g, ' ')
}

function eventData(event) {
  if (!event) return {}
  const raw = event.data ?? event.data_json
  if (!raw) return {}
  if (typeof raw === 'object') return raw
  try {
    return JSON.parse(raw)
  } catch {
    return {}
  }
}

function healthCheckLabel(key) {
  const labels = {
    segments_completed: 'Segments texte générés',
    cg_jobs_completed: 'Jobs texte terminés',
    docx_buildable: 'Word final téléchargeable',
    pre_review_snapshotted: 'Snapshot avant review',
    review_consistent: 'Review conformité',
    audio_tts_files: 'Segments texte audio à jour',
    module_persistant: 'Module persistant',
    health_error: 'Audit final',
  }
  return labels[key] || String(key || '').replace(/_/g, ' ')
}

function PipelineDiagnosticPanel({ diagnostic, loading, error, onRefresh }) {
  const health = diagnostic?.health
  const diagnosticJob = diagnostic?.job
  const folders = diagnostic?.folders || []
  const events = diagnostic?.events || []
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [eventFilter, setEventFilter] = useState('audio')
  const audioEvents = events.filter(event => event.step === 'audio' || String(event.event_type || '').startsWith('audio_'))
  const reviewEvents = events.filter(event =>
    ['review', 'plan_adherence_review', 'word_budget_review'].includes(event.step) ||
    String(event.event_type || '').includes('review') ||
    String(event.event_type || '').includes('humanization') ||
    String(event.event_type || '').includes('calibration')
  )
  const slidesEvents = events.filter(event => event.step === 'slides' || String(event.event_type || '').includes('slides'))
  const visibleEvents = (
    eventFilter === 'audio' ? audioEvents
      : eventFilter === 'review' ? reviewEvents
      : eventFilter === 'slides' ? slidesEvents
      : events
  ).slice(-18)
  const latestAudioEvent = audioEvents[audioEvents.length - 1]
  const latestProgressEvent = [...audioEvents].reverse().find(event => event.event_type === 'audio_progress')
  const latestProgressData = eventData(latestProgressEvent)
  const latestStep = Number(latestProgressData.step || 0)
  const latestTotal = Number(latestProgressData.total || 0)
  const playlistPct = latestTotal > 0 ? Math.min(100, Math.round((latestStep / latestTotal) * 100)) : null
  const totals = folders.reduce((acc, folder) => ({
    words: acc.words + (folder.total_words || 0),
    segments: acc.segments + (folder.segments_completed || 0),
    reviewed: acc.reviewed + (folder.reviewed_segments || 0),
    dirty: acc.dirty + (folder.dirty_segments || 0),
    reviewErrors: acc.reviewErrors + (folder.review_errors || 0),
  }), { words: 0, segments: 0, reviewed: 0, dirty: 0, reviewErrors: 0 })
  const audioReady = Math.max(0, totals.segments - totals.dirty)
  const audioPct = totals.segments > 0 ? Math.round((audioReady / totals.segments) * 100) : 0
  const showGlobalAudioSummary = folders.length > 1
  const healthColor = health?.ok ? '#34d399' : health?.blocking?.length ? '#f87171' : '#fbbf24'
  const healthIcon = health?.ok ? 'verified' : health?.blocking?.length ? 'error_outline' : 'warning_amber'
  const healthEntries = Object.entries(health?.checks || {})

  return (
    <div style={{
      marginTop: '18px',
      padding: '14px',
      borderRadius: '10px',
      border: '1px solid rgba(148,163,184,0.16)',
      background: 'rgba(15,23,42,0.34)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '13px', color: '#e2e8f0', fontWeight: 700, flex: 1, minWidth: 0 }}>
          <Icon name="analytics" /> Diagnostic pipeline
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          style={{ ...S.btn('ghost'), padding: '5px 10px', fontSize: '11px' }}
        >
          <Icon name={loading ? 'hourglass_empty' : 'refresh'} /> Actualiser
        </button>
      </div>

      {error && (
        <div style={{ color: '#f87171', fontSize: '12px', marginBottom: '10px' }}>
          <Icon name="error_outline" /> {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '12px' }}>
        {diagnosticJob && (
          <span style={{ ...S.tag('violet'), padding: '5px 10px' }}>
            <Icon name="tag" /> {formatJobIdentity(diagnosticJob)}
          </span>
        )}
        <span style={{ ...S.tag(health?.ok ? 'green' : health?.blocking?.length ? 'red' : 'amber'), padding: '5px 10px' }}>
          <Icon name={healthIcon} /> Audit {health?.ok ? 'OK' : health?.blocking?.length ? 'bloquant' : 'à surveiller'}
        </span>
        <span style={{ ...S.tag('violet'), padding: '5px 10px' }}>
          <Icon name="folder" /> {folders.length} journée{folders.length > 1 ? 's' : ''}
        </span>
        <span style={{ ...S.tag('violet'), padding: '5px 10px' }}>
          <Icon name="article" /> {totals.words.toLocaleString('fr-FR')} mots
        </span>
        <span style={{ ...S.tag(totals.dirty ? 'amber' : 'green'), padding: '5px 10px' }}>
          <Icon name="graphic_eq" /> {totals.dirty
            ? `${totals.dirty} segment${totals.dirty > 1 ? 's' : ''} texte à régénérer en audio`
            : 'Segments texte audio à jour'}
        </span>
        {totals.reviewErrors > 0 && (
          <span style={{ ...S.tag('red'), padding: '5px 10px' }}>
            <Icon name="report" /> {totals.reviewErrors} erreur{totals.reviewErrors > 1 ? 's' : ''} review
          </span>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px', marginBottom: '14px' }}>
        <div style={{ padding: '12px', borderRadius: '8px', background: 'rgba(15,23,42,0.45)', border: '1px solid rgba(148,163,184,0.12)' }}>
          <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>
            Étape en cours
          </div>
          <div style={{ fontSize: '13px', color: latestAudioEvent ? '#cbd5e1' : '#64748b', lineHeight: 1.45 }}>
            {latestAudioEvent ? (
              <>
                <strong style={{ color: eventTone(latestAudioEvent.status).color }}>{eventLabel(latestAudioEvent.event_type)}</strong>
                {latestAudioEvent.folder_id ? <span style={{ color: '#64748b' }}> · F{latestAudioEvent.folder_id}</span> : null}
                {latestAudioEvent.message ? <span> · {latestAudioEvent.message}</span> : null}
                {latestAudioEvent.error ? <span style={{ color: '#f87171' }}> · {latestAudioEvent.error}</span> : null}
              </>
            ) : (
              'Aucun événement audio reçu.'
            )}
          </div>
          <div style={{ fontSize: '11px', color: '#64748b', marginTop: '8px', lineHeight: 1.4 }}>
            La progression détaillée <strong style={{ color: '#22d3ee' }}>par journée</strong> est affichée plus bas (barre cyan « ⚡ Audio en cours »).
          </div>
        </div>

        {showGlobalAudioSummary && (
          <div style={{ padding: '12px', borderRadius: '8px', background: 'rgba(15,23,42,0.45)', border: '1px solid rgba(148,163,184,0.12)' }}>
            <div style={{ fontSize: '11px', color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '6px' }}>
              Segments validés (texte ↔ audio)
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginBottom: '8px' }}>
              <strong style={{ color: totals.dirty ? '#fbbf24' : '#34d399', fontSize: '22px' }}>{audioPct}%</strong>
              <span style={{ color: '#94a3b8', fontSize: '12px' }}>
                {audioReady}/{totals.segments || 0} segments à jour
              </span>
            </div>
            <div style={{ height: '7px', borderRadius: '999px', background: 'rgba(148,163,184,0.12)', overflow: 'hidden' }}>
              <div style={{ width: `${audioPct}%`, height: '100%', background: totals.dirty ? '#fbbf24' : '#34d399' }} />
            </div>
            <div style={{ fontSize: '11px', color: '#64748b', marginTop: '6px', lineHeight: 1.4 }}>
              Compteur figé pendant la régénération (mis à jour à la fin de chaque bloc TTS). Pour le live, voir la barre <strong style={{ color: '#22d3ee' }}>⚡ par journée</strong>.
            </div>
          </div>
        )}
      </div>

      {folders.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '14px' }}>
          {folders.map(folder => {
            const folderEvents = audioEvents.filter(event => event.folder_id === folder.folder_id)
            const lastFolderEvent = folderEvents[folderEvents.length - 1]
            const pending = folder.dirty_segments || 0
            const completed = folder.segments_completed || 0
            const ready = Math.max(0, completed - pending)
            const pct = completed > 0 ? Math.round((ready / completed) * 100) : 0
            const statusColor = pending ? '#fbbf24' : '#34d399'
            // Progression audio temps réel : dernier event "audio_progress" sur ce folder.
            // Permet à la barre de bouger pendant la pipeline (dirty=0 n'est mis qu'à
            // la fin d'un bloc complet, donc la barre statique "X/18 à jour" reste figée
            // pendant les ~10 min de TTS d'un bloc).
            const lastProgressForFolder = [...folderEvents].reverse().find(e => e.event_type === 'audio_progress')
            const folderProgressData = eventData(lastProgressForFolder)
            const folderProgStep = Number(folderProgressData.step || 0)
            const folderProgTotal = Number(folderProgressData.total || 0)
            const folderProgPct = folderProgTotal > 0 ? Math.min(100, Math.round((folderProgStep / folderProgTotal) * 100)) : null
            const isAudioRunningForFolder = lastFolderEvent && (
              lastFolderEvent.status === 'running' ||
              lastFolderEvent.event_type === 'audio_folder_started' ||
              lastFolderEvent.event_type === 'audio_progress'
            ) && !['audio_folder_completed', 'audio_folder_failed'].includes(lastFolderEvent.event_type)
            return (
              <div key={folder.folder_id} style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                gap: '12px',
                alignItems: 'center',
                padding: '10px 12px',
                borderRadius: '8px',
                border: '1px solid rgba(148,163,184,0.12)',
                background: 'rgba(15,23,42,0.32)',
              }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ color: '#e2e8f0', fontWeight: 700, fontSize: '12px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {folder.name || `Journée ${folder.position + 1}`}
                  </div>
                  <div style={{ color: '#64748b', fontSize: '11px', marginTop: '2px' }}>
                    {folder.folder_label || `F${folder.folder_id}`} · Texte #{folder.content_job_id || '?'} ·{' '}
                    {Number(folder.total_words || 0).toLocaleString('fr-FR')} mots · {folder.reviewed_segments || 0}/{completed || 0} revus
                  </div>
                </div>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap', fontSize: '11px', color: '#94a3b8', marginBottom: '5px' }}>
                    <span style={{ color: statusColor }}>
                      {pending
                        ? `${pending} segment${pending > 1 ? 's' : ''} texte à régénérer`
                        : 'Segments texte audio à jour'}
                    </span>
                    <span>{ready}/{completed || 0} à jour</span>
                  </div>
                  <div style={{ height: '5px', borderRadius: '999px', background: 'rgba(148,163,184,0.12)', overflow: 'hidden' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: statusColor }} />
                  </div>
                  {isAudioRunningForFolder && folderProgPct !== null && (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap', fontSize: '11px', marginTop: '6px', marginBottom: '4px' }}>
                        <span style={{ color: '#22d3ee', fontWeight: 600 }}>
                          <Icon name="bolt" style={{ fontSize: '11px', verticalAlign: 'middle' }} /> Audio en cours
                        </span>
                        <span style={{ color: '#22d3ee' }}>{folderProgStep}/{folderProgTotal} fichiers · {folderProgPct}%</span>
                      </div>
                      <div style={{ height: '5px', borderRadius: '999px', background: 'rgba(34,211,238,0.12)', overflow: 'hidden' }}>
                        <div style={{
                          width: `${folderProgPct}%`,
                          height: '100%',
                          background: 'linear-gradient(90deg, #22d3ee, #06b6d4)',
                          transition: 'width 0.4s ease',
                        }} />
                      </div>
                    </>
                  )}
                </div>
                <div style={{ color: '#94a3b8', fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {lastFolderEvent ? (
                    <>
                      <Icon name={eventTone(lastFolderEvent.status).icon} style={{ color: eventTone(lastFolderEvent.status).color, fontSize: '12px' }} />{' '}
                      {formatEventTime(lastFolderEvent.created_at)} · {lastFolderEvent.message || eventLabel(lastFolderEvent.event_type)}
                    </>
                  ) : (
                    'Aucun événement audio pour ce dossier'
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {health && !health.ok && (
        <div style={{
          color: healthColor,
          fontSize: '12px',
          lineHeight: 1.45,
          marginBottom: '12px',
        }}>
          {health.blocking?.length > 0 && <>Bloquants : {health.blocking.map(healthCheckLabel).join(', ')}</>}
          {health.blocking?.length > 0 && health.warnings?.length > 0 && ' · '}
          {health.warnings?.length > 0 && <>Warnings : {health.warnings.map(healthCheckLabel).join(', ')}</>}
        </div>
      )}

      {healthEntries.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '8px', marginBottom: '14px' }}>
          {healthEntries.map(([key, check]) => (
            <div key={key} style={{
              padding: '9px 10px',
              borderRadius: '8px',
              background: check?.ok ? 'rgba(16,185,129,0.07)' : 'rgba(239,68,68,0.07)',
              border: `1px solid ${check?.ok ? 'rgba(16,185,129,0.18)' : 'rgba(239,68,68,0.18)'}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: check?.ok ? '#34d399' : '#f87171', fontSize: '12px', fontWeight: 700, marginBottom: '3px' }}>
                <Icon name={check?.ok ? 'check_circle' : 'error_outline'} style={{ fontSize: '13px' }} />
                {healthCheckLabel(key)}
              </div>
              <div style={{ color: '#94a3b8', fontSize: '11px', lineHeight: 1.35 }}>
                {check?.detail || 'Pas de détail disponible'}
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '8px' }}>
        <div style={{ fontSize: '12px', color: '#94a3b8', flex: 1, minWidth: 0 }}>
          <strong style={{ color: '#cbd5e1' }}>{totals.reviewed}/{totals.segments}</strong> segments revus · journal détaillé
        </div>
        {[
          ['audio', 'Audio'],
          ['review', 'Review'],
          ['slides', 'Slides'],
          ['all', 'Tout'],
        ].map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setEventFilter(value)}
            style={{
              ...S.btn(eventFilter === value ? 'ghost' : 'neutral'),
              padding: '4px 9px',
              fontSize: '11px',
              opacity: eventFilter === value ? 1 : 0.72,
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
        {visibleEvents.length === 0 ? (
          <div style={{ fontSize: '12px', color: '#64748b' }}>
            Aucun événement dans ce filtre.
          </div>
        ) : visibleEvents.map(event => {
          const tone = eventTone(event.status)
          const duration = formatDuration(event.duration_ms)
          return (
            <div
              key={event.id}
              onClick={() => setSelectedEvent(event)}
              style={{
                display: 'grid',
                gridTemplateColumns: '54px minmax(0, 1fr) auto',
                gap: '8px',
                alignItems: 'center',
                fontSize: '12px',
                color: '#cbd5e1',
                cursor: 'pointer',
                padding: '4px 6px',
                borderRadius: '6px',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(139,92,246,0.08)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              title="Cliquer pour voir le détail"
            >
              <span style={{ color: '#64748b' }}>{formatEventTime(event.created_at)}</span>
              <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                <Icon name={tone.icon} style={{ color: tone.color, fontSize: '13px' }} />{' '}
                <strong style={{ color: tone.color }}>{eventLabel(event.event_type)}</strong>
                {event.folder_id ? <span style={{ color: '#64748b' }}> · F{event.folder_id}</span> : null}
                {event.message ? <span style={{ color: '#94a3b8' }}> · {event.message}</span> : null}
                {event.error ? <span style={{ color: '#f87171' }}> · {event.error}</span> : null}
              </span>
              {duration && <span style={{ color: '#64748b' }}>{duration}</span>}
            </div>
          )
        })}
      </div>
      {selectedEvent && (
        <EventDetailModal event={selectedEvent} onClose={() => setSelectedEvent(null)} />
      )}
    </div>
  )
}

function PipelineActiveNotice({ job, autoPilotState, diagnostic, contentFolders }) {
  if (!job) return null
  const autoRunning = autoPilotState?.status === 'running'
  const contentDone = contentFolders.length > 0 &&
    contentFolders.every(folder => folder.content_status === 'completed')
  const statusRunning = (
    job.status === 'tts_launched'
      ? !contentDone
      : POLLING_STATUSES.has(job.status) && !AUDIO_DONE_STATUSES.has(job.status)
  )
  if (!autoRunning && !statusRunning) return null

  const stepKey = autoPilotState?.step ||
    (job.status === 'tts_launched' ? 'content'
      : job.status === 'audio_running' ? 'audio'
      : job.status === 'daily_splitting' ? 'daily'
      : job.status === 'global_generating' ? 'global'
      : job.status === 'kb_building' ? 'kb'
      : job.status === 'reac_fetching' ? 'reac'
      : '?')
  const label = AUTO_PILOT_STEP_LABELS[stepKey] || String(stepKey || '—').replace(/_/g, ' ')
  const expected = diagnostic?.folder_resolution?.expected_count || job.nb_days || contentFolders.length || 0
  const completed = contentFolders.filter(folder => folder.content_status === 'completed').length
  const activeFolder = contentFolders.find(folder => folder.content_status && folder.content_status !== 'completed')
  const events = diagnostic?.events || []
  const latestEvent = [...events].reverse().find(event => event.status === 'running') || events[events.length - 1]
  const duplicates = diagnostic?.folder_resolution?.duplicates || []
  const model = autoPilotState?.model || job.auto_pilot_model
  const ttsMode = autoPilotState?.tts_mode || job.auto_pilot_tts_mode

  return (
    <div style={{
      padding: '14px 18px',
      marginBottom: '20px',
      borderRadius: '12px',
      background: 'linear-gradient(135deg, rgba(59,130,246,0.15), rgba(139,92,246,0.08))',
      border: '1px solid rgba(59,130,246,0.4)',
      display: 'flex',
      alignItems: 'flex-start',
      gap: '14px',
      flexWrap: 'wrap',
    }}>
      <div style={{
        width: '38px', height: '38px', borderRadius: '10px',
        background: 'rgba(59,130,246,0.2)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flex: '0 0 auto',
      }}>
        <Icon name="autorenew" style={{ fontSize: '22px', color: '#60a5fa' }} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '14px', fontWeight: 700, color: '#60a5fa' }}>
          Étape active : {label}
        </div>
        <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '3px' }}>
          {stepKey === 'content'
            ? `Génération texte en cours — ${completed}/${expected || job.nb_days} journée${(expected || job.nb_days) > 1 ? 's' : ''} terminée${completed > 1 ? 's' : ''}`
            : stepKey === 'slides'
              ? `Génération des decks slides anchor-first — ${contentFolders.filter(folder => (folder.slide_count || 0) > 0).length}/${expected || job.nb_days} journée${(expected || job.nb_days) > 1 ? 's' : ''} prête${(expected || job.nb_days) > 1 ? 's' : ''}`
              : stepKey === 'audio'
                ? `Synthèse audio en cours — ${diagnostic?.folders?.length || contentFolders.length || expected || job.nb_days} journée${(expected || job.nb_days) > 1 ? 's' : ''} prévue${(expected || job.nb_days) > 1 ? 's' : ''}`
                : 'La pipeline travaille sur cette étape.'}
          {activeFolder ? ` · dossier actif : ${activeFolder.folder_label || `F${activeFolder.folder_id}`}` : ''}
          {ttsMode ? <> · TTS : <strong>{ttsMode}</strong></> : null}
          {model ? <> · modèle : <strong>{pipelineModelLabel(model)}</strong></> : null}
        </div>
        {latestEvent && (
          <div style={{ fontSize: '11.5px', color: '#cbd5e1', marginTop: '7px' }}>
            <Icon name="schedule" style={{ fontSize: '13px', color: '#94a3b8' }} />{' '}
            {formatEventTime(latestEvent.created_at)} · {eventLabel(latestEvent.event_type)}
            {latestEvent.message ? ` · ${latestEvent.message}` : ''}
          </div>
        )}
        {duplicates.length > 0 && (
          <div style={{ fontSize: '11.5px', color: '#fbbf24', marginTop: '7px' }}>
            <Icon name="warning_amber" style={{ fontSize: '13px' }} />{' '}
            {duplicates.length} dossier{duplicates.length > 1 ? 's' : ''} doublon{duplicates.length > 1 ? 's' : ''} détecté{duplicates.length > 1 ? 's' : ''} et ignoré{duplicates.length > 1 ? 's' : ''} pour les étapes aval.
          </div>
        )}
      </div>
    </div>
  )
}

function EventDetailModal({ event, onClose }) {
  const tone = eventTone(event.status)
  let dataPreview = null
  try {
    const raw = event.data ?? event.data_json
    const parsed = typeof raw === 'string' && raw ? JSON.parse(raw) : raw
    if (parsed && Object.keys(parsed).length > 0) {
      dataPreview = JSON.stringify(parsed, null, 2)
    }
  } catch {
    dataPreview = String((event.data ?? event.data_json) || '')
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(15,23,42,0.75)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '24px',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#0f172a',
          border: '1px solid rgba(139,92,246,0.35)',
          borderRadius: '14px',
          padding: '24px 28px',
          width: 'min(720px, 100%)',
          maxHeight: '85vh',
          overflowY: 'auto',
          boxShadow: '0 25px 60px rgba(0,0,0,0.5)',
          color: '#cbd5e1',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px', gap: '12px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
              <Icon name={tone.icon} style={{ color: tone.color, fontSize: '20px' }} />
              <strong style={{ color: tone.color, fontSize: '16px' }}>{eventLabel(event.event_type)}</strong>
            </div>
            <div style={{ fontSize: '12px', color: '#64748b' }}>
              {formatEventTime(event.created_at)} · status <strong style={{ color: tone.color }}>{event.status || 'info'}</strong>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent', border: '1px solid rgba(148,163,184,0.3)',
              color: '#94a3b8', borderRadius: '8px', padding: '4px 10px', cursor: 'pointer',
            }}
            title="Fermer"
          >
            <Icon name="close" />
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '8px 14px', fontSize: '13px', marginBottom: '16px' }}>
          {event.job_id && (<><span style={{ color: '#64748b' }}>Job formation</span><span style={{ color: '#cbd5e1' }}>Job #{event.job_id}</span></>)}
          {event.step && (<><span style={{ color: '#64748b' }}>Étape</span><span style={{ color: '#cbd5e1' }}>{event.step}</span></>)}
          {event.folder_id && (<><span style={{ color: '#64748b' }}>Dossier journée</span><span style={{ color: '#cbd5e1' }}>F{event.folder_id}</span></>)}
          {event.model && (<><span style={{ color: '#64748b' }}>Modèle LLM</span><span style={{ color: '#a78bfa', fontFamily: 'monospace' }}>{event.model}</span></>)}
          {event.duration_ms != null && (<><span style={{ color: '#64748b' }}>Durée</span><span style={{ color: '#cbd5e1' }}>{formatDuration(event.duration_ms) || `${event.duration_ms} ms`}</span></>)}
          <span style={{ color: '#64748b' }}>Type</span><span style={{ color: '#cbd5e1', fontFamily: 'monospace' }}>{event.event_type}</span>
          <span style={{ color: '#64748b' }}>ID</span><span style={{ color: '#cbd5e1', fontFamily: 'monospace' }}>{event.id}</span>
        </div>

        {event.message && (
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#64748b', marginBottom: '4px' }}>Message</div>
            <div style={{ fontSize: '13px', color: '#cbd5e1', lineHeight: 1.5, padding: '10px 12px', background: 'rgba(167,139,250,0.06)', border: '1px solid rgba(167,139,250,0.22)', borderRadius: '6px' }}>
              {event.message}
            </div>
          </div>
        )}

        {event.error && (
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#f87171', marginBottom: '4px' }}>Erreur</div>
            <div style={{ fontSize: '13px', color: '#fecaca', lineHeight: 1.5, padding: '10px 12px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(248,113,113,0.32)', borderRadius: '6px', fontFamily: 'monospace', wordBreak: 'break-word' }}>
              {event.error}
            </div>
          </div>
        )}

        {dataPreview && (
          <div>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#64748b', marginBottom: '4px' }}>Données</div>
            <pre style={{ fontSize: '11.5px', color: '#cbd5e1', background: 'rgba(15,23,42,0.6)', border: '1px solid rgba(99,102,241,0.15)', borderRadius: '6px', padding: '10px 12px', overflowX: 'auto', margin: 0, fontFamily: 'monospace', lineHeight: 1.4 }}>
              {dataPreview}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Stepper horizontal ───────────────────────────────────────────────────────
function Stepper({ currentStep, status }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '32px', overflowX: 'auto', paddingBottom: '4px' }}>
      {STEP_LABELS.map((s, i) => {
        const done = i < currentStep
        const active = i === currentStep
        // err inclut audio_error pour afficher l'icône erreur sur l'étape TTS
        const err = (status === 'error' || status === 'audio_error') && active
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', flex: i < STEP_LABELS.length - 1 ? 1 : 0 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: '80px' }}>
              <div style={{
                width: '40px', height: '40px', borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '18px',
                background: err ? 'rgba(239,68,68,0.2)' : done ? 'rgba(16,185,129,0.2)' : active ? 'rgba(139,92,246,0.25)' : 'rgba(30,41,59,0.8)',
                border: `2px solid ${err ? '#f87171' : done ? '#34d399' : active ? '#8B5CF6' : 'rgba(99,102,241,0.2)'}`,
                color: err ? '#f87171' : done ? '#34d399' : active ? '#a78bfa' : '#475569',
                transition: 'all 0.3s',
              }}>
                {done ? <Icon name="check" /> : err ? <Icon name="error" /> : <Icon name={s.icon} />}
              </div>
              <span style={{ fontSize: '11px', color: active ? '#a78bfa' : done ? '#34d399' : '#475569', marginTop: '6px', textAlign: 'center', fontWeight: active ? 600 : 400 }}>
                {s.label}
              </span>
            </div>
            {i < STEP_LABELS.length - 1 && (
              <div style={{ flex: 1, height: '2px', background: done ? 'rgba(16,185,129,0.4)' : 'rgba(99,102,241,0.1)', margin: '0 8px', marginBottom: '20px' }} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function hasCompletedPipelineEvent(events, predicate) {
  return (events || []).some(event => event?.status === 'completed' && predicate(event))
}

function PipelineStagePill({ stage, index, onClick }) {
  const tone = stage.done
    ? { color: '#34d399', bg: 'rgba(16,185,129,0.10)', border: 'rgba(16,185,129,0.24)', icon: 'check_circle' }
    : stage.active
      ? { color: '#fbbf24', bg: 'rgba(245,158,11,0.10)', border: 'rgba(245,158,11,0.32)', icon: 'hourglass_empty' }
      : { color: '#64748b', bg: 'rgba(30,41,59,0.42)', border: 'rgba(99,102,241,0.13)', icon: stage.icon }
  const label = stage.done ? 'OK' : stage.active ? 'En cours' : stage.optional ? 'Optionnel' : 'À venir'

  return (
    <button
      type="button"
      onClick={onClick}
      title="Ouvrir le détail de cette étape"
      style={{
      display: 'grid',
      gridTemplateColumns: '30px minmax(0, 1fr)',
      gap: '9px',
      alignItems: 'start',
      padding: '10px 11px',
      borderRadius: '8px',
      border: `1px solid ${tone.border}`,
      background: tone.bg,
      minHeight: '92px',
      width: '100%',
      textAlign: 'left',
      cursor: 'pointer',
      fontFamily: 'inherit',
      appearance: 'none',
    }}>
      <div style={{
        width: '28px',
        height: '28px',
        borderRadius: '8px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: tone.color,
        background: 'rgba(15,23,42,0.52)',
        fontSize: '15px',
      }}>
        <Icon name={tone.icon} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px', flexWrap: 'wrap', marginBottom: '4px' }}>
          <span style={{ color: '#64748b', fontSize: '10.5px', fontWeight: 700 }}>
            {String(index + 1).padStart(2, '0')}
          </span>
          <span style={{ color: tone.color, fontSize: '10.5px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            {label}
          </span>
        </div>
        <div style={{ color: stage.done || stage.active ? '#e2e8f0' : '#94a3b8', fontSize: '12.5px', fontWeight: 700, lineHeight: 1.3 }}>
          {stage.title}
        </div>
        <div style={{ color: stage.done || stage.active ? '#94a3b8' : '#64748b', fontSize: '11.5px', lineHeight: 1.35, marginTop: '4px' }}>
          {stage.detail}
        </div>
      </div>
    </button>
  )
}

function PipelineVisualMap({ job, currentStep, autoPilotState, contentFolders, diagnostic }) {
  const [auditStage, setAuditStage] = useState(null)
  if (!job) return null

  const events = diagnostic?.events || []
  const activeAutoStep = autoPilotState?.status === 'running' ? autoPilotState.step : null
  const activeAutoIdx = AUTO_PILOT_ORDER_INDEX[activeAutoStep] ?? -1
  const autoDone = autoPilotState?.status === 'done' || job.auto_pilot_step === 'done'
  const autoPassed = key => {
    const idx = AUTO_PILOT_ORDER_INDEX[key]
    return autoDone || (activeAutoIdx >= 0 && idx >= 0 && activeAutoIdx > idx)
  }
  const autoActive = key => activeAutoStep === key

  const folders = contentFolders || []
  const expectedFolders = diagnostic?.folder_resolution?.expected_count || job.nb_days || folders.length || 0
  const completedFolders = folders.filter(f => f.content_status === 'completed').length
  const allContentCompleted = folders.length > 0 && folders.every(f => f.content_status === 'completed')
  const allReviewed = folders.length > 0 && folders.every(f => {
    const completed = f.segments_completed || 0
    const processed = (f.segments_reviewed || 0) + (f.segments_review_errors || 0)
    return completed > 0 && processed >= completed
  })
  const allSlidesGenerated = folders.length > 0 && folders.every(f => (f.slide_count || 0) > 0)
  const textReady = TEXT_AVAILABLE_STATUSES.has(job.status)
  const planAdherenceDone = hasCompletedPipelineEvent(events, e => e.step === 'plan_adherence_review') ||
    allContentCompleted || allReviewed || autoPassed('content')
  const finalBudgetDone = hasCompletedPipelineEvent(events, e => e.step === 'word_budget_review') ||
    Boolean(job.auto_pilot_post_review_docs_done)
  const postDocsDone = Boolean(job.auto_pilot_post_review_docs_done) ||
    (textReady && allReviewed && !autoActive('post_review_docs'))
  const slidesDone = allSlidesGenerated || hasCompletedPipelineEvent(events, e => e.step === 'slides' && e.event_type === 'step_completed') ||
    autoPassed('slides')

  const contentActive = autoActive('content') || (job.status === 'tts_launched' && !allContentCompleted)
  const stages = [
    {
      key: 'start',
      title: 'Initialisation RNCP et plateforme',
      detail: `Job ${job.job_label || `#${job.id}`} créé, plateforme cible verrouillée.`,
      icon: 'search',
      auditMode: 'job_init',
      done: currentStep > 0 || autoPassed('start'),
      active: currentStep === 0 || autoActive('start'),
    },
    {
      key: 'reac',
      title: 'Téléchargement REAC',
      detail: 'Sources officielles récupérées avant enrichissement métier.',
      icon: 'download',
      auditMode: 'reac',
      done: Boolean(job.reac_available) || currentStep > 1 || autoPassed('reac'),
      active: job.status === 'reac_fetching' || autoActive('reac'),
    },
    {
      key: 'kb',
      title: 'Enrichissement Knowledge Base',
      detail: 'Compétences, cas terrain, pièges fréquents et vocabulaire métier.',
      icon: 'psychology',
      auditMode: 'kb',
      done: (job.kb_total || 0) > 0 || currentStep > 2 || autoPassed('kb'),
      active: job.status === 'kb_building' || autoActive('kb'),
    },
    {
      key: 'global',
      title: 'Programme global',
      detail: 'Architecture complète de la formation à partir du REAC enrichi.',
      icon: 'auto_stories',
      auditMode: 'global_program',
      done: Boolean(job.global_program_validated) || currentStep > 3 || autoPassed('global'),
      active: job.status === 'global_generating' || autoActive('global'),
    },
    {
      key: 'daily',
      title: 'Programmes journée',
      detail: 'Découpage pédagogique par journées, thèmes et chapitres.',
      icon: 'calendar_view_week',
      auditMode: 'daily_programs',
      done: Boolean(job.daily_programs_validated) || currentStep > 4 || autoPassed('daily'),
      active: job.status === 'daily_splitting' || autoActive('daily'),
    },
    {
      key: 'plan_json',
      title: 'Plan JSON verrouillé',
      detail: 'Validation structure, budgets, cours 7, ouvertures et conclusions.',
      icon: 'schema',
      artifacts: ['content-plan.json'],
      auditMode: 'plan_json',
      done: allContentCompleted || autoPassed('content'),
      active: contentActive,
    },
    {
      key: 'slide_beats',
      title: 'Teaching beats et anchors slides',
      detail: 'Exemples, conseils, pièges, comparaisons et templates associés au plan.',
      icon: 'account_tree',
      artifacts: ['content-plan.json'],
      auditMode: 'slide_beats',
      done: allContentCompleted || autoPassed('content'),
      active: contentActive,
    },
    {
      key: 'section_generation',
      title: 'Génération par section — texte V1',
      detail: `${completedFolders}/${expectedFolders || job.nb_days} journée${(expectedFolders || job.nb_days) > 1 ? 's' : ''} générée${completedFolders > 1 ? 's' : ''}, section par section.`,
      icon: 'edit_note',
      artifacts: ['content-plan.json', 'content-draft-sections.json'],
      auditMode: 'section_generation',
      done: allContentCompleted || autoPassed('content'),
      active: contentActive,
    },
    {
      key: 'plan_adherence',
      title: 'Adhérence au plan',
      detail: 'Corrige ordre, reprises, conclusions, doublons d’intro et fuites d’horaires avant le budget.',
      icon: 'rule',
      artifacts: ['content-quality-reviews.json', 'content-draft-sections.json'],
      auditMode: 'plan_adherence',
      done: planAdherenceDone,
      active: contentActive,
    },
    {
      key: 'budget_calibration',
      title: 'Calibrage budget texte',
      detail: 'Alignement des volumes de mots avant toute conformité éthique.',
      icon: 'speed',
      artifacts: ['content-budget-calibration.json', 'content-draft-sections.json', 'content-course-scripts.json'],
      auditMode: 'budget_calibration',
      done: allContentCompleted || autoPassed('content'),
      active: contentActive,
    },
    {
      key: 'ethical_micro',
      title: 'Micro-conformité éthique',
      detail: 'Contrôle des règles éthiques #1-#16 sur le texte calibré.',
      icon: 'shield',
      artifacts: ['content-ethical-micro-review.json'],
      auditMode: 'ethical_micro',
      done: allContentCompleted || autoPassed('content'),
      active: contentActive,
    },
    {
      key: 'structured_artifacts',
      title: 'Artefacts structurés',
      detail: 'content-plan, draft-sections, course-scripts et reviewed-scripts.',
      icon: 'data_object',
      artifacts: ['content-plan.json', 'content-draft-sections.json', 'content-course-scripts.json', 'content-reviewed-scripts.json'],
      done: allContentCompleted || autoPassed('content'),
      active: contentActive,
    },
    {
      key: 'local_compliance',
      title: 'Conformité par morceau',
      detail: 'Review locale hors micro-éthique : hallucinations, TTS, oral et architecture, sans dépasser le budget.',
      icon: 'verified_user',
      reportEndpoint: 'review-report',
      auditMode: 'review_report',
      done: allReviewed || Boolean(job.auto_pilot_post_review_docs_done) || autoPassed('review'),
      active: autoActive('review'),
    },
    {
      key: 'post_review_docs',
      title: 'Texte validé, Word 2 et audio-plan',
      detail: 'Assemblage du texte validé localement et artefacts prêts pour les slides.',
      icon: 'description',
      artifacts: ['content-reviewed-scripts.json', 'content-audio-plan.json', 'content-script-plan.json'],
      done: postDocsDone || finalBudgetDone || autoPassed('post_review_docs'),
      active: autoActive('post_review_docs'),
    },
    {
      key: 'slides',
      title: 'Slides anchor-first',
      detail: 'Deck généré depuis les anchors du JSON, puis persisté par journée.',
      icon: 'slideshow',
      auditMode: 'slides',
      done: slidesDone,
      active: autoActive('slides'),
    },
    {
      key: 'done',
      title: 'Finalisation',
      detail: 'Texte, Word 2 et slides prêts ; audio lançable séparément depuis chaque journée.',
      icon: 'inventory_2',
      done: slidesDone || autoDone,
      active: autoActive('done'),
    },
  ]

  const doneCount = stages.filter(stage => stage.done || stage.optional).length
  const activeLabel = AUTO_PILOT_STEP_LABELS[activeAutoStep] || (activeAutoStep ? String(activeAutoStep).replace(/_/g, ' ') : null)

  return (
    <div style={{ ...S.card, marginBottom: '22px', padding: '18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '12px' }}>
        <div style={{ ...S.cardTitle, marginBottom: 0, flex: 1, minWidth: 0 }}>
          <Icon name="route" /> Roadmap auto-pilot API
        </div>
        <span style={S.tag(activeAutoStep ? 'amber' : doneCount === stages.length ? 'green' : 'violet')}>
          <Icon name={activeAutoStep ? 'hourglass_empty' : 'timeline'} />
          {activeAutoStep ? `Actif : ${activeLabel}` : `${doneCount}/${stages.length} étapes`}
        </span>
      </div>
      <div style={{ fontSize: '12px', color: '#94a3b8', lineHeight: 1.45, marginBottom: '14px' }}>
        Cette carte montre le vrai trajet de fabrication : plan structuré, génération par sections,
        adhérence au plan, calibrage budget, micro-review éthique, artefacts, reviews, puis slides anchor-first.
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(255px, 1fr))',
        gap: '9px',
      }}>
        {stages.map((stage, index) => (
          <PipelineStagePill
            key={`${index}-${stage.title}`}
            stage={stage}
            index={index}
            onClick={() => setAuditStage({ stage, index })}
          />
        ))}
      </div>
      {auditStage && (
        <PipelineStepAuditModal
          job={job}
          stage={auditStage.stage}
          index={auditStage.index}
          folders={folders}
          events={events}
          onClose={() => setAuditStage(null)}
        />
      )}
    </div>
  )
}

const PIPELINE_STAGE_EVENT_ALIASES = {
  start: ['start', 'init'],
  reac: ['reac'],
  kb: ['kb'],
  global: ['global'],
  daily: ['daily'],
  plan_json: ['content', 'structured_plan'],
  slide_beats: ['content', 'slides'],
  section_generation: ['content', 'structured_section'],
  plan_adherence: ['content', 'plan_adherence', 'plan_adherence_review', 'structured_section'],
  ethical_micro: ['content', 'ethical_micro'],
  structured_artifacts: ['content', 'artifact'],
  budget_calibration: ['content', 'budget', 'calibration'],
  local_compliance: ['review'],
  post_review_docs: ['post_review_docs', 'word_budget_review'],
  slides: ['slides'],
  audio: ['audio'],
  done: ['done', 'finalize'],
}

function eventMatchesPipelineStage(event, stage) {
  const aliases = PIPELINE_STAGE_EVENT_ALIASES[stage.key] || [stage.key]
  const haystack = [
    event?.step,
    event?.event_type,
    event?.message,
  ].filter(Boolean).join(' ').toLowerCase()
  return aliases.some(alias => haystack.includes(String(alias).toLowerCase()))
}

function pipelineStageStatusLabel(stage) {
  if (stage.done) return 'OK'
  if (stage.active) return 'En cours'
  if (stage.optional) return 'Optionnel'
  return 'À venir'
}

function PipelineStepAuditModal({ job, stage, index, folders, events, onClose }) {
  const [payload, setPayload] = useState({ artifacts: [], reports: [], slideDecks: [], kb: null })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const stageEvents = (events || []).filter(event => eventMatchesPipelineStage(event, stage)).slice(0, 20)
  const folderList = (folders || []).filter(folder => folder.folder_id)
  const artifactNames = stage.artifacts || []

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      const artifacts = []
      const reports = []
      const slideDecks = []
      let kb = null

      try {
        if (stage.auditMode === 'kb') {
          try {
            const resp = await fetch(apiUrl(`/api/formation/${job.id}/kb`), { credentials: 'include' })
            const data = await resp.json()
            kb = resp.ok ? { entries: data.entries || [], stats: data.stats || {}, error: '' } : { entries: [], stats: {}, error: data.error || 'Knowledge Base indisponible' }
          } catch {
            kb = { entries: [], stats: {}, error: 'Erreur réseau Knowledge Base' }
          }
        }

        if (artifactNames.length > 0) {
          const artifactResults = await Promise.all(
            folderList.flatMap(folder =>
              artifactNames.map(async name => {
                try {
                  const resp = await fetch(
                    apiUrl(`/api/formation/${job.id}/content/${folder.folder_id}/artifact/${encodeURIComponent(name)}`),
                    { credentials: 'include' },
                  )
                  const data = await resp.json()
                  return { folder, name, ok: resp.ok, artifact: data.artifact || null, error: data.error || '' }
                } catch (e) {
                  return { folder, name, ok: false, artifact: null, error: 'Erreur réseau' }
                }
              }),
            ),
          )
          artifacts.push(...artifactResults)
        }

        if (stage.reportEndpoint) {
          const reportResults = await Promise.all(
            folderList.map(async folder => {
              try {
                const resp = await fetch(
                  apiUrl(`/api/formation/${job.id}/content/${folder.folder_id}/${stage.reportEndpoint}`),
                  { credentials: 'include' },
                )
                const data = await resp.json()
                return { folder, ok: resp.ok, report: data.report || null, error: data.error || '' }
              } catch (e) {
                return { folder, ok: false, report: null, error: 'Erreur réseau' }
              }
            }),
          )
          reports.push(...reportResults)
        }

        if (stage.auditMode === 'slides') {
          const deckResults = await Promise.all(
            folderList.map(async folder => {
              try {
                const resp = await fetch(
                  apiUrl(`/api/slides/data?folder_id=${encodeURIComponent(folder.folder_id)}`),
                  { credentials: 'include' },
                )
                const data = await resp.json()
                return {
                  folder,
                  ok: resp.ok && data.status === 'success',
                  deck: data.status === 'success' ? data : null,
                  error: data.message || data.error || '',
                }
              } catch (e) {
                return { folder, ok: false, deck: null, error: 'Erreur réseau' }
              }
            }),
          )
          slideDecks.push(...deckResults)
        }

        if (!cancelled) setPayload({ artifacts, reports, slideDecks, kb })
      } catch (e) {
        if (!cancelled) setError('Impossible de charger le détail de cette étape.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [job.id, stage.key])

  const loadedArtifacts = payload.artifacts.filter(item => item.ok && item.artifact)
  const loadedReports = payload.reports.filter(item => item.ok && item.report)
  const loadedSlideDecks = payload.slideDecks.filter(item => item.ok && item.deck)
  const patchStats = computeAuditPatchStats(payload)

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.72)',
      zIndex: 1200, padding: '20px', display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 'min(1180px, 100%)', maxHeight: '92vh', overflow: 'hidden',
        background: '#111827', border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: '12px', display: 'flex', flexDirection: 'column',
        boxShadow: '0 24px 80px rgba(0,0,0,0.45)',
      }}>
        <div style={{
          padding: '18px 22px', borderBottom: '1px solid rgba(148,163,184,0.14)',
          display: 'flex', justifyContent: 'space-between', gap: '16px', alignItems: 'flex-start',
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Étape {String(index + 1).padStart(2, '0')} · {pipelineStageStatusLabel(stage)}
            </div>
            <div style={{ color: '#e2e8f0', fontSize: '19px', fontWeight: 800, marginTop: '4px' }}>
              {stage.title}
            </div>
            <div style={{ color: '#94a3b8', fontSize: '13px', lineHeight: 1.45, marginTop: '5px' }}>
              {stage.detail}
            </div>
          </div>
          <button onClick={onClose} style={{ ...S.btn('ghost'), padding: '5px 10px', flexShrink: 0 }}>
            <Icon name="close" />
          </button>
        </div>

        <div style={{ overflow: 'auto', padding: '20px 22px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))', gap: '10px', marginBottom: '18px' }}>
            <AuditStatCard label="Dossiers" value={folderList.length} color="#a78bfa" />
            <AuditStatCard label="Événements" value={stageEvents.length} color="#94a3b8" />
            <AuditStatCard label="Artefacts" value={loadedArtifacts.length} color="#38bdf8" />
            <AuditStatCard label="Rapports" value={loadedReports.length} color="#34d399" />
            <AuditStatCard label="Decks slides" value={loadedSlideDecks.length} color="#f59e0b" />
            <AuditStatCard label="Patches appliqués" value={patchStats.applied} color="#60a5fa" />
            <AuditStatCard label="Patches rejetés" value={patchStats.rejected} color="#fb923c" />
          </div>

          {loading && <div style={{ color: '#94a3b8', fontSize: '13px' }}>Chargement du détail…</div>}
          {error && <div style={{ color: '#f87171', fontSize: '13px' }}><Icon name="error" /> {error}</div>}

          {!loading && stage.auditMode === 'job_init' && (
            <JobInitializationAuditView job={job} folders={folderList} />
          )}
          {!loading && stage.auditMode === 'reac' && (
            <ReacAuditView job={job} />
          )}
          {!loading && stage.auditMode === 'kb' && (
            <KnowledgeBaseAuditView kb={payload.kb} job={job} />
          )}
          {!loading && stage.auditMode === 'global_program' && (
            <GlobalProgramAuditView job={job} />
          )}
          {!loading && stage.auditMode === 'daily_programs' && (
            <DailyProgramsAuditView job={job} />
          )}
          {!loading && stage.auditMode === 'plan_json' && (
            <PlanJsonAuditView artifacts={payload.artifacts} />
          )}
          {!loading && stage.auditMode === 'slide_beats' && (
            <SlideBeatsAuditView artifacts={payload.artifacts} />
          )}
          {!loading && stage.auditMode === 'ethical_micro' && (
            <EthicalMicroAuditView artifacts={payload.artifacts} />
          )}
          {!loading && stage.auditMode === 'section_generation' && (
            <SectionGenerationAuditView artifacts={payload.artifacts} />
          )}
          {!loading && stage.auditMode === 'plan_adherence' && (
            <PlanAdherenceAuditView artifacts={payload.artifacts} />
          )}
          {!loading && stage.auditMode === 'budget_calibration' && (
            <BudgetCalibrationAuditView artifacts={payload.artifacts} />
          )}
          {!loading && stage.auditMode === 'volume_safety' && (
            <VolumeSafetyAuditView artifacts={payload.artifacts} />
          )}
          {!loading && stage.auditMode === 'review_report' && (
            <ReviewReportsAuditView reports={payload.reports} />
          )}
          {!loading && stage.auditMode === 'slides' && (
            <SlidesDeckAuditView decks={payload.slideDecks} />
          )}
          {!loading && stage.auditMode !== 'job_init' && stage.auditMode !== 'reac' && stage.auditMode !== 'kb' && stage.auditMode !== 'global_program' && stage.auditMode !== 'daily_programs' && stage.auditMode !== 'plan_json' && stage.auditMode !== 'slide_beats' && stage.auditMode !== 'ethical_micro' && stage.auditMode !== 'section_generation' && stage.auditMode !== 'plan_adherence' && stage.auditMode !== 'budget_calibration' && stage.auditMode !== 'volume_safety' && stage.auditMode !== 'review_report' && stage.auditMode !== 'slides' && (
            <ArtifactAuditView artifacts={payload.artifacts} stage={stage} />
          )}

          <StepEventsList events={stageEvents} />
        </div>
      </div>
    </div>
  )
}

function AuditStatCard({ label, value, color }) {
  return (
    <div style={{ padding: '11px 12px', background: 'rgba(15,23,42,0.55)', border: '1px solid rgba(148,163,184,0.14)', borderRadius: '8px' }}>
      <div style={{ color: '#94a3b8', fontSize: '11px', marginBottom: '3px' }}>{label}</div>
      <div style={{ color, fontSize: '21px', fontWeight: 800 }}>{value}</div>
    </div>
  )
}

function JobInitializationAuditView({ job, folders }) {
  const rows = [
    ['Job', job.job_label || `#${job.id}`],
    ['Titre professionnel', job.tp_name || 'Non renseigné'],
    ['RNCP', job.rncp_code ? `RNCP ${job.rncp_code}` : 'Non renseigné'],
    ['Plateforme', job.platform_id ? `#${job.platform_id}` : 'Non liée'],
    ['Durée', `${job.total_hours || 0}h · ${job.nb_days || 0} journée${Number(job.nb_days || 0) > 1 ? 's' : ''}`],
    ['Statut actuel', job.status || 'Inconnu'],
    ['Dossiers cours', folders.length],
  ]

  return (
    <AuditInfoPanel
      icon="search"
      title="Initialisation du module"
      detail="Cette étape pose le contexte durable du module : RNCP, titre professionnel, durée cible, plateforme et nombre de journées attendues."
    >
      <AuditKeyValueGrid rows={rows} />
    </AuditInfoPanel>
  )
}

function ReacAuditView({ job }) {
  const rows = [
    ['REAC', job.reac_available ? 'Téléchargé' : 'Non disponible'],
    ['Taille REAC', `${formatAuditNumber(job.reac_length || 0)} caractères`],
    ['Référentiel de certification', `${formatAuditNumber(job.rc_length || 0)} caractères`],
    ['Fiches ROME', `${formatAuditNumber(job.rome_length || 0)} caractères`],
    ['Source', job.reac_available ? 'France Compétences / extraction backend' : 'En attente de récupération'],
  ]

  return (
    <AuditInfoPanel
      icon="download"
      title="Sources RNCP récupérées"
      detail="Le texte brut du REAC n'est pas affiché ici pour garder la modale légère ; l'API expose les tailles et la disponibilité des sources."
    >
      <AuditKeyValueGrid rows={rows} />
    </AuditInfoPanel>
  )
}

function KnowledgeBaseAuditView({ kb, job }) {
  const entries = Array.isArray(kb?.entries) ? kb.entries : []
  const stats = kb?.stats || {}

  if (kb?.error) {
    return <AuditEmptyState icon="error" title="Knowledge Base indisponible" detail={kb.error} />
  }

  if (!entries.length) {
    return (
      <AuditEmptyState
        icon="psychology"
        title="Aucune compétence enrichie visible"
        detail="La Knowledge Base n'a pas encore tourné, ou aucune entrée exploitable n'a été renvoyée par l'API."
      />
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '14px' }}>
        <div style={{
          padding: '10px 16px', borderRadius: '10px',
          background: 'rgba(16,185,129,0.08)',
          border: '1px solid rgba(16,185,129,0.25)',
        }}>
          <div style={{ fontSize: '22px', fontWeight: 700, color: '#34d399' }}>
            {stats.completed ?? entries.filter(e => e.status === 'completed').length}
          </div>
          <div style={{ fontSize: '11px', color: '#64748b', marginTop: 2 }}>compétences enrichies</div>
        </div>
        <div style={{
          padding: '10px 16px', borderRadius: '10px',
          background: 'rgba(139,92,246,0.08)',
          border: '1px solid rgba(139,92,246,0.25)',
        }}>
          <div style={{ fontSize: '22px', fontWeight: 700, color: '#a78bfa' }}>
            {Number(stats.total_words || 0) >= 1000 ? `${(Number(stats.total_words || 0) / 1000).toFixed(1)}k` : (stats.total_words || 0)}
          </div>
          <div style={{ fontSize: '11px', color: '#64748b', marginTop: 2 }}>mots dans la KB</div>
        </div>
        {Number(stats.error || 0) > 0 && (
          <div style={{
            padding: '10px 16px', borderRadius: '10px',
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.25)',
          }}>
            <div style={{ fontSize: '22px', fontWeight: 700, color: '#f87171' }}>{stats.error}</div>
            <div style={{ fontSize: '11px', color: '#64748b', marginTop: 2 }}>compétences en erreur</div>
          </div>
        )}
      </div>

      <details style={{ marginBottom: '14px' }} open>
        <summary style={{ cursor: 'pointer', fontSize: '13px', color: '#a78bfa', marginBottom: '10px' }}>
          Voir le détail des compétences enrichies ({entries.length})
        </summary>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '10px', maxHeight: '620px', overflowY: 'auto' }}>
          {entries.map((entry, index) => (
            <KnowledgeBaseEntryDetails key={entry.id || entry.competence_index || index} entry={entry} />
          ))}
        </div>
      </details>
    </div>
  )
}

function GlobalProgramAuditView({ job }) {
  const text = job.global_program || ''
  if (!text.trim()) {
    return (
      <AuditEmptyState
        icon="auto_stories"
        title="Programme global non disponible"
        detail="Le programme global n'a pas encore été généré ou n'est pas renvoyé par l'API du job."
      />
    )
  }

  return (
    <AuditInfoPanel
      icon="auto_stories"
      title="Programme global"
      detail={`${formatAuditNumber(countAuditWords(text))} mots · validation ${job.global_program_validated ? 'effectuée' : 'en attente'}.`}
    >
      <div style={{ background: 'rgba(15,23,42,0.6)', borderRadius: '10px', padding: '16px', maxHeight: '560px', overflowY: 'auto', fontSize: '13px', color: '#cbd5e1', lineHeight: '1.6', whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
        {text}
      </div>
    </AuditInfoPanel>
  )
}

function DailyProgramsAuditView({ job }) {
  const programs = parseDailyProgramsForAudit(job.daily_programs)
  if (!programs.length) {
    return (
      <AuditEmptyState
        icon="calendar_view_week"
        title="Programmes journée non disponibles"
        detail="Le découpage journée n'a pas encore été généré ou le JSON daily_programs est vide."
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '13px', color: '#94a3b8' }}>
          {programs.length} journées générées. Validation {job.daily_programs_validated ? 'effectuée' : 'en attente'}.
        </span>
        <span style={S.tag(job.daily_programs_validated ? 'green' : 'violet')}>
          <Icon name={job.daily_programs_validated ? 'check' : 'calendar_view_week'} />
          {job.daily_programs_validated ? 'Journées validées' : `${job.nb_days || programs.length} jours prévus`}
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {programs.map((day, index) => (
          <DailyProgramAuditDay key={day.day_number || index} day={day} index={index} initiallyOpen={index === 0} />
        ))}
      </div>
    </div>
  )
}

function KnowledgeBaseEntryDetails({ entry }) {
  return (
    <details style={{
      borderRadius: '8px',
      background: 'rgba(15,23,42,0.5)',
      borderLeft: `3px solid ${entry.status === 'completed' ? '#34d399' : entry.status === 'error' ? '#f87171' : '#64748b'}`,
    }}>
      <summary style={{ cursor: 'pointer', padding: '10px 14px', listStyle: 'none' }}>
        <div style={{ color: '#cbd5e1', fontWeight: 500, fontSize: '13px' }}>{entry.competence_title || entry.title || 'Compétence'}</div>
        <div style={{ color: '#64748b', marginTop: 2, fontSize: '11px' }}>
          {entry.bloc || 'Bloc non renseigné'} · {entry.status === 'completed' ? `${entry.total_words || entry.word_count || 0} mots` : entry.status}
          {entry.error_message && <span style={{ color: '#f87171' }}> — {entry.error_message}</span>}
        </div>
      </summary>
      {entry.status === 'completed' && (
        <div style={{ padding: '4px 14px 16px 14px', fontSize: '12px', color: '#cbd5e1', lineHeight: 1.6 }}>
          {entry.definition_pedagogique && (
            <div style={{ marginTop: '10px' }}>
              <div style={kbSectionTitleStyle}>Définition pédagogique</div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{entry.definition_pedagogique}</div>
            </div>
          )}
          {entry.contexte_terrain && (
            <div style={{ marginTop: '12px' }}>
              <div style={kbSectionTitleStyle}>Contexte terrain</div>
              <div style={{ whiteSpace: 'pre-wrap' }}>{entry.contexte_terrain}</div>
            </div>
          )}
          {Array.isArray(entry.etudes_de_cas) && entry.etudes_de_cas.length > 0 && (
            <div style={{ marginTop: '12px' }}>
              <div style={kbSectionTitleStyle}>Études de cas ({entry.etudes_de_cas.length})</div>
              {entry.etudes_de_cas.map((cas, idx) => (
                <div key={idx} style={{ marginBottom: '10px', padding: '8px 12px', background: 'rgba(139,92,246,0.06)', borderLeft: '2px solid rgba(139,92,246,0.4)', borderRadius: '4px' }}>
                  <div style={{ fontWeight: 600, color: '#e2e8f0', marginBottom: '4px' }}>{cas.titre || cas.title || `Cas ${idx + 1}`}</div>
                  {cas.situation && <div><strong style={{ color: '#94a3b8' }}>Situation :</strong> {cas.situation}</div>}
                  {cas.enjeu && <div style={{ marginTop: '3px' }}><strong style={{ color: '#94a3b8' }}>Enjeu :</strong> {cas.enjeu}</div>}
                  {cas.resolution_attendue && <div style={{ marginTop: '3px' }}><strong style={{ color: '#94a3b8' }}>Résolution :</strong> {cas.resolution_attendue}</div>}
                  {cas.variantes && <div style={{ marginTop: '3px' }}><strong style={{ color: '#94a3b8' }}>Variantes :</strong> {cas.variantes}</div>}
                </div>
              ))}
            </div>
          )}
          {Array.isArray(entry.pieges_frequents) && entry.pieges_frequents.length > 0 && (
            <div style={{ marginTop: '12px' }}>
              <div style={kbSectionTitleStyle}>Pièges fréquents ({entry.pieges_frequents.length})</div>
              {entry.pieges_frequents.map((p, idx) => (
                <div key={idx} style={{ marginBottom: '8px', padding: '8px 12px', background: 'rgba(239,68,68,0.05)', borderLeft: '2px solid rgba(239,68,68,0.35)', borderRadius: '4px' }}>
                  <div style={{ fontWeight: 600, color: '#e2e8f0', marginBottom: '3px' }}>{p.piege || p.title || `Piège ${idx + 1}`}</div>
                  {p.pourquoi_frequent && <div><strong style={{ color: '#94a3b8' }}>Pourquoi :</strong> {p.pourquoi_frequent}</div>}
                  {p.comment_eviter && <div style={{ marginTop: '3px' }}><strong style={{ color: '#94a3b8' }}>Comment éviter :</strong> {p.comment_eviter}</div>}
                </div>
              ))}
            </div>
          )}
          {entry.vocabulaire_metier && Object.keys(entry.vocabulaire_metier).length > 0 && (
            <div style={{ marginTop: '12px' }}>
              <div style={kbSectionTitleStyle}>Vocabulaire métier ({Object.keys(entry.vocabulaire_metier).length})</div>
              <dl style={{ margin: 0 }}>
                {Object.entries(entry.vocabulaire_metier).map(([terme, def], idx) => (
                  <div key={idx} style={{ marginBottom: '6px' }}>
                    <dt style={{ display: 'inline', fontWeight: 600, color: '#34d399' }}>{terme}</dt>
                    <dd style={{ display: 'inline', margin: 0, marginLeft: '6px', color: '#cbd5e1' }}>: {def}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          {Array.isArray(entry.liens_connexes) && entry.liens_connexes.length > 0 && (
            <div style={{ marginTop: '12px', color: '#64748b', fontSize: '11px', fontStyle: 'italic' }}>
              Liens connexes : {entry.liens_connexes.join(', ')}
            </div>
          )}
        </div>
      )}
    </details>
  )
}

const kbSectionTitleStyle = {
  color: '#a78bfa',
  fontWeight: 600,
  fontSize: '11px',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  marginBottom: '4px',
}

function DailyProgramAuditDay({ day, index, initiallyOpen }) {
  const subParts = Array.isArray(day.sub_parts)
    ? day.sub_parts
    : Array.isArray(day.courses)
      ? day.courses.map(course => ({
          name: course.course_title || course.title,
          content: course.module_content || course.description || course.objective,
        }))
      : Array.isArray(day.modules)
        ? day.modules
        : []

  return (
    <details open={initiallyOpen} style={{ background: 'rgba(15,23,42,0.5)', borderRadius: '10px', border: '1px solid rgba(99,102,241,0.15)', overflow: 'hidden' }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', padding: '12px 16px' }}>
          <div style={{ minWidth: 0 }}>
            <span style={{ fontWeight: 600, fontSize: '14px', color: '#e2e8f0' }}>Jour {day.day_number || index + 1}</span>
            <span style={{ color: '#64748b', fontSize: '13px', marginLeft: '10px' }}>{day.title || day.day_title || 'Programme journée'}</span>
          </div>
          <span style={{ fontSize: '12px', color: '#64748b', whiteSpace: 'nowrap' }}>{subParts.length} modules</span>
        </div>
      </summary>

      <div style={{ padding: '10px 16px 14px', borderTop: '1px solid rgba(99,102,241,0.12)' }}>
        {subParts.length > 0 ? (
          <>
            <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '12px' }}>
              {subParts.map((sp, si) => (
                <span key={si} style={{ display: 'inline-block', background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.15)', borderRadius: '6px', padding: '2px 8px', margin: '2px', fontSize: '11px', color: '#a78bfa' }}>
                  {sp.name || sp.course_title || sp.title || `Module ${si + 1}`}
                </span>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '10px' }}>
              {subParts.map((sp, si) => (
                <div key={si} style={{
                  padding: '10px 11px',
                  borderRadius: '8px',
                  background: 'rgba(2,6,23,0.34)',
                  border: '1px solid rgba(148,163,184,0.10)',
                }}>
                  <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '12.5px' }}>
                    {sp.name || sp.course_title || sp.title || `Module ${si + 1}`}
                  </div>
                  {(sp.content || sp.module_content || sp.description || sp.objective) && (
                    <div style={{ color: '#94a3b8', fontSize: '12px', lineHeight: 1.55, marginTop: '6px' }}>
                      {sp.content || sp.module_content || sp.description || sp.objective}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        ) : (
          <AuditEmptyState
            icon="info"
            title="Aucun module lisible"
            detail="La journée existe, mais elle ne contient pas de liste sub_parts/courses exploitable."
          />
        )}
      </div>
    </details>
  )
}

function AuditInfoPanel({ icon, title, detail, children }) {
  return (
    <div style={{
      padding: '14px',
      background: 'rgba(15,23,42,0.48)',
      border: '1px solid rgba(148,163,184,0.14)',
      borderRadius: '10px',
    }}>
      <div style={{ color: '#e2e8f0', fontWeight: 900, fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Icon name={icon} /> {title}
      </div>
      {detail && (
        <div style={{ color: '#94a3b8', fontSize: '12px', lineHeight: 1.5, marginTop: '6px', marginBottom: children ? '12px' : 0 }}>
          {detail}
        </div>
      )}
      {children}
    </div>
  )
}

function AuditKeyValueGrid({ rows }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '8px' }}>
      {(rows || []).map(([label, value]) => (
        <div key={label} style={{
          padding: '9px 10px',
          background: 'rgba(2,6,23,0.34)',
          border: '1px solid rgba(148,163,184,0.10)',
          borderRadius: '8px',
        }}>
          <div style={{ color: '#94a3b8', fontSize: '10.5px', marginBottom: '3px' }}>{label}</div>
          <div style={{ color: '#e2e8f0', fontSize: '12.5px', fontWeight: 800 }}>{value ?? '—'}</div>
        </div>
      ))}
    </div>
  )
}

function AuditTextBlock({ text, empty = 'Aucun texte disponible.' }) {
  return (
    <div style={{
      color: '#cbd5e1',
      fontSize: '12px',
      lineHeight: 1.62,
      whiteSpace: 'pre-wrap',
      background: 'rgba(2,6,23,0.42)',
      border: '1px solid rgba(148,163,184,0.10)',
      borderRadius: '8px',
      padding: '12px',
      maxHeight: '520px',
      overflow: 'auto',
    }}>
      {String(text || '').trim() || empty}
    </div>
  )
}

function parseDailyProgramsForAudit(raw) {
  if (Array.isArray(raw)) return raw
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function SlidesDeckAuditView({ decks }) {
  const loaded = (decks || []).filter(item => item.ok && item.deck)

  if (!loaded.length) {
    return (
      <AuditEmptyState
        icon="slideshow"
        title="Aucun deck slides disponible"
        detail="La génération slides n'a pas encore persisté de deck pour les dossiers de ce job."
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{
        padding: '12px 14px',
        background: 'rgba(245,158,11,0.08)',
        border: '1px solid rgba(245,158,11,0.24)',
        borderRadius: '10px',
        color: '#fde68a',
        fontSize: '12px',
        lineHeight: 1.5,
      }}>
        <strong>Lecture de l'étape slides.</strong> Sélectionnez une slide : la modale affiche le passage source délimité du texte final à gauche et l'image de la slide générée à droite. La référence mots vient de la fenêtre source attachée à la slide.
      </div>
      {loaded.map((item, index) => (
        <SlideDeckDayAudit
          key={item.folder?.folder_id || index}
          folder={item.folder}
          deck={item.deck}
          initiallyOpen={index === 0}
        />
      ))}
    </div>
  )
}

function SlideDeckDayAudit({ folder, deck, initiallyOpen }) {
  const [open, setOpen] = useState(Boolean(initiallyOpen))
  const [selectedSlideIndex, setSelectedSlideIndex] = useState(0)
  const slides = Array.isArray(deck?.slides) ? deck.slides : []
  const stats = deck?.stats || {}
  const activeSlideIndex = slides.length ? Math.min(selectedSlideIndex, slides.length - 1) : 0
  const activeSlide = slides[activeSlideIndex]

  return (
    <div style={{ border: '1px solid rgba(148,163,184,0.16)', borderRadius: '10px', overflow: 'hidden', background: 'rgba(15,23,42,0.38)' }}>
      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        style={{
          width: '100%',
          padding: '13px 15px',
          background: 'rgba(30,41,59,0.72)',
          border: 'none',
          color: '#e2e8f0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
          <Icon name={open ? 'expand_less' : 'expand_more'} />
          <span style={{ fontWeight: 800 }}>{folderDisplayName(folder)}</span>
          <span style={{ color: '#94a3b8', fontSize: '12px' }}>{slides.length} slides</span>
        </span>
        <span style={{ color: '#94a3b8', fontSize: '12px' }}>
          {stats.generation_mode || deck.generation_mode || 'script'}
        </span>
      </button>

      {open && (
        <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {slides.length === 0 ? (
            <AuditEmptyState
              icon="slideshow"
              title="Deck vide"
              detail="Le deck a été trouvé, mais il ne contient aucune slide exploitable."
            />
          ) : (
            <>
              <div style={{
                display: 'flex',
                gap: '8px',
                overflowX: 'auto',
                padding: '2px 0 8px',
              }}>
                {slides.map((slide, index) => {
                  const selected = index === activeSlideIndex
                  return (
                    <button
                      key={slide.slide_id || index}
                      type="button"
                      onClick={() => setSelectedSlideIndex(index)}
                      style={{
                        flex: '0 0 auto',
                        minWidth: '118px',
                        padding: '8px 10px',
                        borderRadius: '8px',
                        border: `1px solid ${selected ? 'rgba(245,158,11,0.56)' : 'rgba(148,163,184,0.14)'}`,
                        background: selected ? 'rgba(245,158,11,0.12)' : 'rgba(15,23,42,0.52)',
                        color: selected ? '#fde68a' : '#cbd5e1',
                        cursor: 'pointer',
                        textAlign: 'left',
                      }}
                    >
                      <div style={{ fontSize: '11px', fontWeight: 900 }}>Slide {index + 1}</div>
                      <div style={{ fontSize: '10px', color: selected ? '#fcd34d' : '#94a3b8', marginTop: '3px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {slide.template_type || 'template'}
                      </div>
                    </button>
                  )
                })}
              </div>
              <SlideSourcePreviewRow slide={activeSlide} index={activeSlideIndex} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

function SlideSourcePreviewRow({ slide, index }) {
  const sourceRef = slide.source_ref || {}
  const sourceText = normalizeWhitespace(slide.source_text || '')
  const sourceRange = sourceRef.word_start !== undefined || sourceRef.word_end !== undefined
    ? `mots ${sourceRef.word_start ?? '--'}-${sourceRef.word_end ?? '--'}`
    : 'fenêtre source'

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 380px), 1fr))',
      gap: '16px',
      alignItems: 'stretch',
      padding: '14px',
      border: '1px solid rgba(148,163,184,0.14)',
      borderRadius: '10px',
      background: 'rgba(2,6,23,0.32)',
    }}>
      <div style={{
        borderRadius: '8px',
        border: '1px solid rgba(148,163,184,0.14)',
        background: 'rgba(15,23,42,0.75)',
        overflow: 'hidden',
        minHeight: '260px',
        display: 'flex',
        flexDirection: 'column',
      }}>
        <div style={{
          padding: '10px 12px',
          borderBottom: '1px solid rgba(148,163,184,0.12)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '10px',
        }}>
          <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '13px' }}>
            Texte final délimité · slide {index + 1}
          </div>
          <div style={{ color: '#94a3b8', fontSize: '11px', whiteSpace: 'nowrap' }}>
            {sourceRange}
          </div>
        </div>
        <div style={{ padding: '12px', color: '#cbd5e1', fontSize: '12px', lineHeight: 1.65, overflow: 'auto', maxHeight: '420px' }}>
          {sourceRef.sub_part_name && (
            <div style={{ color: '#93c5fd', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' }}>
              {sourceRef.sub_part_name}
            </div>
          )}
          {slide.slide_anchor_id && (
            <div style={{ color: '#fde68a', fontSize: '11px', marginBottom: '8px' }}>
              Anchor: <strong>{slide.slide_anchor_id}</strong>{slide.beat_id ? ` · ${slide.beat_id}` : ''}
            </div>
          )}
          {slide.event_summary && (
            <div style={{
              marginBottom: '10px',
              padding: '8px 9px',
              border: '1px solid rgba(96,165,250,0.18)',
              borderRadius: '7px',
              background: 'rgba(59,130,246,0.08)',
              color: '#bfdbfe',
              fontSize: '11px',
              lineHeight: 1.45,
            }}>
              Idée visualisée : {slide.event_summary}
            </div>
          )}
          <div>{sourceText || 'Passage source non disponible.'}</div>
        </div>
      </div>

      <div style={{
        borderRadius: '8px',
        border: '1px solid rgba(148,163,184,0.14)',
        background: '#020617',
        overflow: 'hidden',
        minHeight: '260px',
        display: 'flex',
        flexDirection: 'column',
      }}>
        <div style={{
          padding: '10px 12px',
          borderBottom: '1px solid rgba(148,163,184,0.12)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '10px',
        }}>
          <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '13px' }}>
            Image de la slide générée
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
            {slide.event_type && (
              <span style={{
                color: '#c4b5fd',
                background: 'rgba(139,92,246,0.13)',
                border: '1px solid rgba(139,92,246,0.22)',
                borderRadius: '999px',
                padding: '2px 7px',
                fontSize: '10px',
                fontWeight: 800,
                whiteSpace: 'nowrap',
              }}>
                {slide.event_type}
              </span>
            )}
            <span style={{ color: '#94a3b8', fontSize: '11px', whiteSpace: 'nowrap' }}>
              {slide.template_type || 'template'}
            </span>
          </div>
        </div>
        <SlidePreviewFrame slide={slide} />
      </div>
    </div>
  )
}

function SlidePreviewFrame({ slide }) {
  return (
    <div style={{ padding: '14px', display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, overflow: 'hidden' }}>
      <div style={{
        width: '100%',
        maxWidth: '720px',
        aspectRatio: '16 / 9',
        flex: '0 1 720px',
        borderRadius: '6px',
        overflow: 'hidden',
        boxShadow: '0 16px 40px rgba(0,0,0,0.35)',
      }} className="pipeline-slide-preview-scope">
        {renderPipelineSlidePreview(slide)}
      </div>
    </div>
  )
}

function renderPipelineSlidePreview(slide = {}) {
  const commonProps = {
    badge: 'TP-CRCD',
    brandName: 'SALES HACKING',
  }
  const props = { ...(slide.data || {}), ...commonProps }

  switch (slide.template_type) {
    case 'welcome':
      return <WelcomeSlidePreview {...props} />
    case 'day_program':
      return <DayProgramSlidePreview {...props} />
    case 'context':
      return <ContextSlidePreview {...props} />
    case 'reflection':
      return <ReflectionTemplate {...props} />
    case 'casestudy':
      return <CaseStudyTemplate {...props} />
    case 'facilitator':
      return <FacilitatorTemplate {...props} />
    case 'chart':
      return <ChartTemplate {...props} />
    case 'stats':
      return <StatsTemplate {...props} />
    case 'story':
      return <StoryTemplate {...props} />
    case 'recap':
      return <RecapTemplate {...props} />
    case 'analogy':
      return <AnalogyTemplate {...props} />
    case 'warning':
      return <WarningTemplate {...props} />
    case 'tip':
      return <TipTemplate {...props} />
    case 'opinion':
      return <OpinionTemplate {...props} />
    case 'transition':
      return <TransitionTemplate {...props} />
    case 'playful':
      return <PlayfulTemplate {...props} />
    default:
      return (
        <div style={{ width: '100%', height: '100%', background: '#f8fafc', color: '#0f172a', padding: '48px', fontFamily: 'Inter, system-ui, sans-serif' }}>
          <div style={{ fontSize: '42px', fontWeight: 800, marginBottom: '18px' }}>
            Template non reconnu
          </div>
          <div style={{ fontSize: '24px' }}>{slide.template_type || 'inconnu'}</div>
        </div>
      )
  }
}

function WelcomeSlidePreview({ title = 'Bienvenue', subtitle, formation_name, day_label, badge = 'TP-CRCD', brandName = 'SALES HACKING' }) {
  return (
    <div style={{
      width: '100%',
      height: '100%',
      background: '#f8fafc',
      color: '#0f172a',
      fontFamily: 'Inter, system-ui, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      padding: '36px 44px',
      boxSizing: 'border-box',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#64748b', fontSize: '16px', fontWeight: 800 }}>
        <span>{badge}</span>
        <span>{brandName}</span>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <div style={{ color: '#dc2626', fontSize: '18px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '18px' }}>
          {day_label || subtitle || 'Journée de formation'}
        </div>
        <div style={{ fontSize: '58px', lineHeight: 1, fontWeight: 950 }}>
          {title}
        </div>
        <div style={{ marginTop: '24px', height: '3px', width: '88px', background: '#dc2626', borderRadius: '999px' }} />
        <div style={{ marginTop: '24px', fontSize: '30px', lineHeight: 1.18, fontWeight: 850, color: '#334155', maxWidth: '820px' }}>
          {formation_name || subtitle || 'Formation'}
        </div>
      </div>
    </div>
  )
}

function DayProgramSlidePreview({ title = 'Programme de la journée', items = [], day_label, formation_name, badge = 'TP-CRCD', brandName = 'SALES HACKING' }) {
  const safeItems = Array.isArray(items) && items.length ? items.slice(0, 7) : ['Accueil et objectifs', 'Thèmes clés', 'Synthèse et questions']
  return (
    <div style={{
      width: '100%',
      height: '100%',
      background: '#f8fafc',
      color: '#0f172a',
      fontFamily: 'Inter, system-ui, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      padding: '34px 44px',
      boxSizing: 'border-box',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#64748b', fontSize: '16px', fontWeight: 800 }}>
        <span>{badge}</span>
        <span>{brandName}</span>
      </div>
      <div style={{ marginTop: '26px', color: '#dc2626', fontSize: '16px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {day_label || formation_name || 'Séquence du jour'}
      </div>
      <div style={{ marginTop: '10px', fontSize: '42px', lineHeight: 1.05, fontWeight: 950 }}>
        {title}
      </div>
      <div style={{ marginTop: '24px', display: 'grid', gap: '8px', maxWidth: '820px' }}>
        {safeItems.map((item, index) => (
          <div key={index} style={{ display: 'grid', gridTemplateColumns: '36px 1fr', gap: '12px', alignItems: 'center', padding: '10px 12px', background: '#eef2f7', borderLeft: '4px solid #dc2626', borderRadius: '8px' }}>
            <div style={{ color: '#dc2626', fontWeight: 950, fontSize: '16px' }}>{String(index + 1).padStart(2, '0')}</div>
            <div style={{ fontSize: '18px', fontWeight: 800, color: '#334155', lineHeight: 1.2 }}>{item}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ContextSlidePreview({ formation_name, chapter, label, badge = 'TP-CRCD', brandName = 'SALES HACKING' }) {
  return (
    <div style={{
      width: '100%',
      height: '100%',
      background: '#f8fafc',
      color: '#0f172a',
      fontFamily: 'Inter, system-ui, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      padding: '36px 44px',
      boxSizing: 'border-box',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#64748b', fontSize: '16px', fontWeight: 800 }}>
        <span>{badge}</span>
        <span>{brandName}</span>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <div style={{ color: '#dc2626', fontSize: '18px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '18px' }}>
          {label || 'Séquence en cours'}
        </div>
        <div style={{ fontSize: '42px', lineHeight: 1.08, fontWeight: 900, maxWidth: '820px' }}>
          {formation_name || 'Formation'}
        </div>
        <div style={{ marginTop: '24px', height: '3px', width: '88px', background: '#dc2626', borderRadius: '999px' }} />
        <div style={{ marginTop: '24px', fontSize: '28px', lineHeight: 1.25, fontWeight: 800, color: '#334155', maxWidth: '780px' }}>
          {chapter || 'Chapitre en cours'}
        </div>
      </div>
    </div>
  )
}

function normalizeWhitespace(text) {
  return String(text || '').replace(/\s+/g, ' ').trim()
}

function computeAuditPatchStats(payload) {
  let applied = 0
  let rejected = 0
  for (const item of payload.artifacts || []) {
    const summary = item.artifact?.summary || {}
    const reviewSummary = item.artifact?.review_summary || {}
    applied += Number(summary.patches_applied || 0)
    rejected += Number(summary.patches_rejected || 0)
    applied += Number(reviewSummary.patches_applied || 0)
    rejected += Number(reviewSummary.patches_rejected || 0)
  }
  for (const item of payload.reports || []) {
    const summary = item.report?.summary || {}
    applied += Number(summary.patches_applied || 0)
    rejected += Number(summary.patches_rejected || 0)
  }
  return { applied, rejected }
}

function folderDisplayName(folder = {}) {
  return folder.folder_name || folder.name || `Dossier ${folder.folder_id}`
}

function SectionGenerationAuditView({ artifacts }) {
  const days = buildSectionGenerationDays(artifacts)
  const hasDraft = days.some(day => day.draft)

  if (!hasDraft) {
    return (
      <AuditEmptyState
        icon="info"
        title="Aucun texte généré par section disponible"
        detail="Cette étape n'a pas encore produit content-draft-sections.json, ou le job a été généré avant cet artefact."
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{
        padding: '12px 14px',
        background: 'rgba(59,130,246,0.08)',
        border: '1px solid rgba(96,165,250,0.22)',
        borderRadius: '10px',
        color: '#bfdbfe',
        fontSize: '12px',
        lineHeight: 1.5,
      }}>
        <strong>Lecture de l'étape 8.</strong> Cette vue montre le texte brut généré avant les reviews : budget prévu, mots réellement produits, sections, conclusions et slides prévues dans chaque partie. Quand un ancien artefact ne stocke pas encore le passage exact d'une slide, le passage est reconstruit depuis le texte de la section et marqué en estimation.
      </div>
      {days.map((day, index) => (
        <GeneratedDayAudit key={day.folder?.folder_id || index} day={day} initiallyOpen={index === 0} />
      ))}
    </div>
  )
}

function buildSectionGenerationDays(artifacts) {
  const byFolder = new Map()
  for (const item of artifacts || []) {
    const folderId = item.folder?.folder_id || item.folder_id || 'unknown'
    if (!byFolder.has(folderId)) {
      byFolder.set(folderId, { folder: item.folder || {}, planArtifact: null, draft: null, missing: [] })
    }
    const entry = byFolder.get(folderId)
    if (!item.ok || !item.artifact) {
      entry.missing.push(item.name)
      continue
    }
    if (item.name === 'content-plan.json') entry.planArtifact = item.artifact
    if (item.name === 'content-draft-sections.json') entry.draft = item.artifact
  }
  return Array.from(byFolder.values()).sort((a, b) =>
    Number(a.folder?.position ?? a.folder?.folder_position ?? a.folder?.folder_id ?? 0) -
    Number(b.folder?.position ?? b.folder?.folder_position ?? b.folder?.folder_id ?? 0),
  )
}

function GeneratedDayAudit({ day, initiallyOpen }) {
  const plan = day.planArtifact?.structured_course_plan || {}
  const planCourses = Array.isArray(plan.courses) ? plan.courses : []
  const draftCourses = Array.isArray(day.draft?.courses) ? day.draft.courses : []
  const courseNumbers = Array.from(new Set([
    ...planCourses.map(course => Number(course.course_number || 0)).filter(Boolean),
    ...draftCourses.map(course => Number(course.course_number || 0)).filter(Boolean),
  ])).sort((a, b) => a - b)
  const courses = courseNumbers.map(number => ({
    number,
    plan: planCourses.find(course => Number(course.course_number || 0) === number) || null,
    draft: draftCourses.find(course => Number(course.course_number || 0) === number) || null,
  }))
  const targetWords = courses.reduce((sum, course) => sum + Number(course.plan?.target_words || course.draft?.target_words || 0), 0)
  const actualWords = courses.reduce((sum, course) => sum + Number(course.draft?.draft_word_count || course.draft?.word_count || 0), 0)
  const slidesCount = planCourses.reduce((sum, course) =>
    sum + plannedSectionsForCourse(course).reduce((sectionSum, section) => sectionSum + slideBeatsForSection(section.plan).length, 0),
  0)

  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(15,23,42,0.48)',
      border: '1px solid rgba(148,163,184,0.14)',
      borderRadius: '12px',
      overflow: 'hidden',
    }}>
      <summary style={{
        cursor: 'pointer',
        padding: '14px 16px',
        color: '#e2e8f0',
        fontWeight: 900,
        listStyle: 'none',
        borderBottom: '1px solid rgba(148,163,184,0.12)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span><Icon name="calendar_view_week" /> {folderDisplayName(day.folder)}</span>
          <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <SmallMetric label="Thèmes" value={courses.length} />
            <SmallMetric label="Slides prévues" value={slidesCount} />
            <SmallMetric label="Mots" value={`${formatAuditNumber(actualWords)} / ${formatAuditNumber(targetWords)}`} />
          </span>
        </div>
      </summary>
      <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {courses.length === 0 && (
          <AuditEmptyState
            icon="info"
            title="Aucun thème lisible"
            detail="L'artefact existe, mais il ne contient pas de liste de thèmes exploitable."
          />
        )}
        {courses.map((course, index) => (
          <GeneratedCourseAudit key={course.number || index} course={course} initiallyOpen={index === 0} />
        ))}
      </div>
    </details>
  )
}

function GeneratedCourseAudit({ course, initiallyOpen }) {
  const coursePlan = course.plan || course.draft?.course_plan || {}
  const draft = course.draft || {}
  const title = coursePlan.course_title || draft.course_title || `Thème ${course.number}`
  const targetWords = Number(coursePlan.target_words || draft.target_words || 0)
  const actualWords = Number(draft.draft_word_count || draft.word_count || 0)
  const sectionRows = buildGeneratedSectionRows(coursePlan, draft)
  const slidesCount = sectionRows.reduce((sum, row) => sum + row.slideBeats.length, 0)

  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(2,6,23,0.34)',
      border: '1px solid rgba(148,163,184,0.12)',
      borderRadius: '10px',
      overflow: 'hidden',
    }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '13px 14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Thème {course.number} · {courseKindLabel(coursePlan.course_kind)}
            </div>
            <div style={{ color: '#e2e8f0', fontWeight: 900, fontSize: '15px', marginTop: '3px' }}>
              {title}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
            <WordBudgetBadge target={targetWords} actual={actualWords} />
            <SmallMetric label="Sections" value={sectionRows.length} />
            <SmallMetric label="Slides" value={slidesCount} />
          </div>
        </div>
      </summary>
      <div style={{ borderTop: '1px solid rgba(148,163,184,0.10)', padding: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {sectionRows.map((row, index) => (
          <GeneratedSectionAudit key={`${row.kind}-${row.partNumber || index}`} row={row} />
        ))}
      </div>
    </details>
  )
}

function GeneratedSectionAudit({ row }) {
  const text = row.actual?.text || ''
  const targetWords = Number(row.plan?.target_words || row.actual?.target_words || 0)
  const actualWords = Number(row.actual?.word_count || countAuditWords(text))
  const mustInclude = Array.isArray(row.plan?.must_include) ? row.plan.must_include : []
  const mustAvoid = Array.isArray(row.plan?.must_avoid) ? row.plan.must_avoid : []

  return (
    <div style={{
      border: '1px solid rgba(148,163,184,0.12)',
      borderRadius: '10px',
      background: 'rgba(15,23,42,0.50)',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '11px 12px',
        borderBottom: '1px solid rgba(148,163,184,0.10)',
        display: 'flex',
        justifyContent: 'space-between',
        gap: '10px',
        flexWrap: 'wrap',
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: sectionKindColor(row.kind), fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            {sectionKindLabel(row.kind, row.partNumber)}
          </div>
          <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '13px', marginTop: '2px' }}>
            {row.title}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          <WordBudgetBadge target={targetWords} actual={actualWords} compact />
          <SmallMetric label="À couvrir" value={mustInclude.length} />
          <SmallMetric label="À éviter" value={mustAvoid.length} />
          <SmallMetric label="Slides" value={row.slideBeats.length} />
        </div>
      </div>

      <div style={{ padding: '12px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 900, marginBottom: '7px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Texte généré pour cette section
          </div>
          <div style={{
            color: '#cbd5e1',
            fontSize: '12px',
            lineHeight: 1.65,
            whiteSpace: 'pre-wrap',
            background: 'rgba(2,6,23,0.46)',
            border: '1px solid rgba(148,163,184,0.10)',
            borderRadius: '8px',
            padding: '11px',
            maxHeight: '310px',
            overflow: 'auto',
          }}>
            {text || 'Aucun texte généré trouvé pour cette section.'}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', minWidth: 0 }}>
          <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Slides prévues dans cette section
          </div>
          {row.slideBeats.length === 0 ? (
            <div style={{
              padding: '12px',
              color: '#64748b',
              fontSize: '12px',
              background: 'rgba(2,6,23,0.32)',
              border: '1px dashed rgba(148,163,184,0.14)',
              borderRadius: '8px',
            }}>
              Aucune slide prévue ici. La section reste uniquement orale.
            </div>
          ) : row.slideBeats.map((beat, index) => (
            <SlideAnchorAuditCard
              key={beat.beat_id || index}
              beat={beat}
              sectionText={text}
              sectionTargetWords={targetWords}
              slideIndex={index}
              slidesCount={row.slideBeats.length}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function SlideAnchorAuditCard({ beat, sectionText, sectionTargetWords, slideIndex, slidesCount }) {
  const anchor = beat.slide_anchor || {}
  const excerpt = extractBeatExcerpt(sectionText, beat, slideIndex, slidesCount)
  const explicitTarget = Number(anchor.target_words || beat.target_words || 0)
  const plannedWords = explicitTarget || estimateSlideAnchorWords(sectionTargetWords, slidesCount)
  const actualWords = countAuditWords(excerpt)
  const fields = anchor.fields_hint || {}

  return (
    <div style={{
      background: 'rgba(30,41,59,0.44)',
      border: '1px solid rgba(96,165,250,0.18)',
      borderRadius: '9px',
      padding: '10px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#93c5fd', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Slide {slideIndex + 1} · {anchor.template_type || beat.type || 'template'}
          </div>
          <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '12px', marginTop: '3px', lineHeight: 1.35 }}>
            {beat.role || anchor.visual_goal || 'Moment pédagogique prévu'}
          </div>
        </div>
        <div style={{ flexShrink: 0, textAlign: 'right' }}>
          <div style={{ color: '#bfdbfe', fontSize: '11px', fontWeight: 900 }}>
            {explicitTarget ? '' : '≈ '}{formatAuditNumber(plannedWords)} prévus
          </div>
          <div style={{ color: '#94a3b8', fontSize: '11px', marginTop: '2px' }}>
            ≈ {formatAuditNumber(actualWords)} générés
          </div>
        </div>
      </div>

      {anchor.visual_goal && (
        <div style={{ color: '#94a3b8', fontSize: '11px', lineHeight: 1.45, marginTop: '7px' }}>
          {anchor.visual_goal}
        </div>
      )}

      <SlideFieldsPreview fields={fields} />

      <details style={{ marginTop: '8px' }}>
        <summary style={{ cursor: 'pointer', color: '#c4b5fd', fontSize: '11px', fontWeight: 800 }}>
          Voir le passage associé
        </summary>
        <div style={{
          marginTop: '7px',
          color: '#cbd5e1',
          fontSize: '11px',
          lineHeight: 1.55,
          whiteSpace: 'pre-wrap',
          background: 'rgba(2,6,23,0.36)',
          border: '1px solid rgba(148,163,184,0.10)',
          borderRadius: '7px',
          padding: '8px',
          maxHeight: '160px',
          overflow: 'auto',
        }}>
          {excerpt || 'Passage non localisable dans le texte existant.'}
        </div>
      </details>
    </div>
  )
}

function SlideFieldsPreview({ fields }) {
  const items = Array.isArray(fields?.items) ? fields.items : []
  if (!fields?.text && items.length === 0) return null
  return (
    <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '5px' }}>
      {fields.text && (
        <div style={{ color: '#dbeafe', fontSize: '11px', lineHeight: 1.45, padding: '7px 8px', background: 'rgba(59,130,246,0.10)', borderRadius: '7px' }}>
          {fields.text}
        </div>
      )}
      {items.length > 0 && (
        <div style={{ display: 'grid', gap: '5px' }}>
          {items.slice(0, 6).map((item, index) => (
            <div key={index} style={{ color: '#cbd5e1', fontSize: '11px', lineHeight: 1.35, padding: '6px 7px', background: 'rgba(15,23,42,0.50)', borderRadius: '7px' }}>
              <strong style={{ color: '#bfdbfe' }}>{item.title || `Élément ${index + 1}`}</strong>
              {item.description ? ` — ${item.description}` : ''}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function plannedSectionsForCourse(coursePlan = {}) {
  const sections = []
  if (coursePlan.opening) {
    sections.push({ kind: 'opening', partNumber: null, title: 'Introduction', plan: { kind: 'opening', ...coursePlan.opening } })
  }
  for (const part of coursePlan.parts || []) {
    sections.push({
      kind: 'part',
      partNumber: Number(part.part_number || sections.length),
      title: part.title || `Partie ${part.part_number || ''}`.trim(),
      plan: { kind: 'part', ...part },
    })
  }
  if (coursePlan.course_conclusion) {
    sections.push({ kind: 'course_conclusion', partNumber: null, title: 'Conclusion et passage Q/R', plan: { kind: 'course_conclusion', ...coursePlan.course_conclusion } })
  }
  if (coursePlan.day_conclusion) {
    sections.push({ kind: 'day_conclusion', partNumber: null, title: 'Conclusion globale de la journée', plan: { kind: 'day_conclusion', ...coursePlan.day_conclusion } })
  }
  return sections
}

function buildGeneratedSectionRows(coursePlan = {}, draft = {}) {
  const plannedSections = plannedSectionsForCourse(coursePlan)
  const actualSections = Array.isArray(draft.sections) ? draft.sections : []
  if (plannedSections.length === 0) {
    return actualSections.map(section => ({
      kind: section.kind || 'section',
      partNumber: section.part_number,
      title: section.title || section.label || sectionKindLabel(section.kind, section.part_number),
      plan: section,
      actual: section,
      slideBeats: slideBeatsForSection(section),
    }))
  }
  return plannedSections.map(planned => {
    const actual = matchGeneratedSection(actualSections, planned)
    return {
      kind: planned.kind,
      partNumber: planned.partNumber,
      title: planned.title || actual?.title || actual?.label || sectionKindLabel(planned.kind, planned.partNumber),
      plan: planned.plan,
      actual: actual || {},
      slideBeats: slideBeatsForSection(planned.plan),
    }
  })
}

function matchGeneratedSection(actualSections, planned) {
  return actualSections.find(section =>
    section.kind === planned.kind &&
    (planned.kind !== 'part' || Number(section.part_number || 0) === Number(planned.partNumber || 0))
  ) || actualSections.find(section => String(section.label || '').toLowerCase() === sectionKindLabel(planned.kind, planned.partNumber).toLowerCase())
}

function slideBeatsForSection(section = {}) {
  return (Array.isArray(section.teaching_beats) ? section.teaching_beats : [])
    .filter(beat => beat?.slide_anchor?.enabled)
}

function SmallMetric({ label, value }) {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '4px',
      padding: '4px 7px',
      borderRadius: '999px',
      background: 'rgba(148,163,184,0.10)',
      color: '#cbd5e1',
      fontSize: '11px',
      fontWeight: 800,
      whiteSpace: 'nowrap',
    }}>
      <span style={{ color: '#94a3b8', fontWeight: 700 }}>{label}</span>
      {value}
    </span>
  )
}

function WordBudgetBadge({ target, actual, compact = false }) {
  const delta = Number(actual || 0) - Number(target || 0)
  const ratio = target ? Math.abs(delta) / target : 0
  const color = ratio <= 0.15 ? '#34d399' : ratio <= 0.30 ? '#fbbf24' : '#fb7185'
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '6px',
      padding: compact ? '4px 7px' : '6px 9px',
      borderRadius: '999px',
      background: `${color}18`,
      border: `1px solid ${color}45`,
      color,
      fontSize: '11px',
      fontWeight: 900,
      whiteSpace: 'nowrap',
    }}>
      {formatAuditNumber(actual || 0)} / {formatAuditNumber(target || 0)} mots
      {target ? <span style={{ color: '#94a3b8', fontWeight: 800 }}>{delta >= 0 ? '+' : ''}{formatAuditNumber(delta)}</span> : null}
    </span>
  )
}

function courseKindLabel(kind) {
  const labels = {
    opening_year_day: 'ouverture journée',
    standard_reprise: 'reprise',
    end_of_day: 'fin de journée',
  }
  return labels[kind] || kind || 'thème'
}

function sectionKindLabel(kind, partNumber) {
  if (kind === 'opening') return 'Introduction'
  if (kind === 'course_conclusion') return 'Conclusion / Q-R'
  if (kind === 'day_conclusion') return 'Conclusion journée'
  if (kind === 'part') return `Chapitre ${partNumber || ''}`.trim()
  return 'Section'
}

function sectionKindColor(kind) {
  if (kind === 'opening') return '#a78bfa'
  if (kind === 'course_conclusion' || kind === 'day_conclusion') return '#fbbf24'
  return '#38bdf8'
}

function estimateSlideAnchorWords(sectionTargetWords, slidesCount) {
  if (!sectionTargetWords) return 0
  const count = Math.max(1, Number(slidesCount || 1))
  return Math.max(80, Math.min(360, Math.round((Number(sectionTargetWords) * 0.35) / count)))
}

function extractBeatExcerpt(sectionText, beat, slideIndex, slidesCount) {
  const text = String(sectionText || '').trim()
  if (!text) return ''
  const paragraphs = text.split(/\n{2,}/).map(p => p.trim()).filter(Boolean)
  if (paragraphs.length === 0) return compactAuditWords(text, 120)
  const terms = beatSearchTerms(beat)
  const scored = paragraphs.map((paragraph, index) => ({
    paragraph,
    index,
    score: scoreParagraphForTerms(paragraph, terms),
  })).sort((a, b) => b.score - a.score)
  if (scored[0]?.score > 0) {
    const best = scored[0]
    const merged = [
      paragraphs[Math.max(0, best.index - 1)],
      best.paragraph,
      paragraphs[Math.min(paragraphs.length - 1, best.index + 1)],
    ].filter(Boolean)
    return compactAuditWords(Array.from(new Set(merged)).join('\n\n'), 145)
  }
  return sliceAuditWords(text, slideIndex, slidesCount, 135)
}

function beatSearchTerms(beat = {}) {
  const anchor = beat.slide_anchor || {}
  const fields = anchor.fields_hint || {}
  const chunks = [
    beat.role,
    beat.spoken_requirement,
    anchor.visual_goal,
    fields.text,
    ...(Array.isArray(fields.items) ? fields.items.flatMap(item => [item.title, item.description]) : []),
  ]
  const stop = new Set(['avec', 'dans', 'pour', 'plus', 'vous', 'nous', 'cette', 'section', 'client', 'clients', 'faire', 'montrer', 'afficher', 'présenter'])
  return Array.from(new Set(
    chunks.join(' ')
      .toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .split(/[^a-z0-9]+/)
      .filter(word => word.length >= 5 && !stop.has(word)),
  )).slice(0, 18)
}

function scoreParagraphForTerms(paragraph, terms) {
  const normalized = String(paragraph || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  return (terms || []).reduce((score, term) => score + (normalized.includes(term) ? 1 : 0), 0)
}

function countAuditWords(text) {
  return String(text || '').trim().split(/[^\p{L}\p{N}'’-]+/u).filter(Boolean).length
}

function compactAuditWords(text, limit) {
  const words = String(text || '').trim().split(/\s+/).filter(Boolean)
  if (words.length <= limit) return words.join(' ')
  return `${words.slice(0, limit).join(' ')}…`
}

function sliceAuditWords(text, index, total, limit) {
  const words = String(text || '').trim().split(/\s+/).filter(Boolean)
  if (words.length <= limit) return words.join(' ')
  const count = Math.max(1, Number(total || 1))
  const sliceSize = Math.max(limit, Math.ceil(words.length / count))
  const start = Math.min(words.length - limit, Math.max(0, Number(index || 0) * sliceSize))
  return compactAuditWords(words.slice(start, start + sliceSize).join(' '), limit)
}

function formatAuditNumber(value) {
  return Number(value || 0).toLocaleString('fr-FR')
}

function PlanAdherenceAuditView({ artifacts }) {
  const days = buildPlanAdherenceDays(artifacts)
  const hasReview = days.some(day => day.review)

  if (!hasReview) {
    return (
      <AuditEmptyState
        icon="info"
        title="Aucun audit d'adhérence au plan disponible"
        detail="Cette étape écrit content-quality-reviews.json après la génération par section. Relance une génération texte pour obtenir l'audit lisible cours par cours."
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{
        padding: '12px 14px',
        background: 'rgba(167,139,250,0.08)',
        border: '1px solid rgba(167,139,250,0.24)',
        borderRadius: '10px',
        color: '#ddd6fe',
        fontSize: '12px',
        lineHeight: 1.5,
      }}>
        <strong>Lecture de l'étape 9.</strong> Cette vue vérifie que le texte suit le plan JSON avant le budget : intro au bon endroit, ordre des chapitres, teaching beats couverts, pas de double introduction, pas de fuite d'horaires et conclusion qui ferme vraiment avant le Q/R.
      </div>
      {days.map((day, index) => (
        <PlanAdherenceDay key={day.folder?.folder_id || index} day={day} initiallyOpen={index === 0} />
      ))}
    </div>
  )
}

function buildPlanAdherenceDays(artifacts) {
  const byFolder = new Map()
  for (const item of artifacts || []) {
    const folderId = item.folder?.folder_id || item.folder_id || 'unknown'
    if (!byFolder.has(folderId)) {
      byFolder.set(folderId, { folder: item.folder || {}, review: null, draft: null })
    }
    const entry = byFolder.get(folderId)
    if (!item.ok || !item.artifact) continue
    if (item.name === 'content-quality-reviews.json') entry.review = item.artifact
    if (item.name === 'content-draft-sections.json') entry.draft = item.artifact
  }
  return Array.from(byFolder.values()).sort((a, b) =>
    Number(a.folder?.position ?? a.folder?.folder_position ?? a.folder?.folder_id ?? 0) -
    Number(b.folder?.position ?? b.folder?.folder_position ?? b.folder?.folder_id ?? 0),
  )
}

function PlanAdherenceDay({ day, initiallyOpen }) {
  const courses = planAdherenceCoursesForDay(day)
  const summary = day.review?.review_summary || {}
  const changed = courses.filter(course => course.changed).length
  const failed = courses.filter(course => course.failed).length
  const issues = courses.reduce((sum, course) => sum + planAdherenceIssues(course).length, 0)
  const legacy = courses.filter(course => course.legacy).length
  const timing = day.review?.review_timing || summary.review_timing || ''

  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(15,23,42,0.48)',
      border: '1px solid rgba(148,163,184,0.14)',
      borderRadius: '12px',
      overflow: 'hidden',
    }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '14px 16px', borderBottom: '1px solid rgba(148,163,184,0.12)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: '#e2e8f0', fontWeight: 900 }}>
            <Icon name="rule" /> {folderDisplayName(day.folder)}
          </span>
          <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <SmallMetric label="Thèmes audités" value={courses.length} />
            <SmallMetric label="Corrections" value={changed} />
            <SmallMetric label="Problèmes" value={issues} />
            <SmallMetric label="Échecs" value={failed} />
          </span>
        </div>
      </summary>
      <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <PlanAdherenceScopeCard timing={timing} legacyCount={legacy} />
        {courses.length === 0 && (
          <AuditEmptyState
            icon="info"
            title="Aucun cours exploitable"
            detail="L'artefact existe, mais il ne contient pas de liste de cours exploitable."
          />
        )}
        {courses.map((course, index) => (
          <PlanAdherenceCourse key={course.course_number || index} course={course} initiallyOpen={index === 0} />
        ))}
      </div>
    </details>
  )
}

function planAdherenceCoursesForDay(day) {
  const reviewCourses = Array.isArray(day.review?.courses) ? day.review.courses : []
  const draftCourses = Array.isArray(day.draft?.courses) ? day.draft.courses : []
  const numbers = Array.from(new Set([
    ...reviewCourses.map(course => Number(course.course_number || 0)).filter(Boolean),
    ...draftCourses.map(course => Number(course.course_number || 0)).filter(Boolean),
  ])).sort((a, b) => a - b)
  return numbers.map(number => {
    const review = reviewCourses.find(course => Number(course.course_number || 0) === number) || {}
    const draft = draftCourses.find(course => Number(course.course_number || 0) === number) || {}
    const draftText = draftCourseText(draft)
    const beforeText = review.before_text || review.initial_text || draftText
    const afterText = review.after_text || review.final_text || beforeText
    const finalAudit = review.final_audit || {}
    const issues = Array.isArray(finalAudit.issues) ? finalAudit.issues : []
    const hasDetailedAudit = Boolean(review.final_audit || review.before_text || review.after_text || review.attempts)
    return {
      ...review,
      course_number: number,
      course_title: review.course_title || draft.course_title || `Thème ${number}`,
      initial_words: review.initial_words ?? draft.draft_word_count ?? countAuditWords(beforeText),
      final_words: review.final_words ?? countAuditWords(afterText),
      changed: Boolean(review.changed),
      failed: Boolean(review.failed),
      before_text: beforeText,
      after_text: afterText,
      final_audit: finalAudit,
      issues_count: review.issues_count ?? issues.length,
      legacy: !hasDetailedAudit,
    }
  })
}

function draftCourseText(draft = {}) {
  if (draft.course_text) return draft.course_text
  if (draft.text) return draft.text
  if (Array.isArray(draft.sections)) {
    return draft.sections.map(section => section.text || '').filter(Boolean).join('\n\n')
  }
  return ''
}

function PlanAdherenceScopeCard({ timing, legacyCount }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
      gap: '8px',
    }}>
      <PlanCheckItem label="Ordre du plan" detail="Les chapitres restent dans l'ordre prévu." />
      <PlanCheckItem label="Intro et reprises" detail="Pas de double intro, pas de reprise incohérente." />
      <PlanCheckItem label="Conclusions" detail="Le texte ferme avant Q/R, sans nouveau développement." />
      <PlanCheckItem label="Fuites internes" detail="Pas d'horaires, créneaux, planning ou mot cours mal placé." />
      {timing && (
        <PlanCheckItem label="Moment pipeline" detail={timing === 'after_section_generation_before_budget_calibration' ? 'Exécuté juste après génération, avant budget.' : timing} />
      )}
      {legacyCount > 0 && (
        <PlanCheckItem label="Ancien artefact" detail={`${legacyCount} thème(s) sans détail avant/après. Relancer la génération pour l'audit complet.`} warning />
      )}
    </div>
  )
}

function PlanCheckItem({ label, detail, warning = false }) {
  return (
    <div style={{
      padding: '10px 11px',
      background: warning ? 'rgba(251,191,36,0.08)' : 'rgba(2,6,23,0.34)',
      border: `1px solid ${warning ? 'rgba(251,191,36,0.22)' : 'rgba(148,163,184,0.12)'}`,
      borderRadius: '9px',
    }}>
      <div style={{ color: warning ? '#fde68a' : '#c4b5fd', fontWeight: 900, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </div>
      <div style={{ color: '#cbd5e1', fontSize: '12px', lineHeight: 1.45, marginTop: '4px' }}>
        {detail}
      </div>
    </div>
  )
}

function PlanAdherenceCourse({ course, initiallyOpen }) {
  const issues = planAdherenceIssues(course)
  const beforeWords = Number(course.initial_words || countAuditWords(course.before_text))
  const afterWords = Number(course.final_words || countAuditWords(course.after_text))
  const status = planAdherenceStatus(course, issues)

  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(2,6,23,0.34)',
      border: `1px solid ${status.border}`,
      borderRadius: '10px',
      overflow: 'hidden',
    }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '13px 14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: status.color, fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Thème {course.course_number} · {status.label}
            </div>
            <div style={{ color: '#e2e8f0', fontWeight: 900, fontSize: '15px', marginTop: '3px' }}>
              {course.course_title || `Thème ${course.course_number}`}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
            <SmallMetric label="Avant" value={`${formatAuditNumber(beforeWords)} mots`} />
            <SmallMetric label="Après" value={`${formatAuditNumber(afterWords)} mots`} />
            <SmallMetric label="Écart" value={`${afterWords - beforeWords >= 0 ? '+' : ''}${formatAuditNumber(afterWords - beforeWords)}`} />
            <SmallMetric label="Issues" value={issues.length} />
          </div>
        </div>
      </summary>
      <div style={{ borderTop: '1px solid rgba(148,163,184,0.10)', padding: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {course.legacy ? (
          <AuditEmptyState
            icon="info"
            title="Audit détaillé non disponible pour ce thème"
            detail="Cet artefact ancien ne contient que le titre du thème. Les prochaines générations stockeront le diagnostic, les problèmes détectés et le texte avant/après correction."
          />
        ) : (
          <>
            <PlanAdherenceIssueList issues={issues} ok={Boolean(course.final_audit?.ok)} summary={course.final_audit?.summary} error={course.error} />
            <PlanAdherenceBeforeAfter course={course} issues={issues} />
          </>
        )}
      </div>
    </details>
  )
}

function planAdherenceIssues(course) {
  const finalIssues = Array.isArray(course.final_audit?.issues) ? course.final_audit.issues : []
  const attemptIssues = Array.isArray(course.attempts?.[0]?.audit?.issues) ? course.attempts[0].audit.issues : []
  return finalIssues.length > 0 ? finalIssues : attemptIssues
}

function planAdherenceStatus(course, issues) {
  if (course.failed) return { label: 'échec', color: '#f87171', border: 'rgba(248,113,113,0.28)' }
  if (course.legacy) return { label: 'ancien artefact', color: '#fbbf24', border: 'rgba(251,191,36,0.24)' }
  if (course.changed) return { label: 'corrigé', color: '#60a5fa', border: 'rgba(96,165,250,0.28)' }
  if (issues.length > 0 || course.final_audit?.ok === false) return { label: 'à vérifier', color: '#fb923c', border: 'rgba(251,146,60,0.28)' }
  return { label: 'ok', color: '#34d399', border: 'rgba(52,211,153,0.24)' }
}

function PlanAdherenceIssueList({ issues, ok, summary, error }) {
  if (error) {
    return <AuditEmptyState icon="error" title="Audit en erreur" detail={error} />
  }
  if (!issues.length) {
    return (
      <AuditEmptyState
        icon={ok ? 'verified_user' : 'info'}
        title={ok ? 'Plan respecté' : 'Aucun problème détaillé enregistré'}
        detail={summary || 'L’audit n’a pas remonté de problème de structure pédagogique.'}
      />
    )
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '8px' }}>
      {issues.map((issue, index) => (
        <div key={index} style={{
          padding: '10px 11px',
          background: issue.severity === 'critical' ? 'rgba(239,68,68,0.09)' : 'rgba(251,146,60,0.08)',
          border: `1px solid ${issue.severity === 'critical' ? 'rgba(239,68,68,0.24)' : 'rgba(251,146,60,0.22)'}`,
          borderRadius: '9px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '5px' }}>
            <span style={{ color: '#fed7aa', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase' }}>
              {issue.type || 'problème'}
            </span>
            <span style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 800 }}>
              {issue.section || 'section'}
            </span>
          </div>
          <div style={{ color: '#e2e8f0', fontSize: '12px', lineHeight: 1.45, fontWeight: 800 }}>
            {issue.problem || 'Problème signalé par l’audit.'}
          </div>
          {issue.evidence && (
            <div style={{ color: '#cbd5e1', fontSize: '12px', lineHeight: 1.45, marginTop: '7px', fontStyle: 'italic' }}>
              “{issue.evidence}”
            </div>
          )}
          {issue.fix_instruction && (
            <div style={{ color: '#bfdbfe', fontSize: '12px', lineHeight: 1.45, marginTop: '7px' }}>
              Correction attendue : {issue.fix_instruction}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function PlanAdherenceBeforeAfter({ course, issues }) {
  const beforeText = course.before_text || ''
  const afterText = course.after_text || ''
  if (!beforeText && !afterText) {
    return (
      <AuditEmptyState
        icon="visibility_off"
        title="Texte avant/après indisponible"
        detail="L'audit existe, mais l'artefact ne contient pas le texte comparatif."
      />
    )
  }
  const evidenceHighlights = issues.map(issue => issue.evidence).filter(Boolean)
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '12px' }}>
      <PlanTextPane
        title="Avant audit"
        color="#ef4444"
        text={beforeText}
        highlights={evidenceHighlights}
      />
      <PlanTextPane
        title={course.changed ? 'Après correction' : 'Texte conservé'}
        color="#3b82f6"
        text={afterText || beforeText}
        compareText={beforeText}
        highlightChanged={course.changed}
      />
    </div>
  )
}

function PlanTextPane({ title, color, text, highlights = [], compareText = '', highlightChanged = false }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ color, fontSize: '11px', fontWeight: 900, marginBottom: '7px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {title}
      </div>
      <div style={{
        color: '#cbd5e1',
        fontSize: '12px',
        lineHeight: 1.65,
        whiteSpace: 'pre-wrap',
        background: 'rgba(2,6,23,0.46)',
        border: '1px solid rgba(148,163,184,0.10)',
        borderRadius: '8px',
        padding: '11px',
        maxHeight: '360px',
        overflow: 'auto',
      }}>
        {highlightChanged
          ? <HighlightedChangedParagraphs beforeText={compareText} afterText={text} color={color} />
          : <HighlightedText text={text || 'Aucun texte disponible.'} highlights={highlights} color={color} />}
      </div>
    </div>
  )
}

function HighlightedChangedParagraphs({ beforeText, afterText, color }) {
  const after = String(afterText || '')
  if (!after.trim()) return 'Aucun texte disponible.'
  const beforeKeys = new Set(splitAuditParagraphs(beforeText).map(paragraph => normalizeAuditText(paragraph)))
  const paragraphs = splitAuditParagraphs(after)
  if (paragraphs.length === 0) return after
  return (
    <>
      {paragraphs.map((paragraph, index) => {
        const changed = !beforeKeys.has(normalizeAuditText(paragraph))
        return (
          <span key={index}>
            {changed ? (
              <mark style={{
                color: '#f8fafc',
                background: color === '#3b82f6' ? 'rgba(59,130,246,0.38)' : 'rgba(239,68,68,0.38)',
                borderRadius: '4px',
                padding: '1px 3px',
              }}>
                {paragraph}
              </mark>
            ) : paragraph}
            {index < paragraphs.length - 1 ? '\n\n' : ''}
          </span>
        )
      })}
    </>
  )
}

function BudgetCalibrationAuditView({ artifacts }) {
  const days = buildBudgetCalibrationDays(artifacts)
  const hasData = days.some(day => day.records.length > 0)

  if (!hasData) {
    return (
      <AuditEmptyState
        icon="info"
        title="Aucun artefact de calibrage budget disponible"
        detail="Les nouvelles générations écrivent content-budget-calibration.json. Pour les anciens jobs, cette vue utilise les scripts calibrés si disponibles."
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{
        padding: '12px 14px',
        background: 'rgba(250,204,21,0.08)',
        border: '1px solid rgba(250,204,21,0.24)',
        borderRadius: '10px',
        color: '#fde68a',
        fontSize: '12px',
        lineHeight: 1.5,
      }}>
        <strong>Lecture de l'étape 11.</strong> Cette vue compare le texte avant calibrage et le texte après calibrage. Les passages surlignés en jaune correspondent aux paragraphes ajoutés ou fortement modifiés pour se rapprocher du budget prévu.
      </div>
      {days.map((day, index) => (
        <BudgetCalibrationDay key={day.folder?.folder_id || index} day={day} initiallyOpen={index === 0} />
      ))}
    </div>
  )
}

function buildBudgetCalibrationDays(artifacts) {
  const byFolder = new Map()
  for (const item of artifacts || []) {
    const folderId = item.folder?.folder_id || item.folder_id || 'unknown'
    if (!byFolder.has(folderId)) {
      byFolder.set(folderId, { folder: item.folder || {}, calibration: null, draft: null, scripts: null })
    }
    const entry = byFolder.get(folderId)
    if (!item.ok || !item.artifact) continue
    if (item.name === 'content-budget-calibration.json') entry.calibration = item.artifact
    if (item.name === 'content-draft-sections.json') entry.draft = item.artifact
    if (item.name === 'content-course-scripts.json') entry.scripts = item.artifact
  }
  return Array.from(byFolder.values()).map(day => ({
    ...day,
    records: budgetCalibrationRecordsForDay(day),
  })).sort((a, b) =>
    Number(a.folder?.position ?? a.folder?.folder_position ?? a.folder?.folder_id ?? 0) -
    Number(b.folder?.position ?? b.folder?.folder_position ?? b.folder?.folder_id ?? 0),
  )
}

function budgetCalibrationRecordsForDay(day) {
  if (Array.isArray(day.calibration?.courses) && day.calibration.courses.length > 0) {
    return day.calibration.courses
  }
  const drafts = Array.isArray(day.draft?.courses) ? day.draft.courses : []
  const scripts = Array.isArray(day.scripts?.courses) ? day.scripts.courses : []
  const numbers = Array.from(new Set([
    ...drafts.map(course => Number(course.course_number || 0)).filter(Boolean),
    ...scripts.map(course => Number(course.course_number || 0)).filter(Boolean),
  ])).sort((a, b) => a - b)
  return numbers.map(number => {
    const draft = drafts.find(course => Number(course.course_number || 0) === number) || {}
    const script = scripts.find(course => Number(course.course_number || 0) === number) || {}
    const beforeText = Array.isArray(draft.sections)
      ? draft.sections.map(section => section.text || '').filter(Boolean).join('\n\n')
      : ''
    const afterText = script.text || ''
    return {
      course_number: number,
      course_title: script.course_title || draft.course_title || `Thème ${number}`,
      target_words: script.target_words || draft.target_words || 0,
      before_words: draft.draft_word_count || countAuditWords(beforeText),
      after_words: script.word_count || countAuditWords(afterText),
      delta_words: (script.word_count || countAuditWords(afterText)) - (draft.draft_word_count || countAuditWords(beforeText)),
      changed: beforeText.trim() !== afterText.trim(),
      calibration: script.calibration || {},
      before_text: beforeText,
      after_text: afterText,
      sections: draft.sections || [],
      structured_plan: script.structured_plan || draft.course_plan || {},
    }
  })
}

function BudgetCalibrationDay({ day, initiallyOpen }) {
  const target = day.records.reduce((sum, record) => sum + Number(record.target_words || 0), 0)
  const before = day.records.reduce((sum, record) => sum + Number(record.before_words || 0), 0)
  const after = day.records.reduce((sum, record) => sum + Number(record.after_words || 0), 0)
  const changed = day.records.filter(record => record.changed).length

  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(15,23,42,0.48)',
      border: '1px solid rgba(148,163,184,0.14)',
      borderRadius: '12px',
      overflow: 'hidden',
    }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '14px 16px', borderBottom: '1px solid rgba(148,163,184,0.12)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: '#e2e8f0', fontWeight: 900 }}>
            <Icon name="speed" /> {folderDisplayName(day.folder)}
          </span>
          <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <SmallMetric label="Avant" value={`${formatAuditNumber(before)} mots`} />
            <SmallMetric label="Après" value={`${formatAuditNumber(after)} mots`} />
            <SmallMetric label="Cible" value={`${formatAuditNumber(target)} mots`} />
            <SmallMetric label="Modifiés" value={changed} />
          </span>
        </div>
      </summary>
      <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {day.records.map((record, index) => (
          <BudgetCalibrationCourse key={record.course_number || index} record={record} initiallyOpen={index === 0} />
        ))}
      </div>
    </details>
  )
}

function BudgetCalibrationCourse({ record, initiallyOpen }) {
  const before = Number(record.before_words || countAuditWords(record.before_text))
  const after = Number(record.after_words || countAuditWords(record.after_text))
  const target = Number(record.target_words || 0)
  const delta = after - before
  const status = record.calibration?.status || (target && after >= target * 0.94 && after <= target ? 'ok' : 'à vérifier')

  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(2,6,23,0.34)',
      border: '1px solid rgba(148,163,184,0.12)',
      borderRadius: '10px',
      overflow: 'hidden',
    }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '13px 14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Thème {record.course_number} · {status}
            </div>
            <div style={{ color: '#e2e8f0', fontWeight: 900, fontSize: '15px', marginTop: '3px' }}>
              {record.course_title || `Thème ${record.course_number}`}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
            <WordBudgetBadge target={target} actual={after} />
            <SmallMetric label="Avant" value={formatAuditNumber(before)} />
            <SmallMetric label="Delta" value={`${delta >= 0 ? '+' : ''}${formatAuditNumber(delta)}`} />
          </div>
        </div>
      </summary>
      <div style={{ borderTop: '1px solid rgba(148,163,184,0.10)', padding: '12px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '12px' }}>
        <CalibrationTextPane title="Avant calibrage" text={record.before_text} muted />
        <CalibrationTextPane title="Après calibrage" text={record.after_text} beforeText={record.before_text} highlight />
      </div>
    </details>
  )
}

function CalibrationTextPane({ title, text, beforeText = '', highlight = false, muted = false }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ color: muted ? '#94a3b8' : '#fde68a', fontSize: '11px', fontWeight: 900, marginBottom: '7px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {title}
      </div>
      <div style={{
        color: '#cbd5e1',
        fontSize: '12px',
        lineHeight: 1.65,
        whiteSpace: 'pre-wrap',
        background: 'rgba(2,6,23,0.46)',
        border: '1px solid rgba(148,163,184,0.10)',
        borderRadius: '8px',
        padding: '11px',
        maxHeight: '360px',
        overflow: 'auto',
      }}>
        {highlight ? <HighlightedAddedText beforeText={beforeText} afterText={text} /> : (text || 'Aucun texte disponible.')}
      </div>
    </div>
  )
}

function VolumeSafetyAuditView({ artifacts }) {
  const available = (artifacts || []).filter(item => item.ok && item.artifact)
  if (available.length === 0) {
    return (
      <AuditEmptyState
        icon="info"
        title="Aucun artefact de sécurité volume disponible"
        detail="La sécurité volume n'a pas encore tourné, ou ce job a été généré avant l'ajout de l'artefact content-volume-safety.json."
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{
        padding: '12px 14px',
        background: 'rgba(250,204,21,0.08)',
        border: '1px solid rgba(250,204,21,0.24)',
        borderRadius: '10px',
        color: '#fde68a',
        fontSize: '12px',
        lineHeight: 1.5,
      }}>
        <strong>Lecture de l'étape 12.</strong> Cette vue montre les ajouts effectués pour combler un déficit de volume journée. Le jaune correspond au contenu additionnel ajouté par sécurité volume.
      </div>
      {available.map((item, index) => (
        <VolumeSafetyDay key={`${item.folder?.folder_id}-${index}`} item={item} initiallyOpen={index === 0} />
      ))}
    </div>
  )
}

function VolumeSafetyDay({ item, initiallyOpen }) {
  const artifact = item.artifact || {}
  const before = artifact.audit_before || {}
  const after = artifact.audit_after || before
  const enriched = Array.isArray(artifact.enriched) ? artifact.enriched : []
  const failed = Array.isArray(artifact.failed) ? artifact.failed : []

  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(15,23,42,0.48)',
      border: '1px solid rgba(148,163,184,0.14)',
      borderRadius: '12px',
      overflow: 'hidden',
    }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '14px 16px', borderBottom: '1px solid rgba(148,163,184,0.12)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: '#e2e8f0', fontWeight: 900 }}>
            <Icon name="auto_fix_high" /> {folderDisplayName(item.folder)}
          </span>
          <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <SmallMetric label="Avant" value={`${formatAuditNumber(before.total_words)} mots`} />
            <SmallMetric label="Après" value={`${formatAuditNumber(after.total_words)} mots`} />
            <SmallMetric label="Déficit" value={formatAuditNumber(after.deficit || 0)} />
            <SmallMetric label="Ajouts" value={enriched.length} />
            <SmallMetric label="Échecs" value={failed.length} />
          </span>
        </div>
      </summary>
      <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {artifact.skipped && (
          <AuditEmptyState
            icon="verified_user"
            title="Sécurité volume non nécessaire"
            detail="La journée était déjà au-dessus du seuil minimal, aucun ajout n'a été effectué."
          />
        )}
        {enriched.length === 0 && !artifact.skipped && (
          <AuditEmptyState
            icon="info"
            title="Aucun ajout enregistré"
            detail="L'étape a tourné sans enrichissement exploitable, ou l'artefact ne contient pas encore les détails."
          />
        )}
        {enriched.map((entry, index) => (
          <VolumeSafetyAddition key={`${entry.segment_id}-${entry.pass_idx}-${index}`} entry={entry} />
        ))}
      </div>
    </details>
  )
}

function VolumeSafetyAddition({ entry }) {
  return (
    <div style={{
      background: 'rgba(2,6,23,0.34)',
      border: '1px solid rgba(250,204,21,0.18)',
      borderRadius: '10px',
      overflow: 'hidden',
    }}>
      <div style={{ padding: '12px 13px', borderBottom: '1px solid rgba(148,163,184,0.10)', display: 'flex', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ color: '#fde68a', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Segment {entry.segment_id} · passe {entry.pass_idx || entry.passe || '?'}
          </div>
          <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '13px', marginTop: '3px' }}>
            {entry.sub_part_name || 'Segment enrichi'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          <SmallMetric label="Avant" value={formatAuditNumber(entry.words_before)} />
          <SmallMetric label="Ajout" value={`+${formatAuditNumber(entry.words_added)}`} />
          <SmallMetric label="Après" value={formatAuditNumber(entry.words_after)} />
        </div>
      </div>
      <div style={{ padding: '12px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '12px' }}>
        <CalibrationTextPane title="Texte ajouté" text={entry.addition_text} beforeText="" highlight />
        <CalibrationTextPane title="Après ajout dans le segment" text={entry.text_after} beforeText={entry.text_before} highlight />
      </div>
    </div>
  )
}

function HighlightedAddedText({ beforeText, afterText }) {
  const after = String(afterText || '')
  if (!after.trim()) return 'Aucun texte disponible.'
  if (!String(beforeText || '').trim()) {
    return <mark style={addedHighlightStyle()}>{after}</mark>
  }
  const beforeParagraphKeys = new Set(
    splitAuditParagraphs(beforeText).map(paragraph => normalizeAuditText(paragraph)),
  )
  const paragraphs = splitAuditParagraphs(after)
  if (paragraphs.length === 0) return after
  return (
    <>
      {paragraphs.map((paragraph, index) => {
        const isAdded = !beforeParagraphKeys.has(normalizeAuditText(paragraph))
        return (
          <span key={index}>
            {isAdded ? <mark style={addedHighlightStyle()}>{paragraph}</mark> : paragraph}
            {index < paragraphs.length - 1 ? '\n\n' : ''}
          </span>
        )
      })}
    </>
  )
}

function splitAuditParagraphs(text) {
  return String(text || '').split(/\n{2,}/).map(paragraph => paragraph.trim()).filter(Boolean)
}

function normalizeAuditText(text) {
  return String(text || '')
    .toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function addedHighlightStyle() {
  return {
    color: '#fefce8',
    background: 'rgba(250,204,21,0.34)',
    borderRadius: '4px',
    padding: '1px 3px',
  }
}

function EthicalMicroAuditView({ artifacts }) {
  const available = (artifacts || []).filter(item => item.ok && item.artifact)
  const missing = (artifacts || []).filter(item => !item.ok)
  const records = available.flatMap(item =>
    (item.artifact.records || []).map(record => ({ ...record, folder: item.folder, generated_at: item.artifact.generated_at })),
  )
  const issueRecords = records.filter(record =>
    record.status !== 'clean' || (record.patches_detail || []).length > 0 || record.error,
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {missing.length > 0 && available.length === 0 && (
        <AuditEmptyState
          icon="info"
          title="Aucun rapport micro-éthique disponible pour cette génération"
          detail="Les prochaines générations écriront content-ethical-micro-review.json avec les passages problématiques et les corrections exactes."
        />
      )}
      {available.length > 0 && issueRecords.length === 0 && (
        <AuditEmptyState
          icon="verified_user"
          title="Aucune correction micro-éthique appliquée"
          detail={`${records.length} section(s) auditées sur les règles #1 à #16, sans patch appliqué.`}
        />
      )}
      {issueRecords.map((record, i) => (
        <div key={`${record.folder?.folder_id}-${record.course_number}-${record.section_label}-${i}`} style={{
          background: 'rgba(15,23,42,0.48)', border: '1px solid rgba(148,163,184,0.14)',
          borderRadius: '10px', overflow: 'hidden',
        }}>
          <div style={{ padding: '12px 14px', borderBottom: '1px solid rgba(148,163,184,0.12)' }}>
            <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '13px' }}>
              {folderDisplayName(record.folder)} · Cours {record.course_number} · {record.section_label}
            </div>
            <div style={{ color: '#94a3b8', fontSize: '12px', marginTop: '3px' }}>
              {record.status} · {record.patches_applied || 0} appliqué(s) · {record.patches_rejected || 0} rejeté(s)
              {record.error ? ` · ${record.error}` : ''}
            </div>
          </div>
          <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {(record.patches_detail || []).map((patch, patchIndex) => (
              <PatchBeforeAfter
                key={patchIndex}
                patch={patch}
                beforeText={record.original_text}
                afterText={record.final_text}
                leftTitle="Passage problématique"
                rightTitle={patch.status === 'applied' ? 'Correction appliquée' : 'Correction proposée'}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function ReviewReportsAuditView({ reports }) {
  const available = (reports || []).filter(item => item.ok && item.report)
  const patches = available.flatMap(item =>
    (item.report.by_segment || []).flatMap(segment =>
      (segment.patches_detail || []).map(patch => ({
        patch,
        folder: item.folder,
        segment,
        report: item.report,
      })),
    ),
  )

  if (available.length === 0) {
    return (
      <AuditEmptyState
        icon="info"
        title="Aucun rapport disponible"
        detail="Cette étape n'a pas encore produit de rapport lisible, ou elle n'a pas encore été exécutée."
      />
    )
  }

  if (patches.length === 0) {
    return (
      <AuditEmptyState
        icon="verified"
        title="Aucun patch dans les rapports chargés"
        detail={`${available.length} rapport(s) trouvé(s), sans correction détaillée.`}
      />
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      {patches.map((entry, i) => (
        <div key={i} style={{ background: 'rgba(15,23,42,0.48)', border: '1px solid rgba(148,163,184,0.14)', borderRadius: '10px', padding: '13px' }}>
          <div style={{ color: '#cbd5e1', fontWeight: 800, fontSize: '13px', marginBottom: '8px' }}>
            {folderDisplayName(entry.folder)} · Sous-partie {Number(entry.segment.sub_idx || 0) + 1} · Passe {entry.segment.passe}
          </div>
          <PatchBeforeAfter
            patch={entry.patch}
            beforeText={entry.patch.original}
            afterText={entry.patch.replacement}
            leftTitle="Avant"
            rightTitle="Après"
          />
        </div>
      ))}
    </div>
  )
}

function PatchBeforeAfter({ patch, beforeText, afterText, leftTitle, rightTitle }) {
  const leftTerm = patch.original || ''
  const rightTerm = patch.replacement || ''
  return (
    <div style={{ border: '1px solid rgba(148,163,184,0.12)', borderRadius: '8px', overflow: 'hidden' }}>
      <div style={{
        padding: '8px 10px', background: 'rgba(15,23,42,0.72)', display: 'flex',
        gap: '8px', alignItems: 'center', flexWrap: 'wrap', fontSize: '11px',
      }}>
        <span style={{ color: '#a78bfa', fontWeight: 800 }}>{patch.rule || '?'}</span>
        <span style={{ color: patch.status === 'applied' ? '#60a5fa' : '#fb923c', fontWeight: 800, textTransform: 'uppercase' }}>
          {patch.status === 'applied' ? 'appliqué' : (patch.reject_reason || 'rejeté')}
        </span>
        {patch.reason && <span style={{ color: '#94a3b8' }}>{patch.reason}</span>}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
        <DiffPane title={leftTitle} color="#ef4444" text={beforeText || leftTerm} highlights={[leftTerm]} />
        <DiffPane title={rightTitle} color="#3b82f6" text={afterText || rightTerm} highlights={[rightTerm]} />
      </div>
    </div>
  )
}

function DiffPane({ title, color, text, highlights }) {
  return (
    <div style={{ padding: '12px', borderRight: '1px solid rgba(148,163,184,0.10)' }}>
      <div style={{ color, fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' }}>
        {title}
      </div>
      <div style={{
        color: '#cbd5e1', fontSize: '12px', lineHeight: 1.6, whiteSpace: 'pre-wrap',
        maxHeight: '260px', overflow: 'auto',
      }}>
        <HighlightedText text={text || '—'} highlights={highlights || []} color={color} />
      </div>
    </div>
  )
}

function HighlightedText({ text, highlights, color }) {
  let parts = [{ text: String(text || ''), hit: false }]
  for (const raw of (highlights || []).filter(Boolean)) {
    const term = String(raw)
    if (!term) continue
    parts = parts.flatMap(part => {
      if (part.hit || !part.text.includes(term)) return [part]
      const split = part.text.split(term)
      const next = []
      split.forEach((chunk, index) => {
        if (chunk) next.push({ text: chunk, hit: false })
        if (index < split.length - 1) next.push({ text: term, hit: true })
      })
      return next
    })
  }
  return (
    <>
      {parts.map((part, index) => part.hit ? (
        <mark key={index} style={{ color: '#f8fafc', background: color === '#3b82f6' ? 'rgba(59,130,246,0.55)' : 'rgba(239,68,68,0.55)', borderRadius: '3px', padding: '1px 2px' }}>
          {part.text}
        </mark>
      ) : (
        <span key={index}>{part.text}</span>
      ))}
    </>
  )
}

function PlanJsonAuditView({ artifacts }) {
  const days = buildPlanJsonDays(artifacts)
  if (days.length === 0) {
    return (
      <AuditEmptyState
        icon="schema"
        title="Aucun plan structuré lisible"
        detail="L'artefact content-plan.json n'est pas encore disponible, ou il ne contient pas de structured_course_plan exploitable."
      />
    )
  }

  const totals = days.reduce((acc, day) => {
    acc.courses += day.courses.length
    acc.words += day.courses.reduce((sum, course) => sum + Number(course.target_words || 0), 0)
    acc.sections += day.courses.reduce((sum, course) => sum + plannedSectionsForCourse(course).length, 0)
    acc.slides += day.courses.reduce((sum, course) =>
      sum + plannedSectionsForCourse(course).reduce((sectionSum, section) => sectionSum + slideBeatsForSection(section.plan).length, 0),
    0)
    return acc
  }, { courses: 0, words: 0, sections: 0, slides: 0 })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{
        padding: '12px 14px',
        background: 'rgba(139,92,246,0.08)',
        border: '1px solid rgba(139,92,246,0.24)',
        borderRadius: '10px',
        color: '#ddd6fe',
        fontSize: '12px',
        lineHeight: 1.5,
      }}>
        <strong>Lecture de l'étape 6.</strong> Cette vue transforme le plan JSON verrouillé en plan pédagogique lisible : journées, thèmes, budgets, chapitres, contraintes et anchors slides prévus.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
        <AuditStatCard label="Journées" value={days.length} color="#a78bfa" />
        <AuditStatCard label="Thèmes" value={totals.courses} color="#38bdf8" />
        <AuditStatCard label="Sections" value={totals.sections} color="#34d399" />
        <AuditStatCard label="Slides prévues" value={totals.slides} color="#f59e0b" />
        <AuditStatCard label="Budget mots" value={formatAuditNumber(totals.words)} color="#60a5fa" />
      </div>

      {days.map((day, index) => (
        <PlanJsonDayAudit key={day.folder?.folder_id || index} day={day} initiallyOpen={index === 0} />
      ))}
    </div>
  )
}

function buildPlanJsonDays(artifacts) {
  return (artifacts || [])
    .filter(item => item.ok && item.artifact && item.name === 'content-plan.json')
    .map(item => {
      const plan = item.artifact.structured_course_plan || item.artifact.course_plan || {}
      const courses = Array.isArray(plan.courses)
        ? plan.courses
        : Array.isArray(item.artifact.courses)
          ? item.artifact.courses
          : []
      return { folder: item.folder || {}, plan, courses }
    })
    .filter(day => day.courses.length > 0)
    .sort((a, b) =>
      Number(a.folder?.position ?? a.folder?.folder_position ?? a.folder?.folder_id ?? 0) -
      Number(b.folder?.position ?? b.folder?.folder_position ?? b.folder?.folder_id ?? 0),
    )
}

function PlanJsonDayAudit({ day, initiallyOpen }) {
  const targetWords = day.courses.reduce((sum, course) => sum + Number(course.target_words || 0), 0)
  const sections = day.courses.reduce((sum, course) => sum + plannedSectionsForCourse(course).length, 0)
  const slides = day.courses.reduce((sum, course) =>
    sum + plannedSectionsForCourse(course).reduce((sectionSum, section) => sectionSum + slideBeatsForSection(section.plan).length, 0),
  0)

  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(15,23,42,0.48)',
      border: '1px solid rgba(148,163,184,0.14)',
      borderRadius: '12px',
      overflow: 'hidden',
    }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '14px 16px', borderBottom: '1px solid rgba(148,163,184,0.12)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: '#e2e8f0', fontWeight: 900 }}>
            <Icon name="calendar_view_week" /> {folderDisplayName(day.folder)}
          </span>
          <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <SmallMetric label="Thèmes" value={day.courses.length} />
            <SmallMetric label="Sections" value={sections} />
            <SmallMetric label="Slides" value={slides} />
            <SmallMetric label="Budget" value={`${formatAuditNumber(targetWords)} mots`} />
          </span>
        </div>
      </summary>
      <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {day.courses.map((course, index) => (
          <PlanJsonCourseAudit key={course.course_number || index} course={course} initiallyOpen={index === 0} />
        ))}
      </div>
    </details>
  )
}

function PlanJsonCourseAudit({ course, initiallyOpen }) {
  const sections = plannedSectionsForCourse(course)
  const targetWords = Number(course.target_words || 0)
  const slides = sections.reduce((sum, section) => sum + slideBeatsForSection(section.plan).length, 0)
  const constraints = collectPlanConstraints(course)

  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(2,6,23,0.34)',
      border: '1px solid rgba(148,163,184,0.12)',
      borderRadius: '10px',
      overflow: 'hidden',
    }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '13px 14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Thème {course.course_number || '?'} · {courseKindLabel(course.course_kind)}
            </div>
            <div style={{ color: '#e2e8f0', fontWeight: 900, fontSize: '15px', marginTop: '3px', lineHeight: 1.35 }}>
              {course.course_title || 'Thème sans titre'}
            </div>
          </div>
          <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <SmallMetric label="Budget" value={`${formatAuditNumber(targetWords)} mots`} />
            <SmallMetric label="Sections" value={sections.length} />
            <SmallMetric label="Slides" value={slides} />
          </span>
        </div>
      </summary>
      <div style={{ borderTop: '1px solid rgba(148,163,184,0.10)', padding: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {constraints.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '10px' }}>
            {constraints.map((constraint, index) => (
              <PlanConstraintCard key={`${constraint.title}-${index}`} constraint={constraint} />
            ))}
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {sections.map((section, index) => (
            <PlanJsonSectionAudit key={`${section.kind}-${section.partNumber || index}`} section={section} />
          ))}
        </div>
      </div>
    </details>
  )
}

function PlanJsonSectionAudit({ section }) {
  const plan = section.plan || {}
  const targetWords = Number(plan.target_words || 0)
  const mustInclude = Array.isArray(plan.must_include) ? plan.must_include : []
  const mustAvoid = Array.isArray(plan.must_avoid) ? plan.must_avoid : []
  const slideBeats = slideBeatsForSection(plan)

  return (
    <div style={{
      border: '1px solid rgba(148,163,184,0.12)',
      borderRadius: '10px',
      background: 'rgba(15,23,42,0.50)',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '11px 12px',
        borderBottom: '1px solid rgba(148,163,184,0.10)',
        display: 'flex',
        justifyContent: 'space-between',
        gap: '10px',
        flexWrap: 'wrap',
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: sectionKindColor(section.kind), fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            {sectionKindLabel(section.kind, section.partNumber)}
          </div>
          <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '13px', marginTop: '2px' }}>
            {section.title || 'Section'}
          </div>
        </div>
        <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <SmallMetric label="Budget" value={targetWords ? `${formatAuditNumber(targetWords)} mots` : 'non fixé'} />
          <SmallMetric label="À couvrir" value={mustInclude.length} />
          <SmallMetric label="À éviter" value={mustAvoid.length} />
          <SmallMetric label="Slides" value={slideBeats.length} />
        </span>
      </div>
      <div style={{ padding: '12px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px' }}>
        <PlanListBlock title="À couvrir" items={mustInclude} color="#34d399" empty="Aucune contrainte obligatoire." />
        <PlanListBlock title="À éviter" items={mustAvoid} color="#fb7185" empty="Aucun interdit spécifique." />
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#93c5fd', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' }}>
            Slides prévues
          </div>
          {slideBeats.length === 0 ? (
            <div style={{ padding: '12px', color: '#64748b', fontSize: '12px', background: 'rgba(2,6,23,0.32)', border: '1px dashed rgba(148,163,184,0.14)', borderRadius: '8px' }}>
              Section uniquement orale.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {slideBeats.map((beat, index) => (
                <PlanSlideBeatCard key={beat.beat_id || index} beat={beat} index={index} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function PlanListBlock({ title, items, color, empty }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ color, fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' }}>
        {title}
      </div>
      {items.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: '12px', padding: '10px', borderRadius: '8px', background: 'rgba(2,6,23,0.28)', border: '1px dashed rgba(148,163,184,0.12)' }}>
          {empty}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {items.map((item, index) => (
            <div key={index} style={{ color: '#cbd5e1', fontSize: '12px', lineHeight: 1.45, padding: '8px 9px', background: `${color}10`, borderLeft: `2px solid ${color}88`, borderRadius: '7px' }}>
              {String(item)}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function PlanSlideBeatCard({ beat, index }) {
  const anchor = beat.slide_anchor || {}
  return (
    <div style={{ background: 'rgba(30,41,59,0.44)', border: '1px solid rgba(96,165,250,0.18)', borderRadius: '9px', padding: '10px' }}>
      <div style={{ color: '#93c5fd', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Slide {index + 1} · {anchor.template_type || beat.type || 'template'}
      </div>
      <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '12px', marginTop: '4px', lineHeight: 1.35 }}>
        {beat.role || anchor.visual_goal || 'Moment pédagogique prévu'}
      </div>
      {anchor.visual_goal && (
        <div style={{ color: '#94a3b8', fontSize: '11px', lineHeight: 1.45, marginTop: '6px' }}>
          {anchor.visual_goal}
        </div>
      )}
      {anchor.spoken_requirement && (
        <div style={{ marginTop: '8px', color: '#dbeafe', fontSize: '11px', lineHeight: 1.45, padding: '7px 8px', background: 'rgba(59,130,246,0.10)', borderRadius: '7px' }}>
          {anchor.spoken_requirement}
        </div>
      )}
    </div>
  )
}

function PlanConstraintCard({ constraint }) {
  return (
    <div style={{ padding: '10px 11px', borderRadius: '9px', background: 'rgba(2,6,23,0.34)', border: `1px solid ${constraint.color}33` }}>
      <div style={{ color: constraint.color, fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '5px' }}>
        {constraint.title}
      </div>
      <div style={{ color: '#cbd5e1', fontSize: '12px', lineHeight: 1.45 }}>
        {constraint.value}
      </div>
    </div>
  )
}

function collectPlanConstraints(course = {}) {
  const constraints = []
  if (course.course_kind) constraints.push({ title: 'Type de cours', value: courseKindLabel(course.course_kind), color: '#a78bfa' })
  if (Number(course.course_number || 0) === 7) constraints.push({ title: 'Cours 7', value: 'Contrôle attendu des transitions, Q/R et conclusion de journée.', color: '#f59e0b' })
  if (course.opening?.must_include?.length) constraints.push({ title: 'Ouverture', value: `${course.opening.must_include.length} point(s) obligatoires`, color: '#38bdf8' })
  if (course.course_conclusion?.must_avoid?.length) constraints.push({ title: 'Conclusion', value: `${course.course_conclusion.must_avoid.length} interdit(s) à respecter`, color: '#fb7185' })
  if (course.day_conclusion) constraints.push({ title: 'Fin de journée', value: 'Conclusion globale prévue dans ce thème.', color: '#34d399' })
  return constraints
}

function SlideBeatsAuditView({ artifacts }) {
  const days = buildSlideBeatDays(artifacts)
  if (days.length === 0) {
    return (
      <AuditEmptyState
        icon="account_tree"
        title="Aucun teaching beat exploitable"
        detail="L'artefact content-plan.json n'est pas encore disponible, ou aucun slide_anchor activé n'a été trouvé dans le plan."
      />
    )
  }

  const totals = days.reduce((acc, day) => {
    acc.courses += day.courses.length
    acc.sections += day.sections.length
    acc.beats += day.beats.length
    for (const beat of day.beats) {
      const template = beat.anchor.template_type || beat.beat.type || 'template'
      acc.templates[template] = (acc.templates[template] || 0) + 1
    }
    return acc
  }, { courses: 0, sections: 0, beats: 0, templates: {} })
  const topTemplates = Object.entries(totals.templates)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{
        padding: '12px 14px',
        background: 'rgba(59,130,246,0.08)',
        border: '1px solid rgba(96,165,250,0.24)',
        borderRadius: '10px',
        color: '#bfdbfe',
        fontSize: '12px',
        lineHeight: 1.5,
      }}>
        <strong>Lecture de l'étape 7.</strong> Cette vue isole les moments visuels prévus par le plan : teaching beats, anchors slides, templates, objectifs visuels, exigences orales et champs suggérés.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
        <AuditStatCard label="Journées" value={days.length} color="#a78bfa" />
        <AuditStatCard label="Thèmes" value={totals.courses} color="#38bdf8" />
        <AuditStatCard label="Sections avec slides" value={totals.sections} color="#34d399" />
        <AuditStatCard label="Anchors slides" value={totals.beats} color="#f59e0b" />
      </div>

      {topTemplates.length > 0 && (
        <div style={{
          display: 'flex',
          gap: '8px',
          flexWrap: 'wrap',
          padding: '12px',
          borderRadius: '10px',
          border: '1px solid rgba(148,163,184,0.12)',
          background: 'rgba(15,23,42,0.38)',
        }}>
          {topTemplates.map(([template, count]) => (
            <span key={template} style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 9px',
              borderRadius: '999px',
              color: '#dbeafe',
              background: 'rgba(59,130,246,0.12)',
              border: '1px solid rgba(96,165,250,0.22)',
              fontSize: '11px',
              fontWeight: 900,
            }}>
              {template} <span style={{ color: '#93c5fd' }}>{count}</span>
            </span>
          ))}
        </div>
      )}

      {days.map((day, index) => (
        <SlideBeatDayAudit key={day.folder?.folder_id || index} day={day} initiallyOpen={index === 0} />
      ))}
    </div>
  )
}

function buildSlideBeatDays(artifacts) {
  return buildPlanJsonDays(artifacts).map(day => {
    const sections = []
    const beats = []
    for (const course of day.courses) {
      for (const section of plannedSectionsForCourse(course)) {
        const sectionBeats = slideBeatsForSection(section.plan).map((beat, index) => ({
          beat,
          anchor: beat.slide_anchor || {},
          index,
          course,
          section,
        }))
        if (sectionBeats.length > 0) {
          sections.push({ course, section, beats: sectionBeats })
          beats.push(...sectionBeats)
        }
      }
    }
    return { ...day, sections, beats }
  }).filter(day => day.beats.length > 0)
}

function SlideBeatDayAudit({ day, initiallyOpen }) {
  const templates = Array.from(new Set(day.beats.map(item => item.anchor.template_type || item.beat.type || 'template')))
  return (
    <details open={initiallyOpen} style={{
      background: 'rgba(15,23,42,0.48)',
      border: '1px solid rgba(148,163,184,0.14)',
      borderRadius: '12px',
      overflow: 'hidden',
    }}>
      <summary style={{ cursor: 'pointer', listStyle: 'none', padding: '14px 16px', borderBottom: '1px solid rgba(148,163,184,0.12)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: '#e2e8f0', fontWeight: 900 }}>
            <Icon name="calendar_view_week" /> {folderDisplayName(day.folder)}
          </span>
          <span style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <SmallMetric label="Sections" value={day.sections.length} />
            <SmallMetric label="Slides" value={day.beats.length} />
            <SmallMetric label="Templates" value={templates.length} />
          </span>
        </div>
      </summary>

      <div style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {day.sections.map((entry, index) => (
          <SlideBeatSectionAudit key={`${entry.course.course_number}-${entry.section.kind}-${entry.section.partNumber || index}`} entry={entry} />
        ))}
      </div>
    </details>
  )
}

function SlideBeatSectionAudit({ entry }) {
  const { course, section, beats } = entry
  return (
    <div style={{
      border: '1px solid rgba(96,165,250,0.16)',
      borderRadius: '10px',
      background: 'rgba(2,6,23,0.34)',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '12px 13px',
        borderBottom: '1px solid rgba(148,163,184,0.10)',
        display: 'flex',
        justifyContent: 'space-between',
        gap: '10px',
        flexWrap: 'wrap',
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#93c5fd', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Thème {course.course_number || '?'} · {sectionKindLabel(section.kind, section.partNumber)}
          </div>
          <div style={{ color: '#e2e8f0', fontWeight: 900, fontSize: '14px', marginTop: '3px', lineHeight: 1.35 }}>
            {course.course_title || 'Thème sans titre'}
          </div>
          <div style={{ color: '#94a3b8', fontSize: '12px', marginTop: '3px' }}>
            {section.title || 'Section'} · {beats.length} slide{beats.length > 1 ? 's' : ''} prévue{beats.length > 1 ? 's' : ''}
          </div>
        </div>
        <SmallMetric label="Budget section" value={section.plan?.target_words ? `${formatAuditNumber(section.plan.target_words)} mots` : 'non fixé'} />
      </div>

      <div style={{ padding: '12px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
        {beats.map((item, index) => (
          <SlideBeatAnchorCard key={item.beat.beat_id || item.anchor.anchor_id || index} item={item} index={index} />
        ))}
      </div>
    </div>
  )
}

function SlideBeatAnchorCard({ item, index }) {
  const { beat, anchor } = item
  const fields = anchor.fields_hint || {}
  const fieldItems = Array.isArray(fields.items) ? fields.items : []
  return (
    <div style={{
      background: 'rgba(15,23,42,0.64)',
      border: '1px solid rgba(96,165,250,0.20)',
      borderRadius: '10px',
      overflow: 'hidden',
    }}>
      <div style={{ padding: '11px 12px', borderBottom: '1px solid rgba(148,163,184,0.10)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'flex-start' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ color: '#93c5fd', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Slide {index + 1} · {anchor.template_type || beat.type || 'template'}
            </div>
            <div style={{ color: '#e2e8f0', fontWeight: 900, fontSize: '13px', lineHeight: 1.35, marginTop: '4px' }}>
              {beat.role || anchor.visual_goal || 'Moment pédagogique prévu'}
            </div>
          </div>
          {anchor.anchor_id && (
            <span style={{ color: '#64748b', fontSize: '10px', fontWeight: 800, whiteSpace: 'nowrap' }}>
              {anchor.anchor_id}
            </span>
          )}
        </div>
      </div>

      <div style={{ padding: '11px 12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <SlideBeatInfoBlock title="Objectif visuel" text={anchor.visual_goal || beat.visual_goal} color="#38bdf8" />
        <SlideBeatInfoBlock title="Exigence orale" text={anchor.spoken_requirement || beat.spoken_requirement} color="#34d399" />
        <SlideBeatInfoBlock title="Résumé pédagogique" text={beat.summary || beat.event_summary || beat.description} color="#f59e0b" />

        {(fields.text || fieldItems.length > 0) && (
          <div>
            <div style={{ color: '#c4b5fd', fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '7px' }}>
              Champs suggérés
            </div>
            {fields.text && (
              <div style={{ color: '#ddd6fe', fontSize: '12px', lineHeight: 1.45, padding: '8px 9px', background: 'rgba(139,92,246,0.10)', borderRadius: '8px', marginBottom: fieldItems.length ? '7px' : 0 }}>
                {fields.text}
              </div>
            )}
            {fieldItems.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {fieldItems.slice(0, 5).map((field, fieldIndex) => (
                  <div key={fieldIndex} style={{ color: '#cbd5e1', fontSize: '12px', lineHeight: 1.4, padding: '7px 8px', background: 'rgba(2,6,23,0.32)', borderRadius: '7px' }}>
                    {typeof field === 'string' ? (
                      field
                    ) : (
                      <>
                        <strong style={{ color: '#bfdbfe' }}>{field.title || `Élément ${fieldIndex + 1}`}</strong>
                        {field.description ? ` — ${field.description}` : ''}
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function SlideBeatInfoBlock({ title, text, color }) {
  if (!text) return null
  return (
    <div>
      <div style={{ color, fontSize: '11px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '5px' }}>
        {title}
      </div>
      <div style={{ color: '#cbd5e1', fontSize: '12px', lineHeight: 1.45, padding: '8px 9px', background: `${color}10`, borderLeft: `2px solid ${color}88`, borderRadius: '7px' }}>
        {text}
      </div>
    </div>
  )
}

function ArtifactAuditView({ artifacts, stage }) {
  const available = (artifacts || []).filter(item => item.ok && item.artifact)
  if ((stage.artifacts || []).length === 0) {
    return (
      <AuditEmptyState
        icon="visibility"
        title="Étape observable par événements"
        detail="Cette étape ne produit pas encore d'artefact JSON dédié. Les événements associés sont listés plus bas."
      />
    )
  }
  if (available.length === 0) {
    return (
      <AuditEmptyState
        icon="info"
        title="Aucun artefact disponible"
        detail="L'étape n'a pas encore tourné, ou ce job a été généré avant la persistance de cet artefact."
      />
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {available.map((item, i) => (
        <div key={`${item.folder.folder_id}-${item.name}-${i}`} style={{ background: 'rgba(15,23,42,0.48)', border: '1px solid rgba(148,163,184,0.14)', borderRadius: '10px', overflow: 'hidden' }}>
          <div style={{ padding: '10px 12px', borderBottom: '1px solid rgba(148,163,184,0.12)', color: '#cbd5e1', fontWeight: 800, fontSize: '12px' }}>
            {folderDisplayName(item.folder)} · {item.name}
          </div>
          <pre style={{ margin: 0, padding: '12px', maxHeight: '360px', overflow: 'auto', color: '#94a3b8', fontSize: '11px', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(compactArtifactForPreview(item.artifact), null, 2)}
          </pre>
        </div>
      ))}
    </div>
  )
}

function compactArtifactForPreview(artifact) {
  if (!artifact || typeof artifact !== 'object') return artifact
  const compact = { ...artifact }
  if (Array.isArray(compact.courses)) {
    compact.courses = compact.courses.slice(0, 3).map(course => ({
      course_number: course.course_number,
      course_title: course.course_title,
      target_words: course.target_words,
      word_count: course.word_count || course.draft_word_count,
      sections: Array.isArray(course.sections) ? course.sections.length : undefined,
      calibration: course.calibration,
    }))
    compact.preview_note = 'Aperçu limité aux 3 premiers cours pour garder la modale lisible.'
  }
  if (Array.isArray(compact.records)) {
    compact.records = compact.records.slice(0, 8).map(record => ({
      course_number: record.course_number,
      section_label: record.section_label,
      status: record.status,
      proposed: record.proposed,
      patches_applied: record.patches_applied,
      patches_rejected: record.patches_rejected,
    }))
    compact.preview_note = 'Aperçu limité aux 8 premiers enregistrements; les diffs détaillés sont affichés dans la vue dédiée.'
  }
  return compact
}

function AuditEmptyState({ icon, title, detail }) {
  return (
    <div style={{ padding: '18px', background: 'rgba(15,23,42,0.42)', border: '1px solid rgba(148,163,184,0.14)', borderRadius: '10px' }}>
      <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Icon name={icon} /> {title}
      </div>
      <div style={{ color: '#94a3b8', fontSize: '12px', lineHeight: 1.5, marginTop: '6px' }}>
        {detail}
      </div>
    </div>
  )
}

function StepEventsList({ events }) {
  if (!events || events.length === 0) return null
  return (
    <div style={{ marginTop: '18px' }}>
      <div style={{ color: '#cbd5e1', fontSize: '13px', fontWeight: 800, marginBottom: '8px' }}>
        Événements pipeline liés
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {events.map((event, i) => (
          <div key={event.id || i} style={{
            display: 'grid', gridTemplateColumns: '150px 110px 1fr', gap: '10px',
            padding: '8px 10px', background: 'rgba(15,23,42,0.42)',
            border: '1px solid rgba(148,163,184,0.10)', borderRadius: '7px',
            color: '#94a3b8', fontSize: '11px',
          }}>
            <span>{event.created_at ? new Date(String(event.created_at).replace(' ', 'T')).toLocaleString('fr-FR') : '—'}</span>
            <span style={{ color: event.status === 'completed' ? '#34d399' : event.status === 'error' ? '#f87171' : '#fbbf24', fontWeight: 800 }}>
              {event.status || event.event_type}
            </span>
            <span style={{ color: '#cbd5e1' }}>{event.message || event.event_type || event.step}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Carte d'un job existant ──────────────────────────────────────────────────
function JobCard({ job, onSelect, selected }) {
  const step = statusToStep(job.status, job)
  const statusColor = AUDIO_DONE_STATUSES.has(job.status) ? 'green'
    : (job.status === 'error' || job.status === 'audio_error') ? 'red'
    : POLLING_STATUSES.has(job.status) ? 'amber'
    : 'violet'
  const createdAt = formatJobTimestamp(job.created_at)
  const platformLabel = job.platform_label || (job.platform_id ? `P${job.platform_id}` : 'P?')
  const jobLabel = job.job_label || `Job #${job.id}`

  return (
    <div
      onClick={() => onSelect(job)}
      style={{
        background: selected ? 'rgba(139,92,246,0.12)' : 'rgba(15,23,42,0.4)',
        border: `1px solid ${selected ? 'rgba(139,92,246,0.5)' : 'rgba(99,102,241,0.15)'}`,
        borderRadius: '12px',
        padding: '14px 18px',
        cursor: 'pointer',
        marginBottom: '10px',
        transition: 'all 0.2s',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
      }}
      title={`${jobLabel} · ${platformLabel}${job.platform_name ? ` · ${job.platform_name}` : ''}`}
    >
      <div style={{ minWidth: 0, flex: '1 1 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <div style={{ fontWeight: 600, fontSize: '15px', color: '#e2e8f0' }}>{job.tp_name}</div>
          <span style={{
            fontSize: '11px',
            fontWeight: 700,
            color: '#c4b5fd',
            background: 'rgba(139,92,246,0.14)',
            border: '1px solid rgba(139,92,246,0.24)',
            borderRadius: '999px',
            padding: '2px 8px',
          }}>
            {jobLabel}
          </span>
          <span style={{
            fontSize: '11px',
            fontWeight: 700,
            color: '#94a3b8',
            background: 'rgba(148,163,184,0.08)',
            border: '1px solid rgba(148,163,184,0.16)',
            borderRadius: '999px',
            padding: '2px 8px',
          }}>
            {platformLabel}
          </span>
        </div>
        <div style={{ fontSize: '11px', color: '#a78bfa', fontWeight: 600, marginTop: '4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {job.platform_name || 'Plateforme sans nom'}
        </div>
        <div style={{ fontSize: '12px', color: '#64748b', marginTop: '3px', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
          <span>{job.total_hours}h · {job.nb_days} jour{job.nb_days > 1 ? 's' : ''}</span>
          <span>RNCP {job.rncp_code}</span>
          {createdAt && <span>Créé le {createdAt}</span>}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={S.tag(statusColor)}>{job.status.replace(/_/g, ' ')}</span>
        <span style={{ color: '#475569', fontSize: '18px' }}><Icon name="chevron_right" /></span>
      </div>
    </div>
  )
}

// ─── Formulaire création nouveau job ─────────────────────────────────────────
function NewJobForm({ onCreated }) {
  const [platformName, setPlatformName] = useState('')
  const [tpName, setTpName] = useState('')
  const [rncpCode, setRncpCode] = useState('')
  const [hours, setHours] = useState('')
  const [model, setModel] = useState('pro')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const nbDays = hours ? Math.ceil(parseInt(hours) / 7) : 0
  const canCreate = platformName.trim() && tpName.trim() && rncpCode.trim() && parseInt(hours) > 0

  const handleCreate = async () => {
    if (!canCreate) return
    setCreating(true)
    setError('')
    try {
      const resp = await fetch(apiUrl('/api/formation/init'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          platform_name: platformName.trim(),
          tp_name: tpName.trim(),
          rncp_code: rncpCode.trim().replace(/^RNCP/i, ''),
          total_hours: parseInt(hours),
          model,
        }),
      })
      const data = await resp.json()
      if (data.job_id) onCreated(data.job_id)
      else setError(data.error || 'Erreur création')
    } catch (e) {
      setError('Erreur réseau')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div style={S.card}>
      <div style={S.cardTitle}><Icon name="add_circle" /> Nouveau pipeline formation</div>

      {/* Nom de la plateforme */}
      <div style={{ marginBottom: '16px' }}>
        <label style={S.label}>Nom de la plateforme (nouveau module)</label>
        <input
          style={S.input}
          value={platformName}
          onChange={e => setPlatformName(e.target.value)}
          placeholder="ex: Formation CRCD Promo 2026, TP EC Septembre…"
        />
        <div style={{ fontSize: '11px', color: '#475569', marginTop: '4px' }}>
          Une nouvelle plateforme sera créée avec ce nom pour accueillir les cours générés.
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: '16px', marginBottom: '16px' }}>
        <div>
          <label style={S.label}>Nom du titre professionnel</label>
          <input
            style={S.input}
            value={tpName}
            onChange={e => setTpName(e.target.value)}
            placeholder="ex: TP CRCD, Employé commercial…"
          />
        </div>
        <div>
          <label style={S.label}>Code RNCP</label>
          <input
            style={S.input}
            value={rncpCode}
            onChange={e => setRncpCode(e.target.value)}
            placeholder="ex: 35304"
          />
          <div style={{ fontSize: '11px', color: '#475569', marginTop: '4px' }}>
            Trouvable sur <a href="https://www.francecompetences.fr" target="_blank" rel="noreferrer" style={{ color: '#7c3aed' }}>francecompetences.fr</a>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: '16px', alignItems: 'end', marginBottom: '16px' }}>
        <div>
          <label style={S.label}>Durée totale (heures)</label>
          <input
            style={S.input}
            type="number"
            min="7"
            value={hours}
            onChange={e => setHours(e.target.value)}
            placeholder="ex: 105"
          />
        </div>
        {nbDays > 0 && (
          <div style={{ color: '#94a3b8', fontSize: '14px', paddingBottom: '10px' }}>
            → <strong style={{ color: '#a78bfa' }}>{nbDays} journée{nbDays > 1 ? 's' : ''}</strong> de cours de 7h
          </div>
        )}
      </div>

      <div style={{ marginBottom: '16px' }}>
        <label style={S.label}>Modèle IA pour toute la pipeline</label>
        <select
          style={S.input}
          value={model}
          onChange={e => setModel(e.target.value)}
        >
          <option value="pro">DeepSeek Pro</option>
          <option value="flash">DeepSeek Flash</option>
          <option value="sonnet">Claude Sonnet</option>
          <option value="haiku">Claude Haiku</option>
        </select>
        <div style={{ fontSize: '11px', color: '#475569', marginTop: '4px' }}>
          Ce choix sera repris par la génération, la sécurité volume, la révision conformité et les relances.
        </div>
      </div>

      {error && <div style={{ color: '#f87171', fontSize: '13px', marginBottom: '12px' }}>{error}</div>}

      {canCreate && nbDays > 0 && (
        <button style={S.btn('primary')} onClick={handleCreate} disabled={creating}>
          {creating ? <Icon name="hourglass_empty" /> : <Icon name="rocket_launch" />}
          {creating ? 'Création…' : `Créer le pipeline (${nbDays} jour${nbDays > 1 ? 's' : ''})`}
        </button>
      )}
    </div>
  )
}

// ─── Panneau "Affiner avec l'IA" ─────────────────────────────────────────────
function RefinePanel({ jobId, contentType, currentContent, onRevised }) {
  const [open, setOpen] = useState(false)
  const [instruction, setInstruction] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const HAIKU = 'claude-haiku-4-5-20251001'

  const handleRefine = async (model) => {
    if (!instruction.trim()) return
    setLoading(true)
    setError('')
    try {
      const resp = await fetch(apiUrl(`/api/formation/${jobId}/refine`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ content_type: contentType, instruction: instruction.trim(), current_content: currentContent, model }),
      })
      const data = await resp.json()
      if (data.revised_content) {
        onRevised(data.revised_content)
        setInstruction('')
        setOpen(false)
      } else {
        setError(data.error || 'Erreur')
      }
    } catch (e) {
      setError('Erreur réseau')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ marginTop: '12px' }}>
      <button
        style={{ ...S.btn('ghost'), fontSize: '12px', padding: '6px 12px' }}
        onClick={() => setOpen(v => !v)}
      >
        <Icon name={open ? 'close' : 'auto_fix_high'} /> {open ? 'Fermer' : 'Affiner avec l\'IA'}
      </button>

      {open && (
        <div style={{ marginTop: '10px', padding: '14px 16px', background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.2)', borderRadius: '10px' }}>
          <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '8px' }}>
            Décris ce que tu veux modifier (ex: "raccourcis le module 2", "ajoute plus d'exercices pratiques", "reformule en termes plus simples"…)
          </div>
          <textarea
            style={{ ...S.input, height: '70px', resize: 'vertical', fontSize: '13px' }}
            value={instruction}
            onChange={e => setInstruction(e.target.value)}
            placeholder="Ex: enlève les références réglementaires, ajoute un module sur la gestion des réclamations…"
            disabled={loading}
          />
          {error && <div style={{ color: '#f87171', fontSize: '12px', margin: '6px 0' }}>{error}</div>}
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px', flexWrap: 'wrap' }}>
            <button
              style={{ ...S.btn('primary'), fontSize: '12px', padding: '6px 14px' }}
              onClick={() => handleRefine(null)}
              disabled={loading || !instruction.trim()}
            >
              {loading ? <Icon name="hourglass_empty" /> : <Icon name="auto_fix_high" />}
              {loading ? 'Modification…' : 'Modifier (Sonnet)'}
            </button>
            <button
              style={{ ...S.btn('neutral'), fontSize: '12px', padding: '6px 14px' }}
              onClick={() => handleRefine(HAIKU)}
              disabled={loading || !instruction.trim()}
              title="~5x moins cher"
            >
              <Icon name="bolt" /> Modifier (Haiku)
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Bloc d'étape individuel ──────────────────────────────────────────────────
// ─── Double colonne API / Claude Code — Phase 2 ─────────────────────────────
// Activation par `import.meta.env.DEV` : colonne droite visible uniquement en
// dev (localhost:5173 via Vite). Les build prod Azure Static Web Apps gardent
// la mono-colonne API. Pattern cohérent avec le gating backend `LOCAL_DEV=true`
// documenté dans memoire/03-decisions/pipeline-dual-api-et-claude-code.md.
const DUAL_COLUMN_ENABLED = import.meta.env.DEV

const CC_MODELS = [
  { value: 'haiku', label: 'Haiku', hint: 'rapide, volume' },
  { value: 'sonnet', label: 'Sonnet', hint: 'qualité fine' },
]
const CC_DEFAULT_MODEL_BY_STEP = {
  kb: 'haiku',
  global: 'haiku',
  daily: 'haiku',
  content: 'sonnet',
  review: 'sonnet',
}
// Subprocess auto : global + daily + kb en mode mono-chunk,
// content + review en mode chunked
// (boucle séquentielle de N appels CLI dans le backend, voir
// claude_code_mission_service.py:_execute_chunked).
// kb : prompt borné à 1500-2500 mots/compétence × ~10 = ~25K mots ≈ 38K tokens
// (largement sous la limite Sonnet 64K output). Parsing tolérant à la
// troncature dans `_import_kb` via `_repair_truncated_json`.
const CC_AUTO_EXEC_ENABLED = {
  global: true,
  kb: true,
  daily: true,
  content: true,
  review: true,
}

function StepDualLayout({ apiContent, claudeCodeContent }) {
  // En mono-colonne (DUAL_COLUMN_ENABLED=false), on ne rend que le contenu
  // API ; aucun visuel n'évoque Claude Code. Le code reste présent mais
  // dormant côté front de prod.
  if (!DUAL_COLUMN_ENABLED) return apiContent
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1px 1fr',
        gap: '24px',
        alignItems: 'start',
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: '11px',
            fontWeight: 700,
            color: '#60a5fa',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            marginBottom: '10px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <Icon name="cloud" style={{ fontSize: '14px' }} /> API Cloud
        </div>
        {apiContent}
      </div>
      <div
        aria-hidden
        style={{
          alignSelf: 'stretch',
          background: 'rgba(255,255,255,0.12)',
          width: '1px',
        }}
      />
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: '11px',
            fontWeight: 700,
            color: '#f59e0b',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            marginBottom: '10px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <Icon name="terminal" style={{ fontSize: '14px' }} /> Claude Code local
        </div>
        {claudeCodeContent}
      </div>
    </div>
  )
}

function ClaudeCodeStepActions({
  stepKey,
  stepLabel,
  jobId,
  disabled,
  disabledReason,
  onExport,
  onExecute,
  pendingMission,
  onImport,
  generatedVia,
  defaultModel,
}) {
  const [model, setModel] = useState(defaultModel || CC_DEFAULT_MODEL_BY_STEP[stepKey] || 'haiku')
  const [exporting, setExporting] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [showLogs, setShowLogs] = useState(false)

  const isRunning = pendingMission?.execution_status === 'running'
  const execDone = pendingMission?.execution_status === 'done'
  const execError = pendingMission?.execution_status === 'error'

  const handleExport = async () => {
    if (disabled || exporting) return
    setExporting(true)
    try {
      await onExport({ stepKey, model })
    } finally {
      setExporting(false)
    }
  }
  const handleExecute = async () => {
    if (disabled || executing || isRunning) return
    setExecuting(true)
    try {
      await onExecute({ stepKey, model })
    } finally {
      setExecuting(false)
    }
  }
  const handleImport = async () => {
    if (importing || !pendingMission) return
    setImporting(true)
    try {
      await onImport({ stepKey })
    } finally {
      setImporting(false)
    }
  }

  return (
    <div
      style={{
        padding: '14px',
        border: '1px dashed rgba(245, 158, 11, 0.3)',
        borderRadius: '10px',
        background: 'rgba(245, 158, 11, 0.04)',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
      }}
    >
      <div style={{ fontSize: '13px', color: '#fbbf24', fontWeight: 600 }}>{stepLabel}</div>

      {/* Badge de provenance — UNIQUEMENT si la dernière génération vient
          de Claude Code. La colonne API a déjà ses propres indicateurs ;
          afficher "Généré via API" sur la colonne CC est trompeur (le user
          se demande pourquoi son côté CC parle d'API). */}
      {generatedVia && generatedVia !== 'api' && (
        <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Icon name="terminal" style={{ fontSize: '12px' }} />
          Généré via {generatedVia === 'claude_code_haiku' ? 'Claude Code Haiku' : 'Claude Code Sonnet'}
        </div>
      )}

      <label style={{ fontSize: '12px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '8px' }}>
        Modèle :
        <select
          value={model}
          onChange={e => setModel(e.target.value)}
          disabled={disabled || exporting}
          style={{
            background: 'rgba(15,23,42,0.8)',
            color: '#e2e8f0',
            border: '1px solid rgba(245,158,11,0.3)',
            borderRadius: '6px',
            padding: '4px 8px',
            fontSize: '12px',
            outline: 'none',
          }}
        >
          {CC_MODELS.map(m => (
            <option key={m.value} value={m.value}>{m.label} — {m.hint}</option>
          ))}
        </select>
      </label>

      {/* Bouton principal : exécution automatique via subprocess `claude`.
          Scope V1 : uniquement pour `global`. Les autres étapes affichent
          un message "à venir" + bouton d'export manuel pour ceux qui
          veulent vraiment essayer. */}
      {CC_AUTO_EXEC_ENABLED[stepKey] ? (
        <button
          onClick={handleExecute}
          disabled={disabled || executing || isRunning}
          title={
            disabled ? (disabledReason || 'Non disponible à cette étape')
            : isRunning ? 'Exécution en cours — Claude Code travaille'
            : 'Exporte la mission + lance `claude -p` + importe le résultat automatiquement'
          }
          style={{
            ...S.btn('primary'),
            padding: '7px 12px',
            fontSize: '12px',
            background: isRunning
              ? 'linear-gradient(135deg, #78350f, #d97706)'
              : 'linear-gradient(135deg, #d97706, #f59e0b)',
            color: '#fff',
            boxShadow: '0 4px 12px rgba(245,158,11,0.25)',
            opacity: disabled ? 0.5 : 1,
            cursor: (disabled || isRunning) ? 'wait' : 'pointer',
          }}
        >
          <Icon name={isRunning || executing ? 'hourglass_empty' : 'play_circle'} />{' '}
          {isRunning ? 'Claude Code travaille…' : executing ? 'Lancement…' : 'Exécuter avec Claude Code'}
        </button>
      ) : (
        <div
          style={{
            padding: '8px 10px',
            border: '1px dashed rgba(148,163,184,0.25)',
            borderRadius: '8px',
            fontSize: '11px',
            color: '#94a3b8',
            lineHeight: 1.4,
          }}
        >
          <strong style={{ color: '#cbd5e1' }}>Exécution auto à venir</strong><br />
          V1 : on valide le subprocess Claude Code d'abord sur <em>Programme global</em>.
          Ensuite on l'étendra aux autres étapes avec une stratégie adaptée
          (chunking pour KB/content, etc.).
        </div>
      )}

      {/* État d'exécution : en cours / terminé / erreur */}
      {isRunning && (
        <div style={{ fontSize: '11px', color: '#fbbf24', lineHeight: 1.4 }}>
          Peut prendre de quelques minutes à ~30 min selon l'étape et le modèle.
          L'import se fait automatiquement à la fin.
        </div>
      )}

      {/* Progression chunked (content/review) : "X/N — chunk_id" */}
      {pendingMission?.progress && pendingMission.progress.total > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div style={{ fontSize: '11px', color: '#cbd5e1', display: 'flex', justifyContent: 'space-between' }}>
            <span>
              <strong>{pendingMission.progress.current}/{pendingMission.progress.total}</strong>
              {pendingMission.progress.current_chunk ? ` · ${pendingMission.progress.current_chunk}` : ''}
            </span>
            {pendingMission.progress.errors?.length > 0 && (
              <span style={{ color: '#f87171' }}>
                {pendingMission.progress.errors.length} erreur(s)
              </span>
            )}
          </div>
          <div style={{ height: '4px', background: 'rgba(148,163,184,0.15)', borderRadius: '2px', overflow: 'hidden' }}>
            <div style={{
              height: '100%',
              width: `${Math.round((pendingMission.progress.current / pendingMission.progress.total) * 100)}%`,
              background: pendingMission.progress.errors?.length > 0
                ? 'linear-gradient(90deg, #d97706, #f59e0b)'
                : 'linear-gradient(90deg, #34d399, #10b981)',
              transition: 'width 0.3s ease',
            }} />
          </div>
          {(pendingMission.progress.status === 'throttling' || pendingMission.progress.status === 'rate_limited') && (
            <div style={{
              fontSize: '10px',
              color: pendingMission.progress.status === 'rate_limited' ? '#f87171' : '#fbbf24',
              fontStyle: 'italic',
            }}>
              {pendingMission.progress.status === 'rate_limited'
                ? '⏳ Rate limit Anthropic atteint — attente avant retry automatique…'
                : '⏸ Pause anti-rate-limit (75s) entre chunks…'}
            </div>
          )}
        </div>
      )}
      {(isRunning || execDone || execError) && (
        <button
          onClick={() => setShowLogs(true)}
          style={{ ...S.btn('ghost'), padding: '4px 10px', fontSize: '11px' }}
          title="Voir les logs de Claude Code (stdout du subprocess)"
        >
          <Icon name="terminal" style={{ fontSize: '13px' }} /> Voir les logs
        </button>
      )}
      {showLogs && (
        <ClaudeCodeLogsModal
          jobId={jobId}
          stepKey={stepKey}
          onClose={() => setShowLogs(false)}
          autoPoll={isRunning}
        />
      )}
      {execDone && (
        <div style={{ fontSize: '11px', color: '#34d399', display: 'flex', alignItems: 'center', gap: '4px' }}>
          <Icon name="check_circle" style={{ fontSize: '13px' }} />
          Exécution terminée et importée
        </div>
      )}
      {execError && (
        <div style={{ fontSize: '11px', color: '#f87171', lineHeight: 1.4 }}>
          <Icon name="error" style={{ fontSize: '12px' }} /> Échec : {pendingMission.execution_error}
        </div>
      )}

      {/* Bouton avancé : export manuel (pour cas où on veut intervenir) */}
      <button
        onClick={handleExport}
        disabled={disabled || exporting || isRunning}
        title={disabled ? disabledReason || 'Non disponible à cette étape' : 'Avancé : exporter les fichiers sans lancer Claude Code (tu lances manuellement dans ton terminal)'}
        style={{
          ...S.btn('ghost'),
          padding: '5px 10px',
          fontSize: '11px',
          borderColor: 'rgba(148,163,184,0.25)',
          color: '#94a3b8',
          opacity: disabled || isRunning ? 0.4 : 0.8,
        }}
      >
        <Icon name="file_download" style={{ fontSize: '13px' }} />{' '}
        {exporting ? 'Export…' : 'Exporter manuellement'}
      </button>

      {pendingMission && pendingMission.has_output && !isRunning && (
        <div
          style={{
            padding: '8px 10px',
            border: '1px solid rgba(245,158,11,0.4)',
            borderRadius: '8px',
            background: 'rgba(245,158,11,0.08)',
            fontSize: '11px',
            color: '#fbbf24',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: '4px' }}>Résultat présent</div>
          <div style={{ color: '#fde68a', marginBottom: '6px', lineHeight: 1.4 }}>
            output.md existe dans <code style={{ fontSize: '10px' }}>{pendingMission.path}</code>
          </div>
          <button
            onClick={handleImport}
            disabled={importing}
            style={{
              ...S.btn('ghost'),
              padding: '4px 10px',
              fontSize: '11px',
              width: '100%',
              justifyContent: 'center',
            }}
          >
            <Icon name={importing ? 'hourglass_empty' : 'file_upload'} />{' '}
            {importing ? 'Import…' : 'Importer le résultat manuellement'}
          </button>
        </div>
      )}
    </div>
  )
}


// Variante StepBlock pour la colonne Claude Code — même hauteur d'alignement
// que son pendant API (via grid-row partagée), mais style ambre distinct et
// label allégé (pas de numéro d'étape en grand).
function StepBlockCC({ stepIndex, currentStep, status, title, icon, children }) {
  const active = stepIndex === currentStep
  const done = stepIndex < currentStep
  const pending = stepIndex > currentStep
  return (
    <div style={{
      ...S.card,
      border: `1px solid ${active ? 'rgba(245,158,11,0.35)' : done ? 'rgba(245,158,11,0.2)' : 'rgba(245,158,11,0.12)'}`,
      background: 'rgba(245,158,11,0.03)',
      opacity: pending ? 0.5 : 1,
      transition: 'all 0.3s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: active || done ? '16px' : '0' }}>
        <div style={{
          width: '32px', height: '32px', borderRadius: '8px', fontSize: '16px',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(245,158,11,0.12)',
          color: '#fbbf24',
        }}>
          <Icon name={icon} />
        </div>
        <span style={{ fontWeight: 600, color: '#fbbf24', flex: 1, fontSize: '14px' }}>
          {title}
        </span>
      </div>
      {(active || done) && children}
    </div>
  )
}


function StepBlock({ stepIndex, currentStep, status, title, icon, children }) {
  const active = stepIndex === currentStep
  const done = stepIndex < currentStep
  const pending = stepIndex > currentStep

  return (
    <div style={{
      ...S.card,
      border: `1px solid ${active ? 'rgba(139,92,246,0.4)' : done ? 'rgba(16,185,129,0.2)' : 'rgba(99,102,241,0.1)'}`,
      opacity: pending ? 0.45 : 1,
      transition: 'all 0.3s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: active ? '20px' : '0' }}>
        <div style={{
          width: '32px', height: '32px', borderRadius: '8px', fontSize: '16px',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: done ? 'rgba(16,185,129,0.15)' : active ? 'rgba(139,92,246,0.15)' : 'rgba(30,41,59,0.8)',
          color: done ? '#34d399' : active ? '#a78bfa' : '#475569',
        }}>
          {done ? <Icon name="check" /> : <Icon name={icon} />}
        </div>
        <span style={{ fontWeight: 600, color: done ? '#34d399' : active ? '#e2e8f0' : '#475569', flex: 1 }}>
          {title}
        </span>
        {done && <span style={S.tag('green')}>Terminé</span>}
        {active && POLLING_STATUSES.has(status) && !AUDIO_DONE_STATUSES.has(status) && <span style={S.tag('amber')}><Icon name="hourglass_empty" /> En cours…</span>}
      </div>
      {(active || done) && children}
    </div>
  )
}

// ─── Page principale ──────────────────────────────────────────────────────────
export default function FormationPipeline() {
  const [jobs, setJobs] = useState([])
  const [selectedJobId, setSelectedJobId] = useState(null)
  const [job, setJob] = useState(null)
  const [showNew, setShowNew] = useState(false)
  const [loading, setLoading] = useState(true)

  // États étape 3 — programme global
  const [globalProgram, setGlobalProgram] = useState('')
  const [globalEditing, setGlobalEditing] = useState(false)
  const [globalValidating, setGlobalValidating] = useState(false)

  // États étape 4 — programmes journée
  const [dailyPrograms, setDailyPrograms] = useState([])
  const [dailyEditIdx, setDailyEditIdx] = useState(null)
  const [dailyEditText, setDailyEditText] = useState('')
  const [dailyValidating, setDailyValidating] = useState(false)

  // États étape 5 — Génération cours (texte)
  const [launchingTTS, setLaunchingTTS] = useState(false)
  const [ttsResult, setTtsResult] = useState(null)
  const [contentFolders, setContentFolders] = useState([])
  const [viewingFolder, setViewingFolder] = useState(null)    // folder object affiché en modal
  const [reportFolder, setReportFolder] = useState(null)           // rapport conformité stricte
  const [humanizationReportFolder, setHumanizationReportFolder] = useState(null)  // ancien rapport humanisation, affiché seulement pour les jobs legacy

  // Audio à la demande par journée
  const [audioError, setAudioError] = useState('')
  const [folderAudioRunning, setFolderAudioRunning] = useState({})
  const [continuingAfterTextFolders, setContinuingAfterTextFolders] = useState({})
  const [continueAfterTextError, setContinueAfterTextError] = useState('')
  const [continueAfterTextNotice, setContinueAfterTextNotice] = useState('')
  const [resumeExpanded, setResumeExpanded] = useState({})
  // Modèle utilisé pour la relance aval. Initialisé sur l'auto_pilot_model du
  // job courant si présent, sinon DeepSeek Pro (cas des jobs historiques sans
  // colonne persistée).
  const [continueAfterTextModel, setContinueAfterTextModel] = useState('deepseek-v4-pro')
  useEffect(() => {
    if (job?.auto_pilot_model) {
      setContinueAfterTextModel(job.auto_pilot_model)
    }
  }, [job?.auto_pilot_model])
  const [pipelineDiagnostic, setPipelineDiagnostic] = useState(null)
  const [pipelineDiagnosticLoading, setPipelineDiagnosticLoading] = useState(false)
  const [pipelineDiagnosticError, setPipelineDiagnosticError] = useState('')

  // Module persistant lié à ce job (créé automatiquement à la fin de la pipeline).
  // Fetché depuis /api/hr/formation-modules, filtré par source_pipeline_job_id.
  const [linkedModule, setLinkedModule] = useState(null)

  // État Knowledge Base (Couche 1)
  const [kb, setKb] = useState({ entries: [], stats: { total: 0, completed: 0, error: 0, total_words: 0 } })

  // Actions en cours
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState('')

  const pollingRef = useRef(null)
  const selectedJobIdRef = useRef(null)
  useEffect(() => {
    selectedJobIdRef.current = selectedJobId
  }, [selectedJobId])

  // ─── Fetch liste des jobs ─────────────────────────────────────────────────
  const fetchJobs = useCallback(async () => {
    try {
      const resp = await fetch(apiUrl('/api/formation/list'), { credentials: 'include' })
      const data = await resp.json()
      if (data.jobs) setJobs(data.jobs)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchJobs() }, [fetchJobs])

  // ─── Fetch job courant ────────────────────────────────────────────────────
  const fetchJob = useCallback(async (id) => {
    try {
      const resp = await fetch(apiUrl(`/api/formation/${id}`), { credentials: 'include' })
      const data = await resp.json()
      if (selectedJobIdRef.current && Number(selectedJobIdRef.current) !== Number(id)) return
      if (data.id && Number(data.id) === Number(id)) {
        setJob(data)
        // Synchroniser les états locaux si pas en train d'éditer
        if (!globalEditing) setGlobalProgram(data.global_program || '')
        if (dailyEditIdx === null && data.daily_programs) {
          try { setDailyPrograms(JSON.parse(data.daily_programs)) } catch {}
        }
      }
    } catch (e) { console.error(e) }
  }, [globalEditing, dailyEditIdx])

  // ─── Fetch knowledge base (Couche 1) ──────────────────────────────────────
  const fetchKb = useCallback(async (id) => {
    try {
      const resp = await fetch(apiUrl(`/api/formation/${id}/kb`), { credentials: 'include' })
      const data = await resp.json()
      if (data.stats) setKb({ entries: data.entries || [], stats: data.stats })
    } catch (e) { console.error(e) }
  }, [])

  // ─── Auto-pilot : statut + polling pendant l'orchestration auto ────────────
  const [autoPilotState, setAutoPilotState] = useState(null)  // {step, status, error?, ...} ou null

  const fetchAutoPilotStatus = useCallback(async (jobId) => {
    if (!jobId) return
    try {
      const resp = await fetch(apiUrl(`/api/formation/${jobId}/run-auto/status`), { credentials: 'include' })
      const data = await resp.json()
      setAutoPilotState(data && data.status && data.status !== 'idle' ? data : null)
    } catch (e) { /* silent */ }
  }, [])

  const fetchPipelineDiagnostic = useCallback(async (jobId, { silent = false } = {}) => {
    if (!jobId) return
    if (!silent) setPipelineDiagnosticLoading(true)
    setPipelineDiagnosticError('')
    try {
      const resp = await fetch(apiUrl(`/api/formation/${jobId}/diagnostic?events_limit=80`), { credentials: 'include' })
      const data = await resp.json()
      if (selectedJobIdRef.current && Number(selectedJobIdRef.current) !== Number(jobId)) return
      if (resp.ok) {
        setPipelineDiagnostic(data)
      } else {
        setPipelineDiagnosticError(data.error || 'Diagnostic indisponible')
      }
    } catch {
      setPipelineDiagnosticError('Erreur réseau diagnostic')
    } finally {
      if (!silent) setPipelineDiagnosticLoading(false)
    }
  }, [])

  // Poll l'auto-pilot toutes les 5s tant qu'il tourne
  useEffect(() => {
    if (!selectedJobId) return
    fetchAutoPilotStatus(selectedJobId)
    fetchPipelineDiagnostic(selectedJobId, { silent: true })
    const interval = setInterval(() => {
      fetchAutoPilotStatus(selectedJobId)
      fetchPipelineDiagnostic(selectedJobId, { silent: true })
    }, 5000)
    return () => clearInterval(interval)
  }, [selectedJobId, fetchAutoPilotStatus, fetchPipelineDiagnostic])

  // ─── Fetch module lié au job courant ──────────────────────────────────────
  const fetchLinkedModule = useCallback(async (jobId) => {
    if (!jobId) { setLinkedModule(null); return }
    try {
      const resp = await fetch(apiUrl('/api/hr/formation-modules'), { credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        const mod = (data.modules || []).find(m => m.source_pipeline_job_id === jobId)
        setLinkedModule(mod || null)
      }
    } catch (e) { console.error('Erreur fetch module:', e) }
  }, [])

  // ─── Polling automatique ──────────────────────────────────────────────────
  useEffect(() => {
    if (!selectedJobId) return
    fetchJob(selectedJobId)
    fetchKb(selectedJobId)
    fetchLinkedModule(selectedJobId)

    const startPolling = () => {
      pollingRef.current = setInterval(async () => {
        const resp = await fetch(apiUrl(`/api/formation/${selectedJobId}`), { credentials: 'include' })
        const data = await resp.json()
        if (data.id) {
          setJob(data)
          if (!globalEditing) setGlobalProgram(data.global_program || '')
          if (dailyEditIdx === null && data.daily_programs) {
            try { setDailyPrograms(JSON.parse(data.daily_programs)) } catch {}
          }
          // Rafraîchir la KB pendant l'enrichissement
          if (data.status === 'kb_building' || data.status === 'kb_ready') {
            fetchKb(selectedJobId)
          }
          // Rafraîchir le diagnostic pendant la synthèse audio pour que la
          // barre de progression temps réel par dossier reste vivante (events
          // audio_progress se mettent à jour seulement si on re-fetch).
          if (AUDIO_ACTIVE_STATUSES.has(data.status)) {
            fetchPipelineDiagnostic(selectedJobId, { silent: true })
          }
          // Arrêter le polling quand le statut n'est plus "en cours"
          if (!POLLING_STATUSES.has(data.status)) {
            clearInterval(pollingRef.current)
          }
          // Quand la pipeline atteint l'état audio final, un module est auto-créé côté
          // backend. On le récupère pour l'afficher dans le bloc Synthèse TTS.
          if (AUDIO_DONE_STATUSES.has(data.status)) {
            fetchLinkedModule(selectedJobId)
          }
        }
      }, 3000)
    }

    startPolling()
    return () => clearInterval(pollingRef.current)
  }, [selectedJobId])

  // Relancer le polling si le statut devient "en cours"
  useEffect(() => {
    if (job && POLLING_STATUSES.has(job.status)) {
      clearInterval(pollingRef.current)
      pollingRef.current = setInterval(() => fetchJob(job.id), 3000)
    }
  }, [job?.status])

  // ─── Actions API ──────────────────────────────────────────────────────────
  const doAction = async (path, body = {}) => {
    setActionLoading(true)
    setActionError('')
    try {
      const resp = await fetch(apiUrl(`/api/formation/${selectedJobId}/${path}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })
      const data = await resp.json()
      if (data.error) setActionError(data.error)
      else {
        await fetchJob(selectedJobId)
        await fetchJobs()
      }
      return data
    } catch (e) {
      setActionError('Erreur réseau')
    } finally {
      setActionLoading(false)
    }
  }

  const HAIKU = 'claude-haiku-4-5-20251001'

  const handleFetchReac = () => doAction('fetch-reac')
  const handleEnrichReac = (model) => doAction('enrich-reac', model ? { model } : {})
  const handleGenerateGlobal = (model) => doAction('generate-global', model ? { model } : {})
  const handleSplitDaily = (model) => doAction('split-daily', model ? { model } : {})

  const handleValidateGlobal = async () => {
    setGlobalValidating(true)
    const body = globalEditing ? { program_text: globalProgram } : {}
    await doAction('validate-global', body)
    setGlobalEditing(false)
    setGlobalValidating(false)
  }

  const handleValidateDaily = async () => {
    setDailyValidating(true)
    // Si on a édité, envoyer les programmes modifiés
    const body = { daily_programs: dailyPrograms }
    await doAction('validate-daily', body)
    setDailyEditIdx(null)
    setDailyValidating(false)
  }

  const handleLaunchTTS = async (model) => {
    setLaunchingTTS(true)
    const data = await doAction('launch-tts', model ? { model } : {})
    if (data?.folder_ids) setTtsResult(data)
    setLaunchingTTS(false)
  }

  // ─── Étape 5 suite — fetch de l'état des dossiers cours par journée ───────
  const fetchContentFolders = useCallback(async (jobId) => {
    try {
      const resp = await fetch(apiUrl(`/api/formation/${jobId}/content`), { credentials: 'include' })
      const data = await resp.json()
      if (selectedJobIdRef.current && Number(selectedJobIdRef.current) !== Number(jobId)) return
      if (data.folders) setContentFolders(data.folders)
      else setContentFolders([])
    } catch (e) {
      console.error('fetchContentFolders:', e)
      setContentFolders([])
    }
  }, [])

  // Rehydrate les dossiers dès que le job peut avoir du texte. Important :
  // après découplage audio, un job texte prêt est `text_ready`, donc un refresh
  // ne doit pas retomber sur l'écran "Générer".
  useEffect(() => {
    if (!job || !selectedJobId) return
    const shouldLoadContent =
      TEXT_AVAILABLE_STATUSES.has(job.status) ||
      job.daily_programs_validated ||
      contentFolders.length > 0
    if (!shouldLoadContent) return

    fetchContentFolders(selectedJobId)
    const shouldPollContent =
      CONTENT_POLLING_STATUSES.has(job.status) ||
      contentFolders.some(f => f.content_status && f.content_status !== 'completed')
    if (!shouldPollContent) return

    const interval = setInterval(() => {
      const allDone = contentFolders.length > 0 &&
        contentFolders.every(f => f.content_status === 'completed')
      if (!allDone) fetchContentFolders(selectedJobId)
    }, 3000)
    return () => clearInterval(interval)
  }, [selectedJobId, job?.status, job?.daily_programs_validated, contentFolders.length, fetchContentFolders])

  const allContentCompleted = contentFolders.length > 0 &&
    contentFolders.every(f => f.content_status === 'completed')

  const handleDownloadDocx = (folderId, version = 'current') => {
    // Ouvre directement l'URL backend (Content-Disposition: attachment).
    // version='current' = état actuel (post-révision si appliquée)
    // version='pre_review' = snapshot pris au finalize content (avant révision)
    const url = apiUrl(`/api/formation/${selectedJobId}/content/${folderId}/docx?version=${version}`)
    window.open(url, '_blank')
  }

  // ─── Étape 5 — reprise de la génération texte après crash backend ──────────
  const [resumingContent, setResumingContent] = useState(false)
  const handleResumeContent = async () => {
    setResumingContent(true)
    setActionError('')
    try {
      const resp = await fetch(apiUrl(`/api/formation/${selectedJobId}/resume-content`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({}),
      })
      const data = await resp.json()
      if (data.error) setActionError(data.error)
      else await fetchContentFolders(selectedJobId)
    } catch (e) {
      setActionError('Erreur réseau')
    } finally {
      setResumingContent(false)
    }
  }

  const handleContinueAfterText = async (folderId, modelOverride = null, fromStep = 'review') => {
    setContinueAfterTextError('')
    setContinueAfterTextNotice('')
    setPipelineDiagnostic(null)
    setContinuingAfterTextFolders(prev => ({ ...prev, [folderId]: true }))
    try {
      const chosenModel = modelOverride || continueAfterTextModel || job?.auto_pilot_model
      const resp = await fetch(
        apiUrl(`/api/formation/${selectedJobId}/content/${folderId}/continue-after-text`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            model: chosenModel,
            max_slides: 60,
            pace: 'normal',
            from_step: fromStep,
          }),
        },
      )
      const data = await resp.json()
      if (!resp.ok || data.error) {
        setContinueAfterTextError(data.error || `Erreur ${resp.status}`)
        setContinuingAfterTextFolders(prev => { const n = { ...prev }; delete n[folderId]; return n })
        return
      }
      const resolvedFolderId = data.folder_id || folderId
      if (resolvedFolderId !== folderId) {
        const reason = data.folder_resolution?.reason
        setContinueAfterTextNotice(
          `Relance redirigée vers F${resolvedFolderId}${reason ? ` (${reason})` : ''}`,
        )
        setContinuingAfterTextFolders(prev => {
          const next = { ...prev }
          delete next[folderId]
          next[resolvedFolderId] = true
          return next
        })
      }
      await fetchJob(selectedJobId)
      await fetchContentFolders(selectedJobId)
      await fetchVolumeAudit(selectedJobId)
      await fetchPipelineDiagnostic(selectedJobId, { silent: true })
    } catch {
      setContinueAfterTextError('Erreur réseau')
      setContinuingAfterTextFolders(prev => { const n = { ...prev }; delete n[folderId]; return n })
    }
  }

  // ─── Étape 6bis — révision conformité via reviewer API (Claude Sonnet) ────
  // Spec : memoire/03-decisions/pipeline-dual-api-et-claude-code.md — Phase 1.
  // Le backend spawn un greenlet qui audit segment par segment. Côté front on
  // suit l'avancement via `segments_reviewed` / `segments_completed` polled.
  const [reviewingFolders, setReviewingFolders] = useState({})  // { [folderId]: true }
  const [reviewError, setReviewError] = useState('')

  const handleReviewFolder = async (folderId) => {
    setReviewError('')
    setReviewingFolders(prev => ({ ...prev, [folderId]: true }))
    try {
      const resp = await fetch(
        apiUrl(`/api/formation/${selectedJobId}/content/${folderId}/review`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({}),
        }
      )
      const data = await resp.json()
      if (resp.status !== 202 && data.error) {
        setReviewError(data.error)
        setReviewingFolders(prev => { const n = { ...prev }; delete n[folderId]; return n })
        return
      }
      // 202 Accepted — on garde le folder dans reviewingFolders, le polling
      // (plus bas) le retirera automatiquement une fois reviewed === completed.
      await fetchContentFolders(selectedJobId)
    } catch (e) {
      setReviewError('Erreur réseau')
      setReviewingFolders(prev => { const n = { ...prev }; delete n[folderId]; return n })
    }
  }

  // Polling dédié pendant une révision — indépendant du polling génération.
  useEffect(() => {
    const ids = Object.keys(reviewingFolders)
    if (ids.length === 0) return
    const interval = setInterval(() => {
      fetchContentFolders(selectedJobId)
    }, 3000)
    return () => clearInterval(interval)
  }, [reviewingFolders, selectedJobId, fetchContentFolders])

  // À chaque refresh de contentFolders, retirer du set les folders dont la
  // révision est "terminée" = tous les segments ont été **traités** : soit
  // audités avec succès (reviewed=1), soit marqués en échec (review_error
  // défini). Un segment en échec compte pour arrêter le polling sans
  // mentir sur la conformité.
  useEffect(() => {
    setReviewingFolders(prev => {
      const next = { ...prev }
      let changed = false
      for (const f of contentFolders) {
        const processed = (f.segments_reviewed || 0) + (f.segments_review_errors || 0)
        if (next[f.folder_id] && processed >= f.segments_completed && f.segments_completed > 0) {
          delete next[f.folder_id]
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [contentFolders])

  // ─── Étape 6.5 — Sécurité volume (audit + enrichissement à la demande) ────
  // Filet de sécurité POST-génération : si une journée est sous le budget audio
  // calibré, l'utilisateur peut lancer un agent qui enrichit (append-only)
  // les segments les plus courts en respectant les règles #1-#27.
  const [volumeAudit, setVolumeAudit] = useState(null)              // { target, folders[] }
  const [safetyRunning, setSafetyRunning] = useState({})            // { [folderId]: true }
  const [safetyError, setSafetyError] = useState('')
  const [safetyModel, setSafetyModel] = useState('sonnet')
  useEffect(() => {
    if (job?.auto_pilot_model) setSafetyModel(job.auto_pilot_model)
  }, [job?.auto_pilot_model])

  const fetchVolumeAudit = useCallback(async (jobId) => {
    if (!jobId) return
    try {
      const resp = await fetch(apiUrl(`/api/formation/${jobId}/volume-audit`), { credentials: 'include' })
      if (resp.status === 403) return
      const data = await resp.json()
      if (selectedJobIdRef.current && Number(selectedJobIdRef.current) !== Number(jobId)) return
      if (data.folders) setVolumeAudit(data)
    } catch (e) {
      // Silencieux : endpoint optionnel
    }
  }, [])

  useEffect(() => {
    if (!selectedJobId || !autoPilotState || !['running', 'starting'].includes(autoPilotState.status)) return
    fetchContentFolders(selectedJobId)
    fetchVolumeAudit(selectedJobId)
    const interval = setInterval(() => {
      fetchContentFolders(selectedJobId)
      fetchVolumeAudit(selectedJobId)
    }, 5000)
    return () => clearInterval(interval)
  }, [selectedJobId, autoPilotState?.status, autoPilotState?.step, fetchContentFolders, fetchVolumeAudit])

  useEffect(() => {
    const ids = Object.keys(continuingAfterTextFolders)
    if (ids.length === 0 || !selectedJobId) return
    const interval = setInterval(() => {
      fetchJob(selectedJobId)
      fetchContentFolders(selectedJobId)
      fetchVolumeAudit(selectedJobId)
      fetchPipelineDiagnostic(selectedJobId, { silent: true })
    }, 4000)
    return () => clearInterval(interval)
  }, [continuingAfterTextFolders, selectedJobId, fetchJob, fetchContentFolders, fetchVolumeAudit, fetchPipelineDiagnostic])

  useEffect(() => {
    setContinuingAfterTextFolders(prev => {
      const next = { ...prev }
      let changed = false
      const isJobErrored = job?.status === 'audio_error'
      for (const f of contentFolders) {
        const processed = (f.segments_reviewed || 0) + (f.segments_review_errors || 0)
        const reviewDone = f.segments_completed > 0 && processed >= f.segments_completed
        const audioClean = (f.dirty_segments || 0) === 0
        // Reset quand le run est fini : soit succès (review faite + audio clean),
        // soit échec terminal (job en audio_error). Sans ce 2ᵉ cas, le state
        // restait coincé à true après un crash TTS, désactivant les boutons.
        if (next[f.folder_id] && reviewDone && (audioClean || isJobErrored)) {
          delete next[f.folder_id]
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [contentFolders, job?.status])

  // Fetch dès qu'au moins une journée est completed
  useEffect(() => {
    if (!selectedJobId) return
    const hasCompleted = contentFolders.some(f => f.content_status === 'completed')
    if (!hasCompleted) return
    fetchVolumeAudit(selectedJobId)
  }, [selectedJobId, contentFolders, fetchVolumeAudit])

  // Polling pendant une exécution volume safety
  useEffect(() => {
    const ids = Object.keys(safetyRunning)
    if (ids.length === 0) return
    const interval = setInterval(async () => {
      for (const folderId of ids) {
        try {
          const resp = await fetch(
            apiUrl(`/api/formation/${selectedJobId}/content/${folderId}/volume-safety/status`),
            { credentials: 'include' },
          )
          const data = await resp.json()
          if (data.status === 'done' || data.status === 'error') {
            setSafetyRunning(prev => { const n = { ...prev }; delete n[folderId]; return n })
            if (data.status === 'error') {
              setSafetyError(`Folder ${folderId} : ${data.error || 'erreur inconnue'}`)
            }
            await fetchVolumeAudit(selectedJobId)
            await fetchContentFolders(selectedJobId)
          }
        } catch (e) { /* ignore */ }
      }
    }, 4000)
    return () => clearInterval(interval)
  }, [safetyRunning, selectedJobId, fetchVolumeAudit, fetchContentFolders])

  const handleLaunchVolumeSafety = async (folderId, mode = null) => {
    setSafetyError('')
    setSafetyRunning(prev => ({ ...prev, [folderId]: true }))
    try {
      const resp = await fetch(
        apiUrl(`/api/formation/${selectedJobId}/content/${folderId}/volume-safety`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(mode ? { model: safetyModel, mode } : { model: safetyModel }),
        },
      )
      const data = await resp.json()
      if (resp.status !== 202 && data.error) {
        setSafetyError(data.error)
        setSafetyRunning(prev => { const n = { ...prev }; delete n[folderId]; return n })
      }
    } catch (e) {
      setSafetyError('Erreur réseau')
      setSafetyRunning(prev => { const n = { ...prev }; delete n[folderId]; return n })
    }
  }

  // ─── Missions Claude Code (Phase 3) — export / import manuel ──────────────
  // Spec : memoire/03-decisions/pipeline-dual-api-et-claude-code.md
  // Le backend écrit des fichiers dans review_queue/<job>/<step>/, l'utilisateur
  // lance `claude --model <haiku|sonnet>` dans son terminal, Claude Code écrit
  // le résultat, puis le frontend importe via un second bouton.
  const [pendingMissions, setPendingMissions] = useState({})  // { [stepKey]: { path, exported_at, command, ... } }
  const [missionModal, setMissionModal] = useState(null)       // { stepKey, mission } quand une mission vient d'être exportée
  const [missionError, setMissionError] = useState('')

  const fetchPendingMissions = useCallback(async (jobId) => {
    if (!DUAL_COLUMN_ENABLED || !jobId) return
    try {
      const resp = await fetch(apiUrl(`/api/formation/${jobId}/missions/pending`), { credentials: 'include' })
      if (resp.status === 403) return  // LOCAL_DEV non activé côté backend, on ignore
      const data = await resp.json()
      if (data.missions) setPendingMissions(data.missions)
    } catch (e) {
      // Silencieux : endpoint pas indispensable
    }
  }, [])

  useEffect(() => {
    if (!selectedJobId) return
    fetchPendingMissions(selectedJobId)
  }, [selectedJobId, fetchPendingMissions])

  const handleExportMission = async ({ stepKey, model }) => {
    setMissionError('')
    try {
      const resp = await fetch(
        apiUrl(`/api/formation/${selectedJobId}/missions/${stepKey}/export`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ model }),
        }
      )
      const data = await resp.json()
      if (!resp.ok || data.error) {
        setMissionError(data.error || `Erreur ${resp.status}`)
        return
      }
      setPendingMissions(prev => ({ ...prev, [stepKey]: data.mission }))
      setMissionModal({ stepKey, mission: data.mission })
    } catch (e) {
      setMissionError('Erreur réseau')
    }
  }

  const handleExecuteMission = async ({ stepKey, model }) => {
    setMissionError('')
    try {
      const resp = await fetch(
        apiUrl(`/api/formation/${selectedJobId}/missions/${stepKey}/execute`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ model }),
        }
      )
      const data = await resp.json()
      if (!resp.ok || data.error) {
        setMissionError(data.error || `Erreur ${resp.status}`)
        return
      }
      // 202 Accepted — le greenlet tourne. Le polling fetchPendingMissions
      // va refresh l'UI avec execution_status='running' puis 'done'/'error'.
      await fetchPendingMissions(selectedJobId)
    } catch (e) {
      setMissionError('Erreur réseau')
    }
  }

  // Polling continu tant qu'au moins une mission est en execution_status='running'
  useEffect(() => {
    if (!selectedJobId || !DUAL_COLUMN_ENABLED) return
    const hasRunning = Object.values(pendingMissions).some(m => m.execution_status === 'running')
    if (!hasRunning) return
    const interval = setInterval(() => {
      fetchPendingMissions(selectedJobId)
      // Si un done récent, on refresh aussi le job et les folders
      fetchJob(selectedJobId)
      fetchContentFolders(selectedJobId)
    }, 4000)
    return () => clearInterval(interval)
  }, [pendingMissions, selectedJobId, fetchPendingMissions])

  const handleImportMission = async ({ stepKey }) => {
    setMissionError('')
    try {
      const resp = await fetch(
        apiUrl(`/api/formation/${selectedJobId}/missions/${stepKey}/import`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({}),
        }
      )
      const data = await resp.json()
      // Si 501 (not_implemented) ou autre erreur : on affiche le message et
      // on GARDE la mission dans la file + la modale reste ouverte.
      // L'utilisateur doit savoir que rien n'a été importé.
      if (!resp.ok || data.error) {
        const prefix = data.not_implemented ? 'Import non implémenté : ' : ''
        setMissionError(`${prefix}${data.error || `Erreur ${resp.status}`}`)
        return
      }
      setPendingMissions(prev => {
        const next = { ...prev }
        delete next[stepKey]
        return next
      })
      setMissionModal(null)
      // Re-fetch l'état courant du job et des folders
      await fetchJob(selectedJobId)
      await fetchContentFolders(selectedJobId)
    } catch (e) {
      setMissionError('Erreur réseau')
    }
  }

  const handleLaunchFolderAudio = async (folder, ttsMode = 'gtts') => {
    if (!folder?.folder_id) return
    setAudioError('')
    setFolderAudioRunning(prev => ({ ...prev, [folder.folder_id]: true }))
    try {
      const resp = await fetch(
        apiUrl(`/api/formation/${selectedJobId}/content/${folder.folder_id}/generate-audio`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            tts_mode: ttsMode,
            force_all: true,
            sync_slides: true,
            auto_generate_slides: true,
          }),
        },
      )
      const data = await resp.json()
      if (!resp.ok || data.error) {
        setAudioError(data.error || `Erreur ${resp.status}`)
      } else {
        await fetchJob(selectedJobId)
        await fetchContentFolders(selectedJobId)
        await fetchLinkedModule(selectedJobId)
        await fetchPipelineDiagnostic(selectedJobId, { silent: true })
      }
    } catch (e) {
      setAudioError('Erreur réseau audio')
    } finally {
      setFolderAudioRunning(prev => {
        const next = { ...prev }
        delete next[folder.folder_id]
        return next
      })
    }
  }

  const handleJobCreated = async (jobId) => {
    setShowNew(false)
    resetJobScopedState()
    setSelectedJobId(jobId)
    setPipelineJobInUrl(jobId)
    await fetchJobs()
  }

  const resetJobScopedState = () => {
    setContentFolders([])
    setViewingFolder(null)
    setReportFolder(null)
    setTtsResult(null)
    setAudioError('')
    setContinueAfterTextError('')
    setContinueAfterTextNotice('')
    setContinuingAfterTextFolders({})
    setReviewingFolders({})
    setReviewError('')
    setVolumeAudit(null)
    setSafetyRunning({})
    setSafetyError('')
    setPipelineDiagnostic(null)
    setPipelineDiagnosticError('')
    setAutoPilotState(null)
    setLinkedModule(null)
    setPendingMissions({})
    setMissionModal(null)
    setMissionError('')
  }

  const handleSelectJob = (j) => {
    resetJobScopedState()
    setSelectedJobId(j.id)
    setPipelineJobInUrl(j.id)
    setJob(j)
    setGlobalProgram(j.global_program || '')
    setDailyPrograms([])
    setDailyEditIdx(null)
    setActionError('')
  }

  useEffect(() => {
    if (showNew || selectedJobId || jobs.length === 0) return
    const rawJobId = new URLSearchParams(window.location.search).get('job')
    const parsedJobId = Number(rawJobId)
    if (!parsedJobId) return
    const initialJob = jobs.find(j => j.id === parsedJobId)
    if (!initialJob) return
    resetJobScopedState()
    setSelectedJobId(initialJob.id)
    setJob(initialJob)
    setGlobalProgram(initialJob.global_program || '')
    setDailyPrograms([])
    setDailyEditIdx(null)
    setActionError('')
  }, [jobs, selectedJobId, showNew])

  // ─── Édition journée ──────────────────────────────────────────────────────
  const startEditDay = (idx) => {
    setDailyEditIdx(idx)
    setDailyEditText(JSON.stringify(dailyPrograms[idx], null, 2))
  }

  const saveEditDay = () => {
    try {
      const parsed = JSON.parse(dailyEditText)
      const updated = [...dailyPrograms]
      updated[dailyEditIdx] = parsed
      setDailyPrograms(updated)
      setDailyEditIdx(null)
    } catch {
      alert('JSON invalide')
    }
  }

  // `text_ready` est l'état normal après la pipeline texte. Les anciens jobs
  // peuvent encore rester en `tts_launched`; dans les deux cas, si tous les
  // dossiers sont complétés, l'étape texte est terminée.
  // On avance currentStep à 6 pour que l'UI reflète l'état réel :
  // texte + slides prêts, audio disponible ensuite par dossier.
  let currentStep = job ? statusToStep(job.status, job) : -1
  if (['text_ready', 'tts_launched'].includes(job?.status) && allContentCompleted) {
    currentStep = 6
  }
  // Détection "stale running" : Azure App Service peut redémarrer le backend
  // (déploiement GitHub Actions, scaling, etc.) en plein run audio → les greenlets
  // meurent silencieusement et le job reste figé en `audio_running` à vie.
  // Sans détection, l'UI bloque les boutons audio de journée indéfiniment.
  // Heuristique : si statut=audio_running mais aucun event audio depuis > 3 min,
  // on considère que la pipeline est morte et on permet la relance.
  const STALE_AUDIO_RUN_MS = 3 * 60 * 1000
  const _audioEvents = (pipelineDiagnostic?.events || []).filter(
    e => e.step === 'audio' || String(e.event_type || '').startsWith('audio_')
  )
  const _lastAudioEventAt = _audioEvents.length > 0
    ? new Date(_audioEvents[_audioEvents.length - 1].created_at).getTime()
    : null
  const audioStale = (
    AUDIO_ACTIVE_STATUSES.has(job?.status)
    && _lastAudioEventAt !== null
    && (Date.now() - _lastAudioEventAt) > STALE_AUDIO_RUN_MS
  )
  const audioBusy = AUDIO_ACTIVE_STATUSES.has(job?.status) && !audioStale
  const selectedPipelineModel = pipelineModelLabel(job?.auto_pilot_model)

  // ─── Render ───────────────────────────────────────────────────────────────
  return (
    <div style={S.page}>
      {/* Top bar */}
      <div style={S.topBar}>
        <div style={{ fontSize: '22px', color: '#8B5CF6' }}><Icon name="school" /></div>
        <h1 style={S.topBarTitle}>Pipeline Formation</h1>
        <div style={{ flex: 1 }} />
        <button style={S.btn('ghost')} onClick={() => { resetJobScopedState(); setShowNew(v => !v); setSelectedJobId(null); setJob(null); setPipelineJobInUrl(null) }}>
          <Icon name={showNew ? 'close' : 'add'} /> {showNew ? 'Annuler' : 'Nouveau pipeline'}
        </button>
      </div>

      <div style={S.container}>

        {/* Formulaire nouveau job */}
        {showNew && <NewJobForm onCreated={handleJobCreated} />}

        {/* Liste des jobs existants */}
        {!showNew && (
          <div style={{ marginBottom: '24px' }}>
            <div style={S.cardTitle}><Icon name="history" /> Pipelines existants</div>
            {loading ? (
              <div style={{ color: '#64748b', fontSize: '14px' }}>Chargement…</div>
            ) : jobs.length === 0 ? (
              <div style={{ color: '#475569', fontSize: '14px', textAlign: 'center', padding: '24px' }}>
                Aucun pipeline. Créez-en un avec le bouton ci-dessus.
              </div>
            ) : (
              jobs.map(j => <JobCard key={j.id} job={j} onSelect={handleSelectJob} selected={j.id === selectedJobId} />)
            )}
          </div>
        )}

        {/* Détail du job sélectionné */}
        {job && !showNew && (
          <>
            {/* En-tête job */}
            <div style={{ ...S.card, background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.25)', marginBottom: '24px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
                <div>
                  <div style={{ fontSize: '20px', fontWeight: 700, color: '#e2e8f0' }}>{job.tp_name}</div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '6px' }}>
                    <span style={S.tag('violet')}>{job.job_label || `Job #${job.id}`}</span>
                    <span style={S.tag('violet')}>{job.platform_label || `P${job.platform_id || '?'}`}</span>
                    {job.created_at && <span style={S.tag('violet')}>Créé le {formatJobTimestamp(job.created_at)}</span>}
                  </div>
                  {job.platform_name && (
                    <div style={{ fontSize: '12px', color: '#8b5cf6', fontWeight: 600, marginTop: '2px' }}>
                      <Icon name="layers" /> {job.platform_name}
                    </div>
                  )}
                  <div style={{ fontSize: '13px', color: '#64748b', marginTop: '4px' }}>
                    RNCP {job.rncp_code} · {job.total_hours}h · {job.nb_days} journée{job.nb_days > 1 ? 's' : ''}
                    {job.reac_length ? <span style={{ color: '#34d399', marginLeft: 6 }}>✓ REAC {(job.reac_length / 1000).toFixed(0)}k</span> : <span style={{ color: '#64748b', marginLeft: 6 }}>REAC non téléchargé</span>}
                    {job.rc_length > 0 && <span style={{ color: '#34d399', marginLeft: 6 }}>✓ RC {(job.rc_length / 1000).toFixed(0)}k</span>}
                    {job.rome_length > 0 && <span style={{ color: '#34d399', marginLeft: 6 }}>✓ ROME {(job.rome_length / 1000).toFixed(0)}k</span>}
                  </div>
                </div>
                <span style={S.tag(
                  AUDIO_DONE_STATUSES.has(job.status) ? 'green'
                  : AUDIO_ACTIVE_STATUSES.has(job.status) ? 'amber'
                  : (job.status === 'error' || job.status === 'audio_error') ? 'red'
                  : 'violet'
                )}>
                  {AUDIO_DONE_STATUSES.has(job.status)
                    ? 'Clôturée'
                    : AUDIO_ACTIVE_STATUSES.has(job.status)
                      ? 'Audio en cours'
                    : job.status?.replace(/_/g, ' ')}
                </span>
              </div>
              {job.error_message && (
                <div style={{ marginTop: '12px', padding: '10px 14px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '8px', fontSize: '13px', color: '#f87171' }}>
                  <strong>Erreur :</strong> {job.error_message}
                </div>
              )}
            </div>

            <PipelineActiveNotice
              job={job}
              autoPilotState={autoPilotState}
              diagnostic={pipelineDiagnostic}
              contentFolders={contentFolders}
            />
            {autoPilotState && autoPilotState.status === 'error' && (
              <div style={{
                padding: '12px 16px',
                marginBottom: '20px',
                borderRadius: '10px',
                background: 'rgba(239,68,68,0.1)',
                border: '1px solid rgba(239,68,68,0.4)',
                color: '#f87171',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                flexWrap: 'wrap',
              }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Icon name="error_outline" /> <strong>Auto-pilot interrompu</strong> à l'étape <em>{autoPilotState.step || '?'}</em> : {autoPilotState.error}
                </div>
                <button
                  style={{
                    ...S.btn('primary'),
                    background: 'linear-gradient(135deg, #3b82f6, #60a5fa)',
                    boxShadow: '0 4px 15px rgba(59,130,246,0.3)',
                    padding: '6px 14px',
                    fontSize: '12px',
                  }}
                  onClick={async () => {
                    try {
                      const resp = await fetch(
                        apiUrl(`/api/formation/${selectedJobId}/run-auto`),
                        {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          credentials: 'include',
                          body: JSON.stringify({
                            tts_mode: autoPilotState.tts_mode || 'gtts',
                            model: autoPilotState.model || 'sonnet',
                          }),
                        },
                      )
                      const data = await resp.json()
                      if (resp.status !== 202 && data.error) {
                        alert(`Reprise impossible : ${data.error}`)
                      } else {
                        await fetchAutoPilotStatus(selectedJobId)
                        await fetchJob(selectedJobId)
                      }
                    } catch (e) {
                      alert('Erreur réseau lors de la reprise')
                    }
                  }}
                >
                  <Icon name="autorenew" /> Reprendre auto-pilot
                </button>
              </div>
            )}

            {/* Bandeau de clôture — affiché quand l'audio est terminé (toutes les
                étapes ont abouti). Marque visuellement la fin de la pipeline.
                Le module persistant créé est affiché dedans (matérialise "1 RNCP
                = 1 module durable", réutilisable pour de nouvelles promos). */}
            {AUDIO_DONE_STATUSES.has(job.status) && (
              <div style={{
                position: 'relative',
                padding: '20px 24px',
                marginBottom: '24px',
                borderRadius: '14px',
                background: 'linear-gradient(135deg, rgba(16,185,129,0.18), rgba(52,211,153,0.08))',
                border: '1px solid rgba(16,185,129,0.45)',
                boxShadow: '0 8px 30px rgba(16,185,129,0.15)',
                overflow: 'hidden',
              }}>
                <div style={{
                  position: 'absolute', top: 0, right: 0,
                  width: '180px', height: '180px',
                  background: 'radial-gradient(circle, rgba(52,211,153,0.18), transparent 70%)',
                  pointerEvents: 'none',
                }} />
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap', position: 'relative' }}>
                  <div style={{
                    width: '52px', height: '52px', borderRadius: '14px',
                    background: 'linear-gradient(135deg, #059669, #10b981)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    boxShadow: '0 4px 18px rgba(16,185,129,0.4)',
                  }}>
                    <Icon name="verified" style={{ fontSize: '28px', color: '#fff' }} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '20px', fontWeight: 700, color: '#34d399', letterSpacing: '0.3px' }}>
                      Pipeline terminée — formation prête
                    </div>
                    <div style={{ fontSize: '13px', color: '#94a3b8', marginTop: '4px' }}>
                      <strong style={{ color: '#e2e8f0' }}>{job.tp_name}</strong>
                      {' · '}{job.nb_days} journée{job.nb_days > 1 ? 's' : ''} générée{job.nb_days > 1 ? 's' : ''}
                      {' · '}{(job.nb_days || 0) * 19} MP3 (cours + Q&A + pauses)
                      {job.platform_name && <> {' · '}plateforme <strong style={{ color: '#a78bfa' }}>{job.platform_name}</strong></>}
                    </div>
                    {linkedModule && (
                      <div style={{ fontSize: '12px', color: '#64748b', marginTop: '6px' }}>
                        Module persistant créé :{' '}
                        <strong style={{ color: '#a78bfa' }}>
                          {linkedModule.tp_name} — RNCP {linkedModule.rncp_code || '?'}
                          {linkedModule.version && <> — {linkedModule.version}</>}
                        </strong>
                        {linkedModule.voice_type && (
                          <> {' · '}voix actuelle : <strong style={{ color: voiceColor(linkedModule.voice_type) }}>{voiceLabel(linkedModule.voice_type)}</strong></>
                        )}
                        {' '}— réutilisable pour toutes les promos sans relancer la pipeline.
                      </div>
                    )}
                  </div>
                  <span style={{
                    ...S.tag('green'),
                    padding: '6px 14px',
                    fontSize: '12px',
                    fontWeight: 700,
                    letterSpacing: '0.5px',
                    textTransform: 'uppercase',
                  }}>
                    <Icon name="check_circle" style={{ fontSize: '14px' }} /> Clôturée
                  </span>
                </div>
              </div>
            )}

            {/* Stepper */}
            <Stepper currentStep={currentStep} status={job.status} />
            <PipelineVisualMap
              job={job}
              currentStep={currentStep}
              autoPilotState={autoPilotState}
              contentFolders={contentFolders}
              diagnostic={pipelineDiagnostic}
            />

            {/* Bandeau missions Claude Code en attente d'import (Phase 3) */}
            {DUAL_COLUMN_ENABLED && Object.keys(pendingMissions).length > 0 && (
              <div
                style={{
                  padding: '12px 16px',
                  background: 'rgba(245,158,11,0.08)',
                  border: '1px solid rgba(245,158,11,0.35)',
                  borderRadius: '10px',
                  fontSize: '13px',
                  color: '#fbbf24',
                  marginBottom: '16px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  flexWrap: 'wrap',
                }}
              >
                <Icon name="warning_amber" />
                <strong>{Object.keys(pendingMissions).length} mission(s) Claude Code en attente d'import</strong>
                <span style={{ color: '#fde68a' }}>
                  · {Object.keys(pendingMissions).join(', ')}
                </span>
              </div>
            )}

            {/* Erreur action */}
            {actionError && (
              <div style={{ padding: '10px 14px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '8px', fontSize: '13px', color: '#f87171', marginBottom: '16px' }}>
                {actionError}
              </div>
            )}
            {missionError && (
              <div style={{ padding: '10px 14px', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.3)', borderRadius: '8px', fontSize: '13px', color: '#fbbf24', marginBottom: '16px' }}>
                Mission : {missionError}
              </div>
            )}

            {/* ── Étape 1 : Init (affichage seul, déjà fait) ── */}
            <StepBlock stepIndex={0} currentStep={currentStep} status={job.status} title="Recherche RNCP & initialisation" icon="search">
              <div style={{ fontSize: '14px', color: '#94a3b8' }}>
                Job initialisé. RNCP <strong style={{ color: '#a78bfa' }}>{job.rncp_code}</strong> sélectionné pour <strong style={{ color: '#a78bfa' }}>{job.tp_name}</strong>.
              </div>
            </StepBlock>

            <FlowArrowDown />

            {/* ── Étape 2 : Téléchargement REAC ── */}
            <StepBlock stepIndex={1} currentStep={currentStep} status={job.status} title="Téléchargement REAC" icon="download">
              {job.status === 'reac_fetching' ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#fbbf24', fontSize: '14px' }}>
                  <Icon name="hourglass_empty" /> Téléchargement REAC en cours…
                </div>
              ) : job.reac_available ? (
                <div>
                  {/* Source téléchargée (REAC seul affiché — RC/ROME tentés en silence côté backend) */}
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '14px' }}>
                    <div style={{
                      padding: '8px 14px', borderRadius: '8px', fontSize: '12px',
                      background: job.reac_length > 0 ? 'rgba(16,185,129,0.08)' : 'rgba(30,41,59,0.6)',
                      border: `1px solid ${job.reac_length > 0 ? 'rgba(16,185,129,0.25)' : 'rgba(99,102,241,0.1)'}`,
                    }}>
                      <div style={{ fontWeight: 600, color: job.reac_length > 0 ? '#34d399' : '#475569' }}>
                        {job.reac_length > 0 ? '✓' : '—'} REAC
                        {job.reac_length > 0 && <span style={{ fontWeight: 400, marginLeft: 6, color: '#64748b' }}>{(job.reac_length / 1000).toFixed(0)}k car.</span>}
                      </div>
                      <div style={{ color: '#475569', marginTop: 2 }}>Référentiel Emploi Activités Compétences</div>
                    </div>
                  </div>
                  <button style={{ ...S.btn('ghost'), fontSize: '12px' }} onClick={handleFetchReac} disabled={actionLoading}>
                    <Icon name="refresh" /> Re-télécharger
                  </button>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '16px' }}>
                    Télécharge le REAC depuis France Compétences (PDF officiel du titre professionnel).
                  </p>
                  <button style={S.btn('primary')} onClick={handleFetchReac} disabled={actionLoading}>
                    <Icon name="download" /> Télécharger les sources
                  </button>
                </div>
              )}
            </StepBlock>

            {/* ─── Connecteur REAC → split en 2 colonnes (ou ↓ simple en mono) ── */}
            {DUAL_COLUMN_ENABLED ? <FlowSplit /> : <FlowArrowDown />}

            {/* ─── Labels de colonnes si DUAL — une ligne commune au-dessus ── */}
            {DUAL_COLUMN_ENABLED && (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '24px 40px',
                  marginBottom: '8px',
                }}
              >
                <div style={{
                  fontSize: '11px', fontWeight: 700, color: '#60a5fa',
                  textTransform: 'uppercase', letterSpacing: '0.1em',
                  display: 'flex', alignItems: 'center', gap: '6px',
                }}>
                  <Icon name="cloud" style={{ fontSize: '14px' }} /> API Cloud · Anthropic
                </div>
                <div style={{
                  fontSize: '11px', fontWeight: 700, color: '#f59e0b',
                  textTransform: 'uppercase', letterSpacing: '0.1em',
                  display: 'flex', alignItems: 'center', gap: '6px',
                }}>
                  <Icon name="terminal" style={{ fontSize: '14px' }} /> Claude Code local · forfait
                </div>
              </div>
            )}

            {/* ─── Wrapper grid des étapes 3-6 (API à gauche, CC à droite) ──
                 En mono : grid 1fr = stack vertical normal.
                 En dual : grid 1fr 1fr + séparateur central sobre en absolute.
                 Chaque paire <StepBlock>/<StepBlockCC> se place auto sur
                 la même ligne grâce à grid-auto-flow: row. Spec :
                 memoire/03-decisions/pipeline-dual-api-et-claude-code.md */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: DUAL_COLUMN_ENABLED ? '1fr 1fr' : '1fr',
                gap: '16px 40px',
                position: 'relative',
                marginBottom: '24px',
              }}
            >
              {DUAL_COLUMN_ENABLED && (
                <div
                  aria-hidden
                  style={{
                    position: 'absolute',
                    top: 0, bottom: 0, left: '50%',
                    width: '1px',
                    background: 'rgba(255,255,255,0.12)',
                    transform: 'translateX(-50%)',
                    pointerEvents: 'none',
                  }}
                />
              )}

            {/* ── Étape 3 : Enrichissement Knowledge Base (Couche 1) ── */}
            <StepBlock stepIndex={2} currentStep={currentStep} status={job.status} title="Enrichissement Knowledge Base" icon="psychology">
              {job.status === 'kb_building' ? (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#fbbf24', fontSize: '14px', marginBottom: '14px' }}>
                    <Icon name="hourglass_empty" /> Enrichissement en cours… ({kb.stats.completed}/{kb.stats.total || '?'} compétences)
                  </div>
                  {kb.stats.total > 0 && (
                    <div style={{ height: '6px', background: 'rgba(30,41,59,0.8)', borderRadius: '3px', overflow: 'hidden', marginBottom: '12px' }}>
                      <div style={{
                        height: '100%',
                        width: `${(kb.stats.completed / kb.stats.total) * 100}%`,
                        background: 'linear-gradient(90deg, #8B5CF6, #a78bfa)',
                        transition: 'width 0.4s',
                      }} />
                    </div>
                  )}
                  {kb.stats.total_words > 0 && (
                    <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '12px' }}>
                      {kb.stats.total_words.toLocaleString()} mots produits jusqu'ici
                    </div>
                  )}
                  <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '10px', fontStyle: 'italic' }}>
                    💡 Si la progression semble figée plus de 2 minutes (backend redémarré, crash), clique "Reprendre" — ça continuera depuis la dernière compétence enregistrée.
                  </div>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button style={S.btn('ghost')} onClick={() => handleEnrichReac()} disabled={actionLoading}>
                      <Icon name="refresh" /> Reprendre (Sonnet)
                    </button>
                    <button style={S.btn('ghost')} onClick={() => handleEnrichReac(HAIKU)} disabled={actionLoading}>
                      <Icon name="bolt" /> Reprendre (Haiku)
                    </button>
                  </div>
                </div>
              ) : job.status === 'kb_ready' || currentStep > 2 ? (
                <div>
                  <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '14px' }}>
                    <div style={{
                      padding: '10px 16px', borderRadius: '10px',
                      background: 'rgba(16,185,129,0.08)',
                      border: '1px solid rgba(16,185,129,0.25)',
                    }}>
                      <div style={{ fontSize: '22px', fontWeight: 700, color: '#34d399' }}>{kb.stats.completed}</div>
                      <div style={{ fontSize: '11px', color: '#64748b', marginTop: 2 }}>compétences enrichies</div>
                    </div>
                    <div style={{
                      padding: '10px 16px', borderRadius: '10px',
                      background: 'rgba(139,92,246,0.08)',
                      border: '1px solid rgba(139,92,246,0.25)',
                    }}>
                      <div style={{ fontSize: '22px', fontWeight: 700, color: '#a78bfa' }}>
                        {kb.stats.total_words >= 1000 ? `${(kb.stats.total_words / 1000).toFixed(1)}k` : kb.stats.total_words}
                      </div>
                      <div style={{ fontSize: '11px', color: '#64748b', marginTop: 2 }}>mots dans la KB</div>
                    </div>
                    {kb.stats.error > 0 && (
                      <div style={{
                        padding: '10px 16px', borderRadius: '10px',
                        background: 'rgba(239,68,68,0.08)',
                        border: '1px solid rgba(239,68,68,0.25)',
                      }}>
                        <div style={{ fontSize: '22px', fontWeight: 700, color: '#f87171' }}>{kb.stats.error}</div>
                        <div style={{ fontSize: '11px', color: '#64748b', marginTop: 2 }}>compétences en erreur</div>
                      </div>
                    )}
                  </div>
                  {kb.entries.length > 0 && (
                    <details style={{ marginBottom: '14px' }} open>
                      <summary style={{ cursor: 'pointer', fontSize: '13px', color: '#a78bfa', marginBottom: '10px' }}>
                        Voir le détail des compétences enrichies ({kb.entries.length})
                      </summary>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '10px', maxHeight: '600px', overflowY: 'auto' }}>
                        {kb.entries.map(e => (
                          <details key={e.id} style={{
                            borderRadius: '8px',
                            background: 'rgba(15,23,42,0.5)',
                            borderLeft: `3px solid ${e.status === 'completed' ? '#34d399' : e.status === 'error' ? '#f87171' : '#64748b'}`,
                          }}>
                            <summary style={{ cursor: 'pointer', padding: '10px 14px', listStyle: 'none' }}>
                              <div style={{ color: '#cbd5e1', fontWeight: 500, fontSize: '13px' }}>{e.competence_title}</div>
                              <div style={{ color: '#64748b', marginTop: 2, fontSize: '11px' }}>
                                {e.bloc} · {e.status === 'completed' ? `${e.total_words} mots` : e.status}
                                {e.error_message && <span style={{ color: '#f87171' }}> — {e.error_message}</span>}
                              </div>
                            </summary>
                            {e.status === 'completed' && (
                              <div style={{ padding: '4px 14px 16px 14px', fontSize: '12px', color: '#cbd5e1', lineHeight: 1.6 }}>
                                {e.definition_pedagogique && (
                                  <div style={{ marginTop: '10px' }}>
                                    <div style={{ color: '#a78bfa', fontWeight: 600, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '4px' }}>Définition pédagogique</div>
                                    <div style={{ whiteSpace: 'pre-wrap' }}>{e.definition_pedagogique}</div>
                                  </div>
                                )}
                                {e.contexte_terrain && (
                                  <div style={{ marginTop: '12px' }}>
                                    <div style={{ color: '#a78bfa', fontWeight: 600, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '4px' }}>Contexte terrain</div>
                                    <div style={{ whiteSpace: 'pre-wrap' }}>{e.contexte_terrain}</div>
                                  </div>
                                )}
                                {e.etudes_de_cas && e.etudes_de_cas.length > 0 && (
                                  <div style={{ marginTop: '12px' }}>
                                    <div style={{ color: '#a78bfa', fontWeight: 600, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>Études de cas ({e.etudes_de_cas.length})</div>
                                    {e.etudes_de_cas.map((cas, idx) => (
                                      <div key={idx} style={{ marginBottom: '10px', padding: '8px 12px', background: 'rgba(139,92,246,0.06)', borderLeft: '2px solid rgba(139,92,246,0.4)', borderRadius: '4px' }}>
                                        <div style={{ fontWeight: 600, color: '#e2e8f0', marginBottom: '4px' }}>{cas.titre}</div>
                                        {cas.situation && <div><strong style={{ color: '#94a3b8' }}>Situation :</strong> {cas.situation}</div>}
                                        {cas.enjeu && <div style={{ marginTop: '3px' }}><strong style={{ color: '#94a3b8' }}>Enjeu :</strong> {cas.enjeu}</div>}
                                        {cas.resolution_attendue && <div style={{ marginTop: '3px' }}><strong style={{ color: '#94a3b8' }}>Résolution :</strong> {cas.resolution_attendue}</div>}
                                        {cas.variantes && <div style={{ marginTop: '3px' }}><strong style={{ color: '#94a3b8' }}>Variantes :</strong> {cas.variantes}</div>}
                                      </div>
                                    ))}
                                  </div>
                                )}
                                {e.pieges_frequents && e.pieges_frequents.length > 0 && (
                                  <div style={{ marginTop: '12px' }}>
                                    <div style={{ color: '#a78bfa', fontWeight: 600, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>Pièges fréquents ({e.pieges_frequents.length})</div>
                                    {e.pieges_frequents.map((p, idx) => (
                                      <div key={idx} style={{ marginBottom: '8px', padding: '8px 12px', background: 'rgba(239,68,68,0.05)', borderLeft: '2px solid rgba(239,68,68,0.35)', borderRadius: '4px' }}>
                                        <div style={{ fontWeight: 600, color: '#e2e8f0', marginBottom: '3px' }}>⚠️ {p.piege}</div>
                                        {p.pourquoi_frequent && <div><strong style={{ color: '#94a3b8' }}>Pourquoi :</strong> {p.pourquoi_frequent}</div>}
                                        {p.comment_eviter && <div style={{ marginTop: '3px' }}><strong style={{ color: '#94a3b8' }}>Comment éviter :</strong> {p.comment_eviter}</div>}
                                      </div>
                                    ))}
                                  </div>
                                )}
                                {e.vocabulaire_metier && Object.keys(e.vocabulaire_metier).length > 0 && (
                                  <div style={{ marginTop: '12px' }}>
                                    <div style={{ color: '#a78bfa', fontWeight: 600, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>Vocabulaire métier ({Object.keys(e.vocabulaire_metier).length})</div>
                                    <dl style={{ margin: 0 }}>
                                      {Object.entries(e.vocabulaire_metier).map(([terme, def], idx) => (
                                        <div key={idx} style={{ marginBottom: '6px' }}>
                                          <dt style={{ display: 'inline', fontWeight: 600, color: '#34d399' }}>{terme}</dt>
                                          <dd style={{ display: 'inline', margin: 0, marginLeft: '6px', color: '#cbd5e1' }}>: {def}</dd>
                                        </div>
                                      ))}
                                    </dl>
                                  </div>
                                )}
                                {e.liens_connexes && e.liens_connexes.length > 0 && (
                                  <div style={{ marginTop: '12px', color: '#64748b', fontSize: '11px', fontStyle: 'italic' }}>
                                    🔗 Liens connexes : {e.liens_connexes.join(', ')}
                                  </div>
                                )}
                              </div>
                            )}
                          </details>
                        ))}
                      </div>
                    </details>
                  )}
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button style={S.btn('ghost')} onClick={() => handleEnrichReac()} disabled={actionLoading}>
                      <Icon name="refresh" /> Relancer (Sonnet)
                    </button>
                    <button style={S.btn('ghost')} onClick={() => handleEnrichReac(HAIKU)} disabled={actionLoading}>
                      <Icon name="bolt" /> Relancer (Haiku)
                    </button>
                  </div>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '10px' }}>
                    Claude va extraire les compétences du REAC et les enrichir une par une
                    (définition pédagogique, études de cas, pièges fréquents, vocabulaire métier, contexte terrain).
                  </p>
                  <p style={{ fontSize: '13px', color: '#475569', marginBottom: '16px' }}>
                    Objectif : passer de ~15 000 mots bruts (REAC) à ~120 000 mots exploitables pour nourrir
                    la génération du programme et éviter la dilution sur les formations longues.
                  </p>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button style={S.btn('primary')} onClick={() => handleEnrichReac()} disabled={actionLoading}>
                      <Icon name="psychology" /> Enrichir (Sonnet)
                    </button>
                    <button style={S.btn('neutral')} onClick={() => handleEnrichReac(HAIKU)} disabled={actionLoading} title="~5x moins cher, qualité légèrement inférieure">
                      <Icon name="bolt" /> Enrichir (Haiku)
                    </button>
                  </div>
                </div>
              )}
            </StepBlock>

            {/* Étape KB en mode Claude Code — réactivée 2026-04-28 :
                prompt borné (1500-2500 mots/compétence) + parsing tolérant à la
                troncature. Permet d'économiser des crédits API quand le compte
                Anthropic est bas. */}
            {DUAL_COLUMN_ENABLED && (
              <StepBlockCC stepIndex={2} currentStep={currentStep} status={job.status} title="Enrichissement KB (local)" icon="psychology">
                <ClaudeCodeStepActions
                  stepKey="kb"
                  stepLabel="Enrichissement Knowledge Base"
                  jobId={selectedJobId}
                  disabled={!job.reac_length || currentStep < 2}
                  disabledReason={!job.reac_length ? 'REAC non téléchargé' : undefined}
                  onExport={handleExportMission}
                  onExecute={handleExecuteMission}
                  onImport={handleImportMission}
                  pendingMission={pendingMissions.kb}
                  generatedVia={job.kb_generated_via}
                />
              </StepBlockCC>
            )}

            {/* ─── KB → Programme global (1 flèche par colonne) ── */}
            <FlowArrowDown />
            {DUAL_COLUMN_ENABLED && <FlowArrowDown />}

            {/* ── Étape 4 : Programme global ── */}
            <StepBlock stepIndex={3} currentStep={currentStep} status={job.status} title="Programme global" icon="auto_stories">
              {job.status === 'global_generating' ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#fbbf24', fontSize: '14px' }}>
                  <Icon name="hourglass_empty" /> Claude génère le programme global… (peut prendre 1-2 min)
                </div>
              ) : job.status === 'global_ready' || job.status === 'global_validated' || currentStep > 3 ? (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                    <span style={{ fontSize: '13px', color: '#94a3b8' }}>Relisez et corrigez si nécessaire avant de valider.</span>
                    <button style={S.btn('neutral')} onClick={() => setGlobalEditing(v => !v)}>
                      <Icon name={globalEditing ? 'visibility' : 'edit'} /> {globalEditing ? 'Prévisualiser' : 'Modifier'}
                    </button>
                  </div>
                  {globalEditing ? (
                    <textarea
                      style={{ ...S.input, height: '400px', resize: 'vertical', fontFamily: 'Fira Code, monospace', fontSize: '13px', lineHeight: '1.5' }}
                      value={globalProgram}
                      onChange={e => setGlobalProgram(e.target.value)}
                    />
                  ) : (
                    <div style={{ background: 'rgba(15,23,42,0.6)', borderRadius: '10px', padding: '16px', maxHeight: '360px', overflowY: 'auto', fontSize: '13px', color: '#cbd5e1', lineHeight: '1.6', whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                      {globalProgram || '(aucun contenu)'}
                    </div>
                  )}
                  <RefinePanel
                    jobId={job.id}
                    contentType="global"
                    currentContent={globalProgram}
                    onRevised={(revised) => setGlobalProgram(revised)}
                  />
                  {!job.global_program_validated && (
                    <div style={{ marginTop: '14px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                      <button style={S.btn('success')} onClick={handleValidateGlobal} disabled={globalValidating || actionLoading}>
                        <Icon name="check_circle" /> {globalValidating ? 'Validation…' : 'Valider le programme'}
                      </button>
                      <button style={S.btn('ghost')} onClick={() => handleGenerateGlobal()} disabled={actionLoading}>
                        <Icon name="refresh" /> Regénérer (Sonnet)
                      </button>
                      <button style={S.btn('ghost')} onClick={() => handleGenerateGlobal(HAIKU)} disabled={actionLoading}>
                        <Icon name="bolt" /> Regénérer (Haiku)
                      </button>
                    </div>
                  )}
                  {job.global_program_validated && currentStep === 3 && (
                    <div style={{ marginTop: '12px' }}>
                      <span style={S.tag('green')}><Icon name="check" /> Programme validé</span>
                    </div>
                  )}
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '16px' }}>
                    {selectedPipelineModel} va générer un programme de formation complet ({job.nb_days} journées) à partir du REAC.
                  </p>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button style={S.btn('primary')} onClick={() => handleGenerateGlobal()} disabled={actionLoading}>
                      <Icon name="auto_stories" /> Générer ({selectedPipelineModel})
                    </button>
                    <button style={S.btn('neutral')} onClick={() => handleGenerateGlobal(HAIKU)} disabled={actionLoading} title="~5x moins cher, qualité légèrement inférieure">
                      <Icon name="bolt" /> Générer (Haiku)
                    </button>
                  </div>
                </div>
              )}
            </StepBlock>

            {/* Pendant Claude Code — étape 4 (Programme global) */}
            {DUAL_COLUMN_ENABLED && (
              <StepBlockCC stepIndex={3} currentStep={currentStep} status={job.status} title="Programme global (local)" icon="auto_stories">
                <ClaudeCodeStepActions
                  stepKey="global"
                  stepLabel="Programme global"
                  jobId={selectedJobId}
                  disabled={currentStep < 3 || job.status === 'kb_building'}
                  disabledReason="En attente de la KB"
                  onExport={handleExportMission}
                  onExecute={handleExecuteMission}
                  onImport={handleImportMission}
                  pendingMission={pendingMissions.global}
                  generatedVia={job.global_program_generated_via}
                />
              </StepBlockCC>
            )}

            {/* ─── Programme global → Programmes journée (1 flèche par colonne) ── */}
            <FlowArrowDown />
            {DUAL_COLUMN_ENABLED && <FlowArrowDown />}

            {/* ── Étape 5 : Programmes journée ── */}
            <StepBlock stepIndex={4} currentStep={currentStep} status={job.status} title={`Programmes journée (${job.nb_days} jours)`} icon="calendar_view_week">
              {job.status === 'daily_splitting' ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#fbbf24', fontSize: '14px' }}>
                  <Icon name="hourglass_empty" /> Découpage en cours… ({job.nb_days} journées de 7h)
                </div>
              ) : job.status === 'daily_ready' || job.status === 'daily_validated' || currentStep > 4 ? (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                    <span style={{ fontSize: '13px', color: '#94a3b8' }}>{dailyPrograms.length} journées générées. Vérifiez et corrigez si nécessaire.</span>
                  </div>

                  {/* Liste des journées */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px' }}>
                    {dailyPrograms.map((day, idx) => (
                      <div key={idx} style={{ background: 'rgba(15,23,42,0.5)', borderRadius: '10px', border: '1px solid rgba(99,102,241,0.15)', overflow: 'hidden' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: dailyEditIdx === idx ? '1px solid rgba(99,102,241,0.2)' : 'none' }}>
                          <div>
                            <span style={{ fontWeight: 600, fontSize: '14px' }}>Jour {day.day_number}</span>
                            <span style={{ color: '#64748b', fontSize: '13px', marginLeft: '10px' }}>{day.title}</span>
                          </div>
                          <div style={{ display: 'flex', gap: '8px' }}>
                            <span style={{ fontSize: '12px', color: '#64748b' }}>{day.sub_parts?.length || 0} modules</span>
                            {dailyEditIdx === idx ? (
                              <>
                                <button style={S.btn('success')} onClick={saveEditDay} title="Sauvegarder">
                                  <Icon name="save" /> Sauvegarder
                                </button>
                                <button style={S.btn('neutral')} onClick={() => setDailyEditIdx(null)}>
                                  <Icon name="close" />
                                </button>
                              </>
                            ) : (
                              <button style={S.btn('neutral')} onClick={() => startEditDay(idx)}>
                                <Icon name="edit" /> Modifier
                              </button>
                            )}
                          </div>
                        </div>

                        {dailyEditIdx === idx ? (
                          <textarea
                            style={{ ...S.input, height: '300px', resize: 'vertical', fontFamily: 'Fira Code, monospace', fontSize: '12px', borderRadius: '0', border: 'none', borderTop: '1px solid rgba(99,102,241,0.15)' }}
                            value={dailyEditText}
                            onChange={e => setDailyEditText(e.target.value)}
                          />
                        ) : (
                          <div style={{ padding: '10px 16px' }}>
                            <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '8px' }}>
                              {day.sub_parts?.map((sp, si) => (
                                <span key={si} style={{ display: 'inline-block', background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.15)', borderRadius: '6px', padding: '2px 8px', margin: '2px', fontSize: '11px', color: '#a78bfa' }}>
                                  {sp.name}
                                </span>
                              ))}
                            </div>
                            <RefinePanel
                              jobId={job.id}
                              contentType="daily"
                              currentContent={JSON.stringify(day, null, 2)}
                              onRevised={(revised) => {
                                try {
                                  const parsed = JSON.parse(revised)
                                  const updated = [...dailyPrograms]
                                  updated[idx] = parsed
                                  setDailyPrograms(updated)
                                } catch {
                                  // si pas du JSON valide, ignorer
                                }
                              }}
                            />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {!job.daily_programs_validated && (
                    <div style={{ display: 'flex', gap: '10px' }}>
                      <button style={S.btn('success')} onClick={handleValidateDaily} disabled={dailyValidating || actionLoading || dailyEditIdx !== null}>
                        <Icon name="check_circle" /> {dailyValidating ? 'Validation…' : 'Valider les journées'}
                      </button>
                      <button style={S.btn('ghost')} onClick={() => handleSplitDaily()} disabled={actionLoading}>
                        <Icon name="refresh" /> Regénérer ({selectedPipelineModel})
                      </button>
                      <button style={S.btn('ghost')} onClick={() => handleSplitDaily(HAIKU)} disabled={actionLoading}>
                        <Icon name="bolt" /> Regénérer (Haiku)
                      </button>
                    </div>
                  )}
                  {job.daily_programs_validated && currentStep === 4 && (
                    <span style={S.tag('green')}><Icon name="check" /> Journées validées</span>
                  )}
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '16px' }}>
                    {selectedPipelineModel} va découper le programme global en <strong style={{ color: '#a78bfa' }}>{job.nb_days} journées</strong> de 7h, chacune avec 6 modules.
                  </p>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button style={S.btn('primary')} onClick={() => handleSplitDaily()} disabled={actionLoading || !job.global_program_validated}>
                      <Icon name="calendar_view_week" /> Découper ({selectedPipelineModel})
                    </button>
                    <button style={S.btn('neutral')} onClick={() => handleSplitDaily(HAIKU)} disabled={actionLoading || !job.global_program_validated} title="~5x moins cher">
                      <Icon name="bolt" /> Découper (Haiku)
                    </button>
                  </div>
                  {!job.global_program_validated && (
                    <div style={{ fontSize: '12px', color: '#f87171', marginTop: '8px' }}>Le programme global doit être validé d'abord.</div>
                  )}
                </div>
              )}
            </StepBlock>

            {/* Pendant Claude Code — étape 5 (Programmes journée) */}
            {DUAL_COLUMN_ENABLED && (
              <StepBlockCC stepIndex={4} currentStep={currentStep} status={job.status} title="Programmes journée (local)" icon="calendar_view_week">
                <ClaudeCodeStepActions
                  stepKey="daily"
                  stepLabel={`Programmes journée (${job.nb_days} jours)`}
                  jobId={selectedJobId}
                  disabled={currentStep < 4 || !job.global_program_validated}
                  disabledReason="En attente du programme global validé"
                  onExport={handleExportMission}
                  onExecute={handleExecuteMission}
                  onImport={handleImportMission}
                  pendingMission={pendingMissions.daily}
                  generatedVia={job.daily_programs_generated_via}
                />
              </StepBlockCC>
            )}

            {/* ─── Programmes journée → Génération cours (1 flèche par colonne) ── */}
            <FlowArrowDown />
            {DUAL_COLUMN_ENABLED && <FlowArrowDown />}

            {/* ── Étape 6 : Génération des cours (texte) + relecture PDF ── */}
            <StepBlock stepIndex={5} currentStep={currentStep} status={job.status} title="Génération des cours (texte)" icon="edit_note">
              {TEXT_AVAILABLE_STATUSES.has(job.status) || ttsResult || (contentFolders.length > 0 && contentFolders.some(f => f.content_status === 'completed')) ? (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: allContentCompleted ? '#34d399' : '#fbbf24', fontSize: '15px', fontWeight: 600, marginBottom: '12px', flexWrap: 'wrap' }}>
                    <Icon name={allContentCompleted ? 'check_circle' : 'hourglass_top'} />
                    <span>
                      {allContentCompleted
                        ? `Textes des ${contentFolders.length} journées générés — prêts pour la relecture`
                        : `Génération : ${contentFolders.filter(f => f.content_status === 'completed').length}/${contentFolders.length || job.nb_days} journées terminées`}
                    </span>
                    {!allContentCompleted && contentFolders.length > 0 && (
                      <button
                        style={{ ...S.btn('neutral'), padding: '5px 11px', fontSize: '12px', marginLeft: 'auto' }}
                        onClick={handleResumeContent}
                        disabled={resumingContent}
                        title="Relance la génération sur les dossiers non completed sans perdre ce qui est déjà en DB (checkpointing)"
                      >
                        <Icon name="refresh" /> {resumingContent ? 'Reprise…' : 'Reprendre'}
                      </button>
                    )}
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '12px' }}>
                    {contentFolders.map(folder => {
                      const pct = Math.round((folder.segments_completed / folder.segments_total) * 100)
                      const isDone = folder.content_status === 'completed'
                      const isError = folder.content_status === 'error'
                      const folderIdentity = formatFolderIdentity(folder)
                      const belongsToSelectedJob = !folder.formation_job_id || folder.formation_job_id === selectedJobId
                      const canUseFolder = isDone && belongsToSelectedJob
                      const continuingAfterText = !!continuingAfterTextFolders[folder.folder_id]
                      const folderAudioBusy = !!folderAudioRunning[folder.folder_id] || audioBusy
                      return (
                        <div key={folder.folder_id} style={{
                          background: 'rgba(15,23,42,0.5)',
                          border: `1px solid ${!belongsToSelectedJob || isError ? 'rgba(239,68,68,0.3)' : isDone ? 'rgba(16,185,129,0.25)' : 'rgba(99,102,241,0.2)'}`,
                          borderRadius: '10px',
                          padding: '12px 14px',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
                            <div style={{ minWidth: 0, flex: '1 1 220px' }}>
                              <div style={{ fontSize: '14px', fontWeight: 600, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                Jour {folder.day_number} — {folder.day_title}
                              </div>
                              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '5px' }}>
                                <span style={{ ...S.tag('violet'), padding: '2px 7px', fontSize: '10.5px' }}>
                                  {formatJobIdentity(job)}
                                </span>
                                <span style={{ ...S.tag(belongsToSelectedJob ? 'violet' : 'red'), padding: '2px 7px', fontSize: '10.5px' }}>
                                  {folderIdentity}
                                </span>
                              </div>
                              <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>
                                {!belongsToSelectedJob
                                  ? <span style={{ color: '#f87171' }}>Ce dossier appartient au job #{folder.formation_job_id}, pas au job sélectionné.</span>
                                  : isDone
                                  ? `✓ ${folder.total_words.toLocaleString('fr-FR')} mots générés`
                                  : isError
                                    ? <span style={{ color: '#f87171' }}>Erreur — {folder.error_message || 'inconnu'}</span>
                                    : `${folder.segments_completed}/${folder.segments_total} segments — ${pct}%`}
                              </div>
	                              {/* Statut révision conformité (étape 6bis).
                                  Trois états distincts :
                                  - En cours : ambre, progression X/Y
                                  - Terminé tout OK : vert, "N segments révisés"
                                  - Terminé avec erreurs : orange, clairement
                                    signalé que N segments n'ont PAS été audités
                                  - Partiel (qq segments en cache) : gris */}
                              {isDone && (() => {
                                const reviewing = !!reviewingFolders[folder.folder_id]
                                const nRev = folder.segments_reviewed || 0
                                const nErr = folder.segments_review_errors || 0
                                const nComp = folder.segments_completed || 0
                                const processed = nRev + nErr
                                if (reviewing) {
                                  return (
                                    <div style={{ fontSize: '12px', color: '#fbbf24', marginTop: '2px' }}>
                                      <Icon name="hourglass_empty" style={{ fontSize: '12px' }} /> Révision en cours — {processed}/{nComp} segments traités
                                      {nErr > 0 && <span style={{ color: '#f87171' }}> · {nErr} en erreur</span>}
                                    </div>
                                  )
                                }
	                                if (processed >= nComp && nComp > 0 && nErr === 0) {
	                                  return (
	                                    <div style={{ fontSize: '12px', color: '#34d399', marginTop: '2px' }}>
	                                      <Icon name="verified" style={{ fontSize: '12px' }} /> Conformité locale révisée ({nRev} segments)
	                                    </div>
	                                  )
	                                }
                                if (processed >= nComp && nComp > 0 && nErr > 0) {
                                  return (
                                    <div style={{ fontSize: '12px', color: '#fb923c', marginTop: '2px' }}>
                                      <Icon name="error_outline" style={{ fontSize: '12px' }} /> Révision partielle — {nRev} audités, <strong>{nErr} en erreur reviewer</strong> (relancer pour retry)
                                    </div>
                                  )
                                }
                                if (nRev > 0 || nErr > 0) {
                                  return (
                                    <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                                      {nRev}/{nComp} segments révisés{nErr > 0 && <span style={{ color: '#f87171' }}> · {nErr} en erreur</span>}
                                    </div>
                                  )
                                }
                                return null
                              })()}
                              {isDone && (
                                <div style={{
                                  fontSize: '12px',
                                  color: (folder.slide_count || 0) > 0 ? '#60a5fa' : '#64748b',
                                  marginTop: '2px',
                                }}>
                                  <Icon name="slideshow" style={{ fontSize: '12px' }} />{' '}
                                  {(folder.slide_count || 0) > 0
                                    ? `Slides anchor-first prêtes (${folder.slide_count})`
                                    : 'Slides anchor-first en attente'}
                                </div>
                              )}
	                            </div>
	                            {/* ─── 2 sous-zones du flux d'une journée ──────────
	                                 1. Texte généré (lecture / téléchargements / rapport)
	                                 2. Conformité locale par morceau (hors micro-éthique)
	                                 Séparées par des FlowArrowDown pour matérialiser
	                                 l'ordre du flux : génération → révision. */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                              {/* ── Zone 1 : Texte généré ──────────────────── */}
                              <div style={{
                                padding: '8px 10px',
                                borderRadius: '8px',
                                background: 'rgba(167, 139, 250, 0.06)',
                                border: '1px solid rgba(167, 139, 250, 0.22)',
                              }}>
                                <div style={{
                                  fontSize: '10px',
                                  fontWeight: 700,
                                  color: '#a78bfa',
                                  textTransform: 'uppercase',
                                  letterSpacing: '0.08em',
                                  marginBottom: '6px',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '5px',
                                }}>
                                  <Icon name="description" style={{ fontSize: '12px' }} /> Texte généré
                                </div>
                                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
                                  <button
                                    style={{ ...S.btn('neutral'), padding: '6px 12px', fontSize: '12px' }}
                                    disabled={!canUseFolder}
                                    onClick={() => setViewingFolder(folder)}
                                    title={canUseFolder ? 'Lire le texte de la journée' : 'En attente de génération ou dossier hors job'}
                                  >
                                    <Icon name="visibility" /> Voir
                                  </button>
                                  <button
                                    style={{ ...S.btn('neutral'), padding: '6px 12px', fontSize: '12px' }}
                                    disabled={!canUseFolder}
                                    onClick={() => window.open(`/generated-slides?job_id=${selectedJobId}&folder_id=${folder.folder_id}`, '_blank')}
                                    title={canUseFolder ? 'Prévisualiser les slides générées depuis le texte' : 'En attente de génération ou dossier hors job'}
                                  >
                                    <Icon name="slideshow" /> Slides
                                  </button>
                                  <button
                                    style={{ ...S.btn('primary'), padding: '6px 12px', fontSize: '12px' }}
                                    disabled={!canUseFolder}
                                    onClick={() => handleDownloadDocx(folder.folder_id, 'pre_review')}
                                    title={canUseFolder
                                      ? 'Télécharger le Word AVANT révision conformité (texte tel que généré)'
                                      : 'En attente de génération ou dossier hors job'}
                                  >
                                    <Icon name="description" /> Word
                                  </button>
                                  {(folder.segments_reviewed || 0) > 0 && (
                                    <button
                                      style={{
                                        ...S.btn('primary'),
                                        padding: '6px 12px',
                                        fontSize: '12px',
                                        background: 'linear-gradient(135deg, #34d399, #10b981)',
                                      }}
                                      disabled={!canUseFolder}
                                      onClick={() => handleDownloadDocx(folder.folder_id, 'current')}
                                      title="Télécharger le Word APRÈS révision conformité (texte révisé, utilisé pour le TTS)"
                                    >
                                      <Icon name="description" /> Word 2
                                    </button>
                                  )}
                                  {(folder.segments_reviewed || 0) > 0 && (
                                    <>
                                      <button
                                        style={{
                                          ...S.btn('ghost'),
                                          padding: '6px 12px',
                                          fontSize: '12px',
                                          borderColor: 'rgba(52, 211, 153, 0.4)',
                                          color: '#34d399',
                                        }}
                                        onClick={() => setReportFolder(folder)}
                                        title="Voir le rapport détaillé de la révision conformité"
                                      >
                                        <Icon name="assessment" /> Rapport conformité
                                      </button>
                                      {(folder.segments_humanized || 0) > 0 && (
                                        <button
                                          style={{
                                            ...S.btn('ghost'),
                                            padding: '6px 12px',
                                            fontSize: '12px',
                                            borderColor: 'rgba(139, 92, 246, 0.4)',
                                            color: '#a78bfa',
                                          }}
                                          onClick={() => setHumanizationReportFolder(folder)}
                                          title="Voir l'ancien rapport humanisation pour un job généré avant la refonte"
                                        >
                                          <Icon name="auto_fix_high" /> Humanisation legacy
                                        </button>
                                      )}
                                    </>
                                  )}
                                </div>
                              </div>

                              {/* ── Zone 2 : Audio + synchro slides à la demande ── */}
                              <div style={{
                                padding: '8px 10px',
                                borderRadius: '8px',
                                background: 'rgba(251, 146, 60, 0.05)',
                                border: '1px solid rgba(251, 146, 60, 0.22)',
                              }}>
                                <div style={{
                                  fontSize: '10px',
                                  fontWeight: 700,
                                  color: '#fb923c',
                                  textTransform: 'uppercase',
                                  letterSpacing: '0.08em',
                                  marginBottom: '6px',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '5px',
                                }}>
                                  <Icon name="record_voice_over" style={{ fontSize: '12px' }} /> Audio journée + synchro slides
                                </div>
                                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
                                  <button
                                    style={{ ...S.btn('ghost'), padding: '6px 12px', fontSize: '12px', borderColor: 'rgba(251,146,60,0.35)', color: '#fb923c' }}
                                    disabled={!canUseFolder || folderAudioBusy}
                                    onClick={() => handleLaunchFolderAudio(folder, 'gtts')}
                                    title={canUseFolder ? 'Génère l’audio Edge TTS de cette journée et synchronise les slides sur ce texte' : 'Texte de journée requis'}
                                  >
                                    <Icon name={folderAudioBusy ? 'hourglass_empty' : 'graphic_eq'} /> {folderAudioBusy ? 'Audio…' : 'Edge + synchro'}
                                  </button>
                                  <button
                                    style={{ ...S.btn('neutral'), padding: '6px 12px', fontSize: '12px', border: '1px dashed #64748b' }}
                                    disabled={!canUseFolder || folderAudioBusy}
                                    onClick={() => handleLaunchFolderAudio(folder, 'mock')}
                                    title="Mode test : MP3 silence, timings et synchro sans coût TTS"
                                  >
                                    <Icon name="science" /> Test silence
                                  </button>
                                  <button
                                    style={{ ...S.btn('success'), padding: '6px 12px', fontSize: '12px' }}
                                    disabled={!canUseFolder || folderAudioBusy}
                                    onClick={() => handleLaunchFolderAudio(folder, 'fish_audio')}
                                    title="Génère l’audio Fish Audio payant de cette journée et synchronise les slides"
                                  >
                                    <Icon name="slideshow" /> Fish + synchro
                                  </button>
                                </div>
                              </div>

                              {/* ── Reprendre depuis une étape ─────────────── */}
                              {(() => {
                                const isOpen = !!resumeExpanded[folder.folder_id]
                                return (
                                  <div style={{
                                    borderRadius: '8px',
                                    border: '1px solid rgba(251, 191, 36, 0.25)',
                                    background: 'rgba(251, 191, 36, 0.04)',
                                    overflow: 'hidden',
                                  }}>
                                    <button
                                      onClick={() => setResumeExpanded(prev => ({ ...prev, [folder.folder_id]: !isOpen }))}
                                      style={{
                                        width: '100%',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '6px',
                                        padding: '7px 10px',
                                        background: 'none',
                                        border: 'none',
                                        cursor: 'pointer',
                                        color: '#fbbf24',
                                        fontSize: '11px',
                                        fontWeight: 700,
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.07em',
                                      }}
                                    >
                                      <Icon name={isOpen ? 'expand_less' : 'chevron_right'} style={{ fontSize: '14px' }} />
                                      Reprendre depuis une étape
                                      {continuingAfterText && (
                                        <span style={{ marginLeft: 'auto', fontWeight: 400, fontSize: '10px', color: '#fbbf24', opacity: 0.8 }}>
                                          <Icon name="hourglass_empty" style={{ fontSize: '11px' }} /> en cours…
                                        </span>
                                      )}
                                    </button>
                                    {isOpen && (
                                      <div style={{ padding: '0 10px 10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                                          <span style={{ fontSize: '11px', color: '#94a3b8' }}>Modèle :</span>
                                          <select
                                            value={continueAfterTextModel}
                                            onChange={e => setContinueAfterTextModel(e.target.value)}
                                            disabled={continuingAfterText}
                                            style={{
                                              padding: '4px 8px',
                                              fontSize: '12px',
                                              background: 'rgba(15, 23, 42, 0.6)',
                                              color: '#cbd5e1',
                                              border: '1px solid rgba(167, 139, 250, 0.3)',
                                              borderRadius: '6px',
                                              cursor: 'pointer',
                                            }}
                                          >
                                            <option value="deepseek-v4-pro">DeepSeek Pro</option>
                                            <option value="deepseek-v4-flash">DeepSeek Flash</option>
                                            <option value="sonnet">Claude Sonnet</option>
                                            <option value="haiku">Claude Haiku</option>
                                          </select>
                                        </div>
                                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                                          {[
                                            { step: 'content', label: 'Génération texte', icon: 'text_fields', title: 'Purge les segments et régénère le texte depuis zéro, puis enchaîne plan JSON, adhérence plan, calibrage budget, micro-éthique, reviews et slides' },
                                            { step: 'review', label: 'Conformité locale', icon: 'rule', title: 'Lance conformité locale par morceau + Word 2 + slides' },
                                            { step: 'slides', label: 'Slides', icon: 'slideshow', title: 'Saute les reviews — supprime le deck slides existant et régénère les slides' },
                                          ].map(({ step, label, icon, title }) => (
                                            <button
                                              key={step}
                                              style={{
                                                ...S.btn('ghost'),
                                                padding: '6px 12px',
                                                fontSize: '12px',
                                                borderColor: continuingAfterText ? 'rgba(251,191,36,0.15)' : 'rgba(251,191,36,0.4)',
                                                color: continuingAfterText ? '#78716c' : '#fbbf24',
                                              }}
                                              disabled={!canUseFolder || continuingAfterText}
                                              onClick={() => handleContinueAfterText(folder.folder_id, null, step)}
                                              title={!canUseFolder ? 'Texte non terminé ou dossier hors job' : title}
                                            >
                                              <Icon name={continuingAfterText ? 'hourglass_empty' : icon} style={{ fontSize: '13px' }} />
                                              {' '}Depuis : {label}
                                            </button>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                )
                              })()}

                              <FlowArrowDown height={18} />

                              {/* ── Zone 3 : Révision conformité ───────────── */}
                              <div style={{
                                padding: '8px 10px',
                                borderRadius: '8px',
                                background: 'rgba(52, 211, 153, 0.05)',
                                border: '1px solid rgba(52, 211, 153, 0.2)',
                              }}>
                                <div style={{
                                  fontSize: '10px',
                                  fontWeight: 700,
                                  color: '#34d399',
                                  textTransform: 'uppercase',
                                  letterSpacing: '0.08em',
                                  marginBottom: '6px',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '5px',
                                }}>
	                                  <Icon name="rule" style={{ fontSize: '12px' }} /> Conformité locale <span style={{ fontWeight: 400, opacity: 0.7, textTransform: 'none', letterSpacing: 'normal' }}>· hors micro-éthique</span>
                                </div>
                                {(() => {
                                  const reviewing = !!reviewingFolders[folder.folder_id]
                                  const nRev = folder.segments_reviewed || 0
                                  const nErr = folder.segments_review_errors || 0
                                  const nComp = folder.segments_completed || 0
                                  const allClean = isDone && nComp > 0 && nRev >= nComp && nErr === 0 && !reviewing
                                  const hasRetryable = nErr > 0
                                  const disabled = !canUseFolder || reviewing || allClean
                                  return (
                                    <button
                                      style={{ ...S.btn('ghost'), padding: '6px 12px', fontSize: '12px' }}
                                      disabled={disabled}
                                      onClick={() => handleReviewFolder(folder.folder_id)}
                                      title={
                                        !belongsToSelectedJob
                                          ? 'Dossier rattaché à un autre job'
                                          : !isDone
                                          ? 'En attente de génération'
                                          : reviewing
                                            ? 'Révision en cours'
                                            : allClean
                                              ? 'Tous les segments ont déjà été révisés avec succès'
                                              : hasRetryable
                                                ? `Relancer la révision — ${nErr} segment(s) en erreur à re-tester`
                                                : `Lancer la révision conformité via API ${selectedPipelineModel}`
                                      }
                                    >
                                      <Icon name={reviewing ? 'hourglass_empty' : (hasRetryable ? 'refresh' : 'rule')} />{' '}
                                      {reviewing
                                        ? 'Révision…'
                                        : hasRetryable
                                          ? `Retenter (${nErr} en erreur)`
                                          : 'Réviser la conformité via API'}
                                    </button>
                                  )
                                })()}
                              </div>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                    {reviewError && (
                      <div style={{ fontSize: '13px', color: '#f87171', marginTop: '4px' }}>
                        Révision : {reviewError}
                      </div>
                    )}
                    {continueAfterTextError && (
                      <div style={{ fontSize: '13px', color: '#f87171', marginTop: '4px' }}>
                        Reprise aval : {continueAfterTextError}
                      </div>
                    )}
                    {continueAfterTextNotice && (
                      <div style={{ fontSize: '13px', color: '#fbbf24', marginTop: '4px' }}>
                        Reprise aval : {continueAfterTextNotice}
                      </div>
                    )}
                    {audioError && (
                      <div style={{ fontSize: '13px', color: '#f87171', marginTop: '4px' }}>
                        Audio journée : {audioError}
                      </div>
                    )}
                    {contentFolders.length === 0 && (
                      <div style={{ fontSize: '13px', color: '#64748b' }}>Chargement de l'état des journées…</div>
                    )}
                  </div>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '8px' }}>
                    Crée <strong style={{ color: '#a78bfa' }}>{job.nb_days} dossiers cours</strong> et génère le texte complet de chaque journée (6 modules × 3 passes avec {selectedPipelineModel}).
                  </p>
                  <p style={{ fontSize: '13px', color: '#475569', marginBottom: '16px' }}>
                    Volume calibré selon les créneaux cours audio. Cette étape ne fait pas encore la synthèse audio — vous pourrez relire les textes et les télécharger en PDF avant de lancer le TTS.
                  </p>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button
                      style={S.btn('success')}
                      onClick={() => handleLaunchTTS()}
                      disabled={launchingTTS || actionLoading || !job.daily_programs_validated}
                    >
                      <Icon name="edit_note" /> {launchingTTS ? 'Lancement…' : `Générer — ${selectedPipelineModel} (${job.nb_days} journées)`}
                    </button>
                    <button
                      style={S.btn('neutral')}
                      onClick={() => handleLaunchTTS(HAIKU)}
                      disabled={launchingTTS || actionLoading || !job.daily_programs_validated}
                      title="~5x moins cher, qualité légèrement inférieure"
                    >
                      <Icon name="bolt" /> {launchingTTS ? 'Lancement…' : `Haiku`}
                    </button>
                  </div>
                  {!job.daily_programs_validated && (
                    <div style={{ fontSize: '12px', color: '#f87171', marginTop: '8px' }}>Les journées doivent être validées d'abord.</div>
                  )}
                </div>
              )}
            </StepBlock>

            {/* Pendant Claude Code — étape 6 (Génération cours texte) + conformité locale */}
            {DUAL_COLUMN_ENABLED && (
              <StepBlockCC stepIndex={5} currentStep={currentStep} status={job.status} title="Génération cours + Révision (local)" icon="edit_note">
                <ClaudeCodeStepActions
                  stepKey="content"
                  stepLabel="Génération des cours (texte)"
                  jobId={selectedJobId}
                  disabled={currentStep < 5 || !job.daily_programs_validated}
                  disabledReason="En attente des programmes journée validés"
                  onExport={handleExportMission}
                  onExecute={handleExecuteMission}
                  onImport={handleImportMission}
                  pendingMission={pendingMissions.content}
                  generatedVia={null}
                />

                <FlowArrowDown height={20} />
                <div>
                  <ClaudeCodeStepActions
                    stepKey="review"
                    stepLabel="Conformité locale par morceau"
                    jobId={selectedJobId}
                    disabled={!TEXT_AVAILABLE_STATUSES.has(job.status)}
                    disabledReason="En attente de la génération texte"
                    onExport={handleExportMission}
                    onExecute={handleExecuteMission}
                    onImport={handleImportMission}
                    pendingMission={pendingMissions.review}
                    generatedVia={null}
                  />
                </div>
              </StepBlockCC>
            )}

            </div>{/* fin du grid dual API / Claude Code */}

          </>
        )}
      </div>

      {viewingFolder && (
        <FolderTextModal
          jobId={selectedJobId}
          folder={viewingFolder}
          onClose={() => setViewingFolder(null)}
        />
      )}

      {reportFolder && (
        <ReviewReportModal
          jobId={selectedJobId}
          folder={reportFolder}
          onClose={() => setReportFolder(null)}
        />
      )}

      {humanizationReportFolder && (
        <ReviewReportModal
          jobId={selectedJobId}
          folder={humanizationReportFolder}
          reportEndpoint="humanization-report"
          onClose={() => setHumanizationReportFolder(null)}
        />
      )}

      {missionModal && (
        <ClaudeCodeMissionModal
          stepKey={missionModal.stepKey}
          mission={missionModal.mission}
          onClose={() => setMissionModal(null)}
          onImport={() => handleImportMission({ stepKey: missionModal.stepKey })}
        />
      )}
    </div>
  )
}

// ─── Modal d'instructions mission Claude Code (Phase 3) ───────────────────────
// Modale logs subprocess `claude` — poll automatique tant que `autoPoll=true`.
function ClaudeCodeLogsModal({ jobId, stepKey, onClose, autoPoll }) {
  const [logs, setLogs] = useState('')
  const [source, setSource] = useState(null)
  const [loading, setLoading] = useState(true)
  const logsRef = useRef(null)

  const fetchLogs = useCallback(async () => {
    try {
      const resp = await fetch(
        apiUrl(`/api/formation/${jobId}/missions/${stepKey}/logs?tail=300`),
        { credentials: 'include' }
      )
      const data = await resp.json()
      if (resp.ok) {
        setLogs(data.logs || '')
        setSource(data.source)
      }
    } catch (e) {
      // silencieux
    } finally {
      setLoading(false)
    }
  }, [jobId, stepKey])

  useEffect(() => {
    fetchLogs()
  }, [fetchLogs])

  // Poll toutes les 3s tant que l'exécution tourne
  useEffect(() => {
    if (!autoPoll) return
    const interval = setInterval(fetchLogs, 3000)
    return () => clearInterval(interval)
  }, [autoPoll, fetchLogs])

  // Auto-scroll vers le bas à chaque update
  useEffect(() => {
    if (logsRef.current) logsRef.current.scrollTop = logsRef.current.scrollHeight
  }, [logs])

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: '24px',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#0f172a', borderRadius: '12px', padding: '20px',
          width: '90vw', maxWidth: '1000px', height: '80vh',
          display: 'flex', flexDirection: 'column',
          border: '1px solid rgba(245,158,11,0.3)', color: '#e2e8f0',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
          <Icon name="terminal" style={{ color: '#fbbf24' }} />
          <h3 style={{ margin: 0, fontSize: '16px', flex: 1 }}>
            Logs Claude Code — {stepKey}
            {autoPoll && <span style={{ fontSize: '11px', color: '#fbbf24', marginLeft: '8px' }}>● live (poll 3s)</span>}
            {source === 'archived' && <span style={{ fontSize: '11px', color: '#94a3b8', marginLeft: '8px' }}>(archivé)</span>}
          </h3>
          <button onClick={fetchLogs} style={{ ...S.btn('ghost'), padding: '4px 10px', fontSize: '12px' }}>
            <Icon name="refresh" /> Refresh
          </button>
          <button onClick={onClose} style={{ ...S.btn('ghost'), padding: '4px 10px', fontSize: '12px' }}>
            <Icon name="close" /> Fermer
          </button>
        </div>
        <pre
          ref={logsRef}
          style={{
            flex: 1,
            margin: 0,
            padding: '12px',
            background: '#020617',
            borderRadius: '8px',
            fontSize: '11px',
            fontFamily: "'Fira Code', 'Menlo', monospace",
            color: '#cbd5e1',
            overflow: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            border: '1px solid rgba(30,41,59,0.8)',
          }}
        >
          {loading ? 'Chargement…' : logs || '(pas encore de logs — execution.log non créé)'}
        </pre>
      </div>
    </div>
  )
}


function ClaudeCodeMissionModal({ stepKey, mission, onClose, onImport }) {
  const [copied, setCopied] = useState(false)
  const command = mission?.command || `claude --model ${mission?.model || 'haiku'}`
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch (e) {
      // ignore
    }
  }
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: '24px',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#1e293b', borderRadius: '14px', padding: '24px',
          maxWidth: '640px', width: '100%', color: '#e2e8f0',
          border: '1px solid rgba(245,158,11,0.3)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
          <Icon name="terminal" style={{ color: '#fbbf24' }} />
          <h3 style={{ margin: 0, fontSize: '18px' }}>Mission Claude Code exportée</h3>
        </div>

        <div style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '6px' }}>Étape</div>
        <div style={{ fontSize: '14px', color: '#e2e8f0', marginBottom: '14px', fontWeight: 600 }}>
          {mission.step_label || stepKey}
        </div>

        <div style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '6px' }}>Fichiers écrits</div>
        <code
          style={{
            display: 'block',
            padding: '10px 12px', background: 'rgba(15,23,42,0.8)', borderRadius: '8px',
            fontSize: '12px', color: '#cbd5e1', marginBottom: '14px', wordBreak: 'break-all',
          }}
        >
          {mission.path}
        </code>

        <div style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '6px' }}>Dans ton terminal</div>
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '10px 12px', background: 'rgba(15,23,42,0.8)', borderRadius: '8px',
            marginBottom: '6px',
          }}
        >
          <code style={{ flex: 1, fontSize: '13px', color: '#a78bfa' }}>$ {command}</code>
          <button
            onClick={handleCopy}
            style={{ ...S.btn('ghost'), padding: '4px 10px', fontSize: '12px' }}
          >
            <Icon name={copied ? 'check' : 'content_copy'} /> {copied ? 'Copié' : 'Copier'}
          </button>
        </div>
        <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '14px' }}>
          Puis dans la session Claude Code :
          <div style={{ marginTop: '4px', color: '#cbd5e1' }}>
            &gt; Exécute la mission décrite dans <code style={{ color: '#a78bfa' }}>{mission.path}/task.md</code>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={S.btn('ghost')}>Plus tard</button>
          <button onClick={onImport} style={S.btn('primary')}>
            <Icon name="file_upload" /> Importer le résultat
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Modal de lecture du texte d'une journée ──────────────────────────────────
function ReviewReportModal({ jobId, folder, onClose, reportEndpoint = 'review-report' }) {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedSegments, setExpandedSegments] = useState({})

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const resp = await fetch(
          apiUrl(`/api/formation/${jobId}/content/${folder.folder_id}/${reportEndpoint}`),
          { credentials: 'include' },
        )
        const data = await resp.json()
        if (cancelled) return
        if (resp.ok && data.report) setReport(data.report)
        else setError(data.error || 'Aucun rapport disponible')
      } catch (e) {
        if (!cancelled) setError('Erreur réseau')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [jobId, folder.folder_id])

  const ruleLabels = {
    '#18': 'Anti-hallucination (chiffres / études non sourcés)',
    '#21': 'Fusion syntaxique hypothétiques',
    '#22': 'Guillemets de discours direct (TTS muet)',
    '#23': 'Posture dialogale',
    '#24': 'Punchlines à isoler',
    '#25': 'Format cours à distance (visuel/interactif)',
    '#26': 'Énumérations mécaniques',
    '#27': 'Registre oral, pas écrit',
    '#DB': 'Diff texte courant / snapshot avant révision',
    '#ERR': 'Erreur reviewer',
  }
  const reportTimestamp = report?.imported_at || report?.persisted_at

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000, padding: '20px',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: '#1e293b', borderRadius: '12px', maxWidth: '900px',
        width: '100%', maxHeight: '90vh', overflow: 'auto',
        border: '1px solid rgba(52, 211, 153, 0.3)',
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 24px', borderBottom: '1px solid rgba(148,163,184,0.15)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px',
        }}>
          <div>
            <div style={{ fontSize: '13px', color: reportEndpoint === 'humanization-report' ? '#a78bfa' : '#34d399', fontWeight: 600, marginBottom: '4px' }}>
              <Icon name={reportEndpoint === 'humanization-report' ? 'auto_fix_high' : 'assessment'} style={{ fontSize: '14px' }} /> {reportEndpoint === 'humanization-report' ? 'Rapport humanisation (intros / transitions / rythme)' : 'Rapport de révision conformité'}
            </div>
            <div style={{ fontSize: '15px', color: '#e2e8f0', fontWeight: 600 }}>
              {folder.folder_name || `Dossier ${folder.folder_id}`}
            </div>
            {reportTimestamp && (
              <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                Rapport généré le {new Date(String(reportTimestamp).replace(' ', 'T')).toLocaleString('fr-FR')}
                {report.generated_via && ` · ${report.generated_via}`}
                {report.via_positional_fallback && ' · résolution positionnelle (ids segment obsolètes)'}
              </div>
            )}
            {report?.is_reconstructed && (
              <div style={{
                fontSize: '11px', color: '#fbbf24', marginTop: '6px',
                padding: '6px 10px', background: 'rgba(251, 191, 36, 0.08)',
                border: '1px solid rgba(251, 191, 36, 0.24)', borderRadius: '4px',
                lineHeight: 1.4,
              }}>
                <Icon name="info" style={{ fontSize: '12px' }} /> <strong>Rapport reconstitué</strong>
                {' — '}{report.reconstruction_note}
              </div>
            )}
            {report?.is_db_fallback && (
              <div style={{
                fontSize: '11px', color: '#a78bfa', marginTop: '6px',
                padding: '6px 10px', background: 'rgba(167, 139, 250, 0.08)',
                border: '1px solid rgba(167, 139, 250, 0.24)', borderRadius: '4px',
                lineHeight: 1.4,
              }}>
                <Icon name="info" style={{ fontSize: '12px' }} /> <strong>Rapport reconstruit depuis la base</strong>
                {' — '}{report.reconstruction_note}
              </div>
            )}
            {reportEndpoint === 'humanization-report' && (
              <div style={{
                fontSize: '11px', color: '#c4b5fd', marginTop: '6px',
                padding: '6px 10px', background: 'rgba(124, 58, 237, 0.10)',
                border: '1px solid rgba(167, 139, 250, 0.28)', borderRadius: '4px',
                lineHeight: 1.4,
              }}>
                <Icon name="info" style={{ fontSize: '12px' }} /> Le diff affiche la version TTS brute avec tags audio.
                Les exports Word, Word 2 et l'aperçu texte retirent automatiquement ces tags.
              </div>
            )}
          </div>
          <button onClick={onClose} style={{ ...S.btn('ghost'), padding: '4px 10px', fontSize: '13px' }}>
            <Icon name="close" />
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: '24px' }}>
          {loading && <div style={{ color: '#94a3b8' }}>Chargement…</div>}
          {error && (
            <div style={{ color: '#f87171', fontSize: '13px' }}>
              <Icon name="error" /> {error}
            </div>
          )}
          {report && (
            <>
              {/* Summary cards */}
              <div style={{
                display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: '12px', marginBottom: '24px',
              }}>
                {[
                  { label: 'Segments audités', value: report.summary.segments_reviewed, color: '#a78bfa' },
                  { label: 'Patches proposés', value: report.summary.patches_proposed, color: '#94a3b8' },
                  { label: 'Patches appliqués', value: report.summary.patches_applied, color: '#34d399' },
                  { label: 'Patches rejetés', value: report.summary.patches_rejected, color: '#fb923c' },
                  { label: 'Segments échoués', value: report.summary.segments_failed, color: '#f87171' },
                ].map(card => (
                  <div key={card.label} style={{
                    padding: '12px', background: 'rgba(15,23,42,0.5)', borderRadius: '8px',
                    border: '1px solid rgba(148,163,184,0.15)',
                  }}>
                    <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>
                      {card.label}
                    </div>
                    <div style={{ fontSize: '24px', color: card.color, fontWeight: 700 }}>
                      {card.value}
                    </div>
                  </div>
                ))}
              </div>

              {/* By rule */}
              <div style={{ marginBottom: '24px' }}>
                <div style={{ fontSize: '13px', color: '#cbd5e1', fontWeight: 600, marginBottom: '10px' }}>
                  Patches par règle violée
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {Object.entries(report.by_rule || {})
                    .sort((a, b) => b[1].proposed - a[1].proposed)
                    .map(([rule, stats]) => (
                      <div key={rule} style={{
                        display: 'grid',
                        gridTemplateColumns: '60px 1fr auto auto auto',
                        gap: '12px', alignItems: 'center',
                        padding: '8px 12px', background: 'rgba(15,23,42,0.4)',
                        borderRadius: '6px', fontSize: '12px',
                      }}>
                        <div style={{ color: '#a78bfa', fontWeight: 600 }}>{rule}</div>
                        <div style={{ color: '#cbd5e1' }}>{ruleLabels[rule] || '—'}</div>
                        <div style={{ color: '#94a3b8' }}>{stats.proposed} proposés</div>
                        <div style={{ color: '#34d399' }}>{stats.applied} appliqués</div>
                        <div style={{ color: '#fb923c' }}>{stats.rejected} rejetés</div>
                      </div>
                    ))}
                </div>
              </div>

              {/* By segment (expandable) */}
              <div>
                <div style={{ fontSize: '13px', color: '#cbd5e1', fontWeight: 600, marginBottom: '10px' }}>
                  Détail par segment ({(report.by_segment || []).length})
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {(report.by_segment || []).map((seg, i) => {
                    const key = `${seg.sub_idx}_${seg.passe}`
                    const expanded = !!expandedSegments[key]
                    return (
                      <div key={key} style={{
                        background: 'rgba(15,23,42,0.4)', borderRadius: '6px',
                        border: '1px solid rgba(148,163,184,0.1)',
                      }}>
                        <div
                          onClick={() => setExpandedSegments({ ...expandedSegments, [key]: !expanded })}
                          style={{
                            padding: '10px 12px', cursor: 'pointer',
                            display: 'grid',
                            gridTemplateColumns: 'auto 1fr auto auto',
                            gap: '12px', alignItems: 'center', fontSize: '12px',
                          }}
                        >
                          <Icon name={expanded ? 'expand_more' : 'chevron_right'} style={{ color: '#94a3b8' }} />
                          <div style={{ color: '#cbd5e1' }}>
                            Sous-partie {seg.sub_idx + 1} · Passe {seg.passe}
                          </div>
                          <div style={{ color: '#34d399' }}>{seg.patches_applied} appliqués</div>
                          <div style={{ color: seg.patches_rejected > 0 ? '#fb923c' : '#475569' }}>
                            {seg.patches_rejected} rejetés
                          </div>
                        </div>
                        {expanded && (
                          <div style={{ padding: '0 12px 12px 32px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            {(seg.patches_detail || []).map((p, j) => (
                              <div key={j} style={{
                                padding: '8px 10px', background: 'rgba(0,0,0,0.2)',
                                borderLeft: `3px solid ${p.status === 'applied' ? '#34d399' : '#fb923c'}`,
                                borderRadius: '4px', fontSize: '11px',
                              }}>
                                <div style={{ display: 'flex', gap: '8px', marginBottom: '4px', alignItems: 'center' }}>
                                  <span style={{ color: '#a78bfa', fontWeight: 600 }}>{p.rule}</span>
                                  <span style={{
                                    color: p.status === 'applied' ? '#34d399' : '#fb923c',
                                    fontSize: '10px', textTransform: 'uppercase',
                                  }}>
                                    {p.status === 'applied' ? '✓ appliqué' : `✗ ${p.reject_reason || 'rejeté'}`}
                                  </span>
                                  {p.reason && (
                                    <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>{p.reason}</span>
                                  )}
                                </div>
                                <div style={{ color: '#f87171', marginBottom: '2px' }}>
                                  <span style={{ color: '#64748b' }}>−</span> {p.original}
                                </div>
                                <div style={{ color: '#34d399' }}>
                                  <span style={{ color: '#64748b' }}>+</span> {p.replacement}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}


function FolderTextModal({ jobId, folder, onClose }) {
  const [text, setText] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const resp = await fetch(
          apiUrl(`/api/formation/${jobId}/content/${folder.folder_id}/text`),
          { credentials: 'include' },
        )
        const data = await resp.json()
        if (cancelled) return
        if (data.text) setText(data.text)
        else setError(data.error || 'Aucun texte disponible')
      } catch (e) {
        if (!cancelled) setError('Erreur réseau')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [jobId, folder.folder_id])

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: '20px',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#0f172a', borderRadius: '16px',
          border: '1px solid rgba(139,92,246,0.25)',
          maxWidth: '900px', width: '100%', maxHeight: '85vh',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}
      >
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid rgba(99,102,241,0.15)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
        }}>
          <div>
            <div style={{ fontSize: '16px', fontWeight: 700, color: '#e2e8f0' }}>
              Jour {folder.day_number} — {folder.day_title}
            </div>
            <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>
              {folder.total_words.toLocaleString('fr-FR')} mots · 6 modules × 3 passes
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              style={{ ...S.btn('primary'), padding: '6px 12px', fontSize: '12px' }}
              onClick={() => window.open(apiUrl(`/api/formation/${jobId}/content/${folder.folder_id}/docx`), '_blank')}
            >
              <Icon name="description" /> Word
            </button>
            <button
              style={{ ...S.btn('neutral'), padding: '6px 12px', fontSize: '12px' }}
              onClick={onClose}
            >
              <Icon name="close" />
            </button>
          </div>
        </div>
        <div style={{
          padding: '20px 24px', overflow: 'auto', flex: 1,
          fontFamily: "'Georgia', serif", fontSize: '14px',
          color: '#cbd5e1', lineHeight: 1.7, whiteSpace: 'pre-wrap',
        }}>
          {loading && <div style={{ color: '#64748b' }}>Chargement du texte…</div>}
          {error && <div style={{ color: '#f87171' }}>{error}</div>}
          {text && text}
        </div>
      </div>
    </div>
  )
}
