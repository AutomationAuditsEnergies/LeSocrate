import React, { useLayoutEffect, useRef, useState } from 'react';
import './DeckTemplates.css';
import { SalesHackingSourceSlide } from './SalesHackingSourceSlides';

const splitTitle = (title = '', fallback = '') => String(title || fallback).split(/\s+/);

const getChapterTitleFit = (chapterLabel = '', title = '') => {
  const text = `${chapterLabel || ''} ${title || ''}`.trim();
  const words = splitTitle(text).filter(Boolean);
  const wordCount = words.length;
  const charCount = Array.from(text).length;
  const longestWord = words.reduce((max, word) => Math.max(max, Array.from(word).length), 0);

  let fontSize = 76;
  if (wordCount >= 13 || charCount >= 86 || longestWord >= 22) {
    fontSize = 44;
  } else if (wordCount >= 11 || charCount >= 72 || longestWord >= 18) {
    fontSize = 48;
  } else if (wordCount >= 9 || charCount >= 58) {
    fontSize = 50;
  } else if (wordCount >= 7 || charCount >= 46) {
    fontSize = 62;
  }

  return {
    fontSize,
    shouldWrap: wordCount >= 13 || charCount >= 86 || longestWord >= 22,
  };
};

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

const svgTextLines = (value = '', maxChars = 24, maxLines = 2) => {
  const words = String(value || '').split(/\s+/).filter(Boolean);
  const lines = [];
  let current = '';
  words.forEach((word) => {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length > maxChars && current) {
      lines.push(current);
      current = word;
    } else {
      current = candidate;
    }
  });
  if (current) lines.push(current);
  if (lines.length <= maxLines) return lines;
  const lineCount = Math.max(1, maxLines);
  const targetLength = Math.ceil(words.join(' ').length / lineCount);
  const balanced = [];
  current = '';
  words.forEach((word) => {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length > targetLength && current && balanced.length < lineCount - 1) {
      balanced.push(current);
      current = word;
    } else {
      current = candidate;
    }
  });
  if (current) balanced.push(current);
  return balanced;
};

const svgTitleBlock = (value = '', fallback = '', maxChars = 28) => {
  const text = String(value || fallback || '').trim();
  const lines = svgTextLines(text, maxChars, 3);
  const length = text.length;
  const fontSize = length > 68 ? 18 : length > 56 ? 20 : length > 42 ? 22 : 26;
  return {
    lines,
    fontSize,
    lineGap: Math.round(fontSize * 1.2),
  };
};

