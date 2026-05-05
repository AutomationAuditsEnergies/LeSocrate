import React, { useState } from 'react';
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

const COMMON_PROPS = {
  badge: 'TP-CRCD',
  brandName: 'SALES HACKING',
};

const TEMPLATE_PREVIEWS = [
  {
    type: 'playful',
    label: 'Playful',
    description: 'Cartes visuelles pour comparer plusieurs leviers.',
    data: {
      title: "Pourquoi l'automatisation est vitale ?",
      cards: [
        {
          title: 'Gain de temps',
          desc: 'Libérer les équipes des tâches répétitives pour se concentrer sur la relation client.',
          img: 'https://images.unsplash.com/photo-1506784983877-45594efa4cbe?q=80&w=1200&auto=format&fit=crop',
        },
        {
          title: 'Scalabilité',
          desc: 'Traiter plus de demandes sans augmenter mécaniquement les effectifs.',
          img: 'https://images.unsplash.com/photo-1558494949-ef526b0042a0?q=80&w=1200&auto=format&fit=crop',
        },
        {
          title: 'Fiabilité',
          desc: 'Réduire les erreurs de saisie et sécuriser les informations commerciales.',
          img: 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?q=80&w=1200&auto=format&fit=crop',
        },
      ],
    },
  },
  {
    type: 'reflection',
    label: 'Reflection',
    description: 'Point conceptuel ou question de recul.',
    data: {
      title: 'La posture professionnelle',
      text: "Un bon conseiller ne cherche pas seulement à répondre vite. Il reformule, vérifie le besoin réel et sécurise la suite de l'échange.",
    },
  },
  {
    type: 'casestudy',
    label: 'Case Study',
    description: 'Mise en situation ou comparaison de cas.',
    data: {
      title: 'Trois situations client',
      cases: [
        { title: 'Client pressé', desc: 'Il faut prioriser la demande et aller droit au résultat attendu.' },
        { title: 'Client hésitant', desc: 'Il faut clarifier le besoin avant de proposer une solution.' },
        { title: 'Client mécontent', desc: "Il faut traiter l'émotion avant de traiter la procédure." },
      ],
    },
  },
  {
    type: 'facilitator',
    label: 'Facilitator',
    description: 'Processus en étapes.',
    data: {
      title: 'Traiter une demande',
      steps: [
        { title: 'Identifier', desc: 'Comprendre le besoin exprimé.', icon: 'target', color: 'orange' },
        { title: 'Qualifier', desc: 'Vérifier les contraintes utiles.', icon: 'gear', color: 'purple' },
        { title: 'Agir', desc: 'Proposer une réponse concrète.', icon: 'flash', color: 'lime' },
        { title: 'Clore', desc: 'Confirmer la suite avec précision.', icon: 'flag', color: 'blue' },
      ],
    },
  },
  {
    type: 'chart',
    label: 'Chart',
    description: 'Graphique ou évolution chiffrée.',
    data: {
      title: 'Progression des demandes',
      description: 'Le volume peut augmenter fortement aux heures de pointe. Le traitement doit rester structuré pour éviter les pertes de suivi.',
    },
  },
  {
    type: 'stats',
    label: 'Stats',
    description: 'Chiffres clés et synthèse rapide.',
    data: {
      eyebrow: 'Indicateurs',
      title: 'Priorités',
      description: "Trois repères simples permettent de piloter la qualité d'un accueil client.",
      stats: [{ number: '3' }, { number: '24h' }, { number: '95%' }],
      columns: [
        'Identifier la demande avant de proposer une réponse.',
        'Respecter le délai annoncé au client.',
        'Tracer les informations utiles pour la suite.',
      ],
    },
  },
  {
    type: 'story',
    label: 'Story',
    description: 'Mini-récit pédagogique.',
    data: {
      title: 'Le client qui revient',
      narrative: "Un client qui répète sa demande n'est pas forcément difficile. Il signale souvent que la première réponse n'a pas été assez claire.",
      moral: 'La clarté évite la répétition et protège la relation.',
    },
  },
  {
    type: 'recap',
    label: 'Recap',
    description: 'Résumé de fin de partie.',
    data: {
      title: 'À retenir',
      points: [
        'Écouter avant de répondre.',
        'Reformuler pour vérifier.',
        'Annoncer une suite réaliste.',
        'Tracer les éléments utiles.',
      ],
    },
  },
  {
    type: 'analogy',
    label: 'Analogy',
    description: 'Comparaison simple pour ancrer une idée.',
    data: {
      title: 'Le suivi client',
      concept: 'CRM',
      comparison: 'Carnet de bord',
      text: "Comme un carnet de bord, le CRM sert à comprendre ce qui s'est passé, qui doit agir, et quelle est la prochaine étape.",
    },
  },
  {
    type: 'warning',
    label: 'Warning',
    description: 'Erreur fréquente ou point de vigilance.',
    data: {
      title: 'Ne pas promettre trop vite',
      text: 'Une promesse imprécise crée une attente difficile à tenir. Mieux vaut annoncer un délai clair et réaliste.',
    },
  },
  {
    type: 'tip',
    label: 'Tip',
    description: 'Astuce opérationnelle.',
    data: {
      title: 'La phrase de validation',
      text: "Terminez par une phrase courte : je récapitule ce que nous avons convenu, puis je vous confirme la prochaine étape.",
    },
  },
  {
    type: 'opinion',
    label: 'Opinion',
    description: 'Point de vue du formateur.',
    data: {
      title: 'La qualité se voit dans les détails',
      text: 'Une procédure bien suivie ne remplace pas la posture. Les deux doivent avancer ensemble.',
    },
  },
  {
    type: 'transition',
    label: 'Transition',
    description: 'Passage entre deux thèmes.',
    data: {
      title: 'Passons à la pratique',
      from_topic: 'Les principes',
      to_topic: 'Les gestes métier',
    },
  },
  {
    type: 'framework',
    label: 'Framework — 4 satellites + cœur',
    description: 'Modèle conceptuel circulaire à 4 axes (ex. 5 forces de Porter).',
    data: {
      title: 'Les 4 forces de Porter',
      center: { title: 'Intensité de rivalité entre concurrents' },
      segments: [
        { title: 'Menace des nouveaux entrants', desc: "Barrières à l'entrée faibles." },
        { title: 'Menace des produits de substitution', desc: 'Alternatives plus efficaces.' },
        { title: 'Pouvoir de négociation des clients', desc: 'Clients nombreux ou concentrés.' },
        { title: 'Pouvoir de négociation des fournisseurs', desc: 'Fournisseurs peu nombreux.' },
      ],
    },
  },
  {
    type: 'framework',
    label: 'Framework — 6 satellites + cœur',
    description: 'Variante plus dense (modèles à 6 leviers ou étapes).',
    data: {
      title: 'Les 6 leviers de la performance',
      center: { title: 'Performance commerciale' },
      segments: [
        { title: 'Prospection', desc: 'Volume des contacts entrants.' },
        { title: 'Qualification', desc: 'Tri du besoin réel.' },
        { title: 'Argumentaire', desc: 'Promesse adaptée.' },
        { title: 'Closing', desc: 'Décision claire.' },
        { title: 'Onboarding', desc: 'Démarrage sans friction.' },
        { title: 'Fidélisation', desc: 'Valeur dans la durée.' },
      ],
    },
  },
];

