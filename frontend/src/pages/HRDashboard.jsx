import { useState, useEffect, useRef, useMemo } from 'react'
import { apiUrl } from '../api'
import CoursFoldersModal from '../components/CoursFolders'
import SlideToConfirm, { BackupPipeline } from '../components/SlideToConfirm'

// ─── Material Icon Component ─────────────────────────────────────────────────
const Icon = ({ name, className = '' }) => (
  <span className={`material-icons ${className}`}>{name}</span>
)

const hasCrCdTitle = (title = '') => /\bCRCD\b/i.test(title)
const hasEcTitle = (title = '') => /\bEC\b/i.test(title)
const normalizeRncpCode = (value = '') => String(value).trim().replace(/^RNCP\s*/i, '')
const getPlatformThumbnail = (platform = {}) => {
  const title = platform.name || ''
  const sourceTitle = platform.source_tp_name || ''
  const rncpCode = normalizeRncpCode(platform.source_rncp_code || platform.rncp_code)

  if (rncpCode === '35304' || hasCrCdTitle(title) || hasCrCdTitle(sourceTitle)) {
    return { src: '/tp-crcd-thumbnail.svg', alt: 'TP CRCD' }
  }
  if (hasEcTitle(title) || hasEcTitle(sourceTitle)) return { src: '/tp-ec-thumbnail.svg', alt: 'TP EC' }
  return null
}

