import { useNavigate, useSearchParams } from 'react-router-dom'
import { Component, lazy, Suspense, useState, useEffect } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { apiFetch, apiUrl, getPlatformName, setPlatformId, setPlatformName } from '../api'
import { isSupabaseConfigured, supabase } from '../supabaseClient'

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
  const [searchParams] = useSearchParams()
  const [splineLoaded, setSplineLoaded] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [authMode, setAuthMode] = useState('login')
  const [platformName, setPlatformNameState] = useState(getPlatformName())
  const [showPassword, setShowPassword] = useState(false)
  const [formMessage, setFormMessage] = useState(null)
  const [resettingPassword, setResettingPassword] = useState(false)
  const [passwordRecoveryMode, setPasswordRecoveryMode] = useState(false)

  useEffect(() => {
    document.body.style.overflow = 'hidden'

    const pParam = searchParams.get('p')
    if (pParam) {
      setPlatformId(pParam)
      fetch(apiUrl(`/api/platform-info?id=${pParam}`))
        .then(r => r.json())
        .then(data => {
          if (data.name) {
            setPlatformName(data.name)
            setPlatformNameState(data.name)
          }
        })
        .catch(() => {})
    }

    return () => {
      document.body.style.overflow = ''
    }
  }, [searchParams])

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
    if (!isSupabaseConfigured) return undefined

    if (searchParams.get('auth') === 'recovery') {
      setPasswordRecoveryMode(true)
      setAuthMode('login')
      setFormMessage({ type: 'success', text: 'Choisissez un nouveau mot de passe.' })
    }

    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') {
        setPasswordRecoveryMode(true)
        setAuthMode('login')
        setFormMessage({ type: 'success', text: 'Choisissez un nouveau mot de passe.' })
      }
    })

    return () => data.subscription.unsubscribe()
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
        if (!isSupabaseConfigured) {
          setFormMessage({ type: 'error', text: "Supabase Auth n'est pas configuré sur ce frontend." })
          return
        }
        if (password !== passwordConfirm) {
          setFormMessage({ type: 'error', text: 'Les deux mots de passe ne correspondent pas.' })
          return
        }

        const { error } = await supabase.auth.updateUser({ password })
        if (error) {
          setFormMessage({
            type: 'error',
            text: getSupabaseErrorMessage(error, 'Impossible de modifier le mot de passe.'),
          })
          return
        }

        await supabase.auth.signOut()
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
        if (!isSupabaseConfigured) {
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
          const { data: signUpData, error: signUpError } = await supabase.auth.signUp({
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
          const { data: signInData, error: signInError } = await supabase.auth.signInWithPassword({
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
        const withPlatform = (path) => (pId && pId !== '1' ? `${path}?p=${pId}` : path)

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

    if (!isSupabaseConfigured) {
      setFormMessage({ type: 'error', text: "Supabase Auth n'est pas configuré sur ce frontend." })
      return
    }

    setResettingPassword(true)
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
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
    <div
      className="relative min-h-dvh overflow-x-hidden overflow-y-auto bg-white md:h-screen md:overflow-hidden"
      style={{
        backgroundImage: 'url("/static/images/rocket.jpg"), linear-gradient(160deg, #0f172a 0%, #1e1b4b 55%, #312e81 100%)',
        backgroundColor: '#1e1b4b',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
      }}
    >
      {/* Spline — exactement comme avant, on touche rien */}
      <div
        className="hidden md:block"
        style={{
          position: 'absolute',
          top: '10%', left: '5%',
          width: '50%', height: '80%',
          opacity: splineLoaded ? 0.8 : 0,
          transform: splineLoaded ? 'scale(1)' : 'scale(0.95)',
          transition: 'opacity 1.5s ease-out, transform 1.5s ease-out',
          willChange: 'opacity, transform',
        }}
      >
        <SplineErrorBoundary>
          <Suspense fallback={null}>
            <Spline
              scene="https://prod.spline.design/Td1yXokrn9dRpNzQ/scene.splinecode"
              style={{ width: '100%', height: '100%' }}
              onLoad={() => setTimeout(() => setSplineLoaded(true), 100)}
            />
          </Suspense>
        </SplineErrorBoundary>
      </div>

      {/* Panel blanc — posé par-dessus à droite, wallpaper intact dessous */}
      <div
        className="relative z-10 flex min-h-dvh w-full flex-col overflow-y-auto bg-white md:absolute md:bottom-0 md:right-0 md:top-0 md:w-[600px] md:border-l md:border-black md:shadow-[-20px_0_60px_rgba(15,23,42,0.25)]"
      >
        {/* Titre — ancré en haut */}
        <div className="flex flex-shrink-0 justify-center px-5 pb-4 pt-8 sm:pt-10 md:pt-8">
          <div className="flex items-end gap-2 rotate-[-6deg]" aria-label="Sales hacking">
            <span className="text-[30px] font-bold leading-none text-[#111827] sm:text-[34px]" style={{ fontFamily: 'Caveat, cursive' }}>
              Sales
            </span>
            <span className="text-[35px] font-bold leading-none text-[#6070F2] sm:text-[39px]" style={{ fontFamily: 'Caveat, cursive' }}>
              hacking
            </span>
          </div>
        </div>

        <div className="mx-auto flex w-full max-w-[430px] flex-1 flex-col justify-center px-5 pb-8 pt-2 sm:px-8 md:max-w-none md:px-10 md:pb-12">

          {/* Onglets */}
          {!passwordRecoveryMode && (
            <div className="mb-6 grid grid-cols-2 rounded-lg border border-gray-200 bg-gray-50 p-1 text-sm font-semibold text-gray-600 sm:mb-7">
              <button
                type="button"
                onClick={() => { setAuthMode('login'); setFormMessage(null) }}
                className={`rounded-md px-3 py-2 transition ${authMode === 'login' ? 'bg-white text-[#6070F2] shadow-sm' : 'hover:text-gray-900'}`}
              >
                Connexion
              </button>
              <button
                type="button"
                onClick={() => { setAuthMode('signup'); setFormMessage(null) }}
                className={`rounded-md px-3 py-2 transition ${authMode === 'signup' ? 'bg-white text-[#6070F2] shadow-sm' : 'hover:text-gray-900'}`}
              >
                Inscription
              </button>
            </div>
          )}

          {/* Message */}
          {formMessage && (
            <div
              className={`mb-6 rounded-lg border px-4 py-3 text-sm font-medium ${
                formMessage.type === 'success'
                  ? 'border-[#6070F2]/30 bg-[#6070F2]/10 text-[#3340b8]'
                  : 'border-red-200 bg-red-50 text-red-700'
              }`}
              role={formMessage.type === 'error' ? 'alert' : 'status'}
            >
              {formMessage.text}
            </div>
          )}

          {/* Formulaire */}
          <form className="space-y-4 text-left sm:space-y-5" onSubmit={handleFormSubmit}>
            {passwordRecoveryMode && (
              <div className="text-center">
                <h1 className="text-2xl font-bold text-gray-900">Nouveau mot de passe</h1>
                <p className="mt-2 text-sm font-medium text-gray-500">
                  Saisissez votre nouveau mot de passe pour reprendre l'accès à votre compte.
                </p>
              </div>
            )}

            {!passwordRecoveryMode && (
              <div className="space-y-1.5">
                <label className="block text-sm font-medium text-gray-700" htmlFor="email">E-mail</label>
                <input
                  id="email" name="email" type="email" autoComplete="email"
                  placeholder="Entrez votre adresse e-mail"
                  className="w-full rounded-lg border border-gray-200 p-3 text-sm placeholder:text-gray-500 focus:border-[#6070F2] focus:outline-none focus:ring-2 focus:ring-[#6070F2]/30"
                />
              </div>
            )}

            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700" htmlFor="password">
                {passwordRecoveryMode ? 'Nouveau mot de passe' : 'Mot de passe'}
              </label>
              <div className="relative">
                <input
                  id="password" name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete={authMode === 'signup' ? 'new-password' : 'current-password'}
                  placeholder="Entrez votre mot de passe"
                  className="w-full rounded-lg border border-gray-200 p-3 pr-12 text-sm placeholder:text-gray-500 focus:border-[#6070F2] focus:outline-none focus:ring-2 focus:ring-[#6070F2]/30"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition"
                  aria-label={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {authMode === 'login' && !passwordRecoveryMode && (
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={handleForgotPassword}
                    disabled={resettingPassword}
                    className="text-sm font-semibold text-[#6070F2] transition hover:text-[#5361dc] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {resettingPassword ? 'Envoi en cours...' : 'Mot de passe oublié ?'}
                  </button>
                </div>
              )}
            </div>

            {(authMode === 'signup' || passwordRecoveryMode) && (
              <div className="space-y-1.5">
                <label className="block text-sm font-medium text-gray-700" htmlFor="password_confirm">
                  {passwordRecoveryMode ? 'Confirmer le nouveau mot de passe' : 'Confirmer le mot de passe'}
                </label>
                <input
                  id="password_confirm" name="password_confirm"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  placeholder="Confirmez votre mot de passe"
                  className="w-full rounded-lg border border-gray-200 p-3 text-sm placeholder:text-gray-500 focus:border-[#6070F2] focus:outline-none focus:ring-2 focus:ring-[#6070F2]/30"
                />
              </div>
            )}

            {authMode === 'signup' && !passwordRecoveryMode && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-gray-700" htmlFor="prenom">Prénom</label>
                  <input id="prenom" name="prenom" type="text" autoComplete="given-name"
                    placeholder="Votre prénom"
                    className="w-full rounded-lg border border-gray-200 p-3 text-sm placeholder:text-gray-500 focus:border-[#6070F2] focus:outline-none focus:ring-2 focus:ring-[#6070F2]/30" />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-gray-700" htmlFor="nom">Nom</label>
                  <input id="nom" name="nom" type="text" autoComplete="family-name"
                    placeholder="Votre nom"
                    className="w-full rounded-lg border border-gray-200 p-3 text-sm placeholder:text-gray-500 focus:border-[#6070F2] focus:outline-none focus:ring-2 focus:ring-[#6070F2]/30" />
                </div>
              </div>
            )}

            {authMode === 'login' && !passwordRecoveryMode && (
              <details className="rounded-lg border border-gray-200 px-4 py-3">
                <summary className="cursor-pointer text-sm font-medium text-gray-500 list-none flex items-center gap-1.5 select-none">
                  <span className="text-xs">▸</span> Connexion ancienne promo
                </summary>
                <div className="mt-3 space-y-3">
                  <div className="space-y-1.5">
                    <label className="block text-sm font-medium text-gray-700" htmlFor="nom">Nom</label>
                    <input id="nom" name="nom" type="text"
                      className="w-full rounded-lg border border-gray-200 p-3 text-sm focus:border-[#6070F2] focus:outline-none focus:ring-2 focus:ring-[#6070F2]/30" />
                  </div>
                  <div className="space-y-1.5">
                    <label className="block text-sm font-medium text-gray-700" htmlFor="prenom">Prénom</label>
                    <input id="prenom" name="prenom" type="text"
                      className="w-full rounded-lg border border-gray-200 p-3 text-sm focus:border-[#6070F2] focus:outline-none focus:ring-2 focus:ring-[#6070F2]/30" />
                  </div>
                </div>
              </details>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-[#6070F2] text-white font-bold py-3 px-4 rounded-lg hover:bg-[#5361dc] transition-colors disabled:cursor-not-allowed disabled:opacity-70"
            >
              {submitting
                ? 'Connexion...'
                : passwordRecoveryMode
                  ? 'Modifier le mot de passe'
                  : authMode === 'signup'
                    ? 'Créer mon compte'
                    : 'Entrer au cours'}
            </button>

            {passwordRecoveryMode && (
              <button
                type="button"
                onClick={async () => {
                  await supabase?.auth.signOut()
                  window.history.replaceState({}, '', '/')
                  setPasswordRecoveryMode(false)
                  setFormMessage(null)
                }}
                className="w-full text-sm font-semibold text-gray-500 transition hover:text-gray-800"
              >
                Revenir à la connexion
              </button>
            )}
          </form>

          <p className="mt-8 text-center text-sm text-gray-500 sm:mt-10">
            © 2026 Le Socrate. Tous droits réservés.
          </p>
        </div>
      </div>
    </div>
  )
}
