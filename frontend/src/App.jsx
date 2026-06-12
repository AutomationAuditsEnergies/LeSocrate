import { lazy, Suspense, useState, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { apiUrl } from './api'
import Index from './pages/Index.jsx'
import ProtectedAdminRoute from './components/ProtectedAdminRoute.jsx'

// Code splitting : seule la page de login (Index) est dans le bundle initial.
// Chaque page lourde (HRDashboard ~7k lignes, FormationPipeline ~8k, Video…)
// est téléchargée à la demande — le premier affichage ne paie plus les 3 Mo.
const Admin = lazy(() => import('./pages/Admin.jsx'))
const Attente = lazy(() => import('./pages/Attente.jsx'))
const DebugCours = lazy(() => import('./pages/DebugCours.jsx'))
const Intro = lazy(() => import('./pages/Intro.jsx'))
const LoginAdmin = lazy(() => import('./pages/LoginAdmin.jsx'))
const Video = lazy(() => import('./pages/Video.jsx'))
const TestSlides = lazy(() => import('./pages/TestSlides.jsx'))
const GeneratedSlides = lazy(() => import('./pages/GeneratedSlides.jsx'))
const Recorder = lazy(() => import('./pages/Recorder.jsx'))
const HRDashboard = lazy(() => import('./pages/HRDashboard.jsx'))
const ScheduleConfig = lazy(() => import('./pages/ScheduleConfig.jsx'))
const FormationPipeline = lazy(() => import('./pages/FormationPipeline.jsx'))

// Même visuel que le splash inline de index.html : la transition entre le
// chargement d'un chunk et la page est invisible (pas de flash noir).
function RouteFallback() {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'linear-gradient(160deg, #0f172a 0%, #1e1b4b 55%, #312e81 100%)',
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
          border: '3px solid rgba(139, 92, 246, 0.25)',
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
          <Route path="/" element={<Index />} />
          <Route path="/attente" element={<Attente />} />
          <Route path="/video" element={<Video />} />
          <Route path="/login-admin" element={<LoginAdmin />} />

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
