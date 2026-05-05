import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const PALETTE = ['#F4A332', '#7FCFC9', '#3FA6A0', '#A7B85A', '#E07A6F'];

// tools: [{ icon, name, desc, when }]
const ToolkitTemplate = ({
  title = 'Les 5 leviers de négociation',
  subtitle = 'Chaque levier peut débloquer une situation. Utilisez-les dans l\'ordre, pas tous à la fois.',
  tools = [
    {
      icon: '📊',
      name: 'Le volume',
      desc: 'Ajuster la quantité ou la fréquence de la commande.',
      when: 'Si le prix est le frein principal',
    },
    {
      icon: '💳',
      name: 'Le paiement',
      desc: 'Proposer un étalement ou un paiement différé sans modifier le montant.',
      when: 'Si le problème est la trésorerie',
    },
    {
      icon: '⏱️',
      name: 'Le délai',
      desc: 'Ajuster les échéances de livraison ou de mise en service.',
      when: 'Si le calendrier bloque la décision',
    },
    {
      icon: '📄',
      name: 'La contractualisation',
      desc: 'Durée d\'engagement, clauses de sortie, garanties.',
      when: 'Si le client a peur de s\'engager',
    },
    {
      icon: '🔄',
      name: 'L\'alternative produit',
      desc: 'Proposer une version différente mieux adaptée au contexte.',
      when: 'Si le produit actuel ne "colle" pas',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <div className="text-center">
        <div className="inline-flex items-center gap-2 bg-[#2d241e] text-white px-4 py-1.5 rounded-full mb-2">
          <span className="text-lg">🧰</span>
          <span className="font-['Poppins'] font-bold text-[0.8rem] uppercase tracking-wide">Boîte à outils</span>
        </div>
        <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase leading-tight">{title}</h1>
        {subtitle && <p className="font-['Poppins'] text-[0.82rem] text-[#666] mt-1">{subtitle}</p>}
      </div>

      <div className="flex-1 flex gap-3 items-stretch">
        {tools.map((tool, i) => {
          const color = PALETTE[i % PALETTE.length];
          return (
            <div
              key={i}
              className="flex-1 flex flex-col rounded-2xl overflow-hidden border-2"
              style={{ borderColor: color }}
            >
              {/* Header outil */}
              <div className="px-4 py-3 flex flex-col items-center gap-1" style={{ backgroundColor: `${color}20` }}>
                <div
                  className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl"
                  style={{ backgroundColor: color }}
                >
                  <span>{tool.icon}</span>
                </div>
                <span className="font-['Poppins'] font-bold text-[0.88rem] text-center" style={{ color }}>
                  {tool.name}
                </span>
              </div>

              {/* Contenu */}
              <div className="flex-1 bg-white px-4 py-3 flex flex-col gap-2 justify-center">
                <p className="font-['Poppins'] text-[0.82rem] text-[#333] leading-snug text-center">
                  {tool.desc}
                </p>
                <div
                  className="rounded-lg px-3 py-1.5 text-center"
                  style={{ backgroundColor: `${color}15` }}
                >
                  <span className="font-['Poppins'] text-[0.72rem] font-bold uppercase tracking-wide" style={{ color }}>
                    Quand →
                  </span>
                  <p className="font-['Poppins'] text-[0.75rem] text-[#444] mt-0.5">{tool.when}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  </div>
);

export default ToolkitTemplate;
