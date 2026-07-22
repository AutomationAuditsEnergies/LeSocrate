import "./AgentCarousel.css";

const pierreCapabilities = [
  "Prépare les diapositives du module",
  "Anime les journées de formation",
  "Interagit avec les élèves en direct",
];

export const AgentCarousel = () => {
  return (
    <article className="cadrenza-pierre-card">
      <div className="cadrenza-pierre-visual">
        <img
          src="/static/images/ai-teacher-hero.png"
          alt="Pierre, professeur IA, animant une formation devant des élèves"
        />
      </div>

      <div className="cadrenza-pierre-content">
        <header className="cadrenza-pierre-heading">
          <div className="cadrenza-pierre-avatar" aria-hidden="true">
            <img src="/robot-blue.png" alt="" />
          </div>
          <div>
            <h3>Pierre</h3>
            <p>Formateur TP CRCD</p>
          </div>
        </header>

        <p className="cadrenza-pierre-description">
          Pierre prépare vos supports pédagogiques, anime les journées de
          formation et accompagne les élèves tout au long du cours.
        </p>

        <ul className="cadrenza-pierre-capabilities">
          {pierreCapabilities.map((capability) => (
            <li key={capability}>
              <span aria-hidden="true">✓</span>
              {capability}
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
};
