import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Component, lazy, Suspense, useState, useEffect } from 'react'
import { apiFetch, apiUrl, getStudentLoginPath, setPlatformId, setPlatformName, setStudentLoginPath } from '../api'
import { getSupabaseClient } from '../supabaseClient'

const Spline = lazy(() => import('@splinetool/react-spline'))

class SplineErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { failed: false } }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error) { console.warn('Spline désactivé:', error) }
  render() { return this.state.failed ? null : this.props.children }
}

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

export default function Index({ preloadCourseRoutes, preloadAttenteRoute, preloadVideoRoute }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const [splineLoaded, setSplineLoaded] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [authMode, setAuthMode] = useState('login')
  const [formMessage, setFormMessage] = useState(null)
  const [resettingPassword, setResettingPassword] = useState(false)
  const [passwordRecoveryMode, setPasswordRecoveryMode] = useState(false)

  useEffect(() => {
    document.body.style.overflow = 'hidden'

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

    return () => {
      document.body.style.overflow = ''
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

  useEffect(() => {
    let cancelled = false
    let subscription = null

    getSupabaseClient().then((client) => {
      if (cancelled || !client) return

      if (searchParams.get('auth') === 'recovery') {
        setPasswordRecoveryMode(true)
        setAuthMode('login')
        setFormMessage({ type: 'success', text: 'Choisissez un nouveau mot de passe.' })
      }

      const { data } = client.auth.onAuthStateChange((event) => {
        if (event === 'PASSWORD_RECOVERY') {
          setPasswordRecoveryMode(true)
          setAuthMode('login')
          setFormMessage({ type: 'success', text: 'Choisissez un nouveau mot de passe.' })
        }
      })
      subscription = data.subscription
    })

    return () => {
      cancelled = true
      subscription?.unsubscribe()
    }
  }, [searchParams])

  const handleFormSubmit = async (event) => {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setFormMessage(null)

    const formData = new FormData(event.target)
    const email = String(formData.get('email') || '').trim().toLowerCase()
    const password = String(formData.get('password') || '')
    const passwordConfirm = String(formData.get('password_confirm') || '')
    const nom = String(formData.get('nom') || '').trim()
    const prenom = String(formData.get('prenom') || '').trim()

    try {
      if (passwordRecoveryMode) {
        const supabaseClient = await getSupabaseClient()
        if (!supabaseClient) {
          setFormMessage({ type: 'error', text: "Supabase Auth n'est pas configuré sur ce frontend." })
          return
        }
        if (password !== passwordConfirm) {
          setFormMessage({ type: 'error', text: 'Les deux mots de passe ne correspondent pas.' })
          return
        }

        const { error } = await supabaseClient.auth.updateUser({ password })
        if (error) {
          setFormMessage({
            type: 'error',
            text: getSupabaseErrorMessage(error, 'Impossible de modifier le mot de passe.'),
          })
          return
        }

        await supabaseClient.auth.signOut()
        window.history.replaceState({}, '', '/')
        setPasswordRecoveryMode(false)
        setAuthMode('login')
        setFormMessage({
          type: 'success',
          text: 'Mot de passe modifié. Vous pouvez maintenant vous connecter.',
        })
        return
      }

      let response
      if (email || password) {
        const supabaseClient = await getSupabaseClient()
        if (!supabaseClient) {
          setFormMessage({ type: 'error', text: "Supabase Auth n'est pas configuré sur ce frontend." })
          return
        }
        let authData
        if (authMode === 'signup') {
          if (password !== passwordConfirm) {
            setFormMessage({ type: 'error', text: 'Les deux mots de passe ne correspondent pas.' })
            return
          }
          if (!nom || !prenom) {
            setFormMessage({ type: 'error', text: 'Nom et prénom sont requis pour créer un compte.' })
            return
          }
          const { data: signUpData, error: signUpError } = await supabaseClient.auth.signUp({
            email,
            password,
            options: {
              data: {
                nom,
                prenom,
                platform_id: parseInt(localStorage.getItem('platform_id') || '1'),
                role: 'student',
              },
            },
          })
          if (signUpError) {
            setFormMessage({
              type: 'error',
              text: getSupabaseErrorMessage(signUpError, 'Impossible de créer le compte.'),
            })
            return
          }
          if (!signUpData.session?.access_token) {
            setFormMessage({
              type: 'success',
              text: 'Compte créé. Vérifiez votre email pour confirmer votre inscription, puis reconnectez-vous.',
            })
            return
          }
          authData = signUpData
        } else {
          const { data: signInData, error: signInError } = await supabaseClient.auth.signInWithPassword({
            email,
            password,
          })
          if (signInError) {
            setFormMessage({
              type: 'error',
              text: getSupabaseErrorMessage(signInError, 'Identifiants incorrects.'),
            })
            return
          }
          authData = signInData
        }
        response = await fetch(apiUrl('/api/auth/supabase-session'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            access_token: authData.session?.access_token,
            platform_id: parseInt(localStorage.getItem('platform_id') || '1'),
          }),
        })
      } else {
        response = await fetch(apiUrl('/api/auth/login'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            nom,
            prenom,
            platform_id: parseInt(localStorage.getItem('platform_id') || '1'),
          }),
        })
      }

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

  const handleForgotPassword = async () => {
    if (resettingPassword) return

    const email = String(document.getElementById('email')?.value || '').trim().toLowerCase()
    setFormMessage(null)

    if (!email) {
      setFormMessage({ type: 'error', text: 'Entrez votre email pour recevoir le lien de réinitialisation.' })
      return
    }

    const supabaseClient = await getSupabaseClient()
    if (!supabaseClient) {
      setFormMessage({ type: 'error', text: "Supabase Auth n'est pas configuré sur ce frontend." })
      return
    }

    setResettingPassword(true)
    try {
      const { error } = await supabaseClient.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/?auth=recovery`,
      })

      if (error) {
        setFormMessage({
          type: 'error',
          text: getSupabaseErrorMessage(error, "Impossible d'envoyer le lien de réinitialisation."),
        })
        return
      }

      setFormMessage({
        type: 'success',
        text: 'Email envoyé. Ouvrez le lien reçu pour modifier votre mot de passe.',
      })
    } catch (error) {
      console.error('Erreur réinitialisation mot de passe:', error)
      setFormMessage({ type: 'error', text: "Impossible d'envoyer le lien de réinitialisation." })
    } finally {
      setResettingPassword(false)
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
          <div
            className="relative z-10 flex w-full items-center justify-center p-12"
            style={{
              opacity: splineLoaded ? 1 : 0,
              transform: splineLoaded ? 'scale(1)' : 'scale(0.96)',
              transition: 'opacity 1s ease-out, transform 1s ease-out',
            }}
          >
            <SplineErrorBoundary>
              <Suspense fallback={null}>
                <Spline
                  scene="https://prod.spline.design/Td1yXokrn9dRpNzQ/scene.splinecode"
                  style={{ width: '100%', height: '70vh', maxWidth: '560px' }}
                  onLoad={() => setTimeout(() => setSplineLoaded(true), 100)}
                />
              </Suspense>
            </SplineErrorBoundary>
          </div>
        </section>

        <section className="flex min-h-screen items-center justify-center px-6 py-10 sm:px-10 lg:px-12">
          <div className="w-full max-w-[420px]">
            <div className="mb-8">
              <p className="mb-3 text-sm font-semibold text-violet-700">Formation</p>
              <h2 className="text-3xl font-bold text-slate-950">
                {passwordRecoveryMode ? 'Nouveau mot de passe' : (authMode === 'signup' ? 'Inscription' : 'Connexion')}
              </h2>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                {passwordRecoveryMode
                  ? "Saisissez votre nouveau mot de passe pour reprendre accès à votre cours."
                  : authMode === 'signup'
                    ? 'Créez votre accès élève pour rejoindre votre formation.'
                    : 'Identifiez-vous pour accéder à votre espace de formation.'}
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
                    onClick={() => { setAuthMode(mode); setFormMessage(null) }}
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

            {formMessage && (
              <div
                className={`mb-6 rounded-lg border px-4 py-3 text-sm font-medium ${
                  formMessage.type === 'success'
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                    : 'border-red-200 bg-red-50 text-red-700'
                }`}
                role={formMessage.type === 'error' ? 'alert' : 'status'}
              >
                {formMessage.text}
              </div>
            )}

            <form className="space-y-5" onSubmit={handleFormSubmit}>
              {!passwordRecoveryMode && (
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-slate-800" htmlFor="email">
                    E-mail
                  </label>
                  <input
                    id="email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    placeholder="Votre adresse e-mail"
                    className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                  />
                </div>
              )}

              <div>
                <div className="mb-1.5 flex items-center justify-between gap-3">
                  <label className="block text-sm font-medium text-slate-800" htmlFor="password">
                    {passwordRecoveryMode ? 'Nouveau mot de passe' : 'Mot de passe'}
                  </label>
                  {authMode === 'login' && !passwordRecoveryMode && (
                    <button
                      type="button"
                      onClick={handleForgotPassword}
                      disabled={resettingPassword}
                      className="text-sm font-semibold text-violet-700 transition hover:text-violet-900 disabled:cursor-not-allowed disabled:text-slate-400"
                    >
                      {resettingPassword ? 'Envoi...' : 'Mot de passe oublié ?'}
                    </button>
                  )}
                </div>
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete={authMode === 'signup' || passwordRecoveryMode ? 'new-password' : 'current-password'}
                  placeholder={passwordRecoveryMode ? 'Nouveau mot de passe' : 'Votre mot de passe'}
                  className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                />
              </div>

              {(authMode === 'signup' || passwordRecoveryMode) && (
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-slate-800" htmlFor="password_confirm">
                    {passwordRecoveryMode ? 'Confirmer le nouveau mot de passe' : 'Confirmer le mot de passe'}
                  </label>
                  <input
                    id="password_confirm"
                    name="password_confirm"
                    type="password"
                    autoComplete="new-password"
                    placeholder={passwordRecoveryMode ? 'Confirmez le nouveau mot de passe' : 'Confirmez votre mot de passe'}
                    className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                  />
                </div>
              )}

              {authMode === 'signup' && !passwordRecoveryMode && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-slate-800" htmlFor="prenom">
                      Prénom
                    </label>
                    <input
                      id="prenom"
                      name="prenom"
                      type="text"
                      autoComplete="given-name"
                      placeholder="Votre prénom"
                      className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-slate-800" htmlFor="nom">
                      Nom
                    </label>
                    <input
                      id="nom"
                      name="nom"
                      type="text"
                      autoComplete="family-name"
                      placeholder="Votre nom"
                      className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                    />
                  </div>
                </div>
              )}

              {authMode === 'login' && !passwordRecoveryMode && (
                <details className="rounded-lg border border-slate-300 px-4 py-3">
                  <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-medium text-slate-600">
                    <span className="text-xs">▸</span> Connexion ancienne promo
                  </summary>
                  <div className="mt-3 space-y-3">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-slate-800" htmlFor="nom">Nom</label>
                      <input id="nom" name="nom" type="text" className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25" />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-slate-800" htmlFor="prenom">Prénom</label>
                      <input id="prenom" name="prenom" type="text" className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25" />
                    </div>
                  </div>
                </details>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="mt-2 inline-flex h-12 w-full items-center justify-center rounded-lg bg-[#8B5CF6] px-5 text-sm font-semibold text-white transition hover:bg-[#7c3aed] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-500 disabled:cursor-not-allowed disabled:bg-[#a78bfa]"
              >
                {submitting
                  ? (passwordRecoveryMode ? 'Modification...' : authMode === 'signup' ? 'Création...' : 'Connexion...')
                  : passwordRecoveryMode
                    ? 'Modifier le mot de passe'
                    : authMode === 'signup'
                      ? 'Créer le compte'
                      : 'Entrer au cours'}
              </button>

              {passwordRecoveryMode && (
                <button
                  type="button"
                  onClick={async () => {
                    const supabaseClient = await getSupabaseClient()
                    await supabaseClient?.auth.signOut()
                    window.history.replaceState({}, '', '/')
                    setPasswordRecoveryMode(false)
                    setFormMessage(null)
                  }}
                  className="w-full text-sm font-semibold text-slate-500 transition hover:text-slate-800"
                >
                  Revenir à la connexion
                </button>
              )}
            </form>
          </div>
        </section>
      </div>
    </main>
  )
}
