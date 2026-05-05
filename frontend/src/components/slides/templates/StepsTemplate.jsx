import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const PALETTE = ['#F4A332', '#7FCFC9', '#3FA6A0', '#A7B85A', '#E07A6F'];

const StepsTemplate = ({
  title = 'Le diagnostic systématique en 4 étapes',
  subtitle = 'Avant de proposer une solution, comprendre est obligatoire.',
  steps = [
    {
      title: 'Du flou au factuel',
      desc: 'Reformulez le problème en termes concrets. Posez des questions ouvertes pour sortir de l\'imprécis.',
    },
    {
      title: 'Explorer les causes',
      desc: 'Listez toutes les origines possibles (outil : arbre Ishikawa). Ne sautez pas aux conclusions.',
    },
    {
      title: 'Formuler des hypothèses',
      desc: 'Max 3-4 hypothèses plausibles. Priorisez par probabilité et facilité de vérification.',
    },
    {
      title: 'Vérifier et agir',
      desc: 'Testez dans l\'ordre. La première validée devient votre plan d\'action. Confirmez avec le client.',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col items-center px-10 py-5 gap-3">
      <div className="text-center">
        <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase leading-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="font-['Poppins'] text-[0.9rem] text-[#666] mt-1">{subtitle}</p>
        )}
      </div>

      {/* Steps */}
      <div className="flex-1 w-full flex items-center gap-0">
        {steps.map((step, i) => {
          const color = PALETTE[i % PALETTE.length];
          const isLast = i === steps.length - 1;
          return (
            <React.Fragment key={i}>
              <div className="flex-1 flex flex-col items-center gap-3">
                {/* Numéro */}
                <div
                  className="w-14 h-14 rounded-full flex items-center justify-center text-white font-['Fredoka'] text-[1.6rem] font-bold shadow-md flex-shrink-0"
                  style={{ backgroundColor: color }}
                >
                  {i + 1}
                </div>

                {/* Carte */}
                <div
                  className="w-full rounded-2xl p-4 border-2 flex flex-col gap-2"
                  style={{ borderColor: color, backgroundColor: `${color}18` }}
                >
                  <div
                    className="font-['Poppins'] font-bold text-[0.95rem] text-center"
                    style={{ color }}
                  >
                    {step.title}
                  </div>
                  <p className="font-['Poppins'] text-[0.82rem] text-[#444] text-center leading-snug">
                    {step.desc}
                  </p>
                </div>
              </div>

              {/* Flèche entre étapes */}
              {!isLast && (
                <div className="flex-shrink-0 w-8 flex items-center justify-center">
                  <svg viewBox="0 0 24 24" className="w-6 h-6 text-[#94A3B8]" fill="currentColor">
                    <path d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6-1.41-1.41z" />
                  </svg>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Barre de progression */}
      <div className="w-full flex gap-1">
        {steps.map((_, i) => (
          <div
            key={i}
            className="flex-1 h-1.5 rounded-full"
            style={{ backgroundColor: PALETTE[i % PALETTE.length] }}
          />
        ))}
      </div>
    </div>
  </div>
);

export default StepsTemplate;
