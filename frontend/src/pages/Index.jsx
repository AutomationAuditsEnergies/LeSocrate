import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { apiFetch, apiUrl, getStudentLoginPath, setPlatformId, setPlatformName, setStudentLoginPath } from '../api'

export default function Index({ preloadCourseRoutes, preloadAttenteRoute, preloadVideoRoute }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const [submitting, setSubmitting] = useState(false)
  const [formMessage, setFormMessage] = useState(null)

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
      if (!nom || !prenom || !password) {
        setFormMessage({ type: 'error', text: 'Nom, prénom et mot de passe sont requis.' })
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
    <main className="min-h-screen bg-[#f8fafc] text-slate-950" style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,1fr)_520px]">
        <section
          className="relative hidden overflow-hidden bg-[#03093d] lg:flex"
          style={{
            backgroundImage: 'url(/student-login-wallpaper.png)',
            backgroundSize: 'cover',
            backgroundPosition: 'center',
          }}
        />

        <section className="flex min-h-screen items-center justify-center px-6 py-10 sm:px-10 lg:px-12">
          <div className="w-full max-w-[420px]">
            <div className="mb-8">
              <p className="mb-3 text-sm font-semibold text-violet-700">Formation</p>
              <h2 className="text-3xl font-bold text-slate-950">
                Connexion
              </h2>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                Identifiez-vous avec le mot de passe reçu par email pour accéder au cours.
              </p>
            </div>

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

              <div>
                <label className="mb-1.5 block text-sm font-medium text-slate-800" htmlFor="password">
                  Mot de passe
                </label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  placeholder="Mot de passe reçu par email"
                  className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                />
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="mt-2 inline-flex h-12 w-full items-center justify-center rounded-lg bg-[#8B5CF6] px-5 text-sm font-semibold text-white transition hover:bg-[#7c3aed] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-500 disabled:cursor-not-allowed disabled:bg-[#a78bfa]"
              >
                {submitting
                  ? 'Connexion...'
                  : 'Entrer au cours'}
              </button>
            </form>
          </div>
        </section>
      </div>
    </main>
  )
}
