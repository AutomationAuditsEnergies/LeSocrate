import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const PracticeExerciseTemplate = ({
  title = 'Exercice : s\'écouter avec une oreille professionnelle',
  duration = '15 min',
  objective = 'Identifier votre tendance vocale dominante pour commencer à la corriger.',
  steps = [
    {
      num: 1,
      title: 'Enregistrez-vous',
      desc: 'Lisez à voix haute un paragraphe de cours ou racontez une anecdote professionnelle de 2 minutes. N\'importe quel appareil suffit.',
    },
    {
      num: 2,
      title: 'Écoutez avec distance',
      desc: 'Attendez 5 minutes, puis écoutez comme si c\'était quelqu\'un d\'autre. Votre cerveau compense automatiquement les défauts si vous écoutez trop vite.',
    },
    {
      num: 3,
      title: 'Notez vos observations',
      desc: 'Identifiez : Est-ce que mon débit est régulier ? Est-ce que mon intonation varie ? Est-ce que j\'articule clairement ?',
    },
    {
      num: 4,
      title: 'Identifiez 1 axe à travailler',
      desc: 'Un seul. Pas trois. La semaine prochaine, vous en ajouterez un autre. La surcharge détruit la progression.',
    },
  ],
  output = 'À la fin de l\'exercice : vous avez identifié votre tendance vocale principale (débit / intonation / articulation / volume).',
  accentColor = '#7FCFC9',
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      {/* Titre + meta */}
      <div className="flex items-start gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-1">
            <div className="bg-[#2d241e] text-white font-['Poppins'] font-bold text-[0.8rem] uppercase tracking-wide px-3 py-1 rounded-full">
              ✏️ Exercice pratique
            </div>
            <div className="font-['Poppins'] text-[0.8rem] text-[#888]">⏱ {duration}</div>
          </div>
          <h1 className="font-['Fredoka'] text-[1.9rem] text-[#2d241e] font-bold uppercase leading-tight">
            {title}
          </h1>
        </div>
        <div
          className="rounded-xl px-4 py-2 border-2 max-w-[260px] flex-shrink-0"
          style={{ borderColor: accentColor, backgroundColor: `${accentColor}15` }}
        >
          <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wide mb-1" style={{ color: accentColor }}>
            Objectif
          </div>
          <p className="font-['Poppins'] text-[0.8rem] text-[#2d241e] leading-snug">{objective}</p>
        </div>
      </div>

      {/* Steps */}
      <div className="flex-1 flex gap-3">
        {steps.map((step, i) => (
          <div
            key={i}
            className="flex-1 rounded-2xl overflow-hidden border-2"
            style={{ borderColor: accentColor }}
          >
            <div className="px-4 py-2 flex items-center gap-2" style={{ backgroundColor: accentColor }}>
              <span className="font-['Fredoka'] text-white text-[1.5rem] font-bold leading-none">{step.num}</span>
              <span className="font-['Poppins'] text-white text-[0.88rem] font-bold">{step.title}</span>
            </div>
            <div className="bg-white px-4 py-3">
              <p className="font-['Poppins'] text-[0.82rem] text-[#444] leading-snug">{step.desc}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Output attendu */}
      <div
        className="rounded-xl px-5 py-2.5 flex items-center gap-3 border-2"
        style={{ borderColor: '#A7B85A', backgroundColor: '#F3F7E6' }}
      >
        <span className="text-xl flex-shrink-0">✅</span>
        <div>
          <span className="font-['Poppins'] font-bold text-[0.75rem] uppercase tracking-wide text-[#A7B85A]">Résultat attendu — </span>
          <span className="font-['Poppins'] text-[0.82rem] text-[#2d241e]">{output}</span>
        </div>
      </div>
    </div>
  </div>
);

export default PracticeExerciseTemplate;
