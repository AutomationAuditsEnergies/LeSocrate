import React, { useState } from 'react';

// — Templates existants —
import PlayfulTemplate from '../components/slides/templates/PlayfulTemplate';
import ReflectionTemplate from '../components/slides/templates/ReflectionTemplate';
import CaseStudyTemplate from '../components/slides/templates/CaseStudyTemplate';
import FacilitatorTemplate from '../components/slides/templates/FacilitatorTemplate';
import ChartTemplate from '../components/slides/templates/ChartTemplate';
import StatsTemplate from '../components/slides/templates/StatsTemplate';
import StoryTemplate from '../components/slides/templates/StoryTemplate';
import RecapTemplate from '../components/slides/templates/RecapTemplate';
import AnalogyTemplate from '../components/slides/templates/AnalogyTemplate';
import WarningTemplate from '../components/slides/templates/WarningTemplate';
import TipTemplate from '../components/slides/templates/TipTemplate';
import OpinionTemplate from '../components/slides/templates/OpinionTemplate';
import TransitionTemplate from '../components/slides/templates/TransitionTemplate';
import FrameworkTemplate from '../components/slides/templates/FrameworkTemplate';

// — Nouveaux templates (corpus TP CRCD) —
import ComparisonTemplate from '../components/slides/templates/ComparisonTemplate';
import StepsTemplate from '../components/slides/templates/StepsTemplate';
import ProfilesTemplate from '../components/slides/templates/ProfilesTemplate';
import DefinitionTemplate from '../components/slides/templates/DefinitionTemplate';
import QuotableTemplate from '../components/slides/templates/QuotableTemplate';
import ScriptTemplate from '../components/slides/templates/ScriptTemplate';
import MatrixTemplate from '../components/slides/templates/MatrixTemplate';
import GradientTemplate from '../components/slides/templates/GradientTemplate';
import SignalsTemplate from '../components/slides/templates/SignalsTemplate';
import TimelineTemplate from '../components/slides/templates/TimelineTemplate';
import ChannelAdaptationTemplate from '../components/slides/templates/ChannelAdaptationTemplate';
import BeforeAfterTemplate from '../components/slides/templates/BeforeAfterTemplate';
import ChecklistTemplate from '../components/slides/templates/ChecklistTemplate';
import EscalationLadderTemplate from '../components/slides/templates/EscalationLadderTemplate';
import ToolkitTemplate from '../components/slides/templates/ToolkitTemplate';
import DecisionTreeTemplate from '../components/slides/templates/DecisionTreeTemplate';
import TemperatureScaleTemplate from '../components/slides/templates/TemperatureScaleTemplate';
import KPIExplainerTemplate from '../components/slides/templates/KPIExplainerTemplate';
import SelfDiagTemplate from '../components/slides/templates/SelfDiagTemplate';
import ParadoxTemplate from '../components/slides/templates/ParadoxTemplate';
import LearningPathTemplate from '../components/slides/templates/LearningPathTemplate';
import PracticeExerciseTemplate from '../components/slides/templates/PracticeExerciseTemplate';
import SelfManagementTemplate from '../components/slides/templates/SelfManagementTemplate';
import SignalRadarTemplate from '../components/slides/templates/SignalRadarTemplate';
import { DeckChapterOpener, DeckDayProgram7Steps, DeckPause, DeckProgramYear, DeckQA, DeckWelcome } from '../components/slides/templates/DeckTemplates';

const P = { badge: 'TP-CRCD', brandName: 'SALES HACKING' };

