import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const ProfilesTemplate = ({
  title = 'Les 3 profils de prospects',
  profiles = [
    {
      name: 'L\'Expert',
      emoji: '🎯',
      color: '#3FA6A0',
      bg: '#E6F7F6',
      signals: ['Coupe la parole', 'Jargon technique', 'Compare avec des concurrents', 'Veut aller vite'],
      posture: 'Respectez son niveau. Soyez direct, factuel, sans sur-expliquer.',
      phrase: '"D\'après vos expériences passées, qu\'est-ce qui vous a manqué ?"',
    },
    {
      name: 'Le Novice',
      emoji: '🌱',
      color: '#A7B85A',
      bg: '#F3F7E6',
      signals: ['Beaucoup de questions basiques', 'Hésite avant de répondre', 'Cherche à comprendre', 'Vocabulaire simple'],
      posture: 'Ralentissez. Vulgarisez sans condescendance. Guidez étape par étape.',
      phrase: '"Je vous explique d\'abord comment ça fonctionne, et on voit ensemble ce qui vous correspond."',
    },
    {
      name: 'Le Pressé',
      emoji: '⚡',
      color: '#F4A332',
      bg: '#FFF8ED',
      signals: ['Interruptions fréquentes', '"On peut aller à l\'essentiel ?"', 'Répond par oui/non', 'Agenda chargé visible'],
      posture: 'Soyez concis. Pitch en 30 secondes. Proposez le créneau avant qu\'il coupe.',
      phrase: '"En 2 minutes : voici ce que vous gagnez et voici la prochaine étape."',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] font-bold text-center uppercase">
        {title}
      </h1>

      <div className="flex-1 flex gap-4 items-stretch">
        {profiles.map((p, i) => (
          <div
            key={i}
            className="flex-1 rounded-2xl flex flex-col overflow-hidden border-2"
            style={{ borderColor: p.color, backgroundColor: p.bg }}
          >
            {/* En-tête profil */}
            <div className="flex items-center gap-3 px-5 py-3" style={{ backgroundColor: p.color }}>
              <span className="text-3xl">{p.emoji}</span>
              <span className="font-['Fredoka'] text-white text-[1.3rem] font-bold">{p.name}</span>
            </div>

            <div className="flex-1 flex flex-col px-5 py-3 gap-3">
              {/* Signaux */}
              <div>
                <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wider text-[#666] mb-1">
                  Signaux de reconnaissance
                </div>
                <div className="flex flex-col gap-1">
                  {p.signals.map((s, j) => (
                    <div key={j} className="flex items-start gap-2">
                      <span className="text-[0.8rem]" style={{ color: p.color }}>▸</span>
                      <span className="font-['Poppins'] text-[0.8rem] text-[#333]">{s}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Posture */}
              <div className="rounded-lg px-3 py-2 bg-white border" style={{ borderColor: p.color }}>
                <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wider mb-1" style={{ color: p.color }}>
                  Votre posture
                </div>
                <p className="font-['Poppins'] text-[0.82rem] text-[#2d241e] leading-snug">{p.posture}</p>
              </div>

              {/* Phrase clé */}
              <div className="mt-auto">
                <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wider text-[#666] mb-1">
                  Phrase clé
                </div>
                <p className="font-['Poppins'] text-[0.82rem] text-[#2d241e] italic leading-snug">{p.phrase}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  </div>
);

export default ProfilesTemplate;
