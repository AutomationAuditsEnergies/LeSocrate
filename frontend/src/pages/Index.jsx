import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useState, useEffect } from 'react'
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

  const handleFormSubmit = async (event) => {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setFormMessage(null)

    const formData = new FormData(event.target)
    const password = String(formData.get('password') || '')
    const nom = String(formData.get('nom') || '').trim()
    const prenom = String(formData.get('prenom') || '').trim()

    try {
      if (!nom || !prenom || (!invitationToken && !password)) {
        setFormMessage({
          type: 'error',
          text: invitationToken
            ? 'Votre nom et votre prénom sont requis.'
            : 'Nom, prénom et code secret sont requis.',
        })
        return
      }

      const response = await fetch(apiUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          nom,
          prenom,
          password,
          ...(invitationToken ? { invitation_token: invitationToken } : {}),
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

            <form className="auth-form" onSubmit={handleFormSubmit}>
              <div className="auth-form__row">
                <div className="auth-field">
                  <label htmlFor="nom">Nom</label>
                  <input
                    id="nom"
                    name="nom"
                    type="text"
                    autoComplete="family-name"
                    placeholder="Votre nom"
                    required
                  />
                </div>
                <div className="auth-field">
                  <label htmlFor="prenom">Prénom</label>
                  <input
                    id="prenom"
                    name="prenom"
                    type="text"
                    autoComplete="given-name"
                    placeholder="Votre prénom"
                    required
                  />
                </div>
              </div>

              {!invitationToken && (
                <div className="auth-field">
                  <label htmlFor="password">Code secret de la séance</label>
                  <div className="auth-password-wrap">
                    <input
                      id="password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="current-password"
                      placeholder="Code reçu par e-mail"
                      required
                    />
                    <button
                      type="button"
                      className="auth-password-toggle"
                      onClick={() => setShowPassword((visible) => !visible)}
                      aria-label={showPassword ? 'Masquer le code secret' : 'Afficher le code secret'}
                      aria-pressed={showPassword}
                    >
                      {showPassword ? 'Masquer' : 'Afficher'}
                    </button>
                  </div>
                </div>
              )}

              <button type="submit" disabled={submitting} className="auth-submit">
                {submitting ? 'Connexion…' : 'Rejoindre le cours'}
              </button>
            </form>

            <p className="auth-assurance">
              {invitationToken ? 'Invitation vérifiée' : 'Accès réservé aux apprenants inscrits'}
            </p>
          </div>
        </section>
      </div>
    </main>
  )
}