const GROUPS = [
  {
    label: 'Deck fourni',
    items: [
      { type: 'welcome', label: '01 Bienvenue · exact', data: { title: 'Bienvenue', formation_name: 'Titre professionnel CRCD', day_label: 'Journée 1', meta_note: 'Relation client à distance' } },
      { type: 'program_year', label: '02 Programme annuel · deux phases', data: { title: "Programme de l'année.", subtitle: 'Deux grands ensembles de compétences qui se complètent pour tenir toutes les facettes du poste.', day_label: 'Parcours annuel', phases: [{ title: 'Assistance et relation client à distance', desc: 'Accueillir, écouter, comprendre et résoudre les demandes clients, quel que soit le canal utilisé.' }, { title: 'Actions commerciales en relation client à distance', desc: "Identifier un besoin, éveiller un intérêt et proposer une solution adaptée avec éthique et justesse." }] } },
      { type: 'day_program_7_steps', label: '02 Programme journée · exact', data: { title: 'Programme de la journée.', subtitle: "Une journée dédiée aux fondamentaux de l'échange à distance — du premier contact jusqu'à l'empreinte que l'on laisse après.", day_label: 'Feuille de route', active_item: 1, items: ['Communiquer sans visuel', 'Le ton de la voix', 'Le rythme de synchronisation', "Humaniser l'écrit asynchrone", 'La première minute', "L'écoute active", "L'empreinte après contact"] } },
      { type: 'chapter_opener', label: '03 Chapitre 1 · exact', data: { chapter_label: 'Chapitre 1', title: "L'obstacle invisible", axes: [{ title: 'Le brouillard de la distance', desc: 'Quand le client ne voit pas, son cerveau complète.' }, { title: 'Les biais de perception', desc: 'Un silence, un ton ou un rythme devient un message.' }] } },
      { type: 'reflection', label: '05 Reflection · principe clé', data: { title: 'Même intention, autre forme.', text: "L'accueil ne change pas d'objectif selon le canal. Ce qui change, c'est la manière de le faire ressentir.", eyebrow: 'Principe clé' } },
      { type: 'definition', label: '03 Definition', data: { term: 'Opération.', eyebrow: 'Vocabulaire #01', definition: "Un système répétable qui produit un résultat prévisible — sans dépendre d'une personne en particulier.", isItems: ['RÉPÉTABLE', 'MESURABLE', 'DÉLÉGABLE', 'DOCUMENTÉ'] } },
      { type: 'comparison', label: '04 Diagnostic', data: { title: 'Équipe épuisée vs autonome.', cols: [{ label: 'État actuel', items: ['Tout passe par 2 personnes', 'Aucun process écrit', '3h/jour en Slack', 'Erreurs qui se répètent'] }, { label: 'Objectif 7 semaines', items: ['Décisions distribuées', '12 SOPs documentées', 'Slack divisé par 4', 'Erreurs trackées + résolues'] }] } },
      { type: 'warning', label: '05 Mistake', data: { title: 'Automatiser le chaos.', text: "Brancher une IA sur un process bancal multiplie le désordre à la vitesse de la machine. Documentez d'abord, automatisez ensuite." } },
      { type: 'casestudy', label: '06 Case study · cartes comparatives', data: { title: "Les codes d'accueil selon le canal.", eyebrow: 'Analyse comparative', cases: [{ tag: '01 · Téléphone', title: 'La voix en direct', desc: "L'accueil se joue dans les premières secondes. Ton, rythme et articulation remplacent le visuel.", example: 'Bonjour, société X, Amelle, bonjour.' }, { tag: '02 · Email', title: "L'écrit posé", desc: "La formule d'accueil doit être courte et personnalisée. Le client lit en diagonale : le prénom et le motif doivent sauter aux yeux.", example: 'Bonjour [Prénom], suite à votre demande...' }, { tag: '03 · Chat', title: "L'écrit immédiat", desc: "La réponse doit être rapide et fluide. Pas de bloc de texte : une phrase d'accueil, puis une question courte.", example: 'Bonjour ! En quoi puis-je vous aider ?' }] } },
      { type: 'steps', label: '07 Process', data: { title: '4 étapes pour rendre un process délégable.', steps: [{ title: 'Observer', desc: 'Filmer 5 fois la tâche réelle.' }, { title: 'Découper', desc: 'Identifier décisions, actions répétables et exceptions.' }, { title: 'Automatiser', desc: "Brancher l'IA uniquement sur les segments stables." }, { title: 'Mesurer', desc: 'Définir 1 KPI par étape.' }] } },
      { type: 'recap', label: '09 Recap', data: { title: "Ce qu'on retient.", points: ["Process avant outils : l'outil amplifie ce qui existe.", 'Filmer la réalité : observer avant de prescrire.', 'Mesurer ou tâtonner : 1 chiffre par étape.'] } },
      { type: 'pause', label: '11 Pause', data: { title: 'Pause.', duration: '5 minutes.', subtitle: "notez ce qui vous a marqué jusqu'ici." } },
      { type: 'qa', label: '12 Q&A', data: { title: 'On répond à tout.' } },
      { type: 'quotable', label: '14 Quote', data: { quote: "On a doublé la capacité de l'équipe sans recruter. Le secret ? Arrêter de tout faire passer par nous." } },
      { type: 'tip', label: '19 Tip', data: { title: 'Commencer par observer.', text: "Avant d'écrire un seul process, filmez ou notez ce qui se passe vraiment — pas ce que vous croyez qui se passe." } },
    ],
  },
  {
    label: 'Existants',
    items: [
      { type: 'playful', label: 'Playful', data: { title: "Pourquoi l'automatisation est vitale ?", cards: [ { title: 'Gain de temps', desc: 'Libérer les équipes des tâches répétitives.' }, { title: 'Scalabilité', desc: 'Traiter plus de demandes sans augmenter les effectifs.' }, { title: 'Fiabilité', desc: 'Réduire les erreurs et sécuriser les informations.' } ] } },
      { type: 'facilitator', label: 'Facilitator', data: { title: 'Traiter une demande', steps: [ { title: 'Identifier', desc: 'Comprendre le besoin exprimé.', icon: 'target', color: 'orange' }, { title: 'Qualifier', desc: 'Vérifier les contraintes utiles.', icon: 'gear', color: 'purple' }, { title: 'Agir', desc: 'Proposer une réponse concrète.', icon: 'flash', color: 'lime' }, { title: 'Clore', desc: 'Confirmer la suite avec précision.', icon: 'flag', color: 'blue' } ] } },
      { type: 'story', label: 'Story', data: { title: 'Le client qui revient', narrative: "Un client qui répète sa demande signale souvent que la première réponse n'était pas assez claire.", moral: 'La clarté évite la répétition et protège la relation.' } },
      { type: 'analogy', label: 'Analogy', data: { title: 'Le suivi client', concept: 'CRM', comparison: 'Carnet de bord', text: "Comme un carnet de bord, le CRM sert à comprendre ce qui s'est passé et quelle est la prochaine étape." } },
      { type: 'opinion', label: 'Opinion', data: { title: 'La qualité se voit dans les détails', text: 'Une procédure bien suivie ne remplace pas la posture. Les deux doivent avancer ensemble.' } },
      { type: 'framework', label: 'Framework 4', data: { title: 'Les 4 forces de Porter', center: { title: 'Intensité de rivalité entre concurrents' }, segments: [ { title: 'Menace des nouveaux entrants', desc: "Barrières à l'entrée faibles." }, { title: 'Menace des produits de substitution', desc: 'Alternatives plus efficaces.' }, { title: 'Pouvoir de négociation des clients', desc: 'Clients nombreux ou concentrés.' }, { title: 'Pouvoir de négociation des fournisseurs', desc: 'Fournisseurs peu nombreux.' } ] } },
    ],
  },
  {
    label: 'Tier 1 — Critiques',
    items: [
      { type: 'comparison-ternary', label: 'Comparison (ternaire)', data: { title: 'Les 3 postures face au client en difficulté', cols: [ { label: 'Sympathie', color: '#60A5FA', icon: '😢', bg: '#EFF6FF', accent: '#BFDBFE', items: ['"Oh je suis tellement désolé pour vous"', 'Partage émotionnel total', 'Le conseiller perd son objectivité', 'Relation floue, pas de solution'] }, { label: 'Empathie pro', color: '#16A34A', icon: '🎯', bg: '#F0FDF4', accent: '#BBF7D0', items: ['"Je vois que c\'est une situation difficile."', 'Reconnaît l\'émotion sans la partager', 'Posture stable et professionnelle', 'Solution proposée, relation renforcée'] }, { label: 'Neutralité froide', color: '#DC2626', icon: '🤖', bg: '#FEF2F2', accent: '#FECACA', items: ['"Votre numéro de dossier, s\'il vous plaît."', 'Ignore l\'état émotionnel du client', 'Le client se sent comme un ticket', 'Relation détériorée, risque de churn'] } ] } },
      { type: 'steps-mini', label: 'Steps (2 étapes)', data: { title: 'Recadrage cognitif entre deux appels', subtitle: 'Deux secondes suffisent pour repartir sur une page blanche.', steps: [ { title: 'Fermer mentalement', desc: 'Cet échange est terminé. J\'ai fait ce que je pouvais avec ce que j\'avais.' }, { title: 'Page blanche', desc: 'Le prochain client n\'a rien à voir avec le précédent. Recommencer à zéro.' } ] } },
      { type: 'profiles', label: 'Profiles (3 profils)', data: {} },
    ],
  },
  {
    label: 'Tier 2 — Importants',
    items: [
      { type: 'quotable-2', label: 'Quotable (autre)', data: { quote: 'Votre voix est votre premier\ninstrument de confiance.\nPas votre script.', accentColor: '#3FA6A0' } },
      { type: 'script', label: 'Script (dialogue)', data: {} },
      { type: 'matrix', label: 'Matrix', data: {} },
    ],
  },
  {
    label: 'Tier 3 — Utiles',
    items: [
      { type: 'gradient', label: 'Gradient (spectre)', data: {} },
      { type: 'signals', label: 'Signals (détection)', data: {} },
      { type: 'timeline', label: 'Timeline', data: {} },
      { type: 'channel', label: 'Channel Adaptation', data: {} },
      { type: 'beforeafter', label: 'Before/After', data: {} },
      { type: 'escalation', label: 'Escalation Ladder', data: {} },
      { type: 'toolkit', label: 'Toolkit', data: {} },
    ],
  },
  {
    label: 'Tier 4 — Spécialisés',
    items: [
      { type: 'decisiontree', label: 'Decision Tree', data: {} },
      { type: 'temperature', label: 'Temperature Scale', data: {} },
      { type: 'kpi', label: 'KPI Explainer', data: {} },
      { type: 'selfdiag', label: 'Self-Diag', data: {} },
      { type: 'paradox', label: 'Paradox', data: {} },
      { type: 'learningpath', label: 'Learning Path', data: {} },
      { type: 'selfmanagement', label: 'Self Management', data: {} },
      { type: 'signalradar', label: 'Signal Radar', data: {} },
    ],
  },
];

