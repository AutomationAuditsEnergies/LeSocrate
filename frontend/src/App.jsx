import { useState, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { apiUrl } from './api'
import Admin from './pages/Admin.jsx'
import Attente from './pages/Attente.jsx'
import DebugCours from './pages/DebugCours.jsx'
import Index from './pages/Index.jsx'
import Intro from './pages/Intro.jsx'
import LoginAdmin from './pages/LoginAdmin.jsx'
import Video from './pages/Video.jsx'
import TestSlides from './pages/TestSlides.jsx'
import GeneratedSlides from './pages/GeneratedSlides.jsx'
import Recorder from './pages/Recorder.jsx'
import HRDashboard from './pages/HRDashboard.jsx'
import ProtectedAdminRoute from './components/ProtectedAdminRoute.jsx'

function ProtectedHRRoute({ children }) {
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    fetch(apiUrl('/api/hr/enabled'), { credentials: 'include' })
      .then(r => r.json())
      .then(data => setStatus(data.enabled ? 'enabled' : 'disabled'))
      .catch(() => setStatus('disabled'))
  }, [])

  if (status === 'loading') return null
  if (status === 'disabled') return <Navigate to="/" replace />
  return children
}

export default function App() {
  return (
    <BrowserRouter>
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

        <Route path="/intro" element={<Intro />} />
        <Route path="/test-slides" element={<TestSlides />} />
        <Route path="/generated-slides" element={<GeneratedSlides />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
