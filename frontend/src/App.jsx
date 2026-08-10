import { Component, lazy, Suspense, useState, useEffect } from 'react'
import { BrowserRouter, Route, Routes, useNavigate, useSearchParams } from 'react-router-dom'
import { apiUrl } from './runtimeConfig'
import Index from './pages/Index.jsx'
import ProtectedAdminRoute from './components/ProtectedAdminRoute.jsx'
import AppLoader from './components/AppLoader.jsx'
import AppErrorState from './components/AppErrorState.jsx'
import { clearSupabaseSession, getSupabaseClient } from './supabaseClient'

// Code splitting : les grosses pages restent chargées à la demande, mais les
// routes du flux apprenant sont préchargées depuis la page d'accueil pour éviter
// le flash de fallback après validation du formulaire.
const loadAttentePage = () => import('./pages/Attente.jsx')
const loadLoginCentrePage = () => import('./pages/LoginCentre.jsx')
const loadVideoPage = () => import('./pages/Video.jsx')
const loadHRDashboardPage = () => import('./pages/HRDashboard.jsx')
const loadClassEntryPage = () => import('./pages/ClassEntry.jsx')

const INTERNAL_ADMIN_TYPES = ['legacy_admin']
const CENTER_DASHBOARD_TYPES = ['legacy_admin', 'training_center']
const PIPELINE_ACCOUNT_TYPES = ['training_center']
const PIPELINE_PERMISSIONS = ['formation_pipeline']
const CENTER_PROTECTED_PATHS = ['/dashboard-centre', '/formation-pipeline']

const Attente = lazy(loadAttentePage)
const DebugCours = lazy(() => import('./pages/DebugCours.jsx'))
const LoginCentre = lazy(loadLoginCentrePage)
const Landing = lazy(() => import('./pages/Landing.jsx'))
const Video = lazy(loadVideoPage)
const TestSlides = lazy(() => import('./pages/TestSlides.jsx'))
const HRDashboard = lazy(loadHRDashboardPage)
const ScheduleConfig = lazy(() => import('./pages/ScheduleConfig.jsx'))
const FormationPipeline = lazy(() => import('./pages/FormationPipeline.jsx'))
const ClassEntry = lazy(loadClassEntryPage)

function preloadCourseRoutes() {
  return Promise.all([loadVideoPage(), loadAttentePage()])
}

function preloadAttenteRoute() {
  return loadAttentePage()
}

function preloadVideoRoute() {
  return loadVideoPage()
}

function RouteFallback() {
  return <AppLoader label="Chargement" />
}

class AppErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Erreur interface apprenant:', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    return <AppErrorState />
  }
}

function ProtectedHRRoute({ children }) {
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    fetch(apiUrl('/api/hr/enabled'), { credentials: 'include' })
      .then(r => r.json())
      .then(data => setStatus(data.enabled ? 'enabled' : 'disabled'))
      .catch(() => setStatus('disabled'))
  }, [])

  if (status === 'loading') return <RouteFallback />
  if (status === 'disabled') {
    return (
      <div
        style={{
          minHeight: '100vh',
          background: '#f8fafc',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
          fontFamily: 'Inter, system-ui, sans-serif',
        }}
      >
        <div
          style={{
            width: '100%',
            maxWidth: 460,
            borderRadius: 16,
            background: '#fff',
            border: '1px solid #e2e8f0',
            boxShadow: '0 18px 45px rgba(15, 23, 42, 0.10)',
            padding: 28,
          }}
        >
          <p style={{ margin: 0, color: '#7c3aed', fontSize: 14, fontWeight: 700 }}>
            Centre de formation
          </p>
          <h1 style={{ margin: '10px 0 0', color: '#0f172a', fontSize: 26, lineHeight: 1.2 }}>
            Tableau de bord indisponible
          </h1>
          <p style={{ margin: '14px 0 0', color: '#64748b', lineHeight: 1.6 }}>
            Le serveur n'a pas confirmé l'activation de l'espace centre. Vous n'êtes pas redirigé vers
            l'application élève.
          </p>
          <a
            href="/connexion-centre"
            style={{
              display: 'inline-flex',
              marginTop: 22,
              minHeight: 44,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 10,
              background: '#8B5CF6',
              color: '#fff',
              fontWeight: 700,
              padding: '0 18px',
              textDecoration: 'none',
            }}
          >
            Retour à la connexion
          </a>
        </div>
      </div>
    )
  }
  return children
}

function CenterDashboardRoute() {
  return (
    <ProtectedHRRoute>
      <ProtectedAdminRoute loginPath="/connexion-centre" allowedAccountTypes={CENTER_DASHBOARD_TYPES}>
        <HRDashboard />
      </ProtectedAdminRoute>
    </ProtectedHRRoute>
  )
}