const ALL_ITEMS = GROUPS.flatMap((g, gi) => g.items.map((item, ii) => ({ ...item, groupLabel: g.label, globalIndex: gi * 100 + ii })));

const renderSlide = (item) => {
  const d = item.data || {};
  switch (item.type) {
    // — Existants —
    case 'welcome': return <DeckWelcome {...d} {...P} />;
    case 'program_year':
    case 'day_year': return <DeckProgramYear {...d} {...P} />;
    case 'day_program': return <DeckProgramYear {...d} {...P} />;
    case 'day_program_7_steps': return <DeckDayProgram7Steps {...d} {...P} />;
    case 'chapter_opener': return <DeckChapterOpener {...d} {...P} />;
    case 'pause': return <DeckPause {...d} {...P} />;
    case 'qa': return <DeckQA {...d} {...P} />;
    case 'playful': return <PlayfulTemplate {...d} {...P} />;
    case 'reflection': return <ReflectionTemplate {...d} {...P} />;
    case 'casestudy': return <CaseStudyTemplate {...d} {...P} />;
    case 'facilitator': return <FacilitatorTemplate {...d} {...P} />;
    case 'chart': return <ChartTemplate {...d} {...P} />;
    case 'stats': return <StatsTemplate {...d} {...P} />;
    case 'story': return <StoryTemplate {...d} {...P} />;
    case 'recap': return <RecapTemplate {...d} {...P} />;
    case 'analogy': return <AnalogyTemplate {...d} {...P} />;
    case 'warning': return <WarningTemplate {...d} {...P} />;
    case 'tip': return <TipTemplate {...d} {...P} />;
    case 'opinion': return <OpinionTemplate {...d} {...P} />;
    case 'transition': return <TransitionTemplate {...d} {...P} />;
    case 'framework': return <FrameworkTemplate {...d} {...P} />;
    // — Nouveaux Tier 1 —
    case 'comparison': return <ComparisonTemplate {...d} {...P} />;
    case 'comparison-ternary': return <ComparisonTemplate {...d} {...P} />;
    case 'steps': return <StepsTemplate {...d} {...P} />;
    case 'steps-mini': return <StepsTemplate {...d} {...P} />;
    case 'profiles': return <ProfilesTemplate {...d} {...P} />;
    // — Tier 2 —
    case 'definition': return <DefinitionTemplate {...d} {...P} />;
    case 'quotable': return <QuotableTemplate {...d} {...P} />;
    case 'quotable-2': return <QuotableTemplate {...d} {...P} />;
    case 'script': return <ScriptTemplate {...d} {...P} />;
    case 'matrix': return <MatrixTemplate {...d} {...P} />;
    // — Tier 3 —
    case 'gradient': return <GradientTemplate {...d} {...P} />;
    case 'signals': return <SignalsTemplate {...d} {...P} />;
    case 'timeline': return <TimelineTemplate {...d} {...P} />;
    case 'channel': return <ChannelAdaptationTemplate {...d} {...P} />;
    case 'beforeafter': return <BeforeAfterTemplate {...d} {...P} />;
    case 'checklist': return <ChecklistTemplate {...d} {...P} />;
    case 'escalation': return <EscalationLadderTemplate {...d} {...P} />;
    case 'toolkit': return <ToolkitTemplate {...d} {...P} />;
    // — Tier 4 —
    case 'decisiontree': return <DecisionTreeTemplate {...d} {...P} />;
    case 'temperature': return <TemperatureScaleTemplate {...d} {...P} />;
    case 'kpi': return <KPIExplainerTemplate {...d} {...P} />;
    case 'selfdiag': return <SelfDiagTemplate {...d} {...P} />;
    case 'paradox': return <ParadoxTemplate {...d} {...P} />;
    case 'learningpath': return <LearningPathTemplate {...d} {...P} />;
    case 'exercise': return <PracticeExerciseTemplate {...d} {...P} />;
    case 'selfmanagement': return <SelfManagementTemplate {...d} {...P} />;
    case 'signalradar': return <SignalRadarTemplate {...d} {...P} />;
    default: return null;
  }
};

