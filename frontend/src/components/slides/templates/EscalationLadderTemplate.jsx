import React from 'react';

const Header = ({ badge = 'TP-CRCD', brandName = 'SALES HACKING' }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5]">
    <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">{badge}</div>
    <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">{brandName}</span>
  </div>
);

// levels: [{ label, trigger, action, phrase?, color }] — du bas (le plus doux) au haut (le plus fort)
const EscalationLadderTemplate = ({
  title = 'Escalade recouvrement amiable',
  subtitle = 'Montez un niveau seulement si le précédent n\'a pas fonctionné.',
  levels = [
    {
      label: 'Contact amical',
      trigger: 'Premier impayé détecté',
      action: 'Appel chaleureux — explorer la situation, proposer une solution',
      phrase: '"Je vois qu\'une facture est en attente — est-ce qu\'il y a quelque chose que je peux faire ?"',
      color: '#A7B85A',
    },
    {
      label: 'Relance formelle',
      trigger: 'Pas de réponse après 7 jours',
      action: 'Email structuré + rappel du montant + délai précis + numéro de contact',
      phrase: '"Nous n\'avons pas reçu de réponse. La facture de X€ est due au [date]. Merci de revenir vers nous."',
      color: '#F4A332',
    },
    {
      label: 'Ultimatum négocié',
      trigger: 'Pas de réponse après 14 jours',
      action: 'Appel + email simultanés. Proposer un échéancier ou une date limite ferme.',
      phrase: '"C\'est votre dernière opportunité de régler amiablement avant transmission au service juridique."',
      color: '#E07A6F',
    },
    {
      label: 'Transmission',
      trigger: 'Aucune réponse ou refus',
      action: 'Transmission au service contentieux ou cabinet de recouvrement',
      phrase: null,
      color: '#DC2626',
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => {
  const reversed = [...levels].reverse();

  return (
    <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)]">
      <Header badge={badge} brandName={brandName} />

      <div className="flex-1 flex gap-8 px-10 py-4">
        {/* Échelle visuelle (escalier) */}
        <div className="flex flex-col justify-center gap-1 w-32 flex-shrink-0">
          <div className="font-['Poppins'] text-[0.7rem] font-bold uppercase tracking-wide text-[#666] text-center mb-2">
            Intensité
          </div>
          {reversed.map((lvl, i) => (
            <div
              key={i}
              className="rounded-lg flex items-center justify-center"
              style={{
                height: `${20 + i * 8}px`,
                backgroundColor: lvl.color,
                width: `${55 + i * 12}%`,
                marginLeft: 'auto',
              }}
            >
              <span className="text-white font-['Poppins'] text-[0.65rem] font-bold text-center px-1">
                {i === 0 ? '🔒 MAX' : i === reversed.length - 1 ? '1' : `${i + 1}`}
              </span>
            </div>
          ))}
          <div className="font-['Poppins'] text-[0.65rem] text-[#888] text-center mt-1">Niveau 1 = premier</div>
        </div>

        {/* Cartes de niveaux */}
        <div className="flex-1 flex flex-col gap-2 justify-center">
          {reversed.map((lvl, i) => (
            <div
              key={i}
              className="flex items-stretch rounded-xl overflow-hidden border-l-4"
              style={{ borderColor: lvl.color, backgroundColor: 'white' }}
            >
              {/* Badge niveau */}
              <div
                className="w-14 flex-shrink-0 flex flex-col items-center justify-center py-2"
                style={{ backgroundColor: `${lvl.color}20` }}
              >
                <span className="font-['Fredoka'] text-[1.4rem] font-bold" style={{ color: lvl.color }}>
                  {reversed.length - i}
                </span>
              </div>

              {/* Contenu */}
              <div className="flex-1 px-4 py-2 flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="font-['Poppins'] font-bold text-[0.9rem] text-[#2d241e]">{lvl.label}</span>
                  <span className="font-['Poppins'] text-[0.72rem] text-[#888] italic">→ si : {lvl.trigger}</span>
                </div>
                <p className="font-['Poppins'] text-[0.8rem] text-[#444]">{lvl.action}</p>
                {lvl.phrase && (
                  <p className="font-['Poppins'] text-[0.75rem] text-[#666] italic mt-0.5">{lvl.phrase}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {subtitle && (
        <div className="px-10 pb-3">
          <p className="font-['Poppins'] text-[0.8rem] text-[#888] text-center italic">{subtitle}</p>
        </div>
      )}
    </div>
  );
};

export default EscalationLadderTemplate;
