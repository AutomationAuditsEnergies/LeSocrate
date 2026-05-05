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

const P = { badge: 'TP-CRCD', brandName: 'SALES HACKING' };

const GROUPS = [
  {
    label: 'Existants',
    items: [
      { type: 'playful', label: 'Playful', data: { title: "Pourquoi l'automatisation est vitale ?", cards: [ { title: 'Gain de temps', desc: 'Libérer les équipes des tâches répétitives.', img: 'https://images.unsplash.com/photo-1506784983877-45594efa4cbe?q=80&w=1200&auto=format&fit=crop' }, { title: 'Scalabilité', desc: 'Traiter plus de demandes sans augmenter les effectifs.', img: 'https://images.unsplash.com/photo-1558494949-ef526b0042a0?q=80&w=1200&auto=format&fit=crop' }, { title: 'Fiabilité', desc: 'Réduire les erreurs et sécuriser les informations.', img: 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?q=80&w=1200&auto=format&fit=crop' } ] } },
      { type: 'reflection', label: 'Reflection', data: { title: 'La posture professionnelle', text: "Un bon conseiller reformule, vérifie le besoin réel et sécurise la suite de l'échange." } },
      { type: 'casestudy', label: 'Case Study', data: { title: 'Trois situations client', cases: [ { title: 'Client pressé', desc: 'Prioriser et aller droit au résultat.' }, { title: 'Client hésitant', desc: 'Clarifier le besoin avant de proposer.' }, { title: 'Client mécontent', desc: "Traiter l'émotion avant la procédure." } ] } },
      { type: 'facilitator', label: 'Facilitator', data: { title: 'Traiter une demande', steps: [ { title: 'Identifier', desc: 'Comprendre le besoin exprimé.', icon: 'target', color: 'orange' }, { title: 'Qualifier', desc: 'Vérifier les contraintes utiles.', icon: 'gear', color: 'purple' }, { title: 'Agir', desc: 'Proposer une réponse concrète.', icon: 'flash', color: 'lime' }, { title: 'Clore', desc: 'Confirmer la suite avec précision.', icon: 'flag', color: 'blue' } ] } },
      { type: 'chart', label: 'Chart', data: { title: 'Progression des demandes', description: 'Le volume augmente aux heures de pointe. Le traitement doit rester structuré.' } },
      { type: 'stats', label: 'Stats', data: { eyebrow: 'Indicateurs', title: 'Priorités', description: "Trois repères pour piloter la qualité d'un accueil.", stats: [{ number: '3' }, { number: '24h' }, { number: '95%' }], columns: ['Identifier la demande avant de répondre.', 'Respecter le délai annoncé.', 'Tracer les infos utiles.'] } },
      { type: 'story', label: 'Story', data: { title: 'Le client qui revient', narrative: "Un client qui répète sa demande signale souvent que la première réponse n'était pas assez claire.", moral: 'La clarté évite la répétition et protège la relation.' } },
      { type: 'recap', label: 'Recap', data: { title: 'À retenir', points: ['Écouter avant de répondre.', 'Reformuler pour vérifier.', 'Annoncer une suite réaliste.', 'Tracer les éléments utiles.'] } },
      { type: 'analogy', label: 'Analogy', data: { title: 'Le suivi client', concept: 'CRM', comparison: 'Carnet de bord', text: "Comme un carnet de bord, le CRM sert à comprendre ce qui s'est passé et quelle est la prochaine étape." } },
      { type: 'warning', label: 'Warning', data: { title: 'Ne pas promettre trop vite', text: 'Une promesse imprécise crée une attente difficile à tenir.' } },
      { type: 'tip', label: 'Tip', data: { title: 'La phrase de validation', text: "Terminez par : je récapitule ce qu'on vient de convenir, puis je vous confirme la prochaine étape." } },
      { type: 'opinion', label: 'Opinion', data: { title: 'La qualité se voit dans les détails', text: 'Une procédure bien suivie ne remplace pas la posture. Les deux doivent avancer ensemble.' } },
      { type: 'transition', label: 'Transition', data: { title: 'Passons à la pratique', from_topic: 'Les principes', to_topic: 'Les gestes métier' } },
      { type: 'framework', label: 'Framework 4', data: { title: 'Les 4 forces de Porter', center: { title: 'Intensité de rivalité entre concurrents' }, segments: [ { title: 'Menace des nouveaux entrants', desc: "Barrières à l'entrée faibles." }, { title: 'Menace des produits de substitution', desc: 'Alternatives plus efficaces.' }, { title: 'Pouvoir de négociation des clients', desc: 'Clients nombreux ou concentrés.' }, { title: 'Pouvoir de négociation des fournisseurs', desc: 'Fournisseurs peu nombreux.' } ] } },
      { type: 'framework', label: 'Framework 6', data: { title: 'Les 6 leviers de la performance', center: { title: 'Performance commerciale' }, segments: [ { title: 'Prospection', desc: 'Volume des contacts entrants.' }, { title: 'Qualification', desc: 'Tri du besoin réel.' }, { title: 'Argumentaire', desc: 'Promesse adaptée.' }, { title: 'Closing', desc: 'Décision claire.' }, { title: 'Onboarding', desc: 'Démarrage sans friction.' }, { title: 'Fidélisation', desc: 'Valeur dans la durée.' } ] } },
    ],
  },
  {
    label: 'Tier 1 — Critiques',
    items: [
      { type: 'comparison', label: 'Comparison (binaire)', data: {} },
      { type: 'comparison-ternary', label: 'Comparison (ternaire)', data: { title: 'Les 3 postures face au client en difficulté', cols: [ { label: 'Sympathie', color: '#60A5FA', icon: '😢', bg: '#EFF6FF', accent: '#BFDBFE', items: ['"Oh je suis tellement désolé pour vous"', 'Partage émotionnel total', 'Le conseiller perd son objectivité', 'Relation floue, pas de solution'] }, { label: 'Empathie pro', color: '#16A34A', icon: '🎯', bg: '#F0FDF4', accent: '#BBF7D0', items: ['"Je vois que c\'est une situation difficile."', 'Reconnaît l\'émotion sans la partager', 'Posture stable et professionnelle', 'Solution proposée, relation renforcée'] }, { label: 'Neutralité froide', color: '#DC2626', icon: '🤖', bg: '#FEF2F2', accent: '#FECACA', items: ['"Votre numéro de dossier, s\'il vous plaît."', 'Ignore l\'état émotionnel du client', 'Le client se sent comme un ticket', 'Relation détériorée, risque de churn'] } ] } },
      { type: 'steps', label: 'Steps (4 étapes)', data: {} },
      { type: 'steps-mini', label: 'Steps (2 étapes)', data: { title: 'Recadrage cognitif entre deux appels', subtitle: 'Deux secondes suffisent pour repartir sur une page blanche.', steps: [ { title: 'Fermer mentalement', desc: 'Cet échange est terminé. J\'ai fait ce que je pouvais avec ce que j\'avais.' }, { title: 'Page blanche', desc: 'Le prochain client n\'a rien à voir avec le précédent. Recommencer à zéro.' } ] } },
      { type: 'profiles', label: 'Profiles (3 profils)', data: {} },
    ],
  },
  {
    label: 'Tier 2 — Importants',
    items: [
      { type: 'definition', label: 'Definition', data: {} },
      { type: 'quotable', label: 'Quotable', data: {} },
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
      { type: 'checklist', label: 'Checklist', data: {} },
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
      { type: 'exercise', label: 'Practice Exercise', data: {} },
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
