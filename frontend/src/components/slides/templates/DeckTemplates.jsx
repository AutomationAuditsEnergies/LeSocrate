import React, { useLayoutEffect, useRef, useState } from 'react';
import './DeckTemplates.css';
import { SalesHackingSourceSlide } from './SalesHackingSourceSlides';

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

export const DeckWelcome = () => <SalesHackingSourceSlide sourceId="welcome" />;

export const DeckChapterOpener = () => <SalesHackingSourceSlide sourceId="chapter_opener" />;

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

export const DeckProgramYear = () => <SalesHackingSourceSlide sourceId="program_year" />;

export const DeckDayProgram7Steps = () => <SalesHackingSourceSlide sourceId="day_program" />;

const renderReflectionTitle = (title = 'Une idée à retenir') => {
  const clean = String(title || 'Une idée à retenir').trim();
  if (clean.includes('\n')) {
    const lines = clean.split(/\n+/).filter(Boolean);
    const last = lines.pop();
    return <>{lines.map((line, index) => <React.Fragment key={index}>{line}<br /></React.Fragment>)}<span>{last}</span></>;
  }
  const parts = clean.split(/,\s*/);
  if (parts.length >= 2) {
    return <>{parts[0]},<br /><span>{parts.slice(1).join(', ')}</span></>;
  }
  const words = clean.split(/\s+/);
  if (words.length > 3) {
    const pivot = Math.ceil(words.length / 2);
    return <>{words.slice(0, pivot).join(' ')}<br /><span>{words.slice(pivot).join(' ')}</span></>;
  }
  return <span>{clean}</span>;
};

const renderReflectionText = (text = '') => {
  const clean = String(text || '').trim();
  if (!clean) return null;
  const sentences = clean.split(/(?<=[.!?])\s+/).filter(Boolean);
  if (sentences.length >= 2) {
    const last = sentences.pop();
    return <>{sentences.join(' ')}<br /><b>{last}</b></>;
  }
  return clean;
};

export const DeckStatement = ({
  title = 'Une idée à retenir',
  text,
  eyebrow = 'Principe clé',
  badge,
  brandName = 'Sales hacking',
}) => {
  const { brandHead, brandTail } = getDeckBrandParts(brandName);
  const [shellRef, scale] = useSlideStageScale();

  return (
    <div className="deck-reflection-shell" ref={shellRef}>
      <section className="deck-reflection-stage" style={{ transform: `scale(${scale})` }}>
        <div className="deck-chrome">
          <div className="deck-brand">
            <span className="deck-brand-mark">{brandHead}</span>
            <span className="deck-brand-tag">{brandTail}</span>
          </div>
          <div className="deck-reflection-rec"><span />EN DIRECT · {badge || 'TP-CRCD'}</div>
          <div className="deck-reflection-pages"><b>05</b> / 19</div>
          <div className="deck-reflection-section">TYPE · REFLECTION</div>
        </div>

        <span className="deck-reflection-eyebrow">— {eyebrow}</span>
        <h2 className="deck-reflection-title">{renderReflectionTitle(title)}</h2>
        {text && <p className="deck-reflection-body">{renderReflectionText(text)}</p>}
      </section>
    </div>
  );
};

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

export const DeckCaseStudy = ({
  title = 'Cas terrain',
  eyebrow = 'Analyse comparative',
  cases = [],
  items,
  badge,
  brandName = 'Sales hacking',
}) => {
  const sourceCases = Array.isArray(cases) ? cases : [];
  const sourceItems = sourceCases.length ? sourceCases : (Array.isArray(items) ? items : []);
  const safeCases = (sourceItems.length ? sourceItems : [
    {
      tag: '01 · Situation',
      title,
      desc: 'Un cas concret pour ancrer la notion dans une situation professionnelle.',
      example: '',
    },
  ]).slice(0, 6);
  const colClass = safeCases.length <= 2 ? 'cols-2' : (safeCases.length === 3 ? 'cols-3' : 'cols-many');
  const accents = ['accent-coral', 'accent-gold', 'accent-green', 'accent-blue'];
  const { brandHead, brandTail } = getDeckBrandParts(brandName);
  const [shellRef, scale] = useSlideStageScale();

  return (
    <div className="deck-casestudy-shell" ref={shellRef}>
      <section className="deck-casestudy-stage" style={{ transform: `scale(${scale})` }}>
        <div className="deck-chrome">
          <div className="deck-brand">
            <span className="deck-brand-mark">{brandHead}</span>
            <span className="deck-brand-tag">{brandTail}</span>
          </div>
          <div className="deck-casestudy-rec"><span />EN DIRECT · {badge || 'TP-CRCD'}</div>
          <div className="deck-casestudy-pages"><b>06</b> / 19</div>
          <div className="deck-casestudy-section">TYPE · CASE_STUDY</div>
        </div>

        <div className="deck-casestudy-head">
          <span className="deck-eyebrow">— {eyebrow}</span>
          <h1><AccentTitle title={title} fallback="Cas terrain." /></h1>
        </div>

        <div className={`deck-casestudy-cards ${colClass}`}>
          {safeCases.map((item, i) => {
            const caseTitle = typeof item === 'string' ? item : item.title;
            const caseDesc = typeof item === 'string' ? '' : (item.desc || item.description || item.text || '');
            const caseTag = typeof item === 'string' ? '' : (item.tag || item.label || `${String(i + 1).padStart(2, '0')} · Cas`);
            const caseExample = typeof item === 'string' ? '' : (item.example || item.quote || '');
            return (
              <article className={`deck-casestudy-card ${accents[i % accents.length]}`} key={i}>
                <div className="deck-casestudy-stripe" />
                <div className="deck-casestudy-body">
                  <span className="deck-casestudy-tag">{caseTag}</span>
                  <h3>{caseTitle}</h3>
                  <div className="deck-casestudy-sep" />
                  {caseDesc && <p>{caseDesc}</p>}
                  {caseExample && <em>{caseExample}</em>}
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
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

export const DeckPause = () => <SalesHackingSourceSlide sourceId="pause" />;

export const DeckQA = () => <SalesHackingSourceSlide sourceId="qa" />;

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
