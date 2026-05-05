import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const TemperatureScaleTemplate = ({
  title = 'La qualification des prospects',
  subtitle = 'Un contact froid n\'est pas perdu — il est juste mal préparé.',
  zones = [
    {
      label: 'Froid ❄️',
      color: '#60A5FA',
      bg: '#EFF6FF',
      criteria: [
        'Pas de besoin identifié',
        'Pas de budget prévu',
        'Aucun contact récent',
        'Décideur non identifié',
      ],
      action: 'Nurturing — contenu, veille, LinkedIn. Pas de pression commerciale.',
    },
    {
      label: 'Tiède 🌤️',
      color: '#F4A332',
      bg: '#FFF8ED',
      criteria: [
        'Besoin vague mais réel',
        'Budget à définir',
        'Décideur accessible',
        'Intérêt exprimé informellement',
      ],
      action: 'Qualifier. Appel de découverte pour affiner le besoin réel.',
    },
    {
      label: 'Chaud 🔥',
      color: '#DC2626',
      bg: '#FEF2F2',
      criteria: [
        'Besoin précis et urgent',
        'Budget validé',
        'Décideur impliqué',
        'Délai de décision court',
      ],
      action: 'Proposer. Envoyer une offre personnalisée et fixer un RDV de closing.',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <div className="text-center">
        <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase">{title}</h1>
        {subtitle && <p className="font-['Poppins'] text-[0.85rem] text-[#666] mt-1">{subtitle}</p>}
      </div>

      {/* Barre thermomètre */}
      <div className="w-full h-5 rounded-full overflow-hidden"
        style={{ background: 'linear-gradient(to right, #60A5FA, #F4A332, #DC2626)' }}
      />

      {/* Cartes zones */}
      <div className="flex-1 flex gap-4">
        {zones.map((z, i) => (
          <div
            key={i}
            className="flex-1 rounded-2xl overflow-hidden border-2 flex flex-col"
            style={{ borderColor: z.color, backgroundColor: z.bg }}
          >
            {/* Header zone */}
            <div className="px-5 py-3 flex items-center justify-center" style={{ backgroundColor: z.color }}>
              <span className="font-['Fredoka'] text-white text-[1.3rem] font-bold">{z.label}</span>
            </div>

            {/* Critères */}
            <div className="flex-1 px-5 py-3 flex flex-col gap-2">
              <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wide" style={{ color: z.color }}>
                Critères
              </div>
              {z.criteria.map((c, j) => (
                <div key={j} className="flex items-start gap-2">
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5" style={{ backgroundColor: z.color }} />
                  <span className="font-['Poppins'] text-[0.82rem] text-[#333]">{c}</span>
                </div>
              ))}
            </div>

            {/* Action */}
            <div className="border-t-2 px-5 py-3" style={{ borderColor: z.color }}>
              <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wide mb-1" style={{ color: z.color }}>
                Action →
              </div>
              <p className="font-['Poppins'] text-[0.82rem] text-[#2d241e] font-semibold leading-snug">{z.action}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default TemperatureScaleTemplate;
