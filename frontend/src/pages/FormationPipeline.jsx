import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '../api'
import './FormationPipeline.css'

const PIPELINE_STAGES = [
  { key: 'reac', label: 'Référentiel RNCP', icon: 'description' },
  { key: 'kb', label: 'Base de connaissances', icon: 'library_books' },
  { key: 'global', label: 'Programme global', icon: 'account_tree' },
  { key: 'daily', label: 'Programmes journée', icon: 'calendar_view_week' },
  { key: 'content', label: 'Contenus pédagogiques', icon: 'menu_book' },
  { key: 'review', label: 'Contrôle de conformité', icon: 'rule' },
  { key: 'post_review_docs', label: 'Documents validés', icon: 'fact_check' },
  { key: 'slides', label: 'Supports de cours', icon: 'slideshow' },
  { key: 'finalize_text', label: 'Finalisation', icon: 'verified' },
]

const LEGACY_OVERVIEW_STAGES = [
  { key: 'start', label: 'Recherche RNCP', icon: 'search' },
  { key: 'reac', label: 'Téléchargement REAC', icon: 'download' },
  { key: 'kb', label: 'Enrichissement KB', icon: 'psychology' },
  { key: 'global', label: 'Programme global', icon: 'auto_stories' },
  { key: 'daily', label: 'Programmes journée', icon: 'calendar_view_week' },
  { key: 'done', label: 'Texte + slides', icon: 'slideshow' },
]

const DETAILED_PIPELINE_STAGES = [
  {
    key: 'start',
    title: 'Initialisation RNCP et plateforme',
    detail: 'Création du job, contrôle du RNCP et verrouillage de la plateforme cible.',
    icon: 'search',
    majorStep: 'start',
    signals: ['initialisation', 'pipeline_started', 'job_created'],
  },
  {
    key: 'reac',
    title: 'Téléchargement REAC',
    detail: 'Récupération des sources officielles avant l’enrichissement métier.',
    icon: 'download',
    majorStep: 'reac',
    signals: ['reac'],
  },
  {
    key: 'kb',
    title: 'Enrichissement Knowledge Base',
    detail: 'Compétences, cas terrain, pièges fréquents et vocabulaire métier.',
    icon: 'psychology',
    majorStep: 'kb',
    signals: ['knowledge_base', 'enrichissement', 'kb_'],
  },
  {
    key: 'global',
    title: 'Programme global',
    detail: 'Architecture complète de la formation à partir du REAC enrichi.',
    icon: 'auto_stories',
    majorStep: 'global',
    signals: ['global_program', 'programme_global'],
  },
  {
    key: 'daily',
    title: 'Programmes journée',
    detail: 'Découpage pédagogique par journées, thèmes et chapitres.',
    icon: 'calendar_view_week',
    majorStep: 'daily',
    signals: ['daily_program', 'programmes_journee', 'daily_'],
  },
  {
    key: 'plan_json',
    title: 'Plan JSON verrouillé',
    detail: 'Validation de la structure, des budgets, des cours et des conclusions.',
    icon: 'schema',
    majorStep: 'content',
    signals: ['plan_json', 'content-plan', 'structured_plan', 'plan_locked'],
    artifacts: ['content-plan.json'],
  },
  {
    key: 'slide_beats',
    title: 'Moments pédagogiques et ancrages visuels',
    detail: 'Exemples, conseils, pièges et comparaisons reliés au plan.',
    icon: 'account_tree',
    majorStep: 'content',
    signals: ['slide_beat', 'anchor', 'ancrage'],
    artifacts: ['content-plan.json'],
  },
  {
    key: 'section_generation',
    title: 'Génération par section, texte V1',
    detail: 'Production des journées section par section avec checkpoints durables.',
    icon: 'edit_note',
    majorStep: 'content',
    signals: ['section_generation', 'structured_section', 'content_generation'],
    artifacts: ['content-draft-sections.json'],
  },
  {
    key: 'plan_adherence',
    title: 'Adhérence au plan',
    detail: 'Contrôle de l’ordre, des reprises, des conclusions et des doublons.',
    icon: 'rule',
    majorStep: 'content',
    signals: ['plan_adherence', 'adherence'],
    artifacts: ['content-quality-reviews.json'],
  },
  {
    key: 'budget_calibration',
    title: 'Calibrage budget texte',
    detail: 'Alignement des volumes de mots avant les contrôles de conformité.',
    icon: 'speed',
    majorStep: 'content',
    signals: ['budget_calibration', 'word_budget', 'calibration'],
    artifacts: ['content-budget-calibration.json'],
  },
  {
    key: 'ethical_micro',
    title: 'Micro-conformité éthique',
    detail: 'Contrôle des règles éthiques sur le texte calibré.',
    icon: 'shield',
    majorStep: 'content',
    signals: ['ethical_micro', 'micro_review', 'ethique'],
    artifacts: ['content-ethical-micro-review.json'],
  },
  {
    key: 'structured_artifacts',
    title: 'Artefacts structurés',
    detail: 'Persistance des plans, brouillons, scripts et scripts révisés.',
    icon: 'data_object',
    majorStep: 'content',
    signals: ['structured_artifact', 'artifact', 'course_scripts'],
    artifacts: ['content-course-scripts.json', 'content-reviewed-scripts.json'],
  },
  {
    key: 'local_compliance',
    title: 'Conformité par morceau',
    detail: 'Relecture locale des hallucinations, du style oral et de l’architecture.',
    icon: 'verified_user',
    majorStep: 'review',
    signals: ['review', 'local_compliance', 'conformite'],
  },
  {
    key: 'post_review_docs',
    title: 'Texte validé, Word 2 et audio-plan',
    detail: 'Assemblage du texte validé et des artefacts prêts pour les slides.',
    icon: 'description',
    majorStep: 'post_review_docs',
    signals: ['post_review_docs', 'word_2', 'audio_plan'],
    artifacts: ['content-audio-plan.json', 'content-script-plan.json'],
  },
  {
    key: 'slide_curation',
    title: 'Curation IA des slides',
    detail: 'Choix des passages visualisables, des ancrages et des templates.',
    icon: 'filter_alt',
    majorStep: 'slides',
    signals: ['slide_curation', 'curation', 'template_backlog'],
  },
  {
    key: 'slides',
    title: 'Slides anchor-first',
    detail: 'Génération des decks depuis les décisions de curation.',
    icon: 'slideshow',
    majorStep: 'slides',
    signals: ['slides', 'slide_deck'],
  },
  {
    key: 'done',
    title: 'Finalisation',
    detail: 'Texte, documents et slides prêts pour la diffusion.',
    icon: 'inventory_2',
    majorStep: 'done',
    signals: ['finalization', 'finalisation', 'pipeline_completed'],
  },
]

