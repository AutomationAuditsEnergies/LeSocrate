import { useState, useEffect, useRef, useCallback } from 'react'
import { apiUrl } from '../api'

const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`} style={{ fontSize: 'inherit' }}>{name}</span>
)

// ─── Statuts qui nécessitent un polling ───────────────────────────────────────
const POLLING_STATUSES = new Set([
  'reac_fetching', 'kb_building', 'global_generating', 'daily_splitting',
  'tts_launched', 'audio_launched'
])

// ─── Mapping statut → étape active (0-indexed) ────────────────────────────────
function statusToStep(status, job = null) {
  if (!status) return -1
  if (status === 'init') return 1
  if (status === 'reac_fetching') return 1
  if (status === 'reac_ready') return 2
  if (status === 'kb_building') return 2
  if (status === 'kb_ready') return 3
  if (status === 'global_generating') return 3
  if (status === 'global_ready') return 3
  if (status === 'global_validated') return 4
  if (status === 'daily_splitting') return 4
  if (status === 'daily_ready') return 4
  if (status === 'daily_validated') return 5
  if (status === 'tts_launched') return 5         // textes en cours ou prêts
  if (status === 'audio_launched') return 6       // synthèse audio lancée
  if (status === 'error') {
    // Déduire l'étape où l'erreur s'est produite pour rester cliquable
    if (!job) return 1
    if (job.daily_programs) return 4
    if (job.global_program_validated) return 4
    if (job.global_program) return 3
    if (job.kb_total > 0) return 3
    if (job.reac_available) return 2
    return 1
  }
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

// ─── Stepper horizontal ───────────────────────────────────────────────────────
function Stepper({ currentStep, status }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: '32px', overflowX: 'auto', paddingBottom: '4px' }}>
      {STEP_LABELS.map((s, i) => {
        const done = i < currentStep
        const active = i === currentStep
        const err = status === 'error' && active
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
  const step = statusToStep(job.status)
  const statusColor = job.status === 'audio_launched' ? 'green'
    : job.status === 'error' ? 'red'
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
        {active && POLLING_STATUSES.has(status) && <span style={S.tag('amber')}><Icon name="hourglass_empty" /> En cours…</span>}
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

  // États étape 6 — Synthèse audio Fish Audio
  const [launchingAudio, setLaunchingAudio] = useState(false)
  const [audioError, setAudioError] = useState('')

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

  // ─── Polling automatique ──────────────────────────────────────────────────
  useEffect(() => {
    if (!selectedJobId) return
    fetchJob(selectedJobId)
    fetchKb(selectedJobId)

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
    if (!['tts_launched', 'audio_launched'].includes(job.status)) return
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

  const handleDownloadDocx = (folderId) => {
    // Ouvre directement l'URL backend (Content-Disposition: attachment)
    window.open(apiUrl(`/api/formation/${selectedJobId}/content/${folderId}/docx`), '_blank')
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

  // ─── Étape 6 — lancement de la synthèse audio Fish Audio ──────────────────
  const handleLaunchAudio = async () => {
    setLaunchingAudio(true)
    setAudioError('')
    try {
      const resp = await fetch(apiUrl(`/api/formation/${selectedJobId}/launch-audio`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({}),
      })
      const data = await resp.json()
      if (data.error) setAudioError(data.error)
      else {
        await fetchJob(selectedJobId)
        await fetchJobs()
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
                <span style={S.tag(job.status === 'audio_launched' ? 'green' : job.status === 'error' ? 'red' : 'violet')}>
                  {job.status?.replace(/_/g, ' ')}
                </span>
              </div>
              {job.error_message && (
                <div style={{ marginTop: '12px', padding: '10px 14px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: '8px', fontSize: '13px', color: '#f87171' }}>
                  <strong>Erreur :</strong> {job.error_message}
                </div>
              )}
            </div>

            {/* Stepper */}
            <Stepper currentStep={currentStep} status={job.status} />

            {/* Erreur action */}
            {actionError && (
              <div style={{ padding: '10px 14px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '8px', fontSize: '13px', color: '#f87171', marginBottom: '16px' }}>
                {actionError}
              </div>
            )}

            {/* ── Étape 1 : Init (affichage seul, déjà fait) ── */}
            <StepBlock stepIndex={0} currentStep={currentStep} status={job.status} title="Recherche RNCP & initialisation" icon="search">
              <div style={{ fontSize: '14px', color: '#94a3b8' }}>
                Job initialisé. RNCP <strong style={{ color: '#a78bfa' }}>{job.rncp_code}</strong> sélectionné pour <strong style={{ color: '#a78bfa' }}>{job.tp_name}</strong>.
              </div>
            </StepBlock>

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
                    Claude va générer un programme de formation complet ({job.nb_days} journées) à partir du REAC.
                  </p>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button style={S.btn('primary')} onClick={() => handleGenerateGlobal()} disabled={actionLoading}>
                      <Icon name="auto_stories" /> Générer (Sonnet)
                    </button>
                    <button style={S.btn('neutral')} onClick={() => handleGenerateGlobal(HAIKU)} disabled={actionLoading} title="~5x moins cher, qualité légèrement inférieure">
                      <Icon name="bolt" /> Générer (Haiku)
                    </button>
                  </div>
                </div>
              )}
            </StepBlock>

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
                        <Icon name="refresh" /> Regénérer (Sonnet)
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
                    Claude va découper le programme global en <strong style={{ color: '#a78bfa' }}>{job.nb_days} journées</strong> de 7h, chacune avec 6 modules.
                  </p>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button style={S.btn('primary')} onClick={() => handleSplitDaily()} disabled={actionLoading || !job.global_program_validated}>
                      <Icon name="calendar_view_week" /> Découper (Sonnet)
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

            {/* ── Étape 6 : Génération des cours (texte) + relecture PDF ── */}
            <StepBlock stepIndex={5} currentStep={currentStep} status={job.status} title="Génération des cours (texte)" icon="edit_note">
              {job.status === 'tts_launched' || job.status === 'audio_launched' || ttsResult ? (
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
                      return (
                        <div key={folder.folder_id} style={{
                          background: 'rgba(15,23,42,0.5)',
                          border: `1px solid ${isError ? 'rgba(239,68,68,0.3)' : isDone ? 'rgba(16,185,129,0.25)' : 'rgba(99,102,241,0.2)'}`,
                          borderRadius: '10px',
                          padding: '12px 14px',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
                            <div style={{ minWidth: 0, flex: 1 }}>
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
                            </div>
                            <div style={{ display: 'flex', gap: '6px' }}>
                              <button
                                style={{ ...S.btn('neutral'), padding: '6px 12px', fontSize: '12px' }}
                                disabled={!isDone}
                                onClick={() => setViewingFolder(folder)}
                                title={isDone ? 'Lire le texte de la journée' : 'En attente de génération'}
                              >
                                <Icon name="visibility" /> Voir
                              </button>
                              <button
                                style={{ ...S.btn('primary'), padding: '6px 12px', fontSize: '12px' }}
                                disabled={!isDone}
                                onClick={() => handleDownloadDocx(folder.folder_id)}
                                title={isDone ? 'Télécharger le programme officiel (Word)' : 'En attente de génération'}
                              >
                                <Icon name="description" /> Word
                              </button>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                    {contentFolders.length === 0 && (
                      <div style={{ fontSize: '13px', color: '#64748b' }}>Chargement de l'état des journées…</div>
                    )}
                  </div>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '8px' }}>
                    Crée <strong style={{ color: '#a78bfa' }}>{job.nb_days} dossiers cours</strong> et génère le texte complet de chaque journée (6 modules × 3 passes Claude).
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
                      <Icon name="edit_note" /> {launchingTTS ? 'Lancement…' : `Générer — Sonnet (${job.nb_days} journées)`}
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

            {/* ── Étape 7 : Synthèse TTS Fish Audio ── */}
            <StepBlock stepIndex={6} currentStep={currentStep} status={job.status} title="Synthèse TTS Fish Audio" icon="record_voice_over">
              {job.status === 'audio_launched' ? (
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#34d399', fontSize: '15px', fontWeight: 600, marginBottom: '12px' }}>
                    <Icon name="check_circle" /> Synthèse audio lancée avec succès !
                  </div>
                  <div style={{ fontSize: '14px', color: '#94a3b8' }}>
                    {contentFolders.length || job.nb_days} dossiers cours en cours de synthèse dans la plateforme{' '}
                    <strong style={{ color: '#a78bfa' }}>{job.platform_name || `#${job.platform_id}`}</strong>.
                    Suivez la progression audio (19 MP3 par journée) dans le <strong style={{ color: '#a78bfa' }}>HR Dashboard → Cours Folders</strong>.
                  </div>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '14px', color: '#94a3b8', marginBottom: '8px' }}>
                    Lance la synthèse <strong style={{ color: '#a78bfa' }}>Fish Audio S2-Pro</strong> pour toutes les journées : 19 MP3 par jour (cours + Q&A + pauses).
                  </p>
                  <p style={{ fontSize: '13px', color: '#475569', marginBottom: '16px' }}>
                    Compter ~1h à 2h par journée. Étape irréversible côté facturation Fish Audio — vérifiez d'abord les textes via "Voir" ou "PDF" ci-dessus.
                  </p>
                  <button
                    style={S.btn('success')}
                    onClick={handleLaunchAudio}
                    disabled={launchingAudio || !allContentCompleted}
                  >
                    <Icon name="record_voice_over" /> {launchingAudio ? 'Lancement…' : `Lancer le TTS (${contentFolders.length || job.nb_days} journées)`}
                  </button>
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
    </div>
  )
}

// ─── Modal de lecture du texte d'une journée ──────────────────────────────────
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
