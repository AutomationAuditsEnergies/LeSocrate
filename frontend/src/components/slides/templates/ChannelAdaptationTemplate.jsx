import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// channels: [{ name, icon, color, cells: { [criterion]: value } }]
// criteria: [string]
const ChannelAdaptationTemplate = ({
  title = 'Adapter son message selon le canal',
  criteria = ['Ton', 'Longueur', 'Règle clé', 'À éviter'],
  channels = [
    {
      name: 'Téléphone',
      icon: '📞',
      color: '#3FA6A0',
      cells: {
        'Ton': 'Chaleureux, rythmé, expressif',
        'Longueur': 'Phrases courtes, pauses régulières',
        'Règle clé': 'Les 10 premières secondes décident de tout',
        'À éviter': 'Débit trop rapide, voix monocorde',
      },
    },
    {
      name: 'Chat',
      icon: '💬',
      color: '#7FCFC9',
      cells: {
        'Ton': 'Direct, humain, mais concis',
        'Longueur': 'Max 3 lignes par message',
        'Règle clé': 'Réponse en moins de 90 secondes',
        'À éviter': 'Blocs de texte longs, majuscules',
      },
    },
    {
      name: 'Email',
      icon: '📧',
      color: '#F4A332',
      cells: {
        'Ton': 'Professionnel, orienté client',
        'Longueur': 'Objet précis + corps structuré',
        'Règle clé': 'Commencer par "Vous" jamais par "Je"',
        'À éviter': 'Fautes, formules vagues, CC inutile',
      },
    },
    {
      name: 'SMS',
      icon: '📱',
      color: '#A7B85A',
      cells: {
        'Ton': 'Ultra-concis, formel malgré tout',
        'Longueur': 'Max 160 caractères, 1 seule information',
        'Règle clé': 'Toujours inclure le numéro de dossier',
        'À éviter': 'Abréviations, emojis, plusieurs infos',
      },
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <h1 className="font-['Fredoka'] text-[1.9rem] text-[#2d241e] font-bold uppercase text-center">
        {title}
      </h1>

      {/* Table */}
      <div className="flex-1 rounded-xl overflow-hidden border border-[#E2E8F0]">
        {/* Column headers */}
        <div className="flex bg-[#2d241e]">
          <div className="w-28 flex-shrink-0 px-4 py-2 border-r border-white/10" />
          {channels.map((ch, i) => (
            <div
              key={i}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-2 border-r border-white/10 last:border-0"
            >
              <span className="text-xl">{ch.icon}</span>
              <span className="font-['Poppins'] font-bold text-white text-[0.85rem]">{ch.name}</span>
            </div>
          ))}
        </div>

        {/* Data rows */}
        {criteria.map((crit, ri) => (
          <div
            key={ri}
            className="flex border-t border-[#E2E8F0]"
            style={{ backgroundColor: ri % 2 === 0 ? 'white' : '#F8FAFC' }}
          >
            {/* Criterion label */}
            <div className="w-28 flex-shrink-0 px-4 py-3 border-r border-[#E2E8F0] flex items-center">
              <span className="font-['Poppins'] font-bold text-[0.8rem] text-[#2d241e] uppercase tracking-wide">
                {crit}
              </span>
            </div>
            {/* Cell per channel */}
            {channels.map((ch, ci) => (
              <div
                key={ci}
                className="flex-1 px-4 py-3 border-r border-[#E2E8F0] last:border-0 flex items-center"
              >
                <p className="font-['Poppins'] text-[0.8rem] text-[#333] leading-snug">
                  {ch.cells[crit] || '—'}
                </p>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default ChannelAdaptationTemplate;
