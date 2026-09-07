import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { apiFetch, apiUrl, getPlatformId, setPlatformId, setPlatformName } from '../api'

export default function DebugCours() {
  const [debugInfo, setDebugInfo] = useState(null)
  const [playlist, setPlaylist] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [searchParams] = useSearchParams()
  const pParam = searchParams.get('p')
  const platformId = pParam || getPlatformId()

  useEffect(() => {
    if (!pParam) return
    setPlatformId(pParam)
    fetch(apiUrl(`/api/platform-info?id=${pParam}`))
      .then(r => r.json())
      .then(data => { if (data.name) setPlatformName(data.name) })
      .catch(() => {})
  }, [pParam])

  // Fonction pour simuler un saut dans le temps
  const handleTimeJump = async (seconds) => {
    try {
      if (!debugInfo || !debugInfo.heure_debut_cours) {
        console.error('debugInfo non disponible')
        return
      }

      // Calculer la nouvelle heure de début du cours
      // Pour avancer dans le temps, on RECULE l'heure de début
      // Pour reculer dans le temps, on AVANCE l'heure de début
      const heureDebut = new Date(debugInfo.heure_debut_cours)
      const nouvelleHeureDebut = new Date(heureDebut.getTime() - seconds * 1000)

      // Formater la date pour l'API (format: YYYY-MM-DD HH:MM:SS) en heure locale
      const year = nouvelleHeureDebut.getFullYear()
      const month = String(nouvelleHeureDebut.getMonth() + 1).padStart(2, '0')
      const day = String(nouvelleHeureDebut.getDate()).padStart(2, '0')
      const hours = String(nouvelleHeureDebut.getHours()).padStart(2, '0')
      const minutes = String(nouvelleHeureDebut.getMinutes()).padStart(2, '0')
      const secs = String(nouvelleHeureDebut.getSeconds()).padStart(2, '0')

      const dateStr = `${year}-${month}-${day}`
      const timeStr = `${hours}:${minutes}:${secs}`

      const response = await apiFetch('/api/admin/config_cours', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          date_cours: dateStr,
          heure_cours: timeStr,
          platform_id: Number(platformId),
        }),
      })

      if (response.ok) {
        // Recharger immédiatement les infos
        fetchDebugInfo()
      }
    } catch (err) {
      console.error('Erreur saut temporel:', err)
    }
  }

  // Fonction pour simuler le début du cours (mettre l'heure de début = maintenant)
  const handleSimulateStart = async () => {
    try {
      const now = new Date()
      // Utiliser toLocaleString pour obtenir l'heure locale française
      const year = now.getFullYear()
      const month = String(now.getMonth() + 1).padStart(2, '0')
      const day = String(now.getDate()).padStart(2, '0')
      const hours = String(now.getHours()).padStart(2, '0')
      const minutes = String(now.getMinutes()).padStart(2, '0')
      const secs = String(now.getSeconds()).padStart(2, '0')

      const dateStr = `${year}-${month}-${day}`
      const timeStr = `${hours}:${minutes}:${secs}`

      const response = await apiFetch('/api/admin/config_cours', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          date_cours: dateStr,
          heure_cours: timeStr,
          platform_id: Number(platformId),
        }),
      })

      if (response.ok) {
        fetchDebugInfo()
      }
    } catch (err) {
      console.error('Erreur simulation début:', err)
    }
  }

  // Fonction pour réinitialiser la simulation (remettre l'heure de début par défaut)
  const handleResetSimulation = async () => {
    try {
      // Remettre l'heure de début à l'heure par défaut (28 mai 2025 16:35)
      const response = await apiFetch('/api/admin/config_cours', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          date_cours: '2025-05-28',
          heure_cours: '16:35',
          platform_id: Number(platformId),
        }),
      })

      if (response.ok) {
        fetchDebugInfo()
      }
    } catch (err) {
      console.error('Erreur reset simulation:', err)
    }
  }

  useEffect(() => {
    fetchDebugInfo()
    // Actualiser toutes les 5 secondes
    const interval = setInterval(fetchDebugInfo, 5000)
    return () => clearInterval(interval)
  }, [platformId])

  const fetchDebugInfo = async () => {
    try {
      const response = await apiFetch(`/api/debug/cours-info?p=${encodeURIComponent(platformId)}`)

      if (response.ok) {
        const data = await response.json()
        if (data.success) {
          setDebugInfo(data.debug_info)
          // Charger aussi la playlist
          fetchPlaylist()
        }
      } else {
        setError('Accès refusé - Connectez-vous en tant qu\'admin')
      }
    } catch (err) {
      console.error('Erreur chargement debug:', err)
      setError('Erreur de connexion au serveur')
    } finally {
      setLoading(false)
    }
  }

  const fetchPlaylist = async () => {
    try {
      const response = await apiFetch(`/api/debug/playlist?p=${encodeURIComponent(platformId)}`)
      if (response.ok) {
        const data = await response.json()
        if (data.success) {
          setPlaylist(data.playlist)
        }
      }
    } catch (err) {
      console.error('Erreur chargement playlist:', err)
    }
  }

  if (loading) {
    return (
      <div className="bg-gray-900 text-white p-8 min-h-screen flex items-center justify-center">
        <p className="text-xl">Chargement des informations de debug...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-gray-900 text-white p-8 min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-500 text-xl mb-4">{error}</p>
          <a href={`/login-admin?p=${platformId}`} className="bg-blue-600 hover:bg-blue-700 px-6 py-3 rounded-lg font-medium transition">
            Se connecter
          </a>
        </div>
      </div>
    )
  }

  if (!debugInfo) {
    return null
  }

  const status = debugInfo.status === 'En cours' ? 'playing' : debugInfo.status === 'En attente' ? 'waiting' : 'finished'

  return (
    <div className="bg-gray-900 text-white p-8 min-h-screen">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold mb-6">Debug - État du cours P{platformId}</h1>
        <p className="text-sm text-gray-400 mb-6">Actualisation automatique toutes les 5 secondes</p>

        {/* Table de mixage temporelle */}
        <div className="bg-gradient-to-br from-gray-800 to-gray-900 p-6 rounded-lg mb-6 border-2 border-yellow-600/50">
          <h2 className="text-xl font-semibold mb-4 text-yellow-400">Table de mixage temporelle</h2>

          <div className="space-y-4">
            {/* Bouton simuler début */}
            <div className="flex justify-center">
              <button
                type="button"
                onClick={handleSimulateStart}
                className="bg-green-600 hover:bg-green-700 px-6 py-3 rounded-lg font-medium transition shadow-lg"
              >
                Simuler le début du cours
              </button>
            </div>

            {/* Contrôles de navigation temporelle */}
            <div className="bg-gray-800/50 p-4 rounded-lg border border-green-600/50">
              <h3 className="text-lg font-medium mb-3 text-green-400">Avancer/Reculer dans le temps</h3>

              {/* Grands sauts */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2">
                <button
                  type="button"
                  onClick={() => handleTimeJump(-3600)}
                  className="bg-red-700 hover:bg-red-800 px-3 py-2 rounded text-sm transition font-bold"
                >
                  -1h
                </button>
                <button
                  type="button"
                  onClick={() => handleTimeJump(-1800)}
                  className="bg-red-600 hover:bg-red-700 px-3 py-2 rounded text-sm transition"
                >
                  -30min
                </button>
                <button
                  type="button"
                  onClick={() => handleTimeJump(1800)}
                  className="bg-blue-600 hover:bg-blue-700 px-3 py-2 rounded text-sm transition"
                >
                  +30min
                </button>
                <button
                  type="button"
                  onClick={() => handleTimeJump(3600)}
                  className="bg-blue-700 hover:bg-blue-800 px-3 py-2 rounded text-sm transition font-bold"
                >
                  +1h
                </button>
              </div>

              {/* Sauts moyens */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2">
                <button
                  type="button"
                  onClick={() => handleTimeJump(-900)}
                  className="bg-red-600 hover:bg-red-700 px-3 py-2 rounded text-sm transition"
                >
                  -15min
                </button>
                <button
                  type="button"
                  onClick={() => handleTimeJump(-300)}
                  className="bg-red-600 hover:bg-red-700 px-3 py-2 rounded text-sm transition"
                >
                  -5min
                </button>
                <button
                  type="button"
                  onClick={() => handleTimeJump(300)}
                  className="bg-blue-600 hover:bg-blue-700 px-3 py-2 rounded text-sm transition"
                >
                  +5min
                </button>
                <button
                  type="button"
                  onClick={() => handleTimeJump(900)}
                  className="bg-blue-600 hover:bg-blue-700 px-3 py-2 rounded text-sm transition"
                >
                  +15min
                </button>
              </div>

              {/* Petits sauts */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
                <button
                  type="button"
                  onClick={() => handleTimeJump(-60)}
                  className="bg-red-500 hover:bg-red-600 px-3 py-2 rounded text-sm transition"
                >
                  -1min
                </button>
                <button
                  type="button"
                  onClick={() => handleTimeJump(-10)}
                  className="bg-red-500 hover:bg-red-600 px-3 py-2 rounded text-sm transition"
                >
                  -10s
                </button>
                <button
                  type="button"
                  onClick={() => handleTimeJump(10)}
                  className="bg-blue-500 hover:bg-blue-600 px-3 py-2 rounded text-sm transition"
                >
                  +10s
                </button>
                <button
                  type="button"
                  onClick={() => handleTimeJump(60)}
                  className="bg-blue-500 hover:bg-blue-600 px-3 py-2 rounded text-sm transition"
                >
                  +1min
                </button>
              </div>

              {/* Info et reset */}
              <div className="text-xs text-green-300 bg-green-900/30 p-3 rounded flex justify-between items-center">
                <div>
                  <strong>Temps actuel :</strong> {debugInfo.temps_ecoule_secondes}s ({debugInfo.temps_ecoule_minutes} min)
                  <br />
                  <strong>Raccourcis :</strong> 10s • 1min • 5min • 15min • 30min • 1h
                </div>
                <button
                  type="button"
                  onClick={handleResetSimulation}
                  className="bg-yellow-600 hover:bg-yellow-700 px-4 py-2 rounded text-sm font-medium transition"
                >
                  Reset (heure réelle)
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-gray-800 p-6 rounded-lg">
            <h2 className="text-xl font-semibold mb-4 text-blue-400">Informations temporelles</h2>
            <div className="space-y-2">
              <p>
                <span className="text-gray-400">Heure de début :</span>{' '}
                <span className="font-mono">{debugInfo.heure_debut_cours}</span>
              </p>
              <p>
                <span className="text-gray-400">Heure actuelle :</span>{' '}
                <span className="font-mono">{debugInfo.heure_actuelle}</span>
              </p>
              {debugInfo.simulation_active && (
                <p className="bg-yellow-900 p-2 rounded text-yellow-200">
                  Mode simulation activé
                </p>
              )}
              <p>
                <span className="text-gray-400">Temps restant avant début :</span>{' '}
                {debugInfo.temps_avant_debut || 0}s
              </p>
              <p>
                <span className="text-gray-400">Offset actuel :</span>{' '}
                {debugInfo.temps_ecoule_secondes}s ({debugInfo.temps_ecoule_minutes} min)
              </p>
            </div>
          </div>

          <div className="bg-gray-800 p-6 rounded-lg">
            <h2 className="text-xl font-semibold mb-4 text-green-400">Audio actuel</h2>
            {status === 'playing' ? (
              <div className="space-y-2">
                <p>
                  <span className="text-gray-400">ID :</span> {debugInfo.audio_actuel_id}
                </p>
                <p>
                  <span className="text-gray-400">Fichier :</span>{' '}
                  <span className="text-sm font-mono break-all">
                    {playlist.find((p) => p.id === debugInfo.audio_actuel_id)?.filename || 'N/A'}
                  </span>
                </p>
                <p>
                  <span className="text-gray-400">Titre :</span> {debugInfo.audio_actuel_titre}
                </p>
                <p>
                  <span className="text-gray-400">Position :</span> {debugInfo.offset_dans_audio}s /{' '}
                  {debugInfo.duree_audio_actuel}s
                </p>
                <div className="w-full bg-gray-700 rounded-full h-2 mt-3">
                  <div
                    className="bg-green-500 h-2 rounded-full"
                    style={{ width: `${(debugInfo.offset_dans_audio / debugInfo.duree_audio_actuel) * 100}%` }}
                  />
                </div>
              </div>
            ) : status === 'waiting' ? (
              <p className="text-yellow-400">En attente du début du cours...</p>
            ) : (
              <p className="text-red-400">Cours terminé</p>
            )}
          </div>
        </div>

        <div className="mt-6 bg-gray-800 p-6 rounded-lg">
          <h2 className="text-xl font-semibold mb-4 text-purple-400">Playlist</h2>
          <p className="text-gray-400 mb-4">
            {debugInfo.nombre_audios} audios - Durée totale : {debugInfo.duree_totale_cours_secondes}s (
            {debugInfo.duree_totale_cours_minutes} min)
          </p>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {playlist.map((item) => (
              <div
                key={item.id}
                className={`${
                  debugInfo.audio_actuel_id === item.id ? 'bg-green-900 border-2 border-green-500' : 'bg-gray-700'
                } p-3 rounded text-sm`}
              >
                <p>
                  <strong>
                    #{item.id} - {item.title}
                  </strong>
                </p>
                <p className="text-gray-400 text-xs font-mono break-all">
                  {item.filename.split('/').pop()} ({item.duration}s)
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-6 bg-gray-800 p-6 rounded-lg">
          <h2 className="text-xl font-semibold mb-4 text-red-400">Statut global</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="text-center">
              <p
                className={`text-2xl font-bold ${
                  status === 'waiting'
                    ? 'text-yellow-400'
                    : status === 'playing'
                      ? 'text-green-400'
                      : 'text-red-400'
                }`}
              >
                {status.toUpperCase()}
              </p>
              <p className="text-sm text-gray-400">Statut</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-blue-400">{debugInfo.duree_totale_cours_secondes}s</p>
              <p className="text-sm text-gray-400">Durée totale</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-purple-400">{debugInfo.temps_ecoule_secondes}s</p>
              <p className="text-sm text-gray-400">Temps écoulé</p>
            </div>
          </div>
        </div>

        <div className="mt-8 text-center space-x-4">
          <a href={`/admin?p=${platformId}`} className="bg-blue-600 hover:bg-blue-700 px-6 py-3 rounded-lg font-medium transition inline-block">
            Retour à l&apos;Admin
          </a>
          <a
            href={`/video?p=${platformId}`}
            className="bg-purple-600 hover:bg-purple-700 px-6 py-3 rounded-lg font-medium transition inline-block"
          >
            Aller au cours
          </a>
        </div>
      </div>
    </div>
  )
}