export default function TestSlides() {
  const [currentSlide, setCurrentSlide] = useState(0);
  const slide = TEMPLATE_PREVIEWS[currentSlide];

  const renderSlide = () => {
    switch (slide.type) {
      case 'playful':
        return <PlayfulTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'reflection':
        return <ReflectionTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'casestudy':
        return <CaseStudyTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'facilitator':
        return <FacilitatorTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'chart':
        return <ChartTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'stats':
        return <StatsTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'story':
        return <StoryTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'recap':
        return <RecapTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'analogy':
        return <AnalogyTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'warning':
        return <WarningTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'tip':
        return <TipTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'opinion':
        return <OpinionTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'transition':
        return <TransitionTemplate {...slide.data} {...COMMON_PROPS} />;
      case 'framework':
        return <FrameworkTemplate {...slide.data} {...COMMON_PROPS} />;
      default:
        return null;
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#0f172a',
      color: '#f1f5f9',
      display: 'grid',
      gridTemplateColumns: '280px 1fr',
      fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
    }}>
      <aside style={{
        borderRight: '1px solid #334155',
        padding: '24px',
        backgroundColor: '#111827',
        overflowY: 'auto',
      }}>
        <div style={{ marginBottom: '22px' }}>
          <div style={{
            color: '#a78bfa',
            fontSize: '11px',
            fontWeight: 700,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            marginBottom: '8px',
          }}>
            Aperçu templates
          </div>
          <h1 style={{
            margin: 0,
            fontSize: '22px',
            lineHeight: '28px',
            fontWeight: 700,
          }}>
            Slides React
          </h1>
        </div>

        <div style={{ display: 'grid', gap: '8px' }}>
          {TEMPLATE_PREVIEWS.map((item, index) => {
            const active = index === currentSlide;
            return (
              <button
                key={item.type}
                type="button"
                onClick={() => setCurrentSlide(index)}
                style={{
                  textAlign: 'left',
                  border: `1px solid ${active ? '#8B5CF6' : '#334155'}`,
                  backgroundColor: active ? 'rgba(139, 92, 246, 0.14)' : 'transparent',
                  color: active ? '#f8fafc' : '#cbd5e1',
                  borderRadius: '8px',
                  padding: '10px 12px',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                <div style={{ fontSize: '14px', fontWeight: 700 }}>{item.label}</div>
                <div style={{ fontSize: '12px', color: active ? '#c4b5fd' : '#94a3b8', marginTop: '3px' }}>
                  {item.description}
                </div>
              </button>
            );
          })}
        </div>
      </aside>

      <main style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '28px',
        gap: '18px',
        overflow: 'hidden',
      }}>
        <div style={{
          width: 'min(1200px, 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
        }}>
          <div>
            <div style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '4px' }}>
              Template {currentSlide + 1} / {TEMPLATE_PREVIEWS.length}
            </div>
            <h2 style={{ margin: 0, fontSize: '20px', lineHeight: '28px' }}>
              {slide.label}
            </h2>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              type="button"
              onClick={() => setCurrentSlide(Math.max(0, currentSlide - 1))}
              disabled={currentSlide === 0}
              style={{
                padding: '9px 14px',
                borderRadius: '8px',
                border: '1px solid #334155',
                backgroundColor: 'transparent',
                color: currentSlide === 0 ? '#64748b' : '#f1f5f9',
                cursor: currentSlide === 0 ? 'not-allowed' : 'pointer',
                fontFamily: 'inherit',
                fontWeight: 600,
              }}
            >
              Precedent
            </button>
            <button
              type="button"
              onClick={() => setCurrentSlide(Math.min(TEMPLATE_PREVIEWS.length - 1, currentSlide + 1))}
              disabled={currentSlide === TEMPLATE_PREVIEWS.length - 1}
              style={{
                padding: '9px 14px',
                borderRadius: '8px',
                border: '1px solid #8B5CF6',
                backgroundColor: currentSlide === TEMPLATE_PREVIEWS.length - 1 ? 'transparent' : '#8B5CF6',
                color: currentSlide === TEMPLATE_PREVIEWS.length - 1 ? '#64748b' : '#ffffff',
                cursor: currentSlide === TEMPLATE_PREVIEWS.length - 1 ? 'not-allowed' : 'pointer',
                fontFamily: 'inherit',
                fontWeight: 600,
              }}
            >
              Suivant
            </button>
          </div>
        </div>

        <div style={{
          width: 'min(1200px, 100%)',
          display: 'flex',
          justifyContent: 'center',
          overflow: 'auto',
          padding: '8px',
        }}>
          {renderSlide()}
        </div>
      </main>
    </div>
  );
}
