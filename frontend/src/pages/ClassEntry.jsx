import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { apiUrl, setPlatformId, setPlatformName, setStudentLoginPath } from '../api'
import Index from './Index.jsx'

function ClassEntryFallback({ title, message }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6 text-slate-950" style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      <section className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-sm font-semibold text-violet-700">Le Socrate</p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight">{title}</h1>
        {message && <p className="mt-3 text-sm leading-6 text-slate-600">{message}</p>}
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
    return <ClassEntryFallback title="Chargement de la classe" message="Préparation de l'espace de connexion." />
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
