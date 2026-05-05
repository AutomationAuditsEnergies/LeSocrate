import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// kpis: [{ acronym, fullName, definition, goodValue, impact, color }]
const KPIExplainerTemplate = ({
  title = 'Les KPI de la relation client à distance',
  kpis = [
    {
      acronym: 'TMT',
      fullName: 'Temps Moyen de Traitement',
      definition: 'Durée moyenne de chaque interaction (appel, chat, email), de l\'ouverture à la fermeture du dossier.',
      goodValue: '< 5 min pour les demandes courantes',
      impact: 'Directement influencé par votre clarté, votre débit vocal et votre maîtrise du diagnostic.',
      color: '#3FA6A0',
    },
    {
      acronym: 'NPS',
      fullName: 'Net Promoter Score',
      definition: 'Mesure la probabilité qu\'un client recommande votre entreprise à son entourage. Échelle 0–10.',
      goodValue: '> 50 = Excellent · 0–49 = Bien · < 0 = à corriger',
      impact: 'Influencé par la qualité de l\'empathie, la résolution au premier contact, la relation humaine.',
      color: '#F4A332',
    },
    {
      acronym: 'FCR',
      fullName: 'First Call Resolution',
      definition: 'Taux de demandes résolues dès le premier contact, sans rappel ni relance nécessaire.',
      goodValue: '> 70% dans un service client performant',
      impact: 'Dépend de la qualité du diagnostic initial et de votre capacité à anticiper les questions.',
      color: '#A7B85A',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase text-center">
        {title}
      </h1>

      <div className="flex-1 flex gap-4">
        {kpis.map((kpi, i) => (
          <div
            key={i}
            className="flex-1 rounded-2xl overflow-hidden border-2 flex flex-col"
            style={{ borderColor: kpi.color }}
          >
            {/* Header KPI */}
            <div className="px-5 pt-4 pb-3 flex flex-col items-center gap-1" style={{ backgroundColor: kpi.color }}>
              <div className="font-['Fredoka'] text-white text-[3rem] font-bold leading-none">{kpi.acronym}</div>
              <div className="font-['Poppins'] text-white/90 text-[0.78rem] text-center font-semibold">{kpi.fullName}</div>
            </div>

            {/* Définition */}
            <div className="bg-white px-5 py-3 flex-1 flex flex-col gap-3">
              <div>
                <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wide text-[#888] mb-1">Définition</div>
                <p className="font-['Poppins'] text-[0.82rem] text-[#333] leading-snug">{kpi.definition}</p>
              </div>

              <div className="rounded-lg px-3 py-2" style={{ backgroundColor: `${kpi.color}15` }}>
                <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wide mb-1" style={{ color: kpi.color }}>
                  Seuil de performance
                </div>
                <p className="font-['Poppins'] text-[0.8rem] text-[#2d241e] font-semibold">{kpi.goodValue}</p>
              </div>

              <div className="mt-auto">
                <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wide text-[#888] mb-1">
                  Ce que vous pouvez y faire
                </div>
                <p className="font-['Poppins'] text-[0.78rem] text-[#555] italic leading-snug">{kpi.impact}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default KPIExplainerTemplate;
