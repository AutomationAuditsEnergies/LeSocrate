import { useState, useEffect, useRef, useCallback } from 'react'
import { apiUrl } from '../api'

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

  // Étape 7 (synthèse TTS audio)
  if (AUDIO_DONE_STATUSES.has(status)) return 7
  if (AUDIO_ACTIVE_STATUSES.has(status)) return 6

  // Étape 6 (génération texte cours) — texte lancé OU audio en erreur
  // (audio_error = on était à l'étape 7 ; les textes restent validés et
  // l'utilisateur peut relancer le TTS)
  if (status === 'tts_launched' || status === 'audio_error') return 6

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
  { icon: 'edit_note', label: 'Génération cours' },
  { icon: 'record_voice_over', label: 'Synthèse TTS' },
]

// ─── Connecteurs visuels entre étapes du pipeline ─────────────────────────────
// Matérialise le flux de données : RNCP → REAC → split (API/CC) → ... → merge → TTS.
// Trois primitives :
//   - FlowArrowDown : flèche verticale ↓ entre 2 cards consécutives.
//   - FlowSplit     : Y-fork qui part d'un tronc commun vers les 2 colonnes.
//   - FlowMerge     : Y-merge inverse qui rejoint les 2 colonnes vers un tronc.
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

// Y-merge (2 → 1) : symétrique inverse de FlowSplit. Les 2 colonnes remontent
// vers une barre horizontale, qui descend en tronc central avec une seule tête.
function FlowMerge({ color = FLOW_COLOR }) {
  const drop = 22
  const stem = 18
  const arrow = 7
  const total = drop + stem + arrow
  return (
    <div style={{ position: 'relative', height: `${total}px`, margin: '4px 0' }}>
      {/* montée gauche */}
      <div style={{
        position: 'absolute',
        left: `calc(25% - 10px - ${FLOW_STROKE / 2}px)`, top: 0,
        width: `${FLOW_STROKE}px`, height: `${drop}px`,
        background: color,
      }}/>
      {/* montée droite */}
      <div style={{
        position: 'absolute',
        right: `calc(25% - 10px - ${FLOW_STROKE / 2}px)`, top: 0,
        width: `${FLOW_STROKE}px`, height: `${drop}px`,
        background: color,
      }}/>
      {/* barre horizontale */}
      <div style={{
        position: 'absolute',
        left: 'calc(25% - 10px)', right: 'calc(25% - 10px)',
        top: `${drop}px`, height: `${FLOW_STROKE}px`,
        background: color,
      }}/>
      {/* tronc central descendant */}
      <div style={{
        position: 'absolute',
        left: '50%', top: `${drop}px`,
        width: `${FLOW_STROKE}px`, height: `${stem}px`,
        background: color, transform: 'translateX(-50%)',
      }}/>
      {/* tête de flèche bas */}
      <div style={{
        position: 'absolute',
        left: '50%', top: `${drop + stem}px`,
        transform: 'translateX(-50%)',
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
  if (t === 'gtts') return 'gTTS — voix basique gratuite'
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
  const date = new Date(String(value).replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return String(value).slice(11, 16) || String(value)
  return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
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
    audio_started: 'Audio démarré',
    audio_progress: 'Progression audio',
    audio_folder_started: 'Journée audio démarrée',
    audio_folder_completed: 'Journée audio terminée',
    audio_folder_failed: 'Journée audio échouée',
    audio_completed: 'Audio terminé',
    audio_failed: 'Audio échoué',
    continue_after_text_started: 'Reprise aval démarrée',
    continue_after_text_completed: 'Reprise aval terminée',
    continue_after_text_failed: 'Reprise aval échouée',
  }
  return labels[eventType] || String(eventType || 'Événement').replace(/_/g, ' ')
}

function PipelineDiagnosticPanel({ diagnostic, loading, error, onRefresh }) {
  const health = diagnostic?.health
  const folders = diagnostic?.folders || []
  const events = diagnostic?.events || []
  // events[] arrive déjà du plus ancien au plus récent depuis le backend
  // (list_pipeline_events fait `for row in reversed(rows)`). On garde cet
  // ordre et on prend les 8 derniers : du plus ancien (haut) au plus récent (bas).
  const recentEvents = events.slice(-8)
  const [selectedEvent, setSelectedEvent] = useState(null)
  const totals = folders.reduce((acc, folder) => ({
    words: acc.words + (folder.total_words || 0),
    segments: acc.segments + (folder.segments_completed || 0),
    reviewed: acc.reviewed + (folder.reviewed_segments || 0),
    dirty: acc.dirty + (folder.dirty_segments || 0),
    reviewErrors: acc.reviewErrors + (folder.review_errors || 0),
  }), { words: 0, segments: 0, reviewed: 0, dirty: 0, reviewErrors: 0 })
  const healthColor = health?.ok ? '#34d399' : health?.blocking?.length ? '#f87171' : '#fbbf24'
  const healthIcon = health?.ok ? 'verified' : health?.blocking?.length ? 'error_outline' : 'warning_amber'

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
          <Icon name="graphic_eq" /> {totals.dirty} segment{totals.dirty > 1 ? 's' : ''} audio dirty
        </span>
        {totals.reviewErrors > 0 && (
          <span style={{ ...S.tag('red'), padding: '5px 10px' }}>
            <Icon name="report" /> {totals.reviewErrors} erreur{totals.reviewErrors > 1 ? 's' : ''} review
          </span>
        )}
      </div>

      {health && !health.ok && (
        <div style={{
          color: healthColor,
          fontSize: '12px',
          lineHeight: 1.45,
          marginBottom: '12px',
        }}>
          {health.blocking?.length > 0 && <>Bloquants : {health.blocking.join(', ')}</>}
          {health.blocking?.length > 0 && health.warnings?.length > 0 && ' · '}
          {health.warnings?.length > 0 && <>Warnings : {health.warnings.join(', ')}</>}
        </div>
      )}

      <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '8px' }}>
        <strong style={{ color: '#cbd5e1' }}>{totals.reviewed}/{totals.segments}</strong> segments revus · derniers événements
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
        {recentEvents.length === 0 ? (
          <div style={{ fontSize: '12px', color: '#64748b' }}>
            Aucun événement structuré encore enregistré pour cette pipeline.
          </div>
        ) : recentEvents.map(event => {
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
                {event.folder_id ? <span style={{ color: '#64748b' }}> · dossier {event.folder_id}</span> : null}
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

function EventDetailModal({ event, onClose }) {
  const tone = eventTone(event.status)
  let dataPreview = null
  try {
    const parsed = typeof event.data_json === 'string' && event.data_json
      ? JSON.parse(event.data_json)
      : event.data_json
    if (parsed && Object.keys(parsed).length > 0) {
      dataPreview = JSON.stringify(parsed, null, 2)
    }
  } catch {
    dataPreview = String(event.data_json || '')
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
          {event.step && (<><span style={{ color: '#64748b' }}>Étape</span><span style={{ color: '#cbd5e1' }}>{event.step}</span></>)}
          {event.folder_id && (<><span style={{ color: '#64748b' }}>Dossier</span><span style={{ color: '#cbd5e1' }}>#{event.folder_id}</span></>)}
          {event.model && (<><span style={{ color: '#64748b' }}>Modèle LLM</span><span style={{ color: '#a78bfa', fontFamily: 'monospace' }}>{event.model}</span></>)}
          {event.duration_ms != null && (<><span style={{ color: '#64748b' }}>Durée</span><span style={{ color: '#cbd5e1' }}>{formatDuration(event.duration_ms) || `${event.duration_ms} ms`}</span></>)}
          <span style={{ color: '#64748b' }}>Type</span><span style={{ color: '#cbd5e1', fontFamily: 'monospace' }}>{event.event_type}</span>
          <span style={{ color: '#64748b' }}>ID</span><span style={{ color: '#cbd5e1', fontFamily: 'monospace' }}>{event.id}</span>
        </div>

        {event.message && (
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#64748b', marginBottom: '4px' }}>Message</div>
            <div style={{ fontSize: '13px', color: '#cbd5e1', lineHeight: 1.5, padding: '10px 12px', background: 'rgba(167,139,250,0.06)', borderLeft: '3px solid rgba(167,139,250,0.4)', borderRadius: '6px' }}>
              {event.message}
            </div>
          </div>
        )}

        {event.error && (
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#f87171', marginBottom: '4px' }}>Erreur</div>
            <div style={{ fontSize: '13px', color: '#fecaca', lineHeight: 1.5, padding: '10px 12px', background: 'rgba(239,68,68,0.08)', borderLeft: '3px solid #f87171', borderRadius: '6px', fontFamily: 'monospace', wordBreak: 'break-word' }}>
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

// ─── Carte d'un job existant ──────────────────────────────────────────────────
function JobCard({ job, onSelect, selected }) {
  const step = statusToStep(job.status, job)
  const statusColor = AUDIO_DONE_STATUSES.has(job.status) ? 'green'
    : (job.status === 'error' || job.status === 'audio_error') ? 'red'
    : POLLING_STATUSES.has(job.status) ? 'amber'
    : 'violet'

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
    >
      <div>
        <div style={{ fontWeight: 600, fontSize: '15px', color: '#e2e8f0' }}>{job.tp_name}</div>
        {job.platform_name && (
          <div style={{ fontSize: '11px', color: '#8b5cf6', fontWeight: 500, marginTop: '1px' }}>{job.platform_name}</div>
        )}
        <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>
          {job.total_hours}h — {job.nb_days} jour{job.nb_days > 1 ? 's' : ''} · RNCP {job.rncp_code}
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
// Subprocess auto : global + daily + kb en mode mono-chunk, content + review
// en mode chunked (boucle séquentielle de N appels CLI dans le backend, voir
// claude_code_mission_service.py:_execute_chunked).
// kb : prompt borné à 1500-2500 mots/compétence × ~10 = ~25K mots ≈ 38K tokens
// (largement sous la limite Sonnet 64K output). Parsing tolérant à la
// troncature dans `_import_kb` via `_repair_truncated_json`.
const CC_AUTO_EXEC_ENABLED = { global: true, kb: true, daily: true, content: true, review: true }

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
  const [reportFolder, setReportFolder] = useState(null)      // folder dont on affiche le rapport de révision

  // États étape 6 — Synthèse audio Fish Audio
  const [launchingAudio, setLaunchingAudio] = useState(false)
  const [audioError, setAudioError] = useState('')
  const [continuingAfterTextFolders, setContinuingAfterTextFolders] = useState({})
  const [continueAfterTextError, setContinueAfterTextError] = useState('')
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
      if (data.id) {
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
      if (data.folders) setContentFolders(data.folders)
    } catch (e) {
      console.error('fetchContentFolders:', e)
    }
  }, [])

  // Fetch dès que la génération texte a été lancée, puis poll pendant qu'elle tourne.
  useEffect(() => {
    if (!job || !selectedJobId) return
    if (!['tts_launched', 'audio_running', 'audio_completed', 'audio_launched', 'audio_error'].includes(job.status)) return
    fetchContentFolders(selectedJobId)
    // Poll toutes les 3s tant qu'au moins un dossier n'a pas fini son texte
    const interval = setInterval(() => {
      const allDone = contentFolders.length > 0 &&
        contentFolders.every(f => f.content_status === 'completed')
      if (!allDone) fetchContentFolders(selectedJobId)
    }, 3000)
    return () => clearInterval(interval)
  }, [selectedJobId, job?.status, contentFolders.length, fetchContentFolders])

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

  const handleContinueAfterText = async (folderId) => {
    setContinueAfterTextError('')
    setContinuingAfterTextFolders(prev => ({ ...prev, [folderId]: true }))
    try {
      const resp = await fetch(
        apiUrl(`/api/formation/${selectedJobId}/content/${folderId}/continue-after-text`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            model: job?.auto_pilot_model,
            max_slides: 60,
            pace: 'normal',
          }),
        },
      )
      const data = await resp.json()
      if (resp.status !== 202 || data.error) {
        setContinueAfterTextError(data.error || `Erreur ${resp.status}`)
        setContinuingAfterTextFolders(prev => { const n = { ...prev }; delete n[folderId]; return n })
        return
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
  // Filet de sécurité POST-génération : si une journée totalise <90 000 mots,
  // l'utilisateur peut lancer un agent Claude Code qui enrichit (append-only)
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
      if (data.folders) setVolumeAudit(data)
    } catch (e) {
      // Silencieux : endpoint optionnel
    }
  }, [])

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
      for (const f of contentFolders) {
        const processed = (f.segments_reviewed || 0) + (f.segments_review_errors || 0)
        const reviewDone = f.segments_completed > 0 && processed >= f.segments_completed
        const audioClean = (f.dirty_segments || 0) === 0
        if (next[f.folder_id] && reviewDone && audioClean) {
          delete next[f.folder_id]
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [contentFolders])

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

  // ─── Étape 6 — lancement de la synthèse audio Fish Audio ──────────────────
  // 3 modes de synthèse audio dans l'étape 7 :
  // - mock=true       → MP3 silence 1s, test gratuit (ne produit aucun audio réel)
  // - basicTts=true   → gTTS (Google, voix basique gratuite) — vraie voix, utile
  //                      pour vérifier le flux et écouter le texte sans payer Fish
  // - (par défaut)    → Fish Audio S2-Pro (voix studio payante)
  const handleLaunchAudio = async (mock = false, basicTts = false, syncSlides = false, autoGenerateSlides = false) => {
    setLaunchingAudio(true)
    setAudioError('')
    try {
      const resp = await fetch(apiUrl(`/api/formation/${selectedJobId}/launch-audio`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          mock,
          basic_tts: basicTts,
          sync_slides: syncSlides,
          auto_generate_slides: autoGenerateSlides,
        }),
      })
      const data = await resp.json()
      if (data.error) setAudioError(data.error)
      else {
        await fetchJob(selectedJobId)
        await fetchJobs()
        // Re-fetch le module : son champ voice_type vient d'être mis à jour
        // par le backend (cf. launch_audio → UPDATE formation_modules).
        await fetchLinkedModule(selectedJobId)
        await fetchPipelineDiagnostic(selectedJobId, { silent: true })
      }
    } catch (e) {
      setAudioError('Erreur réseau')
    } finally {
      setLaunchingAudio(false)
    }
  }

  const handleJobCreated = async (jobId) => {
    setShowNew(false)
    setSelectedJobId(jobId)
    await fetchJobs()
  }

  const handleSelectJob = (j) => {
    setSelectedJobId(j.id)
    setJob(j)
    setGlobalProgram(j.global_program || '')
    setDailyPrograms([])
    setDailyEditIdx(null)
    setActionError('')
    setTtsResult(null)
    setPipelineDiagnostic(null)
    setPipelineDiagnosticError('')
  }

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

  // Le statut backend reste 'tts_launched' tant que l'admin n'a pas cliqué
  // "Lancer la synthèse TTS". Mais si tous les folders ont leur texte généré,
  // l'étape 5 est en réalité terminée et l'étape 6 attend l'action utilisateur.
  // On avance currentStep à 6 pour que l'UI reflète l'état réel : étape 5 OK,
  // étape 6 active (bouton "Lancer le TTS" disponible).
  let currentStep = job ? statusToStep(job.status, job) : -1
  if (job?.status === 'tts_launched' && allContentCompleted) {
    currentStep = 6
  }
  const audioBusy = launchingAudio || AUDIO_ACTIVE_STATUSES.has(job?.status)
  const selectedPipelineModel = pipelineModelLabel(job?.auto_pilot_model)

  // ─── Render ───────────────────────────────────────────────────────────────
  return (
    <div style={S.page}>
      {/* Top bar */}
      <div style={S.topBar}>
        <div style={{ fontSize: '22px', color: '#8B5CF6' }}><Icon name="school" /></div>
        <h1 style={S.topBarTitle}>Pipeline Formation</h1>
        <div style={{ flex: 1 }} />
        <button style={S.btn('ghost')} onClick={() => { setShowNew(v => !v); setSelectedJobId(null) }}>
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

            {/* Bandeau auto-pilot — affiché quand l'orchestration automatique
                est active. Permet à l'utilisateur de comprendre que la pipeline
                tourne sans intervention et qu'il n'a pas besoin de cliquer. */}
            {autoPilotState && autoPilotState.status === 'running' && (
              <div style={{
                padding: '14px 18px',
                marginBottom: '20px',
                borderRadius: '12px',
                background: 'linear-gradient(135deg, rgba(59,130,246,0.15), rgba(139,92,246,0.08))',
                border: '1px solid rgba(59,130,246,0.4)',
                display: 'flex',
                alignItems: 'center',
                gap: '14px',
                flexWrap: 'wrap',
              }}>
                <div style={{
                  width: '38px', height: '38px', borderRadius: '10px',
                  background: 'rgba(59,130,246,0.2)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <Icon name="autorenew" style={{ fontSize: '22px', color: '#60a5fa' }} className="material-icons" />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '14px', fontWeight: 700, color: '#60a5fa' }}>
                    Auto-pilot en cours — étape : {(() => {
                      const labels = {
                        start: 'démarrage', reac: 'téléchargement REAC',
                        kb: 'enrichissement Knowledge Base', global: 'programme global',
                        daily: 'programmes journée', content: 'génération texte (long)',
                        volume_safety: 'sécurité volume',
                        review: 'révision conformité',
                        post_review_docs: 'document final',
                        audio: 'synthèse audio', done: 'terminé', '?': '—',
                      }
                      return labels[autoPilotState.step] || autoPilotState.step
                    })()}
                  </div>
                  <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                    Toutes les étapes s'enchaînent automatiquement — TTS : <strong>{autoPilotState.tts_mode || 'gtts'}</strong>
                    {' · '}modèle : <strong>{pipelineModelLabel(autoPilotState.model)}</strong>
                    {' · '}stop-on-error
                  </div>
                </div>
              </div>
            )}
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
              {['tts_launched', 'audio_running', 'audio_completed', 'audio_launched', 'audio_error'].includes(job.status) || ttsResult || (contentFolders.length > 0 && contentFolders.some(f => f.content_status === 'completed')) ? (
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
                      const continuingAfterText = !!continuingAfterTextFolders[folder.folder_id]
                      return (
                        <div key={folder.folder_id} style={{
                          background: 'rgba(15,23,42,0.5)',
                          border: `1px solid ${isError ? 'rgba(239,68,68,0.3)' : isDone ? 'rgba(16,185,129,0.25)' : 'rgba(99,102,241,0.2)'}`,
                          borderRadius: '10px',
                          padding: '12px 14px',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
                            <div style={{ minWidth: 0, flex: '1 1 220px' }}>
                              <div style={{ fontSize: '14px', fontWeight: 600, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                Jour {folder.day_number} — {folder.day_title}
                              </div>
                              <div style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>
                                {isDone
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
                                      <Icon name="verified" style={{ fontSize: '12px' }} /> Conformité révisée ({nRev} segments)
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
                            </div>
                            {/* ─── 3 sous-zones du flux d'une journée ──────────
                                 1. Texte généré (lecture / téléchargements / rapport)
                                 2. Sécurité volume (enrichissement si <90k mots)
                                 3. Révision conformité (audit règles #1-#27)
                                 Séparées par des FlowArrowDown pour matérialiser
                                 l'ordre du flux : génération → volume → révision. */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                              {/* ── Zone 1 : Texte généré ──────────────────── */}
                              <div style={{
                                padding: '8px 10px',
                                borderRadius: '8px',
                                background: 'rgba(167, 139, 250, 0.06)',
                                borderLeft: '3px solid rgba(167, 139, 250, 0.5)',
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
                                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                                  <button
                                    style={{
                                      ...S.btn('ghost'),
                                      padding: '6px 12px',
                                      fontSize: '12px',
                                      borderColor: 'rgba(251, 191, 36, 0.35)',
                                      color: '#fbbf24',
                                    }}
                                    disabled={!isDone || continuingAfterText}
                                    onClick={() => handleContinueAfterText(folder.folder_id)}
                                    title="Conserve le Word initial, remet à zéro les étapes aval, puis relance volume, conformité, Word 2, slides et gTTS synchronisé"
                                  >
                                    <Icon name={continuingAfterText ? 'hourglass_empty' : 'play_arrow'} />
                                    {continuingAfterText ? 'Relance aval…' : 'Continuer après le texte'}
                                  </button>
                                  <button
                                    style={{ ...S.btn('neutral'), padding: '6px 12px', fontSize: '12px' }}
                                    disabled={!isDone}
                                    onClick={() => setViewingFolder(folder)}
                                    title={isDone ? 'Lire le texte de la journée' : 'En attente de génération'}
                                  >
                                    <Icon name="visibility" /> Voir
                                  </button>
                                  <button
                                    style={{ ...S.btn('neutral'), padding: '6px 12px', fontSize: '12px' }}
                                    disabled={!isDone}
                                    onClick={() => window.open(`/generated-slides?job_id=${selectedJobId}&folder_id=${folder.folder_id}`, '_blank')}
                                    title={isDone ? 'Prévisualiser les slides générées depuis le texte' : 'En attente de génération'}
                                  >
                                    <Icon name="slideshow" /> Slides
                                  </button>
                                  {/* Word original = snapshot pris au finalize content,
                                      AVANT que la révision conformité ne touche au texte.
                                      Permet la comparaison avant/après. */}
                                  <button
                                    style={{ ...S.btn('primary'), padding: '6px 12px', fontSize: '12px' }}
                                    disabled={!isDone}
                                    onClick={() => handleDownloadDocx(folder.folder_id, 'pre_review')}
                                    title={isDone
                                      ? 'Télécharger le Word AVANT révision conformité (texte tel que généré)'
                                      : 'En attente de génération'}
                                  >
                                    <Icon name="description" /> Word
                                  </button>
                                  {/* Word 2 = texte ACTUEL en DB (= post-révision si appliquée). */}
                                  {(folder.segments_reviewed || 0) > 0 && (
                                    <button
                                      style={{
                                        ...S.btn('primary'),
                                        padding: '6px 12px',
                                        fontSize: '12px',
                                        background: 'linear-gradient(135deg, #34d399, #10b981)',
                                      }}
                                      disabled={!isDone}
                                      onClick={() => handleDownloadDocx(folder.folder_id, 'current')}
                                      title="Télécharger le Word APRÈS révision conformité (texte révisé, utilisé pour le TTS)"
                                    >
                                      <Icon name="description" /> Word 2
                                    </button>
                                  )}
                                  {/* Bouton "Rapport" — stats détaillées de la dernière révision. */}
                                  {(folder.segments_reviewed || 0) > 0 && (
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
                                      <Icon name="assessment" /> Rapport
                                    </button>
                                  )}
                                </div>
                              </div>

                              <FlowArrowDown height={18} />

                              {/* ── Zone 2 : Sécurité volume ───────────────── */}
                              <div style={{
                                padding: '8px 10px',
                                borderRadius: '8px',
                                background: 'rgba(245, 158, 11, 0.05)',
                                borderLeft: '3px solid rgba(245, 158, 11, 0.5)',
                              }}>
                                <div style={{
                                  fontSize: '10px',
                                  fontWeight: 700,
                                  color: '#fbbf24',
                                  textTransform: 'uppercase',
                                  letterSpacing: '0.08em',
                                  marginBottom: '6px',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '5px',
                                }}>
                                  <Icon name="auto_fix_high" style={{ fontSize: '12px' }} /> Sécurité volume <span style={{ fontWeight: 400, opacity: 0.7, textTransform: 'none', letterSpacing: 'normal' }}>· cible 90k mots</span>
                                </div>
                                {(() => {
                                  const folderAudit = (volumeAudit?.folders || []).find(f => f.folder_id === folder.folder_id)
                                  const deficit = folderAudit?.deficit || 0
                                  const running = !!safetyRunning[folder.folder_id]
                                  const atTarget = isDone && deficit === 0 && folderAudit
                                  const disabled = !isDone || running || atTarget
                                  return (
                                    <button
                                      style={{ ...S.btn('ghost'), padding: '6px 12px', fontSize: '12px' }}
                                      disabled={disabled}
                                      onClick={() => handleLaunchVolumeSafety(folder.folder_id, 'api')}
                                      title={
                                        !isDone
                                          ? 'En attente de génération'
                                          : running
                                            ? 'Enrichissement en cours'
                                            : atTarget
                                              ? `Volume OK (${folderAudit.total_words.toLocaleString('fr-FR')} mots ≥ 90k)`
                                              : `Compléter via API jusqu'à 90k (déficit ${deficit.toLocaleString('fr-FR')} mots)`
                                      }
                                    >
                                      <Icon name={running ? 'hourglass_empty' : (atTarget ? 'check_circle' : 'auto_fix_high')} />{' '}
                                      {running
                                        ? 'Enrichissement…'
                                        : atTarget
                                          ? 'Volume OK'
                                          : 'Compléter le volume via API'}
                                    </button>
                                  )
                                })()}
                              </div>

                              <FlowArrowDown height={18} />

                              {/* ── Zone 3 : Révision conformité ───────────── */}
                              <div style={{
                                padding: '8px 10px',
                                borderRadius: '8px',
                                background: 'rgba(52, 211, 153, 0.05)',
                                borderLeft: '3px solid rgba(52, 211, 153, 0.5)',
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
                                  <Icon name="rule" style={{ fontSize: '12px' }} /> Révision conformité <span style={{ fontWeight: 400, opacity: 0.7, textTransform: 'none', letterSpacing: 'normal' }}>· règles #1-#27</span>
                                </div>
                                {(() => {
                                  const reviewing = !!reviewingFolders[folder.folder_id]
                                  const nRev = folder.segments_reviewed || 0
                                  const nErr = folder.segments_review_errors || 0
                                  const nComp = folder.segments_completed || 0
                                  const allClean = isDone && nComp > 0 && nRev >= nComp && nErr === 0 && !reviewing
                                  const hasRetryable = nErr > 0
                                  const disabled = !isDone || reviewing || allClean
                                  return (
                                    <button
                                      style={{ ...S.btn('ghost'), padding: '6px 12px', fontSize: '12px' }}
                                      disabled={disabled}
                                      onClick={() => handleReviewFolder(folder.folder_id)}
                                      title={
                                        !isDone
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
                    ~90 000 mots par journée. Cette étape ne fait pas encore la synthèse audio — vous pourrez relire les textes et les télécharger en PDF avant de lancer le TTS.
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

            {/* Pendant Claude Code — étape 6 (Génération cours texte) + étape 6bis (Révision) */}
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

                {/* ── Étape intermédiaire : Sécurité volume (90 000 mots/journée) ──
                    Entre la génération texte et la révision conformité. Audite
                    le total_words par folder ; si <90k, propose un enrichissement
                    Claude Code (append-only, règles #1-#27). */}
                {volumeAudit && volumeAudit.folders && volumeAudit.folders.length > 0 && (
                  <FlowArrowDown height={20} />
                )}
                {volumeAudit && volumeAudit.folders && volumeAudit.folders.length > 0 && (
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
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '13px', color: '#fbbf24', fontWeight: 600, flex: 1, minWidth: 0 }}>
                        Sécurité volume — {volumeAudit.target.toLocaleString('fr-FR')} mots / journée
                      </span>
                      <select
                        value={safetyModel}
                        onChange={e => setSafetyModel(e.target.value)}
                        style={{
                          background: 'rgba(15,23,42,0.8)',
                          color: '#e2e8f0',
                          border: '1px solid rgba(245,158,11,0.3)',
                          borderRadius: '6px',
                          padding: '4px 8px',
                          fontSize: '12px',
                        }}
                      >
                        <option value="pro">DeepSeek Pro</option>
                        <option value="flash">DeepSeek Flash</option>
                        <option value="sonnet">Claude Sonnet</option>
                        <option value="haiku">Claude Haiku</option>
                      </select>
                    </div>

                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                      Audit après génération · si une journée fait moins de 90 000 mots, un agent
                      Claude Code enrichit (append-only) les segments les plus courts en respectant
                      les règles #1-#27.
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {volumeAudit.folders.map(fa => {
                        const total = fa.total_words || 0
                        const target = volumeAudit.target
                        const pct = Math.min(100, Math.round((total / target) * 100))
                        const isOk = total >= target
                        const isLow = total < 80000
                        const color = isOk ? '#34d399' : isLow ? '#f87171' : '#fbbf24'
                        const running = !!safetyRunning[fa.folder_id]
                        return (
                          <div key={fa.folder_id} style={{
                            background: 'rgba(15,23,42,0.4)',
                            borderRadius: '8px',
                            padding: '8px 10px',
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                              <div style={{ minWidth: 0, flex: 1 }}>
                                <div style={{ fontSize: '12px', color: '#e2e8f0' }}>
                                  Jour {fa.day_number} —{' '}
                                  <strong style={{ color }}>{total.toLocaleString('fr-FR')}</strong>
                                  <span style={{ color: '#64748b' }}> / {target.toLocaleString('fr-FR')}</span>
                                </div>
                                <div style={{
                                  marginTop: '4px',
                                  height: '4px',
                                  borderRadius: '2px',
                                  background: 'rgba(30,41,59,0.8)',
                                  overflow: 'hidden',
                                }}>
                                  <div style={{
                                    width: `${pct}%`,
                                    height: '100%',
                                    background: color,
                                    transition: 'width 0.3s',
                                  }} />
                                </div>
                              </div>
                              {isOk ? (
                                <span style={{ fontSize: '11px', color: '#34d399', fontWeight: 600 }}>
                                  <Icon name="check_circle" style={{ fontSize: '13px' }} /> OK
                                </span>
                              ) : (
                                <button
                                  style={{
                                    ...S.btn('primary'),
                                    background: 'linear-gradient(135deg, #f59e0b, #fbbf24)',
                                    boxShadow: '0 4px 15px rgba(251,191,36,0.25)',
                                    padding: '5px 10px',
                                    fontSize: '11px',
                                  }}
                                  disabled={running}
                                  onClick={() => handleLaunchVolumeSafety(fa.folder_id)}
                                  title={`Enrichit les ${Math.min(5, fa.shortest_segments?.length || 0)} segments les plus courts (déficit ${fa.deficit.toLocaleString('fr-FR')} mots)`}
                                >
                                  <Icon name={running ? 'hourglass_empty' : 'auto_fix_high'} style={{ fontSize: '13px' }} />{' '}
                                  {running ? 'Enrichissement…' : 'Compléter'}
                                </button>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    {safetyError && (
                      <div style={{ fontSize: '12px', color: '#f87171' }}>
                        {safetyError}
                      </div>
                    )}
                  </div>
                )}

                <FlowArrowDown height={20} />
                <div>
                  <ClaudeCodeStepActions
                    stepKey="review"
                    stepLabel="Révision conformité (étape 6bis)"
                    jobId={selectedJobId}
                    disabled={!['tts_launched', 'audio_running', 'audio_completed', 'audio_launched', 'audio_error'].includes(job.status)}
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

            {/* ─── Connecteur fin-pipeline : merge des 2 colonnes vers TTS ── */}
            {DUAL_COLUMN_ENABLED ? <FlowMerge /> : <FlowArrowDown />}

            {/* ── Étape 7 : Synthèse TTS Fish Audio ── */}
            <StepBlock stepIndex={6} currentStep={currentStep} status={job.status} title="Synthèse TTS Fish Audio" icon="record_voice_over">
              {AUDIO_DONE_STATUSES.has(job.status) || AUDIO_ACTIVE_STATUSES.has(job.status) ? (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: AUDIO_ACTIVE_STATUSES.has(job.status) ? '#fbbf24' : '#34d399', fontSize: '15px', fontWeight: 600, marginBottom: '12px' }}>
                    <Icon name={AUDIO_ACTIVE_STATUSES.has(job.status) ? 'hourglass_empty' : 'check_circle'} />{' '}
                    {AUDIO_ACTIVE_STATUSES.has(job.status) ? 'Synthèse audio en cours' : 'Synthèse audio terminée'}
                  </div>
                  <div style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '16px' }}>
                    {contentFolders.length || job.nb_days} dossiers cours dans la plateforme{' '}
                    <strong style={{ color: '#a78bfa' }}>{job.platform_name || `#${job.platform_id}`}</strong>.
                    Le diagnostic ci-dessous suit les événements audio, les erreurs et l'état des segments.
                  </div>

                  {/* Module persistant créé à la fin de la pipeline — matérialise le
                      principe "1 RNCP = 1 module durable" : ce module est sélectionnable
                      dans la modale "Nouvelle plateforme" pour créer des promos. */}
                  {linkedModule && (
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '12px',
                      padding: '14px 16px',
                      marginBottom: '16px',
                      borderRadius: '10px',
                      background: 'linear-gradient(135deg, rgba(139, 92, 246, 0.12), rgba(139, 92, 246, 0.04))',
                      border: '1px solid rgba(139, 92, 246, 0.35)',
                    }}>
                      <Icon name="inventory_2" className="text-2xl" style={{ color: '#a78bfa' }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: '13px', color: '#a78bfa', fontWeight: 600, marginBottom: '2px' }}>
                          <Icon name="check" className="text-sm" /> Module créé et disponible
                        </div>
                        <div style={{ fontSize: '15px', color: '#e2e8f0', fontWeight: 600 }}>
                          {linkedModule.tp_name} — RNCP {linkedModule.rncp_code || '?'} — <span style={{ color: '#a78bfa' }}>{linkedModule.version}</span>
                        </div>
                        {linkedModule.voice_type && (
                          <div style={{ fontSize: '12px', marginTop: '4px' }}>
                            <Icon name="record_voice_over" style={{ fontSize: '13px', color: voiceColor(linkedModule.voice_type) }} />{' '}
                            <span style={{ color: '#94a3b8' }}>Voix actuelle des MP3 :</span>{' '}
                            <strong style={{ color: voiceColor(linkedModule.voice_type) }}>{voiceLabel(linkedModule.voice_type)}</strong>
                          </div>
                        )}
                        <div style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>
                          Ce module peut désormais être sélectionné dans "Nouvelle plateforme" pour créer autant de promos que nécessaire sans relancer la pipeline.
                          {linkedModule.voice_type && ' Relancer le TTS avec une voix différente met à jour les MP3 et la voix du module en place.'}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Bouton relancer : utile quand le précédent run a échoué (ex: force_all bug)
                      ou si on veut re-générer les MP3 suite à une édition de texte.
                      3 voies : silence (0€), gTTS (0€, vraie voix basique), Fish Audio (payant). */}
                  <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                    <button
                      style={{ ...S.btn('neutral'), border: '1px dashed #64748b' }}
                      onClick={() => handleLaunchAudio(true, false)}
                      disabled={audioBusy || !allContentCompleted}
                      title="Re-génère les 7 MP3 cours en mode mock (silence 1s). 0€."
                    >
                      <Icon name="refresh" /> {audioBusy ? '…' : 'Relancer TTS test (gratuit)'}
                    </button>
                    <button
                      style={{ ...S.btn('ghost'), borderColor: 'rgba(251,146,60,0.35)', color: '#fb923c' }}
                      onClick={() => handleLaunchAudio(false, true)}
                      disabled={audioBusy || !allContentCompleted}
                      title="Re-synthèse via gTTS (Google Text-to-Speech, gratuit, voix basique). Permet d'écouter le texte sans payer Fish Audio."
                    >
                      <Icon name="graphic_eq" /> {audioBusy ? '…' : 'Relancer TTS voix basique (gratuit)'}
                    </button>
                    <button
                      style={{ ...S.btn('ghost'), borderColor: 'rgba(56,189,248,0.45)', color: '#38bdf8' }}
                      onClick={() => handleLaunchAudio(false, true, true, true)}
                      disabled={audioBusy || !allContentCompleted}
                      title="Re-synthèse gratuite via gTTS, découpée par slides, avec stockage des timings slide ↔ audio."
                    >
                      <Icon name="slideshow" /> {audioBusy ? '…' : 'Relancer TTS slides + voix basique'}
                    </button>
                    <button
                      style={S.btn('success')}
                      onClick={() => handleLaunchAudio(false, false)}
                      disabled={audioBusy || !allContentCompleted}
                      title="Re-synthèse payante Fish Audio S2-Pro (~9$/journée)."
                    >
                      <Icon name="refresh" /> {audioBusy ? 'Lancement…' : 'Relancer TTS payant'}
                    </button>
                    <button
                      style={S.btn('success')}
                      onClick={() => handleLaunchAudio(false, false, true, true)}
                      disabled={audioBusy || !allContentCompleted}
                      title="Re-synthèse payante Fish Audio S2-Pro avec découpage par slides et timings synchronisés."
                    >
                      <Icon name="slideshow" /> {audioBusy ? 'Lancement…' : 'Relancer TTS slides payant'}
                    </button>
                  </div>
                  {audioError && (
                    <div style={{ fontSize: '12px', color: '#f87171', marginTop: '8px' }}>{audioError}</div>
                  )}
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '8px' }}>
                    Lance la synthèse <strong style={{ color: '#a78bfa' }}>Fish Audio S2-Pro</strong> pour toutes les journées : 19 MP3 par jour (cours + Q&A + pauses).
                  </p>
                  <p style={{ fontSize: '13px', color: '#475569', marginBottom: '16px' }}>
                    Compter ~1h à 2h par journée. Étape irréversible côté facturation Fish Audio — vérifiez d'abord les textes via "Voir" ou "PDF" ci-dessus.
                  </p>
                  <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                    <button
                      style={S.btn('success')}
                      onClick={() => handleLaunchAudio(false, false)}
                      disabled={audioBusy || !allContentCompleted}
                    >
                      <Icon name="record_voice_over" /> {audioBusy ? 'Lancement…' : `Lancer le TTS (${contentFolders.length || job.nb_days} journées)`}
                    </button>
                    <button
                      style={{ ...S.btn('ghost'), borderColor: 'rgba(251,146,60,0.35)', color: '#fb923c' }}
                      onClick={() => handleLaunchAudio(false, true)}
                      disabled={audioBusy || !allContentCompleted}
                      title="Synthèse via gTTS (Google Text-to-Speech, gratuit, voix basique). Utile pour écouter le rendu sans payer Fish Audio."
                    >
                      <Icon name="graphic_eq" /> {audioBusy ? '…' : 'TTS voix basique (gratuit)'}
                    </button>
                    <button
                      style={{ ...S.btn('ghost'), borderColor: 'rgba(56,189,248,0.45)', color: '#38bdf8' }}
                      onClick={() => handleLaunchAudio(false, true, true, true)}
                      disabled={audioBusy || !allContentCompleted}
                      title="Test complet sans Fish Audio : génère les slides si besoin, synthétise en gTTS, concatène par slide et stocke les timings."
                    >
                      <Icon name="slideshow" /> {audioBusy ? '…' : 'TTS slides + voix basique'}
                    </button>
                    <button
                      style={{ ...S.btn('neutral'), border: '1px dashed #64748b' }}
                      onClick={() => handleLaunchAudio(true, false)}
                      disabled={audioBusy || !allContentCompleted}
                      title="Mode test : génère des MP3 de silence 1s au lieu d'appeler Fish Audio. 0 € de coût, permet de tester le flux jusqu'à la diffusion sans consommer ton budget TTS."
                    >
                      <Icon name="science" /> {audioBusy ? '…' : 'TTS test silence (gratuit)'}
                    </button>
                    <button
                      style={S.btn('success')}
                      onClick={() => handleLaunchAudio(false, false, true, true)}
                      disabled={audioBusy || !allContentCompleted}
                      title="Synthèse payante Fish Audio avec génération des slides si besoin, découpage par slides et stockage des timings."
                    >
                      <Icon name="slideshow" /> {audioBusy ? 'Lancement…' : 'TTS slides payant'}
                    </button>
                  </div>
                  {!allContentCompleted && (
                    <div style={{ fontSize: '12px', color: '#f87171', marginTop: '8px' }}>
                      Toutes les journées doivent avoir leur texte généré pour lancer la synthèse.
                    </div>
                  )}
                  {audioError && (
                    <div style={{ fontSize: '12px', color: '#f87171', marginTop: '8px' }}>{audioError}</div>
                  )}
                </div>
              )}
              <PipelineDiagnosticPanel
                diagnostic={pipelineDiagnostic}
                loading={pipelineDiagnosticLoading}
                error={pipelineDiagnosticError}
                onRefresh={() => fetchPipelineDiagnostic(selectedJobId)}
              />
            </StepBlock>
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
function ReviewReportModal({ jobId, folder, onClose }) {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedSegments, setExpandedSegments] = useState({})

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const resp = await fetch(
          apiUrl(`/api/formation/${jobId}/content/${folder.folder_id}/review-report`),
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
            <div style={{ fontSize: '13px', color: '#34d399', fontWeight: 600, marginBottom: '4px' }}>
              <Icon name="assessment" style={{ fontSize: '14px' }} /> Rapport de révision conformité
            </div>
            <div style={{ fontSize: '15px', color: '#e2e8f0', fontWeight: 600 }}>
              {folder.folder_name || `Dossier ${folder.folder_id}`}
            </div>
            {report?.imported_at && (
              <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                Importé le {new Date(report.imported_at).toLocaleString('fr-FR')}
                {report.generated_via && ` · ${report.generated_via}`}
                {report.via_positional_fallback && ' · résolution positionnelle (ids segment obsolètes)'}
              </div>
            )}
            {report?.is_reconstructed && (
              <div style={{
                fontSize: '11px', color: '#fbbf24', marginTop: '6px',
                padding: '6px 10px', background: 'rgba(251, 191, 36, 0.08)',
                borderLeft: '3px solid #fbbf24', borderRadius: '4px',
                lineHeight: 1.4,
              }}>
                <Icon name="info" style={{ fontSize: '12px' }} /> <strong>Rapport reconstitué</strong>
                {' — '}{report.reconstruction_note}
              </div>
            )}
            {report?.is_db_fallback && (
              <div style={{
                fontSize: '11px', color: '#38bdf8', marginTop: '6px',
                padding: '6px 10px', background: 'rgba(56, 189, 248, 0.08)',
                borderLeft: '3px solid #38bdf8', borderRadius: '4px',
                lineHeight: 1.4,
              }}>
                <Icon name="info" style={{ fontSize: '12px' }} /> <strong>Rapport reconstruit depuis la base</strong>
                {' — '}{report.reconstruction_note}
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
