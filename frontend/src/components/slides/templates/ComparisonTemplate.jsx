import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// cols: [{ label, color, icon, items: [string] }]
// mode: 'binary' (2 cols, bad/good) | 'ternary' (3 cols)
const ComparisonTemplate = ({
  title = 'Deux façons de conclure un appel',
  cols = [
    {
      label: 'À éviter',
      color: '#DC2626',
      icon: '✗',
      bg: '#FEF2F2',
      accent: '#FECACA',
      items: [
        '"OK ben je vous envoie une brochure."',
        'Pas de date de rappel fixée.',
        'Le client ne sait pas quoi faire ensuite.',
        'Vous raccrochez sans engagement mutuel.',
      ],
    },
    {
      label: 'Bonne pratique',
      color: '#16A34A',
      icon: '✓',
      bg: '#F0FDF4',
      accent: '#BBF7D0',
      items: [
        '"Je suis disponible jeudi 14h30 ou vendredi 10h — lequel vous convient ?"',
        'Créneau précis proposé immédiatement.',
        'Le client sait exactement ce qui suit.',
        'Les deux parties sont engagées sur une date.',
      ],
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-5 gap-4">
      <h1 className="font-['Fredoka'] text-[1.9rem] text-[#2d241e] font-bold text-center uppercase leading-tight">
        {title}
      </h1>

      <div className="flex-1 flex gap-4 items-stretch">
        {cols.map((col, i) => (
          <React.Fragment key={i}>
            <div
              className="flex-1 flex flex-col rounded-2xl overflow-hidden border-2"
              style={{ borderColor: col.color, backgroundColor: col.bg }}
            >
              {/* En-tête colonne */}
              <div
                className="flex items-center gap-3 px-6 py-3"
                style={{ backgroundColor: col.color }}
              >
                <span className="text-white text-2xl font-bold">{col.icon}</span>
                <span className="font-['Poppins'] font-bold text-white text-[1rem] uppercase tracking-wide">
                  {col.label}
                </span>
              </div>

              {/* Items */}
              <div className="flex-1 flex flex-col justify-center px-6 py-4 gap-3">
                {col.items.map((item, j) => (
                  <div key={j} className="flex items-start gap-3">
                    <div
                      className="mt-1 w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold text-white"
                      style={{ backgroundColor: col.color }}
                    >
                      {j + 1}
                    </div>
                    <p className="font-['Poppins'] text-[0.9rem] text-[#2d241e] leading-snug">
                      {item}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Séparateur VS (sauf après la dernière colonne) */}
            {i < cols.length - 1 && (
              <div className="flex items-center justify-center w-10 flex-shrink-0">
                <div className="flex flex-col items-center gap-1">
                  <div className="w-px flex-1 bg-[#CBD5E1]" />
                  <span className="font-['Fredoka'] text-[1.1rem] font-bold text-[#94A3B8] px-2">VS</span>
                  <div className="w-px flex-1 bg-[#CBD5E1]" />
                </div>
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
    </div>
  </div>
);

export default ComparisonTemplate;
