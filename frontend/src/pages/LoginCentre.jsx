import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiFetch } from '../api'
import { getSupabaseClient } from '../supabaseClient'

function getSupabaseErrorMessage(error, fallback) {
  const message = String(error?.message || '').toLowerCase()

  if (message.includes('email rate limit')) {
    return "Trop d'emails envoyés en peu de temps. Attendez quelques minutes avant de réessayer."
  }

  if (message.includes('password should be at least')) {
    return 'Le mot de passe doit contenir au moins 6 caractères.'
  }

  if (message.includes('invalid login credentials')) {
    return 'Email ou mot de passe incorrect.'
  }

  return error?.message || fallback
}

export default function LoginCentre({ preloadAdminRoute, preloadDashboardRoute }) {
  const initialPasswordRecoveryMode = (() => {
    if (typeof window === 'undefined') return false
    const searchParams = new URLSearchParams(window.location.search)
    const hashParams = new URLSearchParams(window.location.hash.slice(1))
    return searchParams.get('auth') === 'recovery'
      || hashParams.get('type') === 'recovery'
      || (hashParams.has('access_token') && hashParams.has('refresh_token'))
  })()
  const [authMode, setAuthMode] = useState('login')
  const [centerName, setCenterName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(initialPasswordRecoveryMode ? 'Choisissez un nouveau mot de passe.' : '')
  const [loading, setLoading] = useState(false)
  const [resetLoading, setResetLoading] = useState(false)
  const [passwordRecoveryMode, setPasswordRecoveryMode] = useState(initialPasswordRecoveryMode)
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
        body: JSON.stringify({
          center_name: centerName.trim(),
          username: username.trim(),
          password: password.trim(),
        }),
      })
      const data = await response.json().catch(() => ({}))

      if (response.ok && data.success) {
        if (data.token) localStorage.setItem('admin_auth_token', data.token)
        if (data.account?.type === 'legacy_admin') {
          preloadAdminRoute?.().catch(() => {})
          navigate('/admin')
        } else {
          preloadDashboardRoute?.().catch(() => {})
          navigate('/dashboard-centre')
        }
        return
      }

      setError(data.error || `Erreur serveur (${response.status})`)
    } catch (err) {
      console.error('Erreur login centre:', err)
      setError('Erreur de connexion au serveur')
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
    <main className="min-h-screen bg-[#f8fafc] text-slate-950" style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,1fr)_520px]">
        <section
          className="relative hidden overflow-hidden bg-[#03093d] lg:flex"
          style={{
            backgroundImage: 'url(/wallpaper-centre.webp)',
            backgroundSize: 'cover',
            backgroundPosition: 'center',
          }}
        >
          <div className="relative z-10 flex w-full items-center justify-center p-12">
            <img
              src="/robot-blue.png"
              alt="Professeur IA"
              draggable={false}
              className="w-full max-w-[420px] object-contain drop-shadow-2xl"
            />
          </div>
        </section>

        <section className="flex min-h-screen items-center justify-center px-6 py-10 sm:px-10 lg:px-12">
          <div className="w-full max-w-[420px]">
            <Link to="/" className="mb-10 inline-flex items-center gap-3 text-slate-950 lg:hidden">
              <span className="h-3 w-3 rounded-full bg-[#8B5CF6]" />
              <span className="text-sm font-semibold uppercase">Le Socrate</span>
            </Link>

            <div className="mb-8">
              <p className="mb-3 text-sm font-semibold text-violet-700">Centre de formation</p>
              <h2 className="text-3xl font-bold text-slate-950">
                {passwordRecoveryMode ? 'Nouveau mot de passe' : (authMode === 'signup' ? 'Inscription' : 'Connexion')}
              </h2>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                {passwordRecoveryMode
                  ? 'Saisissez votre nouveau mot de passe pour reprendre accès au tableau de bord.'
                  : authMode === 'signup'
                  ? 'Créez votre accès pour gérer vos plateformes de formation.'
                  : 'Identifiez-vous pour accéder au tableau de bord de pilotage.'}
              </p>
            </div>

            {!passwordRecoveryMode && (
            <div className="mb-7 grid h-11 grid-cols-2 rounded-lg bg-slate-200 p-1">
              {[
                ['login', 'Connexion'],
                ['signup', 'Inscription'],
              ].map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => {
                    setAuthMode(mode)
                    setError('')
                    setNotice('')
                  }}
                  className={`rounded-md text-sm font-semibold transition ${
                    authMode === mode
                      ? 'bg-white text-violet-700 shadow-sm'
                      : 'text-slate-600 hover:text-slate-950'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            )}

            {error && (
              <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
                {error}
              </div>
            )}
            {notice && (
              <div className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800">
                {notice}
              </div>
            )}

            <form className="space-y-5" onSubmit={handleSubmit}>
              {authMode === 'signup' && (
                <div>
                  <label htmlFor="centre-name" className="mb-1.5 block text-sm font-medium text-slate-800">
                    Nom du centre
                  </label>
                  <input
                    id="centre-name"
                    name="center_name"
                    type="text"
                    autoComplete="organization"
                    value={centerName}
                    onChange={(event) => setCenterName(event.target.value)}
                    required
                    placeholder="Votre centre de formation"
                    className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                  />
                </div>
              )}

              {!passwordRecoveryMode && (
              <div>
                <label htmlFor="centre-username" className="mb-1.5 block text-sm font-medium text-slate-800">
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
                  className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                />
              </div>
              )}

              <div>
                <div className="mb-1.5 flex items-center justify-between gap-3">
                  <label htmlFor="centre-password" className="block text-sm font-medium text-slate-800">
                    {passwordRecoveryMode ? 'Nouveau mot de passe' : 'Mot de passe'}
                  </label>
                  {authMode === 'login' && !passwordRecoveryMode && (
                    <button
                      type="button"
                      onClick={handleForgotPassword}
                      disabled={resetLoading}
                      className="text-sm font-semibold text-violet-700 transition hover:text-violet-900 disabled:cursor-not-allowed disabled:text-slate-400"
                    >
                      {resetLoading ? 'Envoi...' : 'Mot de passe oublié ?'}
                    </button>
                  )}
                </div>
                <input
                  id="centre-password"
                  name="password"
                  type="password"
                  autoComplete={authMode === 'signup' || passwordRecoveryMode ? 'new-password' : 'current-password'}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  placeholder={passwordRecoveryMode ? 'Nouveau mot de passe' : 'Votre mot de passe'}
                  className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                />
              </div>

              {(authMode === 'signup' || passwordRecoveryMode) && (
                <div>
                  <label htmlFor="centre-confirm-password" className="mb-1.5 block text-sm font-medium text-slate-800">
                    {passwordRecoveryMode ? 'Confirmer le nouveau mot de passe' : 'Confirmer le mot de passe'}
                  </label>
                  <input
                    id="centre-confirm-password"
                    name="confirm_password"
                    type="password"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    required
                    placeholder={passwordRecoveryMode ? 'Confirmez le nouveau mot de passe' : 'Confirmez votre mot de passe'}
                    className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                  />
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="mt-2 inline-flex h-12 w-full items-center justify-center rounded-lg bg-[#8B5CF6] px-5 text-sm font-semibold text-white transition hover:bg-[#7c3aed] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-500 disabled:cursor-not-allowed disabled:bg-[#a78bfa]"
              >
                {loading
                  ? (passwordRecoveryMode ? 'Modification...' : authMode === 'signup' ? 'Création...' : 'Connexion...')
                  : (passwordRecoveryMode ? 'Modifier le mot de passe' : authMode === 'signup' ? 'Créer le compte' : 'Accéder au tableau de bord')}
              </button>
            </form>
          </div>
        </section>
      </div>
    </main>
  )
}
