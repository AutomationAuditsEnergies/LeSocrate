import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Check,
  ChevronRight,
  CircleDollarSign,
  ExternalLink,
  Inbox,
  LogOut,
  MessageSquareText,
  RefreshCw,
  X,
} from 'lucide-react'
import { apiFetch } from '../api'
import { clearSupabaseSession } from '../supabaseClient'
import AppLoader from '../components/AppLoader.jsx'

const formatDateTime = (value) => {
  if (!value) return 'Date inconnue'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('fr-FR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
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

const statusMeta = {
  pending: { label: 'À valider', className: 'bg-amber-50 text-amber-800 ring-amber-200' },
  approved: { label: 'Acceptée', className: 'bg-emerald-50 text-emerald-800 ring-emerald-200' },
  rejected: { label: 'Refusée', className: 'bg-rose-50 text-rose-800 ring-rose-200' },
}

export default function AdminValidations() {
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
      setRequests(payload.requests || [])
      setLinks({ deepseek_url: payload.deepseek_url || '', audio_url: payload.audio_url || '' })
      setError('')
      setSelectedId((current) => current || payload.requests?.[0]?.id || null)
    } catch (requestError) {
      setError(requestError.message || 'Impossible de charger les demandes.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    void loadRequests()
    const timer = window.setInterval(() => void loadRequests({ quiet: true }), 15000)
    return () => window.clearInterval(timer)
  }, [loadRequests])

  const visibleRequests = useMemo(() => (
    filter === 'all' ? requests : requests.filter((item) => item.review_status === filter)
  ), [filter, requests])
  const selected = requests.find((item) => item.id === selectedId) || visibleRequests[0] || null
  const pendingCount = requests.filter((item) => item.review_status === 'pending').length
  const unreadCount = requests.filter((item) => item.unread).length
  const pipelineModel = selected
    ? pipelineModels[selected.id] || selected.pipeline_model || 'flash'
    : 'flash'

  const openRequest = async (requestItem) => {
    setSelectedId(requestItem.id)
    setRejecting(false)
    setRejectNote('')
    if (!requestItem.unread) return
    setRequests((current) => current.map((item) => (
      item.id === requestItem.id ? { ...item, unread: false } : item
    )))
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
          : 'Demande acceptée, mais l’e-mail de paiement n’a pas pu être envoyé.'
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

  const logout = async () => {
    await apiFetch('/api/admin/logout', { method: 'POST' }).catch(() => {})
    localStorage.removeItem('admin_auth_token')
    await clearSupabaseSession().catch(() => {})
    window.location.assign('/connexion-centre')
  }

  if (loading) return <AppLoader label="Chargement des validations" />

  return (
    <div className="flex min-h-dvh bg-white text-[#18181B]">
      <aside className="hidden w-[248px] shrink-0 border-r border-[#E9E9EC] bg-[#F7F7F5] p-3 md:flex md:flex-col">
        <div className="flex h-14 items-center gap-3 px-2">
          <img src="/socrate-mark.svg" alt="Le Socrate" className="h-8 w-8" />
          <div>
            <p className="text-sm font-semibold">Administration</p>
            <p className="text-xs text-[#6B6B72]">Sales Hacking</p>
          </div>
        </div>
        <nav className="mt-4">
          <button type="button" className="flex min-h-11 w-full items-center gap-2.5 rounded-md bg-[#E9E9E7] px-2 text-sm font-medium">
            <MessageSquareText size={17} aria-hidden="true" />
            <span className="flex-1 text-left">Validations</span>
            {unreadCount > 0 && <span className="rounded-full bg-[#18181B] px-1.5 py-0.5 text-[10px] font-semibold text-white">{unreadCount}</span>}
          </button>
        </nav>
        <button type="button" onClick={logout} className="mt-auto flex min-h-11 items-center gap-2.5 rounded-md px-2 text-sm text-[#5F5E5A] hover:bg-black/[0.045]">
          <LogOut size={17} aria-hidden="true" /> Se déconnecter
        </button>
      </aside>

      <main className="min-w-0 flex-1">
        <header className="flex min-h-16 items-center justify-between border-b border-[#E9E9EC] px-4 sm:px-6 lg:px-8">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Validation des demandes</h1>
            <p className="text-xs text-[#6B6B72]">{pendingCount} demande{pendingCount > 1 ? 's' : ''} en attente</p>
          </div>
          <button type="button" onClick={() => loadRequests()} disabled={refreshing} className="flex h-10 items-center gap-2 rounded-lg border border-[#D9D9DE] px-3 text-sm font-medium hover:bg-[#F5F5F6] disabled:opacity-50">
            <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} aria-hidden="true" /> Actualiser
          </button>
        </header>

        <div className="grid min-h-[calc(100dvh-4rem)] lg:grid-cols-[minmax(300px,420px)_1fr]">
          <section className="border-b border-[#E9E9EC] lg:border-b-0 lg:border-r" aria-label="Demandes">
            <div className="flex gap-1 border-b border-[#E9E9EC] p-3">
              {[['pending', 'À valider'], ['approved', 'Acceptées'], ['all', 'Toutes']].map(([value, label]) => (
                <button key={value} type="button" onClick={() => setFilter(value)} className="min-h-9 rounded-md px-3 text-xs font-semibold" style={{ backgroundColor: filter === value ? '#18181B' : 'transparent', color: filter === value ? '#fff' : '#5F5E5A' }}>{label}</button>
              ))}
            </div>
            <div className="max-h-[42dvh] overflow-y-auto lg:max-h-[calc(100dvh-7.7rem)]">
              {visibleRequests.length === 0 ? (
                <div className="px-6 py-14 text-center">
                  <Inbox className="mx-auto text-[#A1A1AA]" size={28} aria-hidden="true" />
                  <p className="mt-3 text-sm font-medium">Aucune demande dans cette vue</p>
                </div>
              ) : visibleRequests.map((item) => {
                const meta = statusMeta[item.review_status] || statusMeta.pending
                return (
                  <button key={item.id} type="button" onClick={() => openRequest(item)} className="flex w-full items-start gap-3 border-b border-[#EFEFF1] px-4 py-4 text-left hover:bg-[#F8F8F7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#18181B]/40" style={{ backgroundColor: selected?.id === item.id ? '#F4F4F2' : '#fff' }}>
                    <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${item.unread ? 'bg-[#18181B]' : 'bg-transparent'}`} aria-label={item.unread ? 'Non lue' : undefined} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center justify-between gap-2">
                        <strong className="truncate text-sm">{item.center_name}</strong>
                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${meta.className}`}>{meta.label}</span>
                      </span>
                      <span className="mt-1 block truncate text-sm text-[#3F3F46]">{item.teacher_name} · {item.training_title}</span>
                      <span className="mt-1 block text-xs text-[#6B6B72]">{formatDateTime(item.created_at)}</span>
                    </span>
                    <ChevronRight size={16} className="mt-1 shrink-0 text-[#A1A1AA]" aria-hidden="true" />
                  </button>
                )
              })}
            </div>
          </section>

          <section className="min-w-0 px-4 py-6 sm:px-6 lg:px-10 lg:py-8" aria-live="polite">
            {!selected ? (
              <div className="mx-auto max-w-md py-16 text-center text-sm text-[#6B6B72]">Sélectionnez une demande pour afficher ses informations.</div>
            ) : (
              <div className="mx-auto max-w-3xl">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-sm text-[#6B6B72]">{selected.center_name} · {selected.center_email}</p>
                    <h2 className="mt-1 text-2xl font-semibold tracking-[-0.025em]">{selected.teacher_name}</h2>
                    <p className="mt-1 text-sm text-[#3F3F46]">{selected.training_title}{selected.rncp_code ? ` · RNCP ${selected.rncp_code}` : ''}</p>
                  </div>
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${(statusMeta[selected.review_status] || statusMeta.pending).className}`}>{(statusMeta[selected.review_status] || statusMeta.pending).label}</span>
                </div>

                <dl className="mt-7 grid gap-px overflow-hidden rounded-xl border border-[#E1E1E5] bg-[#E1E1E5] sm:grid-cols-2">
                  {[
                    ['Journées prévues', selected.training_days],
                    ['Prix client', formatPrice(selected.catalog_amount_cents)],
                    ['Coût API DeepSeek à recharger', apiRechargeCost(selected.training_days, DEEPSEEK_COST_PER_DAY_CENTS)],
                    ['Coût API Fish Audio à recharger', apiRechargeCost(selected.training_days, FISH_AUDIO_COST_PER_DAY_CENTS)],
                    ['Demande reçue', formatDateTime(selected.created_at)],
                  ].map(([label, value]) => (
                    <div key={label} className="bg-white px-4 py-4">
                      <dt className="text-xs text-[#6B6B72]">{label}</dt>
                      <dd className="mt-1 text-sm font-semibold">{value}</dd>
                    </div>
                  ))}
                </dl>

                <div className="mt-6">
                  <h3 className="text-sm font-semibold">Crédits API</h3>
                  <p className="mt-1 text-sm text-[#6B6B72]">Rechargez les comptes nécessaires avant d’accepter la demande.</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <a href={links.audio_url} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[#D9D9DE] px-3 text-sm font-medium hover:bg-[#F5F5F6]">Fish Audio <ExternalLink size={14} aria-hidden="true" /></a>
                    <a href={links.deepseek_url} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[#D9D9DE] px-3 text-sm font-medium hover:bg-[#F5F5F6]">DeepSeek <ExternalLink size={14} aria-hidden="true" /></a>
                  </div>
                </div>

                <fieldset className="mt-6" disabled={selected.review_status !== 'pending' || busy}>
                  <legend className="text-sm font-semibold">Modèle de génération</legend>
                  <p className="mt-1 text-sm text-[#6B6B72]">Ce choix sera conservé jusqu’au lancement de la pipeline après paiement.</p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {PIPELINE_MODELS.map((model) => {
                      const checked = pipelineModel === model.value
                      return (
                        <label key={model.value} className={`cursor-pointer rounded-xl border p-4 transition-colors ${checked ? 'border-[#18181B] bg-[#F4F4F2]' : 'border-[#D9D9DE] bg-white hover:bg-[#F8F8F7]'}`}>
                          <span className="flex items-start gap-3">
                            <input type="radio" name={`pipeline-model-${selected.id}`} value={model.value} checked={checked} onChange={() => setPipelineModels((current) => ({ ...current, [selected.id]: model.value }))} className="mt-0.5 h-4 w-4 accent-[#18181B]" />
                            <span>
                              <span className="block text-sm font-semibold">{model.name}</span>
                              <span className="mt-1 block text-xs leading-5 text-[#6B6B72]">{model.description}</span>
                            </span>
                          </span>
                        </label>
                      )
                    })}
                  </div>
                </fieldset>

                {error && <p className="mt-5 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert">{error}</p>}
                {feedback && <p className="mt-5 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">{feedback}</p>}

                {selected.review_status === 'pending' && (
                  <div className="mt-7 border-t border-[#E9E9EC] pt-5">
                    {rejecting ? (
                      <div>
                        <label className="text-sm font-semibold" htmlFor="admin-reject-note">Motif du refus <span className="font-normal text-[#6B6B72]">(facultatif)</span></label>
                        <textarea id="admin-reject-note" value={rejectNote} onChange={(event) => setRejectNote(event.target.value)} rows={3} className="mt-2 w-full resize-none rounded-lg border border-[#D9D9DE] px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-black/25" placeholder="Expliquez au centre ce qui doit être corrigé." />
                        <div className="mt-3 flex flex-wrap justify-end gap-2">
                          <button type="button" onClick={() => setRejecting(false)} className="min-h-10 rounded-lg border border-[#D9D9DE] px-4 text-sm font-semibold hover:bg-[#F5F5F6]">Annuler</button>
                          <button type="button" onClick={() => decide('reject')} disabled={busy} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-rose-700 px-4 text-sm font-semibold text-white disabled:opacity-50"><X size={15} aria-hidden="true" /> Refuser la demande</button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-wrap justify-end gap-2">
                        <button type="button" onClick={() => setRejecting(true)} disabled={busy} className="min-h-11 rounded-lg border border-[#D9D9DE] px-4 text-sm font-semibold hover:bg-[#F5F5F6] disabled:opacity-50">Refuser</button>
                        <button type="button" onClick={() => decide('approve')} disabled={busy} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[#18181B] px-5 text-sm font-semibold text-white disabled:opacity-50">
                          {busy ? <RefreshCw size={15} className="animate-spin" aria-hidden="true" /> : <Check size={16} aria-hidden="true" />}
                          Accepter et envoyer le paiement
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {selected.review_status === 'approved' && (
                  <div className="mt-7 flex items-center gap-3 rounded-lg bg-[#F5F5F4] px-4 py-3 text-sm text-[#3F3F46]">
                    <CircleDollarSign size={18} aria-hidden="true" /> Le centre a reçu son lien de paiement par e-mail.
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  )
}
