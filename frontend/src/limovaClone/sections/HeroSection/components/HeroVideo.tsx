const PipelineStep = ({ index, label }: { index: number; label: string }) => (
  <div className={`cadrenza-film__step cadrenza-film__step--${index}`}>
    <span>{index}</span>
    <strong>{label}</strong>
    <i aria-hidden="true" />
  </div>
)

export const HeroVideo = () => {
  return (
    <div className="cadrenza-film" role="img" aria-label="Démonstration animée de la création et de la diffusion d’un module de formation Cadrenza">
      <div className="cadrenza-film__glow" aria-hidden="true" />
      <div className="cadrenza-film__window">
        <header className="cadrenza-film__chrome">
          <div className="cadrenza-film__brand">
            <img src="/cadrenza-mark.svg" alt="" />
            <span>Cadrenza</span>
          </div>
          <div className="cadrenza-film__workspace">Centre de formation · Paris</div>
          <div className="cadrenza-film__avatar">AM</div>
        </header>

        <div className="cadrenza-film__body">
          <aside className="cadrenza-film__nav" aria-hidden="true">
            <span className="is-active">Vue d’ensemble</span>
            <span>Formations</span>
            <span>Promotions</span>
            <span>Planning</span>
          </aside>

          <main className="cadrenza-film__stage">
            <section className="cadrenza-film__scene cadrenza-film__scene--source">
              <div className="cadrenza-film__scene-heading">
                <div><small>Nouveau module</small><h2>Employé commercial</h2></div>
                <span className="cadrenza-film__status">RNCP 37099</span>
              </div>
              <div className="cadrenza-film__dropzone">
                <div className="cadrenza-film__document"><b>REAC</b><span>Référentiel officiel</span></div>
                <div className="cadrenza-film__upload-copy"><strong>Référentiel importé</strong><span>42 pages · structure vérifiée</span></div>
                <span className="cadrenza-film__check">✓</span>
              </div>
              <div className="cadrenza-film__cursor cadrenza-film__cursor--one" aria-hidden="true" />
            </section>

            <section className="cadrenza-film__scene cadrenza-film__scene--pipeline">
              <div className="cadrenza-film__scene-heading">
                <div><small>Production</small><h2>Votre module prend forme</h2></div>
                <span className="cadrenza-film__live"><i /> En cours</span>
              </div>
              <div className="cadrenza-film__pipeline">
                <PipelineStep index={1} label="Référentiel analysé" />
                <PipelineStep index={2} label="Cours structuré" />
                <PipelineStep index={3} label="Voix générée" />
                <PipelineStep index={4} label="Contrôle qualité" />
              </div>
              <div className="cadrenza-film__progress"><span /></div>
            </section>

            <section className="cadrenza-film__scene cadrenza-film__scene--schedule">
              <div className="cadrenza-film__scene-heading">
                <div><small>Diffusion</small><h2>Planifier la prochaine promotion</h2></div>
                <span className="cadrenza-film__status">Module prêt</span>
              </div>
              <div className="cadrenza-film__schedule-card">
                <div className="cadrenza-film__calendar"><b>16</b><span>SEPT.</span></div>
                <div><strong>Promotion EC · Automne</strong><span>Du lundi au vendredi · 9h00</span></div>
                <button type="button" tabIndex={-1}>Programmer le cours</button>
              </div>
              <div className="cadrenza-film__cursor cadrenza-film__cursor--two" aria-hidden="true" />
            </section>

            <section className="cadrenza-film__scene cadrenza-film__scene--classroom">
              <div className="cadrenza-film__classroom-top">
                <span className="cadrenza-film__onair"><i /> COURS EN DIRECT</span>
                <span>09:18</span>
              </div>
              <div className="cadrenza-film__lesson">
                <div className="cadrenza-film__teacher"><img src="/professor-icon.png" alt="" /></div>
                <div><small>Votre professeur IA</small><h2>Accueillir et conseiller le client</h2><p>Le cours avance au même rythme pour toute la promotion.</p></div>
              </div>
              <div className="cadrenza-film__wave" aria-hidden="true">{Array.from({ length: 28 }, (_, i) => <i key={i} />)}</div>
              <div className="cadrenza-film__lesson-progress"><span /></div>
            </section>
          </main>
        </div>
      </div>
      <div className="cadrenza-film__caption"><span>Un référentiel.</span><span>Un module durable.</span><span>Chaque promotion formée.</span></div>
    </div>
  )
}
