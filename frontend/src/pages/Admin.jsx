import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Sidebar from '../components/Sidebar.jsx'
import { apiFetch, apiUrl, getPlatformId, setPlatformId, setPlatformName } from '../api'

export default function Admin() {
  const [search, setSearch] = useState('')
  const [logs, setLogs] = useState([])
  const [heureDebut, setHeureDebut] = useState('')
  const [tempsTotal, setTempsTotal] = useState('')
  const [loading, setLoading] = useState(true)
  const [configDate, setConfigDate] = useState('')
  const [configHeure, setConfigHeure] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [studentAccounts, setStudentAccounts] = useState([])
  const [studentForm, setStudentForm] = useState({ email: '', password: '', nom: '', prenom: '' })
  const [studentMessage, setStudentMessage] = useState('')
  const [studentError, setStudentError] = useState('')
  const [internalDashboard, setInternalDashboard] = useState(null)
  const [internalLoading, setInternalLoading] = useState(true)
  const [internalError, setInternalError] = useState('')

  // État pour l'upload PDF
  const [pdfFile, setPdfFile] = useState(null)
  const [pdfDragOver, setPdfDragOver] = useState(false)
  const [pdfUploading, setPdfUploading] = useState(false)
  const [pdfMessage, setPdfMessage] = useState('')
  const [pdfMessageType, setPdfMessageType] = useState('') // 'success', 'error', 'info'
  const [indexerPolling, setIndexerPolling] = useState(false)

  // Restaurer platform_id depuis ?p= si présent (cas refresh en navigation privée).
  const [searchParams] = useSearchParams()
  const currentPlatformId = searchParams.get('p') || getPlatformId()
  useEffect(() => {
    const pParam = searchParams.get('p')
    if (pParam) {
      setPlatformId(pParam)
      fetch(apiUrl(`/api/platform-info?id=${pParam}`))
        .then(r => r.json())
        .then(data => { if (data.name) setPlatformName(data.name) })
        .catch(() => {})
    }
  }, [searchParams])

  const fetchLogs = useCallback(async () => {
    try {
      setLoading(true)
      const url = search
        ? `/api/admin/logs?prenom=${encodeURIComponent(search)}`
        : '/api/admin/logs'

      const response = await apiFetch(url)

      if (response.ok) {
        const data = await response.json()
        setLogs(data.logs || [])
        setHeureDebut(data.heure_debut_cours || '')
        setTempsTotal(data.temps_total || '')

        // Initialiser les champs de config avec l'heure actuelle
        if (data.heure_debut_cours && !configDate) {
          const [date, heure] = data.heure_debut_cours.split(' ')
          setConfigDate(date)
          setConfigHeure(heure.substring(0, 5)) // HH:MM seulement
        }
      }
    } catch (error) {
      console.error('Erreur chargement logs:', error)
    } finally {
      setLoading(false)
    }
  }, [configDate, search])

  const filteredLogs = useMemo(
    () => logs,
    [logs]
  )

  const fetchStudentAccounts = useCallback(async () => {
    try {
      const response = await apiFetch('/api/admin/student-accounts')
      const data = await response.json()
      if (response.ok && data.success) {
        setStudentAccounts(data.accounts || [])
      }
    } catch (error) {
      console.error('Erreur chargement comptes élèves:', error)
    }
  }, [])

  const fetchInternalDashboard = useCallback(async () => {
    try {
      setInternalLoading(true)
      setInternalError('')
      const response = await apiFetch('/api/admin/internal-dashboard')
      const data = await response.json()
      if (response.ok && data.success) {
        setInternalDashboard(data)
      } else if (response.status !== 403) {
        setInternalError(data.error || 'Erreur lors du chargement du dashboard interne')
      }
    } catch (error) {
      console.error('Erreur dashboard interne:', error)
      setInternalError('Erreur de connexion au serveur')
    } finally {
      setInternalLoading(false)
    }
  }, [])

  // Charger les logs depuis l'API
  useEffect(() => {
    Promise.resolve().then(() => {
      fetchLogs()
      fetchStudentAccounts()
    })
  }, [fetchLogs, fetchStudentAccounts])

  useEffect(() => {
    Promise.resolve().then(() => {
      fetchInternalDashboard()
    })
  }, [fetchInternalDashboard])

  // Vérifier le statut de l'indexer au chargement (persistance après refresh)
  useEffect(() => {
    const checkIndexerOnLoad = async () => {
      try {
        const resp = await fetch(apiUrl('/api/admin/indexer-status'), { credentials: 'include' })
        const data = await resp.json()
        if (data.success && data.status === 'inProgress') {
          // Indexation en cours détectée → lancer le polling
          setIndexerPolling(true)
          setPdfMessage('Indexation en cours...')
          setPdfMessageType('info')

          const interval = setInterval(async () => {
            try {
              const r = await fetch(apiUrl('/api/admin/indexer-status'), { credentials: 'include' })
              const d = await r.json()
              if (d.success) {
                if (d.status === 'success') {
                  setPdfMessage('Indexation terminee !')
                  setPdfMessageType('success')
                  setIndexerPolling(false)
                  clearInterval(interval)
                } else if (d.status === 'transientFailure' || d.status === 'persistentFailure') {
                  setPdfMessage(d.message)
                  setPdfMessageType('error')
                  setIndexerPolling(false)
                  clearInterval(interval)
                }
              }
            } catch {
              setIndexerPolling(false)
              clearInterval(interval)
            }
          }, 3000)
        }
      } catch {
        // Silencieux — pas critique au chargement
      }
    }
    checkIndexerOnLoad()
  }, [])

  const handleStudentFormChange = (event) => {
    const { name, value } = event.target
    setStudentForm((current) => ({ ...current, [name]: value }))
  }

  const handleCreateStudent = async (event) => {
    event.preventDefault()
    setStudentMessage('')
    setStudentError('')
    try {
      const response = await apiFetch('/api/admin/student-accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(studentForm),
      })
      const data = await response.json()
      if (response.ok && data.success) {
        setStudentMessage(data.message || 'Compte créé')
        setStudentForm({ email: '', password: '', nom: '', prenom: '' })
        fetchStudentAccounts()
      } else {
        setStudentError(data.error || 'Erreur lors de la création')
      }
    } catch (error) {
      console.error('Erreur création compte élève:', error)
      setStudentError('Erreur de connexion au serveur')
    }
  }

  const handleToggleStudent = async (account) => {
    setStudentMessage('')
    setStudentError('')
    try {
      const response = await apiFetch(`/api/admin/student-accounts/${account.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !account.is_active }),
      })
      const data = await response.json()
      if (response.ok && data.success) {
        setStudentMessage(data.message || 'Compte mis à jour')
        fetchStudentAccounts()
      } else {
        setStudentError(data.error || 'Erreur lors de la mise à jour')
      }
    } catch (error) {
      console.error('Erreur mise à jour compte élève:', error)
      setStudentError('Erreur de connexion au serveur')
    }
  }

  const handleExportExcel = async () => {
    try {
      const response = await apiFetch('/api/admin/export_excel')
      if (!response.ok) {
        alert('Erreur lors de l\'export Excel')
        return
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'export_logs.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('Erreur de connexion au serveur')
    }
  }

  const handleConfigSubmit = async (e) => {
    e.preventDefault()
    setSuccessMessage('')
    setErrorMessage('')

    try {
      const response = await apiFetch('/api/admin/config_cours', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          date_cours: configDate,
          heure_cours: configHeure,
        }),
      })

      const data = await response.json()

      if (response.ok && data.success) {
        setSuccessMessage(data.message)
        // Recharger les logs pour avoir l'heure mise à jour
        fetchLogs()
      } else {
        setErrorMessage(data.error || 'Erreur lors de la mise à jour')
      }
    } catch (error) {
      console.error('Erreur config cours:', error)
      setErrorMessage('Erreur de connexion au serveur')
    }
  }

  const handleForceLogout = async () => {
    if (!confirm('Voulez-vous vraiment forcer la déconnexion de tous les utilisateurs ?')) {
      return
    }

    try {
      const response = await apiFetch('/api/admin/force-logout-finished-users', {
        method: 'POST',
      })

      const data = await response.json()

      if (response.ok && data.success) {
        alert(data.message)
        fetchLogs() // Recharger pour voir les mises à jour
      } else {
        alert(data.error || 'Erreur lors de la déconnexion')
      }
    } catch (error) {
      console.error('Erreur force logout:', error)
      alert('Erreur de connexion au serveur')
    }
  }

  const handlePdfDrop = (e) => {
    e.preventDefault()
    setPdfDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file && file.type === 'application/pdf') {
      setPdfFile(file)
      setPdfMessage('')
    } else {
      setPdfMessage('Seuls les fichiers PDF sont acceptés')
      setPdfMessageType('error')
    }
  }

  const handlePdfSelect = (e) => {
    const file = e.target.files[0]
    if (file) {
      setPdfFile(file)
      setPdfMessage('')
    }
  }

  const pollIndexerStatus = () => {
    setIndexerPolling(true)
    setPdfMessage('Indexation en cours...')
    setPdfMessageType('info')

    const interval = setInterval(async () => {
      try {
        const resp = await fetch(apiUrl('/api/admin/indexer-status'), { credentials: 'include' })
        const data = await resp.json()

        if (data.success) {
          if (data.status === 'success') {
            setPdfMessage('Indexation terminee !')
            setPdfMessageType('success')
            setIndexerPolling(false)
            clearInterval(interval)
          } else if (data.status === 'transientFailure' || data.status === 'persistentFailure') {
            setPdfMessage(data.message)
            setPdfMessageType('error')
            setIndexerPolling(false)
            clearInterval(interval)
          }
          // sinon inProgress → on continue le polling
        }
      } catch {
        setPdfMessage('Erreur de connexion')
        setPdfMessageType('error')
        setIndexerPolling(false)
        clearInterval(interval)
      }
    }, 3000)
  }

  const handlePdfUpload = async () => {
    if (!pdfFile) return

    setPdfUploading(true)
    setPdfMessage('Upload en cours...')
    setPdfMessageType('info')

    try {
      const formData = new FormData()
      formData.append('file', pdfFile)

      const resp = await fetch(apiUrl('/api/admin/upload-pdf'), {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })

      const data = await resp.json()

      if (resp.ok && data.success) {
        setPdfMessage(data.message)
        setPdfMessageType('success')
        setPdfFile(null)
        // Lancer le polling du statut de l'indexer
        pollIndexerStatus()
      } else {
        setPdfMessage(data.error || 'Erreur lors de l\'upload')
        setPdfMessageType('error')
      }
    } catch {
      setPdfMessage('Erreur de connexion au serveur')
      setPdfMessageType('error')
    } finally {
      setPdfUploading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 px-4 py-8 md:px-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-gray-700 bg-gray-800/90 px-5 py-5 shadow-lg backdrop-blur-sm">
          <div>
            <h2 className="text-2xl font-semibold text-white">Administration</h2>
            <p className="mt-1 text-sm text-gray-400">Historique de connexions et configuration du cours</p>
          </div>
          <div className="flex items-center gap-2">
            <a
              href="/hr-dashboard"
              className="rounded-lg border border-fuchsia-500/40 bg-fuchsia-900/30 px-4 py-2 text-sm font-medium text-fuchsia-200 transition hover:-translate-y-0.5 hover:bg-fuchsia-900/50"
            >
              Dashboard RH
            </a>
            <a
              href={`/debug?p=${currentPlatformId}`}
              className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-900 transition hover:-translate-y-0.5 hover:bg-gray-100"
            >
              Debug cours
            </a>
            <a
              href="/logout_admin"
              className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-900 transition hover:-translate-y-0.5 hover:bg-gray-100"
            >
              Se déconnecter
            </a>
          </div>
        </div>

        <Sidebar>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-white">Pilotage interne SaaS</h3>
              <p className="mt-1 text-sm text-gray-400">
                Centres de formation, comptes élèves et dernières connexions. Les mots de passe ne sont jamais affichés.
              </p>
            </div>
            <button
              type="button"
              onClick={fetchInternalDashboard}
              className="rounded-lg border border-gray-600 bg-gray-700 px-3 py-2 text-sm text-gray-100 transition hover:bg-gray-600"
            >
              Actualiser
            </button>
          </div>

          {internalLoading && (
            <p className="mt-4 text-sm text-gray-400">Chargement du dashboard interne...</p>
          )}
          {internalError && (
            <div className="mt-4 rounded-xl border border-rose-400/40 bg-rose-900/30 p-3 text-sm text-rose-200">
              {internalError}
            </div>
          )}

          {internalDashboard && (
            <div className="mt-5 space-y-6">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                {[
                  ['Centres', internalDashboard.summary?.center_count ?? 0],
                  ['Centres clients', internalDashboard.summary?.external_center_count ?? 0],
                  ['Comptes élèves', internalDashboard.summary?.student_count ?? 0],
                  ['Logs récents', internalDashboard.summary?.recent_log_count ?? 0],
                  ['Sessions actives', internalDashboard.summary?.active_session_count ?? 0],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl border border-gray-700 bg-gray-900/60 p-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</p>
                    <p className="mt-2 text-2xl font-semibold text-white">{value}</p>
                  </div>
                ))}
              </div>

              <div>
                <div className="mb-3 flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-white">Centres de formation</h4>
                  <span className="text-xs text-gray-500">Mot de passe: statut uniquement</span>
                </div>
                <div className="overflow-x-auto rounded-xl border border-gray-700">
                  <table className="w-full min-w-[980px] border-separate border-spacing-0 text-sm text-gray-200">
                    <thead className="bg-gray-900/70">
                      <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
                        <th className="border-b border-gray-700 px-3 py-3">Centre</th>
                        <th className="border-b border-gray-700 px-3 py-3">Utilisateur</th>
                        <th className="border-b border-gray-700 px-3 py-3">Email</th>
                        <th className="border-b border-gray-700 px-3 py-3">Mot de passe</th>
                        <th className="border-b border-gray-700 px-3 py-3">Plateformes</th>
                        <th className="border-b border-gray-700 px-3 py-3">Élèves</th>
                        <th className="border-b border-gray-700 px-3 py-3">Logs</th>
                        <th className="border-b border-gray-700 px-3 py-3">Statut</th>
                      </tr>
                    </thead>
                    <tbody>
                      {internalDashboard.centers?.map((center) => (
                        <tr key={center.internal ? 'internal' : center.id} className="transition hover:bg-gray-700/40">
                          <td className="border-b border-gray-800 px-3 py-3">
                            <div className="font-medium text-white">{center.center_name}</div>
                            <div className="text-xs text-gray-500">{center.slug || '-'}</div>
                          </td>
                          <td className="border-b border-gray-800 px-3 py-3">{center.username || '-'}</td>
                          <td className="border-b border-gray-800 px-3 py-3">{center.email || '-'}</td>
                          <td className="border-b border-gray-800 px-3 py-3 text-gray-400">{center.password_status}</td>
                          <td className="border-b border-gray-800 px-3 py-3">{center.platform_count}</td>
                          <td className="border-b border-gray-800 px-3 py-3">{center.student_count}</td>
                          <td className="border-b border-gray-800 px-3 py-3">{center.log_count}</td>
                          <td className="border-b border-gray-800 px-3 py-3">
                            {center.is_active ? 'Actif' : 'Désactivé'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="grid gap-6 xl:grid-cols-2">
                <div>
                  <h4 className="mb-3 text-sm font-semibold text-white">Comptes élèves récents</h4>
                  <div className="max-h-[360px] overflow-auto rounded-xl border border-gray-700">
                    <table className="w-full min-w-[760px] border-separate border-spacing-0 text-sm text-gray-200">
                      <thead className="sticky top-0 bg-gray-900">
                        <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
                          <th className="border-b border-gray-700 px-3 py-3">Email</th>
                          <th className="border-b border-gray-700 px-3 py-3">Nom</th>
                          <th className="border-b border-gray-700 px-3 py-3">Centre</th>
                          <th className="border-b border-gray-700 px-3 py-3">Plateforme</th>
                          <th className="border-b border-gray-700 px-3 py-3">Mot de passe</th>
                          <th className="border-b border-gray-700 px-3 py-3">Statut</th>
                        </tr>
                      </thead>
                      <tbody>
                        {internalDashboard.students?.map((student) => (
                          <tr key={student.id} className="transition hover:bg-gray-700/40">
                            <td className="border-b border-gray-800 px-3 py-3">{student.email}</td>
                            <td className="border-b border-gray-800 px-3 py-3">{student.prenom} {student.nom}</td>
                            <td className="border-b border-gray-800 px-3 py-3">{student.center_name}</td>
                            <td className="border-b border-gray-800 px-3 py-3">{student.platform_name || `P${student.platform_id}`}</td>
                            <td className="border-b border-gray-800 px-3 py-3 text-gray-400">{student.password_status}</td>
                            <td className="border-b border-gray-800 px-3 py-3">{student.is_active ? 'Actif' : 'Désactivé'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {(internalDashboard.students || []).length === 0 && (
                      <p className="p-4 text-sm text-gray-400">Aucun compte élève enregistré.</p>
                    )}
                  </div>
                </div>

                <div>
                  <h4 className="mb-3 text-sm font-semibold text-white">Dernières connexions</h4>
                  <div className="max-h-[360px] overflow-auto rounded-xl border border-gray-700">
                    <table className="w-full min-w-[720px] border-separate border-spacing-0 text-sm text-gray-200">
                      <thead className="sticky top-0 bg-gray-900">
                        <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
                          <th className="border-b border-gray-700 px-3 py-3">Élève</th>
                          <th className="border-b border-gray-700 px-3 py-3">Centre</th>
                          <th className="border-b border-gray-700 px-3 py-3">Plateforme</th>
                          <th className="border-b border-gray-700 px-3 py-3">Arrivée</th>
                          <th className="border-b border-gray-700 px-3 py-3">Départ</th>
                          <th className="border-b border-gray-700 px-3 py-3">Statut</th>
                        </tr>
                      </thead>
                      <tbody>
                        {internalDashboard.recent_logs?.map((log) => (
                          <tr key={log.id} className="transition hover:bg-gray-700/40">
                            <td className="border-b border-gray-800 px-3 py-3">{log.prenom} {log.nom}</td>
                            <td className="border-b border-gray-800 px-3 py-3">{log.center_name}</td>
                            <td className="border-b border-gray-800 px-3 py-3">{log.platform_name || `P${log.platform_id}`}</td>
                            <td className="border-b border-gray-800 px-3 py-3">{log.arrivee}</td>
                            <td className="border-b border-gray-800 px-3 py-3">{log.depart || '-'}</td>
                            <td className="border-b border-gray-800 px-3 py-3">{log.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {(internalDashboard.recent_logs || []).length === 0 && (
                      <p className="p-4 text-sm text-gray-400">Aucun log récent.</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </Sidebar>

        <Sidebar>
          <h3 className="text-base font-semibold text-white">Configuration de l&apos;heure du cours</h3>

          {successMessage && (
            <div className="mt-4 rounded-xl border border-emerald-400/40 bg-emerald-900/30 p-3 text-sm text-emerald-200">
              {successMessage}
            </div>
          )}

          {errorMessage && (
            <div className="mt-4 rounded-xl border border-rose-400/40 bg-rose-900/30 p-3 text-sm text-rose-200">
              {errorMessage}
            </div>
          )}

          <div className="mt-4 rounded-xl border border-gray-700 bg-gray-900/60 p-3 text-sm text-gray-200">
            <strong>Heure actuelle du cours:</strong> {heureDebut || 'Chargement...'}
          </div>

          <form className="mt-4 flex flex-wrap items-end gap-4" onSubmit={handleConfigSubmit}>
            <div>
              <label htmlFor="date_cours" className="mb-1 block text-sm font-medium text-gray-300">
                Date du cours
              </label>
              <input
                type="date"
                id="date_cours"
                name="date_cours"
                value={configDate}
                onChange={(e) => setConfigDate(e.target.value)}
                className="cursor-pointer rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-gray-300"
                required
              />
            </div>

            <div>
              <label htmlFor="heure_cours" className="mb-1 block text-sm font-medium text-gray-300">
                Heure du cours
              </label>
              <input
                type="time"
                id="heure_cours"
                name="heure_cours"
                value={configHeure}
                onChange={(e) => setConfigHeure(e.target.value)}
                className="cursor-pointer rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-gray-300"
                required
              />
            </div>

            <button
              type="submit"
              className="cursor-pointer rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-blue-700"
            >
              Mettre à jour
            </button>
          </form>
        </Sidebar>

        <Sidebar>
          <h3 className="text-base font-semibold text-white">Gestion des sessions</h3>
          <button
            id="force-logout-btn"
            className="mt-4 cursor-pointer rounded-lg border border-rose-500/40 bg-rose-900/40 px-4 py-2 text-sm font-medium text-rose-200 transition hover:-translate-y-0.5 hover:bg-rose-900/60"
            onClick={handleForceLogout}
          >
            Forcer la déconnexion de tous les utilisateurs
          </button>
        </Sidebar>

        <Sidebar>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-white">Comptes élèves</h3>
              <p className="mt-1 text-sm text-gray-400">
                Dès qu&apos;un compte existe sur cette plateforme, le login élève exige un identifiant et un mot de passe.
              </p>
            </div>
            <button
              type="button"
              onClick={fetchStudentAccounts}
              className="rounded-lg border border-gray-600 bg-gray-700 px-3 py-2 text-sm text-gray-100 transition hover:bg-gray-600"
            >
              Actualiser
            </button>
          </div>

          {studentMessage && (
            <div className="mt-4 rounded-xl border border-emerald-400/40 bg-emerald-900/30 p-3 text-sm text-emerald-200">
              {studentMessage}
            </div>
          )}
          {studentError && (
            <div className="mt-4 rounded-xl border border-rose-400/40 bg-rose-900/30 p-3 text-sm text-rose-200">
              {studentError}
            </div>
          )}

          <form className="mt-4 grid gap-3 md:grid-cols-5" onSubmit={handleCreateStudent}>
            <input
              name="email"
              value={studentForm.email}
              onChange={handleStudentFormChange}
              placeholder="Email"
              type="email"
              autoComplete="off"
              className="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-500"
              required
            />
            <input
              name="password"
              value={studentForm.password}
              onChange={handleStudentFormChange}
              placeholder="Mot de passe"
              type="password"
              autoComplete="new-password"
              className="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-500"
              required
              minLength={8}
            />
            <input
              name="nom"
              value={studentForm.nom}
              onChange={handleStudentFormChange}
              placeholder="Nom"
              className="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-500"
              required
            />
            <input
              name="prenom"
              value={studentForm.prenom}
              onChange={handleStudentFormChange}
              placeholder="Prénom"
              className="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-500"
              required
            />
            <button
              type="submit"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-blue-700"
            >
              Créer
            </button>
          </form>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[720px] border-separate border-spacing-0 text-sm text-gray-200">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
                  <th className="border-b border-gray-700 px-3 py-3">Email</th>
                  <th className="border-b border-gray-700 px-3 py-3">Nom</th>
                  <th className="border-b border-gray-700 px-3 py-3">Prénom</th>
                  <th className="border-b border-gray-700 px-3 py-3">Statut</th>
                  <th className="border-b border-gray-700 px-3 py-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {studentAccounts.map((account) => (
                  <tr key={account.id} className="transition hover:bg-gray-700/40">
                    <td className="border-b border-gray-800 px-3 py-3">{account.email || account.username}</td>
                    <td className="border-b border-gray-800 px-3 py-3">{account.nom}</td>
                    <td className="border-b border-gray-800 px-3 py-3">{account.prenom}</td>
                    <td className="border-b border-gray-800 px-3 py-3">
                      {account.is_active ? 'Actif' : 'Désactivé'}
                    </td>
                    <td className="border-b border-gray-800 px-3 py-3">
                      <button
                        type="button"
                        onClick={() => handleToggleStudent(account)}
                        className="rounded-lg border border-gray-600 bg-gray-700 px-3 py-2 text-xs text-gray-100 transition hover:bg-gray-600"
                      >
                        {account.is_active ? 'Désactiver' : 'Réactiver'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {studentAccounts.length === 0 && (
              <p className="mt-3 text-sm text-gray-400">Aucun compte élève créé pour cette plateforme.</p>
            )}
          </div>
        </Sidebar>

        <Sidebar>
          <h3 className="text-base font-semibold text-white">Mise à jour du cours (PDF)</h3>

          <div
            onDragOver={(e) => { e.preventDefault(); setPdfDragOver(true) }}
            onDragLeave={() => setPdfDragOver(false)}
            onDrop={handlePdfDrop}
            onClick={() => document.getElementById('pdf-input').click()}
            className={`mt-4 cursor-pointer rounded-lg border border-dashed p-8 text-center transition ${
              pdfDragOver ? 'border-gray-500 bg-gray-700/60' : 'border-gray-600 bg-gray-900/50 hover:bg-gray-700/40'
            }`}
          >
            <input
              type="file"
              id="pdf-input"
              accept=".pdf"
              className="hidden"
              onChange={handlePdfSelect}
            />
            <p className="text-sm font-medium text-gray-200">
              {pdfFile ? pdfFile.name : 'Glissez un PDF ici ou cliquez pour sélectionner'}
            </p>
          </div>

          {pdfFile && (
            <div className="mt-4">
              <button
                onClick={handlePdfUpload}
                disabled={pdfUploading || indexerPolling}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-500"
              >
                {pdfUploading ? 'Upload en cours...' : 'Mettre à jour le cours'}
              </button>
            </div>
          )}

          {pdfMessage && (
            <div className={`mt-4 rounded-lg border p-3 text-sm ${
              pdfMessageType === 'success'
                ? 'border-emerald-400/40 bg-emerald-900/30 text-emerald-200'
                : pdfMessageType === 'error'
                  ? 'border-rose-400/40 bg-rose-900/30 text-rose-200'
                  : 'border-blue-400/40 bg-blue-900/30 text-blue-200'
            }`}>
              <p>{pdfMessage}</p>
              {indexerPolling && (
                <div className="mt-2 flex items-center gap-2 text-xs text-gray-300">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-500 border-t-gray-100" />
                  <span>Veuillez patienter...</span>
                </div>
              )}
            </div>
          )}
        </Sidebar>

        <Sidebar>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-700 pb-4">
            <p className="text-sm text-gray-300">
              <strong>Temps total cumulé:</strong> {tempsTotal || '0 h 0 min 0 sec'}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                id="prenom"
                name="prenom"
                placeholder="Prénom à rechercher"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-500"
              />
              <button
                type="submit"
                className="rounded-lg border border-gray-600 bg-gray-700 px-3 py-2 text-sm text-gray-100 transition hover:bg-gray-600"
                onClick={(event) => event.preventDefault()}
              >
                Rechercher
              </button>
              <a
                href={`/admin?p=${currentPlatformId}`}
                className="rounded-lg border border-gray-600 bg-gray-700 px-3 py-2 text-sm text-gray-100 transition hover:bg-gray-600"
              >
                Réinitialiser
              </a>
              <button
                onClick={handleExportExcel}
                className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-blue-700"
              >
                Exporter en Excel
              </button>
            </div>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[760px] border-separate border-spacing-0 text-sm text-gray-200">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
                  <th className="border-b border-gray-700 px-3 py-3">ID</th>
                  <th className="border-b border-gray-700 px-3 py-3">Nom</th>
                  <th className="border-b border-gray-700 px-3 py-3">Prénom</th>
                  <th className="border-b border-gray-700 px-3 py-3">Arrivée</th>
                  <th className="border-b border-gray-700 px-3 py-3">Départ</th>
                  <th className="border-b border-gray-700 px-3 py-3">Durée</th>
                </tr>
              </thead>
              <tbody>
                {filteredLogs.map((log) => (
                  <tr key={log.id} className="transition hover:bg-gray-700/40">
                    <td className="border-b border-gray-800 px-3 py-3">{log.id}</td>
                    <td className="border-b border-gray-800 px-3 py-3">{log.nom}</td>
                    <td className="border-b border-gray-800 px-3 py-3">{log.prenom}</td>
                    <td className="border-b border-gray-800 px-3 py-3">{log.arrivee}</td>
                    <td className="border-b border-gray-800 px-3 py-3">{log.depart || 'Encore connecté'}</td>
                    <td className="border-b border-gray-800 px-3 py-3">{log.duree}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {loading && (
            <p className="mt-4 text-sm text-gray-400">Chargement...</p>
          )}
        </Sidebar>

      </div>
    </div>
  )
}
