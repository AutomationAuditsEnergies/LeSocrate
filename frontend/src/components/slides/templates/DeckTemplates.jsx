import React, { useLayoutEffect, useRef, useState } from 'react';
import './DeckTemplates.css';

const splitTitle = (title = '', fallback = '') => String(title || fallback).split(/\s+/);

const getDeckBrandParts = (brandName = 'Sales hacking') => {
  const normalizedBrandName = String(brandName || 'Sales hacking').trim();
  const isSalesHackingBrand = normalizedBrandName.toLowerCase() === 'sales hacking';
  const brandParts = normalizedBrandName.split(/\s+/);
  return {
    brandHead: isSalesHackingBrand ? 'Sales' : (brandParts[0] || 'Sales'),
    brandTail: isSalesHackingBrand ? 'hacking' : (brandParts.slice(1).join(' ') || 'hacking'),
  };
};

const renderWelcomeFormationName = (formationName = 'Titre professionnel CRCD') => {
  const text = String(formationName || 'Titre professionnel CRCD').trim();
  const crcdMatch = text.match(/\bCRCD\b/i);
  if (crcdMatch) {
    const before = text.slice(0, crcdMatch.index).trim();
    const crcd = text.slice(crcdMatch.index, crcdMatch.index + crcdMatch[0].length);
    return <>{before || 'Titre professionnel'}<br /><span className="crl">{crcd.toUpperCase()}</span></>;
  }
  const words = text.split(/\s+/);
  const last = words.pop();
  return <>{words.join(' ')}<br /><span className="crl">{last}</span></>;
};

