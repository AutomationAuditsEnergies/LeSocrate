export default function CadrenzaLogo({ compact = false, className = '' }) {
  return (
    <span className={`cadrenza-logo ${className}`.trim()} aria-label="Cadrenza">
      <svg
        className="cadrenza-logo__mark"
        viewBox="0 0 48 48"
        aria-hidden="true"
        focusable="false"
      >
        <path
          className="cadrenza-logo__arc"
          d="M36.4 12.2C33.2 8.9 28.7 7 24 7C14.6 7 7 14.6 7 24s7.6 17 17 17c4.7 0 9.2-1.9 12.4-5.2"
        />
        <path className="cadrenza-logo__cadence" d="M24 15h14M24 24h10M24 33h14" />
        <circle className="cadrenza-logo__node" cx="24" cy="15" r="2.7" />
        <circle className="cadrenza-logo__node" cx="24" cy="24" r="2.7" />
        <circle className="cadrenza-logo__node" cx="24" cy="33" r="2.7" />
      </svg>
      {!compact && <span className="cadrenza-logo__wordmark">Cadrenza</span>}
    </span>
  )
}
