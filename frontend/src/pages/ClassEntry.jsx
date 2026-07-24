import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { apiUrl, setPlatformId, setPlatformName, setStudentLoginPath } from '../api'
import Index from './Index.jsx'
import CadrenzaLogo from '../components/CadrenzaLogo.jsx'
import AppLoader from '../components/AppLoader.jsx'
import './Auth.css'

function ClassEntryFallback({ title, message }) {
  return (
    <main className="cadrenza-auth auth-fallback">
      <section className="auth-fallback__card" aria-live="polite">
        <CadrenzaLogo />
        <h1>{title}</h1>
        {message && <p>{message}</p>}
      </section>
    </main>
  )
}

export default function ClassEntry({ preloadCourseRoutes, preloadAttenteRoute, preloadVideoRoute }) {
  const { centerSlug, platformSlug } = useParams()
  const [state, setState] = useState({ status: 'loading', error: '' })

  useEffect(() => {
    let cancelled = false
    const classPath = `/classe/${centerSlug}/${platformSlug}`

    async function resolveClassAccess() {
      setState({ status: 'loading', error: '' })
      try {
        const response = await fetch(apiUrl(`/api/class-access/${encodeURIComponent(centerSlug)}/${encodeURIComponent(platformSlug)}`), {
          credentials: 'include',
        })
        const data = await response.json().catch(() => ({}))

        if (!response.ok || !data.success) {
          throw new Error(data.error || `Classe introuvable (${response.status})`)
        }

        setPlatformId(data.platform.id)
        setPlatformName(data.platform.name)
        setStudentLoginPath(classPath)

        if (!cancelled) setState({ status: 'ready', error: '' })
      } catch (error) {
        if (!cancelled) setState({ status: 'error', error: error.message || 'Classe introuvable.' })
      }
    }

    resolveClassAccess()
    return () => {
      cancelled = true
    }
  }, [centerSlug, platformSlug])

  if (state.status === 'loading') {
    return (
      <AppLoader
        label="Chargement de la classe"
        message="Préparation de l'espace de connexion."
        surface="light"
      />
    )
  }

  if (state.status === 'error') {
    return <ClassEntryFallback title="Classe introuvable" message={state.error} />
  }

  return (
    <Index
      preloadCourseRoutes={preloadCourseRoutes}
      preloadAttenteRoute={preloadAttenteRoute}
      preloadVideoRoute={preloadVideoRoute}
    />
  )
}
