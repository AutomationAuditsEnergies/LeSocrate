import { useEffect, useMemo, useState } from 'react'
import Sidebar from '../components/Sidebar.jsx'

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

  // État pour l'upload PDF
  const [pdfFile, setPdfFile] = useState(null)
  const [pdfDragOver, setPdfDragOver] = useState(false)
  const [pdfUploading, setPdfUploading] = useState(false)
  const [pdfMessage, setPdfMessage] = useState('')
  const [pdfMessageType, setPdfMessageType] = useState('') // 'success', 'error', 'info'
  const [indexerPolling, setIndexerPolling] = useState(false)


  // Charger les logs depuis l'API
  useEffect(() => {
    fetchLogs()
  }, [search])

  // Vérifier le statut de l'indexer au chargement (persistance après refresh)
  useEffect(() => {
    const checkIndexerOnLoad = async () => {
      try {
        const resp = await fetch('/api/admin/indexer-status', { credentials: 'include' })
        const data = await resp.json()
        if (data.success && data.status === 'inProgress') {
          // Indexation en cours détectée → lancer le polling
          setIndexerPolling(true)
          setPdfMessage('Indexation en cours...')
          setPdfMessageType('info')

          const interval = setInterval(async () => {
            try {
              const r = await fetch('/api/admin/indexer-status', { credentials: 'include' })
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

  const fetchLogs = async () => {
    try {
      setLoading(true)
      const url = search
        ? `/api/admin/logs?prenom=${encodeURIComponent(search)}`
        : '/api/admin/logs'

      const response = await fetch(url, {
        credentials: 'include',
      })

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
  }

  const filteredLogs = useMemo(
    () => logs,
    [logs]
  )

  const handleConfigSubmit = async (e) => {
    e.preventDefault()
    setSuccessMessage('')
    setErrorMessage('')

    try {
      const response = await fetch('/api/admin/config_cours', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
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
      const response = await fetch('/api/admin/force-logout-finished-users', {
        method: 'POST',
        credentials: 'include',
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
        const resp = await fetch('/api/admin/indexer-status', { credentials: 'include' })
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

      const resp = await fetch('/api/admin/upload-pdf', {
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
              href="/debug"
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
                href="/admin"
                className="rounded-lg border border-gray-600 bg-gray-700 px-3 py-2 text-sm text-gray-100 transition hover:bg-gray-600"
              >
                Réinitialiser
              </a>
              <a
                href="/export_excel"
                className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium !text-white shadow-sm visited:!text-white hover:!text-white focus:!text-white active:!text-white transition hover:-translate-y-0.5 hover:bg-blue-700"
              >
                Exporter en Excel
              </a>
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
