import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const QuotableTemplate = ({
  quote = 'Comprendre d\'abord.\nAdapter ensuite.\nPuis agir.',
  author = null,
  accentColor = '#F4A332',
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => {
  const lines = quote.split('\n');

  return (
    <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
      <Header badge={badge} brandName={brandName} />

      <div className="flex-1 flex flex-col items-center justify-center px-16 py-8 relative">
        {/* Guillemet décoratif haut gauche */}
        <div
          className="absolute top-6 left-10 font-['Fredoka'] text-[9rem] leading-none select-none opacity-15"
          style={{ color: accentColor }}
        >
          "
        </div>

        {/* Guillemet décoratif bas droite */}
        <div
          className="absolute bottom-2 right-10 font-['Fredoka'] text-[9rem] leading-none select-none opacity-15"
          style={{ color: accentColor }}
        >
          "
        </div>

        {/* Ligne accent haut */}
        <div className="w-16 h-1 rounded-full mb-8" style={{ backgroundColor: accentColor }} />

        {/* Citation */}
        <div className="text-center z-10">
          {lines.map((line, i) => (
            <div
              key={i}
              className="font-['Fredoka'] font-bold text-[#2d241e] uppercase leading-tight"
              style={{ fontSize: lines.length <= 2 ? '3.2rem' : '2.6rem' }}
            >
              {line}
            </div>
          ))}
        </div>

        {/* Ligne accent bas */}
        <div className="w-16 h-1 rounded-full mt-8" style={{ backgroundColor: accentColor }} />

        {/* Attribution optionnelle */}
        {author && (
          <p className="font-['Poppins'] text-[0.85rem] text-[#888] mt-4 uppercase tracking-widest">
            — {author}
          </p>
        )}
      </div>
    </div>
  );
};

export default QuotableTemplate;
