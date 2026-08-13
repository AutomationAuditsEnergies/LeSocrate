import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '../api'

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

const STEP_ALIASES = {
  start: 'reac',
  plan_adherence_review: 'review',
  audio_word_calibration: 'review',
  word_budget_review: 'review',
  done: 'done',
}

const QUEUE_ACTIVE_STATUSES = new Set(['queued', 'retry_scheduled', 'running'])
const QUEUE_RECOVERABLE_STATUSES = new Set(['dead_lettered', 'cancelled'])
const JOB_FAILURE_STATUSES = new Set(['error', 'audio_error'])

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

function normalizeStep(step) {
  const value = String(step || '').trim()
  return STEP_ALIASES[value] || value
}

function formatStep(step) {
  const normalized = normalizeStep(step)
  if (normalized === 'done') return 'Finalisation'
  return PIPELINE_STAGES.find(item => item.key === normalized)?.label || 'Initialisation'
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
    || JOB_FAILURE_STATUSES.has(job.status)
    || QUEUE_RECOVERABLE_STATUSES.has(queueStatus)
  )
}

function completedStageKeys(autoPilotState, events) {
  const completed = new Set(
    (events || [])
      .filter(event => event.event_type === 'step_completed' || event.status === 'completed')
      .map(event => normalizeStep(event.step))
      .filter(Boolean),
  )
  const current = normalizeStep(autoPilotState?.step || autoPilotState?.next_step)
  const currentIndex = PIPELINE_STAGES.findIndex(stage => stage.key === current)
  if (current === 'done' || autoPilotState?.status === 'done') {
    PIPELINE_STAGES.forEach(stage => completed.add(stage.key))
  } else if (currentIndex > 0) {
    PIPELINE_STAGES.slice(0, currentIndex).forEach(stage => completed.add(stage.key))
  }
  return completed
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

function PipelineProgress({ autoPilotState, events }) {
  const completed = useMemo(
    () => completedStageKeys(autoPilotState, events),
    [autoPilotState, events],
  )
  const currentStep = normalizeStep(autoPilotState?.step || autoPilotState?.next_step)
  const failed = autoPilotState?.status === 'error'

  return (
    <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="Étapes de la pipeline">
      {PIPELINE_STAGES.map((stage, index) => {
        const isComplete = completed.has(stage.key)
        const isCurrent = stage.key === currentStep && !isComplete
        const isFailed = isCurrent && failed
        return (
          <li
            key={stage.key}
            className={`flex min-h-20 items-center gap-3 rounded-xl border px-4 py-3 ${
              isComplete
                ? 'border-emerald-200 bg-emerald-50'
                : isFailed
                  ? 'border-red-200 bg-red-50'
                  : isCurrent
                    ? 'border-violet-300 bg-violet-50'
                    : 'border-slate-200 bg-white'
            }`}
          >
            <span
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                isComplete
                  ? 'bg-emerald-100 text-emerald-700'
                  : isFailed
                    ? 'bg-red-100 text-red-700'
                    : isCurrent
                      ? 'bg-violet-100 text-violet-700'
                      : 'bg-slate-100 text-slate-500'
              }`}
            >
              <Icon name={isComplete ? 'check' : isFailed ? 'error_outline' : stage.icon} className="text-lg" />
            </span>
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-slate-500">Étape {index + 1}</p>
              <p className="mt-0.5 text-sm font-semibold leading-5 text-slate-900">{stage.label}</p>
            </div>
          </li>
        )
      })}
    </ol>
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
  const [pageError, setPageError] = useState('')
  const [resumeBusy, setResumeBusy] = useState(false)
  const [resumeNotice, setResumeNotice] = useState('')

  const selectJob = useCallback((jobId) => {
    const normalized = Number(jobId)
    setSelectedJobId(normalized)
    setResumeNotice('')
    const url = new URL(window.location.href)
    url.searchParams.set('job', String(normalized))
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
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
      setPageError('')
    } catch (error) {
      setPageError(error.message || 'Impossible de charger les pipelines.')
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
      if (!jobResponse.ok) throw new Error(jobPayload.error || 'Pipeline introuvable.')
      if (!statusResponse.ok) throw new Error(statusPayload.error || 'État de la pipeline indisponible.')
      if (!diagnosticResponse.ok) throw new Error(diagnosticPayload.error || 'Diagnostic indisponible.')
      setJob(jobPayload)
      setAutoPilotState(statusPayload)
      setDiagnostic(diagnosticPayload)
      setPageError('')
    } catch (error) {
      setPageError(error.message || 'Impossible de charger cette pipeline.')
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
      setPageError(error.message || 'La pipeline n’a pas pu reprendre.')
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

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900" style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex min-h-16 max-w-[1480px] items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-violet-700">
              <Icon name="account_tree" className="text-xl" />
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

      <main className="mx-auto grid max-w-[1480px] gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[320px_minmax(0,1fr)] lg:px-8">
        <aside className="self-start lg:sticky lg:top-24">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">Historique</h2>
            <span className="text-xs text-slate-500">{jobs.length} pipeline{jobs.length > 1 ? 's' : ''}</span>
          </div>
          <PipelineList
            jobs={jobs}
            selectedJobId={selectedJobId}
            onSelect={selectJob}
            loading={loadingJobs}
          />
        </aside>

        <section className="min-w-0" aria-live="polite">
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
              <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
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

              <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
                <div className="mb-5">
                  <h3 className="text-base font-semibold text-slate-950">Avancement automatique</h3>
                  <p className="mt-1 text-sm text-slate-600">
                    Les étapes s’enchaînent dans la file durable, sans validation ou relance intermédiaire.
                  </p>
                </div>
                <PipelineProgress autoPilotState={autoPilotState} events={diagnostic?.events} />
              </section>

              <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-base font-semibold text-slate-950">Journées de formation</h3>
                    <p className="mt-1 text-sm text-slate-600">État enregistré des contenus et contrôles.</p>
                  </div>
                  <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                    healthBlocking.length > 0
                      ? 'bg-red-50 text-red-700'
                      : healthWarnings.length > 0
                        ? 'bg-amber-50 text-amber-800'
                        : 'bg-emerald-50 text-emerald-700'
                  }`}>
                    {healthBlocking.length > 0
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
