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

const renderAccentLastWord = (value = '', fallback = '') => {
  const words = splitTitle(value, fallback).filter(Boolean);
  if (words.length < 2) return value || fallback;
  const last = words.pop();
  return <>{words.join(' ')} <span className="crl">{last}</span></>;
};

const deckChrome = (brandName = 'Sales hacking') => {
  const { brandHead, brandTail } = getDeckBrandParts(brandName);
  return (
    <div className="deck-chrome">
      <div className="deck-brand">
        <span className="deck-brand-mark">{brandHead}</span>
        <span className="deck-brand-tag">{brandTail}</span>
      </div>
    </div>
  );
};

const sourceChrome = (brandName = 'Sales hacking') => {
  const { brandHead, brandTail } = getDeckBrandParts(brandName);
  return (
    <div className="chrome">
      <div className="brand">
        <span className="mark">{brandHead}</span>
        <span className="tag">{brandTail}</span>
      </div>
    </div>
  );
};

const SourceSlide = ({ className, children }) => {
  const [shellRef, scale] = useSlideStageScale();

  return (
    <div className="sales-source-deck-shell" ref={shellRef}>
      <section className={`slide ${className}`} style={{ transform: `scale(${scale})` }}>
        {children}
      </section>
    </div>
  );
};

export const DeckWelcome = ({
  title = 'Bienvenue',
  formation_name = 'Titre professionnel CRCD',
  day_label = 'Journée 1',
  meta_note = 'Relation client à distance',
  brandName = 'Sales hacking',
}) => {
  const [shellRef, scale] = useSlideStageScale();

  return (
    <div className="deck-welcome-shell" ref={shellRef}>
      <section className="deck-welcome-stage" style={{ transform: `scale(${scale})` }}>
        {deckChrome(brandName)}
        <div className="deck-welcome-meta-row">
          <span className="deck-welcome-day">{day_label}</span>
          <i className="deck-welcome-meta-bar" />
          <span className="deck-welcome-meta-note">{meta_note}</span>
        </div>
        <h1>{title}</h1>
        <div className="deck-welcome-title">{renderAccentLastWord(formation_name, 'Titre professionnel CRCD')}</div>
      </section>
    </div>
  );
};

