import { useNavigate, useSearchParams } from 'react-router-dom'
import { Component, lazy, Suspense, useState, useEffect } from 'react'
import { apiFetch, apiUrl, setPlatformId, setPlatformName } from '../api'

const Spline = lazy(() => import('@splinetool/react-spline'))

class SplineErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { failed: false } }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error) { console.warn('Spline désactivé:', error) }
  render() { return this.state.failed ? null : this.props.children }
}

export default function Index({ preloadCourseRoutes, preloadAttenteRoute, preloadVideoRoute }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [splineLoaded, setSplineLoaded] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [formMessage, setFormMessage] = useState(null)

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

  const handleFormSubmit = async (event) => {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setFormMessage(null)

    const formData = new FormData(event.target)
    const nom = String(formData.get('nom') || '').trim()
    const prenom = String(formData.get('prenom') || '').trim()

    try {
      if (!nom || !prenom) {
        setFormMessage({ type: 'error', text: 'Nom et prénom sont requis.' })
        return
      }

      const response = await fetch(apiUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          nom,
          prenom,
          platform_id: parseInt(localStorage.getItem('platform_id') || '1'),
        }),
      })

      const data = await response.json().catch(() => ({}))

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
        setFormMessage({ type: 'error', text: data.error || 'Nom ou prénom incorrect.' })
      }
    } catch (error) {
      console.error('Erreur connexion:', error)
      setFormMessage({ type: 'error', text: 'Impossible de se connecter au serveur.' })
    } finally {
      setSubmitting(false)
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
          <form className="space-y-5 text-left" onSubmit={handleFormSubmit}>
            <h1 className="text-center text-2xl font-bold text-gray-900">Connexion</h1>

            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700" htmlFor="nom">Nom</label>
              <input
                id="nom"
                name="nom"
                type="text"
                autoComplete="family-name"
                className="w-full rounded-lg border border-gray-200 p-3 text-sm focus:border-[#6070F2] focus:outline-none focus:ring-2 focus:ring-[#6070F2]/30"
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700" htmlFor="prenom">Prénom</label>
              <input
                id="prenom"
                name="prenom"
                type="text"
                autoComplete="given-name"
                className="w-full rounded-lg border border-gray-200 p-3 text-sm focus:border-[#6070F2] focus:outline-none focus:ring-2 focus:ring-[#6070F2]/30"
              />
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-[#6070F2] text-white font-bold py-3 px-4 rounded-lg hover:bg-[#5361dc] transition-colors disabled:cursor-not-allowed disabled:opacity-70"
            >
              {submitting ? 'Connexion...' : 'Entrer au cours'}
            </button>
          </form>

          <p className="mt-8 text-center text-sm text-gray-500 sm:mt-10">
            © 2026 Le Socrate. Tous droits réservés.
          </p>
        </div>
      </div>
    </div>
  )
}
