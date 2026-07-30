import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { apiUrl, setPlatformId, setPlatformName, setStudentLoginPath } from '../api'
import { getClassAccessFailure } from '../classAccessState.js'
import Index from './Index.jsx'
import CadrenzaLogo from '../components/CadrenzaLogo.jsx'
import AppLoader from '../components/AppLoader.jsx'
import './Auth.css'
import './ClassEntry.css'

function ClassEntryFallback({ failure }) {
  return (
    <main className="class-entry-error">
      <a
        className="class-entry-error__home"
        href="/"
        aria-label="Retour à l’accueil Cadrenza"
      >
        <CadrenzaLogo />
      </a>

      <section className="class-entry-error__content" role="alert">
        <h1>{failure.title}</h1>
        <p className="class-entry-error__message">{failure.message}</p>
        {failure.action === 'retry' ? (
          <button
            className="class-entry-error__action"
            type="button"
            onClick={() => window.location.reload()}
          >
            Réessayer
          </button>
        ) : (
          <a className="class-entry-error__action" href="/">
            Retour à l’accueil
          </a>
        )}
      </section>
    </main>
  )
}

export default function ClassEntry({ preloadCourseRoutes, preloadAttenteRoute, preloadVideoRoute }) {
  const { centerSlug, platformSlug } = useParams()
  const [state, setState] = useState({ status: 'loading', failure: null })

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    const classPath = `/classe/${centerSlug}/${platformSlug}`

    async function resolveClassAccess() {
      setState({ status: 'loading', failure: null })
      try {
        const response = await fetch(apiUrl(`/api/class-access/${encodeURIComponent(centerSlug)}/${encodeURIComponent(platformSlug)}`), {
          credentials: 'include',
          signal: controller.signal,
        })
        const data = await response.json().catch(() => ({}))

        if (!response.ok || !data.success) {
          console.warn('Accès à la classe refusé:', {
            status: response.status,
            reason: data.error || 'Réponse invalide',
          })
          if (!cancelled) {
            setState({
              status: 'error',
              failure: getClassAccessFailure(response.status),
            })
          }
          return
        }

        setPlatformId(data.platform.id)
        setPlatformName(data.platform.name)
        setStudentLoginPath(classPath)

        if (!cancelled) setState({ status: 'ready', failure: null })
      } catch (error) {
        if (error.name === 'AbortError') return
        console.error('API de classe inaccessible:', error)
        if (!cancelled) {
          setState({
            status: 'error',
            failure: getClassAccessFailure(),
          })
        }
      }
    }

    resolveClassAccess()
    return () => {
      cancelled = true
      controller.abort()
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
    return <ClassEntryFallback failure={state.failure} />
  }

  return (
    <Index
      preloadCourseRoutes={preloadCourseRoutes}
      preloadAttenteRoute={preloadAttenteRoute}
      preloadVideoRoute={preloadVideoRoute}
    />
  )
}