const DeckSlide = ({ children, type = 'TEMPLATE', page = '01', className = '', danger = false, badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className={`deck-slide ${danger ? 'deck-slide--danger' : ''} ${className}`}>
    <div className="deck-chrome">
      <div className="deck-brand"><span className="deck-brand-mark">{brandName.split(/\s+/)[0] || 'Sales'}</span><span className="deck-brand-tag">{brandName.split(/\s+/).slice(1).join(' ') || 'Hacking'}</span></div>
      <div className="deck-rec"><span />EN DIRECT · {badge}</div>
      <div className="deck-pages"><b>{page}</b> / 19</div>
      <div className="deck-section">TYPE · {type}</div>
    </div>
    {children}
  </div>
);

const AccentTitle = ({ title, fallback, accentLast = true, className = '' }) => {
  const words = splitTitle(title, fallback);
  if (!accentLast || words.length < 2) return <>{title || fallback}</>;
  const last = words.pop();
  return <span className={className}>{words.join(' ')} <span className="deck-coral">{last}</span></span>;
};

const renderProgramSubtitle = (subtitle) => {
  const text = subtitle || "Une journée dédiée aux fondamentaux de l'échange à distance — du premier contact jusqu'à l'empreinte que l'on laisse après.";
  const highlight = "fondamentaux de l'échange à distance";
  const index = text.indexOf(highlight);
  if (index < 0) return text;
  return (
    <>
      {text.slice(0, index)}
      <b>{highlight}</b>
      {text.slice(index + highlight.length)}
    </>
  );
};

const useSlideStageScale = () => {
  const ref = useRef(null);
  const [scale, setScale] = useState(0.625);

  useLayoutEffect(() => {
    if (!ref.current) return undefined;
    const update = () => {
      const width = ref.current?.clientWidth || 1200;
      setScale(width / 1920);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  return [ref, scale];
};

export const DeckWelcome = ({
  title = 'Bienvenue',
  formation_name = 'Titre professionnel CRCD',
  day_label = 'Journée 1',
  meta_note = 'Relation client à distance',
  brandName = 'Sales hacking',
}) => {
  const [shellRef, scale] = useSlideStageScale();
  const { brandHead, brandTail } = getDeckBrandParts(brandName);

  return (
    <div className="deck-welcome-shell" ref={shellRef}>
      <section className="deck-welcome-stage" style={{ transform: `scale(${scale})` }}>
        <div className="deck-chrome">
          <div className="deck-brand">
            <span className="deck-brand-mark">{brandHead}</span>
            <span className="deck-brand-tag">{brandTail}</span>
          </div>
        </div>

        <div className="deck-welcome-meta-row">
          <span className="deck-welcome-day">{day_label}</span>
          <span className="deck-welcome-meta-bar" />
          <span className="deck-welcome-meta-note">{meta_note}</span>
        </div>

        <h1>{title}</h1>
        <div className="deck-welcome-title">{renderWelcomeFormationName(formation_name)}</div>
      </section>
    </div>
  );
};

export const DeckChapterOpener = ({
  chapter_label,
  chapter,
  title = "L'obstacle invisible",
  axes,
  items,
  points,
  brandName = 'Sales hacking',
}) => {
  const [shellRef, scale] = useSlideStageScale();
  const { brandHead, brandTail } = getDeckBrandParts(brandName);
  const cleanChapterLabel = String(chapter_label || chapter || 'Chapitre 1').replace(/\s*:$/, '');
  const sourceAxes = Array.isArray(axes) ? axes : (Array.isArray(items) ? items : (Array.isArray(points) ? points : []));
  const safeAxes = (sourceAxes.length ? sourceAxes : [
    {
      title: 'Le brouillard de la distance',
      desc: 'Quand le client ne voit pas, son cerveau complète.',
    },
    {
      title: 'Les biais de perception',
      desc: 'Un silence, un ton ou un rythme devient un message.',
    },
  ]).slice(0, 2);

  return (
    <div className="deck-chapter-shell" ref={shellRef}>
      <section className="deck-chapter-stage" style={{ transform: `scale(${scale})` }}>
        <div className="deck-chrome">
          <div className="deck-brand">
            <span className="deck-brand-mark">{brandHead}</span>
            <span className="deck-brand-tag">{brandTail}</span>
          </div>
        </div>

        <div className="deck-chapter-left">
          <h1><span className="deck-chapter-label">{cleanChapterLabel} :</span> <span className="deck-chapter-name">{title}</span></h1>
        </div>

        <div className="deck-chapter-axes">
          {safeAxes.map((axis, index) => (
            <div className="deck-chapter-axis" key={index}>
              <span className="deck-chapter-num">{String(index + 1).padStart(2, '0')}</span>
              <div className="deck-chapter-content">
                <span className="deck-chapter-axis-title">{typeof axis === 'string' ? axis : axis.title}</span>
                <span className="deck-chapter-axis-desc">{typeof axis === 'string' ? '' : (axis.desc || axis.description || axis.text)}</span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};

export const DeckAgenda = ({ title = 'Au programme.', items = [], day_label, formation_name, badge, brandName }) => {
  const sourceItems = Array.isArray(items) ? items : [];
  const safeItems = sourceItems.length ? sourceItems.slice(0, 6) : ['Accueil et objectifs', 'Notions clés', 'Mise en pratique', 'Synthèse'];
  return (
    <DeckSlide type="AGENDA" page="13" className="deck-agenda" badge={badge} brandName={brandName}>
      <div className="deck-agenda-left">
        <span className="deck-eyebrow">{day_label || 'Plan de séance'}</span>
        <h1><b>Au</b>programme.</h1>
        <p>{formation_name || title}</p>
      </div>
      <div className="deck-agenda-list">
        {safeItems.map((item, i) => (
          <div className={`deck-agenda-item ${i === 0 ? 'active' : ''}`} key={i}>
            <div>{String(i + 1).padStart(2, '0')}</div>
            <section><strong>{typeof item === 'string' ? item : item.title}</strong><span>{i === 0 ? 'EN COURS' : 'À VENIR'}</span></section>
          </div>
        ))}
      </div>
    </DeckSlide>
  );
};

export const DeckProgramYear = ({
  title = "Programme de l'année.",
  subtitle = "Deux grands ensembles de compétences qui se complètent pour tenir toutes les facettes du poste.",
  phases,
  items = [],
  day_label,
  formation_name,
  badge,
  brandName = 'Sales hacking',
}) => {
  const sourcePhases = Array.isArray(phases) && phases.length ? phases : items;
  const safePhases = (Array.isArray(sourcePhases) && sourcePhases.length ? sourcePhases : [
    {
      title: 'Assistance et relation client à distance',
      desc: 'Accueillir, écouter, comprendre et résoudre les demandes clients, quel que soit le canal utilisé.',
    },
    {
      title: 'Actions commerciales en relation client à distance',
      desc: "Identifier un besoin, éveiller un intérêt et proposer une solution adaptée avec éthique et justesse.",
    },
  ]).slice(0, 2);
  const { brandHead, brandTail } = getDeckBrandParts(brandName);
  const [shellRef, scale] = useSlideStageScale();

  return (
    <div className="deck-year-shell" ref={shellRef}>
      <section className="deck-year-stage" style={{ transform: `scale(${scale})` }}>
        <div className="deck-chrome">
          <div className="deck-brand">
            <span className="deck-brand-mark">{brandHead}</span>
            <span className="deck-brand-tag">{brandTail}</span>
          </div>
          <div className="deck-year-rec"><span />EN DIRECT · {badge || 'TP-CRCD'}</div>
          <div className="deck-year-pages"><b>02</b> / 19</div>
          <div className="deck-year-section">TYPE · PARCOURS</div>
        </div>

        <div className="deck-year-left">
          <span>{day_label || formation_name || 'Parcours annuel'}</span>
          <h1>{title === "Programme de l'année." ? <>Programme<br />de <em>l&apos;année.</em></> : <AccentTitle title={title} fallback="Programme de l'année." />}</h1>
          <p>{subtitle}</p>
        </div>

        <div className="deck-year-phases">
          {safePhases.map((phase, index) => {
            const phaseTitle = typeof phase === 'string' ? phase : phase.title;
            const phaseDesc = typeof phase === 'string' ? '' : (phase.desc || phase.description || phase.text || '');
            return (
              <article key={index}>
                <div className="deck-year-index">0{index + 1}</div>
                <div>
                  <strong>{phaseTitle}</strong>
                  {phaseDesc && <p>{phaseDesc}</p>}
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
};

export const DeckDayProgram7Steps = ({
  title = 'Programme de la journée.',
  subtitle,
  items = [],
  day_label,
  active_item = 1,
  badge,
  brandName = 'Sales hacking',
}) => {
  const sourceItems = Array.isArray(items) ? items : [];
  const safeItems = (sourceItems.length ? sourceItems : [
    'Communiquer sans visuel',
    'Le ton de la voix',
    'Le rythme de synchronisation',
    "Humaniser l'écrit asynchrone",
    'La première minute',
    "L'écoute active",
    "L'empreinte après contact",
  ]).slice(0, 7);
  const activeIndex = Math.max(0, Math.min(6, Number(active_item || 1) - 1));
  const { brandHead, brandTail } = getDeckBrandParts(brandName);
  const eyebrow = day_label ? (String(day_label).trim().startsWith('—') ? day_label : `— ${day_label}`) : '— Feuille de route';
  const [shellRef, scale] = useSlideStageScale();

  return (
    <div className="deck-program7-shell" ref={shellRef}>
      <section className="deck-program7-stage" style={{ transform: `scale(${scale})` }}>
        <div className="deck-chrome">
          <div className="deck-brand">
            <span className="deck-brand-mark">{brandHead}</span>
            <span className="deck-brand-tag">{brandTail}</span>
          </div>
        </div>

        <div className="deck-program7-left">
          <span className="deck-eyebrow">{eyebrow}</span>
          <h1>{title === 'Programme de la journée.' ? <>Programme<br />de la <span>journée.</span></> : <AccentTitle title={title} fallback="Programme de la journée." />}</h1>
          <p>{renderProgramSubtitle(subtitle)}</p>
        </div>

        <div className="deck-program7-list">
          <ol>
            {safeItems.map((item, i) => (
              <li className={i === activeIndex ? 'start' : ''} key={i}>
                <span className="n">{String(i + 1).padStart(2, '0')}</span>
                <span className="t">{typeof item === 'string' ? item : item.title}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </div>
  );
};

export const DeckStatement = ({ title = 'Une idée à retenir', text, badge, brandName }) => (
  <DeckSlide type="BIG_STATEMENT" page="02" className="deck-big" badge={badge} brandName={brandName}>
    <div>
      <span className="deck-eyebrow">Postulat de départ</span>
      <h1><AccentTitle title={title} fallback="Une idée à retenir" /></h1>
      {text && <p>{text}</p>}
    </div>
  </DeckSlide>
);

export const DeckDefinition = ({ term, title, eyebrow = 'Définition', definition, text, isItems = [], badge, brandName }) => {
  const word = term || title || 'Définition';
  const tags = Array.isArray(isItems) ? isItems : [];
  return (
    <DeckSlide type="DEFINITION" page="03" className="deck-def" badge={badge} brandName={brandName}>
      <div className="deck-def-left">
        <span className="deck-eyebrow">{eyebrow}</span>
        <h2>{word}</h2>
      </div>
      <div className="deck-def-right">
        <span>DÉFINITION DE TRAVAIL</span>
        <p>{definition || text || 'Une idée centrale formulée de manière simple, mémorisable et directement utilisable.'}</p>
        <div>{(tags.length ? tags : ['RÉPÉTABLE', 'MESURABLE', 'ACTIONNABLE']).slice(0, 4).map((item, i) => <em key={i}>{item}</em>)}</div>
      </div>
    </DeckSlide>
  );
};

export const DeckProcess = ({ title = 'Les étapes clés', steps = [], badge, brandName }) => {
  const sourceSteps = Array.isArray(steps) ? steps : [];
  const safeSteps = (sourceSteps.length ? sourceSteps : [{ title: 'Observer', desc: 'Comprendre la situation réelle.' }, { title: 'Découper', desc: 'Identifier les étapes utiles.' }, { title: 'Agir', desc: 'Appliquer la méthode.' }, { title: 'Mesurer', desc: 'Vérifier le résultat.' }]).slice(0, 4);
  return (
    <DeckSlide type="PROCESS" page="07" className="deck-process" badge={badge} brandName={brandName}>
      <header><span className="deck-eyebrow">Méthode</span><h1><AccentTitle title={title} fallback="Les étapes clés" /></h1></header>
      <div className="deck-process-steps">
        {safeSteps.map((step, i) => (
          <div className={i === 0 ? 'active' : ''} key={i}>
            <span>{String(i + 1).padStart(2, '0')}</span>
            <strong>{step.title}</strong>
            <p>{step.desc}</p>
          </div>
        ))}
      </div>
    </DeckSlide>
  );
};

export const DeckRecap = ({ title = "Ce qu'on retient.", points = [], badge, brandName }) => {
  const sourcePoints = Array.isArray(points) ? points : [];
  const safePoints = sourcePoints.length ? sourcePoints.slice(0, 3) : ['Une première idée clé.', 'Une deuxième idée clé.', 'Une action à appliquer.'];
  return (
    <DeckSlide type="RECAP" page="09" className="deck-recap" badge={badge} brandName={brandName}>
      <header><h1>{title}<br /><span>{safePoints.length} idées clés.</span></h1><p>FIN DE SÉQUENCE</p></header>
      <div className="deck-recap-grid">
        {safePoints.map((point, i) => <article key={i}><span>{String(i + 1).padStart(2, '0')} / IDÉE</span><strong>{String(point).split('.')[0]}</strong><p>{point}</p></article>)}
      </div>
    </DeckSlide>
  );
};

export const DeckCaseStudy = ({ title = 'Cas terrain', cases = [], badge, brandName }) => {
  const sourceCases = Array.isArray(cases) ? cases : [];
  const safeCases = sourceCases.length ? sourceCases.slice(0, 3) : [{ title, desc: 'Un cas concret pour ancrer la notion dans une situation professionnelle.' }];
  return (
    <DeckSlide type="CASE_STUDY" page="06" className="deck-case" badge={badge} brandName={brandName}>
      <header><h1>{title}</h1><p>Cas terrain · Application concrète</p></header>
      <div className="deck-case-stats">
        {safeCases.map((item, i) => <article key={i}><strong>{String(i + 1).padStart(2, '0')}</strong><span>{item.title}</span><p>{item.desc}</p></article>)}
      </div>
    </DeckSlide>
  );
};

export const DeckStats = ({ title = 'En chiffres.', description, stats = [], columns = [], badge, brandName }) => {
  const sourceStats = Array.isArray(stats) ? stats : [];
  const sourceColumns = Array.isArray(columns) ? columns : [];
  const safeStats = (sourceStats.length ? sourceStats : [{ number: '3' }, { number: '24h' }, { number: '95%' }]).slice(0, 4);
  return (
    <DeckSlide type="STATS" page="16" className="deck-stats" badge={badge} brandName={brandName}>
      <header><h1><AccentTitle title={title} fallback="En chiffres." /></h1><p>{description || 'Indicateurs à retenir'}</p></header>
      <div className="deck-stats-grid">
        {safeStats.map((stat, i) => <article className={i === 1 ? 'accent' : ''} key={i}><strong>{stat.number || stat.value}</strong><i /><span>{stat.label || sourceColumns[i] || 'Repère clé'}</span></article>)}
      </div>
    </DeckSlide>
  );
};

export const DeckWarning = ({ title = 'À éviter', text, badge, brandName }) => (
  <DeckSlide type="WARNING" page="17" className="deck-warning" danger badge={badge} brandName={brandName}>
    <div><div className="deck-warning-icon">!</div><span>ALERTE CRITIQUE</span><h1><AccentTitle title={title} fallback="À éviter" /></h1><p>{text}</p></div>
  </DeckSlide>
);

export const DeckTip = ({ title = 'Conseil pratique', text, badge, brandName }) => (
  <DeckSlide type="TIP" page="19" className="deck-tip" badge={badge} brandName={brandName}>
    <div className="deck-tip-left"><div className="deck-tip-badge">💡</div><span className="deck-eyebrow">Conseil pro</span><h1><AccentTitle title={title} fallback="Conseil pratique" /></h1><p>{text}</p></div>
    <div className="deck-tip-right"><span>Comment l'appliquer</span><article><strong>Règle simple</strong><p>{text || 'Transformez le conseil en action observable dès la prochaine situation.'}</p></article><article><strong>Point de vigilance</strong><p>Gardez une formulation courte, concrète et directement testable.</p></article></div>
  </DeckSlide>
);

export const DeckTransition = ({ title = 'On passe à la pratique.', from_topic, to_topic, badge, brandName }) => (
  <DeckSlide type="TRANSITION" page="10" className="deck-transition" badge={badge} brandName={brandName}>
    <div><span>{from_topic || 'FIN DE CHAPITRE'}</span><strong>{to_topic ? '→' : '04'}</strong><h1><AccentTitle title={title || to_topic} fallback="On passe à la pratique." /></h1><p>{to_topic || 'Prochaine étape'}</p></div>
  </DeckSlide>
);

export const DeckPause = ({ title = 'Pause.', subtitle = "notez ce qui vous a marqué jusqu'ici.", duration = '5 minutes', badge, brandName }) => (
  <DeckSlide type="PAUSE" page="11" className="deck-pause" badge={badge} brandName={brandName}>
    <div className="deck-pause-ring r3" />
    <div className="deck-pause-ring r2" />
    <div className="deck-pause-ring" />
    <div className="deck-pause-wrap">
      <span className="deck-eyebrow">On respire</span>
      <h1>{title}<br /><span>{duration}</span></h1>
      <p>{subtitle}</p>
    </div>
  </DeckSlide>
);

export const DeckQA = ({ title = 'On répond à tout.', questions = [], badge, brandName }) => {
  const safeQuestions = (Array.isArray(questions) && questions.length ? questions : [
    { initials: 'MA', text: 'Comment on filme un process qui ne se passe jamais pareil deux fois ?', meta: 'MARION · ASSISTANTE OPS' },
    { initials: 'YK', text: 'Outil recommandé pour stocker les SOPs en équipe distribuée ?', meta: 'YANIS · COO' },
    { initials: 'CL', text: "L'IA peut-elle écrire la première version d'un SOP depuis un Loom ?", meta: 'CLARA · FOUNDER' },
  ]).slice(0, 3);
  return (
    <DeckSlide type="QA" page="12" className="deck-qa" badge={badge} brandName={brandName}>
      <div className="deck-qa-left">
        <span className="deck-eyebrow">Vos questions, en direct</span>
        <strong>?</strong>
        <h1>{title}</h1>
      </div>
      <div className="deck-qa-right">
        {safeQuestions.map((question, i) => (
          <article key={i}>
            <b>{question.initials}</b>
            <p>{question.text}<small>{question.meta}</small></p>
            <span>{question.time || 'en direct'}</span>
          </article>
        ))}
        <div className="deck-qa-input">Posez votre question… <span>ENVOYER</span></div>
      </div>
    </DeckSlide>
  );
};

export const DeckComparison = ({ title = 'Avant vs après.', cols = [], rows = [], badge, brandName }) => {
  const sourceCols = Array.isArray(cols) ? cols : [];
  const sourceRows = Array.isArray(rows) ? rows : [];
  const left = sourceCols[0]?.label || 'Avant';
  const right = sourceCols[1]?.label || 'Après';
  const safeRows = sourceRows.length ? sourceRows : (sourceCols[0]?.items || []).slice(0, 4).map((item, i) => ({ label: `Critère ${i + 1}`, before: item, after: sourceCols[1]?.items?.[i] || 'Bonne pratique' }));
  return (
    <DeckSlide type="COMPARISON" page="18" className="deck-comparison" badge={badge} brandName={brandName}>
      <header><span className="deck-eyebrow">Deux approches</span><h1><AccentTitle title={title} fallback="Avant vs après." /></h1></header>
      <table><thead><tr><th /><th>{left}</th><th>{right}</th></tr></thead><tbody>{safeRows.map((row, i) => <tr key={i}><td>{row.label || row.criterion}<small>{row.hint}</small></td><td>{row.before || row.a}</td><td>{row.after || row.b}</td></tr>)}</tbody></table>
    </DeckSlide>
  );
};

export const DeckExercise = ({ title = 'Exercice pratique', duration = '12 minutes', objective, steps = [], badge, brandName }) => {
  const sourceSteps = Array.isArray(steps) ? steps : [];
  const safeSteps = (sourceSteps.length ? sourceSteps : [{ title: 'Nommer la tâche', desc: 'Choisir un cas réel.' }, { title: 'Lister les étapes', desc: 'Décrire la réalité.' }, { title: 'Identifier le point clé', desc: 'Repérer la décision.' }, { title: 'Partager', desc: 'Débriefer ensemble.' }]).slice(0, 4);
  return (
    <DeckSlide type="EXERCISE" page="15" className="deck-exercise" badge={badge} brandName={brandName}>
      <div className="deck-exercise-left"><span>01</span><em>{duration}</em><h1><AccentTitle title={title} fallback="Exercice pratique" /></h1><p>{objective}</p></div>
      <div className="deck-exercise-right">{safeSteps.map((step, i) => <article className={i === 0 ? 'active' : ''} key={i}><b>{step.num || i + 1}</b><div><strong>{step.title}</strong><p>{step.desc}</p></div></article>)}</div>
    </DeckSlide>
  );
};

export default DeckSlide;
