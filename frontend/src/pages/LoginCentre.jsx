import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiFetch } from '../api'
import { getSupabaseClient } from '../supabaseClient'
import CadrenzaLogo from '../components/CadrenzaLogo.jsx'
import './Auth.css'

const AUTH_REQUEST_TIMEOUT_MS = 20_000

function getSupabaseErrorMessage(error, fallback) {
  const message = String(error?.message || '').toLowerCase()

  if (message.includes('email rate limit')) {
    return "Trop d'emails envoyés en peu de temps. Attendez quelques minutes avant de réessayer."
  }

  if (message.includes('password should be at least')) {
    return 'Le mot de passe doit contenir au moins 8 caractères.'
  }

  if (message.includes('invalid login credentials')) {
    return 'Email ou mot de passe incorrect.'
  }

  return error?.message || fallback
}

export default function LoginCentre({ preloadDashboardRoute }) {
  const initialPasswordRecoveryMode = (() => {
    if (typeof window === 'undefined') return false
    const searchParams = new URLSearchParams(window.location.search)
    const hashParams = new URLSearchParams(window.location.hash.slice(1))
    return searchParams.get('auth') === 'recovery'
      || hashParams.get('type') === 'recovery'
      || (hashParams.has('access_token') && hashParams.has('refresh_token'))
  })()
  const initialAuthMode = (() => {
    if (typeof window === 'undefined' || initialPasswordRecoveryMode) return 'login'
    return new URLSearchParams(window.location.search).get('mode') === 'signup' ? 'signup' : 'login'
  })()
  const [authMode, setAuthMode] = useState(initialAuthMode)
  const [centerName, setCenterName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(initialPasswordRecoveryMode ? 'Choisissez un nouveau mot de passe.' : '')
  const [loading, setLoading] = useState(false)
  const [resetLoading, setResetLoading] = useState(false)
  const [passwordRecoveryMode, setPasswordRecoveryMode] = useState(initialPasswordRecoveryMode)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    const preload = () => { preloadDashboardRoute?.().catch(() => {}) }
    if ('requestIdleCallback' in window) {
      const idleId = window.requestIdleCallback(preload, { timeout: 1500 })
      return () => window.cancelIdleCallback(idleId)
    }
    const timeoutId = window.setTimeout(preload, 800)
    return () => window.clearTimeout(timeoutId)
  }, [preloadDashboardRoute])

  useEffect(() => {
    let cancelled = false
    let subscription = null

    getSupabaseClient().then((client) => {
      if (cancelled || !client) return
      const { data } = client.auth.onAuthStateChange((event) => {
        if (event === 'PASSWORD_RECOVERY') {
          setPasswordRecoveryMode(true)
          setAuthMode('login')
          setNotice('Choisissez un nouveau mot de passe.')
        }
      })
      subscription = data.subscription
    })

    return () => {
      cancelled = true
      subscription?.unsubscribe()
    }
  }, [])

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setNotice('')

    if (authMode === 'signup' && password !== confirmPassword) {
      setError('Les deux mots de passe ne correspondent pas')
      return
    }

    if ((authMode === 'signup' || passwordRecoveryMode) && password.length < 8) {
      setError('Le mot de passe doit contenir au moins 8 caractères.')
      return
    }

    setLoading(true)

    try {
      if (passwordRecoveryMode) {
        const supabaseClient = await getSupabaseClient()
        if (!supabaseClient) {
          setError("Supabase Auth n'est pas configuré sur ce frontend.")
          return
        }
        if (password !== confirmPassword) {
          setError('Les deux mots de passe ne correspondent pas')
          return
        }

        const { error: updateError } = await supabaseClient.auth.updateUser({ password })
        if (updateError) {
          setError(getSupabaseErrorMessage(updateError, 'Impossible de modifier le mot de passe.'))
          return
        }

        await supabaseClient.auth.signOut()
        window.history.replaceState({}, '', '/connexion-centre')
        setPasswordRecoveryMode(false)
        setPassword('')
        setConfirmPassword('')
        setNotice('Mot de passe modifié. Vous pouvez maintenant vous connecter.')
        return
      }

      localStorage.removeItem('admin_auth_token')
      const response = await apiFetch(authMode === 'signup' ? '/api/admin/register' : '/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        timeoutMs: AUTH_REQUEST_TIMEOUT_MS,
        body: JSON.stringify({
          center_name: centerName.trim(),
          username: username.trim(),
          password: password.trim(),
        }),
      })
      const data = await response.json().catch(() => ({}))

      if (response.ok && data.success) {
        if (data.token) localStorage.setItem('admin_auth_token', data.token)
        if (data.account) {
          localStorage.setItem('center_account_email', data.account.username || '')
          localStorage.setItem('center_account_name', data.account.center_name || '')
        }
        preloadDashboardRoute?.().catch(() => {})
        navigate('/dashboard-centre')
        return
      }

      setError(data.error || `Erreur serveur (${response.status})`)
    } catch (err) {
      console.error('Erreur login centre:', err)
      if (err?.name === 'TimeoutError' || err?.name === 'AbortError') {
        setError('Le serveur met trop de temps à répondre. Réessayez dans quelques instants.')
      } else {
        setError('Erreur de connexion au serveur')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleForgotPassword = async () => {
    const email = username.trim().toLowerCase()
    setError('')
    setNotice('')
    if (!email) {
      setError("Entrez votre adresse email dans le champ identifiant.")
      return
    }
    const supabaseClient = await getSupabaseClient()
    if (!supabaseClient) {
      setError("Supabase Auth n'est pas configuré sur ce frontend.")
      return
    }
    setResetLoading(true)
    try {
      const response = await apiFetch('/api/admin/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        timeoutMs: AUTH_REQUEST_TIMEOUT_MS,
        body: JSON.stringify({ username: email }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        setError(data.error || `Erreur serveur (${response.status})`)
        return
      }

      const { error: resetError } = await supabaseClient.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/connexion-centre?auth=recovery`,
      })
      if (resetError) {
        setError(getSupabaseErrorMessage(resetError, "Impossible d'envoyer le lien de réinitialisation."))
        return
      }

      setNotice('Email envoyé. Ouvrez le lien reçu pour modifier votre mot de passe.')
    } catch (err) {
      console.error('Erreur mot de passe oublié:', err)
      setError("Impossible d'envoyer l'email de réinitialisation.")
    } finally {
      setResetLoading(false)
    }
  }

  return (
    <main className="cadrenza-auth">
      <a className="auth-skip-link" href="#auth-main">Aller au formulaire</a>
      <div className="auth-layout">
        <aside className="auth-visual" aria-label="Cadrenza pour les centres de formation">
          <Link to="/" className="auth-home-link" aria-label="Cadrenza, retour à l'accueil">
            <CadrenzaLogo />
          </Link>

          <div className="auth-visual__content">
            <p className="auth-eyebrow">Espace centre</p>
            <h1>Pilotez le parcours. Gardez le rythme.</h1>
            <p className="auth-visual__lead">
              Cadrenza réunit vos modules, vos promotions et vos preuves RNCP dans un même poste de pilotage.
            </p>
            <div className="auth-robot-stage" aria-hidden="true">
              <img src="/cadrenza-robot-fleet.webp" alt="" draggable={false} />
            </div>
          </div>

          <div className="auth-visual__meta" aria-label="Fonctions de l'espace centre">
            <span>Modules durables</span>
            <span>Promotions synchronisées</span>
            <span>Suivi centralisé</span>
          </div>
        </aside>

        <section className="auth-panel" id="auth-main">
          <div className="auth-panel__inner">
            <Link to="/" className="auth-mobile-logo" aria-label="Cadrenza, retour à l'accueil">
              <CadrenzaLogo />
            </Link>

            <header className="auth-heading">
              <p className="auth-heading__kicker">Centre de formation</p>
              <h2>
                {passwordRecoveryMode ? 'Nouveau mot de passe' : (authMode === 'signup' ? 'Créer votre espace' : 'Bon retour parmi nous')}
              </h2>
              <p>
                {passwordRecoveryMode
                  ? 'Définissez un nouveau mot de passe pour retrouver votre tableau de bord.'
                  : authMode === 'signup'
                    ? 'Créez l’accès administrateur qui vous permettra de structurer vos parcours.'
                    : 'Connectez-vous pour reprendre le pilotage de vos formations.'}
              </p>
            </header>

            {!passwordRecoveryMode && (
              <div className="auth-mode-switch" role="group" aria-label="Mode d'authentification">
                {[
                  ['login', 'Connexion'],
                  ['signup', 'Créer un compte'],
                ].map(([mode, label]) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={authMode === mode}
                    onClick={() => {
                      setAuthMode(mode)
                      setError('')
                      setNotice('')
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}

            {error && (
              <div className="auth-alert auth-alert--error" role="alert" aria-live="assertive">
                {error}
              </div>
            )}
            {notice && (
              <div className="auth-alert auth-alert--success" role="status" aria-live="polite">
                {notice}
              </div>
            )}

            <form className="auth-form" onSubmit={handleSubmit}>
              {authMode === 'signup' && !passwordRecoveryMode && (
                <div className="auth-field">
                  <label htmlFor="centre-name">Nom du centre</label>
                  <input
                    id="centre-name"
                    name="center_name"
                    type="text"
                    autoComplete="organization"
                    value={centerName}
                    onChange={(event) => setCenterName(event.target.value)}
                    required
                    placeholder="Votre centre de formation"
                  />
                </div>
              )}

              {!passwordRecoveryMode && (
                <div className="auth-field">
                  <label htmlFor="centre-username">
                    {authMode === 'signup' ? 'Email ou identifiant' : 'Identifiant'}
                  </label>
                  <input
                    id="centre-username"
                    name="username"
                    type="text"
                    autoComplete={authMode === 'signup' ? 'email' : 'username'}
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    required
                    placeholder={authMode === 'signup' ? 'contact@centre.fr' : 'Votre identifiant'}
                  />
                </div>
              )}

              <div className="auth-field">
                <div className="auth-field__head">
                  <label htmlFor="centre-password">
                    {passwordRecoveryMode ? 'Nouveau mot de passe' : 'Mot de passe'}
                  </label>
                  {authMode === 'login' && !passwordRecoveryMode && (
                    <button
                      type="button"
                      onClick={handleForgotPassword}
                      disabled={resetLoading}
                      className="auth-text-button"
                    >
                      {resetLoading ? 'Envoi en cours…' : 'Mot de passe oublié ?'}
                    </button>
                  )}
                </div>
                <div className="auth-password-wrap">
                  <input
                    id="centre-password"
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete={authMode === 'signup' || passwordRecoveryMode ? 'new-password' : 'current-password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                    minLength={authMode === 'signup' || passwordRecoveryMode ? 8 : undefined}
                    aria-describedby={authMode === 'signup' || passwordRecoveryMode ? 'centre-password-hint' : undefined}
                    placeholder={passwordRecoveryMode ? 'Nouveau mot de passe' : 'Votre mot de passe'}
                  />
                  <button
                    type="button"
                    className="auth-password-toggle"
                    onClick={() => setShowPassword((visible) => !visible)}
                    aria-label={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                    aria-pressed={showPassword}
                  >
                    {showPassword ? 'Masquer' : 'Afficher'}
                  </button>
                </div>
                {(authMode === 'signup' || passwordRecoveryMode) && (
                  <p className="auth-field__hint" id="centre-password-hint">8 caractères minimum.</p>
                )}
              </div>

              {(authMode === 'signup' || passwordRecoveryMode) && (
                <div className="auth-field">
                  <label htmlFor="centre-confirm-password">
                    {passwordRecoveryMode ? 'Confirmer le nouveau mot de passe' : 'Confirmer le mot de passe'}
                  </label>
                  <div className="auth-password-wrap">
                    <input
                      id="centre-confirm-password"
                      name="confirm_password"
                      type={showConfirmPassword ? 'text' : 'password'}
                      autoComplete="new-password"
                      value={confirmPassword}
                      onChange={(event) => setConfirmPassword(event.target.value)}
                      required
                      minLength={8}
                      placeholder="Saisissez-le une seconde fois"
                    />
                    <button
                      type="button"
                      className="auth-password-toggle"
                      onClick={() => setShowConfirmPassword((visible) => !visible)}
                      aria-label={showConfirmPassword ? 'Masquer la confirmation' : 'Afficher la confirmation'}
                      aria-pressed={showConfirmPassword}
                    >
                      {showConfirmPassword ? 'Masquer' : 'Afficher'}
                    </button>
                  </div>
                </div>
              )}

              <button type="submit" disabled={loading} className="auth-submit">
                {loading
                  ? (passwordRecoveryMode ? 'Modification…' : authMode === 'signup' ? 'Création…' : 'Connexion…')
                  : (passwordRecoveryMode ? 'Enregistrer le mot de passe' : authMode === 'signup' ? 'Créer mon espace' : 'Accéder au tableau de bord')}
              </button>
            </form>

            <p className="auth-assurance">Accès chiffré · Données de formation cloisonnées</p>
          </div>
        </section>
      </div>
    </main>
  )
}
