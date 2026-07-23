import "./AgentCarousel.css";

const capabilities = [
  {
    className: "cadrenza-pierre-callout--slides",
    index: "01",
    text: "Prépare les diapositives du module",
  },
  {
    className: "cadrenza-pierre-callout--training",
    index: "02",
    text: "Anime les journées de formation",
  },
  {
    className: "cadrenza-pierre-callout--students",
    index: "03",
    text: "Interagit avec les élèves en direct",
  },
];

export const AgentCarousel = () => {
  return (
    <article className="cadrenza-pierre-showcase">
      <header className="cadrenza-pierre-intro">
        <div className="cadrenza-pierre-identity">
          <span className="cadrenza-pierre-avatar" aria-hidden="true">
            <img src="/robot-blue.png" alt="" />
          </span>
          <span>
            <strong>Pierre</strong>
            <small>Formateur TP CRCD</small>
          </span>
        </div>

        <p>
          Pierre prépare vos supports pédagogiques, anime les journées de
          formation et accompagne les élèves tout au long du cours.
        </p>
      </header>

      <div className="cadrenza-pierre-stage">
        <div className="cadrenza-pierre-visual">
          <img
            src="/pierre-classe-ia.png"
            alt="Pierre, professeur IA, présente un cours devant trois postes élèves"
          />
        </div>

        <svg
          className="cadrenza-pierre-connectors"
          viewBox="0 0 1120 650"
          role="presentation"
          aria-hidden="true"
        >
          <defs>
            <marker
              id="cadrenza-arrow"
              markerWidth="8"
              markerHeight="8"
              refX="6.5"
              refY="4"
              orient="auto"
            >
              <path d="M0 0L8 4L0 8Z" />
            </marker>
          </defs>
          <path d="M236 154C315 154 334 202 424 228" />
          <circle cx="424" cy="228" r="5" />
          <path d="M236 484C360 484 478 314 680 224" />
          <circle cx="680" cy="224" r="5" />
          <path d="M884 172C835 172 803 158 756 148" />
          <circle cx="756" cy="148" r="5" />
        </svg>

        <ul className="cadrenza-pierre-callouts">
          {capabilities.map((capability) => (
            <li
              className={`cadrenza-pierre-callout ${capability.className}`}
              key={capability.text}
            >
              <span aria-hidden="true">{capability.index}</span>
              <p>{capability.text}</p>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
};