const MAJOR_STEP_ORDER = [
  'start',
  'reac',
  'kb',
  'global',
  'daily',
  'content',
  'review',
  'post_review_docs',
  'slides',
  'done',
]

const STEP_ALIASES = {
  start: 'reac',
  plan_adherence_review: 'review',
  audio_word_calibration: 'review',
  word_budget_review: 'review',
  finalize_text: 'done',
  done: 'done',
}

const QUEUE_ACTIVE_STATUSES = new Set(['queued', 'retry_scheduled', 'running'])
const QUEUE_RECOVERABLE_STATUSES = new Set(['dead_lettered', 'cancelled'])
const QUEUE_TERMINAL_STATUSES = new Set(['completed', 'missing'])
const JOB_FAILURE_STATUSES = new Set(['error', 'audio_error'])
const STALE_QUEUE_GAP_MS = 2 * 60 * 1000

const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`} aria-hidden="true">{name}</span>
)

function formatDate(value) {
  if (!value) return 'Date inconnue'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('fr-FR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function responseErrorMessage(response, payload, fallback) {
  if (payload?.error && response.status < 500) return payload.error
  if (response.status === 404) return 'Cette pipeline n’existe plus ou n’appartient pas à votre centre.'
  if (response.status === 401 || response.status === 403) {
    return 'Votre session ne permet plus d’accéder à cette pipeline. Reconnectez-vous.'
  }
  if (response.status >= 500) {
    return 'Le serveur ne peut pas charger cette pipeline pour le moment. Le job existe toujours et peut être repris.'
  }
  return fallback
}

function normalizeStep(step) {
  const value = String(step || '').trim()
  return STEP_ALIASES[value] || value
}

function normalizeDetailedStep(step) {
  const value = String(step || '').trim()
  if (['plan_adherence_review', 'audio_word_calibration', 'word_budget_review'].includes(value)) return 'review'
  if (value === 'finalize_text') return 'done'
  return value || 'start'
}

function formatStep(step) {
  const normalized = normalizeStep(step)
  if (normalized === 'done') return 'Finalisation'
  return PIPELINE_STAGES.find(item => item.key === normalized)?.label || 'Initialisation'
}

function hasDetachedQueue(job, autoPilotState) {
  if (!job || !autoPilotState) return false
  const queueStatus = autoPilotState.queue?.status
  if (autoPilotState.status !== 'running' || !QUEUE_TERMINAL_STATUSES.has(queueStatus)) return false
  const updatedAt = new Date(job.updated_at || job.created_at || 0).getTime()
  return Number.isFinite(updatedAt) && updatedAt > 0 && Date.now() - updatedAt > STALE_QUEUE_GAP_MS
}

function statusView(job, autoPilotState) {
  const queueStatus = autoPilotState?.queue?.status
  const autoStatus = autoPilotState?.status
  const failed = (
    autoStatus === 'error'
    || JOB_FAILURE_STATUSES.has(job?.status)
    || QUEUE_RECOVERABLE_STATUSES.has(queueStatus)
  )
  if (failed) {
    return {
      label: 'Échec',
      icon: 'error_outline',
      className: 'border-red-200 bg-red-50 text-red-700',
    }
  }
  if (autoStatus === 'stopped') {
    return {
      label: 'Interrompue',
      icon: 'pause_circle',
      className: 'border-amber-200 bg-amber-50 text-amber-800',
    }
  }
  if (hasDetachedQueue(job, autoPilotState)) {
    return {
      label: 'À reprendre',
      icon: 'warning_amber',
      className: 'border-amber-200 bg-amber-50 text-amber-800',
    }
  }
  if (
    autoStatus === 'running'
    || autoStatus === 'starting'
    || QUEUE_ACTIVE_STATUSES.has(queueStatus)
  ) {
    return {
      label: queueStatus === 'retry_scheduled' ? 'Nouvelle tentative planifiée' : 'En cours',
      icon: 'hourglass_top',
      className: 'border-violet-200 bg-violet-50 text-violet-700',
    }
  }
  if (autoStatus === 'done' || autoPilotState?.step === 'done') {
    return {
      label: 'Terminée',
      icon: 'check_circle',
      className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    }
  }
  return {
    label: 'En attente',
    icon: 'schedule',
    className: 'border-slate-200 bg-slate-50 text-slate-700',
  }
}

function pipelineError(job, autoPilotState) {
  if (hasDetachedQueue(job, autoPilotState)) {
    return 'Le job est resté actif en base, mais aucune tâche durable ne le traite actuellement.'
  }
  return (
    autoPilotState?.error
    || autoPilotState?.queue?.last_error
    || job?.auto_pilot_error
    || job?.error_message
    || ''
  )
}

function canResumePipeline(job, autoPilotState) {
  if (!job || !autoPilotState) return false
  const queueStatus = autoPilotState.queue?.status
  return Boolean(
    autoPilotState.status === 'error'
    || autoPilotState.status === 'stopped'
    || autoPilotState.lock_stale
    || hasDetachedQueue(job, autoPilotState)
    || JOB_FAILURE_STATUSES.has(job.status)
    || QUEUE_RECOVERABLE_STATUSES.has(queueStatus)
  )
}

function eventSearchText(event) {
  let payload = ''
  try {
    payload = JSON.stringify(event?.data || event?.payload || {})
  } catch {
    payload = ''
  }
  return [
    event?.step,
    event?.event_type,
    event?.status,
    event?.message,
    event?.error,
    payload,
  ].filter(Boolean).join(' ').toLowerCase()
}

function eventMatchesDetailedStage(event, stage) {
  const haystack = eventSearchText(event)
  return stage.signals.some(signal => haystack.includes(signal))
}

function eventIsComplete(event) {
  const value = `${event?.status || ''} ${event?.event_type || ''}`.toLowerCase()
  return value.includes('completed') || value.includes('success') || value.includes('validated')
}

function eventIsFailure(event) {
  const value = `${event?.status || ''} ${event?.event_type || ''}`.toLowerCase()
  return value.includes('error') || value.includes('failed') || value.includes('dead_letter')
}

function detailedStageStates(job, autoPilotState, diagnostic) {
  const events = diagnostic?.events || []
  const rawCurrentStep = autoPilotState?.step || autoPilotState?.next_step || job?.auto_pilot_step || 'start'
  const currentStep = normalizeDetailedStep(rawCurrentStep)
  const currentMajorIndex = Math.max(0, MAJOR_STEP_ORDER.indexOf(currentStep))
  const pipelineDone = autoPilotState?.status === 'done' || currentStep === 'done'
  const folders = diagnostic?.folders || []
  const allContentComplete = folders.length > 0 && folders.every(folder => folder.content_status === 'completed')
  const allReviewsComplete = folders.length > 0 && folders.every(folder => {
    const completed = Number(folder.segments_completed || 0)
    const reviewed = Number(folder.reviewed_segments || 0)
    const errors = Number(folder.review_errors || 0)
    return completed > 0 && reviewed + errors >= completed && errors === 0
  })

  const matchedEvents = DETAILED_PIPELINE_STAGES.map(stage => (
    events.filter(event => eventMatchesDetailedStage(event, stage))
  ))
  let lastReachedIndex = -1
  matchedEvents.forEach((matches, index) => {
    if (matches.length > 0) lastReachedIndex = index
  })
  if (currentStep === 'content' && lastReachedIndex < 5) lastReachedIndex = 5

  return DETAILED_PIPELINE_STAGES.map((stage, index) => {
    const stageMajorIndex = MAJOR_STEP_ORDER.indexOf(stage.majorStep)
    const matches = matchedEvents[index]
    const failedEvent = [...matches].reverse().find(eventIsFailure)
    const completedByEvent = matches.some(eventIsComplete)
    let complete = pipelineDone || stageMajorIndex < currentMajorIndex || completedByEvent
    let active = !complete && stageMajorIndex === currentMajorIndex

    if (stage.key === 'start' && job?.id && currentStep !== 'start') complete = true
    if (stage.key === 'reac' && job?.reac_available) complete = true
    if (stage.key === 'kb' && Number(job?.kb_total || 0) > 0) complete = true
    if (stage.key === 'global' && job?.global_program_validated) complete = true
    if (stage.key === 'daily' && job?.daily_programs_validated) complete = true
    if (stage.majorStep === 'content' && allContentComplete) complete = true
    if (stage.key === 'local_compliance' && allReviewsComplete) complete = true

    if (currentStep === 'content' && stage.majorStep === 'content') {
      complete = complete || index < lastReachedIndex
      active = !complete && index === lastReachedIndex
    }
    if (complete) active = false

    const failed = Boolean(
      failedEvent
      || (active && (
        autoPilotState?.status === 'error'
        || QUEUE_RECOVERABLE_STATUSES.has(autoPilotState?.queue?.status)
      ))
    )

    return {
      ...stage,
      index,
      complete,
      active,
      failed,
      matches,
      latestEvent: matches[matches.length - 1] || null,
    }
  })
}

function LegacyOverviewProgress({ job, autoPilotState, diagnostic }) {
  const detailedStates = useMemo(
    () => detailedStageStates(job, autoPilotState, diagnostic),
    [job, autoPilotState, diagnostic],
  )
  const stateForOverview = stage => {
    if (stage.key === 'done') {
      const tail = detailedStates.slice(5)
      return {
        complete: tail.length > 0 && tail.every(item => item.complete),
        active: tail.some(item => item.active),
        failed: tail.some(item => item.failed),
      }
    }
    const state = detailedStates.find(item => item.key === stage.key)
    return state || { complete: false, active: false, failed: false }
  }

  return (
    <ol className="legacy-overview" aria-label="Vue synthétique du pipeline">
      {LEGACY_OVERVIEW_STAGES.map((stage, index) => {
        const state = stateForOverview(stage)
        return (
          <li
            key={stage.key}
            className={`legacy-overview__step ${
              state.failed ? 'is-failed' : state.complete ? 'is-complete' : state.active ? 'is-active' : ''
            }`}
          >
            <span className="legacy-overview__icon">
              <Icon name={state.complete ? 'check' : state.failed ? 'error_outline' : stage.icon} />
            </span>
            <span>{stage.label}</span>
            {index < LEGACY_OVERVIEW_STAGES.length - 1 && <span className="legacy-overview__connector" aria-hidden="true" />}
          </li>
        )
      })}
    </ol>
  )
}

function DetailedRoadmap({ job, autoPilotState, diagnostic }) {
  const [selectedKey, setSelectedKey] = useState(null)
  const stages = useMemo(
    () => detailedStageStates(job, autoPilotState, diagnostic),
    [job, autoPilotState, diagnostic],
  )
  const selectedStage = stages.find(stage => stage.key === selectedKey)
  const doneCount = stages.filter(stage => stage.complete).length
  const activeStage = stages.find(stage => stage.active)

  return (
    <section className="debug-roadmap">
      <div className="debug-roadmap__header">
        <div>
          <h3><Icon name="route" /> Roadmap auto-pilot API</h3>
          <p>
            Trajet réel de fabrication : plan structuré, génération par sections, contrôles,
            artefacts et slides anchor-first.
          </p>
        </div>
        <span className={`debug-roadmap__count ${activeStage ? 'is-active' : doneCount === stages.length ? 'is-complete' : ''}`}>
          <Icon name={activeStage ? 'hourglass_empty' : 'timeline'} />
          {activeStage ? `Actif : ${activeStage.title}` : `${doneCount}/${stages.length} étapes`}
        </span>
      </div>

      <div className="debug-roadmap__grid">
        {stages.map(stage => (
          <button
            key={stage.key}
            type="button"
            className={`debug-stage ${
              stage.failed ? 'is-failed' : stage.complete ? 'is-complete' : stage.active ? 'is-active' : ''
            } ${selectedKey === stage.key ? 'is-selected' : ''}`}
            onClick={() => setSelectedKey(current => current === stage.key ? null : stage.key)}
            aria-expanded={selectedKey === stage.key}
          >
            <span className="debug-stage__icon">
              <Icon name={stage.complete ? 'check_circle' : stage.failed ? 'error' : stage.icon} />
            </span>
            <span className="debug-stage__body">
              <span className="debug-stage__meta">
                {String(stage.index + 1).padStart(2, '0')}
                <strong>{stage.failed ? 'ERREUR' : stage.complete ? 'OK' : stage.active ? 'EN COURS' : 'À VENIR'}</strong>
              </span>
              <span className="debug-stage__title">{stage.title}</span>
              <span className="debug-stage__detail">{stage.detail}</span>
            </span>
          </button>
        ))}
      </div>

      {selectedStage && (
        <div className="debug-stage-inspector" aria-live="polite">
          <div className="debug-stage-inspector__heading">
            <div>
              <span>Étape {selectedStage.index + 1}</span>
              <h4>{selectedStage.title}</h4>
            </div>
            <button type="button" onClick={() => setSelectedKey(null)} aria-label="Fermer le détail">
              <Icon name="close" />
            </button>
          </div>
          <p>{selectedStage.detail}</p>
          {selectedStage.artifacts?.length > 0 && (
            <div className="debug-stage-inspector__artifacts">
              <strong>Artefacts attendus</strong>
              {selectedStage.artifacts.map(artifact => <code key={artifact}>{artifact}</code>)}
            </div>
          )}
          <div className="debug-stage-inspector__events">
            <strong>Événements correspondants ({selectedStage.matches.length})</strong>
            {selectedStage.matches.length === 0 ? (
              <span>Aucun événement spécifique enregistré pour cette étape.</span>
            ) : (
              selectedStage.matches.slice(-6).reverse().map((event, index) => (
                <div key={event.id || `${event.created_at}-${index}`}>
                  <time>{formatDate(event.created_at)}</time>
                  <span>{event.message || event.event_type || event.step}</span>
                  {event.error && <em>{event.error}</em>}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </section>
  )
}

function healthCheckLabel(key) {
  const labels = {
    segments_completed: 'Segments texte générés',
    cg_jobs_completed: 'Jobs texte terminés',
    docx_buildable: 'Document Word final',
    pre_review_snapshotted: 'Snapshot avant review',
    review_consistent: 'Review de conformité',
    audio_tts_files: 'Segments audio à jour',
    module_persistant: 'Module persistant',
    structured_pipeline_v2: 'Pipeline structurée V2',
    health_error: 'Calcul du diagnostic',
  }
  return labels[key] || String(key || '').replace(/_/g, ' ')
}

function PipelineDiagnostics({ job, diagnostic, autoPilotState }) {
  const health = diagnostic?.health || {}
  const folders = diagnostic?.folders || []
  const checks = Object.entries(health.checks || {})
  const queue = autoPilotState?.queue || {}
  const volumeFolders = diagnostic?.volume_audit?.folders || []
  const totals = folders.reduce((result, folder) => ({
    words: result.words + Number(folder.total_words || 0),
    segments: result.segments + Number(folder.segments_completed || 0),
    reviewed: result.reviewed + Number(folder.reviewed_segments || 0),
    errors: result.errors + Number(folder.review_errors || 0),
    dirty: result.dirty + Number(folder.dirty_segments || 0),
  }), { words: 0, segments: 0, reviewed: 0, errors: 0, dirty: 0 })
  const resolution = diagnostic?.folder_resolution || {}
  const expectedFolders = Number(resolution.expected_count || folders.length || 0)
  const currentMajorIndex = MAJOR_STEP_ORDER.indexOf(normalizeDetailedStep(
    autoPilotState?.step || autoPilotState?.next_step || job?.auto_pilot_step,
  ))
  const checksPending = folders.length === 0 && currentMajorIndex >= 0 && currentMajorIndex < MAJOR_STEP_ORDER.indexOf('content')
  const detachedQueue = hasDetachedQueue(job, autoPilotState)

  return (
    <section className="pipeline-diagnostics">
      <div className="pipeline-diagnostics__header">
        <div>
          <h3><Icon name="analytics" /> Diagnostic pipeline</h3>
          <p>État brut des contrôles, de la file durable et des sorties enregistrées.</p>
        </div>
        <span className={`pipeline-diagnostics__health ${
          detachedQueue ? 'is-failed' : checksPending ? 'is-pending' : health.ok ? 'is-complete' : health.blocking?.length ? 'is-failed' : 'is-warning'
        }`}>
          <Icon name={detachedQueue ? 'error_outline' : checksPending ? 'schedule' : health.ok ? 'verified' : health.blocking?.length ? 'error_outline' : 'warning_amber'} />
          {detachedQueue ? 'Worker sans tâche active' : checksPending ? 'Contrôles à venir' : health.ok ? 'Audit OK' : health.blocking?.length ? 'Audit bloquant' : 'À surveiller'}
        </span>
      </div>

      <div className="diagnostic-metrics">
        <div><span>Journées</span><strong>{folders.length}/{expectedFolders || '—'}</strong></div>
        <div><span>Mots générés</span><strong>{totals.words.toLocaleString('fr-FR')}</strong></div>
        <div><span>Segments</span><strong>{totals.segments}</strong></div>
        <div><span>Segments revus</span><strong>{totals.reviewed}</strong></div>
        <div className={totals.errors ? 'is-failed' : ''}><span>Erreurs review</span><strong>{totals.errors}</strong></div>
        <div className={totals.dirty ? 'is-warning' : ''}><span>Audio à régénérer</span><strong>{totals.dirty}</strong></div>
      </div>

      <div className="diagnostic-columns">
        <div className="diagnostic-panel">
          <h4><Icon name="dns" /> File durable</h4>
          <dl className="diagnostic-definition-list">
            <div><dt>Statut</dt><dd data-state={queue.status}>{queue.status || 'indisponible'}</dd></div>
            <div><dt>Tentative</dt><dd>{queue.attempt ?? '—'} / {queue.max_attempts ?? '—'}</dd></div>
            <div><dt>Étape DB</dt><dd>{autoPilotState?.step || autoPilotState?.next_step || '—'}</dd></div>
            <div><dt>Work item</dt><dd title={queue.work_item_id}>{queue.work_item_id ? queue.work_item_id.slice(0, 12) : '—'}</dd></div>
          </dl>
          {(queue.last_error || queue.error) && (
            <p className="diagnostic-error"><Icon name="error_outline" /> {queue.last_error || queue.error}</p>
          )}
          {detachedQueue && (
            <p className="diagnostic-error">
              <Icon name="sync_problem" />
              La base indique une étape active, mais le dernier work item est terminé. Utilisez « Reprendre la pipeline ».
            </p>
          )}
        </div>

        <div className="diagnostic-panel">
          <h4><Icon name="folder_copy" /> Résolution des journées</h4>
          <dl className="diagnostic-definition-list">
            <div><dt>Attendues</dt><dd>{expectedFolders || '—'}</dd></div>
            <div><dt>Trouvées</dt><dd>{folders.length}</dd></div>
            <div><dt>Manquantes</dt><dd>{resolution.missing?.length || 0}</dd></div>
            <div><dt>Doublons</dt><dd>{resolution.duplicates?.length || 0}</dd></div>
          </dl>
          {(resolution.missing?.length > 0 || resolution.duplicates?.length > 0) && (
            <p className="diagnostic-warning">
              <Icon name="warning_amber" />
              Vérifier les dossiers manquants ou dupliqués avant les étapes de contenu.
            </p>
          )}
        </div>
      </div>

      {checks.length > 0 && (
        <div className="health-checks">
          <h4>Contrôles de santé</h4>
          <div className="health-checks__grid">
            {checks.map(([key, check]) => (
              <div key={key} className={`health-check ${check?.ok ? 'is-complete' : checksPending ? 'is-pending' : 'is-failed'}`}>
                <Icon name={check?.ok ? 'check_circle' : checksPending ? 'schedule' : 'error_outline'} />
                <div>
                  <strong>{healthCheckLabel(key)}</strong>
                  <span>{checksPending && !check?.ok ? 'Cette vérification sera exécutée après la génération du contenu.' : check?.detail || (check?.ok ? 'Contrôle validé' : 'Contrôle non validé')}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {volumeFolders.length > 0 && (
        <details className="volume-audit">
          <summary>Audit des volumes par journée <Icon name="expand_more" /></summary>
          <div className="volume-audit__rows">
            {volumeFolders.map(folder => {
              const outsideBudget = Number(folder.deficit || 0) > 0 || Number(folder.overflow || 0) > 0
              return (
                <div key={folder.folder_id} className={outsideBudget ? 'is-warning' : 'is-complete'}>
                  <span>Jour {folder.day_number}: {folder.folder_name}</span>
                  <strong>{Number(folder.total_words || 0).toLocaleString('fr-FR')} mots</strong>
                  <em>
                    {folder.deficit > 0
                      ? `Déficit ${Number(folder.deficit).toLocaleString('fr-FR')}`
                      : folder.overflow > 0
                        ? `Dépassement ${Number(folder.overflow).toLocaleString('fr-FR')}`
                        : 'Dans le budget'}
                  </em>
                </div>
              )
            })}
          </div>
        </details>
      )}
    </section>
  )
}

function PipelineList({ jobs, selectedJobId, onSelect, loading }) {
  if (loading) {
    return (
      <div className="space-y-3" aria-label="Chargement des pipelines">
        {[0, 1, 2].map(item => (
          <div key={item} className="h-24 animate-pulse rounded-xl bg-slate-100" />
        ))}
      </div>
    )
  }

  if (jobs.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-5">
        <p className="text-sm font-semibold text-slate-900">Aucune pipeline</p>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Une pipeline apparaîtra ici après la validation d’une commande de professeur IA.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {jobs.map(item => {
        const selected = Number(item.id) === Number(selectedJobId)
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.id)}
            aria-pressed={selected}
            className={`w-full rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40 ${
              selected
                ? 'border-violet-400 bg-violet-50'
                : 'border-slate-200 bg-white hover:bg-slate-50'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-900">
                  {item.tp_name || `Pipeline #${item.id}`}
                </p>
                <p className="mt-1 truncate text-xs text-slate-600">
                  {item.platform_name || `Plateforme ${item.platform_id || 'non attribuée'}`}
                </p>
              </div>
              <span className="shrink-0 text-xs font-medium text-slate-500">#{item.id}</span>
            </div>
            <div className="mt-3 flex items-center justify-between gap-3 text-xs text-slate-500">
              <span>RNCP {item.rncp_code || '—'}</span>
              <span>{formatDate(item.updated_at || item.created_at)}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}

