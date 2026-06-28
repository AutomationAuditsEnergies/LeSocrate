import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiFetch } from '../api'

export default function LoginCentre({ preloadDashboardRoute }) {
  const [authMode, setAuthMode] = useState('login')
  const [centerName, setCenterName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    const preload = () => { preloadDashboardRoute?.().catch(() => {}) }
    if ('requestIdleCallback' in window) {
      const idleId = window.requestIdleCallback(preload, { timeout: 1500 })
      return () => window.cancelIdleCallback(idleId)
    }
    const timeoutId = window.setTimeout(preload, 800)
    return () => window.clearTimeout(timeoutId)
  }, [preloadDashboardRoute])

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')

    if (authMode === 'signup' && password !== confirmPassword) {
      setError('Les deux mots de passe ne correspondent pas')
      return
    }

    setLoading(true)

    try {
      const response = await apiFetch(authMode === 'signup' ? '/api/admin/register' : '/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          center_name: centerName.trim(),
          username: username.trim(),
          password: password.trim(),
        }),
      })
      const data = await response.json().catch(() => ({}))

      if (response.ok && data.success) {
        await preloadDashboardRoute?.().catch(() => {})
        navigate('/hr-dashboard')
        return
      }

      setError(data.error || `Erreur serveur (${response.status})`)
    } catch (err) {
      console.error('Erreur login centre:', err)
      setError('Erreur de connexion au serveur')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-[#f8fafc] text-slate-950" style={{ fontFamily: 'Inter, system-ui, sans-serif' }}>
      <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,1fr)_520px]">
        <section
          className="relative hidden overflow-hidden bg-[#03093d] lg:flex"
          style={{
            backgroundImage: 'url(/wallpaper-centre.webp)',
            backgroundSize: 'cover',
            backgroundPosition: 'center',
          }}
        >
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(3,9,61,0.4)_0%,rgba(3,9,61,0)_34%,rgba(3,9,61,0.58)_100%)]" />
          <div className="relative z-10 flex w-full flex-col justify-between p-12 xl:p-16">
            <Link to="/landing" className="inline-flex w-fit items-center gap-3 text-white">
              <span className="h-3 w-3 rounded-full bg-[#8B5CF6]" />
              <span className="text-sm font-semibold uppercase">Le Socrate</span>
            </Link>

            <div className="max-w-[560px] pb-6">
              <p className="mb-4 text-sm font-semibold text-white/60 uppercase">
                Espace centre de formation
              </p>
              <h1 className="text-[3.75rem] font-black leading-[1.04] text-white">
                Pilotez vos formations depuis un seul espace.
              </h1>
              <p className="mt-6 max-w-[48ch] text-lg leading-8 text-white/78">
                Accédez au tableau de bord pour préparer les modules, suivre les plateformes et gérer vos journées de formation.
              </p>
            </div>
          </div>
        </section>

        <section className="flex min-h-screen items-center justify-center px-6 py-10 sm:px-10 lg:px-12">
          <div className="w-full max-w-[420px]">
            <Link to="/landing" className="mb-10 inline-flex items-center gap-3 text-slate-950 lg:hidden">
              <span className="h-3 w-3 rounded-full bg-[#8B5CF6]" />
              <span className="text-sm font-semibold uppercase">Le Socrate</span>
            </Link>

            <div className="mb-8">
              <p className="mb-3 text-sm font-semibold text-violet-700">Centre de formation</p>
              <h2 className="text-3xl font-bold text-slate-950">
                {authMode === 'signup' ? 'Inscription' : 'Connexion'}
              </h2>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                {authMode === 'signup'
                  ? 'Créez votre accès pour gérer vos plateformes de formation.'
                  : 'Identifiez-vous pour accéder au tableau de bord de pilotage.'}
              </p>
            </div>

            <div className="mb-7 grid h-11 grid-cols-2 rounded-lg bg-slate-200 p-1">
              {[
                ['login', 'Connexion'],
                ['signup', 'Inscription'],
              ].map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => {
                    setAuthMode(mode)
                    setError('')
                  }}
                  className={`rounded-md text-sm font-semibold transition ${
                    authMode === mode
                      ? 'bg-white text-violet-700 shadow-sm'
                      : 'text-slate-600 hover:text-slate-950'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {error && (
              <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
                {error}
              </div>
            )}

            <form className="space-y-5" onSubmit={handleSubmit}>
              {authMode === 'signup' && (
                <div>
                  <label htmlFor="centre-name" className="mb-1.5 block text-sm font-medium text-slate-800">
                    Nom du centre
                  </label>
                  <input
                    id="centre-name"
                    name="center_name"
                    type="text"
                    autoComplete="organization"
                    value={centerName}
                    onChange={(event) => setCenterName(event.target.value)}
                    required
                    placeholder="Votre centre de formation"
                    className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                  />
                </div>
              )}

              <div>
                <label htmlFor="centre-username" className="mb-1.5 block text-sm font-medium text-slate-800">
                  {authMode === 'signup' ? 'Email ou identifiant' : 'Identifiant'}
                </label>
                <input
                  id="centre-username"
                  name="username"
                  type="text"
                  autoComplete={authMode === 'signup' ? 'email' : 'username'}
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  required
                  placeholder={authMode === 'signup' ? 'contact@centre.fr' : 'Votre identifiant'}
                  className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                />
              </div>

              <div>
                <label htmlFor="centre-password" className="mb-1.5 block text-sm font-medium text-slate-800">
                  Mot de passe
                </label>
                <input
                  id="centre-password"
                  name="password"
                  type="password"
                  autoComplete={authMode === 'signup' ? 'new-password' : 'current-password'}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  placeholder="Votre mot de passe"
                  className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                />
              </div>

              {authMode === 'signup' && (
                <div>
                  <label htmlFor="centre-confirm-password" className="mb-1.5 block text-sm font-medium text-slate-800">
                    Confirmer le mot de passe
                  </label>
                  <input
                    id="centre-confirm-password"
                    name="confirm_password"
                    type="password"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    required
                    placeholder="Confirmez votre mot de passe"
                    className="h-12 w-full rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-950 outline-none transition placeholder:text-slate-500 focus:border-violet-500 focus:ring-2 focus:ring-violet-500/25"
                  />
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="mt-2 inline-flex h-12 w-full items-center justify-center rounded-lg bg-[#8B5CF6] px-5 text-sm font-semibold text-white transition hover:bg-[#7c3aed] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-500 disabled:cursor-not-allowed disabled:bg-[#a78bfa]"
              >
                {loading
                  ? (authMode === 'signup' ? 'Création...' : 'Connexion...')
                  : (authMode === 'signup' ? 'Créer le compte' : 'Accéder au tableau de bord')}
              </button>
            </form>
          </div>
        </section>
      </div>
    </main>
  )
}
