import CadrenzaLogo from './CadrenzaLogo.jsx'
import './AppErrorState.css'

function isLandingRoute() {
  if (typeof window === 'undefined') return false

  const { pathname, search } = window.location
  return pathname === '/landing'
    || (pathname === '/' && new URLSearchParams(search).get('p') === '3')
}

export default function AppErrorState() {
  const landing = isLandingRoute()

  return (
    <main className={`app-error-state${landing ? ' app-error-state--landing' : ''}`}>
      <header className="app-error-state__header">
        <a className="app-error-state__home" href="/" aria-label="Retour à l’accueil Cadrenza">
          <CadrenzaLogo />
        </a>
      </header>

      <section className="app-error-state__content" aria-live="assertive">
        <p className="app-error-state__eyebrow">La cadence s’est interrompue</p>
        <h1>Cette page n’a pas pu se charger.</h1>
        <p className="app-error-state__message">
          Rechargez-la pour reprendre là où vous en étiez.
        </p>
        <button
          className="app-error-state__action"
          type="button"
          onClick={() => window.location.reload()}
        >
          Recharger la page
        </button>
      </section>
    </main>
  )
}
