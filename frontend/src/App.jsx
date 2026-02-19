import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
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
        <Route
          path="/recorder"
          element={
            <ProtectedAdminRoute>
              <Recorder />
            </ProtectedAdminRoute>
          }
        />
        <Route
          path="/hr-dashboard"
          element={
            <ProtectedAdminRoute>
              <HRDashboard />
            </ProtectedAdminRoute>
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
