import { lazy, Suspense, useState, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { apiUrl } from './api'
import Index from './pages/Index.jsx'
import ProtectedAdminRoute from './components/ProtectedAdminRoute.jsx'

// Code splitting : les grosses pages restent chargées à la demande, mais les
// routes du flux apprenant sont préchargées depuis la page d'accueil pour éviter
// le flash de fallback après validation du formulaire.
const loadAdminPage = () => import('./pages/Admin.jsx')
const loadAttentePage = () => import('./pages/Attente.jsx')
const loadLoginAdminPage = () => import('./pages/LoginAdmin.jsx')
const loadVideoPage = () => import('./pages/Video.jsx')

const Admin = lazy(loadAdminPage)
const Attente = lazy(loadAttentePage)
const DebugCours = lazy(() => import('./pages/DebugCours.jsx'))
const Intro = lazy(() => import('./pages/Intro.jsx'))
const LoginAdmin = lazy(loadLoginAdminPage)
const Video = lazy(loadVideoPage)
const TestSlides = lazy(() => import('./pages/TestSlides.jsx'))
const GeneratedSlides = lazy(() => import('./pages/GeneratedSlides.jsx'))
const Recorder = lazy(() => import('./pages/Recorder.jsx'))
const HRDashboard = lazy(() => import('./pages/HRDashboard.jsx'))
const ScheduleConfig = lazy(() => import('./pages/ScheduleConfig.jsx'))
const FormationPipeline = lazy(() => import('./pages/FormationPipeline.jsx'))

function preloadCourseRoutes() {
  return Promise.all([loadVideoPage(), loadAttentePage()])
}

// Fallback de route volontairement clair : s'il apparaît encore sur une page
// non préchargée, il ne révèle plus le fond noir global.
function RouteFallback() {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: '#F8F7F5',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          width: 52,
          height: 52,
          borderRadius: '50%',
          border: '3px solid rgba(15, 23, 42, 0.12)',
          borderTopColor: '#8B5CF6',
          animation: 'socrate-spin 0.8s linear infinite',
        }}
      />
    </div>
  )
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
  if (status === 'disabled') return <Navigate to="/" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Index preloadCourseRoutes={preloadCourseRoutes} />} />
          <Route path="/attente" element={<Attente />} />
          <Route path="/video" element={<Video />} />
          <Route path="/login-admin" element={<LoginAdmin preloadAdminRoute={loadAdminPage} />} />

          {/* Routes protégées admin */}
          <Route
            path="/admin"
            element={
              <ProtectedAdminRoute>
                <Admin />
              </ProtectedAdminRoute>
            }
          />
          <Route
            path="/debug"
            element={
              <ProtectedAdminRoute>
                <DebugCours />
              </ProtectedAdminRoute>
            }
          />
          <Route path="/recorder" element={<Recorder />} />
          <Route
            path="/hr-dashboard"
            element={
              <ProtectedHRRoute>
                <ProtectedAdminRoute>
                  <HRDashboard />
                </ProtectedAdminRoute>
              </ProtectedHRRoute>
            }
          />

          <Route
            path="/schedule-config"
            element={
              <ProtectedAdminRoute>
                <ScheduleConfig />
              </ProtectedAdminRoute>
            }
          />
          <Route
            path="/formation-pipeline"
            element={
              <ProtectedAdminRoute>
                <FormationPipeline />
              </ProtectedAdminRoute>
            }
          />
          <Route path="/intro" element={<Intro />} />
          <Route path="/test-slides" element={<TestSlides />} />
          <Route
            path="/generated-slides"
            element={
              <ProtectedAdminRoute>
                <GeneratedSlides />
              </ProtectedAdminRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
