import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import { apiFetch, apiUrl, getStudentLoginPath, setPlatformId, setPlatformName, setStudentLoginPath } from '../api'
import './Auth.css'

export default function Index({ preloadCourseRoutes, preloadAttenteRoute, preloadVideoRoute }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const invitationToken = searchParams.get('invite') || ''
  const [submitting, setSubmitting] = useState(false)
  const [formMessage, setFormMessage] = useState(null)
  const [showPassword, setShowPassword] = useState(false)
  const invitationStartedRef = useRef(false)

  useEffect(() => {
    const pParam = searchParams.get('p')
    if (pParam) {
      setPlatformId(pParam)
      setStudentLoginPath(`/?p=${pParam}`)
      fetch(apiUrl(`/api/platform-info?id=${pParam}`))
        .then(r => r.json())
        .then(data => {
          if (data.name) {
            setPlatformName(data.name)
          }
        })
        .catch(() => {})
    } else if (location.pathname === '/') {
      setStudentLoginPath('/')
    }

  }, [location.pathname, searchParams])

  useEffect(() => {
    const preload = () => {
      preloadCourseRoutes?.().catch(() => {})
    }
    if ('requestIdleCallback' in window) {
      const idleId = window.requestIdleCallback(preload, { timeout: 1500 })
      return () => window.cancelIdleCallback(idleId)
    }
    const timeoutId = window.setTimeout(preload, 800)
    return () => window.clearTimeout(timeoutId)
  }, [preloadCourseRoutes])

  const openStudentSession = async (credentials) => {
    if (submitting) return
    setSubmitting(true)
    setFormMessage(null)

    try {
      const response = await fetch(apiUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          ...credentials,
          platform_id: parseInt(localStorage.getItem('platform_id') || '1'),
        }),
      })

      const data = await response.json()

      if (data.success) {
        if (data.token) localStorage.setItem('auth_token', data.token)
        const pId = localStorage.getItem('platform_id')
        const withPlatform = (path) => {
          if (getStudentLoginPath().startsWith('/classe/')) return path
          return pId && pId !== '1' ? `${path}?p=${pId}` : path
        }

        try {
          const statusResponse = await apiFetch('/api/video/status')
          const statusData = await statusResponse.json().catch(() => ({}))
          if (statusData.status === 'waiting') {
            await preloadAttenteRoute?.().catch(() => {})
            navigate(withPlatform('/attente'), { replace: true })
            return
          }
          if (statusData.status === 'playing' || statusData.status === 'finished') {
            await preloadVideoRoute?.().catch(() => {})
            navigate(withPlatform('/video'), { replace: true })
            return
          }
        } catch (statusError) {
          console.warn('Statut cours indisponible après login:', statusError)
        }

        await preloadVideoRoute?.().catch(() => {})
        navigate(withPlatform('/video'), { replace: true })
      } else {
        setFormMessage({ type: 'error', text: data.error || 'Erreur lors de la connexion.' })
      }
    } catch (error) {
      console.error('Erreur connexion:', error)
      setFormMessage({ type: 'error', text: 'Impossible de se connecter au serveur.' })
    } finally {
      setSubmitting(false)
    }
  }

  const handleFormSubmit = async (event) => {
    event.preventDefault()
    const formData = new FormData(event.target)
    const personalCode = String(formData.get('personal_code') || '').trim()
    if (!personalCode) {
      setFormMessage({ type: 'error', text: 'Votre code personnel est requis.' })
      return
    }
    await openStudentSession({ personal_code: personalCode })
  }

  useEffect(() => {
    if (!invitationToken || invitationStartedRef.current) return
    invitationStartedRef.current = true
    openStudentSession({ invitation_token: invitationToken })
  }, [invitationToken])

  return (
    <main className="cadrenza-auth">
      <a className="auth-skip-link" href="#auth-main">Aller au formulaire</a>
      <div className="auth-layout">
        <aside className="auth-visual auth-visual--learner-login" aria-label="Bureau d’étude">
          <img
            className="auth-study-image"
            src="/student-learning-login-unsplash-yen-vu.jpg"
            alt="Un bureau d’étude avec des livres, des cahiers et un ordinateur"
            draggable={false}
          />
        </aside>

        <section className="auth-panel" id="auth-main">
          <div className="auth-panel__inner">
            <header className="auth-heading">
              <h2>Rejoindre le cours</h2>
            </header>

            {formMessage && (
              <div
                className={`auth-alert ${formMessage.type === 'success' ? 'auth-alert--success' : 'auth-alert--error'}`}
                role={formMessage.type === 'error' ? 'alert' : 'status'}
                aria-live={formMessage.type === 'error' ? 'assertive' : 'polite'}
              >
                {formMessage.text}
              </div>
            )}

            {invitationToken ? (
              <div className="auth-assurance" role="status" aria-live="polite">
                {submitting ? 'Identification automatique en cours…' : 'Invitation personnelle vérifiée'}
              </div>
            ) : (
              <form className="auth-form" onSubmit={handleFormSubmit}>
                <div className="auth-field">
                  <label htmlFor="personal_code">Code personnel</label>
                  <div className="auth-password-wrap">
                    <input
                      id="personal_code"
                      name="personal_code"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="one-time-code"
                      placeholder="Code personnel reçu par e-mail"
                      required
                    />
                    <button
                      type="button"
                      className="auth-password-toggle"
                      onClick={() => setShowPassword((visible) => !visible)}
                      aria-label={showPassword ? 'Masquer le code personnel' : 'Afficher le code personnel'}
                      aria-pressed={showPassword}
                    >
                      {showPassword ? 'Masquer' : 'Afficher'}
                    </button>
                  </div>
                </div>

                <button type="submit" disabled={submitting} className="auth-submit">
                  {submitting ? 'Identification…' : 'Rejoindre le cours'}
                </button>
              </form>
            )}

            <p className="auth-assurance">
              {invitationToken ? 'Aucune information personnelle à saisir' : 'Utilisez le code personnel contenu dans votre e-mail'}
            </p>
          </div>
        </section>
      </div>
    </main>
  )
}