export const DeckChapterOpener = ({
  chapter_label = 'Chapitre',
  title = 'Point clé',
  axes = [],
  items = [],
  brandName = 'Sales hacking',
}) => {
  const [shellRef, scale] = useSlideStageScale();
  const sourceAxes = Array.isArray(axes) && axes.length ? axes : items;
  const safeAxes = (Array.isArray(sourceAxes) && sourceAxes.length ? sourceAxes : [
    { title, desc: 'Le repère principal à retenir dans cette séquence.' },
  ]).slice(0, 3);

  return (
    <div className="deck-chapter-shell" ref={shellRef}>
      <section className="deck-chapter-stage" style={{ transform: `scale(${scale})` }}>
        {deckChrome(brandName)}
        <div className="deck-chapter-left">
          <h1><span className="deck-chapter-label">{chapter_label}</span> <span className="deck-chapter-name">{title}</span></h1>
        </div>
        <div className="deck-chapter-axes">
          {safeAxes.map((axis, index) => {
            const axisTitle = typeof axis === 'string' ? axis : (axis.title || axis.label || `Axe ${index + 1}`);
            const axisDesc = typeof axis === 'string' ? '' : (axis.desc || axis.text || axis.description || '');
            return (
              <div className="deck-chapter-axis" key={index}>
                <span className="deck-chapter-num">{String(index + 1).padStart(2, '0')}</span>
                <div className="deck-chapter-content">
                  <span className="deck-chapter-axis-title">{axisTitle}</span>
                  {axisDesc && <span className="deck-chapter-axis-desc">{axisDesc}</span>}
                </div>
              </div>
            );
          })}
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
  subtitle = 'Deux grands ensembles de compétences qui se complètent.',
  day_label = 'Parcours annuel',
  phases = [],
  items = [],
  brandName = 'Sales hacking',
  badge,
}) => {
  const [shellRef, scale] = useSlideStageScale();
  const sourcePhases = Array.isArray(phases) && phases.length ? phases : items;
  const safePhases = (Array.isArray(sourcePhases) && sourcePhases.length ? sourcePhases : [
    { title: 'Premier ensemble', desc: 'Installer les repères essentiels du parcours.' },
    { title: 'Deuxième ensemble', desc: 'Mettre les compétences en action.' },
  ]).slice(0, 4);
  const { brandHead, brandTail } = getDeckBrandParts(brandName);

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
          <div className="deck-year-section">TYPE · PROGRAMME</div>
        </div>
        <div className="deck-year-left">
          <span>- {day_label}</span>
          <h1>{renderAccentLastWord(title, "Programme de l'année.")}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="deck-year-phases">
          {safePhases.map((phase, index) => {
            const phaseTitle = typeof phase === 'string' ? phase : phase.title;
            const phaseDesc = typeof phase === 'string' ? '' : (phase.desc || phase.text || phase.description || '');
            return (
              <article key={index}>
                <span className="deck-year-index">{String(index + 1).padStart(2, '0')}</span>
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
  subtitle = 'Une journée dédiée aux fondamentaux.',
  day_label = 'Feuille de route',
  active_item = 1,
  items = [],
  brandName = 'Sales hacking',
}) => {
  const [shellRef, scale] = useSlideStageScale();
  const safeItems = (Array.isArray(items) && items.length ? items : [
    'Accueil et objectifs',
    'Notions clés',
    'Méthode',
    'Exemples',
    'Mise en pratique',
    'Synthèse',
    'Questions',
  ]).slice(0, 9);
  const activeIndex = Math.max(0, Number(active_item || 1) - 1);

  return (
    <div className="deck-program7-shell" ref={shellRef}>
      <section className="deck-program7-stage" style={{ transform: `scale(${scale})` }}>
        {deckChrome(brandName)}
        <div className="deck-program7-left">
          <span className="deck-eyebrow">- {day_label}</span>
          <h1>{renderAccentLastWord(title, 'Programme de la journée.')}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="deck-program7-list">
          <ol>
            {safeItems.map((item, index) => (
              <li className={index === activeIndex ? 'start' : ''} key={index}>
                <span className="n">{String(index + 1).padStart(2, '0')}</span>
                <span className="t">{typeof item === 'string' ? item : item.title || item.label}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </div>
  );
};

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

const normalizeTextList = (items, limit = 4) => (
  Array.isArray(items)
    ? items
      .map((item) => {
        if (typeof item === 'string') return item;
        return item?.title || item?.label || item?.text || item?.desc || item?.description || '';
      })
      .filter(Boolean)
      .slice(0, limit)
    : []
);

const splitDisplayTitle = (value = '', fallback = 'Point clé') => {
  const words = splitTitle(value, fallback).filter(Boolean);
  if (!words.length) return { first: fallback, rest: '' };
  if (words.length === 1) return { first: words[0], rest: '' };
  const first = words.slice(0, Math.ceil(words.length / 2)).join(' ');
  const rest = words.slice(Math.ceil(words.length / 2)).join(' ');
  return { first, rest };
};

const pointParts = (point, index) => {
  if (typeof point === 'string') {
    const clean = point.trim();
    const [head, ...tail] = clean.split(/\s*[:.]\s+/);
    return {
      title: head || `Point ${index + 1}`,
      desc: tail.join('. ') || clean,
    };
  }
  return {
    title: point?.title || point?.label || `Point ${index + 1}`,
    desc: point?.desc || point?.description || point?.text || point?.detail || '',
  };
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
    <SourceSlide className="s-def">
      {sourceChrome(brandName)}
      <div className="left">
        <span className="eyebrow">— {eyebrow}</span>
        <h2 className="word">{word}</h2>
      </div>
      <div className="right">
        <div className="label">DÉFINITION DE TRAVAIL</div>
        <p className="body">{definition || text || 'Une idée centrale formulée de manière simple, mémorisable et directement utilisable.'}</p>
        <div className="tag-row">
          {(tags.length ? tags : ['RÉPÉTABLE', 'MESURABLE', 'ACTIONNABLE']).slice(0, 4).map((item, i) => <span key={i}>{item}</span>)}
        </div>
      </div>
    </SourceSlide>
  );
};

export const DeckProcess = ({ title = 'Les étapes clés', steps = [], badge, brandName }) => {
  const sourceSteps = Array.isArray(steps) ? steps : [];
  const safeSteps = (sourceSteps.length ? sourceSteps : [{ title: 'Observer', desc: 'Comprendre la situation réelle.' }, { title: 'Découper', desc: 'Identifier les étapes utiles.' }, { title: 'Agir', desc: 'Appliquer la méthode.' }, { title: 'Mesurer', desc: 'Vérifier le résultat.' }]).slice(0, 4);
  return (
    <SourceSlide className="s-process">
      {sourceChrome(brandName)}
      <div className="head">
        <span className="eyebrow">— Méthode</span>
        <h1>{renderAccentLastWord(title, 'Les étapes clés')}</h1>
      </div>
      <div className="steps">
        {safeSteps.map((step, i) => (
          <div className={`step ${i === 0 ? 'active' : ''}`} key={i}>
            <div className="dot">{String(i + 1).padStart(2, '0')}</div>
            <h3 className="t">{step.title}</h3>
            {step.desc && <p className="d">{step.desc}</p>}
          </div>
        ))}
      </div>
    </SourceSlide>
  );
};

export const DeckStory = ({ title = 'Cas terrain', narrative, moral, text, badge, brandName }) => (
  <DeckSlide type="STORY" page="18" className="deck-story-dynamic" badge={badge} brandName={brandName}>
    <div>
      <span className="deck-eyebrow">Situation</span>
      <h1><AccentTitle title={title} fallback="Cas terrain" /></h1>
      <p>{narrative || text || 'Un exemple concret pour ancrer le point clé.'}</p>
      {moral && <strong>{moral}</strong>}
    </div>
  </DeckSlide>
);

export const DeckAnalogy = ({ title = 'Analogie', concept = 'Concept', comparison = 'Image mentale', text, badge, brandName }) => (
  <DeckSlide type="ANALOGY" page="19" className="deck-analogy-dynamic" badge={badge} brandName={brandName}>
    <header><span className="deck-eyebrow">Analogie</span><h1><AccentTitle title={title} fallback="Analogie" /></h1></header>
    <div>
      <article><span>Concept</span><strong>{concept}</strong></article>
      <article><span>Comparable à</span><strong>{comparison}</strong></article>
    </div>
    {text && <p>{text}</p>}
  </DeckSlide>
);

export const DeckOpinion = ({ title = 'Point de vue', text, badge, brandName }) => (
  <DeckSlide type="OPINION" page="21" className="deck-opinion-dynamic" badge={badge} brandName={brandName}>
    <span>"</span>
    <div>
      <em>Point de vue</em>
      <h1><AccentTitle title={title} fallback="Point de vue" /></h1>
      {text && <p>{text}</p>}
    </div>
  </DeckSlide>
);

export const DeckQuote = ({ quote, title, text, badge, brandName }) => (
  <SourceSlide className="s-journal">
    {sourceChrome(brandName)}
    <div className="jnl-scene">
      <div className="jnl-page">
        <div className="jnl-lines" />
        <div className="jnl-margin" />
        <div className="jnl-content">
          {(() => {
            const value = quote || text || title || 'Citation à retenir.';
            const sentences = String(value).split(/(?<=[.!?])\s+/).filter(Boolean);
            const first = sentences.length > 1 ? sentences.slice(0, -1).join(' ') : value;
            const second = sentences.length > 1 ? sentences[sentences.length - 1] : '';
            return (
              <>
                <p className="jnl-q1">{first}</p>
                {second && <p className="jnl-q2">{second}</p>}
              </>
            );
          })()}
        </div>
      </div>
    </div>
  </SourceSlide>
);

export const DeckFramework = ({ title = 'Cadre de lecture', center = {}, segments = [], items = [], badge, brandName }) => {
  const sourceSegments = Array.isArray(segments) && segments.length ? segments : items;
  const safeSegments = (Array.isArray(sourceSegments) && sourceSegments.length ? sourceSegments : [
    { title: 'Repère 1', desc: 'Premier point de lecture.' },
    { title: 'Repère 2', desc: 'Deuxième point de lecture.' },
    { title: 'Repère 3', desc: 'Troisième point de lecture.' },
    { title: 'Repère 4', desc: 'Quatrième point de lecture.' },
  ]).slice(0, 4);
  return (
    <DeckSlide type="FRAMEWORK" page="20" className="deck-framework-dynamic" badge={badge} brandName={brandName}>
      <header><span className="deck-eyebrow">Modèle</span><h1><AccentTitle title={title} fallback="Cadre de lecture" /></h1></header>
      <div className="deck-framework-dynamic-grid">
        <div className="deck-framework-dynamic-center">{center.title || center.label || 'Point central'}</div>
        {safeSegments.map((segment, index) => (
          <article key={index}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <strong>{typeof segment === 'string' ? segment : segment.title}</strong>
            {typeof segment !== 'string' && (segment.desc || segment.text) && <p>{segment.desc || segment.text}</p>}
          </article>
        ))}
      </div>
    </DeckSlide>
  );
};

export const DeckRecap = ({ title = "Ce qu'on retient.", points = [], badge, brandName }) => {
  const sourcePoints = Array.isArray(points) ? points : [];
  const safePoints = sourcePoints.length ? sourcePoints.slice(0, 3) : ['Une première idée clé.', 'Une deuxième idée clé.', 'Une action à appliquer.'];
  return (
    <SourceSlide className="s-recap2">
      {sourceChrome(brandName)}
      <div className="rc2-layout">
        <div className="rc2-left">
          <div className="rc2-head">
            <h1>{renderAccentLastWord(title, "Ce qu'on retient.")}</h1>
          </div>
          <div className="rc2-cards">
            {safePoints.map((point, i) => {
              const { title: pointTitle, desc } = pointParts(point, i);
              return (
                <div className="rc2-card" style={{ '--card-color': ['#ff6b47', '#f5a623', '#1e40af'][i % 3] }} key={i}>
                  <div className="rc2-num-badge">{String(i + 1).padStart(2, '0')}</div>
                  <h3>{pointTitle}</h3>
                  <div className="rc2-line" />
                  <p>{desc || pointTitle}</p>
                </div>
              );
            })}
          </div>
        </div>
        <div className="rc2-right">
          <div className="rc2-deco rc2-d1" />
          <div className="rc2-deco rc2-d2" />
          <div className="rc2-deco rc2-d3" />
          <div className="rc2-deco rc2-d4" />
          <svg className="rc2-plus p1" width="36" height="36" viewBox="0 0 36 36">
            <line x1="18" y1="0" x2="18" y2="36" stroke="#ff6b47" strokeWidth="5" strokeLinecap="round" />
            <line x1="0" y1="18" x2="36" y2="18" stroke="#ff6b47" strokeWidth="5" strokeLinecap="round" />
          </svg>
          <svg className="rc2-plus p2" width="28" height="28" viewBox="0 0 28 28">
            <line x1="14" y1="0" x2="14" y2="28" stroke="rgba(255,255,255,0.35)" strokeWidth="4" strokeLinecap="round" />
            <line x1="0" y1="14" x2="28" y2="14" stroke="rgba(255,255,255,0.35)" strokeWidth="4" strokeLinecap="round" />
          </svg>
          <svg className="rc2-plus p3" width="28" height="28" viewBox="0 0 28 28">
            <line x1="14" y1="0" x2="14" y2="28" stroke="var(--coral)" strokeWidth="4" strokeLinecap="round" />
            <line x1="0" y1="14" x2="28" y2="14" stroke="var(--coral)" strokeWidth="4" strokeLinecap="round" />
          </svg>
          <svg className="rc2-target" viewBox="0 0 500 500" xmlns="http://www.w3.org/2000/svg">
            <ellipse cx="258" cy="476" rx="180" ry="22" fill="rgba(0,0,20,0.45)" />
            <circle cx="250" cy="250" r="230" fill="#0a1060" />
            <circle cx="250" cy="250" r="190" fill="#0d1880" />
            <circle cx="250" cy="250" r="150" fill="#1a2a9a" />
            <circle cx="250" cy="250" r="110" fill="#f4967a" />
            <circle cx="250" cy="250" r="72" fill="#ff6b47" />
            <circle cx="250" cy="250" r="38" fill="#cc3b1e" />
            <ellipse cx="238" cy="237" rx="14" ry="9" fill="rgba(255,255,255,0.22)" transform="rotate(-20 238 237)" />
            <path d="M 90,180 A 190,190 0 0,1 250,60" stroke="rgba(255,255,255,0.10)" strokeWidth="28" fill="none" strokeLinecap="round" />
            <line x1="30" y1="470" x2="245" y2="255" stroke="#0a1060" strokeWidth="18" strokeLinecap="round" />
            <polygon points="245,255 230,278 268,260" fill="#0a1060" />
            <path d="M30,470 L10,445 L38,455 Z" fill="#0a1060" />
            <path d="M50,450 L28,428 L56,437 Z" fill="#1a2a9a" />
            <line x1="32" y1="468" x2="243" y2="258" stroke="rgba(255,255,255,0.12)" strokeWidth="6" strokeLinecap="round" />
          </svg>
        </div>
      </div>
    </SourceSlide>
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

export const DeckWarning = ({
  title = 'Automatiser le chaos.',
  text = "Brancher une IA sur un process bancal multiplie le désordre à la vitesse de la machine. Documentez d'abord, automatisez ensuite.",
  eyebrow = 'Erreur fréquente',
  label = 'Pourquoi',
  brandName = 'Sales hacking',
}) => {
  const [shellRef, scale] = useSlideStageScale();

  return (
    <div className="deck-warning-note-shell" ref={shellRef}>
      <section className="deck-warning-note-stage" style={{ transform: `scale(${scale})` }}>
        {deckChrome(brandName)}
        <div className="deck-warning-note-inner">
          <div className="deck-warning-note-sticky" aria-hidden="true">
            <svg viewBox="0 0 500 420" width="500" height="420" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="20" y="24" width="458" height="382" rx="4" fill="rgba(0,0,30,0.45)" transform="rotate(2,249,215)" />
              <rect x="14" y="12" width="458" height="382" rx="4" fill="#f5e87c" transform="rotate(-1.5,243,203)" />
              <line x1="50" y1="148" x2="448" y2="144" stroke="rgba(0,0,80,0.08)" strokeWidth="1.5" />
              <line x1="50" y1="188" x2="448" y2="184" stroke="rgba(0,0,80,0.06)" strokeWidth="1" />
              <line x1="50" y1="226" x2="448" y2="222" stroke="rgba(0,0,80,0.06)" strokeWidth="1" />
              <ellipse cx="253" cy="36" rx="14" ry="6" fill="rgba(0,0,30,0.3)" transform="translate(3,6)" />
              <circle cx="251" cy="30" r="20" fill="#cc1a2a" />
              <circle cx="251" cy="30" r="13" fill="#ff5d6c" />
              <circle cx="247" cy="26" r="5" fill="rgba(255,255,255,0.45)" />
              <line x1="251" y1="48" x2="251" y2="66" stroke="#7a0e1a" strokeWidth="5" strokeLinecap="round" />
              <text x="247" y="118" textAnchor="middle" fontFamily="Caveat, cursive" fontSize="88" fill="#cc1a2a" textLength="380" lengthAdjust="spacing" transform="rotate(-1.5,247,118)">Attention !</text>
            </svg>
          </div>

          <div className="deck-warning-note-text">
            <span className="deck-eyebrow">- {eyebrow}</span>
            <h1>{renderAccentLastWord(title, 'Automatiser le chaos.')}</h1>
            <div className="deck-warning-note-body">
              <span className="deck-warning-note-label">{label}</span>
              <p>{text}</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

export const DeckTip = ({ title = 'Conseil pratique', text, badge, brandName }) => (
  <SourceSlide className="s-tip">
    {sourceChrome(brandName)}
    <div className="card">
      <span className="badge">CONSEIL</span>
      <h2>{title}</h2>
      <p>{text || 'Transformez le conseil en action observable dès la prochaine situation.'}</p>
    </div>
  </SourceSlide>
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
  const left = sourceCols[0] || { label: 'Avant', items: [] };
  const right = sourceCols[1] || { label: 'Après', items: [] };
  const leftTitle = splitDisplayTitle(left.label || title, 'Avant');
  const rightTitle = splitDisplayTitle(right.label || 'Après', 'Après');
  const leftItems = normalizeTextList(left.items, 4);
  const rightItems = normalizeTextList(right.items, 4);
  const safeRows = sourceRows.length ? sourceRows : leftItems.map((item, i) => ({ before: item, after: rightItems[i] || 'Bonne pratique' }));
  return (
    <SourceSlide className="s-diag">
      {sourceChrome(brandName)}
      <div className="col l">
        <span className="eyebrow">— {left.label || 'Avant'}</span>
        <h2>{leftTitle.first}<br /><span className="b">{leftTitle.rest || 'actuel.'}</span></h2>
        <ul>
          {(safeRows.length ? safeRows : [{ before: 'Situation actuelle' }]).slice(0, 4).map((row, i) => (
            <li key={i}><span className="ic">−</span>{row.before || row.a || row.label || row.criterion}</li>
          ))}
        </ul>
      </div>
      <div className="col r">
        <span className="eyebrow">— {right.label || 'Après'}</span>
        <h2>{rightTitle.first}<br /><span className="accent">{rightTitle.rest || 'cible.'}</span></h2>
        <ul>
          {(safeRows.length ? safeRows : [{ after: 'Bonne pratique' }]).slice(0, 4).map((row, i) => (
            <li key={i}><span className="ic">✓</span>{row.after || row.b || rightItems[i] || 'Bonne pratique'}</li>
          ))}
        </ul>
      </div>
      <div className="divider">
        <span className="seam" />
        <span className="pill">Comparaison</span>
        <span className="arrow-btn">→</span>
      </div>
    </SourceSlide>
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