// ─── Component ───────────────────────────────────────────────────────────────
export default function HRDashboard() {
  const [platforms, setPlatforms] = useState([])
  const [loading, setLoading] = useState(true)
  const [expandedPlatform, setExpandedPlatform] = useState(null)
  const [platformAudios, setPlatformAudios] = useState({})
  const [playingAudio, setPlayingAudio] = useState(null)
  const [pdfUploading, setPdfUploading] = useState(null)
  const [audiosLoading, setAudiosLoading] = useState(null)
  const [backupJobs, setBackupJobs] = useState({})
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
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newPlatformName, setNewPlatformName] = useState('')
  const [creating, setCreating] = useState(false)
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
  const [newFormTpName, setNewFormTpName] = useState('')
  const [newFormRncp, setNewFormRncp] = useState('')
  const [newFormHours, setNewFormHours] = useState('')
  // Auto-pilot : si activé, une fois le job pipeline initié on appelle l'endpoint
  // /run-auto qui chaîne toutes les étapes (REAC → KB → global → daily → content
  // → review → audio). Sinon, comportement historique : redirection vers
  // /formation-pipeline pour validation manuelle étape par étape.
  const [autoPilot, setAutoPilot] = useState(false)
  const [autoPilotTts, setAutoPilotTts] = useState('gtts')  // 'fish_audio' | 'gtts' | 'mock'
  // Mode d'exécution des étapes IA (KB, global, daily, content, review) :
  // - 'api'          : appels directs à l'API Anthropic (consomme ANTHROPIC_API_KEY)
  // - 'api_deepseek' : appels directs à l'API DeepSeek (consomme DEEPSEEK_API_KEY)
  // - 'claude_code'  : subprocess `claude` local (forfait Pro/Max via OAuth, gratuit côté API)
  // - 'test'         : skip KB/global/daily/content, injecte des DOCX/TXT pré-rédigés.
  //                    La pipeline ne tourne que finalize + review + audio mock + health-check.
  //                    Permet de valider les étapes en aval en ~5 min au lieu de 30-60.
  const [autoPilotMode, setAutoPilotMode] = useState('api')  // 'api' | 'api_deepseek' | 'claude_code' | 'test'
  const [testDocs, setTestDocs] = useState([])  // File[] uploadés pour le mode test
  const backupPollingRef = useRef({})
  const audioRef = useRef(null)
  const [showCoursFoldersModal, setShowCoursFoldersModal] = useState(false)
  const [selectedCoursPlatform, setSelectedCoursPlatform] = useState(null)
  const [cardPage, setCardPage] = useState(0)
  const CARDS_PER_PAGE = 3

  // ─── Fetch data ──────────────────────────────────────────────────────
  const fetchPlatforms = async (refreshSelectedId = null) => {
    try {
      const resp = await fetch(apiUrl('/api/hr/platforms'), { credentials: 'include' })
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
      }
    } catch (e) {
      console.error('Erreur chargement plateformes:', e)
    } finally {
      setLoading(false)
    }
  }

  const fetchAudios = async (platformId) => {
    setAudiosLoading(platformId)
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/audios`), { credentials: 'include' })
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

  useEffect(() => {
    fetchPlatforms()
  }, [])

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
  const handleLock = async (platformId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/toggle-lock`), {
        method: 'POST', credentials: 'include',
      })
      const data = await resp.json()
      if (data.success) fetchPlatforms()
    } catch (e) {
      console.error('Erreur lock:', e)
    }
  }

  const handleBackupAndUnlock = async (platformId) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/backup-and-unlock`), {
        method: 'POST', credentials: 'include',
      })
      const data = await resp.json()
      if (!data.success) {
        setBackupJobs(prev => ({ ...prev, [platformId]: { step_status: 'error', error: data.error } }))
        return
      }
      setBackupJobs(prev => ({ ...prev, [platformId]: { step: 1, step_status: 'running', progress: 0, total: 0 } }))
      startBackupPolling(platformId)
    } catch (e) {
      console.error('Erreur backup-and-unlock:', e)
    }
  }

  const startBackupPolling = (platformId) => {
    if (backupPollingRef.current[platformId]) clearInterval(backupPollingRef.current[platformId])
    backupPollingRef.current[platformId] = setInterval(async () => {
      try {
        const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/backup-status`), { credentials: 'include' })
        const data = await resp.json()
        if (!data.success) return
        setBackupJobs(prev => ({ ...prev, [platformId]: data }))
        if (data.step_status === 'done' || data.step_status === 'error') {
          clearInterval(backupPollingRef.current[platformId])
          if (data.step_status === 'done') fetchPlatforms()
        }
      } catch { /* silencieux */ }
    }, 1500)
  }

  const handleExpandPlatform = (platformId) => {
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
        const resp = await fetch(apiUrl(`/api/hr/platforms/${deleteConfirm.platformId}/audios/${encodeURIComponent(deleteConfirm.filename)}`), {
          method: 'DELETE', credentials: 'include',
        })
        const data = await resp.json()
        if (data.success) {
          fetchAudios(deleteConfirm.platformId)
          fetchPlatforms()
          setDeleteConfirm(null)
        }
      } else if (deleteConfirm.type === 'pdf') {
        const resp = await fetch(apiUrl(`/api/hr/platforms/${deleteConfirm.platformId}/pdf`), {
          method: 'DELETE', credentials: 'include',
        })
        const data = await resp.json()
        if (data.success) {
          fetchPlatforms(deleteConfirm.platformId)
          setDeleteConfirm(null)
        }
      }
    } catch (e) {
      console.error('Erreur suppression:', e)
    } finally {
      setDeletingItem(false)
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

      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/upload-pdf-rag`), {
        method: 'POST', credentials: 'include', body: formData,
      })
      const data = await resp.json()
      if (data.success) fetchPlatforms(platformId)
    } catch (e) {
      console.error('Erreur upload PDF:', e)
    } finally {
      setPdfUploading(null)
    }
  }

  const handleSetCourseTime = async (dateCours, heureCours) => {
    try {
      const resp = await fetch(apiUrl(`/api/hr/platforms/${courseTimePlatformId}/config-cours`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date_cours: dateCours, heure_cours: heureCours }),
      })
      const data = await resp.json()
      return data
    } catch (e) {
      console.error('Erreur config cours:', e)
      return { success: false, error: e.message }
    }
  }

  const handleDeletePdf = (platformId) => {
    const platformName = platforms.find((platform) => platform.id === platformId)?.name
    setDeleteConfirm({ type: 'pdf', platformId, platformName })
  }

  const handleOpenCoursFolders = (platform) => {
    setSelectedCoursPlatform(platform)
    setShowCoursFoldersModal(true)
  }

  const fetchModules = async () => {
    try {
      const resp = await fetch(apiUrl('/api/hr/formation-modules'), { credentials: 'include' })
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
    setFormationMode('existing')
    setSelectedModuleId('')
    setNewFormTpName('')
    setNewFormRncp('')
    setNewFormHours('')
    setAutoPilot(false)
    setAutoPilotTts('gtts')
  }

  // Ouvre la modale en pré-sélectionnant le mode "Nouvelle formation".
  // Utilisé par le bouton "+ Créer un nouveau module" dans la modale Modules.
  const openCreateModuleFlow = () => {
    resetCreateForm()
    fetchModules()
    setFormationMode('new')
    setShowModulesModal(false)
    setShowCreateModal(true)
  }

  const openCreateModal = () => {
    resetCreateForm()
    fetchModules()
    setShowModulesModal(false)
    setShowCreateModal(true)
  }

  const showDashboardView = () => {
    setShowModulesModal(false)
    setShowCreateModal(false)
    setModuleSearchQuery('')
  }

  const showModulesView = () => {
    fetchModules()
    setShowCreateModal(false)
    setShowModulesModal(true)
  }

  const handleCreatePlatform = async () => {
    if (!newPlatformName.trim()) return

    // ─── Branche TEST : bypass /api/hr/platforms, envoie multipart à /init-test ─
    // Crée plateforme + job + folders + segments depuis les DOCX, lance auto-pilot
    // qui skippera KB/global/daily/content. Test ~5 min pipeline en aval.
    if (formationMode === 'new' && autoPilot && autoPilotMode === 'test') {
      const tpName = newFormTpName.trim()
      const rncp = newFormRncp.trim()
      const hours = parseInt(newFormHours, 10)
      if (!tpName || !rncp || !hours || hours <= 0) {
        alert('Nom du TP, code RNCP et durée (h) requis')
        return
      }
      const expectedDocs = Math.ceil(hours / 7)
      if (testDocs.length !== expectedDocs) {
        alert(`Tu dois fournir exactement ${expectedDocs} fichier(s) (1 par journée de 7h). Reçu : ${testDocs.length}`)
        return
      }

      setCreating(true)
      try {
        const fd = new FormData()
        fd.append('platform_name', newPlatformName.trim())
        fd.append('tp_name', tpName)
        fd.append('rncp_code', rncp)
        fd.append('total_hours', String(hours))
        fd.append('tts_mode', 'mock')  // forcé en test
        fd.append('auto_pilot', 'true')
        testDocs.forEach((f) => fd.append('docs', f))

        const resp = await fetch(apiUrl('/api/formation/init-test'), {
          method: 'POST',
          credentials: 'include',
          body: fd,
        })
        const data = await resp.json()
        if (resp.status === 202 && data.ok) {
          setShowCreateModal(false)
          resetCreateForm()
          setTestDocs([])
          fetchPlatforms()
          window.open(`/formation-pipeline?job=${data.job_id}`, '_blank')
        } else {
          alert(`Erreur init-test : ${data.error || 'inconnue'}`)
        }
      } catch (e) {
        console.error('init-test failed:', e)
        alert('Impossible de lancer le test : ' + e.message)
      } finally {
        setCreating(false)
      }
      return
    }

    // ─── Flow normal (API ou Claude Code) ─────────────────────────────────────
    // Validation selon le mode
    let body = { name: newPlatformName.trim() }
    if (formationMode === 'existing') {
      if (!selectedModuleId) {
        alert('Sélectionne un module ou bascule sur "Nouvelle formation"')
        return
      }
      body.module_id = parseInt(selectedModuleId, 10)
    } else if (formationMode === 'new') {
      const tpName = newFormTpName.trim()
      const rncp = newFormRncp.trim()
      const hours = parseInt(newFormHours, 10)
      if (!tpName || !rncp || !hours || hours <= 0) {
        alert('Nom du TP, code RNCP et durée (h) requis pour une nouvelle formation')
        return
      }
      body.new_formation = { tp_name: tpName, rncp_code: rncp, total_hours: hours }
    }
    // formationMode === 'none' → body reste {name} (plateforme vide, comportement historique)

    setCreating(true)
    try {
      const resp = await fetch(apiUrl('/api/hr/platforms'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })
      const data = await resp.json()
      if (data.success) {
        const pipelineJobId = data.platform?.pipeline_job_id
        // Si une pipeline a été lancée et que l'auto-pilot est demandé, on
        // déclenche l'enchaînement automatique avant de fermer la modale.
        if (pipelineJobId && formationMode === 'new' && autoPilot) {
          try {
            const autoResp = await fetch(
              apiUrl(`/api/formation/${pipelineJobId}/run-auto`),
              {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                  tts_mode: autoPilotTts,
                  use_claude_code: autoPilotMode === 'claude_code',
                  model: autoPilotMode === 'api_deepseek' ? 'flash' : 'sonnet',
                }),
              },
            )
            const autoData = await autoResp.json()
            if (autoResp.status !== 202 && autoData.error) {
              alert(`Auto-pilot non démarré : ${autoData.error}`)
            }
          } catch (e) {
            console.error('Auto-pilot start failed:', e)
            alert('Plateforme créée, mais l\'auto-pilot n\'a pas pu démarrer.')
          }
        }
        setShowCreateModal(false)
        resetCreateForm()
        fetchPlatforms()
        // Redirection vers /formation-pipeline pour suivi (auto ou manuel)
        if (pipelineJobId) {
          window.open(`/formation-pipeline?job=${pipelineJobId}`, '_blank')
        }
      } else {
        alert(data.error || 'Erreur lors de la création')
      }
    } catch (e) {
      console.error('Erreur création plateforme:', e)
      alert('Impossible de créer la plateforme')
    } finally {
      setCreating(false)
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

  const colors = darkMode ? {
    bg: '#0f172a',
    cardBg: '#1e293b',
    innerBg: '#0f172a',
    text: '#f1f5f9',
    textSecondary: '#cbd5e1',
    textMuted: '#64748b',
    border: '#334155',
    borderLight: '#1e293b',
    hoverBg: '#1e293b',
    gridOpacity: '0.03'
  } : {
    bg: '#F8F7F5',
    cardBg: '#ffffff',
    innerBg: '#f1f5f9',
    text: '#0f172a',
    textSecondary: '#334155',
    textMuted: '#64748b',
    border: '#e2e8f0',
    borderLight: '#cbd5e1',
    hoverBg: '#f1f5f9',
    gridOpacity: '0.5'
  }

  return (
    <div className={darkMode ? 'dark' : ''}>
      <div className="relative min-h-screen overflow-hidden" style={{ backgroundColor: colors.bg, fontFamily: 'Inter, sans-serif' }}>
        {/* Top Navigation Bar */}
        <div
          className="sticky top-0 z-20 border-b"
          style={{
            backgroundColor: colors.cardBg,
            borderColor: colors.border,
            backdropFilter: 'blur(8px)'
          }}
        >
          <div className="mx-auto max-w-7xl px-6 pt-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex flex-col leading-tight min-w-0">
                <span
                  className="text-[10px] font-semibold uppercase"
                  style={{ fontFamily: 'Inter, sans-serif', color: colors.textMuted, letterSpacing: '0.2em' }}
                >
                  Le Socrate · HR
                </span>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight" style={{ fontFamily: 'Inter, sans-serif', color: colors.text }}>
                  Dashboard Formations
                </h1>
              </div>
              <div className="flex items-center gap-2">
                {/* Back to admin — tertiary navigation, muted text */}
                <a
                  href="/admin"
                  className="flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
                  style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
                  title="Revenir à l'administration P1"
                >
                  <Icon name="arrow_back" className="text-base" />
                  <span>Retour Admin</span>
                </a>
              </div>
            </div>

            <nav className="mt-5 flex items-end gap-10" aria-label="Navigation dashboard formations">
              <SkoolTab
                active={!showModulesModal && !showCreateModal}
                onClick={showDashboardView}
                label="Dashboard"
                colors={colors}
              />
              <SkoolTab
                active={showModulesModal}
                onClick={showModulesView}
                label="Modules"
                colors={colors}
              />
              <SkoolTab
                active={showCreateModal}
                onClick={openCreateModal}
                label="Nouvelle plateforme"
                colors={colors}
              />
            </nav>
          </div>
        </div>

        {/* Background grid pattern */}
        {darkMode && (
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage: `radial-gradient(circle at 20% 30%, rgba(139, 92, 246, 0.1) 0%, transparent 50%),
                 radial-gradient(circle at 80% 70%, rgba(139, 92, 246, 0.08) 0%, transparent 50%),
                 linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
                 linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px)`,
              backgroundSize: '100% 100%, 100% 100%, 32px 32px, 32px 32px',
            }}
          />
        )}

        <div className="relative z-10 mx-auto max-w-7xl px-6 py-8">
          {showModulesModal ? (
            <ModulesCatalogueView
              colors={colors}
              modules={filteredModules}
              moduleSearchQuery={moduleSearchQuery}
              onModuleSearchChange={setModuleSearchQuery}
              onBack={closeModulesModal}
              onCreateModule={openCreateModuleFlow}
              onUseModule={(moduleId) => {
                openCreateModal()
                setFormationMode('existing')
                setSelectedModuleId(String(moduleId))
              }}
            />
          ) : showCreateModal ? (
            <CreatePlatformView
              colors={colors}
              darkMode={darkMode}
              modules={modules}
              newPlatformName={newPlatformName}
              setNewPlatformName={setNewPlatformName}
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
              autoPilotTts={autoPilotTts}
              setAutoPilotTts={setAutoPilotTts}
              autoPilotMode={autoPilotMode}
              setAutoPilotMode={setAutoPilotMode}
              testDocs={testDocs}
              setTestDocs={setTestDocs}
              creating={creating}
              onCreate={handleCreatePlatform}
              onCancel={() => { setShowCreateModal(false); resetCreateForm() }}
            />
          ) : (
            <PlatformCardsView
              platforms={platforms}
              cardPage={cardPage}
              setCardPage={setCardPage}
              cardsPerPage={CARDS_PER_PAGE}
              expandedPlatform={expandedPlatform}
              platformAudios={platformAudios}
              audiosLoading={audiosLoading}
              playingAudio={playingAudio}
              pdfUploading={pdfUploading}
              audioRef={audioRef}
              colors={colors}
              darkMode={darkMode}
              onExpand={handleExpandPlatform}
              onOpenPdfModal={(platform) => {
                setSelectedPlatform(platform)
                setShowPdfModal(true)
              }}
              onOpenCourseTimeModal={async (platform) => {
                setCourseTimePlatformId(platform.id)
                try {
                  const resp = await fetch(apiUrl(`/api/hr/platforms/${platform.id}/course-time`), { credentials: 'include' })
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
            />
          )}
        </div>
      </div>

      {/* Modal Audios */}
      {showAudiosModal && selectedPlatformId && (() => {
        const audiosPlatform = platforms.find(p => p.id === selectedPlatformId)
        return (
          <AudiosModal
            platformId={selectedPlatformId}
            audios={platformAudios[selectedPlatformId] || []}
            loading={audiosLoading === selectedPlatformId}
            onClose={() => setShowAudiosModal(false)}
            darkMode={darkMode}
            recorderUrl={`${(audiosPlatform?.frontend_url || window.location.origin)}/recorder?p=${selectedPlatformId}`}
            onRefreshAudios={() => fetchAudios(selectedPlatformId)}
            uploadLocked={!!audiosPlatform?.upload_locked}
            backupJob={backupJobs[selectedPlatformId] || null}
            onLock={() => handleLock(selectedPlatformId)}
            onBackupAndUnlock={() => handleBackupAndUnlock(selectedPlatformId)}
          />
        )
      })()}

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
          initialHeure={currentCourseTime?.heure_cours}
        />
      )}

      {/* Modal Cours Folders */}
      {showCoursFoldersModal && selectedCoursPlatform && (
        <CoursFoldersModal
          platformId={selectedCoursPlatform.id}
          platformName={selectedCoursPlatform.name}
          onClose={() => setShowCoursFoldersModal(false)}
        />
      )}

      {/* Modal confirmation suppression */}
      {deleteConfirm && (
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

    </div>
  )
}

function SkoolTab({ active, onClick, label, colors }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative pb-4 text-base font-semibold transition-colors"
      style={{ color: active ? colors.text : '#8A8A8A' }}
    >
      {label}
      {active && (
        <span
          className="absolute bottom-[-1px] left-0 h-[3px] w-full"
          style={{ backgroundColor: colors.text }}
        />
      )}
    </button>
  )
}

function PlatformCardsView({
  platforms,
  cardPage,
  setCardPage,
  cardsPerPage,
  expandedPlatform,
  platformAudios,
  audiosLoading,
  playingAudio,
  pdfUploading,
  audioRef,
  colors,
  darkMode,
  onExpand,
  onOpenPdfModal,
  onOpenCourseTimeModal,
  onDeleteAudio,
  onOpenCoursFolders,
  onPlayAudio,
  onPdfUpload,
  onDeletePdf,
}) {
  const totalPages = Math.ceil(platforms.length / cardsPerPage)

  return (
    <>
      {platforms.length > cardsPerPage && (
        <div className="mb-6 flex items-center justify-center gap-3">
          <span className="text-sm" style={{ color: colors.textMuted, fontVariantNumeric: 'tabular-nums' }}>
            Page <span className="font-semibold" style={{ color: colors.text }}>{cardPage + 1}</span> / {totalPages}
          </span>
          <button
            onClick={() => setCardPage(p => Math.max(0, p - 1))}
            disabled={cardPage === 0}
            aria-label="Page précédente"
            className="flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-black/5 dark:hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-30"
            style={{ border: `1px solid ${colors.border}`, color: colors.textSecondary }}
          >
            <Icon name="chevron_left" className="text-xl" />
          </button>
          <button
            onClick={() => setCardPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={cardPage >= totalPages - 1}
            aria-label="Page suivante"
            className="flex h-10 w-10 items-center justify-center rounded-xl transition-colors hover:bg-black/5 dark:hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-30"
            style={{ border: `1px solid ${colors.border}`, color: colors.textSecondary }}
          >
            <Icon name="chevron_right" className="text-xl" />
          </button>
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {platforms.slice(cardPage * cardsPerPage, (cardPage + 1) * cardsPerPage).map((p) => (
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
            onExpand={() => onExpand(p.id)}
            onOpenPdfModal={() => onOpenPdfModal(p)}
            onOpenCourseTimeModal={() => onOpenCourseTimeModal(p)}
            onDeleteAudio={(fn) => onDeleteAudio(p.id, fn)}
            onOpenCoursFolders={() => onOpenCoursFolders(p)}
            onPlayAudio={onPlayAudio}
            onPdfUpload={(file) => onPdfUpload(p.id, file)}
            onDeletePdf={() => onDeletePdf(p.id)}
          />
        ))}
      </div>
    </>
  )
}

function ModulesCatalogueView({
  colors,
  modules,
  moduleSearchQuery,
  onModuleSearchChange,
  onBack,
  onCreateModule,
  onUseModule,
}) {
  return (
    <section
      className="overflow-hidden rounded-2xl"
      style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}` }}
    >
      <header
        className="flex items-start justify-between gap-4 px-7 py-5"
        style={{ borderBottom: `1px solid ${colors.border}` }}
      >
        <div className="flex flex-col leading-tight">
          <span
            className="text-[10px] font-semibold uppercase"
            style={{ color: colors.textMuted, letterSpacing: '0.22em' }}
          >
            Catalogue
          </span>
          <h2 className="mt-1 text-xl font-semibold tracking-tight" style={{ color: colors.text }}>
            Modules de formation
          </h2>
          <p className="mt-1 text-xs" style={{ color: colors.textMuted }}>
            Produits durables des pipelines, réutilisables pour créer une nouvelle plateforme.
          </p>
        </div>
        <button
          onClick={onBack}
          className="flex flex-shrink-0 items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
          style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
        >
          <Icon name="view_module" className="text-base" />
          <span>Plateformes</span>
        </button>
      </header>

      <div
        className="flex items-center gap-3 px-7 py-4"
        style={{ borderBottom: `1px solid ${colors.border}` }}
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
            placeholder="Filtrer par nom de TP ou code RNCP..."
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
          title="Lance une pipeline formation. Mode auto-pilot pour enchaîner toutes les étapes, ou manuel pour valider une à une."
        >
          <Icon name="add" className="text-base" />
          <span>Nouveau module</span>
        </button>
      </div>

      <div className="px-7 py-2">
        {modules.length === 0 ? (
          <div className="py-16 text-center">
            <p className="text-sm font-medium" style={{ color: colors.text }}>
              {moduleSearchQuery
                ? 'Aucun module ne correspond à ce filtre.'
                : 'Aucun module catalogué pour l’instant.'}
            </p>
            <p className="mt-2 text-xs" style={{ color: colors.textMuted }}>
              {moduleSearchQuery
                ? 'Essaie un autre nom de TP ou un code RNCP.'
                : 'Lance une pipeline formation pour produire le premier module durable.'}
            </p>
          </div>
        ) : (
          <ul>
            {modules.map((m, idx) => (
              <li
                key={m.id}
                className="flex items-center gap-5 py-4"
                style={{
                  borderTop: idx === 0 ? 'none' : `1px solid ${colors.border}`,
                  opacity: m.reusable ? 1 : 0.55,
                }}
              >
                <div className="flex w-32 flex-shrink-0 flex-col gap-0.5">
                  <span
                    className="text-[10px] font-semibold uppercase"
                    style={{
                      color: colors.textMuted,
                      letterSpacing: '0.12em',
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    RNCP {m.rncp_code || '—'}
                  </span>
                  <span
                    className="text-xs"
                    style={{
                      color: colors.textSecondary,
                      fontFamily: '"Fira Code", ui-monospace, SFMono-Regular, monospace',
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {m.version}
                  </span>
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold" style={{ color: colors.text }}>
                      {m.tp_name}
                    </span>
                    {m.status === 'validated' && (
                      <span
                        className="flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
                        style={{
                          backgroundColor: 'rgba(16, 185, 129, 0.12)',
                          color: '#10b981',
                          letterSpacing: '0.15em',
                        }}
                      >
                        Validé
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
                        Brouillon
                      </span>
                    )}
                  </div>
                  <p
                    className="mt-1 truncate text-xs"
                    style={{ color: colors.textMuted, fontVariantNumeric: 'tabular-nums' }}
                  >
                    {m.nb_folders} journée{m.nb_folders > 1 ? 's' : ''}
                    {' · Source '}
                    <span style={{ color: colors.textSecondary }}>P{m.source_platform_id}</span>
                    {m.created_at && (
                      <>
                        {' · créé le '}
                        {new Date(m.created_at).toLocaleDateString('fr-FR')}
                      </>
                    )}
                  </p>
                </div>

                <div className="flex-shrink-0">
                  {m.reusable ? (
                    <button
                      onClick={() => onUseModule(m.id)}
                      className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5"
                      style={{ color: colors.textSecondary, border: `1px solid ${colors.border}` }}
                      title="Créer une nouvelle plateforme à partir de ce module"
                    >
                      <span>Utiliser</span>
                      <Icon name="arrow_forward" className="text-sm" />
                    </button>
                  ) : (
                    <span className="text-xs" style={{ color: colors.textMuted }}>
                      {m.nb_folders === 0 ? 'Cours non générés' : 'Non réutilisable'}
                    </span>
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
  newPlatformName,
  setNewPlatformName,
  formationMode,
  setFormationMode,
  selectedModuleId,
  setSelectedModuleId,
  newFormTpName,
  setNewFormTpName,
  newFormRncp,
  setNewFormRncp,
  newFormHours,
  setNewFormHours,
  autoPilot,
  setAutoPilot,
  autoPilotTts,
  setAutoPilotTts,
  autoPilotMode,
  setAutoPilotMode,
  testDocs,
  setTestDocs,
  creating,
  onCreate,
  onCancel,
}) {
  const reusable = modules.filter(m => m.reusable)

  return (
    <section
      className="mx-auto max-w-2xl overflow-hidden rounded-2xl"
      style={{ backgroundColor: colors.cardBg, border: `1px solid ${colors.border}` }}
    >
      <header
        className="flex items-start justify-between gap-4 px-7 py-5"
        style={{ borderBottom: `1px solid ${colors.border}` }}
      >
        <div className="flex flex-col leading-tight">
          <span
            className="text-[10px] font-semibold uppercase"
            style={{ color: colors.textMuted, letterSpacing: '0.22em' }}
          >
            Création
          </span>
          <h2 className="mt-1 text-xl font-semibold tracking-tight" style={{ color: colors.text }}>
            Nouvelle plateforme
          </h2>
        </div>
        <button
          onClick={onCancel}
          disabled={creating}
          className="flex flex-shrink-0 items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
          style={{ color: colors.textMuted, border: `1px solid ${colors.border}` }}
        >
          <Icon name="view_module" className="text-base" />
          <span>Plateformes</span>
        </button>
      </header>

      <div className="p-7">
        <div className="mb-5">
          <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
            Nom de la plateforme
          </label>
          <input
            type="text"
            value={newPlatformName}
            onChange={(e) => setNewPlatformName(e.target.value)}
            placeholder="Ex: TP CRCD Septembre 2026"
            autoFocus
            className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-all"
            style={{
              backgroundColor: darkMode ? '#0f172a' : '#F8F7F5',
              color: darkMode ? '#f1f5f9' : '#1e293b',
              border: `1px solid ${darkMode ? '#334155' : '#e2e8f0'}`,
            }}
          />
          <p className="mt-2 text-xs" style={{ color: darkMode ? '#64748b' : '#94a3b8' }}>
            Nom libre, identifie la promo/session. Ex: "TP CRCD Septembre 2026".
          </p>
        </div>

        <div className="mb-5">
          <label className="mb-2 block text-sm font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
            Module formation
          </label>
          <select
            value={formationMode === 'existing' ? selectedModuleId : (formationMode === 'new' ? '__new__' : '__none__')}
            onChange={(e) => {
              const v = e.target.value
              if (v === '__new__') { setFormationMode('new'); setSelectedModuleId('') }
              else if (v === '__none__') { setFormationMode('none'); setSelectedModuleId('') }
              else { setFormationMode('existing'); setSelectedModuleId(v) }
            }}
            className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-all"
            style={{
              backgroundColor: darkMode ? '#0f172a' : '#F8F7F5',
              color: darkMode ? '#f1f5f9' : '#1e293b',
              border: `1px solid ${darkMode ? '#334155' : '#e2e8f0'}`,
            }}
          >
            <option value="" disabled>Sélectionner un module...</option>
            {reusable.length > 0 && (
              <optgroup label="Modules disponibles (cours + audios prêts)">
                {reusable.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.tp_name} — RNCP {m.rncp_code || '?'} — {m.version} — {m.nb_folders} journée{m.nb_folders > 1 ? 's' : ''}
                  </option>
                ))}
              </optgroup>
            )}
            <option value="__new__">+ Nouvelle formation (lance la pipeline)</option>
            <option value="__none__">Plateforme vide (sans cours)</option>
          </select>
          {formationMode === 'existing' && selectedModuleId && (
            <p className="mt-2 text-xs" style={{ color: '#10b981' }}>
              ✓ Les cours + audios du module seront clonés vers la nouvelle plateforme. Module intact.
            </p>
          )}
          {formationMode === 'new' && (
            <p className="mt-2 text-xs" style={{ color: '#a78bfa' }}>
              ⚙ Un job pipeline va être initié, tu finiras les étapes de validation sur /formation-pipeline.
            </p>
          )}
          {formationMode === 'none' && (
            <p className="mt-2 text-xs" style={{ color: darkMode ? '#64748b' : '#94a3b8' }}>
              Plateforme sans cours, tu pourras uploader du contenu manuellement.
            </p>
          )}
        </div>

        {formationMode === 'new' && (
          <div className="mb-5 rounded-lg p-4" style={{ backgroundColor: darkMode ? '#0f172a' : '#F8F7F5', border: `1px dashed ${darkMode ? '#334155' : '#cbd5e1'}` }}>
            <div className="mb-3">
              <label className="mb-1 block text-xs font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>Nom du TP</label>
              <input type="text" value={newFormTpName} onChange={(e) => setNewFormTpName(e.target.value)} placeholder="Ex: TP CRCD"
                className="w-full rounded-lg px-3 py-2 text-sm outline-none"
                style={{ backgroundColor: darkMode ? '#1e293b' : '#ffffff', color: darkMode ? '#f1f5f9' : '#1e293b', border: `1px solid ${darkMode ? '#334155' : '#e2e8f0'}` }} />
            </div>
            <div className="mb-3">
              <label className="mb-1 block text-xs font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>Code RNCP</label>
              <input type="text" value={newFormRncp} onChange={(e) => setNewFormRncp(e.target.value)} placeholder="Ex: 35304"
                className="w-full rounded-lg px-3 py-2 text-sm outline-none"
                style={{ backgroundColor: darkMode ? '#1e293b' : '#ffffff', color: darkMode ? '#f1f5f9' : '#1e293b', border: `1px solid ${darkMode ? '#334155' : '#e2e8f0'}` }} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>Durée totale (heures)</label>
              <input type="number" value={newFormHours} onChange={(e) => setNewFormHours(e.target.value)} placeholder="Ex: 70" min="1"
                className="w-full rounded-lg px-3 py-2 text-sm outline-none"
                style={{ backgroundColor: darkMode ? '#1e293b' : '#ffffff', color: darkMode ? '#f1f5f9' : '#1e293b', border: `1px solid ${darkMode ? '#334155' : '#e2e8f0'}` }} />
            </div>

            <div className="mt-4 pt-4" style={{ borderTop: `1px dashed ${darkMode ? '#334155' : '#cbd5e1'}` }}>
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  checked={autoPilot}
                  onChange={(e) => setAutoPilot(e.target.checked)}
                  className="mt-1"
                  style={{ accentColor: '#8B5CF6' }}
                />
                <div>
                  <div className="text-xs font-semibold" style={{ color: darkMode ? '#f1f5f9' : '#1e293b' }}>
                    Lancer en mode auto-pilot
                  </div>
                  <div className="mt-1 text-xs" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
                    Toutes les étapes s'enchaînent automatiquement (~30 min à 2 h selon le TTS). Sans cette option, les étapes restent à valider à la main dans l'onglet Formation Pipeline.
                  </div>
                </div>
              </label>

              {autoPilot && (
                <div className="ml-7 mt-3 space-y-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
                      Voix TTS pour l'étape audio
                      {autoPilotMode === 'test' && (
                        <span className="ml-2" style={{ color: '#a78bfa' }}>
                          (forcé en mock pour le mode test)
                        </span>
                      )}
                    </label>
                    <select
                      value={autoPilotMode === 'test' ? 'mock' : autoPilotTts}
                      onChange={(e) => setAutoPilotTts(e.target.value)}
                      disabled={autoPilotMode === 'test'}
                      className="w-full rounded-lg px-3 py-2 text-sm outline-none"
                      style={{
                        backgroundColor: darkMode ? '#1e293b' : '#ffffff',
                        color: darkMode ? '#f1f5f9' : '#1e293b',
                        border: `1px solid ${darkMode ? '#334155' : '#e2e8f0'}`,
                        opacity: autoPilotMode === 'test' ? 0.5 : 1,
                      }}
                    >
                      <option value="gtts">gTTS — voix basique gratuite (recommandé pour test)</option>
                      <option value="mock">Mock — silence 1 s (gratuit, pour tester l'orchestration)</option>
                      <option value="fish_audio">Fish Audio S2-Pro (payant, ~9$/journée)</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
                      Mode d'exécution des étapes IA (KB · global · daily · content · review)
                    </label>
                    <select
                      value={autoPilotMode}
                      onChange={(e) => setAutoPilotMode(e.target.value)}
                      className="w-full rounded-lg px-3 py-2 text-sm outline-none"
                      style={{ backgroundColor: darkMode ? '#1e293b' : '#ffffff', color: darkMode ? '#f1f5f9' : '#1e293b', border: `1px solid ${darkMode ? '#334155' : '#e2e8f0'}` }}
                    >
                      <option value="api">API Anthropic — paie ta clé ANTHROPIC_API_KEY (~5–7$ pour 7h Sonnet)</option>
                      <option value="api_deepseek">API DeepSeek — paie ta clé DEEPSEEK_API_KEY (deepseek-v4-flash)</option>
                      <option value="claude_code">Claude Code local — forfait Pro/Max via OAuth (gratuit côté API)</option>
                      <option value="test">TEST — injecte des DOCX/TXT pré-rédigés (skip génération, ~5 min)</option>
                    </select>
                    <div className="mt-1 text-xs" style={{ color: darkMode ? '#64748b' : '#94a3b8' }}>
                      {autoPilotMode === 'claude_code' && 'Le backend doit avoir LOCAL_DEV=true et le binaire `claude` dans son PATH.'}
                      {autoPilotMode === 'api' && 'Mode standard, aucune dépendance locale requise.'}
                      {autoPilotMode === 'api_deepseek' && 'Le backend doit avoir DEEPSEEK_API_KEY dans son .env. Endpoint compatible Anthropic, route automatique sur api.deepseek.com.'}
                      {autoPilotMode === 'test' && 'Skip KB/global/daily/content + volume safety (tu fournis 1 DOCX/TXT par journée). Seule la révision conformité tourne (Claude Code Sonnet, ~15 min). Audio en mock. Pour itérer vite sur la qualité review.'}
                    </div>
                  </div>

                  {autoPilotMode === 'test' && (
                    <div
                      className="rounded-lg border-2 border-dashed p-3"
                      style={{
                        borderColor: '#a78bfa',
                        backgroundColor: darkMode ? '#1e293b' : '#faf7ff',
                      }}
                    >
                      <label className="mb-2 block text-xs font-semibold" style={{ color: '#8B5CF6' }}>
                        📄 Documents source (1 par journée — total {Math.max(1, Math.ceil((parseInt(newFormHours, 10) || 7) / 7))})
                      </label>
                      <input
                        type="file"
                        accept=".docx,.txt"
                        multiple
                        onChange={(e) => setTestDocs(Array.from(e.target.files || []))}
                        className="block w-full text-xs"
                        style={{ color: darkMode ? '#cbd5e1' : '#475569' }}
                      />
                      {testDocs.length > 0 && (
                        <ul className="mt-2 space-y-1 text-xs" style={{ color: darkMode ? '#94a3b8' : '#64748b' }}>
                          {testDocs.map((f, i) => (
                            <li key={i}>
                              <span className="font-mono">Jour {i + 1}</span> · {f.name} ({(f.size / 1024).toFixed(1)} ko)
                            </li>
                          ))}
                        </ul>
                      )}
                      <div className="mt-2 text-xs" style={{ color: '#a78bfa' }}>
                        Chaque fichier sera découpé en 18 segments (6 sous-parties × 3 passes). Les 18 segments alimenteront review + audio.
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        <div className="flex justify-end gap-3">
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
            disabled={creating || !newPlatformName.trim()}
            className="rounded-lg px-5 py-2 text-sm font-medium text-white transition-all"
            style={{
              backgroundColor: creating || !newPlatformName.trim() ? '#a78bfa' : '#8B5CF6',
              opacity: creating || !newPlatformName.trim() ? 0.6 : 1,
            }}
          >
            {creating ? 'Création...' : 'Créer la plateforme'}
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
  darkMode,
  recorderUrl,
  onRefreshAudios,
  uploadLocked = false,
  backupJob = null,
  onLock = () => {},
  onBackupAndUnlock = () => {},
}) {
  // État dérivé du backup job pour BackupPipeline.
  const isBackupRunning = backupJob && backupJob.step_status === 'running'
  const isBackupDone = backupJob && backupJob.step_status === 'done'
  const isBackupError = backupJob && backupJob.step_status === 'error'
  // Mini colors object pour BackupPipeline (qui en attend une forme précise).
  const pipelineColors = darkMode
    ? { innerBg: '#0f172a', border: '#334155', cardBg: '#1e293b', text: '#f1f5f9', textMuted: '#64748b' }
    : { innerBg: '#F8F7F5', border: '#e2e8f0', cardBg: '#ffffff', text: '#0f172a', textMuted: '#64748b' }
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
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/cours-folders`), { credentials: 'include' })
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
      const resp = await fetch(apiUrl(`/api/hr/platforms/${platformId}/fill-from-folder`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
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
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#e2e8f0', backgroundColor: '#137fec' }}>
          <div className="flex items-center gap-3 text-white">
            <Icon name="audiotrack" className="text-2xl" />
            <h3 className="text-lg font-bold">AUDIOS FORMATION</h3>
          </div>
          <div className="flex items-center gap-2">
            <div style={{ width: 190 }}>
              <SlideToConfirm
                compact
                locked={uploadLocked}
                onConfirm={uploadLocked ? onBackupAndUnlock : onLock}
                disabled={isBackupRunning}
                onDark
              />
            </div>
            <button
              onClick={handleOpenFillModal}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
              style={{ backgroundColor: 'rgba(255,255,255,0.2)', color: 'white' }}
              onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.3)'}
              onMouseLeave={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.2)'}
            >
              <Icon name="drive_folder_upload" className="text-base" />
              <span>Remplir avec les audios</span>
            </button>
            <a
              href={recorderUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
              style={{ backgroundColor: 'rgba(255,255,255,0.2)', color: 'white' }}
              onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.3)'}
              onMouseLeave={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.2)'}
            >
              <Icon name="upload" className="text-base" />
              <span>Uploader</span>
            </a>
            <button
              onClick={onClose}
              aria-label="Fermer"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-white transition-colors active:scale-[0.98]"
              style={{ backgroundColor: 'transparent' }}
              onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.16)'}
              onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
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
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ backgroundColor: '#137fec' }}>
                    <Icon name="drive_folder_upload" className="text-white text-xl" />
                  </div>
                  <h4 className="text-base font-bold text-slate-800">Remplir avec les audios</h4>
                </div>

                <p className="text-sm text-slate-500 mb-4">
                  Choisissez le dossier de cours à utiliser. Les 7 fichiers cours générés + les Q&A et pauses seront copiés dans la plateforme.
                </p>

                {loadingFolders ? (
                  <div className="flex justify-center py-4">
                    <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-blue-500" />
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
                      style={{ backgroundColor: filling || !selectedFillFolderId ? '#93c5fd' : '#137fec' }}
                    >
                      {filling ? 'Copie en cours...' : 'Remplir'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Backup pipeline — affiché en bandeau sous le header quand le job est actif */}
        {(isBackupRunning || isBackupDone || isBackupError) && (
          <div className="px-6 pt-4">
            <BackupPipeline job={backupJob} colors={pipelineColors} darkMode={darkMode} />
          </div>
        )}

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto" style={{ maxHeight: 'calc(90vh - 80px)' }}>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-blue-500" />
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
function PlatformCard({
  platform: p, expanded, audios, audiosLoading, playingAudio, pdfUploading,
  audioRef, colors, darkMode, onExpand, onOpenPdfModal, onOpenCourseTimeModal, onDeleteAudio, onPlayAudio, onPdfUpload, onDeletePdf, onOpenCoursFolders,
}) {
  const pdfInputId = `pdf-input-${p.id}`
  const platformThumbnail = getPlatformThumbnail(p)

  return (
    <div
      className="relative rounded-2xl overflow-hidden transition-all duration-300"
      style={{
        backgroundColor: colors.cardBg,
        border: p.active ? '1px solid #E4E4E4' : `1px solid ${colors.border}`,
        boxShadow: darkMode ? 'none' : '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.1)'
      }}
    >
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
      {p.active && p.status === 'pending' && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center rounded-2xl"
          style={{ backgroundColor: darkMode ? 'rgba(15, 23, 42, 0.92)' : 'rgba(248, 250, 252, 0.98)', backdropFilter: 'blur(4px)' }}
        >
          <div className="text-center px-6">
            <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-[3px]"
              style={{ borderColor: darkMode ? '#334155' : '#e2e8f0', borderTopColor: '#8B5CF6' }} />
            <p className="text-sm font-semibold mb-1" style={{ color: colors.text }}>
              {p.source_formation_id ? 'Clone des cours en cours' : 'Module en construction'}
            </p>
            <p className="text-xs mb-4" style={{ color: colors.textMuted }}>
              {p.source_formation_id
                ? 'Copie des cours + blobs Azure — quelques instants…'
                : 'La pipeline est initiée. Finalise les étapes sur la page de suivi.'}
            </p>
            {!p.source_formation_id && (
              <a
                href="/formation-pipeline"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-medium transition-all"
                style={{
                  backgroundColor: '#8B5CF6',
                  color: 'white',
                  textDecoration: 'none',
                }}
              >
                <Icon name="open_in_new" className="text-sm" />
                Suivre la pipeline
              </a>
            )}
          </div>
        </div>
      )}

      {/* Error overlay : clone ou pipeline échoué */}
      {p.active && p.status === 'error' && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center rounded-2xl"
          style={{ backgroundColor: darkMode ? 'rgba(15, 23, 42, 0.92)' : 'rgba(248, 250, 252, 0.98)', backdropFilter: 'blur(4px)' }}
        >
          <div className="text-center px-6">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full" style={{ backgroundColor: '#fee2e2' }}>
              <Icon name="error" className="text-2xl" style={{ color: '#dc2626' }} />
            </div>
            <p className="text-sm font-semibold mb-1" style={{ color: colors.text }}>Erreur de setup</p>
            <p className="text-xs" style={{ color: colors.textMuted }}>Voir les logs backend pour le détail.</p>
          </div>
        </div>
      )}

      <div className="p-6">
        {platformThumbnail && (
          <div
            className="mb-5 overflow-hidden rounded-xl"
            style={{
              aspectRatio: '16 / 7.2',
              border: '1px solid #E4E4E4',
              backgroundColor: '#F8F7F5',
            }}
          >
            <img
              src={platformThumbnail.src}
              alt={platformThumbnail.alt}
              className="h-full w-full object-cover"
              draggable={false}
            />
          </div>
        )}

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
              P{p.id}
            </span>
            <h3 className="truncate text-lg font-semibold leading-tight tracking-tight" style={{ color: colors.text }}>
              {p.name}
            </h3>
          </div>
          {p.active && (
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

        {/* === Group A : tuiles d'actions internes en grille 2×2 ===
            Layout horizontal compact (icône à gauche, label à droite). Les
            icônes restent slate au rest pour préserver "The One Voice Rule"
            de DESIGN.md — le seul signal violet du card body est l'état
            actif de la tuile Audios quand son panel est déplié. */}
        <div className="mb-3 grid grid-cols-2 gap-2">
          {/* PDF — toujours visible (l'overlay couvre le card si !p.active) */}
          <button
            onClick={onOpenPdfModal}
            className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
            style={{
              border: `1px solid ${colors.border}`,
              color: colors.textSecondary,
            }}
          >
            <Icon name="picture_as_pdf" className="text-lg" style={{ color: colors.textMuted }} />
            <span>PDF</span>
          </button>

          {/* Heure du cours */}
          {p.active && (
            <button
              onClick={onOpenCourseTimeModal}
              className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
              style={{
                border: `1px solid ${colors.border}`,
                color: colors.textSecondary,
              }}
            >
              <Icon name="schedule" className="text-lg" style={{ color: colors.textMuted }} />
              <span>Heure</span>
            </button>
          )}

          {/* Audios — l'unique tuile à état actif violet (signal "panel ouvert sous la grille") */}
          {p.active && (
            <button
              onClick={onExpand}
              className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
              style={
                expanded
                  ? {
                      backgroundColor: 'rgba(139, 92, 246, 0.10)',
                      border: '1px solid rgba(139, 92, 246, 0.35)',
                      color: darkMode ? '#c4b5fd' : '#7c3aed',
                    }
                  : {
                      border: `1px solid ${colors.border}`,
                      color: colors.textSecondary,
                    }
              }
            >
              <Icon
                name="audiotrack"
                className="text-lg"
                style={{ color: expanded ? (darkMode ? '#c4b5fd' : '#7c3aed') : colors.textMuted }}
              />
              <span>Audios</span>
            </button>
          )}

          {/* Gérer les cours */}
          {p.active && (
            <button
              onClick={onOpenCoursFolders}
              className="group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium tracking-tight transition-colors hover:bg-black/5 dark:hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40"
              style={{
                border: `1px solid ${colors.border}`,
                color: colors.textSecondary,
              }}
            >
              <Icon name="folder_special" className="text-lg" style={{ color: colors.textMuted }} />
              <span>Cours</span>
            </button>
          )}
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
            href={`${p.frontend_url || window.location.origin}/?p=${p.id}`}
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

        {/* Lien vers la page admin de la plateforme (login-admin sur le domaine
            distant pour que la session admin se crée localement sur le bon
            backend ; ?p= garantit le platform_id correct dans le localStorage). */}
        {p.active && (
          <a
            href={`${p.frontend_url || window.location.origin}/login-admin?p=${p.id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex w-full items-center justify-between rounded-md px-3 py-2 text-sm transition-colors hover:bg-black/5 dark:hover:bg-white/5"
            style={{
              color: colors.textSecondary,
              textDecoration: 'none',
            }}
          >
            <span>Admin</span>
            <Icon name="open_in_new" className="text-base" style={{ color: colors.textMuted }} />
          </a>
        )}

      </div>
    </div>
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

// SlideToConfirm + BackupPipeline ont été déplacés vers
// `components/SlideToConfirm.jsx` pour être partagés avec CoursFoldersModal,
// qui héberge maintenant l'action lock/unlock + le pipeline de backup.

// ─── Course Time Modal ───────────────────────────────────────────────────────
function CourseTimeModal({ onClose, onSubmit, initialDate, initialHeure }) {
  const today = new Date().toISOString().split('T')[0]
  const [date, setDate] = useState(initialDate || today)
  const [heure, setHeure] = useState(initialHeure || '')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!date || !heure) return
    setLoading(true)
    setResult(null)
    const data = await onSubmit(date, heure)
    setResult(data)
    setLoading(false)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl overflow-hidden"
        style={{ width: '100%', maxWidth: '420px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#e2e8f0', backgroundColor: '#137fec' }}>
          <div className="flex items-center gap-3 text-white">
            <Icon name="schedule" className="text-2xl" />
            <h3 className="text-lg font-bold">HEURE DU COURS</h3>
          </div>
          <button
            onClick={onClose}
            className="text-white hover:bg-white/20 rounded-full p-1 transition-colors"
          >
            <Icon name="close" className="text-2xl" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6">
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
              <div>
                <label className="block text-xs font-semibold mb-1.5" style={{ color: '#334155' }}>Heure de début</label>
                <input
                  type="time"
                  value={heure}
                  onChange={(e) => setHeure(e.target.value)}
                  required
                  className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                  style={{ borderColor: '#e2e8f0', color: '#0f172a', backgroundColor: '#F8F7F5' }}
                  onFocus={(e) => { e.currentTarget.style.borderColor = '#137fec' }}
                  onBlur={(e) => { e.currentTarget.style.borderColor = '#e2e8f0' }}
                />
              </div>

              {result && !result.success && (
                <p className="text-xs rounded-lg px-3 py-2" style={{ color: '#dc2626', backgroundColor: '#fee2e2' }}>
                  {result.error || 'Une erreur est survenue'}
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
                  style={{ backgroundColor: '#137fec', opacity: (loading || !date || !heure) ? 0.6 : 1 }}
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
        </div>
      </div>
    </div>
  )
}
