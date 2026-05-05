import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const PALETTE = ['#7FCFC9', '#3FA6A0', '#F4A332', '#A7B85A', '#E07A6F'];

// stages: [{ period, title, focus, milestone }]
const LearningPathTemplate = ({
  title = 'Votre parcours de montée en compétences TP CRCD',
  stages = [
    {
      period: 'J1–J2',
      title: 'Fondations',
      focus: 'Accueil, écoute active, communication orale et écrite',
      milestone: 'Premiers appels supervisés réussis',
    },
    {
      period: 'Semaine 2',
      title: 'Diagnostic',
      focus: 'Méthode de diagnostic + gestion des situations difficiles',
      milestone: 'Résolution autonome de 80% des cas courants',
    },
    {
      period: 'Mois 1',
      title: 'Vente éthique',
      focus: 'Prospection, objections, cross-selling, closing',
      milestone: 'Premiers deals conclus en autonomie',
    },
    {
      period: 'Mois 2–3',
      title: 'Maîtrise',
      focus: 'Rétention, recouvrement, adaptation comportementale avancée',
      milestone: 'Taux FCR > 70%, NPS client positif',
    },
    {
      period: 'Fin de cursus',
      title: 'Certification',
      focus: 'Épreuve jury, dossier de compétences, mise en situation',
      milestone: '🎓 Titre Professionnel CRCD obtenu',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-5 gap-4">
      <h1 className="font-['Fredoka'] text-[1.9rem] text-[#2d241e] font-bold uppercase text-center leading-tight">
        {title}
      </h1>

      {/* Path */}
      <div className="flex-1 flex flex-col justify-center">
        {/* Timeline line */}
        <div className="relative flex items-center mb-4">
          <div className="absolute left-0 right-0 h-1.5 bg-[#E2E8F0] rounded-full" />
          {stages.map((_, i) => {
            const pos = (i / (stages.length - 1)) * 100;
            const color = PALETTE[i % PALETTE.length];
            return (
              <div
                key={i}
                className="absolute w-4 h-4 rounded-full border-4 border-[#FFF9E6]"
                style={{ left: `${pos}%`, transform: 'translateX(-50%)', backgroundColor: color }}
              />
            );
          })}
          {/* Progression fill */}
          <div
            className="absolute left-0 h-1.5 rounded-full"
            style={{ width: '40%', background: `linear-gradient(to right, ${PALETTE[0]}, ${PALETTE[1]})` }}
          />
        </div>

        {/* Cartes */}
        <div className="flex gap-2">
          {stages.map((stage, i) => {
            const color = PALETTE[i % PALETTE.length];
            const isLast = i === stages.length - 1;
            return (
              <div
                key={i}
                className="flex-1 rounded-2xl overflow-hidden border-2 flex flex-col"
                style={{ borderColor: color, opacity: i > 1 ? 0.85 : 1 }}
              >
                {/* Header */}
                <div className="px-3 py-2" style={{ backgroundColor: color }}>
                  <div className="font-['Poppins'] text-white text-[0.7rem] font-bold uppercase">{stage.period}</div>
                  <div className="font-['Fredoka'] text-white text-[1rem] font-bold">{stage.title}</div>
                </div>

                {/* Content */}
                <div className="flex-1 bg-white px-3 py-2 flex flex-col gap-2">
                  <p className="font-['Poppins'] text-[0.75rem] text-[#444] leading-snug">{stage.focus}</p>
                  <div
                    className="mt-auto rounded-lg px-2 py-1.5 text-center"
                    style={{ backgroundColor: isLast ? color : `${color}20` }}
                  >
                    <p
                      className="font-['Poppins'] text-[0.72rem] font-bold leading-snug"
                      style={{ color: isLast ? 'white' : color }}
                    >
                      ✓ {stage.milestone}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  </div>
);

export default LearningPathTemplate;
