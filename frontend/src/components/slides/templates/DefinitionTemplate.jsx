import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const DefinitionTemplate = ({
  term = "L'empathie authentique",
  eyebrow = 'Définition',
  definition = "Reconnaître l'émotion du client comme étant légitime. Se dire : cette personne ressent quelque chose, et cette émotion est justifiée par sa situation.",
  isItems = [
    "Reconnaître l'état émotionnel sans le partager",
    "Valider que la réaction du client est justifiée",
    "Maintenir une posture professionnelle et stable",
  ],
  isNotItems = [
    "De la pitié (regarder l'autre de haut en bas)",
    "De la complaisance (tout accepter au nom de la compréhension)",
    "Ressentir exactement ce que le client ressent",
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-12 py-5 gap-4">
      {/* Terme */}
      <div className="flex flex-col items-center gap-1">
        <span className="font-['Poppins'] text-[0.75rem] font-bold uppercase tracking-[0.2em] text-[#888]">{eyebrow}</span>
        <div className="bg-[#2d241e] text-white font-['Fredoka'] text-[2.4rem] font-bold px-8 py-2 rounded-xl uppercase">
          {term}
        </div>
      </div>

      {/* Définition centrale */}
      <div className="bg-white border-l-4 border-[#3FA6A0] rounded-r-xl px-6 py-3">
        <p className="font-['Poppins'] text-[1rem] text-[#2d241e] italic leading-relaxed">
          « {definition} »
        </p>
      </div>

      {/* Deux colonnes */}
      <div className="flex-1 flex gap-5">
        {/* C'est... */}
        <div className="flex-1 rounded-2xl overflow-hidden border-2 border-[#16A34A] bg-[#F0FDF4] flex flex-col">
          <div className="bg-[#16A34A] px-5 py-2 flex items-center gap-2">
            <span className="text-white text-xl font-bold">✓</span>
            <span className="font-['Poppins'] font-bold text-white text-[0.9rem] uppercase tracking-wide">C'est…</span>
          </div>
          <div className="flex-1 flex flex-col justify-center px-5 py-3 gap-2">
            {isItems.map((item, i) => (
              <div key={i} className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-[#16A34A] flex-shrink-0 mt-0.5 flex items-center justify-center">
                  <span className="text-white text-xs font-bold">✓</span>
                </div>
                <p className="font-['Poppins'] text-[0.88rem] text-[#2d241e] leading-snug">{item}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Ce n'est PAS... */}
        <div className="flex-1 rounded-2xl overflow-hidden border-2 border-[#DC2626] bg-[#FEF2F2] flex flex-col">
          <div className="bg-[#DC2626] px-5 py-2 flex items-center gap-2">
            <span className="text-white text-xl font-bold">✗</span>
            <span className="font-['Poppins'] font-bold text-white text-[0.9rem] uppercase tracking-wide">Ce n'est PAS…</span>
          </div>
          <div className="flex-1 flex flex-col justify-center px-5 py-3 gap-2">
            {isNotItems.map((item, i) => (
              <div key={i} className="flex items-start gap-3">
                <div className="w-5 h-5 rounded-full bg-[#DC2626] flex-shrink-0 mt-0.5 flex items-center justify-center">
                  <span className="text-white text-xs font-bold">✗</span>
                </div>
                <p className="font-['Poppins'] text-[0.88rem] text-[#2d241e] leading-snug">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  </div>
);

export default DefinitionTemplate;
