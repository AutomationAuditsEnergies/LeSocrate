import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiFetch, apiUrl, setPlatformId, setPlatformName } from '../api'

const STARS = [
  [45, 55, 1.5, 0.7], [120, 30, 1, 0.5], [180, 80, 2, 0.8], [250, 25, 1.5, 0.6],
  [380, 50, 1, 0.4], [450, 30, 2, 0.75], [520, 70, 1.5, 0.55], [560, 120, 1, 0.65],
  [30, 150, 1, 0.5], [90, 200, 2, 0.8], [150, 160, 1, 0.45], [500, 150, 1.5, 0.6],
  [570, 200, 2, 0.7], [40, 400, 1.5, 0.55], [100, 440, 1, 0.4], [540, 380, 2, 0.75],
  [580, 440, 1.5, 0.6], [30, 500, 1, 0.5], [80, 550, 2, 0.65], [550, 530, 1.5, 0.45],
  [500, 570, 1, 0.55], [200, 560, 1.5, 0.7], [300, 580, 1, 0.4], [420, 560, 2, 0.8],
  [320, 48, 1, 0.5], [60, 320, 1.5, 0.6], [580, 320, 2, 0.7], [470, 490, 1, 0.45],
  [135, 390, 1.5, 0.5], [390, 130, 1, 0.6], [490, 240, 1.5, 0.35],
]

function SpaceScene() {
  return (
    <svg
      viewBox="0 0 600 600"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="absolute inset-0 w-full h-full"
    >
      <defs>
        <radialGradient id="planetGrad" cx="38%" cy="30%" r="65%">
          <stop offset="0%" stopColor="#7C3AED" />
          <stop offset="45%" stopColor="#4C1D95" />
          <stop offset="100%" stopColor="#1e1b4b" />
        </radialGradient>
        <radialGradient id="planetGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#8B5CF6" stopOpacity="0.25" />
          <stop offset="100%" stopColor="#8B5CF6" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="ringGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#A78BFA" stopOpacity="0.05" />
          <stop offset="25%" stopColor="#A78BFA" stopOpacity="0.7" />
          <stop offset="75%" stopColor="#8B5CF6" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#8B5CF6" stopOpacity="0.05" />
        </linearGradient>
        <linearGradient id="rocketBody" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#ddd6fe" />
          <stop offset="100%" stopColor="#ede9fe" />
        </linearGradient>
        <radialGradient id="porthole" cx="40%" cy="35%" r="60%">
          <stop offset="0%" stopColor="#7dd3fc" />
          <stop offset="100%" stopColor="#0369a1" />
        </radialGradient>
        <linearGradient id="flame" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#f97316" stopOpacity="0.95" />
          <stop offset="40%" stopColor="#fb923c" stopOpacity="0.6" />
          <stop offset="100%" stopColor="#fbbf24" stopOpacity="0" />
        </linearGradient>
        <clipPath id="ringBack">
          <rect x="0" y="0" width="600" height="358" />
        </clipPath>
        <clipPath id="ringFront">
          <rect x="0" y="358" width="600" height="242" />
        </clipPath>
        <filter id="softGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Stars */}
      {STARS.map(([cx, cy, r, opacity], i) => (
        <circle key={i} cx={cx} cy={cy} r={r} fill="white" opacity={opacity} />
      ))}

      {/* Ambient glow */}
      <circle cx="320" cy="362" r="190" fill="url(#planetGlow)" />

      {/* Ring — back half */}
      <ellipse
        cx="320" cy="358" rx="208" ry="44"
        stroke="url(#ringGrad)" strokeWidth="12" fill="none"
        transform="rotate(-12 320 358)"
        clipPath="url(#ringBack)"
        opacity="0.5"
      />

      {/* Planet */}
      <circle cx="320" cy="362" r="137" fill="url(#planetGrad)" />

      {/* Surface bands */}
      <ellipse cx="320" cy="332" rx="137" ry="17" fill="white" opacity="0.03" />
      <ellipse cx="320" cy="388" rx="137" ry="20" fill="white" opacity="0.025" />

      {/* Specular highlight */}
      <ellipse cx="278" cy="307" rx="44" ry="32" fill="white" opacity="0.07" transform="rotate(-20 278 307)" />

      {/* Ring — front half */}
      <ellipse
        cx="320" cy="358" rx="208" ry="44"
        stroke="url(#ringGrad)" strokeWidth="12" fill="none"
        transform="rotate(-12 320 358)"
        clipPath="url(#ringFront)"
        opacity="0.9"
      />

      {/* Rocket — upper-left, tilted 35° */}
      <g transform="translate(166, 106) rotate(35)">
        {/* Flame */}
        <ellipse cx="0" cy="116" rx="18" ry="50" fill="url(#flame)" />
        <ellipse cx="-5" cy="108" rx="9" ry="28" fill="#fde68a" opacity="0.5" />

        {/* Body */}
        <path d="M-26 42 Q-26 -18 0 -58 Q26 -18 26 42 L26 92 L-26 92 Z" fill="url(#rocketBody)" />

        {/* Shadow side */}
        <path d="M0 -58 Q13 -18 26 42 L26 92 L0 92 Z" fill="rgba(0,0,0,0.07)" />

        {/* Porthole */}
        <circle cx="0" cy="22" r="15" fill="url(#porthole)" filter="url(#softGlow)" />
        <circle cx="0" cy="22" r="15" stroke="white" strokeWidth="1.5" fill="none" opacity="0.45" />
        <circle cx="-4" cy="17" r="4" fill="white" opacity="0.4" />

        {/* Fins */}
        <path d="M-26 68 L-50 102 L-26 88 Z" fill="#7C3AED" opacity="0.9" />
        <path d="M26 68 L50 102 L26 88 Z" fill="#6D28D9" opacity="0.9" />

        {/* Bottom cap */}
        <rect x="-26" y="88" width="52" height="6" rx="3" fill="#c4b5fd" />
      </g>

      {/* Debris */}
      <circle cx="490" cy="272" r="8" fill="#4C1D95" opacity="0.55" />
      <circle cx="510" cy="283" r="4" fill="#5B21B6" opacity="0.38" />
      <circle cx="148" cy="462" r="6" fill="#3b0764" opacity="0.45" />
    </svg>
  )
}

