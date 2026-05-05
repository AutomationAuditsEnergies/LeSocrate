import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// lines: [{ speaker: 'client'|'conseiller', text, annotation? }]
const ScriptTemplate = ({
  title = 'Traiter une objection prix',
  context = 'Le client vient de dire : "Votre prix est trop élevé."',
  lines = [
    {
      speaker: 'client',
      text: '"Franchement, votre tarif est bien au-dessus de ce que je voulais mettre."',
      annotation: null,
    },
    {
      speaker: 'conseiller',
      text: '"Je vous entends. Quand vous dites trop élevé — c\'est par rapport à quel budget ou à quel concurrent ?"',
      annotation: '✓ Ne pas défendre le prix. Creuser d\'abord.',
    },
    {
      speaker: 'client',
      text: '"J\'ai un devis de votre concurrent à 2 400 € pour la même prestation."',
      annotation: null,
    },
    {
      speaker: 'conseiller',
      text: '"D\'accord. Est-ce que ce devis inclut le support post-formation et les mises à jour pendant un an ?"',
      annotation: '✓ Comparer ce qui est comparable.',
    },
    {
      speaker: 'client',
      text: '"Euh… je ne sais pas en fait."',
      annotation: null,
    },
    {
      speaker: 'conseiller',
      text: '"C\'est exactement là où on fait la différence. Voici ce qui est inclus dans notre offre…"',
      annotation: '✓ Valeur ajoutée, pas prix seul.',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <div className="flex items-start gap-4">
        <div>
          <h1 className="font-['Fredoka'] text-[1.7rem] text-[#2d241e] font-bold uppercase leading-tight">{title}</h1>
          <p className="font-['Poppins'] text-[0.85rem] text-[#666] mt-0.5">{context}</p>
        </div>
        <div className="ml-auto flex gap-3 flex-shrink-0 text-[0.75rem] font-['Poppins']">
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-[#E2E8F0]" />
            <span className="text-[#666]">Client</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full bg-[#3FA6A0]" />
            <span className="text-[#666]">Conseiller</span>
          </div>
        </div>
      </div>

      {/* Dialogue */}
      <div className="flex-1 flex flex-col gap-2 overflow-hidden">
        {lines.map((line, i) => {
          const isClient = line.speaker === 'client';
          return (
            <div key={i} className={`flex gap-3 ${isClient ? 'justify-start' : 'justify-end'}`}>
              {/* Avatar */}
              {isClient && (
                <div className="w-8 h-8 rounded-full bg-[#CBD5E1] flex-shrink-0 flex items-center justify-center text-sm">
                  👤
                </div>
              )}

              <div className={`max-w-[62%] flex flex-col gap-1 ${isClient ? 'items-start' : 'items-end'}`}>
                {/* Bulle */}
                <div
                  className="rounded-2xl px-4 py-2.5"
                  style={{
                    backgroundColor: isClient ? '#F1F5F9' : '#3FA6A0',
                    color: isClient ? '#2d241e' : 'white',
                    borderBottomLeftRadius: isClient ? '4px' : '16px',
                    borderBottomRightRadius: isClient ? '16px' : '4px',
                  }}
                >
                  <p className="font-['Poppins'] text-[0.83rem] leading-snug">{line.text}</p>
                </div>
                {/* Annotation */}
                {line.annotation && (
                  <div className="bg-[#F4A332] text-white font-['Poppins'] text-[0.72rem] font-bold px-3 py-0.5 rounded-full">
                    {line.annotation}
                  </div>
                )}
              </div>

              {/* Avatar conseiller */}
              {!isClient && (
                <div className="w-8 h-8 rounded-full bg-[#3FA6A0] flex-shrink-0 flex items-center justify-center text-sm">
                  🎯
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  </div>
);

export default ScriptTemplate;