export default function TestSlides() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const item = ALL_ITEMS[currentIndex];

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#0f172a', color: '#f1f5f9', display: 'grid', gridTemplateColumns: '260px 1fr', fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* Sidebar */}
      <aside style={{ borderRight: '1px solid #334155', padding: '16px', backgroundColor: '#111827', overflowY: 'auto' }}>
        <div style={{ marginBottom: '16px' }}>
          <div style={{ color: '#a78bfa', fontSize: '10px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase', marginBottom: '4px' }}>
            Aperçu templates
          </div>
          <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 700 }}>
            {ALL_ITEMS.length} slides React
          </h1>
        </div>

        {GROUPS.map((group, gi) => (
          <div key={gi} style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: '#64748B', marginBottom: '6px', paddingLeft: '4px' }}>
              {group.label}
            </div>
            <div style={{ display: 'grid', gap: '4px' }}>
              {group.items.map((item, ii) => {
                const idx = ALL_ITEMS.findIndex(a => a.groupLabel === group.label && a.label === item.label && a.type === item.type);
                const active = idx === currentIndex;
                return (
                  <button
                    key={ii}
                    type="button"
                    onClick={() => setCurrentIndex(idx)}
                    style={{
                      textAlign: 'left', border: `1px solid ${active ? '#8B5CF6' : '#1e293b'}`,
                      backgroundColor: active ? 'rgba(139,92,246,0.14)' : 'transparent',
                      color: active ? '#f8fafc' : '#94a3b8', borderRadius: '6px',
                      padding: '6px 10px', cursor: 'pointer', fontFamily: 'inherit',
                    }}
                  >
                    <div style={{ fontSize: '12px', fontWeight: active ? 700 : 500 }}>{item.label}</div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </aside>

      {/* Main */}
      <main style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px', gap: '16px', overflow: 'hidden' }}>
        <div style={{ width: 'min(1200px,100%)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
          <div>
            <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '2px' }}>
              {item.groupLabel} · {currentIndex + 1}/{ALL_ITEMS.length}
            </div>
            <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 700 }}>{item.label}</h2>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button type="button" onClick={() => setCurrentIndex(Math.max(0, currentIndex - 1))} disabled={currentIndex === 0}
              style={{ padding: '8px 14px', borderRadius: '8px', border: '1px solid #334155', backgroundColor: 'transparent', color: currentIndex === 0 ? '#64748b' : '#f1f5f9', cursor: currentIndex === 0 ? 'not-allowed' : 'pointer', fontFamily: 'inherit', fontWeight: 600 }}>
              ← Préc.
            </button>
            <button type="button" onClick={() => setCurrentIndex(Math.min(ALL_ITEMS.length - 1, currentIndex + 1))} disabled={currentIndex === ALL_ITEMS.length - 1}
              style={{ padding: '8px 14px', borderRadius: '8px', border: '1px solid #8B5CF6', backgroundColor: currentIndex === ALL_ITEMS.length - 1 ? 'transparent' : '#8B5CF6', color: currentIndex === ALL_ITEMS.length - 1 ? '#64748b' : '#fff', cursor: currentIndex === ALL_ITEMS.length - 1 ? 'not-allowed' : 'pointer', fontFamily: 'inherit', fontWeight: 600 }}>
              Suiv. →
            </button>
          </div>
        </div>

        <div style={{ width: 'min(1200px,100%)', display: 'flex', justifyContent: 'center', overflow: 'auto', padding: '4px' }}>
          {renderSlide(item)}
        </div>
      </main>
    </div>
  );
}
