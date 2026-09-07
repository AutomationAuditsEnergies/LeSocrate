import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, ChevronRight, ExternalLink, RefreshCw, X } from 'lucide-react'
import { apiFetch } from '../api'
import AppLoader from './AppLoader.jsx'
import { formatPlanningSummary } from '../formationPlanningDisplay'

const statusMeta = {
  pending: { label: 'À valider', className: 'bg-[#F4F4F2] text-[#3F3F46]' },
  approved: { label: 'Acceptée', className: 'bg-emerald-50 text-emerald-800' },
  rejected: { label: 'Refusée', className: 'bg-rose-50 text-rose-800' },
}

const formatDateTime = (value) => {
  if (!value) return 'Date inconnue'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('fr-FR', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const formatDate = (value) => {
  if (!value) return null
  const date = new Date(`${value}T12:00:00`)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleDateString('fr-FR', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

const formatPrice = (cents) => new Intl.NumberFormat('fr-FR', {
  style: 'currency',
  currency: 'EUR',
}).format(Number(cents || 0) / 100)

const DEEPSEEK_COST_PER_DAY_CENTS = 314
const FISH_AUDIO_COST_PER_DAY_CENTS = 625
const PIPELINE_MODELS = [
  {
    value: 'flash',
    name: 'DeepSeek V4 Flash',
    description: 'Économique et rapide, recommandé pour maîtriser le coût de génération.',
  },
  {
    value: 'pro',
    name: 'DeepSeek V4 Pro',
    description: 'Plus coûteux, à choisir lorsque la qualité de rédaction est prioritaire.',
  },
]

const apiRechargeCost = (trainingDays, costPerDayCents) => (
  formatPrice(Number(trainingDays || 0) * costPerDayCents)
)

const pluralize = (value, singular, plural = `${singular}s`) => (
  `${value} ${Number(value) > 1 ? plural : singular}`
)

const formatPeriod = (requestItem) => {
  const start = formatDate(requestItem.schedule_start_date)
  const end = formatDate(requestItem.schedule_end_date)
  if (start && end) return `Du ${start} au ${end}`
  if (start) return `À partir du ${start}`
  return 'Dates à confirmer'
}

const rncpLabel = (value) => String(value || '').replace(/^RNCP\s*/i, '')

const formatDuration = (requestItem) => {
  const segments = []
  if (requestItem.training_weeks) segments.push(pluralize(requestItem.training_weeks, 'semaine'))
  segments.push(formatPlanningSummary(requestItem.planning_summary, {
    fallbackHours: requestItem.total_hours,
    fallbackDays: requestItem.training_days,
    scheduleSchemaVersion: requestItem.schedule_schema_version,
  }))
  return segments.join(' · ') || 'Durée à confirmer'
}

export default function TeacherOrderReviewInbox({ onUnreadCountChange }) {
  const [requests, setRequests] = useState([])
  const [links, setLinks] = useState({ deepseek_url: '', audio_url: '' })
  const [selectedId, setSelectedId] = useState(null)
  const [filter, setFilter] = useState('pending')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [rejectNote, setRejectNote] = useState('')
  const [pipelineModels, setPipelineModels] = useState({})

  const loadRequests = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setRefreshing(true)
    try {
      const response = await apiFetch('/api/admin/teacher-order-validations')
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || !payload.success) throw new Error(payload.error || 'Chargement impossible')
      const nextRequests = payload.requests || []
      setRequests(nextRequests)
      setLinks({ deepseek_url: payload.deepseek_url || '', audio_url: payload.audio_url || '' })
      setError('')
      setSelectedId((current) => (
        nextRequests.some((item) => item.id === current) ? current : nextRequests[0]?.id || null
      ))
      onUnreadCountChange?.(Number(payload.unread_count || 0))
    } catch (requestError) {
      setError(requestError.message || 'Impossible de charger les demandes.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [onUnreadCountChange])

  useEffect(() => {
    void loadRequests()
    const timer = window.setInterval(() => void loadRequests({ quiet: true }), 15000)
    return () => window.clearInterval(timer)
  }, [loadRequests])

  const visibleRequests = useMemo(() => (
    filter === 'all' ? requests : requests.filter((item) => item.review_status === filter)
  ), [filter, requests])

  useEffect(() => {
    if (!visibleRequests.length) {
      setSelectedId(null)
      return
    }
    setSelectedId((current) => (
      visibleRequests.some((item) => item.id === current) ? current : visibleRequests[0].id
    ))
  }, [visibleRequests])

  const selected = visibleRequests.find((item) => item.id === selectedId) || visibleRequests[0] || null
  const pendingCount = requests.filter((item) => item.review_status === 'pending').length
  const pipelineModel = selected
    ? pipelineModels[selected.id] || selected.pipeline_model || 'flash'
    : 'flash'

  const openRequest = async (requestItem) => {
    setSelectedId(requestItem.id)
    setRejecting(false)
    setRejectNote('')
    setFeedback('')
    if (!requestItem.unread) return
    setRequests((current) => current.map((item) => (
      item.id === requestItem.id ? { ...item, unread: false } : item
    )))
    onUnreadCountChange?.(Math.max(0, requests.filter((item) => item.unread).length - 1))
    await apiFetch(`/api/admin/teacher-order-validations/${requestItem.id}/seen`, { method: 'POST' }).catch(() => {})
  }

  const decide = async (decision) => {
    if (!selected || busy) return
    setBusy(true)
    setError('')
    setFeedback('')
    try {
      const response = await apiFetch(`/api/admin/teacher-order-validations/${selected.id}/${decision}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(decision === 'reject'
          ? { note: rejectNote.trim() }
          : { pipeline_model: pipelineModel }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || !payload.success) throw new Error(payload.error || 'Décision impossible')
      setFeedback(decision === 'approve'
        ? payload.payment_email_sent
          ? 'Demande acceptée. Le lien de paiement a été envoyé au centre.'
          : 'Demande acceptée. L’e-mail de paiement n’a pas pu être envoyé.'
        : 'Demande refusée. Le centre verra la décision dans sa messagerie.')
      setRejecting(false)
      setRejectNote('')
      await loadRequests({ quiet: true })
    } catch (requestError) {
      setError(requestError.message || 'Impossible d’enregistrer la décision.')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <div className="flex h-full items-center justify-center"><AppLoader label="Chargement des demandes" /></div>
  }

  return (
    <section className="flex h-full min-h-0 flex-col" aria-labelledby="review-inbox-title">
      <header className="flex shrink-0 items-start justify-between gap-4 border-b border-[#E9E9EC] pb-4">
        <div>
          <h1 id="review-inbox-title" className="text-xl font-semibold tracking-tight text-[#18181B]">Messagerie</h1>
          <p className="mt-1 text-sm text-[#6B6B72]">
            {pendingCount
              ? `${pluralize(pendingCount, 'demande')} à vérifier pour les autres centres.`
              : 'Aucune demande en attente pour les autres centres.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => loadRequests()}
          disabled={refreshing}
          className="flex min-h-10 items-center gap-2 rounded-lg border border-[#D9D9DE] px-3 text-sm font-medium text-[#3F3F46] hover:bg-[#F5F5F6] disabled:opacity-50"
        >
          <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} aria-hidden="true" /> Actualiser
        </button>
      </header>

      {error && (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => loadRequests()} className="font-semibold">Réessayer</button>
        </div>
      )}

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(300px,390px)_1fr]">
        <div className="min-h-0 border-b border-[#E9E9EC] lg:border-b-0 lg:border-r">
          <div className="flex gap-1 border-b border-[#E9E9EC] p-3">
            {[
              ['pending', 'À valider'],
              ['all', 'Toutes'],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                className="min-h-9 rounded-md px-3 text-xs font-semibold"
                style={{ backgroundColor: filter === value ? '#18181B' : 'transparent', color: filter === value ? '#fff' : '#5F5E5A' }}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="max-h-[34dvh] overflow-y-auto lg:max-h-full">
            {visibleRequests.length === 0 ? (
              <p className="px-6 py-12 text-center text-sm text-[#6B6B72]">Aucune demande dans cette vue.</p>
            ) : visibleRequests.map((item) => {
              const meta = statusMeta[item.review_status] || statusMeta.pending
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => openRequest(item)}
                  className="flex w-full items-start gap-3 border-b border-[#EFEFF1] px-4 py-4 text-left transition-colors hover:bg-[#F8F8F7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#18181B]/40"
                  style={{ backgroundColor: selected?.id === item.id ? '#F4F4F2' : '#fff' }}
                >
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.unread ? 'bg-[#18181B]' : 'bg-transparent'}`} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2">
                      <strong className="truncate text-sm text-[#18181B]">{item.center_name}</strong>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${meta.className}`}>{meta.label}</span>
                    </span>
                    <span className="mt-1 block truncate text-xs text-[#3F3F46]">Création de {item.teacher_name}</span>
                    <span className="mt-1 block truncate text-xs text-[#6B6B72]">
                      {item.training_title} · {pluralize(item.training_days, 'jour')}
                    </span>
                    <span className="mt-1 block text-[11px] text-[#8A8A91]">{formatDateTime(item.created_at)}</span>
                  </span>
                  <ChevronRight size={16} className="mt-1 shrink-0 text-[#A1A1AA]" aria-hidden="true" />
                </button>
              )
            })}
          </div>
        </div>

        <article className="min-h-0 overflow-y-auto px-2 py-6 sm:px-6 lg:px-10 lg:py-8" aria-live="polite">
          {!selected ? (
            <p className="mx-auto max-w-md py-16 text-center text-sm text-[#6B6B72]">Sélectionnez une demande pour afficher ses informations.</p>
          ) : (
            <div className="mx-auto max-w-2xl">
              <p className="text-xs text-[#6B6B72]">{formatDateTime(selected.created_at)}</p>
              <p className="mt-4 max-w-[68ch] text-sm leading-6 text-[#3F3F46]">
                {selected.center_name} a demandé la création du professeur IA nommé {selected.teacher_name} pour la formation « {selected.training_title} »{selected.rncp_code ? `, RNCP ${rncpLabel(selected.rncp_code)}` : ''}. La formation comprend {pluralize(selected.training_days, 'journée')} {selected.training_weeks ? `réparties sur ${pluralize(selected.training_weeks, 'semaine')}` : ''}.
              </p>
              <p className="mt-6 text-sm font-semibold text-[#18181B]">
                {selected.review_status === 'pending' ? 'Demande à valider' : (statusMeta[selected.review_status] || statusMeta.pending).label}
              </p>

              <dl className="mt-6 divide-y divide-[#E9E9EC] border-y border-[#E9E9EC]">
                {[
                  ['Centre demandeur', `${selected.center_name} · ${selected.center_email}`],
                  ['Formation', `${selected.training_title}${selected.rncp_code ? ` · RNCP ${rncpLabel(selected.rncp_code)}` : ''}`],
                  ['Durée', formatDuration(selected)],
                  ['Période', formatPeriod(selected)],
                  ['Prix prévu', formatPrice(selected.catalog_amount_cents)],
                  ['Coût API DeepSeek à recharger', apiRechargeCost(selected.training_days, DEEPSEEK_COST_PER_DAY_CENTS)],
                  ['Coût API Fish Audio à recharger', apiRechargeCost(selected.training_days, FISH_AUDIO_COST_PER_DAY_CENTS)],
                ].map(([label, value]) => (
                  <div key={label} className="grid gap-1 py-3 sm:grid-cols-[150px_1fr] sm:gap-5">
                    <dt className="text-xs text-[#6B6B72]">{label}</dt>
                    <dd className="text-sm font-medium text-[#18181B]">{value}</dd>
                  </div>
                ))}
              </dl>

              <div className="mt-6">
                <p className="text-sm font-semibold text-[#18181B]">Crédits API</p>
                <p className="mt-1 text-sm text-[#6B6B72]">Rechargez les services nécessaires avant de valider la demande.</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <a href={links.audio_url} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[#D9D9DE] px-3 text-sm font-medium text-[#3F3F46] hover:bg-[#F5F5F6]">
                    Recharger Fish Audio <ExternalLink size={14} aria-hidden="true" />
                  </a>
                  <a href={links.deepseek_url} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[#D9D9DE] px-3 text-sm font-medium text-[#3F3F46] hover:bg-[#F5F5F6]">
                    Recharger DeepSeek <ExternalLink size={14} aria-hidden="true" />
                  </a>
                </div>
              </div>

              <fieldset className="mt-6" disabled={selected.review_status !== 'pending' || busy}>
                <legend className="text-sm font-semibold text-[#18181B]">Modèle de génération</legend>
                <p className="mt-1 text-sm text-[#6B6B72]">Ce choix sera conservé jusqu’au lancement de la pipeline après paiement.</p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {PIPELINE_MODELS.map((model) => {
                    const checked = pipelineModel === model.value
                    return (
                      <label
                        key={model.value}
                        className={`cursor-pointer rounded-xl border p-4 transition-colors ${checked ? 'border-[#18181B] bg-[#F4F4F2]' : 'border-[#D9D9DE] bg-white hover:bg-[#F8F8F7]'} disabled:cursor-default`}
                      >
                        <span className="flex items-start gap-3">
                          <input
                            type="radio"
                            name={`pipeline-model-${selected.id}`}
                            value={model.value}
                            checked={checked}
                            onChange={() => setPipelineModels((current) => ({
                              ...current,
                              [selected.id]: model.value,
                            }))}
                            className="mt-0.5 h-4 w-4 accent-[#18181B]"
                          />
                          <span>
                            <span className="block text-sm font-semibold text-[#18181B]">{model.name}</span>
                            <span className="mt-1 block text-xs leading-5 text-[#6B6B72]">{model.description}</span>
                          </span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              </fieldset>

              {feedback && <p className="mt-5 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">{feedback}</p>}

              {selected.review_status === 'pending' && (
                <div className="mt-7 border-t border-[#E9E9EC] pt-5">
                  {rejecting ? (
                    <div>
                      <label className="text-sm font-semibold text-[#18181B]" htmlFor="center-review-reject-note">
                        Motif du refus <span className="font-normal text-[#6B6B72]">(facultatif)</span>
                      </label>
                      <textarea
                        id="center-review-reject-note"
                        value={rejectNote}
                        onChange={(event) => setRejectNote(event.target.value)}
                        rows={3}
                        className="mt-2 w-full resize-none rounded-lg border border-[#D9D9DE] px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-black/25"
                        placeholder="Expliquez au centre ce qui doit être corrigé."
                      />
                      <div className="mt-3 flex flex-wrap justify-end gap-2">
                        <button type="button" onClick={() => setRejecting(false)} className="min-h-10 rounded-lg border border-[#D9D9DE] px-4 text-sm font-semibold hover:bg-[#F5F5F6]">Annuler</button>
                        <button type="button" onClick={() => decide('reject')} disabled={busy} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-rose-700 px-4 text-sm font-semibold text-white disabled:opacity-50">
                          <X size={15} aria-hidden="true" /> Refuser la demande
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-wrap justify-end gap-2">
                      <button type="button" onClick={() => setRejecting(true)} disabled={busy} className="min-h-11 rounded-lg border border-[#D9D9DE] px-4 text-sm font-semibold text-[#3F3F46] hover:bg-[#F5F5F6] disabled:opacity-50">Refuser</button>
                      <button type="button" onClick={() => decide('approve')} disabled={busy} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[#18181B] px-5 text-sm font-semibold text-white disabled:opacity-50">
                        {busy ? <RefreshCw size={15} className="animate-spin" aria-hidden="true" /> : <Check size={16} aria-hidden="true" />}
                        Valider et envoyer le paiement
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </article>
      </div>
    </section>
  )
}
