import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const PALETTE = ['#F4A332', '#7FCFC9', '#3FA6A0', '#A7B85A', '#E07A6F'];

// milestones: [{ when, title, actions: [string], color? }]
const TimelineTemplate = ({
  title = 'Suivi post-vente — le protocole',
  subtitle = 'Chaque étape consolide la relation et prévient le churn.',
  milestones = [
    {
      when: '24–48h',
      title: 'Email de confirmation',
      color: '#F4A332',
      actions: ['Récapitulatif de ce qui a été convenu', 'Prochaine étape nommée', 'Contact direct de votre responsable'],
    },
    {
      when: '1 semaine',
      title: 'Appel de bienvenue',
      color: '#7FCFC9',
      actions: ['Vérifier que l\'accès / l\'installation est opérationnel', 'Répondre aux premières questions', 'Identifier un succès rapide à célébrer'],
    },
    {
      when: '1 mois',
      title: 'Point de satisfaction',
      color: '#3FA6A0',
      actions: ['Demander un retour honnête (NPS ou simple appel)', 'Identifier si le besoin a évolué', 'Cross-selling si pertinent'],
    },
    {
      when: '3 mois',
      title: 'Revue de valeur',
      color: '#A7B85A',
      actions: ['Mesurer les résultats obtenus', 'Ajuster si nécessaire', 'Préparer le renouvellement'],
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-5 gap-4">
      <div className="text-center">
        <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase">{title}</h1>
        {subtitle && <p className="font-['Poppins'] text-[0.85rem] text-[#666] mt-1">{subtitle}</p>}
      </div>

      {/* Timeline axis */}
      <div className="flex-1 flex flex-col justify-center gap-3">
        {/* Ligne horizontale avec points */}
        <div className="relative flex items-center">
          <div className="absolute left-0 right-0 h-1 bg-[#E2E8F0] rounded-full" />
          {milestones.map((m, i) => {
            const pos = (i / (milestones.length - 1)) * 100;
            return (
              <div
                key={i}
                className="absolute flex flex-col items-center"
                style={{ left: `${pos}%`, transform: 'translateX(-50%)' }}
              >
                <div
                  className="w-5 h-5 rounded-full border-4 border-[#FFF9E6] shadow-md z-10"
                  style={{ backgroundColor: m.color || PALETTE[i % PALETTE.length] }}
                />
              </div>
            );
          })}
        </div>

        {/* Cartes */}
        <div className="flex gap-3">
          {milestones.map((m, i) => {
            const color = m.color || PALETTE[i % PALETTE.length];
            return (
              <div
                key={i}
                className="flex-1 rounded-2xl overflow-hidden border-2"
                style={{ borderColor: color }}
              >
                {/* Header carte */}
                <div className="px-4 py-2" style={{ backgroundColor: color }}>
                  <div className="font-['Fredoka'] text-white text-[1.1rem] font-bold">{m.when}</div>
                  <div className="font-['Poppins'] text-white text-[0.78rem] font-semibold">{m.title}</div>
                </div>
                {/* Actions */}
                <div className="bg-white px-4 py-3 flex flex-col gap-1.5">
                  {m.actions.map((a, j) => (
                    <div key={j} className="flex items-start gap-2">
                      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5" style={{ backgroundColor: color }} />
                      <span className="font-['Poppins'] text-[0.78rem] text-[#333] leading-snug">{a}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  </div>
);

export default TimelineTemplate;
