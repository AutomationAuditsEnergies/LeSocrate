import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const SelfManagementTemplate = ({
  title = 'Gérer sa propre énergie émotionnelle',
  subtitle = 'Vous ne pouvez pas être empathique si vous êtes vous-même en surcharge.',
  signals = [
    { icon: '😤', text: 'Irritabilité inhabituelle entre deux appels' },
    { icon: '😶', text: 'Réponses plus courtes, moins d\'écoute active' },
    { icon: '🧠', text: 'Difficulté à sortir d\'un échange difficile' },
    { icon: '😴', text: 'Fatigue qui arrive plus tôt que d\'habitude' },
    { icon: '⚡', text: 'Sur-réaction à des situations anodines' },
  ],
  techniques = [
    {
      name: 'La respiration 4-7-8',
      desc: 'Inspirez 4 sec, retenez 7, expirez 8. Active le système parasympathique en 2 cycles.',
      color: '#3FA6A0',
    },
    {
      name: 'Le sas entre deux appels',
      desc: 'Entre deux contacts difficiles : cet échange est terminé / j\'ai fait mon travail / page blanche.',
      color: '#F4A332',
    },
    {
      name: 'Le rituel de déconnexion',
      desc: 'Se lever, faire quelques pas, regarder par la fenêtre. Briser le cycle de surcharge avant le prochain appel.',
      color: '#A7B85A',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <div className="text-center">
        <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold uppercase">{title}</h1>
        {subtitle && <p className="font-['Poppins'] text-[0.85rem] text-[#666] mt-1 italic">{subtitle}</p>}
      </div>

      <div className="flex-1 flex gap-6">
        {/* Signaux de surcharge */}
        <div className="flex-1 rounded-2xl overflow-hidden border-2 border-[#E07A6F] flex flex-col">
          <div className="px-5 py-3 bg-[#E07A6F] flex items-center gap-2">
            <span className="text-xl">🚨</span>
            <span className="font-['Poppins'] font-bold text-white text-[0.9rem] uppercase tracking-wide">
              Signaux de surcharge
            </span>
          </div>
          <div className="flex-1 bg-[#FFF4F2] px-5 py-3 flex flex-col justify-center gap-2">
            {signals.map((s, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="text-xl flex-shrink-0">{s.icon}</span>
                <p className="font-['Poppins'] text-[0.83rem] text-[#2d241e]">{s.text}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Flèche */}
        <div className="flex items-center justify-center w-10 flex-shrink-0">
          <svg viewBox="0 0 24 24" className="w-8 h-8 text-[#CBD5E1]" fill="currentColor">
            <path d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6-1.41-1.41z" />
          </svg>
        </div>

        {/* Techniques de régulation */}
        <div className="flex-1 flex flex-col gap-2">
          <div className="font-['Poppins'] font-bold text-[0.75rem] uppercase tracking-wide text-center text-[#888] mb-1">
            Techniques de régulation
          </div>
          {techniques.map((t, i) => (
            <div
              key={i}
              className="flex-1 rounded-2xl border-2 flex overflow-hidden"
              style={{ borderColor: t.color }}
            >
              <div className="w-2 flex-shrink-0" style={{ backgroundColor: t.color }} />
              <div className="flex-1 bg-white px-4 py-2.5 flex flex-col justify-center">
                <div className="font-['Poppins'] font-bold text-[0.88rem]" style={{ color: t.color }}>
                  {t.name}
                </div>
                <p className="font-['Poppins'] text-[0.8rem] text-[#444] leading-snug mt-0.5">{t.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  </div>
);

export default SelfManagementTemplate;