function hasSupabaseRecoveryHash() {
  if (typeof window === 'undefined' || !window.location.hash) return false
  const hashParams = new URLSearchParams(window.location.hash.slice(1))
  return hashParams.get('type') === 'recovery'
    || (hashParams.has('access_token') && hashParams.has('refresh_token'))
}

function AuthRecoveryRedirect() {
  const navigate = useNavigate()

  useEffect(() => {
    if (window.location.pathname === '/' && hasSupabaseRecoveryHash()) {
      navigate(`/connexion-centre${window.location.hash}`, { replace: true })
    }
  }, [navigate])

  return null
}

function CenterSessionGuard() {
  const navigate = useNavigate()

  useEffect(() => {
    let isMounted = true
    let isRedirecting = false
    let authSubscription = null

    const isCenterProtectedPage = () => (
      CENTER_PROTECTED_PATHS.some(path => window.location.pathname.startsWith(path))
    )

    const returnToLogin = async () => {
      if (isRedirecting || !isCenterProtectedPage()) return
      isRedirecting = true
      localStorage.removeItem('admin_auth_token')
      localStorage.removeItem('admin_email')
      localStorage.removeItem('admin_center_name')
      await clearSupabaseSession().catch(() => {})
      if (isMounted) navigate('/connexion-centre', { replace: true })
    }

    const onSessionExpired = () => {
      void returnToLogin()
    }

    window.addEventListener('socrate:center-session-expired', onSessionExpired)

    void getSupabaseClient().then((client) => {
      if (!isMounted || !client) return
      const { data } = client.auth.onAuthStateChange((event) => {
        if (event === 'SIGNED_OUT') onSessionExpired()
      })
      authSubscription = data.subscription
    })

    return () => {
      isMounted = false
      window.removeEventListener('socrate:center-session-expired', onSessionExpired)
      authSubscription?.unsubscribe()
    }
  }, [navigate])

  return null
}

function PublicRoot() {
  const [searchParams] = useSearchParams()

  if (searchParams.get('p') === '3') return <Landing />

  return (
    <Index
      preloadCourseRoutes={preloadCourseRoutes}
      preloadAttenteRoute={preloadAttenteRoute}
      preloadVideoRoute={preloadVideoRoute}
    />
  )
}

function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-6 text-white">
      <div className="max-w-md">
        <p className="text-sm font-semibold text-orange-300">Cadrenza · Page introuvable</p>
        <h1 className="mt-3 text-3xl font-bold">Cette adresse n'existe pas.</h1>
        <a
          href="/connexion-centre"
          className="mt-8 inline-flex h-11 items-center justify-center rounded-lg bg-orange-400 px-5 text-sm font-semibold text-slate-950 transition hover:bg-orange-300"
        >
          Aller à la connexion
        </a>
      </div>
    </main>
  )
}

export default function App() {
  return (
    <AppErrorBoundary>
      <BrowserRouter>
        <AuthRecoveryRedirect />
        <CenterSessionGuard />
        <Suspense fallback={<RouteFallback />}>
          <Routes>
          <Route
            path="/"
            element={<PublicRoot />}
          />
          <Route
            path="/cours"
            element={
              <Index
                preloadCourseRoutes={preloadCourseRoutes}
                preloadAttenteRoute={preloadAttenteRoute}
                preloadVideoRoute={preloadVideoRoute}
              />
            }
          />
          <Route path="/landing" element={<Landing />} />
          <Route path="/attente" element={<Attente />} />
          <Route
            path="/classe/:centerSlug/:platformSlug"
            element={
              <ClassEntry
                preloadCourseRoutes={preloadCourseRoutes}
                preloadAttenteRoute={preloadAttenteRoute}
                preloadVideoRoute={preloadVideoRoute}
              />
            }
          />
          <Route path="/video" element={<Video />} />
          <Route
            path="/connexion-centre"
            element={(
              <LoginCentre
                preloadDashboardRoute={loadHRDashboardPage}
              />
            )}
          />

          {/* Routes protégées admin */}
          <Route
            path="/debug"
            element={
              <ProtectedAdminRoute allowedAccountTypes={INTERNAL_ADMIN_TYPES}>
                <DebugCours />
              </ProtectedAdminRoute>
            }
          />
          <Route
            path="/dashboard-centre"
            element={<CenterDashboardRoute />}
          />

          <Route
            path="/schedule-config"
            element={
              <ProtectedAdminRoute allowedAccountTypes={INTERNAL_ADMIN_TYPES}>
                <ScheduleConfig />
              </ProtectedAdminRoute>
            }
          />
          <Route
            path="/formation-pipeline"
            element={
              <ProtectedAdminRoute
                allowedAccountTypes={PIPELINE_ACCOUNT_TYPES}
                requiredPermissions={PIPELINE_PERMISSIONS}
              >
                <FormationPipeline />
              </ProtectedAdminRoute>
            }
          />
          <Route path="/test-slides" element={<TestSlides />} />
          <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AppErrorBoundary>
  )
}
