import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

const BeforeAfterTemplate = ({
  title = 'Transformer un bloc de texte en message professionnel',
  label = 'Email de réponse client',
  before = {
    label: 'AVANT',
    subtitle: 'Réponse non structurée',
    content: `Suite à votre demande concernant votre commande numéro 48291 nous avons bien pris note de votre réclamation et notre service va traiter votre dossier dans les meilleurs délais. Pour cela nous aurons besoin de votre pièce d'identité et de votre justificatif de domicile et d'un RIB et de la facture originale. Merci de nous les envoyer par email.`,
  },
  after = {
    label: 'APRÈS',
    subtitle: 'Structure pyramide + liste',
    items: [
      { icon: '📌', text: 'Objet : Dossier n°48291 — Documents requis' },
      { icon: '👤', text: 'Bonjour Madame Martin, votre réclamation a bien été enregistrée.' },
      { icon: '📋', text: 'Pour traiter votre dossier, nous avons besoin de :' },
      { icon: '  1.', text: "Pièce d'identité en cours de validité" },
      { icon: '  2.', text: 'Justificatif de domicile (moins de 3 mois)' },
      { icon: '  3.', text: 'RIB + facture originale' },
      { icon: '📅', text: 'Délai de traitement : 5 jours ouvrés après réception.' },
    ],
  },
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
    <Header badge={badge} brandName={brandName} />

    <div className="flex-1 flex flex-col px-10 py-4 gap-3">
      <div className="flex items-baseline gap-3">
        <h1 className="font-['Fredoka'] text-[1.9rem] text-[#2d241e] font-bold uppercase leading-tight">{title}</h1>
        <span className="font-['Poppins'] text-[0.85rem] text-[#888] italic flex-shrink-0">{label}</span>
      </div>

      <div className="flex-1 flex gap-4 items-stretch">
        {/* AVANT */}
        <div className="flex-1 rounded-2xl overflow-hidden border-2 border-[#DC2626] flex flex-col">
          <div className="bg-[#DC2626] px-5 py-2.5 flex items-center gap-2">
            <span className="font-['Fredoka'] text-white text-[1.2rem] font-bold">{before.label}</span>
            <span className="font-['Poppins'] text-white/80 text-[0.8rem]">— {before.subtitle}</span>
          </div>
          <div className="flex-1 bg-[#FEF2F2] px-5 py-4 flex items-center">
            <p className="font-['Poppins'] text-[0.85rem] text-[#5a2a2a] leading-relaxed italic">
              {before.content}
            </p>
          </div>
        </div>

        {/* Flèche */}
        <div className="flex-shrink-0 flex items-center justify-center w-12">
          <div className="flex flex-col items-center gap-1">
            <div className="w-10 h-10 rounded-full bg-[#2d241e] flex items-center justify-center">
              <svg viewBox="0 0 24 24" className="w-6 h-6 text-white" fill="currentColor">
                <path d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6-1.41-1.41z" />
              </svg>
            </div>
          </div>
        </div>

        {/* APRÈS */}
        <div className="flex-1 rounded-2xl overflow-hidden border-2 border-[#16A34A] flex flex-col">
          <div className="bg-[#16A34A] px-5 py-2.5 flex items-center gap-2">
            <span className="font-['Fredoka'] text-white text-[1.2rem] font-bold">{after.label}</span>
            <span className="font-['Poppins'] text-white/80 text-[0.8rem]">— {after.subtitle}</span>
          </div>
          <div className="flex-1 bg-[#F0FDF4] px-5 py-4 flex flex-col gap-2">
            {after.items.map((item, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="font-['Poppins'] font-bold text-[0.82rem] text-[#16A34A] flex-shrink-0 w-6 mt-0.5">
                  {item.icon}
                </span>
                <p className="font-['Poppins'] text-[0.83rem] text-[#166534] leading-snug">
                  {item.text}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  </div>
);

export default BeforeAfterTemplate;
