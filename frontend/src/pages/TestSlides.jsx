import { useEffect, useState } from 'react';

import { SalesHackingSourceSlide, SOURCE_SLIDE_INDEX } from '../components/slides/templates/SalesHackingSourceSlides';
import './TestSlides.css';

const TEMPLATE_USAGE = {
  welcome: {
    templateId: 'welcome',
    description: "Installer le cadre d'ouverture d'une journée ou d'une grande séquence.",
    useCases: ['accueil de journée', 'ouverture majeure', 'lancement de séquence'],
    useWhen: "Le passage accueille les apprenants au début d'une journée ou d'une séquence majeure.",
    avoidWhen: 'Le passage introduit une notion, un thème, un exercice ou une transition sans accueil explicite.',
  },
  program_year: {
    templateId: 'program_year',
    description: 'Donner une vision annuelle courte des deux grandes phases de la formation.',
    useCases: ['vision annuelle', '2 grandes phases', 'parcours long'],
    useWhen: 'Le passage présente le parcours annuel ou les deux grands blocs de compétences.',
    avoidWhen: "Le passage annonce seulement les thèmes d'une journée ou développe une méthode précise.",
  },
  day_program_7_steps: {
    templateId: 'day_program_7_steps',
    description: 'Afficher une feuille de route complète en sept étapes.',
    useCases: ['programme journée', '7 thèmes exacts', 'feuille de route'],
    useWhen: "Le passage annonce explicitement les sept grands thèmes d'une journée complète.",
    avoidWhen: 'Le passage donne moins ou plus de sept parties, ou seulement une liste de conseils.',
  },
  chapter_opener: {
    templateId: 'chapter_opener',
    description: 'Ouvrir un chapitre ou un grand thème avec son titre et ses axes principaux.',
    useCases: ['nouveau chapitre', 'nouveau thème', 'objectif + axes'],
    useWhen: 'Le passage annonce un nouveau chapitre, un nouveau thème, son objectif ou ses axes.',
    avoidWhen: 'Le passage est un récap, une méthode détaillée, une checklist ou un exemple.',
  },
  reflection: {
    templateId: 'reflection',
    description: 'Mettre en avant une idée centrale, une nuance ou un principe mémorisable.',
    useCases: ['idée centrale', 'principe clé', 'phrase forte'],
    useWhen: 'Le passage contient une idée courte qui peut tenir en une phrase forte.',
    avoidWhen: 'Le passage contient une méthode, une comparaison, un cas terrain ou plusieurs points.',
  },
  definition: {
    templateId: 'definition',
    description: 'Définir une notion métier avec quelques critères de reconnaissance.',
    useCases: ['définition', 'vocabulaire', 'distinction de terme'],
    useWhen: 'Le passage pose une définition, un terme ou une distinction de vocabulaire nécessaire.',
    avoidWhen: 'Le passage donne seulement un conseil pratique ou une opinion.',
  },
  comparison: {
    templateId: 'comparison',
    description: 'Comparer deux familles, états, postures, options ou comportements pour faire apparaître leurs attentes différentes.',
    useCases: ['comparaison 2 colonnes', 'synchrone vs asynchrone', 'deux familles', 'avant / après', 'diagnostic opposé'],
    useWhen: "Le passage oppose explicitement deux familles ou deux modes, par exemple synchrone/asynchrone, téléphone/courriel, immédiat/différé, rapidité/exhaustivité, d'un côté/de l'autre.",
    avoidWhen: 'Le passage définit seulement un terme sans opposition opérationnelle, raconte un cas concret, suit une chronologie ou donne une simple liste.',
  },
  warning: {
    templateId: 'warning',
    description: 'Signaler un piège, une erreur fréquente ou un risque métier.',
    useCases: ['piège', 'erreur fréquente', 'risque', 'mauvaise pratique'],
    useWhen: 'Le passage signale une erreur, un risque, une confusion, une expression interdite ou une mauvaise pratique à éviter.',
    avoidWhen: "Le passage donne un conseil positif sans danger clair. S'il liste exactement trois mots ou expressions à bannir, préfère `situations`.",
  },
  casestudy: {
    templateId: 'casestudy',
    description: 'Comparer plusieurs cas métier concrets dans une même logique.',
    useCases: ['2 à 4 cas comparables', 'canaux', 'variantes métier'],
    useWhen: 'Le passage met en regard 2 à 4 cas concrets comparables, canaux, variantes ou situations métier contextualisées.',
    avoidWhen: 'Le passage raconte un seul cas pour amener un conseil, une astuce ou un réflexe métier : préfère tip. Le passage raconte un seul cas avec une morale narrative : préfère story. Le passage pose une triade conceptuelle comme trois piliers, trois repères, trois profils, trois postures ou trois expressions : préfère situations.',
  },
  steps: {
    templateId: 'steps',
    description: 'Transformer une méthode ou procédure en étapes actionnables.',
    useCases: ['procédure', '2 à 4 étapes', 'méthode ordonnée'],
    useWhen: "Le passage présente un enchaînement, une procédure ou des étapes d'action.",
    avoidWhen: "Le contenu n'a pas au moins deux étapes distinctes ou n'indique aucun ordre.",
  },
  recap: {
    templateId: 'recap',
    description: 'Regrouper plusieurs points à retenir ou réflexes pratiques après un développement.',
    useCases: ['synthèse finale', 'points à retenir', 'après développement'],
    useWhen: 'Le passage donne plusieurs points de synthèse, contrôles ou repères à retenir après avoir traité un chapitre.',
    avoidWhen: "Le contenu introduit une structure nouvelle en trois piliers, trois repères, trois profils, trois postures, trois situations ou trois expressions. Ce n'est pas une synthèse finale : préfère situations.",
  },
  reprise_recap: {
    templateId: 'reprise_recap',
    description: "Remettre en mémoire quelques repères déjà vus avant d'ouvrir le nouveau thème.",
    useCases: ['reprise de début de cours', 'rappel chapitre précédent', 'pont vers la suite'],
    useWhen: "Le passage arrive au début d'un cours après le premier et rappelle brièvement 2 à 4 repères de la séquence précédente avant de faire le lien avec la suite.",
    avoidWhen: "Le passage conclut ce qui vient d'être traité : utilise recap. Le passage annonce directement un nouveau thème avec objectif et axes : utilise chapter_opener.",
  },
  pause: {
    templateId: 'pause',
    description: 'Marquer une pause explicite dans une journée animée.',
    useCases: ['pause explicite', 'respiration journée', 'coupure animée'],
    useWhen: 'Le passage annonce explicitement une pause.',
    avoidWhen: 'Le passage fait une simple respiration rhétorique.',
  },
  qa: {
    templateId: 'qa',
    description: 'Ouvrir un temps de questions-réponses.',
    useCases: ['questions-réponses', 'invitation au tchat', 'temps échange'],
    useWhen: 'Le passage invite explicitement les apprenants à poser des questions.',
    avoidWhen: 'Le passage mentionne une question de façon rhétorique dans un développement.',
  },
  quotable: {
    templateId: 'quotable',
    description: "Ancrer dans l'esprit des apprenants une phrase exacte qui doit devenir un repère professionnel.",
    useCases: ['maxime à ancrer', 'phrase clé', 'citation courte', 'repère mémorisable', 'formule à isoler'],
    useWhen: "Le passage introduit explicitement une maxime, une phrase clé, une formule ou un repère à retenir, surtout avec des signaux comme « la voici », « phrase à retenir », « maxime », « repère », « souvenez-vous ».",
    avoidWhen: "Le passage explique surtout une scène, une expérience client ou un exemple narratif sans phrase exacte à isoler. Dans ce cas, préfère story.",
  },
  tip: {
    templateId: 'tip',
    description: 'Mettre en avant un conseil pratique immédiatement applicable.',
    useCases: ['conseil pratique', 'réflexe métier', 'bonne pratique', 'un cas qui amène une astuce'],
    useWhen: "Le passage donne une astuce, un réflexe métier ou une bonne pratique concrète, même s'il commence par un seul cas fictif pour faire comprendre le conseil.",
    avoidWhen: 'Le passage compare plusieurs cas métier entre eux : préfère casestudy. Le passage est surtout un récit avec morale : préfère story. Le passage est théorique ou centré sur un risque à éviter.',
  },
  situations: {
    templateId: 'situations',
    description: 'Présenter une triade fermée qui structure une notion : trois piliers, trois profils, trois postures, trois situations ou trois expressions.',
    useCases: ['3 piliers', 'triade structurante', '3 profils', '3 postures', '3 expressions à distinguer'],
    useWhen: "Le passage annonce explicitement trois éléments indissociables avec des signaux comme « trois piliers », « les trois », « les voici », « trépied », « triptyque », « trois profils », « trois postures » ou « trois expressions ».",
    avoidWhen: 'Le passage compare des cas métier contextualisés en cartes, avec des scènes ou canaux concrets : préfère casestudy. Le passage synthétise un chapitre déjà traité : préfère recap.',
  },
  flow: {
    templateId: 'flow',
    description: 'Afficher deux à quatre gestes métier enchaînés avec une logique opérationnelle.',
    useCases: ['2 à 4 gestes métier', 'flux opérationnel', 'actions successives'],
    useWhen: "Le passage décrit 2 à 4 actions successives qu'un apprenant doit appliquer dans l'ordre.",
    avoidWhen: 'Le passage est un modèle conceptuel, une simple liste de conseils ou une progression sans action métier.',
  },
  story: {
    templateId: 'story',
    description: 'Transformer une phrase clé ou un principe en scène concrète pour montrer pourquoi il compte.',
    useCases: ["déclinaison narrative d'une maxime", 'mini-récit', 'situation vécue', 'expérience client', 'morale pédagogique'],
    useWhen: "Le passage développe une expérience vécue, une scène client, une mise en situation ou une conséquence concrète qui donne du sens à une maxime ou à un principe.",
    avoidWhen: "Le passage sert d'abord à faire mémoriser une phrase exacte. Dans ce cas, préfère quotable; story peut venir ensuite si le texte raconte une scène qui illustre cette phrase.",
  },
  analogy: {
    templateId: 'analogy',
    description: 'Expliquer une notion abstraite par une image mentale familière.',
    useCases: ['image mentale', 'métaphore utile', 'comparaison hors métier'],
    useWhen: 'Le passage compare une notion à une image, un objet ou une situation connue pour aider la compréhension.',
    avoidWhen: "La comparaison est seulement décorative ou relève d'un exemple métier concret.",
  },
  framework: {
    templateId: 'framework',
    description: 'Présenter un modèle conceptuel avec un centre et plusieurs leviers ou dimensions.',
    useCases: ['modèle conceptuel', '4 à 6 leviers', 'dimensions multiples'],
    useWhen: "Le passage présente un cadre d'analyse avec 4 à 6 forces, leviers ou dimensions autour d'une idée centrale.",
    avoidWhen: 'Le passage présente exactement trois piliers, trois repères ou trois postures : préfère situations. Le passage est une procédure linéaire, une checklist ou une série de cas terrain.',
  },
  opinion: {
    templateId: 'opinion',
    description: 'Isoler une prise de position pédagogique argumentée.',
    useCases: ['point de vue formateur', 'prise de position', 'thèse argumentée'],
    useWhen: 'Le passage affirme un point de vue de formateur qui structure la suite du raisonnement.',
    avoidWhen: 'Le passage est une simple phrase forte sans argument, à traiter plutôt en quotable.',
  },
};

