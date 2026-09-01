import './AppLoader.css'

const SURFACES = {
  dark: {
    background: '#0f172a',
    foreground: '#f1f5f9',
    muted: '#94a3b8',
  },
  landing: {
    background: '#ffffff',
    foreground: '#0f172a',
    muted: '#64748b',
  },
  light: {
    background: '#F8F7F5',
    foreground: '#0f172a',
    muted: '#64748b',
  },
}

function inferSurface() {
  if (typeof window === 'undefined') return 'light'

  const { pathname, search } = window.location
  if (pathname === '/landing' || (pathname === '/' && new URLSearchParams(search).get('p') === '3')) {
    return 'landing'
  }
  if (['/debug', '/schedule-config', '/formation-pipeline'].includes(pathname)) {
    return 'dark'
  }
  return 'light'
}

export default function AppLoader({
  label = 'Chargement',
  message = '',
  surface = 'auto',
}) {
  const palette = SURFACES[surface === 'auto' ? inferSurface() : surface] || SURFACES.light

  return (
    <main
      className="app-loader"
      style={{
        '--app-loader-background': palette.background,
        '--app-loader-foreground': palette.foreground,
        '--app-loader-muted': palette.muted,
      }}
      aria-live="polite"
      aria-busy="true"
    >
      <div className="app-loader__content">
        <img
          className="app-loader__mark"
          src="/socrate-mark.svg"
          alt=""
          aria-hidden="true"
        />
        <p className="app-loader__label">{label}</p>
        {message && <p className="app-loader__message">{message}</p>}
      </div>
    </main>
  )
}
