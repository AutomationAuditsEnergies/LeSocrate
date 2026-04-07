import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../api'

export default function Attente() {
  const navigate = useNavigate()
  const [timeLeft, setTimeLeft] = useState(null)
  const [heureDebut, setHeureDebut] = useState(null)

  const countdown = useMemo(() => {
    const t = timeLeft ?? 0
    const jours = Math.floor(t / (24 * 3600))
    const heures = Math.floor((t % (24 * 3600)) / 3600)
    const minutes = Math.floor((t % 3600) / 60)
    const secondes = t % 60
    return {
      jours: String(jours).padStart(2, '0'),
      heures: String(heures).padStart(2, '0'),
      minutes: String(minutes).padStart(2, '0'),
      secondes: String(secondes).padStart(2, '0'),
    }
  }, [timeLeft])

  // Récupérer le temps restant réel depuis le backend
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await apiFetch('/api/cours-status')
        const data = await res.json()
        if (data.status === 'waiting' && data.temps_restant > 0) {
          setTimeLeft(Math.ceil(data.temps_restant))
          if (data.heure_debut) setHeureDebut(data.heure_debut)
        } else if (data.status === 'playing') {
          window.location.assign('/video')
          return
        } else {
          setTimeLeft(0)
        }
      } catch {
        // En cas d'erreur réseau, on garde la valeur actuelle
      }
    }

    fetchStatus()
    // Re-sync avec le backend toutes les 30s pour éviter la dérive
    const syncInterval = setInterval(fetchStatus, 30000)
    return () => clearInterval(syncInterval)
  }, [])

  // Décrémenter localement chaque seconde
  useEffect(() => {
    if (timeLeft === null) return
    const interval = setInterval(() => {
      setTimeLeft((prev) => (prev > 0 ? prev - 1 : 0))
    }, 1000)
    return () => clearInterval(interval)
  }, [timeLeft !== null])

  return (
    <div
      className="flex flex-col h-full w-full bg-cover bg-center relative overflow-hidden min-h-screen"
      style={{ backgroundImage: 'url("/static/images/prof-avatar.jpg")' }}
    >
      <div className="absolute inset-0 bg-black/60 z-0" />

      <div className="absolute inset-0 z-1">
        <div className="floating-particle absolute top-20 left-20 w-4 h-4 bg-blue-400/30 rounded-full" />
        <div
          className="floating-particle absolute top-40 right-32 w-6 h-6 bg-purple-400/30 rounded-full"
          style={{ animationDelay: '-2s' }}
        />
        <div
          className="floating-particle absolute bottom-32 left-40 w-3 h-3 bg-pink-400/30 rounded-full"
          style={{ animationDelay: '-4s' }}
        />
        <div
          className="floating-particle absolute bottom-20 right-20 w-5 h-5 bg-yellow-400/30 rounded-full"
          style={{ animationDelay: '-1s' }}
        />
        <div
          className="floating-particle absolute top-1/2 left-10 w-4 h-4 bg-green-400/30 rounded-full"
          style={{ animationDelay: '-3s' }}
        />
        <div
          className="floating-particle absolute top-1/3 right-10 w-3 h-3 bg-red-400/30 rounded-full"
          style={{ animationDelay: '-5s' }}
        />
      </div>

      <div className="flex-1 flex flex-col items-center justify-center relative z-10 px-8 py-8">
        <div className="countdown-glow bg-gradient-to-r from-blue-600/20 to-purple-600/20 backdrop-blur-lg border border-white/30 rounded-3xl p-8 mb-8">
          <h2 className="text-2xl font-semibold text-white text-center mb-6">
            {timeLeft === null ? 'Chargement...' : 'Début de la formation dans :'}
          </h2>

          <div className="grid grid-cols-4 gap-4 text-center">
            <div className="bg-white/10 rounded-xl p-4">
              <div id="jours" className="text-3xl font-bold text-blue-400">
                {countdown.jours}
              </div>
              <div className="text-sm text-gray-300">Jours</div>
            </div>
            <div className="bg-white/10 rounded-xl p-4">
              <div id="heures" className="text-3xl font-bold text-purple-400">
                {countdown.heures}
              </div>
              <div className="text-sm text-gray-300">Heures</div>
            </div>
            <div className="bg-white/10 rounded-xl p-4">
              <div id="minutes" className="text-3xl font-bold text-pink-400">
                {countdown.minutes}
              </div>
              <div className="text-sm text-gray-300">Minutes</div>
            </div>
            <div className="bg-white/10 rounded-xl p-4">
              <div id="secondes" className="text-3xl font-bold text-yellow-400">
                {countdown.secondes}
              </div>
              <div className="text-sm text-gray-300">Secondes</div>
            </div>
          </div>
        </div>

        <div className="flex gap-4">
          <button
            onClick={() => window.location.reload()}
            className="group relative px-7 py-3 rounded-xl font-semibold text-white/90 overflow-hidden transition-all duration-300 hover:scale-105 hover:text-white hover:shadow-[0_0_25px_rgba(255,255,255,0.15)]"
            style={{
              background: 'rgba(255,255,255,0.08)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(255,255,255,0.2)',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.1)',
            }}
          >
            <span className="relative z-10 flex items-center gap-2">
              <svg className="w-4 h-4 transition-transform duration-300 group-hover:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Actualiser
            </span>
          </button>

          <button
            onClick={() => navigate('/')}
            className="group relative px-7 py-3 rounded-xl font-semibold text-white/90 overflow-hidden transition-all duration-300 hover:scale-105 hover:text-white hover:shadow-[0_0_25px_rgba(255,255,255,0.15)]"
            style={{
              background: 'rgba(255,255,255,0.08)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(255,255,255,0.2)',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.1)',
            }}
          >
            <span className="relative z-10 flex items-center gap-2">
              <svg className="w-4 h-4 transition-transform duration-300 group-hover:-translate-x-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0a1 1 0 01-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1" />
              </svg>
              Accueil
            </span>
          </button>
        </div>
      </div>
    </div>
  )
}