const SLIDES = SOURCE_SLIDE_INDEX.map((slide) => ({
  label: `${slide.label.replace('&amp;', '&')} · ${slide.isVariant ? 'variante' : 'exact'}`,
  sourceId: slide.id,
  usage: TEMPLATE_USAGE[slide.templateId || slide.id],
}));

const USAGE_STORAGE_KEY = 'socrate-test-slides-usage-rules-v5';

const ruleList = (value) => {
  if (Array.isArray(value)) return value.length ? value : [''];
  return value ? [value] : [''];
};

const getInitialDraftForSlide = (usage) => ({
  description: usage?.description || '',
  keywords: ruleList(usage?.keywords || usage?.useCases),
  useWhen: ruleList(usage?.useWhen),
  avoidWhen: ruleList(usage?.avoidWhen),
});

export default function TestSlides() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isUsagePanelOpen, setIsUsagePanelOpen] = useState(false);
  const [usageDrafts, setUsageDrafts] = useState(() => {
    if (typeof window === 'undefined') return {};
    try {
      return JSON.parse(window.localStorage.getItem(USAGE_STORAGE_KEY) || '{}') || {};
    } catch {
      return {};
    }
  });
  const item = SLIDES[currentIndex];
  const usage = item.usage;
  const editableUsage = usage ? {
    ...usage,
    description: usageDrafts[item.sourceId]?.description ?? usage.description ?? '',
    keywords: usageDrafts[item.sourceId]?.keywords || ruleList(usage.keywords || usage.useCases),
    useWhen: usageDrafts[item.sourceId]?.useWhen || ruleList(usage.useWhen),
    avoidWhen: usageDrafts[item.sourceId]?.avoidWhen || ruleList(usage.avoidWhen),
  } : null;

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(USAGE_STORAGE_KEY, JSON.stringify(usageDrafts));
  }, [usageDrafts]);

  const updateRule = (kind, index, value) => {
    setUsageDrafts((current) => {
      const currentDraft = current[item.sourceId] || getInitialDraftForSlide(usage);
      const nextRules = ruleList(currentDraft[kind]).map((rule, ruleIndex) => (
        ruleIndex === index ? value : rule
      ));
      return {
        ...current,
        [item.sourceId]: {
          ...currentDraft,
          [kind]: nextRules,
        },
      };
    });
  };

  const updateDescription = (value) => {
    setUsageDrafts((current) => {
      const currentDraft = current[item.sourceId] || getInitialDraftForSlide(usage);
      return {
        ...current,
        [item.sourceId]: {
          ...currentDraft,
          description: value,
        },
      };
    });
  };

  const addRule = (kind) => {
    setUsageDrafts((current) => {
      const currentDraft = current[item.sourceId] || getInitialDraftForSlide(usage);
      return {
        ...current,
        [item.sourceId]: {
          ...currentDraft,
          [kind]: [...ruleList(currentDraft[kind]), ''],
        },
      };
    });
  };

  const removeRule = (kind, index) => {
    setUsageDrafts((current) => {
      const currentDraft = current[item.sourceId] || getInitialDraftForSlide(usage);
      const nextRules = ruleList(currentDraft[kind]).filter((_, ruleIndex) => ruleIndex !== index);
      return {
        ...current,
        [item.sourceId]: {
          ...currentDraft,
          [kind]: nextRules.length ? nextRules : [''],
        },
      };
    });
  };

  return (
    <div className="test-slides-page">
      <aside style={{ borderRight: '1px solid #334155', padding: '16px', backgroundColor: '#111827', overflowY: 'auto' }}>
        <div style={{ marginBottom: '16px' }}>
          <div style={{ color: '#a78bfa', fontSize: '10px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase', marginBottom: '4px' }}>
            Aperçu deck
          </div>
          <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 700 }}>
            {SLIDES.length} slides source + variantes
          </h1>
        </div>

        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: '#64748B', marginBottom: '6px', paddingLeft: '4px' }}>
            Deck source exact + variantes
          </div>
          <div style={{ display: 'grid', gap: '4px' }}>
            {SLIDES.map((slide, index) => {
              const active = index === currentIndex;
              return (
                <button
                  key={slide.sourceId}
                  type="button"
                  onClick={() => setCurrentIndex(index)}
                  style={{
                    textAlign: 'left',
                    border: `1px solid ${active ? '#8B5CF6' : '#1e293b'}`,
                    backgroundColor: active ? 'rgba(139,92,246,0.14)' : 'transparent',
                    color: active ? '#f8fafc' : '#94a3b8',
                    borderRadius: '6px',
                    padding: '6px 10px',
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                >
                  <div style={{ fontSize: '12px', fontWeight: active ? 700 : 500 }}>{slide.label}</div>
                  {slide.usage?.templateId && (
                    <div style={{ marginTop: '3px', fontSize: '10px', color: active ? '#c4b5fd' : '#64748b' }}>
                      {slide.usage.templateId}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </aside>

      <main className={`test-slides-main ${isUsagePanelOpen ? 'test-slides-main--panel-open' : 'test-slides-main--panel-collapsed'}`}>
        <div style={{ width: 'min(1200px,100%)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
          <div>
            <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '2px' }}>
              Deck source exact + variantes · {currentIndex + 1}/{SLIDES.length}
            </div>
            <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 700 }}>{item.label}</h2>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              onClick={() => setCurrentIndex(Math.max(0, currentIndex - 1))}
              disabled={currentIndex === 0}
              style={{ padding: '8px 14px', borderRadius: '8px', border: '1px solid #334155', backgroundColor: 'transparent', color: currentIndex === 0 ? '#64748b' : '#f1f5f9', cursor: currentIndex === 0 ? 'not-allowed' : 'pointer', fontFamily: 'inherit', fontWeight: 600 }}
            >
              Préc.
            </button>
            <button
              type="button"
              onClick={() => setCurrentIndex(Math.min(SLIDES.length - 1, currentIndex + 1))}
              disabled={currentIndex === SLIDES.length - 1}
              style={{ padding: '8px 14px', borderRadius: '8px', border: '1px solid #8B5CF6', backgroundColor: currentIndex === SLIDES.length - 1 ? 'transparent' : '#8B5CF6', color: currentIndex === SLIDES.length - 1 ? '#64748b' : '#fff', cursor: currentIndex === SLIDES.length - 1 ? 'not-allowed' : 'pointer', fontFamily: 'inherit', fontWeight: 600 }}
            >
              Suiv.
            </button>
          </div>
        </div>

        {editableUsage && !isUsagePanelOpen && (
          <section className="test-slide-usage-summary" aria-label="Résumé des cas d'usage du template">
            <div>
              <span className="test-slide-kicker">Cas d'usage</span>
              <strong>{editableUsage.templateId}</strong>
              <p>{editableUsage.description}</p>
            </div>
            <div className="test-slide-summary-keywords">
              {editableUsage.keywords.filter(Boolean).slice(0, 4).map((keyword) => (
                <span key={keyword}>{keyword}</span>
              ))}
            </div>
            <button type="button" onClick={() => setIsUsagePanelOpen(true)}>Modifier</button>
          </section>
        )}

        {editableUsage && isUsagePanelOpen && (
          <section className="test-slide-usage-panel" aria-label="Cas d'usage du template">
            <div className="test-slide-usage-head">
              <div>
                <span className="test-slide-kicker">Cas d'usage</span>
                <h3>{editableUsage.templateId}</h3>
              </div>
              <div className="test-slide-usage-actions">
                <span className="test-slide-source-id">{item.sourceId}</span>
                <button type="button" onClick={() => setIsUsagePanelOpen(false)}>Réduire</button>
              </div>
            </div>

            <div className="test-slide-description-block">
              <label htmlFor={`description-${item.sourceId}`}>Description</label>
              <textarea
                id={`description-${item.sourceId}`}
                value={editableUsage.description}
                rows={2}
                placeholder="Décrire le rôle pédagogique global de ce template"
                onChange={(event) => updateDescription(event.target.value)}
              />
            </div>

            <div className="test-slide-keyword-block">
              <div className="test-slide-rule-toolbar test-slide-rule-toolbar--keywords">
                <span>Mots-clés</span>
                <button type="button" onClick={() => addRule('keywords')}>+ Ajouter</button>
              </div>
              <div className="test-slide-keyword-row">
                {editableUsage.keywords.map((keyword, index) => (
                  <div className="test-slide-keyword-edit" key={`keyword-${index}`}>
                    <input
                      type="text"
                      value={keyword}
                      placeholder="mot-clé"
                      onChange={(event) => updateRule('keywords', index, event.target.value)}
                    />
                    <button type="button" aria-label="Supprimer ce mot-clé" onClick={() => removeRule('keywords', index)}>×</button>
                  </div>
                ))}
              </div>
            </div>

            <div className="test-slide-rule-grid">
              <div className="test-slide-rule">
                <div className="test-slide-rule-toolbar">
                  <span>Utiliser quand</span>
                  <button type="button" onClick={() => addRule('useWhen')}>+ Ajouter</button>
                </div>
                <div className="test-slide-rule-list">
                  {editableUsage.useWhen.map((rule, index) => (
                    <div className="test-slide-rule-edit" key={`use-${index}`}>
                      <textarea
                        value={rule}
                        rows={2}
                        placeholder="Ajouter un cas où ce template doit être utilisé"
                        onChange={(event) => updateRule('useWhen', index, event.target.value)}
                      />
                      <button type="button" aria-label="Supprimer cette règle" onClick={() => removeRule('useWhen', index)}>×</button>
                    </div>
                  ))}
                </div>
              </div>
              <div className="test-slide-rule test-slide-rule--avoid">
                <div className="test-slide-rule-toolbar">
                  <span>À éviter</span>
                  <button type="button" onClick={() => addRule('avoidWhen')}>+ Ajouter</button>
                </div>
                <div className="test-slide-rule-list">
                  {editableUsage.avoidWhen.map((rule, index) => (
                    <div className="test-slide-rule-edit" key={`avoid-${index}`}>
                      <textarea
                        value={rule}
                        rows={2}
                        placeholder="Ajouter un cas où ce template ne doit pas être utilisé"
                        onChange={(event) => updateRule('avoidWhen', index, event.target.value)}
                      />
                      <button type="button" aria-label="Supprimer cette règle" onClick={() => removeRule('avoidWhen', index)}>×</button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}

        <div className="test-slide-preview">
          <SalesHackingSourceSlide sourceId={item.sourceId} />
        </div>
      </main>
    </div>
  );
}
