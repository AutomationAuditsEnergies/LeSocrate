import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { apiDownload, apiFetch } from '../api'
import { renderSlideTemplate } from '../components/slides/slideTemplateRegistry'
import { formatJobPlanning } from '../formationPlanningDisplay'

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
const QUEUE_TERMINAL_STATUSES = new Set(['completed', 'dead_lettered', 'cancelled', 'missing'])
const DEEPSEEK_PRO_MODEL = 'deepseek-v4-pro'
const DEEPSEEK_FLASH_MODEL = 'deepseek-v4-flash'

function normalizePipelineModel(model) {
  const value = String(model || '').toLowerCase()
  if (value === 'flash' || value.includes('flash')) {
    return DEEPSEEK_FLASH_MODEL
  }
  return DEEPSEEK_PRO_MODEL
}

function hasDetachedQueue(job, autoPilotState) {
  if (!job || !autoPilotState) return false
  if (autoPilotState.status === 'done' || AUDIO_DONE_STATUSES.has(job.status)) return false
  const step = autoPilotState.next_step || autoPilotState.step || job.auto_pilot_step
  if (!step || step === 'done') return false
  return QUEUE_TERMINAL_STATUSES.has(autoPilotState.queue?.status)
}

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
  voice_calibration: 'calibration de la voix IA',
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

// ─── Connecteur visuel entre étapes du pipeline ───────────────────────────────
// Matérialise le flux de données séquentiel, de RNCP jusqu'aux textes et slides.
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
  return normalizePipelineModel(model) === DEEPSEEK_FLASH_MODEL
    ? 'DeepSeek Flash'
    : 'DeepSeek Pro'
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

function parseBackendDate(value) {
  const raw = String(value || '').trim()
  const sqliteUtc = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(raw)
  return new Date(sqliteUtc ? `${raw.replace(' ', 'T')}Z` : raw)
}

function formatEventTime(value) {
  if (!value) return ''
  const date = parseBackendDate(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(11, 16) || String(value)
  return date.toLocaleTimeString('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Paris',
  })
}

