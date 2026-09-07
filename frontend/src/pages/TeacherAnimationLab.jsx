import { useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'

export default function TeacherAnimationLab() {
  const [view, setView] = useState('payment')
  const reduceMotion = useReducedMotion()

  return (
    <main className="animation-lab min-h-screen bg-[#FAFAF9] font-[Inter,system-ui,sans-serif] text-[#18181B]">
      <header className="animation-lab__toolbar">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6B6B72]">Laboratoire local · Paiement → professeur</p>
        <button
          type="button"
          onClick={() => setView('payment')}
          className="min-h-11 rounded-lg bg-[#18181B] px-4 text-sm font-semibold text-white transition-colors hover:bg-[#2C2C30] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/40 focus-visible:ring-offset-2"
        >
          Revenir au paiement
        </button>
      </header>

      {view === 'payment' ? (
        <section className="animation-lab__payment-page" aria-labelledby="payment-confirmed-title">
          <div className="animation-lab__payment-card">
            <span className="animation-lab__check" aria-hidden="true">✓</span>
            <p className="animation-lab__payment-kicker">PAIEMENT VALIDÉ</p>
            <h1 id="payment-confirmed-title">Paiement confirmé</h1>
            <p>Votre professeur IA a bien rejoint votre espace.</p>
            <div className="animation-lab__receipt">
              <span>Professeur IA · TP Employé commercial</span>
              <strong>120,00 €</strong>
            </div>
            <div className="animation-lab__payment-action">
              <button type="button" onClick={() => setView('teachers')}>
                Voir le professeur
                <span aria-hidden="true">→</span>
              </button>
            </div>
          </div>
        </section>
      ) : (
        <section className="animation-lab__teachers-page" aria-labelledby="teachers-title">
          <div className="animation-lab__roster-shell">
            <header className="animation-lab__roster-heading">
              <h1 id="teachers-title">Mes professeurs</h1>
              <p>Retrouvez vos professeurs, leurs formations et leur prochaine séance.</p>
            </header>
            <div className="animation-lab__filters" aria-hidden="true">
              <span>Tous 1</span><span>En cours 1</span><span>Terminés 0</span>
            </div>

            <div className="animation-lab__cards">
              <motion.div
                initial={reduceMotion ? false : { opacity: 0, y: 24, scale: 0.86, filter: 'blur(12px)' }}
                animate={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
                transition={{ duration: 0.52, ease: [0.16, 1, 0.3, 1] }}
                className="relative isolate w-full max-w-[224px]"
              >
                {!reduceMotion && (
                  <motion.span
                    aria-hidden="true"
                    initial={{ opacity: 0.5, scale: 0.62 }}
                    animate={{ opacity: 0, scale: 1.28 }}
                    transition={{ duration: 0.68, ease: [0.16, 1, 0.3, 1] }}
                    className="pointer-events-none absolute -inset-5 -z-10 rounded-[20px] bg-[#8B5CF6]/30 blur-xl"
                  />
                )}
                <article className="flex min-h-[332px] flex-col gap-2 overflow-hidden rounded-2xl border border-[#E4E4E7] bg-white p-3 shadow-sm">
                  <div className="relative h-[218px] overflow-hidden rounded-xl bg-[#8B5CF612]" aria-hidden="true">
                    <img src="/robot-violet.png" alt="" draggable={false} className="h-full w-full select-none object-contain px-2 pt-2" />
                  </div>
                  <div>
                    <h2 className="truncate text-sm font-semibold tracking-[-0.025em]">Pierrot</h2>
                    <p className="mt-1 truncate text-xs font-medium text-[#6C63FF]">Professeur du TP Employé commercial</p>
                  </div>
                  <ul className="mt-1 space-y-1 text-[11px] leading-[1.45] text-[#52525B]">
                    <li className="flex items-center gap-2"><span className="h-1 w-1 rounded-full bg-[#B45309]" />En préparation · 8 %</li>
                    <li className="flex items-center gap-2"><span className="h-1 w-1 rounded-full bg-[#6C63FF]" />Aucune séance programmée</li>
                    <li className="flex items-center gap-2"><span className="h-1 w-1 rounded-full bg-[#6C63FF]" />6 séances restantes</li>
                  </ul>
                  <span className="mt-auto flex w-full items-center justify-center rounded-full bg-[#121212] px-3 py-1.5 text-xs font-medium text-[#F4F0E7]">Gérer</span>
                </article>
              </motion.div>
            </div>
          </div>
        </section>
      )}
    </main>
  )
}
