import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// sections: [{ title, color, items: [{ text, checked }] }]
const ChecklistTemplate = ({
  title = 'Qualification prospect — avant de décrocher',
  sections = [
    {
      title: 'La cible',
      color: '#3FA6A0',
      items: [
        { text: 'Qui est ce prospect ? (secteur, taille, rôle)', checked: true },
        { text: 'Quel est son enjeu probable ?', checked: true },
        { text: 'A-t-il déjà été contacté ? Par qui ?', checked: false },
      ],
    },
    {
      title: 'L\'accroche',
      color: '#F4A332',
      items: [
        { text: 'Mon angle de valeur unique est identifié', checked: true },
        { text: 'Les 3 parties de l\'accroche sont prêtes (qui / pourquoi / bénéfice)', checked: true },
        { text: 'J\'ai un scénario flexible si la conversation dévie', checked: false },
      ],
    },
    {
      title: 'La conclusion',
      color: '#A7B85A',
      items: [
        { text: 'Je sais quelle action concrète je veux obtenir', checked: true },
        { text: 'J\'ai 2 créneaux prêts à proposer', checked: false },
        { text: 'Je sais comment formuler un refus poliment', checked: false },
      ],
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase text-center">
        {title}
      </h1>

      <div className="flex-1 flex gap-4">
        {sections.map((sec, i) => (
          <div key={i} className="flex-1 flex flex-col rounded-2xl overflow-hidden border-2" style={{ borderColor: sec.color }}>
            {/* Section header */}
            <div className="px-4 py-2.5 flex items-center gap-2" style={{ backgroundColor: sec.color }}>
              <span className="font-['Fredoka'] text-white text-[1.1rem] font-bold">{sec.title}</span>
            </div>

            {/* Items */}
            <div className="flex-1 bg-white px-4 py-3 flex flex-col gap-2.5">
              {sec.items.map((item, j) => (
                <div key={j} className="flex items-start gap-3">
                  {/* Checkbox */}
                  <div
                    className="w-5 h-5 rounded flex-shrink-0 mt-0.5 flex items-center justify-center border-2"
                    style={{
                      backgroundColor: item.checked ? sec.color : 'transparent',
                      borderColor: sec.color,
                    }}
                  >
                    {item.checked && (
                      <svg viewBox="0 0 12 12" className="w-3 h-3" fill="none">
                        <path d="M2 6l3 3 5-5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                  </div>
                  <p
                    className="font-['Poppins'] text-[0.83rem] leading-snug"
                    style={{
                      color: item.checked ? '#888' : '#2d241e',
                      textDecoration: item.checked ? 'line-through' : 'none',
                    }}
                  >
                    {item.text}
                  </p>
                </div>
              ))}
            </div>

            {/* Compteur */}
            <div className="px-4 py-2 border-t" style={{ borderColor: sec.color }}>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 rounded-full bg-[#E2E8F0]">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(sec.items.filter(it => it.checked).length / sec.items.length) * 100}%`,
                      backgroundColor: sec.color,
                    }}
                  />
                </div>
                <span className="font-['Poppins'] text-[0.72rem] text-[#666]">
                  {sec.items.filter(it => it.checked).length}/{sec.items.length}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default ChecklistTemplate;