function formatJobTimestamp(value) {
  if (!value) return ''
  const date = parseBackendDate(value)
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
          {event.model && (<><span style={{ color: '#64748b' }}>Modèle LLM</span><span style={{ color: '#a78bfa', fontFamily: 'monospace' }}>{pipelineModelLabel(event.model)}</span></>)}
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

function latestContentPhaseKey(events) {
  const phaseToStage = {
    plan_json: 'plan_json',
    body_sections: 'section_generation',
    summaries: 'section_generation',
    late_openings: 'section_generation',
    day_conclusions: 'section_generation',
    draft_artifacts: 'structured_artifacts',
    plan_adherence: 'plan_adherence',
    budget_calibration: 'budget_calibration',
    ethical_micro_review: 'ethical_micro',
    reviewed_scripts: 'structured_artifacts',
  }
  for (const event of [...(events || [])].reverse()) {
    const phase = event?.data?.phase
    if (event?.step === 'content' && event?.event_type === 'content_phase_started' && phaseToStage[phase]) {
      return phaseToStage[phase]
    }
  }
  return null
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
  const activeAutoStep = ['running', 'stopped'].includes(autoPilotState?.status)
    ? ((autoPilotState.lock_stale || autoPilotState.status === 'stopped') && autoPilotState.next_step ? autoPilotState.next_step : autoPilotState.step)
    : null
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
  const completedContentSegments = folders.reduce((sum, f) => sum + (f.segments_completed || 0), 0)
  const allContentCompleted = folders.length > 0 && folders.every(f => f.content_status === 'completed')
  const allReviewProcessed = folders.length > 0 && folders.every(f => {
    const completed = f.segments_completed || 0
    const processed = (f.segments_reviewed || 0) + (f.segments_review_errors || 0)
    return completed > 0 && processed >= completed
  })
  const allReviewed = allReviewProcessed && folders.every(f => (f.segments_review_errors || 0) === 0)
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
  const activeContentPhaseKey = latestContentPhaseKey(events)
  const activeContentStageKey = contentActive && !allContentCompleted
    ? (activeContentPhaseKey || (completedContentSegments > 0 ? 'section_generation' : 'plan_json'))
    : null
  const contentStageActive = key => activeContentStageKey === key
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
      active: contentStageActive('plan_json'),
    },
    {
      key: 'slide_beats',
      title: 'Moments pédagogiques et ancrages visuels',
      detail: 'Exemples, conseils, pièges, comparaisons et templates associés au plan.',
      icon: 'account_tree',
      artifacts: ['content-plan.json'],
      auditMode: 'slide_beats',
      done: allContentCompleted || autoPassed('content'),
      active: contentStageActive('slide_beats'),
    },
    {
      key: 'section_generation',
      title: 'Génération par section — texte V1',
      detail: `${completedFolders}/${expectedFolders || job.nb_days} journée${(expectedFolders || job.nb_days) > 1 ? 's' : ''} générée${completedFolders > 1 ? 's' : ''}, section par section.`,
      icon: 'edit_note',
      artifacts: ['content-plan.json', 'content-draft-sections.json'],
      auditMode: 'section_generation',
      done: allContentCompleted || autoPassed('content'),
      active: contentStageActive('section_generation'),
    },
    {
      key: 'plan_adherence',
      title: 'Adhérence au plan',
      detail: 'Corrige ordre, reprises, conclusions, doublons d’intro et fuites d’horaires avant le budget.',
      icon: 'rule',
      artifacts: ['content-quality-reviews.json', 'content-draft-sections.json'],
      auditMode: 'plan_adherence',
      done: planAdherenceDone,
      active: contentStageActive('plan_adherence'),
    },
    {
      key: 'budget_calibration',
      title: 'Calibrage budget texte',
      detail: 'Alignement des volumes de mots avant toute conformité éthique.',
      icon: 'speed',
      artifacts: ['content-budget-calibration.json', 'content-draft-sections.json', 'content-course-scripts.json'],
      auditMode: 'budget_calibration',
      done: allContentCompleted || autoPassed('content'),
      active: contentStageActive('budget_calibration'),
    },
    {
      key: 'ethical_micro',
      title: 'Micro-conformité éthique',
      detail: 'Contrôle des règles éthiques #1-#16 sur le texte calibré.',
      icon: 'shield',
      artifacts: ['content-ethical-micro-review.json'],
      auditMode: 'ethical_micro',
      done: allContentCompleted || autoPassed('content'),
      active: contentStageActive('ethical_micro'),
    },
    {
      key: 'structured_artifacts',
      title: 'Artefacts structurés',
      detail: 'content-plan, draft-sections, course-scripts et reviewed-scripts.',
      icon: 'data_object',
      artifacts: ['content-plan.json', 'content-draft-sections.json', 'content-course-scripts.json', 'content-reviewed-scripts.json'],
      done: allContentCompleted || autoPassed('content'),
      active: contentStageActive('structured_artifacts'),
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
      key: 'slide_curation',
      title: 'Curation IA des slides',
      detail: 'Analyse le texte final, compare aux anchors du plan, choisit les passages visualisables et liste les templates manquants.',
      icon: 'filter_alt',
      auditMode: 'slides',
      done: slidesDone,
      active: autoActive('slides') && !slidesDone,
    },
    {
      key: 'slides',
      title: 'Slides anchor-first',
      detail: 'Deck généré depuis les décisions de curation, puis persisté par journée.',
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
  slide_curation: ['slides', 'curation', 'template_backlog'],
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
  const [payload, setPayload] = useState({ artifacts: [], reports: [], slideDecks: [], kb: null, rejectedPrograms: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const stageEvents = (events || []).filter(event => eventMatchesPipelineStage(event, stage)).slice(0, 20)
  const folderList = useMemo(
    () => (folders || []).filter(folder => folder.folder_id),
    [folders],
  )
  const artifactNames = useMemo(() => stage.artifacts || [], [stage.artifacts])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      const artifacts = []
      const reports = []
      const slideDecks = []
      let kb = null
      let rejectedPrograms = []

      try {
        if (stage.auditMode === 'kb') {
          try {
            const resp = await apiFetch(`/api/formation/${job.id}/kb`, { credentials: 'include' })
            const data = await resp.json()
            kb = resp.ok ? { entries: data.entries || [], stats: data.stats || {}, error: '' } : { entries: [], stats: {}, error: data.error || 'Knowledge Base indisponible' }
          } catch {
            kb = { entries: [], stats: {}, error: 'Erreur réseau Knowledge Base' }
          }
        }

        if (stage.auditMode === 'global_program') {
          const resp = await apiFetch(
            `/api/formation/${job.id}/rejected-global-programs?limit=30`,
            { credentials: 'include' },
          )
          const data = await resp.json()
          if (!resp.ok) throw new Error(data.error || 'Historique des programmes refusés indisponible')
          rejectedPrograms = data.outputs || []
        }

        if (artifactNames.length > 0) {
          const artifactResults = await Promise.all(
            folderList.flatMap(folder =>
              artifactNames.map(async name => {
                try {
                  const resp = await apiFetch(
                    `/api/formation/${job.id}/content/${folder.folder_id}/artifact/${encodeURIComponent(name)}`,
                    { credentials: 'include' },
                  )
                  const data = await resp.json()
                  return { folder, name, ok: resp.ok, artifact: data.artifact || null, error: data.error || '' }
                } catch {
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
                const resp = await apiFetch(
                  `/api/formation/${job.id}/content/${folder.folder_id}/${stage.reportEndpoint}`,
                  { credentials: 'include' },
                )
                const data = await resp.json()
                return { folder, ok: resp.ok, report: data.report || null, error: data.error || '' }
              } catch {
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
                const resp = await apiFetch(
                  `/api/slides/data?folder_id=${encodeURIComponent(folder.folder_id)}`,
                  { credentials: 'include' },
                )
                const data = await resp.json()
                return {
                  folder,
                  ok: resp.ok && data.status === 'success',
                  deck: data.status === 'success' ? data : null,
                  error: data.message || data.error || '',
                }
              } catch {
                return { folder, ok: false, deck: null, error: 'Erreur réseau' }
              }
            }),
          )
          slideDecks.push(...deckResults)
        }

        if (!cancelled) setPayload({ artifacts, reports, slideDecks, kb, rejectedPrograms })
      } catch {
        if (!cancelled) setError('Impossible de charger le détail de cette étape.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [artifactNames, folderList, job.id, stage.auditMode, stage.key, stage.reportEndpoint])

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
            {stage.auditMode === 'global_program' && (
              <AuditStatCard label="Sorties refusées" value={payload.rejectedPrograms.length} color="#f87171" />
            )}
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
            <KnowledgeBaseAuditView kb={payload.kb} />
          )}
          {!loading && stage.auditMode === 'global_program' && (
            <GlobalProgramAuditView job={job} rejectedPrograms={payload.rejectedPrograms} />
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
    ['Planning réel', formatJobPlanning(job)],
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

function KnowledgeBaseAuditView({ kb }) {
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

function GlobalProgramAuditView({ job, rejectedPrograms = [] }) {
  const text = job.global_program || ''
  if (!text.trim() && rejectedPrograms.length === 0) {
    return (
      <AuditEmptyState
        icon="auto_stories"
        title="Programme global non disponible"
        detail="Aucun programme validé ni aucune sortie refusée n'a encore été enregistré. Les prochaines tentatives bloquées seront conservées ici en entier."
      />
    )
  }

  const attemptByRun = new Map()
  rejectedPrograms.forEach(output => {
    const runKey = output.run_id || `legacy-${output.id}`
    if (!attemptByRun.has(runKey)) attemptByRun.set(runKey, attemptByRun.size + 1)
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {text.trim() && (
        <AuditInfoPanel
          icon="auto_stories"
          title="Programme global retenu"
          detail={`${formatAuditNumber(countAuditWords(text))} mots · validation ${job.global_program_validated ? 'effectuée' : 'en attente'}.`}
        >
          <AuditTextBlock text={text} />
        </AuditInfoPanel>
      )}

      {rejectedPrograms.length > 0 && (
        <AuditInfoPanel
          icon="error"
          title="Programmes refusés et blocages exacts"
          detail={`${rejectedPrograms.length} sortie${rejectedPrograms.length > 1 ? 's' : ''} conservée${rejectedPrograms.length > 1 ? 's' : ''}. Chaque carte montre le motif détecté puis le programme complet envoyé au contrôle.`}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {rejectedPrograms.map((output, index) => {
              const runKey = output.run_id || `legacy-${output.id}`
              const attempt = attemptByRun.get(runKey)
              const phaseLabel = output.phase === 'repair' ? 'correction automatique' : 'première génération'
              const violations = Array.isArray(output.violations) ? output.violations : []
              return (
                <details
                  key={output.id || index}
                  open={index === rejectedPrograms.length - 1}
                  style={{
                    padding: '12px', borderRadius: '9px',
                    background: 'rgba(127,29,29,0.10)',
                    border: '1px solid rgba(248,113,113,0.25)',
                  }}
                >
                  <summary style={{ cursor: 'pointer', color: '#fecaca', fontSize: '13px', fontWeight: 800 }}>
                    Tentative {attempt} · {phaseLabel} · {formatJobTimestamp(output.created_at)}
                  </summary>
                  <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {violations.map((violation, violationIndex) => (
                      <div key={`${violation.label}-${violationIndex}`} style={{ padding: '10px 12px', background: 'rgba(239,68,68,0.08)', borderRadius: '8px' }}>
                        <div style={{ color: '#f87171', fontSize: '12px', fontWeight: 900 }}>
                          Bloqué par : « {violation.label} »
                        </div>
                        {(violation.matches || []).map((match, matchIndex) => (
                          <div key={matchIndex} style={{ marginTop: '7px', color: '#cbd5e1', fontSize: '12px', lineHeight: 1.55 }}>
                            Ligne {match.line || '—'} · terme détecté « {match.match || violation.label} »
                            <div style={{ marginTop: '4px', color: '#fca5a5', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
                              {match.excerpt}
                            </div>
                          </div>
                        ))}
                      </div>
                    ))}
                    <div>
                      <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 800, marginBottom: '6px' }}>
                        Programme complet refusé · {formatAuditNumber(output.character_count)} caractères
                      </div>
                      <AuditTextBlock text={output.output_text} />
                    </div>
                  </div>
                </details>
              )
            })}
          </div>
        </AuditInfoPanel>
      )}
    </div>
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
              <SlideSourcePreviewRow slide={activeSlide} index={activeSlideIndex} slides={slides} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

function getSharedSourceKey(slide) {
  const ref = slide?.source_ref || {}
  return [
    ref.source_block_id ?? 'block',
    ref.word_start ?? 'start',
    ref.word_end ?? 'end',
  ].join(':')
}

function getSlideSourceHighlight(slide, index, slides, sourceText) {
  const words = normalizeWhitespace(sourceText || '').split(/\s+/).filter(Boolean)
  const sourceRef = slide?.source_ref || {}
  const sourceStart = Number(sourceRef.word_start || 0)
  if (words.length === 0) {
    return { start: 0, end: 0, globalStart: sourceStart, globalEnd: sourceStart, sharedCount: 0 }
  }

  const exactStart = Number(sourceRef.highlight_word_start)
  const exactEnd = Number(sourceRef.highlight_word_end)
  if (Number.isFinite(exactStart) && Number.isFinite(exactEnd) && exactEnd > exactStart) {
    const start = Math.max(0, Math.min(words.length, exactStart - sourceStart))
    const end = Math.max(start + 1, Math.min(words.length, exactEnd - sourceStart))
    return {
      start,
      end,
      globalStart: sourceStart + start,
      globalEnd: sourceStart + end,
      sharedCount: 1,
      exact: true,
    }
  }

  const key = getSharedSourceKey(slide)
  const shared = (slides || [])
    .map((candidate, candidateIndex) => ({ slide: candidate, index: candidateIndex }))
    .filter(item => getSharedSourceKey(item.slide) === key)
    .sort((a, b) => a.index - b.index)

  if (shared.length <= 1) {
    return {
      start: 0,
      end: words.length,
      globalStart: sourceStart,
      globalEnd: sourceStart + words.length,
      sharedCount: 1,
      exact: false,
    }
  }

  const sharedIndex = Math.max(0, shared.findIndex(item => item.index === index))
  const start = Math.round(sharedIndex * words.length / shared.length)
  const end = Math.max(start + 1, Math.round((sharedIndex + 1) * words.length / shared.length))

  return {
    start,
    end: Math.min(words.length, end),
    globalStart: sourceStart + start,
    globalEnd: sourceStart + Math.min(words.length, end),
    sharedCount: shared.length,
    exact: false,
  }
}

function HighlightedSourceText({ text, highlight }) {
  const words = normalizeWhitespace(text || '').split(/\s+/).filter(Boolean)
  if (!words.length) return <div>Passage source non disponible.</div>

  const start = Math.max(0, Math.min(words.length, highlight?.start ?? 0))
  const end = Math.max(start, Math.min(words.length, highlight?.end ?? words.length))
  const before = words.slice(0, start).join(' ')
  const selected = words.slice(start, end).join(' ')
  const after = words.slice(end).join(' ')

  return (
    <div>
      {before && <span>{before} </span>}
      {selected && (
        <mark style={{
          background: 'rgba(250,204,21,0.22)',
          color: '#fef3c7',
          border: '1px solid rgba(250,204,21,0.28)',
          borderRadius: '6px',
          padding: '1px 3px',
          boxDecorationBreak: 'clone',
          WebkitBoxDecorationBreak: 'clone',
        }}>
          {selected}
        </mark>
      )}
      {after && <span> {after}</span>}
    </div>
  )
}

function SlideSourcePreviewRow({ slide, index, slides = [] }) {
  const sourceRef = slide.source_ref || {}
  const sourceText = normalizeWhitespace(slide.source_text || '')
  const highlight = getSlideSourceHighlight(slide, index, slides, sourceText)
  const sourceRange = sourceRef.word_start !== undefined || sourceRef.word_end !== undefined
    ? `mots ${sourceRef.word_start ?? '--'}-${sourceRef.word_end ?? '--'}`
    : 'fenêtre source'
  const highlightRange = highlight.sharedCount > 1
    ? `surligné ${highlight.globalStart}-${highlight.globalEnd} · fenêtre partagée par ${highlight.sharedCount} slides`
    : `surligné ${highlight.globalStart}-${highlight.globalEnd}${highlight.exact ? ' · citation exacte' : ''}`

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
          <div style={{
            marginBottom: '10px',
            color: '#facc15',
            fontSize: '11px',
            fontWeight: 800,
          }}>
            Passage correspondant à la slide {index + 1} : {highlightRange}
          </div>
          <HighlightedSourceText text={sourceText} highlight={highlight} />
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
  const frameRef = useRef(null)
  const [frameWidth, setFrameWidth] = useState(720)
  const stageWidth = 1200
  const stageHeight = 675
  const scale = Math.min(1, frameWidth / stageWidth)

  useEffect(() => {
    if (!frameRef.current) return undefined
    const updateWidth = () => {
      const width = frameRef.current?.clientWidth || 720
      setFrameWidth(width)
    }
    updateWidth()
    const observer = new ResizeObserver(updateWidth)
    observer.observe(frameRef.current)
    return () => observer.disconnect()
  }, [])

  return (
    <div style={{ padding: '14px', display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, overflow: 'hidden' }}>
      <div
        ref={frameRef}
        style={{
          width: '100%',
          maxWidth: '720px',
          aspectRatio: '16 / 9',
          flex: '0 1 720px',
          borderRadius: '6px',
          overflow: 'hidden',
          boxShadow: '0 16px 40px rgba(0,0,0,0.35)',
          position: 'relative',
          background: '#020617',
        }}
        className="pipeline-slide-preview-scope"
      >
        <div
          className="pipeline-slide-preview-stage"
          style={{
            width: `${stageWidth}px`,
            height: `${stageHeight}px`,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
            position: 'absolute',
            top: 0,
            left: 0,
          }}
        >
          {renderSlideTemplate(slide)}
        </div>
      </div>
    </div>
  )
}

function BeatFirstIterationPanel({
  folders = [],
  selectedJobId,
  model,
  onModelChange,
  mode,
  onModeChange,
  running,
  error,
  notice,
  onRestart,
}) {
  const readyFolders = folders.filter(folder =>
    folder.content_status === 'completed' &&
    (!folder.formation_job_id || Number(folder.formation_job_id) === Number(selectedJobId))
  )
  const readyCount = readyFolders.length
  const totalCount = folders.length || 0
  const disabled = running || readyCount === 0

  return (
    <div style={{
      ...S.card,
      borderColor: 'rgba(167,139,250,0.28)',
      background: 'rgba(15,23,42,0.72)',
      marginBottom: '24px',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: '14px',
        flexWrap: 'wrap',
        marginBottom: '12px',
      }}>
        <div style={{ minWidth: 0, flex: '1 1 360px' }}>
          <div style={{ ...S.cardTitle, color: '#e2e8f0', marginBottom: '8px' }}>
            <Icon name="restart_alt" /> Itérer depuis le plan verrouillé
          </div>
          <div style={{ color: '#cbd5e1', fontSize: '13px', lineHeight: 1.55, maxWidth: '78ch' }}>
            Relance les journées à partir de la génération texte stable : le plan JSON, les teaching beats et les anchors slides restent utilisés comme cadre. Le mode rapide s'arrête après les slides pour vérifier l'alignement sans attendre l'audio.
          </div>
        </div>
        <span style={{ ...S.tag(readyCount > 0 ? 'violet' : 'amber'), alignSelf: 'flex-start' }}>
          {readyCount}/{totalCount || '—'} journée{readyCount > 1 ? 's' : ''} prête{readyCount > 1 ? 's' : ''}
        </span>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: '10px',
        marginBottom: '14px',
      }}>
        {[
          ['Plan source', 'Plan JSON verrouillé existant'],
          ['Unité générée', 'Section complète, avec teaching beats en contexte'],
          ['Sortie rapide', 'Texte stable et slides régénérées, sans audio'],
        ].map(([label, detail]) => (
          <div key={label} style={{
            padding: '10px 12px',
            borderRadius: '8px',
            border: '1px solid rgba(51,65,85,0.85)',
            background: 'rgba(30,41,59,0.38)',
          }}>
            <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>{label}</div>
            <div style={{ fontSize: '13px', color: '#e2e8f0', lineHeight: 1.4 }}>{detail}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'end', gap: '10px', flexWrap: 'wrap' }}>
        <label style={{ ...S.label, margin: 0, minWidth: '220px' }}>
          Mode
          <select
            style={{ ...S.input, marginTop: '6px' }}
            value={mode}
            onChange={e => onModeChange(e.target.value)}
            disabled={running}
          >
            <option value="fast">Rapide · texte + slides</option>
            <option value="full">Complet · reviews + audio</option>
          </select>
        </label>
        <label style={{ ...S.label, margin: 0, minWidth: '220px' }}>
          Modèle
          <select
            style={{ ...S.input, marginTop: '6px' }}
            value={model}
            onChange={e => onModelChange(e.target.value)}
            disabled={running}
          >
            <option value="deepseek-v4-pro">DeepSeek Pro</option>
            <option value="deepseek-v4-flash">DeepSeek Flash</option>
          </select>
        </label>
        <button
          type="button"
          style={{ ...S.btn('primary'), opacity: disabled ? 0.65 : 1 }}
          disabled={disabled}
          onClick={onRestart}
          title={readyCount > 0 ? 'Relance depuis la génération texte stable pour les journées prêtes' : 'Aucune journée texte prête pour cette reprise'}
        >
          <Icon name={running ? 'hourglass_empty' : 'play_arrow'} />
          {running ? 'Relance en cours…' : mode === 'fast' ? 'Tester texte stable + slides' : 'Relancer complet'}
        </button>
      </div>

      {notice && (
        <div style={{ marginTop: '12px', padding: '10px 12px', borderRadius: '8px', background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.22)', color: '#86efac', fontSize: '13px' }}>
          {notice}
        </div>
      )}
      {error && (
        <div style={{ marginTop: '12px', padding: '10px 12px', borderRadius: '8px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.24)', color: '#fca5a5', fontSize: '13px' }}>
          {error}
        </div>
      )}
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
            <span style={{ color: '#93c5fd' }}>Moment pédagogique : </span>
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
          <span style={{ color: '#38bdf8', fontWeight: 800 }}>Ancrage visuel : </span>
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
  const [showResiduals, setShowResiduals] = useState(false)
  const available = (artifacts || []).filter(item => item.ok && item.artifact)
  const missing = (artifacts || []).filter(item => !item.ok)
  const records = available.flatMap(item =>
    (item.artifact.records || []).map(record => ({ ...record, folder: item.folder, generated_at: item.artifact.generated_at })),
  )
  const residualEntries = records.flatMap(record =>
    (record.lexical_residual_findings || []).map((finding, findingIndex) => ({
      finding,
      findingIndex,
      record,
    })),
  )
  const residualSections = new Set(
    residualEntries.map(entry => `${entry.record.folder?.folder_id || 'folder'}-${entry.record.course_number}-${entry.record.section_label}`),
  ).size
  const issueRecords = records.filter(record =>
    record.status !== 'clean' || (record.patches_detail || []).length > 0 || record.error,
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {available.length > 0 && (
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          gap: '12px', flexWrap: 'wrap',
        }}>
          <div style={{ color: '#94a3b8', fontSize: '12px', lineHeight: 1.5 }}>
            {records.length} section(s) auditées · {available.length} artefact(s) chargé(s)
          </div>
          <button
            type="button"
            onClick={() => setShowResiduals(value => !value)}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '7px',
              padding: '7px 10px', borderRadius: '8px',
              border: `1px solid ${residualEntries.length ? 'rgba(251,146,60,0.45)' : 'rgba(52,211,153,0.35)'}`,
              background: residualEntries.length ? 'rgba(251,146,60,0.12)' : 'rgba(16,185,129,0.10)',
              color: residualEntries.length ? '#fdba74' : '#6ee7b7',
              fontSize: '12px', fontWeight: 800, cursor: 'pointer',
            }}
          >
            <Icon name={residualEntries.length ? 'warning' : 'verified'} />
            Résidus éthiques : {residualEntries.length}
          </button>
        </div>
      )}
      {showResiduals && residualEntries.length > 0 && (
        <div style={{
          border: '1px solid rgba(251,146,60,0.24)', borderRadius: '10px',
          background: 'rgba(251,146,60,0.07)', overflow: 'hidden',
        }}>
          <div style={{
            padding: '10px 12px', color: '#fed7aa', fontSize: '12px',
            borderBottom: '1px solid rgba(251,146,60,0.16)', fontWeight: 800,
          }}>
            {residualEntries.length} passage(s) non corrigé(s) · {residualSections} section(s)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '10px 12px' }}>
            {residualEntries.map(({ finding, record, findingIndex }, index) => (
              <div key={`${record.folder?.folder_id}-${record.course_number}-${record.section_label}-${findingIndex}-${index}`} style={{
                padding: '10px', border: '1px solid rgba(251,146,60,0.14)',
                borderRadius: '8px', background: 'rgba(15,23,42,0.42)',
              }}>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '6px' }}>
                  <span style={{ color: '#fdba74', fontWeight: 900, fontSize: '12px' }}>{finding.rule || `#${finding.rule_id || '?'}`}</span>
                  <span style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '12px' }}>{finding.match || finding.term || 'terme détecté'}</span>
                  <span style={{ color: '#94a3b8', fontSize: '12px' }}>
                    {folderDisplayName(record.folder)} · Cours {record.course_number} · {record.section_label}
                  </span>
                </div>
                <div style={{ color: '#cbd5e1', fontSize: '12px', lineHeight: 1.55 }}>
                  {finding.excerpt || 'Extrait indisponible'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
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
        <span style={{ color: '#93c5fd' }}>Moment pédagogique : </span>
        {beat.role || anchor.visual_goal || 'Moment pédagogique prévu'}
      </div>
      {anchor.visual_goal && (
        <div style={{ color: '#94a3b8', fontSize: '11px', lineHeight: 1.45, marginTop: '6px' }}>
          <span style={{ color: '#38bdf8', fontWeight: 800 }}>Ancrage visuel : </span>
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
        <strong>Lecture de l'étape 7.</strong> Cette vue isole les moments pédagogiques avec ancrage visuel prévus par le plan : templates, objectifs visuels, exigences orales et champs suggérés.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
        <AuditStatCard label="Journées" value={days.length} color="#a78bfa" />
        <AuditStatCard label="Thèmes" value={totals.courses} color="#38bdf8" />
        <AuditStatCard label="Sections avec slides" value={totals.sections} color="#34d399" />
        <AuditStatCard label="Ancrages visuels" value={totals.beats} color="#f59e0b" />
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
              <span style={{ color: '#93c5fd' }}>Moment pédagogique : </span>
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
        <SlideBeatInfoBlock title="Ancrage visuel :" text={anchor.visual_goal || beat.visual_goal} color="#38bdf8" />
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
            <span>{formatEventTime(event.created_at) || '—'}</span>
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
          <span>{formatJobPlanning(job)}</span>
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
      const resp = await apiFetch('/api/formation/init', {
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
    } catch {
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

  const handleRefine = async (model) => {
    if (!instruction.trim()) return
    setLoading(true)
    setError('')
    try {
      const resp = await apiFetch(`/api/formation/${jobId}/refine`, {
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
    } catch {
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
              onClick={() => handleRefine(DEEPSEEK_PRO_MODEL)}
              disabled={loading || !instruction.trim()}
            >
              {loading ? <Icon name="hourglass_empty" /> : <Icon name="auto_fix_high" />}
              {loading ? 'Modification…' : 'Modifier (DeepSeek Pro)'}
            </button>
            <button
              style={{ ...S.btn('neutral'), fontSize: '12px', padding: '6px 14px' }}
              onClick={() => handleRefine(DEEPSEEK_FLASH_MODEL)}
              disabled={loading || !instruction.trim()}
              title="Mode rapide"
            >
              <Icon name="bolt" /> Modifier (DeepSeek Flash)
            </button>
          </div>
        </div>
      )}
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
  const [slide2Folder, setSlide2Folder] = useState(null)      // audit texte ↔ slides
  const [reportFolder, setReportFolder] = useState(null)           // rapport conformité stricte
  const [humanizationReportFolder, setHumanizationReportFolder] = useState(null)  // ancien rapport humanisation, affiché seulement pour les jobs legacy

  // Audio à la demande par journée
  const [audioError, setAudioError] = useState('')
  const [audioNotice, setAudioNotice] = useState('')
  const [folderAudioRunning, setFolderAudioRunning] = useState({})
  const [continuingAfterTextFolders, setContinuingAfterTextFolders] = useState({})
  const [continueAfterTextError, setContinueAfterTextError] = useState('')
  const [continueAfterTextNotice, setContinueAfterTextNotice] = useState('')
  const [slideIterationFolders, setSlideIterationFolders] = useState({})
  const [slideIterationError, setSlideIterationError] = useState('')
  const [slideIterationNotice, setSlideIterationNotice] = useState('')
  const [resumeExpanded, setResumeExpanded] = useState({})
  // Modèle utilisé pour la relance aval. Initialisé sur l'auto_pilot_model du
  // job courant si présent, sinon DeepSeek Pro (cas des jobs historiques sans
  // colonne persistée).
  const [continueAfterTextModel, setContinueAfterTextModel] = useState(DEEPSEEK_PRO_MODEL)
  useEffect(() => {
    if (job?.auto_pilot_model) {
      setContinueAfterTextModel(normalizePipelineModel(job.auto_pilot_model))
    }
  }, [job?.auto_pilot_model])
  const [pipelineDiagnostic, setPipelineDiagnostic] = useState(null)
  const [beatFirstIterationRunning, setBeatFirstIterationRunning] = useState(false)
  const [beatFirstIterationError, setBeatFirstIterationError] = useState('')
  const [beatFirstIterationNotice, setBeatFirstIterationNotice] = useState('')
  const [beatFirstIterationMode, setBeatFirstIterationMode] = useState('fast')

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
      const resp = await apiFetch('/api/formation/list', { credentials: 'include' })
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
      const resp = await apiFetch(`/api/formation/${id}`, { credentials: 'include' })
      const data = await resp.json()
      if (selectedJobIdRef.current && Number(selectedJobIdRef.current) !== Number(id)) return
      if (data.id && Number(data.id) === Number(id)) {
        setJob(data)
        // Synchroniser les états locaux si pas en train d'éditer
        if (!globalEditing) setGlobalProgram(data.global_program || '')
        if (dailyEditIdx === null && data.daily_programs) {
          try {
            setDailyPrograms(JSON.parse(data.daily_programs))
          } catch {
            // Conserver le dernier programme valide si le payload est incomplet.
          }
        }
      }
    } catch (e) { console.error(e) }
  }, [globalEditing, dailyEditIdx])

  // ─── Fetch knowledge base (Couche 1) ──────────────────────────────────────
  const fetchKb = useCallback(async (id) => {
    try {
      const resp = await apiFetch(`/api/formation/${id}/kb`, { credentials: 'include' })
      const data = await resp.json()
      if (data.stats) setKb({ entries: data.entries || [], stats: data.stats })
    } catch (e) { console.error(e) }
  }, [])

  // ─── Auto-pilot : statut + polling pendant l'orchestration auto ────────────
  const [autoPilotState, setAutoPilotState] = useState(null)  // {step, status, error?, ...} ou null
  const [stopAutoPilotBusy, setStopAutoPilotBusy] = useState(false)

  const fetchAutoPilotStatus = useCallback(async (jobId) => {
    if (!jobId) return
    try {
      const resp = await apiFetch(`/api/formation/${jobId}/run-auto/status`, { credentials: 'include' })
      const data = await resp.json()
      setAutoPilotState(data && data.status && data.status !== 'idle' ? data : null)
    } catch {
      // Le prochain cycle de polling réessaiera.
    }
  }, [])

  const stopAutoPilot = useCallback(async () => {
    if (!selectedJobId || stopAutoPilotBusy) return
    const ok = window.confirm(`Stopper l'auto-pilot du job #${selectedJobId} ?`)
    if (!ok) return
    setStopAutoPilotBusy(true)
    try {
      const resp = await apiFetch(`/api/formation/${selectedJobId}/run-auto/stop`, {
        method: 'POST',
        credentials: 'include',
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) {
        alert(data.error || "Impossible de stopper l'auto-pilot")
        return
      }
      setAutoPilotState(null)
      await fetchAutoPilotStatus(selectedJobId)
      await fetchJob(selectedJobId)
      await fetchJobs()
    } catch {
      alert("Erreur réseau lors de l'arrêt de l'auto-pilot")
    } finally {
      setStopAutoPilotBusy(false)
    }
  }, [fetchAutoPilotStatus, fetchJob, fetchJobs, selectedJobId, stopAutoPilotBusy])

  const fetchPipelineDiagnostic = useCallback(async (jobId) => {
    if (!jobId) return
    try {
      const resp = await apiFetch(`/api/formation/${jobId}/diagnostic?events_limit=80`, { credentials: 'include' })
      const data = await resp.json()
      if (selectedJobIdRef.current && Number(selectedJobIdRef.current) !== Number(jobId)) return
      if (resp.ok) {
        setPipelineDiagnostic(data)
      }
    } catch {
      // Diagnostic non bloquant : le prochain polling réessaiera.
    }
  }, [])

  // Poll l'auto-pilot toutes les 5s tant qu'il tourne
  useEffect(() => {
    if (!selectedJobId) return
    fetchAutoPilotStatus(selectedJobId)
    fetchPipelineDiagnostic(selectedJobId)
    const interval = setInterval(() => {
      fetchAutoPilotStatus(selectedJobId)
      fetchPipelineDiagnostic(selectedJobId)
    }, 5000)
    return () => clearInterval(interval)
  }, [selectedJobId, fetchAutoPilotStatus, fetchPipelineDiagnostic])

  // ─── Fetch module lié au job courant ──────────────────────────────────────
  const fetchLinkedModule = useCallback(async (jobId) => {
    if (!jobId) { setLinkedModule(null); return }
    try {
      const resp = await apiFetch('/api/hr/formation-modules', { credentials: 'include' })
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
        const resp = await apiFetch(`/api/formation/${selectedJobId}`, { credentials: 'include' })
        const data = await resp.json()
        if (data.id) {
          setJob(data)
          if (!globalEditing) setGlobalProgram(data.global_program || '')
          if (dailyEditIdx === null && data.daily_programs) {
            try {
              setDailyPrograms(JSON.parse(data.daily_programs))
            } catch {
              // Conserver le dernier programme valide si le payload est incomplet.
            }
          }
          // Rafraîchir la KB pendant l'enrichissement
          if (data.status === 'kb_building' || data.status === 'kb_ready') {
            fetchKb(selectedJobId)
          }
          // Rafraîchir le diagnostic pendant la synthèse audio pour que la
          // barre de progression temps réel par dossier reste vivante (events
          // audio_progress se mettent à jour seulement si on re-fetch).
          if (AUDIO_ACTIVE_STATUSES.has(data.status)) {
            fetchPipelineDiagnostic(selectedJobId)
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
  }, [
    dailyEditIdx,
    fetchJob,
    fetchKb,
    fetchLinkedModule,
    fetchPipelineDiagnostic,
    globalEditing,
    selectedJobId,
  ])

  // Relancer le polling si le statut devient "en cours".
  const pollingJobId = job?.id
  const pollingJobStatus = job?.status
  useEffect(() => {
    if (!pollingJobId || !POLLING_STATUSES.has(pollingJobStatus)) return
    clearInterval(pollingRef.current)
    const interval = setInterval(() => fetchJob(pollingJobId), 3000)
    pollingRef.current = interval
    return () => clearInterval(interval)
  }, [fetchJob, pollingJobId, pollingJobStatus])

  // ─── Actions API ──────────────────────────────────────────────────────────
  const doAction = async (path, body = {}) => {
    setActionLoading(true)
    setActionError('')
    try {
      const resp = await apiFetch(`/api/formation/${selectedJobId}/${path}`, {
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
    } catch {
      setActionError('Erreur réseau')
    } finally {
      setActionLoading(false)
    }
  }

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
      const resp = await apiFetch(`/api/formation/${jobId}/content`, { credentials: 'include' })
      const data = await resp.json()
      if (selectedJobIdRef.current && Number(selectedJobIdRef.current) !== Number(jobId)) return
      if (data.folders) setContentFolders(data.folders)
      else setContentFolders([])
    } catch (error) {
      console.error('fetchContentFolders:', error)
      setContentFolders([])
    }
  }, [])

  const allContentCompleted = contentFolders.length > 0 &&
    contentFolders.every(folder => folder.content_status === 'completed')
  const hasIncompleteContent = contentFolders.some(
    folder => folder.content_status && folder.content_status !== 'completed',
  )
  const selectedJobStatus = job?.status
  const dailyProgramsValidated = Boolean(job?.daily_programs_validated)

  // Rehydrate les dossiers dès que le job peut avoir du texte. Important :
  // après découplage audio, un job texte prêt est `text_ready`, donc un refresh
  // ne doit pas retomber sur l'écran "Générer".
  useEffect(() => {
    if (!selectedJobStatus || !selectedJobId) return
    const shouldLoadContent =
      TEXT_AVAILABLE_STATUSES.has(selectedJobStatus) ||
      dailyProgramsValidated ||
      contentFolders.length > 0
    if (!shouldLoadContent) return

    fetchContentFolders(selectedJobId)
    const shouldPollContent =
      CONTENT_POLLING_STATUSES.has(selectedJobStatus) ||
      hasIncompleteContent
    if (!shouldPollContent) return

    const interval = setInterval(() => {
      if (!allContentCompleted) fetchContentFolders(selectedJobId)
    }, 3000)
    return () => clearInterval(interval)
  }, [
    allContentCompleted,
    contentFolders.length,
    dailyProgramsValidated,
    fetchContentFolders,
    hasIncompleteContent,
    selectedJobId,
    selectedJobStatus,
  ])

  const handleDownloadDocx = async (folderId, version = 'current') => {
    setActionError('')
    try {
      await apiDownload(
        `/api/formation/${selectedJobId}/content/${folderId}/docx?version=${version}`,
        `formation-${selectedJobId}-jour-${folderId}.docx`,
      )
    } catch (error) {
      setActionError(error.message || 'Téléchargement Word impossible')
    }
  }

  // ─── Étape 5 — reprise de la génération texte après crash backend ──────────
  const [resumingContent, setResumingContent] = useState(false)
  const handleResumeContent = async () => {
    setResumingContent(true)
    setActionError('')
    try {
      const resp = await apiFetch(`/api/formation/${selectedJobId}/resume-content`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({}),
      })
      const data = await resp.json()
      if (data.error) setActionError(data.error)
      else await fetchContentFolders(selectedJobId)
    } catch {
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
      const resp = await apiFetch(
        `/api/formation/${selectedJobId}/content/${folderId}/continue-after-text`,
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
      await fetchPipelineDiagnostic(selectedJobId)
    } catch {
      setContinueAfterTextError('Erreur réseau')
      setContinuingAfterTextFolders(prev => { const n = { ...prev }; delete n[folderId]; return n })
    }
  }

  const handleRegenerateSlidesOnly = async (folder) => {
    if (!folder?.folder_id) return
    const folderId = folder.folder_id
    setSlideIterationError('')
    setSlideIterationNotice('')
    setSlideIterationFolders(prev => ({ ...prev, [folderId]: true }))
    try {
      const resp = await apiFetch('/api/slides/generate-from-script', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          folder_id: folderId,
          job_id: selectedJobId,
          platform_id: folder.platform_id || job?.platform_id || null,
          max_slides: 60,
          pace: 'normal',
          model: continueAfterTextModel || normalizePipelineModel(job?.auto_pilot_model),
        }),
      })
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || data.status !== 'success') {
        setSlideIterationError(data.message || data.error || `Erreur ${resp.status}`)
        return
      }
      setSlideIterationNotice(
        `Curation + slides régénérées pour F${folderId} (${data.slides_count || 0} slides).`,
      )
      await fetchContentFolders(selectedJobId)
      await fetchPipelineDiagnostic(selectedJobId)
    } catch {
      setSlideIterationError('Erreur réseau')
    } finally {
      setSlideIterationFolders(prev => {
        const next = { ...prev }
        delete next[folderId]
        return next
      })
    }
  }

  // ─── Étape 6bis — révision conformité via DeepSeek ────────────────────────
  // Le backend audite segment par segment. Côté front, on suit l'avancement
  // via `segments_reviewed` / `segments_completed`.
  const [reviewingFolders, setReviewingFolders] = useState({})  // { [folderId]: true }
  const [reviewError, setReviewError] = useState('')

  const handleReviewFolder = async (folderId) => {
    setReviewError('')
    setReviewingFolders(prev => ({ ...prev, [folderId]: true }))
    try {
      const resp = await apiFetch(
        `/api/formation/${selectedJobId}/content/${folderId}/review`,
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
    } catch {
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

  const autoPilotStatus = autoPilotState?.status
  useEffect(() => {
    if (!selectedJobId || !['running', 'starting'].includes(autoPilotStatus)) return
    fetchContentFolders(selectedJobId)
    const interval = setInterval(() => {
      fetchContentFolders(selectedJobId)
    }, 5000)
    return () => clearInterval(interval)
  }, [autoPilotStatus, fetchContentFolders, selectedJobId])

  useEffect(() => {
    const ids = Object.keys(continuingAfterTextFolders)
    if (ids.length === 0 || !selectedJobId) return
    const interval = setInterval(() => {
      fetchJob(selectedJobId)
      fetchContentFolders(selectedJobId)
      fetchPipelineDiagnostic(selectedJobId)
    }, 4000)
    return () => clearInterval(interval)
  }, [
    continuingAfterTextFolders,
    fetchContentFolders,
    fetchJob,
    fetchPipelineDiagnostic,
    selectedJobId,
  ])

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

  const handleRestartBeatFirstIteration = async () => {
    const foldersToRestart = contentFolders.filter(folder =>
      folder.content_status === 'completed' &&
      (!folder.formation_job_id || Number(folder.formation_job_id) === Number(selectedJobId))
    )
    if (foldersToRestart.length === 0) {
      setBeatFirstIterationError('Aucune journée texte prête pour cette reprise.')
      return
    }
    setBeatFirstIterationRunning(true)
    setBeatFirstIterationError('')
    setBeatFirstIterationNotice('')
    setPipelineDiagnostic(null)
    const chosenModel = continueAfterTextModel || normalizePipelineModel(job?.auto_pilot_model)
    const fastMode = beatFirstIterationMode !== 'full'
    const startedFolders = []
    try {
      for (const folder of foldersToRestart) {
        setContinuingAfterTextFolders(prev => ({ ...prev, [folder.folder_id]: true }))
        const resp = await apiFetch(
          `/api/formation/${selectedJobId}/content/${folder.folder_id}/continue-after-text`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
              model: chosenModel,
              max_slides: 60,
              pace: 'normal',
              from_step: 'content',
              iteration_mode: fastMode ? 'fast' : 'full',
              skip_audio: fastMode,
              skip_post_content_review: fastMode,
            }),
          },
        )
        const data = await resp.json().catch(() => ({}))
        if (!resp.ok || data.error) {
          setContinuingAfterTextFolders(prev => {
            const next = { ...prev }
            delete next[folder.folder_id]
            return next
          })
          throw new Error(data.error || `Erreur ${resp.status} sur Jour ${folder.day_number || folder.folder_id}`)
        }
        startedFolders.push(data.folder_id || folder.folder_id)
      }
      setBeatFirstIterationNotice(
        `${fastMode ? 'Itération rapide' : 'Relance complète'} lancée pour ${startedFolders.length} journée${startedFolders.length > 1 ? 's' : ''}. Le suivi se fait dans les cartes journées et le diagnostic pipeline.`,
      )
      await fetchJob(selectedJobId)
      await fetchContentFolders(selectedJobId)
      await fetchPipelineDiagnostic(selectedJobId)
    } catch (e) {
      setBeatFirstIterationError(e?.message || 'Erreur réseau pendant la relance beat-first')
    } finally {
      setBeatFirstIterationRunning(false)
    }
  }

  const handleLaunchFolderAudio = async (folder, ttsMode = 'gtts') => {
    if (!folder?.folder_id) return
    setAudioError('')
    setAudioNotice('')
    setFolderAudioRunning(prev => ({
      ...prev,
      [folder.folder_id]: { status: 'submitting', ttsMode },
    }))
    let accepted = false
    try {
      const resp = await apiFetch(
        `/api/hr/cours-folders/${folder.folder_id}/generate-playlist`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            voice_type: ttsMode,
            force_all: true,
            sync_slides: true,
            auto_generate_slides: true,
            include_breaks: true,
          }),
        },
      )
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok || data.error) {
        setAudioError(data.error || `Erreur ${resp.status}`)
      } else {
        accepted = true
        setFolderAudioRunning(prev => ({
          ...prev,
          [folder.folder_id]: {
            status: data.queue_status || 'queued',
            workItemId: data.work_item_id,
            ttsMode,
          },
        }))
        setAudioNotice(`Audio du jour ${folder.day_number || ''} mis en file durable.`.trim())
      }
    } catch {
      setAudioError('Erreur réseau audio')
    } finally {
      if (!accepted) {
        setFolderAudioRunning(prev => {
          const next = { ...prev }
          delete next[folder.folder_id]
          return next
        })
      }
    }
  }

  const audioFolderPollKey = Object.keys(folderAudioRunning).sort().join(',')
  useEffect(() => {
    const folderIds = audioFolderPollKey
      .split(',')
      .map(value => Number(value))
      .filter(Boolean)
    if (!folderIds.length) return undefined

    let cancelled = false
    const poll = async () => {
      await Promise.all(folderIds.map(async folderId => {
        try {
          const resp = await apiFetch(`/api/hr/cours-folders/${folderId}/playlist-status`, {
            credentials: 'include',
          })
          const data = await resp.json().catch(() => ({}))
          if (cancelled || !resp.ok || !data.success) return

          if (data.status === 'completed') {
            setFolderAudioRunning(prev => {
              const next = { ...prev }
              delete next[folderId]
              return next
            })
            setAudioNotice(`Audio synchronisé terminé pour le dossier F${folderId}.`)
            if (selectedJobId) {
              await Promise.all([
                fetchJob(selectedJobId),
                fetchContentFolders(selectedJobId),
                fetchLinkedModule(selectedJobId),
                fetchPipelineDiagnostic(selectedJobId),
              ])
            }
            return
          }

          if (data.status === 'error') {
            setFolderAudioRunning(prev => {
              const next = { ...prev }
              delete next[folderId]
              return next
            })
            setAudioError(data.message || data.error || `Échec de la génération audio F${folderId}`)
            return
          }

          setFolderAudioRunning(prev => ({
            ...prev,
            [folderId]: {
              ...(prev[folderId] || {}),
              status: data.status || data.queue_status || 'running',
              message: data.message,
            },
          }))
        } catch {
          // Une panne de polling ne change pas l'état durable du worker.
        }
      }))
    }

    poll()
    const interval = window.setInterval(poll, 2500)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [
    audioFolderPollKey,
    fetchContentFolders,
    fetchJob,
    fetchLinkedModule,
    fetchPipelineDiagnostic,
    selectedJobId,
  ])

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
    setSlide2Folder(null)
    setReportFolder(null)
    setTtsResult(null)
    setAudioError('')
    setAudioNotice('')
    setFolderAudioRunning({})
    setContinueAfterTextError('')
    setContinueAfterTextNotice('')
    setContinuingAfterTextFolders({})
    setReviewingFolders({})
    setReviewError('')
    setPipelineDiagnostic(null)
    setBeatFirstIterationRunning(false)
    setBeatFirstIterationError('')
    setBeatFirstIterationNotice('')
    setAutoPilotState(null)
    setLinkedModule(null)
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
  const detachedQueue = hasDetachedQueue(job, autoPilotState)
  const autoPilotIsActive = ['running', 'starting'].includes(autoPilotState?.status)
  const displayedJobStatus = autoPilotIsActive && ['error', 'audio_error'].includes(job?.status)
    ? 'running'
    : job?.status
  const showJobError = Boolean(job?.error_message) && !autoPilotIsActive
  const canStopAutoPilot = !detachedQueue && Boolean(
    (job?.auto_pilot_enabled && job?.auto_pilot_step !== 'done') ||
    ['running', 'starting', 'error'].includes(autoPilotState?.status)
  )
  const interruptedTaskType = autoPilotState?.queue?.task_type
  const interruptedStep = interruptedTaskType === 'voice_reference_calibration'
    ? 'voice_calibration'
    : (autoPilotState?.step || autoPilotState?.next_step || job?.auto_pilot_step || '?')
  const interruptedStepLabel = AUTO_PILOT_STEP_LABELS[interruptedStep]
    || String(interruptedStep).replace(/_/g, ' ')
  const interruptedBeforeReac = interruptedStep === 'voice_calibration'

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
                    RNCP {job.rncp_code} · {formatJobPlanning(job)}
                    {job.reac_length ? <span style={{ color: '#34d399', marginLeft: 6 }}>✓ REAC {(job.reac_length / 1000).toFixed(0)}k</span> : <span style={{ color: '#64748b', marginLeft: 6 }}>REAC non téléchargé</span>}
                    {job.rc_length > 0 && <span style={{ color: '#34d399', marginLeft: 6 }}>✓ RC {(job.rc_length / 1000).toFixed(0)}k</span>}
                    {job.rome_length > 0 && <span style={{ color: '#34d399', marginLeft: 6 }}>✓ ROME {(job.rome_length / 1000).toFixed(0)}k</span>}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  {canStopAutoPilot && (
                    <button
                      type="button"
                      style={{
                        ...S.btn('ghost'),
                        borderColor: 'rgba(248,113,113,0.42)',
                        color: '#fca5a5',
                        padding: '7px 12px',
                        fontSize: '12px',
                        opacity: stopAutoPilotBusy ? 0.65 : 1,
                      }}
                      disabled={stopAutoPilotBusy}
                      onClick={stopAutoPilot}
                    >
                      <Icon name="stop_circle" /> {stopAutoPilotBusy ? 'Arrêt…' : 'Stopper auto-pilot'}
                    </button>
                  )}
                  <span style={S.tag(
                    AUDIO_DONE_STATUSES.has(displayedJobStatus) ? 'green'
                    : (AUDIO_ACTIVE_STATUSES.has(displayedJobStatus) || displayedJobStatus === 'running') ? 'amber'
                    : (displayedJobStatus === 'error' || displayedJobStatus === 'audio_error') ? 'red'
                    : 'violet'
                  )}>
                    {AUDIO_DONE_STATUSES.has(displayedJobStatus)
                      ? 'Clôturée'
                      : AUDIO_ACTIVE_STATUSES.has(displayedJobStatus)
                        ? 'Audio en cours'
                      : displayedJobStatus === 'running'
                        ? 'auto-pilot en cours'
                        : displayedJobStatus?.replace(/_/g, ' ')}
                  </span>
                </div>
              </div>
              {showJobError && (
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
            {autoPilotState && (autoPilotState.status === 'error' || autoPilotState.status === 'stopped' || autoPilotState.lock_stale || detachedQueue) && (
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
                  <Icon name="error_outline" /> <strong>Auto-pilot interrompu</strong> pendant <em>{interruptedStepLabel}</em>
                  {interruptedBeforeReac ? (
                    <> · le téléchargement REAC n’a pas commencé</>
                  ) : autoPilotState.next_step && autoPilotState.next_step !== autoPilotState.step ? (
                    <> · prochaine étape réelle : <em>{autoPilotState.next_step}</em></>
                  ) : null}
                  {detachedQueue
                    ? <> : la tâche durable est terminée en échec{autoPilotState.queue?.last_error ? <> ({autoPilotState.queue.last_error})</> : null}.</>
                    : autoPilotState.error ? <> : {autoPilotState.error}</> : null}
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
                      const resp = await apiFetch(
                        `/api/formation/${selectedJobId}/run-auto/resume`,
                        {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          credentials: 'include',
                          body: JSON.stringify({
                            force: Boolean(autoPilotState.lock_stale || detachedQueue),
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
                    } catch {
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

            {/* Erreur action */}
            {actionError && (
              <div style={{ padding: '10px 14px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '8px', fontSize: '13px', color: '#f87171', marginBottom: '16px' }}>
                {actionError}
              </div>
            )}


            <BeatFirstIterationPanel
              folders={contentFolders}
              selectedJobId={selectedJobId}
              model={continueAfterTextModel}
              onModelChange={setContinueAfterTextModel}
              mode={beatFirstIterationMode}
              onModeChange={setBeatFirstIterationMode}
              running={beatFirstIterationRunning}
              error={beatFirstIterationError}
              notice={beatFirstIterationNotice}
              onRestart={handleRestartBeatFirstIteration}
            />

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

            <FlowArrowDown />

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr',
                gap: '16px',
                marginBottom: '24px',
              }}
            >
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
                    <button style={S.btn('ghost')} onClick={() => handleEnrichReac(DEEPSEEK_PRO_MODEL)} disabled={actionLoading}>
                      <Icon name="refresh" /> Reprendre (DeepSeek Pro)
                    </button>
                    <button style={S.btn('ghost')} onClick={() => handleEnrichReac(DEEPSEEK_FLASH_MODEL)} disabled={actionLoading}>
                      <Icon name="bolt" /> Reprendre (DeepSeek Flash)
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
                    <button style={S.btn('ghost')} onClick={() => handleEnrichReac(DEEPSEEK_PRO_MODEL)} disabled={actionLoading}>
                      <Icon name="refresh" /> Relancer (DeepSeek Pro)
                    </button>
                    <button style={S.btn('ghost')} onClick={() => handleEnrichReac(DEEPSEEK_FLASH_MODEL)} disabled={actionLoading}>
                      <Icon name="bolt" /> Relancer (DeepSeek Flash)
                    </button>
                  </div>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '10px' }}>
                    DeepSeek va extraire les compétences du REAC et les enrichir une par une
                    (définition pédagogique, études de cas, pièges fréquents, vocabulaire métier, contexte terrain).
                  </p>
                  <p style={{ fontSize: '13px', color: '#475569', marginBottom: '16px' }}>
                    Objectif : passer de ~15 000 mots bruts (REAC) à ~120 000 mots exploitables pour nourrir
                    la génération du programme et éviter la dilution sur les formations longues.
                  </p>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button style={S.btn('primary')} onClick={() => handleEnrichReac(DEEPSEEK_PRO_MODEL)} disabled={actionLoading}>
                      <Icon name="psychology" /> Enrichir (DeepSeek Pro)
                    </button>
                    <button style={S.btn('neutral')} onClick={() => handleEnrichReac(DEEPSEEK_FLASH_MODEL)} disabled={actionLoading} title="Mode rapide">
                      <Icon name="bolt" /> Enrichir (DeepSeek Flash)
                    </button>
                  </div>
                </div>
              )}
            </StepBlock>

            <FlowArrowDown />

            {/* ── Étape 4 : Programme global ── */}
            <StepBlock stepIndex={3} currentStep={currentStep} status={job.status} title="Programme global" icon="auto_stories">
              {job.status === 'global_generating' ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#fbbf24', fontSize: '14px' }}>
                  <Icon name="hourglass_empty" /> DeepSeek génère le programme global… (peut prendre 1-2 min)
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
                      <button style={S.btn('ghost')} onClick={() => handleGenerateGlobal(DEEPSEEK_PRO_MODEL)} disabled={actionLoading}>
                        <Icon name="refresh" /> Regénérer (DeepSeek Pro)
                      </button>
                      <button style={S.btn('ghost')} onClick={() => handleGenerateGlobal(DEEPSEEK_FLASH_MODEL)} disabled={actionLoading}>
                        <Icon name="bolt" /> Regénérer (DeepSeek Flash)
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
                    <button style={S.btn('neutral')} onClick={() => handleGenerateGlobal(DEEPSEEK_FLASH_MODEL)} disabled={actionLoading} title="Mode rapide">
                      <Icon name="bolt" /> Générer (DeepSeek Flash)
                    </button>
                  </div>
                </div>
              )}
            </StepBlock>

            <FlowArrowDown />

            {/* ── Étape 5 : Programmes journée ── */}
            <StepBlock stepIndex={4} currentStep={currentStep} status={job.status} title={`Programmes journée (${job.nb_days} jours)`} icon="calendar_view_week">
              {job.status === 'daily_splitting' ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#fbbf24', fontSize: '14px' }}>
                  <Icon name="hourglass_empty" /> Découpage en cours… ({formatJobPlanning(job)})
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
                      <button style={S.btn('ghost')} onClick={() => handleSplitDaily(DEEPSEEK_FLASH_MODEL)} disabled={actionLoading}>
                        <Icon name="bolt" /> Regénérer (DeepSeek Flash)
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
                    {selectedPipelineModel} va découper le programme global selon le planning verrouillé : <strong style={{ color: '#a78bfa' }}>{formatJobPlanning(job)}</strong>.
                  </p>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button style={S.btn('primary')} onClick={() => handleSplitDaily()} disabled={actionLoading || !job.global_program_validated}>
                      <Icon name="calendar_view_week" /> Découper ({selectedPipelineModel})
                    </button>
                    <button style={S.btn('neutral')} onClick={() => handleSplitDaily(DEEPSEEK_FLASH_MODEL)} disabled={actionLoading || !job.global_program_validated} title="Mode rapide">
                      <Icon name="bolt" /> Découper (DeepSeek Flash)
                    </button>
                  </div>
                  {!job.global_program_validated && (
                    <div style={{ fontSize: '12px', color: '#f87171', marginTop: '8px' }}>Le programme global doit être validé d'abord.</div>
                  )}
                </div>
              )}
            </StepBlock>

            <FlowArrowDown />

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
                      const slideIterationBusy = !!slideIterationFolders[folder.folder_id]
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
                                    disabled={!canUseFolder || !(folder.slide_count || 0)}
                                    onClick={() => setSlide2Folder(folder)}
                                    title={
                                      canUseFolder && (folder.slide_count || 0)
                                        ? 'Auditer la correspondance texte surligné et slides'
                                        : 'Slides requises'
                                    }
                                  >
                                    <Icon name="splitscreen" /> Slide2
                                  </button>
                                  <button
                                    style={{
                                      ...S.btn('ghost'),
                                      padding: '6px 12px',
                                      fontSize: '12px',
                                      borderColor: slideIterationBusy ? 'rgba(96,165,250,0.18)' : 'rgba(96,165,250,0.42)',
                                      color: slideIterationBusy ? '#64748b' : '#60a5fa',
                                    }}
                                    disabled={!canUseFolder || slideIterationBusy || continuingAfterText}
                                    onClick={() => handleRegenerateSlidesOnly(folder)}
                                    title={
                                      canUseFolder
                                        ? 'Relance uniquement la curation IA + génération du deck slides depuis le texte final. Ne relance ni texte, ni reviews, ni audio.'
                                        : 'Texte de journée requis'
                                    }
                                  >
                                    <Icon name={slideIterationBusy ? 'hourglass_empty' : 'filter_alt'} />{' '}
                                    {slideIterationBusy ? 'Curation…' : 'Régénérer curation + slides'}
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
                    {slideIterationError && (
                      <div style={{ fontSize: '13px', color: '#f87171', marginTop: '4px' }}>
                        Itération slides : {slideIterationError}
                      </div>
                    )}
                    {slideIterationNotice && (
                      <div style={{ fontSize: '13px', color: '#34d399', marginTop: '4px' }}>
                        Itération slides : {slideIterationNotice}
                      </div>
                    )}
                    {audioError && (
                      <div style={{ fontSize: '13px', color: '#f87171', marginTop: '4px' }}>
                        Audio journée : {audioError}
                      </div>
                    )}
                    {audioNotice && (
                      <div style={{ fontSize: '13px', color: '#34d399', marginTop: '4px' }}>
                        Audio journée : {audioNotice}
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
                    Crée <strong style={{ color: '#a78bfa' }}>{job.nb_days} dossiers cours</strong> et génère le texte de chaque journée selon le planning verrouillé ({formatJobPlanning(job)}) avec {selectedPipelineModel}.
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
                      <Icon name="edit_note" /> {launchingTTS ? 'Lancement…' : `Générer les textes — ${selectedPipelineModel} (${job.nb_days} journées)`}
                    </button>
                    <button
                      style={S.btn('neutral')}
                      onClick={() => handleLaunchTTS(DEEPSEEK_FLASH_MODEL)}
                      disabled={launchingTTS || actionLoading || !job.daily_programs_validated}
                      title="Mode rapide"
                    >
                      <Icon name="bolt" /> {launchingTTS ? 'Lancement…' : 'DeepSeek Flash'}
                    </button>
                  </div>
                  {!job.daily_programs_validated && (
                    <div style={{ fontSize: '12px', color: '#f87171', marginTop: '8px' }}>Les journées doivent être validées d'abord.</div>
                  )}
                </div>
              )}
            </StepBlock>

            </div>

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

      {slide2Folder && (
        <Slide2AlignmentModal
          jobId={selectedJobId}
          folder={slide2Folder}
          onClose={() => setSlide2Folder(null)}
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


    </div>
  )
}

function ReviewReportModal({ jobId, folder, onClose, reportEndpoint = 'review-report' }) {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedSegments, setExpandedSegments] = useState({})

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const resp = await apiFetch(
          `/api/formation/${jobId}/content/${folder.folder_id}/${reportEndpoint}`,
          { credentials: 'include' },
        )
        const data = await resp.json()
        if (cancelled) return
        if (resp.ok && data.report) setReport(data.report)
        else setError(data.error || 'Aucun rapport disponible')
      } catch {
        if (!cancelled) setError('Erreur réseau')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [folder.folder_id, jobId, reportEndpoint])

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
                  {(report.by_segment || []).map(seg => {
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


const SLIDE2_HIGHLIGHT_COLORS = [
  '#60a5fa',
  '#34d399',
  '#fbbf24',
  '#fb923c',
  '#f472b6',
  '#a78bfa',
  '#2dd4bf',
  '#f87171',
  '#c084fc',
  '#38bdf8',
]

function stripSlide2TtsTags(text) {
  return String(text || '')
    .replace(/\[[^[\]\n]{1,50}\]/g, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\n[ \t]+/g, '\n')
    .trim()
}

function splitSlide2Words(text) {
  return String(text || '').trim().split(/\s+/).filter(Boolean)
}

function getSlide2CourseText(course = {}) {
  const sectionTexts = Array.isArray(course.sections)
    ? course.sections
        .map(section => stripSlide2TtsTags(section?.text || section?.script || section?.content || ''))
        .filter(Boolean)
    : []

  if (sectionTexts.length) return sectionTexts.join('\n\n')
  return stripSlide2TtsTags(course.text || course.script || course.content || course.module_content || '')
}

function buildSlide2Courses(artifact, fallbackText = '') {
  let rawCourses = []
  if (Array.isArray(artifact?.courses)) rawCourses = artifact.courses
  else if (Array.isArray(artifact)) rawCourses = artifact
  else if (artifact?.text) rawCourses = [{ course_number: 1, course_title: artifact.course_title || 'Cours', text: artifact.text }]

  if (!rawCourses.length && fallbackText) {
    rawCourses = [{ course_number: 1, course_title: 'Texte complet', text: fallbackText }]
  }

  let cursor = 0
  return rawCourses
    .map((course, index) => {
      const text = getSlide2CourseText(course)
      const wordCount = splitSlide2Words(text).length
      const courseNumber = Number(course.course_number || course.number || course.index || index + 1)
      const item = {
        courseNumber,
        title: course.course_title || course.title || course.name || `Cours ${courseNumber}`,
        text,
        wordStart: cursor,
        wordEnd: cursor + wordCount,
        wordCount,
      }
      cursor += wordCount
      return item
    })
    .filter(course => course.text && course.wordCount > 0)
}

function getSlide2Range(slide = {}) {
  const ref = slide.source_ref || {}
  const start = Number(ref.word_start)
  const end = Number(ref.word_end)
  if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
    return { start, end }
  }

  const windowStart = Number(ref.source_window_word_start)
  const windowEnd = Number(ref.source_window_word_end)
  if (Number.isFinite(windowStart) && Number.isFinite(windowEnd) && windowEnd > windowStart) {
    return { start: windowStart, end: windowEnd }
  }

  return null
}

function getSlide2CourseNumberFromRef(slide = {}) {
  const ref = slide.source_ref || {}
  if (Number.isFinite(Number(ref.sub_part_index))) return Number(ref.sub_part_index) + 1
  const segments = Array.isArray(ref.segments) ? ref.segments : []
  const firstSegment = segments.find(segment =>
    Number.isFinite(Number(segment?.course_number)) || Number.isFinite(Number(segment?.sub_part_index))
  )
  if (!firstSegment) return null
  if (Number.isFinite(Number(firstSegment.course_number))) return Number(firstSegment.course_number)
  return Number(firstSegment.sub_part_index) + 1
}

function findSlide2QuoteRange(courseText, quote) {
  const quoteWords = splitSlide2Words(stripSlide2TtsTags(quote))
  if (!quoteWords.length) return null

  const courseWords = splitSlide2Words(courseText)
  if (!courseWords.length || quoteWords.length > courseWords.length) return null

  const normalizedCourse = courseWords.join(' ')
  const normalizedQuote = quoteWords.join(' ')
  const charIndex = normalizedCourse.indexOf(normalizedQuote)
  if (charIndex < 0) return null

  const beforeWords = splitSlide2Words(normalizedCourse.slice(0, charIndex)).length
  return {
    start: beforeWords,
    end: beforeWords + quoteWords.length,
  }
}

function buildSlide2Assignments(courses = [], slides = []) {
  const byCourse = new Map(courses.map(course => [course.courseNumber, []]))

  slides.forEach((slide, slideIndex) => {
    const range = getSlide2Range(slide)
    let matched = false

    if (range) {
      courses.forEach(course => {
        const start = Math.max(range.start, course.wordStart)
        const end = Math.min(range.end, course.wordEnd)
        if (end <= start) return
        matched = true
        const color = SLIDE2_HIGHLIGHT_COLORS[slideIndex % SLIDE2_HIGHLIGHT_COLORS.length]
        byCourse.get(course.courseNumber)?.push({
          slide,
          slideIndex,
          slideNumber: slideIndex + 1,
          start: start - course.wordStart,
          end: end - course.wordStart,
          color,
        })
      })
    }

    if (matched) return

    const courseNumber = getSlide2CourseNumberFromRef(slide)
    const course = courses.find(item => item.courseNumber === courseNumber)
    if (!course) return

    const ref = slide.source_ref || {}
    const fallbackQuote = ref.source_quote || slide.source_quote || slide.source_text || ''
    const localRange = findSlide2QuoteRange(course.text, fallbackQuote)
    if (!localRange) return

    const color = SLIDE2_HIGHLIGHT_COLORS[slideIndex % SLIDE2_HIGHLIGHT_COLORS.length]
    byCourse.get(course.courseNumber)?.push({
      slide,
      slideIndex,
      slideNumber: slideIndex + 1,
      start: localRange.start,
      end: localRange.end,
      color,
      fallback: true,
    })
  })

  byCourse.forEach((items, courseNumber) => {
    byCourse.set(
      courseNumber,
      items
        .filter(item => item.end > item.start)
        .sort((a, b) => a.start - b.start || a.slideIndex - b.slideIndex),
    )
  })

  return byCourse
}

function countSlide2CoveredWords(wordCount, assignments = []) {
  if (!wordCount) return 0
  const covered = new Array(wordCount).fill(false)
  assignments.forEach(item => {
    const start = Math.max(0, Math.min(wordCount, item.start))
    const end = Math.max(start, Math.min(wordCount, item.end))
    for (let index = start; index < end; index += 1) covered[index] = true
  })
  return covered.filter(Boolean).length
}

function getSlide2Title(slide = {}, index = 0) {
  const data = slide.data || {}
  return data.title || data.headline || data.label || slide.event_summary || `Slide ${index + 1}`
}

function getSlide2AssignmentForWord(assignments, wordIndex) {
  return assignments.find(item => wordIndex >= item.start && wordIndex < item.end) || null
}

function buildSlide2TextChunks(text, assignments = []) {
  const tokens = String(text || '').split(/(\s+)/)
  const chunks = []
  let wordIndex = 0
  let current = null

  const flush = () => {
    if (current && current.text) chunks.push(current)
    current = null
  }

  tokens.forEach(token => {
    if (!token) return
    const isSpace = /^\s+$/.test(token)
    const assignment = isSpace ? current?.assignment || null : getSlide2AssignmentForWord(assignments, wordIndex)
    const key = assignment ? `slide-${assignment.slideIndex}` : 'plain'

    if (!current || current.key !== key) {
      flush()
      current = { key, assignment, text: '' }
    }

    current.text += token
    if (!isSpace) wordIndex += 1
  })

  flush()
  return chunks
}

function Slide2HighlightedText({ text, assignments, selectedSlideIndex, onSelectSlide }) {
  const chunks = useMemo(() => buildSlide2TextChunks(text, assignments), [text, assignments])

  return (
    <div style={{
      fontFamily: "'Fira Code', 'Menlo', 'Consolas', monospace",
      fontSize: '12px',
      lineHeight: 1.72,
      color: '#cbd5e1',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
    }}>
      {chunks.map((chunk, index) => {
        if (!chunk.assignment) return <span key={index}>{chunk.text}</span>
        const active = chunk.assignment.slideIndex === selectedSlideIndex
        return (
          <span
            key={index}
            role="button"
            tabIndex={0}
            onClick={() => onSelectSlide(chunk.assignment.slideIndex)}
            onKeyDown={event => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onSelectSlide(chunk.assignment.slideIndex)
              }
            }}
            title={`Slide ${chunk.assignment.slideNumber}`}
            style={{
              cursor: 'pointer',
              borderRadius: '4px',
              padding: '1px 2px',
              background: active ? `${chunk.assignment.color}44` : `${chunk.assignment.color}24`,
              boxShadow: active ? `0 0 0 1px ${chunk.assignment.color}` : 'none',
              color: active ? '#f8fafc' : '#dbeafe',
              transition: 'background 0.15s, box-shadow 0.15s',
            }}
          >
            {chunk.text}
          </span>
        )
      })}
    </div>
  )
}

function Slide2AlignmentModal({ jobId, folder, onClose }) {
  const [courses, setCourses] = useState([])
  const [slides, setSlides] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedCourseNumber, setSelectedCourseNumber] = useState(null)
  const [selectedSlideIndex, setSelectedSlideIndex] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError('')

      try {
        const [slidesResp, artifactResp] = await Promise.all([
          apiFetch(`/api/slides/data?folder_id=${encodeURIComponent(folder.folder_id)}`, { credentials: 'include' }),
          apiFetch(
            `/api/formation/${jobId}/content/${folder.folder_id}/artifact/content-course-scripts.json`,
            { credentials: 'include' },
          ),
        ])

        const messages = []
        let loadedSlides = []
        let loadedStats = null
        let artifact = null
        let fallbackText = ''

        const slidesData = await slidesResp.json().catch(() => ({}))
        if (slidesResp.ok && slidesData.status === 'success' && Array.isArray(slidesData.slides)) {
          loadedSlides = slidesData.slides
          loadedStats = slidesData.stats || null
        } else {
          messages.push(slidesData.message || slidesData.error || 'Deck slides indisponible')
        }

        const artifactData = await artifactResp.json().catch(() => ({}))
        if (artifactResp.ok && artifactData.artifact) {
          artifact = artifactData.artifact
        } else {
          const textResp = await apiFetch(
            `/api/formation/${jobId}/content/${folder.folder_id}/text`,
            { credentials: 'include' },
          )
          const textData = await textResp.json().catch(() => ({}))
          if (textResp.ok && textData.text) {
            fallbackText = stripSlide2TtsTags(textData.text)
          } else {
            messages.push(artifactData.error || textData.error || 'Texte source indisponible')
          }
        }

        const builtCourses = buildSlide2Courses(artifact, fallbackText)
        if (!builtCourses.length) messages.push('Aucun cours exploitable pour le surlignage')

        if (cancelled) return
        setSlides(loadedSlides)
        setStats(loadedStats)
        setCourses(builtCourses)
        setSelectedCourseNumber(prev => (
          builtCourses.some(course => course.courseNumber === prev)
            ? prev
            : builtCourses[0]?.courseNumber || null
        ))
        setSelectedSlideIndex(prev => (
          Number.isInteger(prev) && loadedSlides[prev] ? prev : 0
        ))
        setError(messages.join(' · '))
      } catch {
        if (!cancelled) setError('Erreur réseau pendant le chargement Slide2')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [jobId, folder.folder_id])

  const assignmentsByCourse = useMemo(() => buildSlide2Assignments(courses, slides), [courses, slides])
  const selectedCourse = useMemo(
    () => courses.find(course => course.courseNumber === selectedCourseNumber) || courses[0] || null,
    [courses, selectedCourseNumber],
  )
  const selectedAssignments = useMemo(
    () => selectedCourse ? assignmentsByCourse.get(selectedCourse.courseNumber) || [] : [],
    [assignmentsByCourse, selectedCourse],
  )

  useEffect(() => {
    if (!courses.length) return
    if (!selectedCourse) {
      setSelectedCourseNumber(courses[0].courseNumber)
    }
  }, [courses, selectedCourse])

  useEffect(() => {
    if (!selectedAssignments.length) return
    if (!selectedAssignments.some(item => item.slideIndex === selectedSlideIndex)) {
      setSelectedSlideIndex(selectedAssignments[0].slideIndex)
    }
  }, [selectedAssignments, selectedSlideIndex])

  const effectiveSlideIndex = Number.isInteger(selectedSlideIndex)
    ? selectedSlideIndex
    : selectedAssignments[0]?.slideIndex ?? 0
  const selectedSlide = slides[effectiveSlideIndex] || null
  const coveredWords = selectedCourse ? countSlide2CoveredWords(selectedCourse.wordCount, selectedAssignments) : 0
  const coveragePct = selectedCourse?.wordCount
    ? Math.round((coveredWords / selectedCourse.wordCount) * 100)
    : 0

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.72)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '18px',
      }}
    >
      <div
        onClick={event => event.stopPropagation()}
        style={{
          width: 'min(1560px, 96vw)',
          height: '90vh',
          background: '#0f172a',
          border: '1px solid rgba(139,92,246,0.28)',
          borderRadius: '16px',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          color: '#e2e8f0',
        }}
      >
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid rgba(99,102,241,0.18)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '14px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
            <div style={{
              width: '40px',
              height: '40px',
              borderRadius: '10px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'rgba(139,92,246,0.14)',
              color: '#a78bfa',
              flexShrink: 0,
            }}>
              <Icon name="splitscreen" />
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: '16px', fontWeight: 700, color: '#e2e8f0' }}>
                Slide2 · Alignement texte / slides
              </div>
              <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                Jour {folder.day_number} — {folder.day_title} · {slides.length || folder.slide_count || 0} slides
                {stats?.source_word_count ? ` · ${Number(stats.source_word_count).toLocaleString('fr-FR')} mots source` : ''}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ ...S.btn('neutral'), padding: '6px 10px', fontSize: '12px', flexShrink: 0 }}
          >
            <Icon name="close" />
          </button>
        </div>

        <div style={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: '240px minmax(420px, 1fr) minmax(360px, 520px)',
          gap: '0',
        }}>
          <aside style={{
            borderRight: '1px solid rgba(99,102,241,0.16)',
            background: 'rgba(15,23,42,0.72)',
            padding: '14px',
            overflow: 'auto',
          }}>
            <div style={{
              fontSize: '10px',
              fontWeight: 800,
              color: '#94a3b8',
              textTransform: 'uppercase',
              letterSpacing: '0.14em',
              marginBottom: '10px',
            }}>
              Cours de la journée
            </div>
            {loading && <div style={{ color: '#64748b', fontSize: '12px' }}>Chargement…</div>}
            {!loading && courses.map(course => {
              const assignments = assignmentsByCourse.get(course.courseNumber) || []
              const covered = countSlide2CoveredWords(course.wordCount, assignments)
              const pct = course.wordCount ? Math.round((covered / course.wordCount) * 100) : 0
              const active = course.courseNumber === selectedCourse?.courseNumber
              return (
                <button
                  key={course.courseNumber}
                  onClick={() => setSelectedCourseNumber(course.courseNumber)}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    padding: '10px 11px',
                    marginBottom: '8px',
                    borderRadius: '10px',
                    border: `1px solid ${active ? 'rgba(139,92,246,0.5)' : 'rgba(51,65,85,0.85)'}`,
                    background: active ? 'rgba(139,92,246,0.12)' : 'rgba(30,41,59,0.42)',
                    color: '#e2e8f0',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 700 }}>Cours {course.courseNumber}</span>
                    <span style={{ fontSize: '11px', color: assignments.length ? '#60a5fa' : '#64748b' }}>
                      {assignments.length} slide{assignments.length > 1 ? 's' : ''}
                    </span>
                  </div>
                  <div style={{
                    fontSize: '12px',
                    color: '#cbd5e1',
                    lineHeight: 1.35,
                    marginBottom: '8px',
                  }}>
                    {course.title}
                  </div>
                  <div style={{ height: '4px', background: 'rgba(15,23,42,0.9)', borderRadius: '999px', overflow: 'hidden' }}>
                    <div style={{
                      width: `${pct}%`,
                      height: '100%',
                      background: pct >= 98 ? '#34d399' : pct >= 70 ? '#fbbf24' : '#f87171',
                    }} />
                  </div>
                  <div style={{ marginTop: '5px', fontSize: '10px', color: '#94a3b8' }}>
                    {pct}% couvert · {course.wordCount.toLocaleString('fr-FR')} mots
                  </div>
                </button>
              )
            })}
          </aside>

          <main style={{
            minWidth: 0,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
            borderRight: '1px solid rgba(99,102,241,0.16)',
          }}>
            <div style={{
              padding: '14px 16px',
              borderBottom: '1px solid rgba(99,102,241,0.16)',
              background: 'rgba(15,23,42,0.58)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start', marginBottom: '10px' }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: '14px', fontWeight: 700, color: '#e2e8f0' }}>
                    {selectedCourse ? `Cours ${selectedCourse.courseNumber} · ${selectedCourse.title}` : 'Texte source'}
                  </div>
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                    {selectedAssignments.length} slide{selectedAssignments.length > 1 ? 's' : ''} liée{selectedAssignments.length > 1 ? 's' : ''} · {coveredWords.toLocaleString('fr-FR')}/{selectedCourse?.wordCount?.toLocaleString('fr-FR') || 0} mots couverts
                  </div>
                </div>
                <span style={{
                  ...S.tag(coveragePct >= 98 ? 'green' : coveragePct >= 70 ? 'amber' : 'red'),
                  flexShrink: 0,
                }}>
                  {coveragePct}% couvert
                </span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {selectedAssignments.map(item => (
                  <button
                    key={`${item.slideIndex}-${item.start}-${item.end}`}
                    onClick={() => setSelectedSlideIndex(item.slideIndex)}
                    style={{
                      border: `1px solid ${item.color}`,
                      background: item.slideIndex === effectiveSlideIndex ? `${item.color}30` : 'rgba(15,23,42,0.7)',
                      color: '#e2e8f0',
                      borderRadius: '999px',
                      padding: '4px 8px',
                      fontSize: '11px',
                      fontWeight: 700,
                      cursor: 'pointer',
                    }}
                  >
                    Slide {item.slideNumber}
                  </button>
                ))}
              </div>
            </div>

            <div style={{
              flex: 1,
              minHeight: 0,
              overflow: 'auto',
              padding: '18px',
              background: '#020617',
            }}>
              {loading && <div style={{ color: '#64748b' }}>Chargement du texte…</div>}
              {error && (
                <div style={{
                  color: '#fca5a5',
                  background: 'rgba(127,29,29,0.22)',
                  border: '1px solid rgba(248,113,113,0.25)',
                  borderRadius: '8px',
                  padding: '10px 12px',
                  fontSize: '12px',
                  marginBottom: '14px',
                }}>
                  {error}
                </div>
              )}
              {selectedCourse && (
                <Slide2HighlightedText
                  text={selectedCourse.text}
                  assignments={selectedAssignments}
                  selectedSlideIndex={effectiveSlideIndex}
                  onSelectSlide={setSelectedSlideIndex}
                />
              )}
            </div>
          </main>

          <aside style={{
            minWidth: 0,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
            background: 'rgba(15,23,42,0.76)',
          }}>
            <div style={{
              padding: '14px 16px',
              borderBottom: '1px solid rgba(99,102,241,0.16)',
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: '10px',
            }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 700 }}>
                  {selectedSlide ? `Slide ${effectiveSlideIndex + 1}/${slides.length}` : 'Slide'}
                </div>
                <div style={{
                  fontSize: '14px',
                  color: '#e2e8f0',
                  fontWeight: 700,
                  lineHeight: 1.35,
                  marginTop: '3px',
                }}>
                  {selectedSlide ? getSlide2Title(selectedSlide, effectiveSlideIndex) : 'Aucune slide sélectionnée'}
                </div>
              </div>
              {selectedSlide && (
                <span style={{
                  ...S.tag('violet'),
                  flexShrink: 0,
                  maxWidth: '160px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}>
                  {selectedSlide.template_type}
                </span>
              )}
            </div>

            <div style={{ minHeight: 0, flex: '0 0 auto', background: '#020617' }}>
              {selectedSlide ? (
                <SlidePreviewFrame slide={selectedSlide} />
              ) : (
                <div style={{ padding: '24px', color: '#64748b', fontSize: '13px' }}>Aperçu indisponible</div>
              )}
            </div>

            <div style={{
              minHeight: 0,
              flex: 1,
              overflow: 'auto',
              padding: '14px 16px',
              borderTop: '1px solid rgba(99,102,241,0.16)',
            }}>
              {selectedSlide && (
                <>
                  <div style={{
                    fontSize: '10px',
                    color: '#94a3b8',
                    fontWeight: 800,
                    textTransform: 'uppercase',
                    letterSpacing: '0.12em',
                    marginBottom: '8px',
                  }}>
                    Source slide
                  </div>
                  <div style={{
                    padding: '10px 12px',
                    borderRadius: '8px',
                    border: '1px solid rgba(51,65,85,0.85)',
                    background: 'rgba(30,41,59,0.44)',
                    color: '#cbd5e1',
                    fontSize: '12px',
                    lineHeight: 1.55,
                    marginBottom: '10px',
                  }}>
                    {selectedSlide.event_summary || selectedSlide.curation_reason || 'Résumé non disponible'}
                  </div>
                  <div style={{
                    fontSize: '11px',
                    color: '#94a3b8',
                    display: 'grid',
                    gridTemplateColumns: 'auto 1fr',
                    gap: '5px 10px',
                  }}>
                    <span>Alignement</span>
                    <span style={{ color: '#cbd5e1' }}>{selectedSlide.source_ref?.source_alignment || selectedSlide.source_ref?.selection_method || '—'}</span>
                    <span>Bloc source</span>
                    <span style={{ color: '#cbd5e1' }}>{selectedSlide.source_ref?.source_block_id ?? '—'}</span>
                    <span>Mots</span>
                    <span style={{ color: '#cbd5e1' }}>
                      {selectedSlide.source_ref?.word_start ?? '—'} → {selectedSlide.source_ref?.word_end ?? '—'}
                    </span>
                    {selectedSlide.slide_anchor_id && (
                      <>
                        <span>Anchor</span>
                        <span style={{ color: '#cbd5e1', wordBreak: 'break-all' }}>{selectedSlide.slide_anchor_id}</span>
                      </>
                    )}
                  </div>
                </>
              )}
            </div>
          </aside>
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
        const resp = await apiFetch(
          `/api/formation/${jobId}/content/${folder.folder_id}/text`,
          { credentials: 'include' },
        )
        const data = await resp.json()
        if (cancelled) return
        if (data.text) setText(data.text)
        else setError(data.error || 'Aucun texte disponible')
      } catch {
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
              {folder.total_words.toLocaleString('fr-FR')} mots · {folder.segments_total || 0} segments de génération
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              style={{ ...S.btn('primary'), padding: '6px 12px', fontSize: '12px' }}
              onClick={async () => {
                try {
                  await apiDownload(
                    `/api/formation/${jobId}/content/${folder.folder_id}/docx`,
                    `formation-${jobId}-jour-${folder.folder_id}.docx`,
                  )
                } catch (downloadError) {
                  setError(downloadError.message || 'Téléchargement Word impossible')
                }
              }}
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