const shortenSvgText = (value = '', maxChars = 64) => {
  const clean = String(value || '').trim();
  return clean.length > maxChars ? `${clean.slice(0, maxChars - 1)}…` : clean;
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
  const titleFit = getChapterTitleFit(chapter_label, title);
  const safeAxes = (Array.isArray(sourceAxes) && sourceAxes.length ? sourceAxes : [
    { title, desc: 'Le repère principal à retenir dans cette séquence.' },
  ]).slice(0, 3);

  return (
    <div className="deck-chapter-shell" ref={shellRef}>
      <section className="deck-chapter-stage" style={{ transform: `scale(${scale})` }}>
        {deckChrome(brandName)}
        <div className="deck-chapter-left">
          <h1
            className={titleFit.shouldWrap ? 'deck-chapter-title--wrap' : undefined}
            style={{
              '--chapter-title-size': `${titleFit.fontSize}px`,
            }}
          >
            <span className="deck-chapter-label">{chapter_label}</span> <span className="deck-chapter-name">{title}</span>
          </h1>
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
  title = 'Parcours annuel.',
  subtitle = 'Deux grands ensembles de compétences qui se complètent.',
  day_label = "Programme de l'année",
  phases = [],
  items = [],
  brandName = 'Sales hacking',
}) => {
  const sourcePhases = Array.isArray(phases) && phases.length ? phases : items;
  const safePhases = (Array.isArray(sourcePhases) && sourcePhases.length ? sourcePhases : [
    { title: 'Premier ensemble', desc: 'Installer les repères essentiels du parcours.' },
    { title: 'Deuxième ensemble', desc: 'Mettre les compétences en action.' },
  ]).slice(0, 2);
  const phaseOne = safePhases[0] || {};
  const phaseTwo = safePhases[1] || {};
  const phaseOneTitle = typeof phaseOne === 'string' ? phaseOne : phaseOne.title;
  const phaseTwoTitle = typeof phaseTwo === 'string' ? phaseTwo : phaseTwo.title;
  const phaseOneDesc = typeof phaseOne === 'string' ? '' : (phaseOne.desc || phaseOne.text || phaseOne.description || '');
  const phaseTwoDesc = typeof phaseTwo === 'string' ? '' : (phaseTwo.desc || phaseTwo.text || phaseTwo.description || '');
  const phaseOneBlock = svgTitleBlock(phaseOneTitle, 'Assistance et relation client', 28);
  const phaseTwoBlock = svgTitleBlock(phaseTwoTitle, 'Actions commerciales', 28);
  const displayedTitle = 'Parcours annuel.';
  const displayedDayLabel = "Programme de l'année";
  const topTitleStartY = 104 - ((phaseOneBlock.lines.length - 1) * phaseOneBlock.lineGap) / 2;
  const bottomTitleStartY = 650 - ((phaseTwoBlock.lines.length - 1) * phaseTwoBlock.lineGap) / 2;

  return (
    <SourceSlide className="s-prog-year">
      {sourceChrome(brandName)}
      <div className="py-head">
        <span className="eyebrow">— {displayedDayLabel || day_label}</span>
        <h1>{renderAccentLastWord(displayedTitle || title, 'Parcours annuel.')}</h1>
        {subtitle && <p className="sub">{subtitle}</p>}
      </div>

      <svg className="py-svg-road" viewBox="0 0 1920 760" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
        <path d="M 0,380 C 160,380 340,220 520,220 C 700,220 860,380 1000,380 C 1140,380 1340,510 1560,510 C 1680,510 1820,380 1920,380" stroke="rgba(0,0,20,0.55)" strokeWidth="120" fill="none" strokeLinecap="round" />
        <path d="M 0,380 C 160,380 340,220 520,220 C 700,220 860,380 1000,380 C 1140,380 1340,510 1560,510 C 1680,510 1820,380 1920,380" stroke="#162060" strokeWidth="104" fill="none" strokeLinecap="round" />
        <path d="M 0,380 C 160,380 340,220 520,220 C 700,220 860,380 1000,380 C 1140,380 1340,510 1560,510 C 1680,510 1820,380 1920,380" stroke="rgba(255,255,255,0.12)" strokeWidth="104" fill="none" strokeLinecap="round" />
        <path d="M 0,380 C 160,380 340,220 520,220 C 700,220 860,380 1000,380 C 1140,380 1340,510 1560,510 C 1680,510 1820,380 1920,380" stroke="rgba(255,255,255,0.65)" strokeWidth="5" fill="none" strokeDasharray="36 22" strokeLinecap="round" />

        <rect x="268" y="16" width="504" height="150" rx="14" fill="rgba(255,255,255,0.07)" stroke="rgba(255,255,255,0.15)" strokeWidth="1.5" />
        <rect x="268" y="16" width="5" height="150" rx="3" fill="#ff5d6c" />
        <text x="284" y="44" fontFamily="'JetBrains Mono',monospace" fontSize="15" fill="#ff5d6c" letterSpacing="3">PHASE 01</text>
        <text textAnchor="middle" fill="white" fontFamily="'Archivo Black',sans-serif">
          {phaseOneBlock.lines.map((line, index) => (
            <tspan x="522" y={topTitleStartY + index * phaseOneBlock.lineGap} fontSize={phaseOneBlock.fontSize} key={line}>{line}</tspan>
          ))}
        </text>
        <text x="284" y="151" fontFamily="Manrope,sans-serif" fontSize="19" fill="rgba(255,255,255,0.60)">{shortenSvgText(phaseOneDesc, 70)}</text>
        <line x1="520" y1="170" x2="520" y2="178" stroke="rgba(255,255,255,0.3)" strokeWidth="2" strokeDasharray="5 4" />
        <circle cx="520" cy="220" r="64" fill="rgba(255,93,108,0.10)" />
        <circle cx="520" cy="220" r="50" fill="none" stroke="rgba(255,93,108,0.35)" strokeWidth="2" />
        <circle cx="520" cy="220" r="40" fill="#ff5d6c" />
        <circle cx="520" cy="220" r="40" fill="none" stroke="rgba(255,255,255,0.22)" strokeWidth="4" />
        <text x="520" y="234" textAnchor="middle" fontFamily="'Archivo Black',sans-serif" fontSize="34" fontWeight="900" fill="white" letterSpacing="-0.5">01</text>

        <circle cx="1560" cy="510" r="64" fill="rgba(255,93,108,0.10)" />
        <circle cx="1560" cy="510" r="50" fill="none" stroke="rgba(255,93,108,0.35)" strokeWidth="2" />
        <circle cx="1560" cy="510" r="40" fill="#ff5d6c" />
        <circle cx="1560" cy="510" r="40" fill="none" stroke="rgba(255,255,255,0.22)" strokeWidth="4" />
        <text x="1560" y="524" textAnchor="middle" fontFamily="'Archivo Black',sans-serif" fontSize="34" fontWeight="900" fill="white" letterSpacing="-0.5">02</text>
        <line x1="1560" y1="554" x2="1560" y2="562" stroke="rgba(255,255,255,0.3)" strokeWidth="2" strokeDasharray="5 4" />
        <rect x="1308" y="564" width="504" height="150" rx="14" fill="rgba(255,255,255,0.07)" stroke="rgba(255,255,255,0.15)" strokeWidth="1.5" />
        <rect x="1308" y="564" width="5" height="150" rx="3" fill="#ff5d6c" />
        <text x="1324" y="592" fontFamily="'JetBrains Mono',monospace" fontSize="15" fill="#ff5d6c" letterSpacing="3">PHASE 02</text>
        <text textAnchor="middle" fill="white" fontFamily="'Archivo Black',sans-serif">
          {phaseTwoBlock.lines.map((line, index) => (
            <tspan x="1562" y={bottomTitleStartY + index * phaseTwoBlock.lineGap} fontSize={phaseTwoBlock.fontSize} key={line}>{line}</tspan>
          ))}
        </text>
        <text x="1324" y="704" fontFamily="Manrope,sans-serif" fontSize="19" fill="rgba(255,255,255,0.60)">{shortenSvgText(phaseTwoDesc, 70)}</text>
      </svg>
    </SourceSlide>
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

const sourceTitleParts = (value = '', fallback = 'Point clé') => {
  const clean = String(value || fallback).trim();
  if (clean.includes('\n')) {
    const lines = clean.split(/\n+/).filter(Boolean);
    return { first: lines.slice(0, -1).join(' '), accent: lines[lines.length - 1] || clean };
  }
  const selon = clean.match(/^(.+?)\s+(selon\s+.+)$/i);
  if (selon) return { first: selon[1], accent: selon[2] };
  const comma = clean.match(/^(.+?,)\s+(.+)$/);
  if (comma) return { first: comma[1], accent: comma[2] };
  const colon = clean.match(/^(.+?:)\s+(.+)$/);
  if (colon) return { first: colon[1], accent: colon[2] };
  const words = clean.split(/\s+/).filter(Boolean);
  if (words.length <= 3) return { first: clean, accent: '' };
  const pivot = Math.ceil(words.length / 2);
  return { first: words.slice(0, pivot).join(' '), accent: words.slice(pivot).join(' ') };
};

const SourceAccentTitle = ({ title, fallback = 'Point clé' }) => {
  const { first, accent } = sourceTitleParts(title, fallback);
  if (!accent) return <>{first}</>;
  return <>{first}<br /><span className="crl">{accent}</span></>;
};

const formatSourceQuote = (value = '') => {
  const clean = String(value || '').trim();
  if (!clean) return '';
  if (/^[«"“]/.test(clean)) return clean;
  return `« ${clean} »`;
};

const sourceItems = (items, fallback, limit) => {
  const source = Array.isArray(items) && items.length ? items : fallback;
  return source.slice(0, limit);
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

export const DeckDefinition = ({ term, title, eyebrow = 'Définition', definition, text, isItems = [], brandName }) => {
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

export const DeckProcess = ({ title = 'Les étapes clés', steps = [], brandName }) => {
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

export const DeckStory = ({ title = 'Cas terrain', narrative, moral, text, brandName }) => (
  <SourceSlide className="s-board">
    {sourceChrome(brandName)}
    <div className="meta">
      <span className="num">STORY</span>
      <span className="bar" />
      <span className="chapter">{title}</span>
    </div>

    <div className="chalkboard">
      <div className="board-inner">
        <div className="ch-lines">
          <p className="ch-para">{narrative || text || 'Un exemple concret pour ancrer le point clé.'}</p>
        </div>
      </div>
      <div className="tray">
        <span className="chalk w" />
        <span className="chalk y" />
        <span className="chalk p" />
        <span className="eraser" />
      </div>
    </div>

    {(moral || text) && (
      <div className="board-morale">
        <span className="lbl">↳ Morale</span>
        <span className="text">{moral || text}</span>
      </div>
    )}
  </SourceSlide>
);

export const DeckAnalogy = ({ title = 'Analogie', concept = 'Concept', comparison = 'Image mentale', text, brandName }) => (
  <SourceSlide className="s-analogy">
    {sourceChrome(brandName)}
    <div className="an-diag" />
    <div className="an-left">
      <span className="an-tag">— Le concept</span>
      <h2 className="an-name">{concept || title}</h2>
      <p className="an-text">{text || 'La notion à comprendre dans la situation professionnelle.'}</p>
    </div>
    <div className="an-right">
      <span className="an-tag">— L'analogie</span>
      <h2 className="an-name">{comparison}</h2>
      <p className="an-text">{text || 'Une image mentale pour rendre la notion plus facile à retenir.'}</p>
    </div>
  </SourceSlide>
);

export const DeckOpinion = ({ title = 'Point de vue', text, brandName }) => (
  <SourceSlide className="s-opinion">
    {sourceChrome(brandName)}
    <span className="quote-bg">"</span>
    <div className="l">
      <span className="badge">POINT DE VUE</span>
      <h1><SourceAccentTitle title={title} fallback="Point de vue" /></h1>
    </div>
    <div className="r">
      <p>{text || 'Une prise de position pédagogique pour structurer la suite du raisonnement.'}</p>
    </div>
  </SourceSlide>
);

export const DeckQuote = ({ quote, title, text, brandName }) => (
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

export const DeckFramework = ({ title = 'Cadre de lecture', center = {}, segments = [], items = [], brandName }) => {
  const sourceSegments = Array.isArray(segments) && segments.length ? segments : items;
  const safeSegments = (Array.isArray(sourceSegments) && sourceSegments.length ? sourceSegments : [
    { title: 'Repère 1', desc: 'Premier point de lecture.' },
    { title: 'Repère 2', desc: 'Deuxième point de lecture.' },
    { title: 'Repère 3', desc: 'Troisième point de lecture.' },
    { title: 'Repère 4', desc: 'Quatrième point de lecture.' },
  ]).slice(0, 6);
  const frameworkClass = safeSegments.length > 4 ? 's-fw tpl six' : 's-fw tpl';
  return (
    <SourceSlide className={frameworkClass}>
      {sourceChrome(brandName)}
      <div className="head">
        <span className="eyebrow">— Modèle d'analyse</span>
        <h1><SourceAccentTitle title={title} fallback="Cadre de lecture" /></h1>
      </div>
      <div className="wheel">
        <svg className="dial" viewBox="0 0 260 260" aria-hidden="true">
          <circle cx="130" cy="130" r="120" fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="2" />
          <g fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="1.5">
            <line x1="130" y1="10" x2="130" y2="250" />
            <line x1="10" y1="130" x2="250" y2="130" />
          </g>
          <g fill="rgba(255,93,108,0.25)" stroke="var(--coral)" strokeWidth="2">
            <path d="M 130 130 L 130 20 A 110 110 0 0 1 240 130 Z" />
          </g>
        </svg>
        <div className="center">{center.title || center.label || 'Point central'}</div>
        {safeSegments.map((segment, index) => (
          <div className={`sat s${index + 1}`} key={index}>
            <div className="t">{typeof segment === 'string' ? segment : segment.title}</div>
            {typeof segment !== 'string' && (segment.desc || segment.text) && <div className="d">{segment.desc || segment.text}</div>}
          </div>
        ))}
      </div>
    </SourceSlide>
  );
};

export const DeckRecap = ({ title = "Ce qu'on retient.", points = [], brandName }) => {
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
  ]).slice(0, 3);
  const colClass = safeCases.length <= 2 ? 'cols-2' : (safeCases.length === 3 ? 'cols-3' : 'cols-many');
  const accents = ['accent-coral', 'accent-gold', 'accent-green', 'accent-blue'];

  return (
    <SourceSlide className="s-casestudy">
      {sourceChrome(brandName)}
      <div className="cs-head">
        <span className="eyebrow">— {eyebrow}</span>
        <h1><SourceAccentTitle title={title} fallback="Cas terrain" /></h1>
      </div>

      <div className={`cs-cards ${colClass} paper`}>
        {safeCases.map((item, i) => {
          const caseTitle = typeof item === 'string' ? item : item.title;
          const caseDesc = typeof item === 'string' ? '' : (item.desc || item.description || item.text || '');
          const caseTag = typeof item === 'string' ? '' : (item.tag || item.label || `${String(i + 1).padStart(2, '0')} · Cas`);
          const caseExample = typeof item === 'string' ? '' : (item.example || item.quote || '');
          return (
            <article className={`cs-card ${accents[i % accents.length]}`} key={i}>
              <div className="cs-stripe" />
              <div className="cs-body">
                <span className="cs-tag">{caseTag}</span>
                <h3 className="cs-title">{caseTitle}</h3>
                <div className="cs-sep" />
                {caseDesc && <p className="cs-text">{caseDesc}</p>}
                {caseExample && <span className="cs-example">{formatSourceQuote(caseExample)}</span>}
              </div>
            </article>
          );
        })}
      </div>
    </SourceSlide>
  );
};

const FlowIcon = ({ index }) => {
  if (index === 0) {
    return (
      <svg viewBox="0 0 64 64" fill="none" stroke="#1a1f3a" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="32" cy="32" r="24" />
        <circle cx="32" cy="32" r="14" />
        <circle cx="32" cy="32" r="4" fill="#1a1f3a" />
      </svg>
    );
  }
  if (index === 1) {
    return (
      <svg viewBox="0 0 64 64" fill="none" stroke="#1a1f3a" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="32" cy="32" r="9" />
        <path d="M32 8 v8 M32 48 v8 M8 32 h8 M48 32 h8 M15 15 l6 6 M43 43 l6 6 M15 49 l6 -6 M43 21 l6 -6" />
      </svg>
    );
  }
  if (index === 2) {
    return (
      <svg viewBox="0 0 64 64" fill="#1a1f3a" stroke="#1a1f3a" strokeWidth="3" strokeLinejoin="round" aria-hidden="true">
        <polygon points="36,6 14,36 30,36 26,58 50,26 34,26" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 64 64" fill="none" stroke="#1a1f3a" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="16" y1="8" x2="16" y2="58" />
      <path d="M16 12 L48 12 L42 22 L48 32 L16 32 Z" fill="#1a1f3a" stroke="none" />
    </svg>
  );
};

export const DeckSituations = ({ title = 'Trois situations client.', eyebrow = 'Adapter sa posture', items = [], cases = [], brandName }) => {
  const safeItems = sourceItems(
    Array.isArray(items) && items.length ? items : cases,
    [
      { title: 'Client pressé.', desc: "Prioriser l'essentiel et aller droit au résultat." },
      { title: 'Client hésitant.', desc: 'Clarifier le besoin avant de proposer quoi que ce soit.' },
      { title: 'Client mécontent.', desc: "Traiter l'émotion avant la procédure." },
    ],
    3,
  );
  const classes = ['a', 'b', 'c'];

  return (
    <SourceSlide className="s-situ">
      {sourceChrome(brandName)}
      <div className="heading">
        <span className="eyebrow">— {eyebrow}</span>
        <h1><SourceAccentTitle title={title} fallback="Trois situations client." /></h1>
      </div>

      <div className="cards">
        {safeItems.map((item, index) => {
          const itemTitle = typeof item === 'string' ? item : item.title;
          const itemDesc = typeof item === 'string' ? '' : (item.desc || item.description || item.text || '');
          return (
            <div className={`card ${classes[index]}`} key={index}>
              <div className="stamp">SITUATION · {String.fromCharCode(65 + index)}</div>
              <div className="t">{itemTitle}</div>
              <div className="d">{itemDesc}</div>
              <div className="badge">{index + 1}</div>
            </div>
          );
        })}
      </div>
    </SourceSlide>
  );
};

export const DeckFlow = ({ title = 'Traiter une demande.', eyebrow = 'Le flux en quatre temps', steps = [], items = [], brandName }) => {
  const safeSteps = sourceItems(
    Array.isArray(steps) && steps.length ? steps : items,
    [
      { title: 'Identifier', desc: 'Comprendre le besoin exprimé.' },
      { title: 'Qualifier', desc: 'Vérifier les contraintes utiles.' },
      { title: 'Agir', desc: 'Proposer une réponse concrète.' },
      { title: 'Clore', desc: 'Confirmer la suite avec précision.' },
    ],
    4,
  );

  return (
    <SourceSlide className="s-flow">
      {sourceChrome(brandName)}
      <div className="head">
        <span className="eyebrow">— {eyebrow}</span>
        <h1><SourceAccentTitle title={title} fallback="Traiter une demande." /></h1>
      </div>

      <div className="row">
        {safeSteps.map((step, index) => {
          const stepTitle = typeof step === 'string' ? step : step.title;
          const stepDesc = typeof step === 'string' ? '' : (step.desc || step.description || step.text || '');
          return (
            <React.Fragment key={index}>
              <div className="step">
                <div className={`tile c${index + 1}`}>
                  <FlowIcon index={index} />
                </div>
                <div className="t">{stepTitle}</div>
                <div className="d">{stepDesc}</div>
              </div>
              {index < safeSteps.length - 1 && (
                <div className="arrow">
                  <svg viewBox="0 0 70 36" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <line x1="6" y1="18" x2="60" y2="18" />
                    <polyline points="48,6 62,18 48,30" />
                  </svg>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </SourceSlide>
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

export const DeckTip = ({ title = 'Conseil pratique', text, brandName }) => (
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

export const DeckComparison = ({ title = 'Avant vs après.', cols = [], rows = [], brandName }) => {
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
