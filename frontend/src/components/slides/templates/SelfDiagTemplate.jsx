import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// traits: [{ label, leftPole, rightPole, defaultPosition: 0-100, color }]
const SelfDiagTemplate = ({
  title = 'Mon profil vocal — où en suis-je ?',
  subtitle = 'Pas un jugement, une observation. Chaque tendance s\'entraîne.',
  intro = 'Positionnez-vous honnêtement sur chaque axe. L\'objectif : identifier votre tendance principale, pas vos points faibles.',
  traits = [
    { label: 'Débit', leftPole: 'Trop lent', rightPole: 'Trop rapide', defaultPosition: 72, color: '#3FA6A0' },
    { label: 'Intonation', leftPole: 'Monocorde', rightPole: 'Surexpressive', defaultPosition: 30, color: '#F4A332' },
    { label: 'Articulation', leftPole: 'Relâchée', rightPole: 'Trop scolaire', defaultPosition: 55, color: '#A7B85A' },
    { label: 'Volume', leftPole: 'Trop faible', rightPole: 'Trop fort', defaultPosition: 45, color: '#7FCFC9' },
    { label: 'Chaleur', leftPole: 'Froid / admin', rightPole: 'Trop proche', defaultPosition: 35, color: '#E07A6F' },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex gap-8 px-10 py-5">
      {/* Intro */}
      <div className="w-56 flex-shrink-0 flex flex-col justify-center gap-4">
        <h1 className="font-['Fredoka'] text-[1.6rem] text-[#2d241e] font-bold uppercase leading-tight">{title}</h1>
        {subtitle && <p className="font-['Poppins'] text-[0.8rem] text-[#888] italic">{subtitle}</p>}
        <div className="bg-[#2d241e] rounded-xl px-4 py-3">
          <p className="font-['Poppins'] text-[0.78rem] text-white leading-snug">{intro}</p>
        </div>
        <div className="flex items-center gap-2 mt-2">
          <div className="w-3 h-3 rounded-full bg-[#3FA6A0]" />
          <span className="font-['Poppins'] text-[0.72rem] text-[#666]">Zone optimale = centre</span>
        </div>
      </div>

      {/* Sliders */}
      <div className="flex-1 flex flex-col justify-center gap-4">
        {traits.map((trait, i) => (
          <div key={i} className="flex items-center gap-4">
            {/* Label */}
            <div className="w-24 flex-shrink-0">
              <span className="font-['Poppins'] font-bold text-[0.85rem] text-[#2d241e]">{trait.label}</span>
            </div>

            {/* Pôle gauche */}
            <span className="font-['Poppins'] text-[0.72rem] text-[#DC2626] w-20 text-right flex-shrink-0">
              {trait.leftPole}
            </span>

            {/* Track */}
            <div className="flex-1 relative h-6 flex items-center">
              {/* Zone optimale (centre) */}
              <div
                className="absolute h-full rounded-full opacity-20"
                style={{
                  left: '35%',
                  width: '30%',
                  backgroundColor: trait.color,
                }}
              />
              {/* Barre */}
              <div className="absolute left-0 right-0 h-2 rounded-full bg-[#E2E8F0]" />
              {/* Curseur */}
              <div
                className="absolute w-5 h-5 rounded-full border-3 border-white shadow-md -translate-x-1/2"
                style={{
                  left: `${trait.defaultPosition}%`,
                  backgroundColor: trait.color,
                  border: '3px solid white',
                }}
              />
            </div>

            {/* Pôle droit */}
            <span className="font-['Poppins'] text-[0.72rem] text-[#DC2626] w-20 flex-shrink-0">
              {trait.rightPole}
            </span>
          </div>
        ))}

        {/* Légende zone optimale */}
        <div className="flex items-center gap-2 mt-2">
          <div className="h-3 w-16 rounded-full opacity-40 bg-[#3FA6A0]" />
          <span className="font-['Poppins'] text-[0.72rem] text-[#888]">Zone optimale (entre les deux extrêmes)</span>
        </div>
      </div>
    </div>
  </div>
);

export default SelfDiagTemplate;
