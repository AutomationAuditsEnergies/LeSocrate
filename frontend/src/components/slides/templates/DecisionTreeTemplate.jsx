import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// tree: root question → branches
const DecisionTreeTemplate = ({
  title = 'Choisir la bonne solution pour le client',
  root = 'Le client a-t-il les compétences en interne pour utiliser l\'outil ?',
  branches = [
    {
      condition: 'OUI',
      color: '#3FA6A0',
      question: 'Son budget est-il adapté à la solution complète ?',
      leaves: [
        { condition: 'OUI', label: 'Solution complète', desc: 'ERP ou logiciel avancé — plein potentiel.', color: '#3FA6A0' },
        { condition: 'NON', label: 'Solution modulaire', desc: 'Commencer avec le module essentiel, évoluer ensuite.', color: '#7FCFC9' },
      ],
    },
    {
      condition: 'NON',
      color: '#F4A332',
      question: 'Est-il prêt à investir dans une formation ou un accompagnement ?',
      leaves: [
        { condition: 'OUI', label: 'Solution + formation', desc: 'Outil simplifié + sessions de prise en main incluses.', color: '#F4A332' },
        { condition: 'NON', label: 'Solution légère', desc: 'Outil quasi clé en main — démarrage immédiat sans formation.', color: '#A7B85A' },
      ],
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col items-center px-10 py-4 gap-3">
      <h1 className="font-['Fredoka'] text-[1.9rem] text-[#2d241e] font-bold uppercase text-center leading-tight">
        {title}
      </h1>

      {/* Root */}
      <div className="bg-[#2d241e] text-white rounded-2xl px-8 py-3 text-center max-w-[70%]">
        <p className="font-['Poppins'] font-bold text-[0.95rem] leading-snug">{root}</p>
      </div>

      {/* Connector line down */}
      <div className="w-px h-3 bg-[#CBD5E1]" />

      {/* Branches */}
      <div className="flex-1 flex gap-6 w-full items-start">
        {branches.map((branch, i) => (
          <div key={i} className="flex-1 flex flex-col items-center gap-2">
            {/* Branch condition badge */}
            <div
              className="px-5 py-1.5 rounded-full text-white font-['Poppins'] font-bold text-[0.85rem]"
              style={{ backgroundColor: branch.color }}
            >
              {branch.condition}
            </div>

            {/* Sub-question */}
            <div
              className="w-full rounded-xl px-4 py-2.5 border-2 text-center"
              style={{ borderColor: branch.color, backgroundColor: `${branch.color}15` }}
            >
              <p className="font-['Poppins'] text-[0.82rem] text-[#2d241e] font-semibold leading-snug">
                {branch.question}
              </p>
            </div>

            {/* Connector */}
            <div className="w-px h-3 bg-[#CBD5E1]" />

            {/* Leaves */}
            <div className="flex gap-3 w-full">
              {branch.leaves.map((leaf, j) => (
                <div
                  key={j}
                  className="flex-1 rounded-xl overflow-hidden border-2"
                  style={{ borderColor: leaf.color }}
                >
                  <div
                    className="px-3 py-1.5 flex items-center gap-2"
                    style={{ backgroundColor: leaf.color }}
                  >
                    <span className="font-['Poppins'] text-white text-[0.72rem] font-bold">{leaf.condition}</span>
                    <span className="font-['Fredoka'] text-white text-[0.95rem] font-bold">{leaf.label}</span>
                  </div>
                  <div className="bg-white px-3 py-2">
                    <p className="font-['Poppins'] text-[0.78rem] text-[#444] leading-snug">{leaf.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default DecisionTreeTemplate;
