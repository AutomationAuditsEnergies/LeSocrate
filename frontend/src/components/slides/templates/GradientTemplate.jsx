import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// zones: [{ label, desc, color, position: 0-100, items: [string] }]
const GradientTemplate = ({
  title = 'Toutes les objections ne se valent pas',
  subtitle = 'Identifiez le type avant de répondre — votre tactique change selon la zone.',
  gradientFrom = '#16A34A',
  gradientTo = '#DC2626',
  zones = [
    {
      label: 'Objection légitime',
      color: '#16A34A',
      position: 12,
      desc: 'Le client a une vraie raison de ne pas acheter maintenant.',
      items: ['Budget absent', 'Pas de décision ce mois', 'Besoin non prioritaire'],
      tactic: 'Respectez. Planifiez un suivi à date.',
    },
    {
      label: 'Peur / Doute',
      color: '#F4A332',
      position: 50,
      desc: 'Le client veut, mais hésite. La peur freine la décision.',
      items: ['Risque perçu trop élevé', 'Manque d\'infos', 'Mauvaise expérience passée'],
      tactic: 'Rassurez avec des preuves. Réduisez le risque perçu.',
    },
    {
      label: 'Écran de fumée',
      color: '#DC2626',
      position: 88,
      desc: 'L\'objection cache autre chose — il ne veut pas vous le dire.',
      items: ['"C\'est trop cher"', '"Je dois réfléchir"', '"Rappelez-moi dans 6 mois"'],
      tactic: 'Creusez avec des questions. Ne répondez pas à l\'écran.',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-12 py-5 gap-4">
      <div className="text-center">
        <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase leading-tight">{title}</h1>
        {subtitle && <p className="font-['Poppins'] text-[0.85rem] text-[#666] mt-1">{subtitle}</p>}
      </div>

      {/* Barre gradient */}
      <div className="relative h-5 rounded-full overflow-hidden"
        style={{ background: `linear-gradient(to right, ${gradientFrom}, ${gradientTo})` }}
      >
        {zones.map((z, i) => (
          <div
            key={i}
            className="absolute top-0 -translate-x-1/2 flex flex-col items-center"
            style={{ left: `${z.position}%` }}
          >
            {/* Marqueur */}
            <div className="w-5 h-5 rounded-full border-2 border-white shadow-md" style={{ backgroundColor: z.color }} />
          </div>
        ))}
      </div>

      {/* Cartes sous la barre */}
      <div className="flex-1 flex gap-4">
        {zones.map((z, i) => (
          <div key={i} className="flex-1 rounded-2xl border-2 overflow-hidden flex flex-col" style={{ borderColor: z.color }}>
            {/* Header */}
            <div className="px-4 py-2.5 flex items-center gap-2" style={{ backgroundColor: z.color }}>
              <span className="font-['Fredoka'] text-white text-[1.1rem] font-bold">{z.label}</span>
            </div>

            <div className="flex-1 bg-white px-4 py-3 flex flex-col gap-2">
              <p className="font-['Poppins'] text-[0.82rem] text-[#555] italic leading-snug">{z.desc}</p>

              <div className="flex flex-col gap-1">
                {z.items.map((item, j) => (
                  <div key={j} className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: z.color }} />
                    <span className="font-['Poppins'] text-[0.8rem] text-[#333]">{item}</span>
                  </div>
                ))}
              </div>

              <div className="mt-auto pt-2 border-t border-[#F1F5F9]">
                <span className="font-['Poppins'] text-[0.72rem] font-bold uppercase tracking-wide" style={{ color: z.color }}>
                  Tactique →
                </span>
                <p className="font-['Poppins'] text-[0.8rem] text-[#2d241e] mt-0.5 font-semibold">{z.tactic}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default GradientTemplate;
