import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiFetch, getPlatformId, getStudentLoginPath, setPlatformId } from '../api'
import './Attente.css'

const COUNTDOWN_UNITS = [
  { key: 'jours', label: 'Jours' },
  { key: 'heures', label: 'Heures' },
  { key: 'minutes', label: 'Minutes' },
  { key: 'secondes', label: 'Secondes' },
]

export default function Attente() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const pParam = searchParams.get('p')
  const [timeLeft, setTimeLeft] = useState(null)
  const hasCountdownStarted = timeLeft !== null

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

  useEffect(() => {
    if (pParam) setPlatformId(pParam)

    const fetchStatus = async () => {
      try {
        const res = await apiFetch('/api/video/status')
        const data = await res.json()
        if (!res.ok || !data.authenticated) {
          navigate(getStudentLoginPath(), { replace: true })
          return
        }
        if (data.status === 'waiting' && data.temps_restant > 0) {
          setTimeLeft(Math.ceil(data.temps_restant))
        } else if (data.status === 'playing' || data.status === 'finished') {
          const platformId = pParam || getPlatformId()
          navigate(platformId && platformId !== '1' ? `/video?p=${platformId}` : '/video', { replace: true })
        } else {
          setTimeLeft(0)
        }
      } catch {
        // En cas d'erreur réseau, on garde la valeur actuelle.
      }
    }

    fetchStatus()
    const syncInterval = setInterval(fetchStatus, 30000)
    return () => clearInterval(syncInterval)
  }, [navigate, pParam])

  useEffect(() => {
    if (!hasCountdownStarted) return undefined
    const interval = setInterval(() => {
      setTimeLeft((prev) => (prev > 0 ? prev - 1 : 0))
    }, 1000)
    return () => clearInterval(interval)
  }, [hasCountdownStarted])

  return (
    <main className="waiting-screen">
      <aside className="waiting-screen__identity" aria-label="Le Socrate">
        <div className="waiting-brand">
          <span className="waiting-brand__mark" aria-hidden="true">S</span>
          <span>SOCRATE</span>
        </div>

        <div className="waiting-screen__intro">
          <p className="waiting-screen__kicker">Classe virtuelle</p>
          <h1>Votre cours commence bientôt.</h1>
          <p>Cette page s’ouvrira automatiquement dès que la séance sera disponible.</p>
        </div>

        <p className="waiting-screen__footnote">Formation certifiante · Session sécurisée</p>
      </aside>

      <section className="waiting-screen__content" aria-labelledby="waiting-countdown-title">
        <div className="waiting-panel">
          <header className="waiting-panel__header">
            <h2 id="waiting-countdown-title">
              {timeLeft === null ? 'Vérification de la séance' : 'Début de la formation dans'}
            </h2>
          </header>

          <div
            className={`waiting-countdown${timeLeft === null ? ' waiting-countdown--loading' : ''}`}
            role="timer"
            aria-live="polite"
            aria-atomic="true"
            aria-label={timeLeft === null ? 'Chargement du temps restant' : `${countdown.jours} jours, ${countdown.heures} heures, ${countdown.minutes} minutes et ${countdown.secondes} secondes`}
          >
            {COUNTDOWN_UNITS.map(({ key, label }) => (
              <div className="waiting-countdown__unit" key={key}>
                <span id={key} className="waiting-countdown__value">{countdown[key]}</span>
                <span className="waiting-countdown__label">{label}</span>
              </div>
            ))}
          </div>

          <div className="waiting-actions">
            <button className="waiting-button waiting-button--primary" type="button" onClick={() => window.location.reload()}>
              Actualiser
            </button>
            <button className="waiting-button waiting-button--secondary" type="button" onClick={() => navigate('/')}>
              Accueil
            </button>
          </div>
        </div>
      </section>
    </main>
  )
}
