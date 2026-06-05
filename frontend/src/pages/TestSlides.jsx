import { useState } from 'react';

import { renderSlideTemplate } from '../components/slides/slideTemplateRegistry';

const GROUPS = [
  {
    label: 'Deck fourni',
    items: [
      { type: 'welcome', label: '01 Bienvenue · exact', data: { title: 'Bienvenue', formation_name: 'Titre professionnel CRCD', day_label: 'Journée 1', meta_note: 'Relation client à distance' } },
      { type: 'program_year', label: '02 Programme annuel · deux phases', data: { title: "Programme de l'année.", subtitle: 'Deux grands ensembles de compétences qui se complètent pour tenir toutes les facettes du poste.', day_label: 'Parcours annuel', phases: [{ title: 'Assistance et relation client à distance', desc: 'Accueillir, écouter, comprendre et résoudre les demandes clients, quel que soit le canal utilisé.' }, { title: 'Actions commerciales en relation client à distance', desc: "Identifier un besoin, éveiller un intérêt et proposer une solution adaptée avec éthique et justesse." }] } },
      { type: 'day_program_7_steps', label: '03 Programme journée · exact', data: { title: 'Programme de la journée.', subtitle: "Une journée dédiée aux fondamentaux de l'échange à distance — du premier contact jusqu'à l'empreinte que l'on laisse après.", day_label: 'Feuille de route', active_item: 1, items: ['Communiquer sans visuel', 'Le ton de la voix', 'Le rythme de synchronisation', "Humaniser l'écrit asynchrone", 'La première minute', "L'écoute active", "L'empreinte après contact"] } },
      { type: 'chapter_opener', label: '04 Chapitre 1 · exact', data: { chapter_label: 'Chapitre 1', title: "L'obstacle invisible", axes: [{ title: 'Le brouillard de la distance', desc: 'Quand le client ne voit pas, son cerveau complète.' }, { title: 'Les biais de perception', desc: 'Un silence, un ton ou un rythme devient un message.' }] } },
      { type: 'reflection', label: '05 Reflection · principe clé', data: { title: 'Même intention, autre forme.', text: "L'accueil ne change pas d'objectif selon le canal. Ce qui change, c'est la manière de le faire ressentir.", eyebrow: 'Principe clé' } },
      { type: 'definition', label: '06 Definition', data: { term: 'Opération.', eyebrow: 'Vocabulaire #01', definition: "Un système répétable qui produit un résultat prévisible — sans dépendre d'une personne en particulier.", isItems: ['RÉPÉTABLE', 'MESURABLE', 'DÉLÉGABLE', 'DOCUMENTÉ'] } },
      { type: 'comparison', label: '07 Diagnostic', data: { title: 'Équipe épuisée vs autonome.', cols: [{ label: 'État actuel', items: ['Tout passe par 2 personnes', 'Aucun process écrit', '3h/jour en Slack', 'Erreurs qui se répètent'] }, { label: 'Objectif 7 semaines', items: ['Décisions distribuées', '12 SOPs documentées', 'Slack divisé par 4', 'Erreurs trackées + résolues'] }] } },
      { type: 'warning', label: '08 Mistake', data: { title: 'Automatiser le chaos.', text: "Brancher une IA sur un process bancal multiplie le désordre à la vitesse de la machine. Documentez d'abord, automatisez ensuite." } },
      { type: 'casestudy', label: '09 Case study · cartes comparatives', data: { title: "Les codes d'accueil selon le canal.", eyebrow: 'Analyse comparative', cases: [{ tag: '01 · Téléphone', title: 'La voix en direct', desc: "L'accueil se joue dans les premières secondes. Ton, rythme et articulation remplacent le visuel.", example: 'Bonjour, société X, Amelle, bonjour.' }, { tag: '02 · Email', title: "L'écrit posé", desc: "La formule d'accueil doit être courte et personnalisée. Le client lit en diagonale : le prénom et le motif doivent sauter aux yeux.", example: 'Bonjour [Prénom], suite à votre demande...' }, { tag: '03 · Chat', title: "L'écrit immédiat", desc: "La réponse doit être rapide et fluide. Pas de bloc de texte : une phrase d'accueil, puis une question courte.", example: 'Bonjour ! En quoi puis-je vous aider ?' }] } },
      { type: 'steps', label: '10 Process', data: { title: '4 étapes pour rendre un process délégable.', steps: [{ title: 'Observer', desc: 'Filmer 5 fois la tâche réelle.' }, { title: 'Découper', desc: 'Identifier décisions, actions répétables et exceptions.' }, { title: 'Automatiser', desc: "Brancher l'IA uniquement sur les segments stables." }, { title: 'Mesurer', desc: 'Définir 1 KPI par étape.' }] } },
      { type: 'recap', label: '11 Recap', data: { title: "Ce qu'on retient.", points: ["Process avant outils : l'outil amplifie ce qui existe.", 'Filmer la réalité : observer avant de prescrire.', 'Mesurer ou tâtonner : 1 chiffre par étape.'] } },
      { type: 'pause', label: '12 Pause', data: { title: 'Pause.', duration: '5 minutes.', subtitle: "notez ce qui vous a marqué jusqu'ici." } },
      { type: 'qa', label: '13 Q&A', data: { title: 'On répond à tout.' } },
      { type: 'quotable', label: '14 Quote', data: { quote: "On a doublé la capacité de l'équipe sans recruter. Le secret ? Arrêter de tout faire passer par nous." } },
      { type: 'tip', label: '15 Tip', data: { title: 'Commencer par observer.', text: "Avant d'écrire un seul process, filmez ou notez ce qui se passe vraiment — pas ce que vous croyez qui se passe." } },
    ],
  },
];

