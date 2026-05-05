import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// rows: [{ cause, icon, color, solutions: [string] }]
const MatrixTemplate = ({
  title = 'Matrice cause → solution (résiliation)',
  rowLabel = 'Cause identifiée',
  colLabel = 'Réponses adaptées',
  rows = [
    {
      cause: 'Problème de prix',
      icon: '💰',
      color: '#F4A332',
      solutions: ['Proposer un tarif dégroupé', 'Offrir une pause de paiement', 'Comparer la valeur vs le concurrent'],
    },
    {
      cause: 'Problème de qualité',
      icon: '⚠️',
      color: '#E07A6F',
      solutions: ['Corriger le défaut signalé', 'Geste commercial immédiat', 'Engagement de suivi daté'],
    },
    {
      cause: 'Non-utilisation du produit',
      icon: '🔌',
      color: '#7FCFC9',
      solutions: ['Session de formation offerte', 'Version simplifiée', 'Accompagnement dédié 30 jours'],
    },
    {
      cause: 'Mauvaise expérience passée',
      icon: '💔',
      color: '#A7B85A',
      solutions: ['Reconnaître explicitement', 'Nommer un contact unique', 'Proposer une période d\'essai gratuite'],
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <h1 className="font-['Fredoka'] text-[1.9rem] text-[#2d241e] font-bold uppercase text-center leading-tight">
        {title}
      </h1>

      {/* Table */}
      <div className="flex-1 flex flex-col overflow-hidden rounded-xl border border-[#E2E8F0]">
        {/* Header row */}
        <div className="flex bg-[#2d241e] text-white">
          <div className="w-[34%] px-5 py-2 font-['Poppins'] font-bold text-[0.8rem] uppercase tracking-wide border-r border-white/20">
            {rowLabel}
          </div>
          <div className="flex-1 px-5 py-2 font-['Poppins'] font-bold text-[0.8rem] uppercase tracking-wide">
            {colLabel}
          </div>
        </div>

        {/* Data rows */}
        {rows.map((row, i) => (
          <div
            key={i}
            className="flex flex-1 border-t border-[#E2E8F0]"
            style={{ backgroundColor: i % 2 === 0 ? 'white' : '#FAFAFA' }}
          >
            {/* Cause */}
            <div
              className="w-[34%] flex items-center gap-3 px-5 py-2 border-r-2"
              style={{ borderColor: row.color }}
            >
              <div
                className="w-9 h-9 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
                style={{ backgroundColor: `${row.color}22` }}
              >
                {row.icon}
              </div>
              <span className="font-['Poppins'] font-bold text-[0.88rem] text-[#2d241e] leading-snug">
                {row.cause}
              </span>
            </div>

            {/* Solutions */}
            <div className="flex-1 flex items-center px-5 py-2 gap-3 flex-wrap">
              {row.solutions.map((sol, j) => (
                <div
                  key={j}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[0.78rem] font-['Poppins'] font-semibold"
                  style={{ backgroundColor: `${row.color}20`, color: row.color, border: `1px solid ${row.color}50` }}
                >
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: row.color }} />
                  {sol}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default MatrixTemplate;
