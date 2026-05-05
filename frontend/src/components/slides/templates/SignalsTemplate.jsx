import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// signals: [{ icon, label, desc, strength: 1-3 }]
const SignalsTemplate = ({
  title = 'Comment reconnaître le moment de décision',
  eyebrow = 'Signaux d\'achat',
  accentColor = '#3FA6A0',
  signals = [
    {
      icon: '🔇',
      label: 'Moins de questions défensives',
      desc: 'Le client arrête de chercher des failles. Il n\'interroge plus chaque point technique.',
      strength: 2,
    },
    {
      icon: '✋',
      label: 'Il affirme son besoin',
      desc: '"Ce serait vraiment utile pour mon équipe." Il se projette dans l\'usage du produit.',
      strength: 3,
    },
    {
      icon: '💬',
      label: 'Il parle de prix',
      desc: 'C\'est le signal décisif — on ne négocie que ce qu\'on a décidé d\'acheter.',
      strength: 3,
    },
    {
      icon: '📅',
      label: 'Il évoque un calendrier',
      desc: '"On pourrait démarrer en septembre." Il intègre votre solution dans son futur.',
      strength: 2,
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-5 gap-4">
      <div className="flex flex-col items-center gap-1">
        <span className="font-['Poppins'] text-[0.75rem] font-bold uppercase tracking-[0.2em] text-[#888]">{eyebrow}</span>
        <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase leading-tight text-center">
          {title}
        </h1>
      </div>

      {/* Signal cards */}
      <div className="flex-1 grid grid-cols-2 gap-4">
        {signals.map((sig, i) => (
          <div
            key={i}
            className="bg-white rounded-2xl border-2 p-5 flex gap-4 items-start"
            style={{ borderColor: accentColor }}
          >
            {/* Numéro + icône */}
            <div className="flex flex-col items-center gap-2 flex-shrink-0">
              <div
                className="w-12 h-12 rounded-2xl flex items-center justify-center text-2xl"
                style={{ backgroundColor: `${accentColor}20` }}
              >
                {sig.icon}
              </div>
              <span
                className="font-['Fredoka'] text-[1.5rem] font-bold"
                style={{ color: accentColor }}
              >
                #{i + 1}
              </span>
            </div>

            <div className="flex-1">
              <div
                className="font-['Poppins'] font-bold text-[0.95rem] text-[#2d241e] mb-1"
              >
                {sig.label}
              </div>
              <p className="font-['Poppins'] text-[0.82rem] text-[#555] leading-snug mb-2">
                {sig.desc}
              </p>
              {/* Force du signal */}
              <div className="flex gap-1">
                <span className="font-['Poppins'] text-[0.7rem] text-[#888] uppercase tracking-wide mr-1">Force :</span>
                {[1, 2, 3].map(level => (
                  <div
                    key={level}
                    className="w-5 h-2 rounded-full"
                    style={{ backgroundColor: level <= sig.strength ? accentColor : '#E2E8F0' }}
                  />
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default SignalsTemplate;
