import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// groups: [{ label, emoji, color, bg, signals: [string], posture, phrase }]
const SignalRadarTemplate = ({
  title = 'Lire un client en 30 secondes',
  groups = [
    {
      label: 'Client fragile',
      emoji: '🕊️',
      color: '#7FCFC9',
      bg: '#EEF9F9',
      signals: [
        'Voix hésitante, débit lent',
        'Questions répétées sur le même point',
        'Formules d\'excuse fréquentes ("je sais pas si...")',
        'Cherche une validation avant d\'avancer',
        'Réagit fort à un ton sec ou pressé',
      ],
      posture: 'Ralentissez. Guidez. Rassurez avant d\'informer.',
      phrase: '"Prenez le temps — c\'est important de bien comprendre avant d\'avancer."',
    },
    {
      label: 'Client difficile',
      emoji: '⚡',
      color: '#E07A6F',
      bg: '#FDF4F3',
      signals: [
        'Ton tranchant, phrases courtes',
        'Interrompt avant la fin de votre réponse',
        '"C\'est pas ma faute", "ça fait des semaines"',
        'Exige une solution immédiate',
        'Menace de partir ou d\'escalader',
      ],
      posture: 'Ne synchronisez pas avec l\'agressivité. Ralentissez votre propre rythme.',
      phrase: '"Je comprends votre impatience — je vais tout faire pour régler ça."',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase text-center leading-tight">
        {title}
      </h1>

      <div className="flex-1 flex gap-5">
        {groups.map((g, i) => (
          <div
            key={i}
            className="flex-1 rounded-2xl overflow-hidden border-2 flex flex-col"
            style={{ borderColor: g.color, backgroundColor: g.bg }}
          >
            {/* Header */}
            <div className="flex items-center gap-3 px-5 py-3" style={{ backgroundColor: g.color }}>
              <span className="text-2xl">{g.emoji}</span>
              <span className="font-['Fredoka'] text-white text-[1.3rem] font-bold">{g.label}</span>
            </div>

            <div className="flex-1 flex flex-col px-5 py-3 gap-3">
              {/* Signaux */}
              <div>
                <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wider text-[#666] mb-1.5">
                  Ce que vous entendez/observez
                </div>
                <div className="flex flex-col gap-1.5">
                  {g.signals.map((sig, j) => (
                    <div key={j} className="flex items-start gap-2">
                      <div
                        className="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5"
                        style={{ backgroundColor: g.color }}
                      />
                      <span className="font-['Poppins'] text-[0.82rem] text-[#333]">{sig}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Posture */}
              <div
                className="rounded-xl px-4 py-2.5 border-2 bg-white"
                style={{ borderColor: g.color }}
              >
                <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wide mb-1" style={{ color: g.color }}>
                  Votre posture
                </div>
                <p className="font-['Poppins'] text-[0.82rem] text-[#2d241e] font-semibold leading-snug">{g.posture}</p>
              </div>

              {/* Phrase clé */}
              <div className="mt-auto">
                <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wide text-[#888] mb-1">
                  Phrase d\'ouverture
                </div>
                <p className="font-['Poppins'] text-[0.82rem] text-[#2d241e] italic leading-snug">{g.phrase}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default SignalRadarTemplate;
