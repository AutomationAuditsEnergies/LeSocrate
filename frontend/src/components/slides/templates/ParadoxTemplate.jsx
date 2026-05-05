import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const ParadoxTemplate = ({
  label = 'Le paradoxe du silence',
  poleA = {
    context: 'À l\'écrit',
    statement: 'Le silence n\'existe pas.',
    sub: 'Une pause sur une page, c\'est du vide — personne ne la ressent.',
    color: '#CBD5E1',
    bg: '#F1F5F9',
  },
  poleB = {
    context: 'À l\'oral',
    statement: 'Le silence est une ressource.',
    sub: 'Une pause de 2 secondes marque, souligne, crée du suspense. Le client s\'arrête d\'écrire pour écouter.',
    color: '#3FA6A0',
    bg: '#E6F7F6',
  },
  resolution = 'Les silences calibrés à l\'oral remplacent les caractères gras à l\'écrit. Utilisez-les après vos phrases clés.',
  accentColor = '#F4A332',
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col items-center justify-center px-12 py-6 gap-5">
      {/* Label paradoxe */}
      <div className="flex items-center gap-3">
        <div className="h-px flex-1 w-16 bg-[#CBD5E1]" />
        <span
          className="font-['Poppins'] font-bold text-[0.75rem] uppercase tracking-[0.2em] px-4 py-1 rounded-full text-white"
          style={{ backgroundColor: accentColor }}
        >
          {label}
        </span>
        <div className="h-px flex-1 w-16 bg-[#CBD5E1]" />
      </div>

      {/* Les deux pôles */}
      <div className="flex gap-6 w-full">
        {/* Pôle A */}
        <div
          className="flex-1 rounded-2xl p-6 border-2 flex flex-col gap-3"
          style={{ borderColor: poleA.color, backgroundColor: poleA.bg }}
        >
          <div className="font-['Poppins'] text-[0.75rem] font-bold uppercase tracking-wide text-[#888]">
            {poleA.context}
          </div>
          <p
            className="font-['Fredoka'] text-[1.7rem] font-bold leading-tight"
            style={{ color: '#2d241e' }}
          >
            {poleA.statement}
          </p>
          <p className="font-['Poppins'] text-[0.85rem] text-[#666] leading-snug">{poleA.sub}</p>
        </div>

        {/* VS / Mais */}
        <div className="flex-shrink-0 w-16 flex items-center justify-center">
          <div className="flex flex-col items-center gap-2">
            <div className="h-12 w-px bg-[#E2E8F0]" />
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center font-['Fredoka'] text-white font-bold text-lg"
              style={{ backgroundColor: accentColor }}
            >
              ≠
            </div>
            <div className="h-12 w-px bg-[#E2E8F0]" />
          </div>
        </div>

        {/* Pôle B */}
        <div
          className="flex-1 rounded-2xl p-6 border-2 flex flex-col gap-3"
          style={{ borderColor: poleB.color, backgroundColor: poleB.bg }}
        >
          <div className="font-['Poppins'] text-[0.75rem] font-bold uppercase tracking-wide" style={{ color: poleB.color }}>
            {poleB.context}
          </div>
          <p
            className="font-['Fredoka'] text-[1.7rem] font-bold leading-tight"
            style={{ color: poleB.color }}
          >
            {poleB.statement}
          </p>
          <p className="font-['Poppins'] text-[0.85rem] text-[#444] leading-snug">{poleB.sub}</p>
        </div>
      </div>

      {/* Résolution */}
      <div
        className="w-full rounded-2xl px-6 py-3 border-2 flex items-center gap-4"
        style={{ borderColor: accentColor, backgroundColor: `${accentColor}15` }}
      >
        <span className="font-['Fredoka'] text-[1.8rem]" style={{ color: accentColor }}>→</span>
        <p className="font-['Poppins'] text-[0.9rem] text-[#2d241e] font-semibold leading-snug">{resolution}</p>
      </div>
    </div>
  </div>
);

export default ParadoxTemplate;