const ALL_ITEMS = GROUPS.flatMap((group, groupIndex) =>
  group.items.map((item, itemIndex) => ({
    ...item,
    groupLabel: group.label,
    globalIndex: groupIndex * 100 + itemIndex,
  })),
);

export default function TestSlides() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const item = ALL_ITEMS[currentIndex];

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#0f172a', color: '#f1f5f9', display: 'grid', gridTemplateColumns: '260px 1fr', fontFamily: 'Inter, system-ui, sans-serif' }}>
      <aside style={{ borderRight: '1px solid #334155', padding: '16px', backgroundColor: '#111827', overflowY: 'auto' }}>
        <div style={{ marginBottom: '16px' }}>
          <div style={{ color: '#a78bfa', fontSize: '10px', fontWeight: 700, letterSpacing: '0.18em', textTransform: 'uppercase', marginBottom: '4px' }}>
            Aperçu deck
          </div>
          <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 700 }}>
            {ALL_ITEMS.length} slides source
          </h1>
        </div>

        {GROUPS.map((group, groupIndex) => (
          <div key={group.label} style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '10px', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: '#64748B', marginBottom: '6px', paddingLeft: '4px' }}>
              {group.label}
            </div>
            <div style={{ display: 'grid', gap: '4px' }}>
              {group.items.map((slide, itemIndex) => {
                const index = groupIndex * 100 + itemIndex;
                const active = ALL_ITEMS.find((entry) => entry.globalIndex === index)?.globalIndex === item.globalIndex;
                const actualIndex = ALL_ITEMS.findIndex((entry) => entry.globalIndex === index);
                return (
                  <button
                    key={`${slide.type}-${slide.label}`}
                    type="button"
                    onClick={() => setCurrentIndex(actualIndex)}
                    style={{
                      textAlign: 'left',
                      border: `1px solid ${active ? '#8B5CF6' : '#1e293b'}`,
                      backgroundColor: active ? 'rgba(139,92,246,0.14)' : 'transparent',
                      color: active ? '#f8fafc' : '#94a3b8',
                      borderRadius: '6px',
                      padding: '6px 10px',
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    <div style={{ fontSize: '12px', fontWeight: active ? 700 : 500 }}>{slide.label}</div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </aside>

      <main style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px', gap: '16px', overflow: 'hidden' }}>
        <div style={{ width: 'min(1200px,100%)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
          <div>
            <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '2px' }}>
              {item.groupLabel} · {currentIndex + 1}/{ALL_ITEMS.length}
            </div>
            <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 700 }}>{item.label}</h2>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              onClick={() => setCurrentIndex(Math.max(0, currentIndex - 1))}
              disabled={currentIndex === 0}
              style={{ padding: '8px 14px', borderRadius: '8px', border: '1px solid #334155', backgroundColor: 'transparent', color: currentIndex === 0 ? '#64748b' : '#f1f5f9', cursor: currentIndex === 0 ? 'not-allowed' : 'pointer', fontFamily: 'inherit', fontWeight: 600 }}
            >
              Préc.
            </button>
            <button
              type="button"
              onClick={() => setCurrentIndex(Math.min(ALL_ITEMS.length - 1, currentIndex + 1))}
              disabled={currentIndex === ALL_ITEMS.length - 1}
              style={{ padding: '8px 14px', borderRadius: '8px', border: '1px solid #8B5CF6', backgroundColor: currentIndex === ALL_ITEMS.length - 1 ? 'transparent' : '#8B5CF6', color: currentIndex === ALL_ITEMS.length - 1 ? '#64748b' : '#fff', cursor: currentIndex === ALL_ITEMS.length - 1 ? 'not-allowed' : 'pointer', fontFamily: 'inherit', fontWeight: 600 }}
            >
              Suiv.
            </button>
          </div>
        </div>

        <div style={{ width: 'min(1200px,100%)', display: 'flex', justifyContent: 'center', overflow: 'auto', padding: '4px' }}>
          {renderSlideTemplate(item)}
        </div>
      </main>
    </div>
  );
}