function FolderProgress({ folders }) {
  if (!folders?.length) {
    return (
      <p className="rounded-xl bg-slate-50 px-4 py-5 text-sm text-slate-600">
        Les journées apparaîtront après la création du programme.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-xs font-medium text-slate-500">
            <th className="px-3 py-3">Journée</th>
            <th className="px-3 py-3">Contenu</th>
            <th className="px-3 py-3">Segments</th>
            <th className="px-3 py-3">Contrôle</th>
            <th className="px-3 py-3">État</th>
          </tr>
        </thead>
        <tbody>
          {folders.map((folder, index) => {
            const completed = Number(folder.segments_completed || 0)
            const total = Number(folder.segments_total || 0)
            const reviewed = Number(folder.reviewed_segments || 0)
            const reviewErrors = Number(folder.review_errors || 0)
            const ready = folder.content_status === 'completed' && completed > 0 && reviewErrors === 0
            return (
              <tr key={folder.folder_id} className="border-b border-slate-100 last:border-0">
                <td className="px-3 py-3">
                  <p className="font-semibold text-slate-900">{folder.name || `Journée ${index + 1}`}</p>
                  <p className="mt-0.5 text-xs text-slate-500">Dossier #{folder.folder_id}</p>
                </td>
                <td className="px-3 py-3 text-slate-700">
                  {Number(folder.total_words || 0).toLocaleString('fr-FR')} mots
                </td>
                <td className="px-3 py-3 text-slate-700">{completed}/{total || '—'}</td>
                <td className="px-3 py-3 text-slate-700">
                  {reviewed} vérifié{reviewed > 1 ? 's' : ''}
                  {reviewErrors > 0 && (
                    <span className="ml-2 font-semibold text-red-700">
                      {reviewErrors} erreur{reviewErrors > 1 ? 's' : ''}
                    </span>
                  )}
                </td>
                <td className="px-3 py-3">
                  <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
                    ready
                      ? 'bg-emerald-50 text-emerald-700'
                      : folder.content_status === 'completed'
                        ? 'bg-amber-50 text-amber-800'
                        : 'bg-slate-100 text-slate-700'
                  }`}>
                    {ready ? 'Validée' : folder.content_status === 'completed' ? 'À contrôler' : 'En préparation'}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function RecentEvents({ events }) {
  const recentEvents = [...(events || [])].reverse().slice(0, 12)
  if (recentEvents.length === 0) {
    return <p className="text-sm text-slate-600">Aucun événement enregistré pour le moment.</p>
  }
  return (
    <ol className="space-y-3">
      {recentEvents.map((event, index) => {
        const error = event.status === 'error' || event.event_type?.includes('failed')
        const completed = event.status === 'completed'
        return (
          <li key={event.id || `${event.created_at}-${index}`} className="flex gap-3">
            <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${
              error ? 'bg-red-500' : completed ? 'bg-emerald-500' : 'bg-slate-400'
            }`} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="text-sm font-medium text-slate-900">
                  {event.message || formatStep(event.step)}
                </p>
                <time className="text-xs text-slate-500">{formatDate(event.created_at)}</time>
              </div>
              {event.error && <p className="mt-1 text-sm leading-5 text-red-700">{event.error}</p>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

export default function FormationPipeline() {
  const [jobs, setJobs] = useState([])
  const [selectedJobId, setSelectedJobId] = useState(null)
  const [job, setJob] = useState(null)
  const [autoPilotState, setAutoPilotState] = useState(null)
  const [diagnostic, setDiagnostic] = useState(null)
  const [loadingJobs, setLoadingJobs] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [jobsError, setJobsError] = useState('')
  const [detailError, setDetailError] = useState('')
  const [resumeBusy, setResumeBusy] = useState(false)
  const [resumeNotice, setResumeNotice] = useState('')

  const selectJob = useCallback((jobId) => {
    const normalized = Number(jobId)
    setSelectedJobId(normalized)
    setJob(null)
    setAutoPilotState(null)
    setDiagnostic(null)
    setDetailError('')
    setResumeNotice('')
  }, [])

  const fetchJobs = useCallback(async () => {
    try {
      const response = await apiFetch('/api/formation/list')
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.error || 'Impossible de charger les pipelines.')
      const nextJobs = payload.jobs || []
      setJobs(nextJobs)
      setSelectedJobId(current => {
        if (current && nextJobs.some(item => Number(item.id) === Number(current))) return current
        const requestedId = Number(new URLSearchParams(window.location.search).get('job'))
        if (requestedId && nextJobs.some(item => Number(item.id) === requestedId)) return requestedId
        return nextJobs[0]?.id ? Number(nextJobs[0].id) : null
      })
      setJobsError('')
    } catch (error) {
      setJobsError(error.message || 'Impossible de charger les pipelines.')
    } finally {
      setLoadingJobs(false)
    }
  }, [])

  const fetchDetail = useCallback(async (jobId, { showLoader = false } = {}) => {
    if (!jobId) {
      setJob(null)
      setAutoPilotState(null)
      setDiagnostic(null)
      return
    }
    if (showLoader) setLoadingDetail(true)
    try {
      const [jobResponse, statusResponse, diagnosticResponse] = await Promise.all([
        apiFetch(`/api/formation/${jobId}`),
        apiFetch(`/api/formation/${jobId}/run-auto/status`),
        apiFetch(`/api/formation/${jobId}/diagnostic?events_limit=60`),
      ])
      const [jobPayload, statusPayload, diagnosticPayload] = await Promise.all([
        jobResponse.json().catch(() => ({})),
        statusResponse.json().catch(() => ({})),
        diagnosticResponse.json().catch(() => ({})),
      ])
      if (!jobResponse.ok) {
        throw new Error(responseErrorMessage(jobResponse, jobPayload, 'Impossible de charger cette pipeline.'))
      }
      if (!statusResponse.ok) {
        throw new Error(responseErrorMessage(statusResponse, statusPayload, 'État de la pipeline indisponible.'))
      }
      if (!diagnosticResponse.ok) {
        throw new Error(responseErrorMessage(diagnosticResponse, diagnosticPayload, 'Diagnostic indisponible.'))
      }
      setJob(jobPayload)
      setAutoPilotState(statusPayload)
      setDiagnostic(diagnosticPayload)
      setDetailError('')
    } catch (error) {
      setJob(null)
      setAutoPilotState(null)
      setDiagnostic(null)
      setDetailError(error.message || 'Impossible de charger cette pipeline.')
    } finally {
      if (showLoader) setLoadingDetail(false)
    }
  }, [])

  useEffect(() => {
    fetchJobs()
    const interval = window.setInterval(fetchJobs, 15000)
    return () => window.clearInterval(interval)
  }, [fetchJobs])

  useEffect(() => {
    if (!selectedJobId) return undefined
    fetchDetail(selectedJobId, { showLoader: true })
    const interval = window.setInterval(() => fetchDetail(selectedJobId), 5000)
    return () => window.clearInterval(interval)
  }, [fetchDetail, selectedJobId])

  useEffect(() => {
    if (!selectedJobId) return
    const url = new URL(window.location.href)
    if (Number(url.searchParams.get('job')) === Number(selectedJobId)) return
    url.searchParams.set('job', String(selectedJobId))
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }, [selectedJobId])

  const resumePipeline = async () => {
    if (!selectedJobId || resumeBusy) return
    setResumeBusy(true)
    setResumeNotice('')
    try {
      const response = await apiFetch(`/api/formation/${selectedJobId}/run-auto/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          force: Boolean(
            autoPilotState?.lock_stale
            || autoPilotState?.queue?.status === 'cancelled'
          ),
        }),
      })
      const payload = await response.json().catch(() => ({}))
      if (![200, 202, 409].includes(response.status)) {
        throw new Error(payload.error || 'La pipeline n’a pas pu reprendre.')
      }
      setResumeNotice(
        response.status === 409
          ? 'La pipeline est déjà prise en charge par le worker.'
          : payload.status === 'done'
            ? 'La pipeline était déjà terminée.'
            : 'La pipeline a été remise dans la file depuis son dernier checkpoint.',
      )
      await Promise.all([fetchJobs(), fetchDetail(selectedJobId)])
    } catch (error) {
      setDetailError(error.message || 'La pipeline n’a pas pu reprendre.')
    } finally {
      setResumeBusy(false)
    }
  }

  const status = statusView(job, autoPilotState)
  const resumable = canResumePipeline(job, autoPilotState)
  const errorMessage = pipelineError(job, autoPilotState)
  const activeStep = formatStep(autoPilotState?.step || autoPilotState?.next_step)
  const healthBlocking = diagnostic?.health?.blocking || []
  const healthWarnings = diagnostic?.health?.warnings || []
  const healthChecksPending = (
    !resumable
    && autoPilotState?.status !== 'done'
    && !(diagnostic?.folders || []).length
  )
  const pageError = jobsError || detailError

  return (
    <div className="formation-pipeline-page min-h-screen bg-slate-50 text-slate-900" style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex min-h-16 max-w-[1480px] items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center text-violet-400">
              <Icon name="school" className="text-2xl" />
            </span>
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold tracking-tight text-slate-950">Pipeline formation</h1>
              <p className="truncate text-xs text-slate-600">Suivi automatique des professeurs IA commandés</p>
            </div>
          </div>
          <a
            href="/dashboard-centre"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-300 px-3.5 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
          >
            <Icon name="arrow_back" className="text-lg" />
            <span className="hidden sm:inline">Retour aux professeurs IA</span>
          </a>
        </div>
      </header>

      <main className="formation-pipeline-main">
        <section className="pipeline-history" aria-labelledby="pipeline-history-title">
          <div className="pipeline-history__heading">
            <h2 id="pipeline-history-title"><Icon name="history" /> Pipelines existants</h2>
            <span>{jobs.length} pipeline{jobs.length > 1 ? 's' : ''}</span>
          </div>
          <PipelineList
            jobs={jobs}
            selectedJobId={selectedJobId}
            onSelect={selectJob}
            loading={loadingJobs}
          />
        </section>

        <section className="pipeline-detail" aria-live="polite">
          {pageError && (
            <div role="alert" className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {pageError}
            </div>
          )}

          {!selectedJobId && !loadingJobs && (
            <div className="rounded-xl border border-slate-200 bg-white p-8">
              <h2 className="text-lg font-semibold text-slate-950">Aucune préparation en cours</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                La création et le démarrage d’une pipeline sont déclenchés automatiquement après la validation d’une commande de professeur IA.
              </p>
            </div>
          )}

          {selectedJobId && loadingDetail && !job && (
            <div className="space-y-4">
              <div className="h-40 animate-pulse rounded-xl bg-slate-100" />
              <div className="h-64 animate-pulse rounded-xl bg-slate-100" />
            </div>
          )}

          {job && (
            <div className="space-y-5">
              <section className="pipeline-job-summary rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
                <div className="flex flex-col justify-between gap-5 md:flex-row md:items-start">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-medium text-slate-500">Pipeline #{job.id}</span>
                      <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${status.className}`}>
                        <Icon name={status.icon} className="text-sm" />
                        {status.label}
                      </span>
                    </div>
                    <h2 className="mt-3 text-xl font-semibold tracking-tight text-slate-950">
                      {job.tp_name || 'Formation sans titre'}
                    </h2>
                    <p className="mt-1 text-sm text-slate-600">
                      {job.platform_name || `Plateforme ${job.platform_id || 'non attribuée'}`}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500">
                      <span>RNCP {job.rncp_code || '—'}</span>
                      <span>{job.nb_days || 0} journée{Number(job.nb_days) > 1 ? 's' : ''}</span>
                      <span>Dernière mise à jour : {formatDate(job.updated_at || job.created_at)}</span>
                    </div>
                  </div>
                  <div className="min-w-[220px] rounded-xl bg-slate-50 px-4 py-3">
                    <p className="text-xs font-medium text-slate-500">Étape actuelle</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">{activeStep}</p>
                    <p className="mt-1 text-xs leading-5 text-slate-600">
                      {autoPilotState?.queue?.status === 'retry_scheduled'
                        ? 'Une nouvelle tentative automatique est déjà planifiée.'
                        : 'La progression est enregistrée dans PostgreSQL après chaque étape.'}
                    </p>
                  </div>
                </div>
              </section>

              {resumable && (
                <section className="rounded-xl border border-red-200 bg-red-50 p-5">
                  <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
                    <div className="min-w-0">
                      <h3 className="flex items-center gap-2 text-sm font-semibold text-red-900">
                        <Icon name="error_outline" className="text-lg" />
                        Pipeline interrompue
                      </h3>
                      <p className="mt-2 max-w-3xl text-sm leading-6 text-red-800">
                        {errorMessage || 'Le worker a arrêté cette pipeline après épuisement des tentatives automatiques.'}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={resumePipeline}
                      disabled={resumeBusy}
                      className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-violet-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40 focus-visible:ring-offset-2 disabled:cursor-wait disabled:opacity-60"
                    >
                      <Icon name={resumeBusy ? 'hourglass_top' : 'restart_alt'} className="text-lg" />
                      {resumeBusy ? 'Reprise en cours…' : 'Reprendre la pipeline'}
                    </button>
                  </div>
                </section>
              )}

              {resumeNotice && (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                  {resumeNotice}
                </div>
              )}

              <section className="legacy-overview-panel" aria-labelledby="overview-title">
                <div className="legacy-overview-panel__header">
                  <h3 id="overview-title">Avancement automatique</h3>
                  <p>Les étapes s’enchaînent dans la file durable, sans validation ou relance intermédiaire.</p>
                </div>
                <LegacyOverviewProgress
                  job={job}
                  autoPilotState={autoPilotState}
                  diagnostic={diagnostic}
                />
              </section>

              <DetailedRoadmap
                job={job}
                autoPilotState={autoPilotState}
                diagnostic={diagnostic}
              />

              <PipelineDiagnostics job={job} diagnostic={diagnostic} autoPilotState={autoPilotState} />

              <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-base font-semibold text-slate-950">Journées de formation</h3>
                    <p className="mt-1 text-sm text-slate-600">État enregistré des contenus et contrôles.</p>
                  </div>
                  <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                    healthChecksPending
                      ? 'bg-slate-100 text-slate-600'
                      : healthBlocking.length > 0
                      ? 'bg-red-50 text-red-700'
                      : healthWarnings.length > 0
                        ? 'bg-amber-50 text-amber-800'
                        : 'bg-emerald-50 text-emerald-700'
                  }`}>
                    {healthChecksPending
                      ? 'Contrôles à venir'
                      : healthBlocking.length > 0
                      ? `${healthBlocking.length} blocage${healthBlocking.length > 1 ? 's' : ''}`
                      : healthWarnings.length > 0
                        ? `${healthWarnings.length} avertissement${healthWarnings.length > 1 ? 's' : ''}`
                        : 'Contrôles conformes'}
                  </span>
                </div>
                <FolderProgress folders={diagnostic?.folders} />
              </section>

              <details className="rounded-xl border border-slate-200 bg-white">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 text-sm font-semibold text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-violet-500/40 sm:px-6">
                  Journal technique récent
                  <Icon name="expand_more" className="text-lg text-slate-500" />
                </summary>
                <div className="border-t border-slate-200 px-5 py-5 sm:px-6">
                  <RecentEvents events={diagnostic?.events} />
                </div>
              </details>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