export default function LoginAdmin({ preloadAdminRoute }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const pParam = searchParams.get('p')

  useEffect(() => {
    if (pParam) {
      setPlatformId(pParam)
      fetch(apiUrl(`/api/platform-info?id=${pParam}`))
        .then(r => r.json())
        .then(data => { if (data.name) setPlatformName(data.name) })
        .catch(() => {})
    }
  }, [pParam])

  useEffect(() => {
    const preload = () => { preloadAdminRoute?.().catch(() => {}) }
    if ('requestIdleCallback' in window) {
      const idleId = window.requestIdleCallback(preload, { timeout: 1500 })
      return () => window.cancelIdleCallback(idleId)
    }
    const timeoutId = window.setTimeout(preload, 800)
    return () => window.clearTimeout(timeoutId)
  }, [preloadAdminRoute])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const response = await apiFetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password: password.trim() }),
      })
      const contentType = response.headers.get('content-type') || ''
      const data = contentType.includes('application/json') ? await response.json() : {}
      if (response.ok && data.success) {
        if (data.token) localStorage.setItem('admin_auth_token', data.token)
        await preloadAdminRoute?.().catch(() => {})
        navigate(pParam ? `/admin?p=${pParam}` : '/admin')
      } else {
        setError(data.error || `Erreur serveur (${response.status})`)
      }
    } catch (err) {
      console.error('Erreur login admin:', err)
      setError('Erreur de connexion au serveur')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* Panel gauche — espace */}
      <div
        className="hidden md:flex flex-1 relative overflow-hidden items-center justify-center"
        style={{ background: 'linear-gradient(160deg, #060b18 0%, #0f172a 40%, #1a0a3b 100%)' }}
      >
        <SpaceScene />
        <div className="absolute bottom-8 inset-x-0 text-center pointer-events-none">
          <p className="text-white/30 text-xs tracking-[0.2em] uppercase font-medium">Le Socrate</p>
          <p className="text-white/15 text-xs mt-0.5">Plateforme de formation professionnelle</p>
        </div>
      </div>

      {/* Panel droit — formulaire */}
      <div className="w-full md:max-w-[480px] flex flex-col justify-center px-8 md:px-14 py-12 bg-white">
        {/* Logo */}
        <div className="mb-10 flex items-center gap-2.5">
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
            style={{ background: 'linear-gradient(135deg, #8B5CF6, #6D28D9)' }}
          >
            <div className="w-3 h-3 bg-white rounded-full" />
          </div>
          <span className="text-xl font-bold text-slate-900 tracking-tight">Le Socrate</span>
        </div>

        <h1 className="text-3xl font-bold text-slate-900 tracking-tight mb-1">Connexion</h1>
        <p className="text-slate-400 text-sm mb-8">Espace administrateur</p>

        {error && (
          <div className="bg-red-50 border border-red-100 text-red-600 px-4 py-3 rounded-lg mb-6 text-sm">
            {error}
          </div>
        )}

        <form className="space-y-5" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-slate-700 mb-1.5">
              Utilisateur
            </label>
            <input
              type="text"
              id="username"
              name="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              placeholder="username"
              className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent transition"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-1.5">
              Mot de passe
            </label>
            <input
              type="password"
              id="password"
              name="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              placeholder="••••••••"
              className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm text-slate-900 placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent transition"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg font-semibold text-sm text-white transition"
            style={{
              background: loading ? '#a78bfa' : 'linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%)',
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>
      </div>
    </div>
  )
}
