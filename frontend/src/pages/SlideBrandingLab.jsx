import { useState } from 'react'

import { SlidePreviewFrame } from '../components/slides/PipelineSlidePreview.jsx'

const previewSlide = {
  template_type: 'reprise_recap',
  data: {
    title: 'On reprend le fil.',
    points: [
      'Double obligation de prix',
      'Une étiquette claire',
      'La confiance du client',
    ],
  },
}

export default function SlideBrandingLab() {
  const [enabled, setEnabled] = useState(true)
  const [companyName, setCompanyName] = useState('Atelier Martin')
  const displayedName = enabled ? (companyName.trim() || 'Votre centre') : ''

  return (
    <main className="min-h-screen bg-[#F4F4F2] px-4 py-8 font-[Inter,system-ui,sans-serif] text-[#18181B] sm:px-8 sm:py-12">
      <div className="mx-auto max-w-[1080px]">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#71717A]">Aperçu local</p>
          <h1 className="mt-2 text-2xl font-bold tracking-[-0.025em] sm:text-3xl">Personnalisation des diapositives</h1>
        </header>

        <section className="overflow-hidden rounded-2xl bg-white" aria-labelledby="branding-title">
          <div className="grid gap-7 px-5 py-6 md:grid-cols-[minmax(0,1fr)_440px] md:px-7 md:py-7">
            <div>
              <h3 id="branding-title" className="text-lg font-semibold">Nom de votre centre de formation sur les diapositives</h3>
              <p className="mt-2 max-w-[58ch] text-sm leading-6 text-[#52525B]">
                Souhaitez-vous afficher le nom de votre centre de formation en haut à gauche des diapositives présentées par le professeur ?
              </p>

              <div className="mt-5 flex flex-wrap gap-2" role="group" aria-label="Personnaliser les diapositives">
                <button
                  type="button"
                  aria-pressed={enabled}
                  onClick={() => setEnabled(true)}
                  className={`min-h-11 rounded-lg border px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/30 ${enabled ? 'border-[#18181B] bg-[#18181B] text-white' : 'border-[#D4D4D8] bg-white text-[#52525B] hover:bg-[#F4F4F5]'}`}
                >
                  Oui, personnaliser
                </button>
                <button
                  type="button"
                  aria-pressed={!enabled}
                  onClick={() => setEnabled(false)}
                  className={`min-h-11 rounded-lg border px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#18181B]/30 ${!enabled ? 'border-[#18181B] bg-[#18181B] text-white' : 'border-[#D4D4D8] bg-white text-[#52525B] hover:bg-[#F4F4F5]'}`}
                >
                  Non
                </button>
              </div>

              {enabled ? (
                <div className="mt-5">
                  <label htmlFor="lab-company-name" className="mb-2 block text-sm font-medium text-[#3F3F46]">
                    Nom du centre de formation
                  </label>
                  <input
                    id="lab-company-name"
                    type="text"
                    value={companyName}
                    maxLength={120}
                    onChange={(event) => setCompanyName(event.target.value)}
                    autoComplete="organization"
                    className="min-h-11 w-full rounded-lg border border-[#D4D4D8] bg-white px-3.5 text-sm text-[#18181B] outline-none placeholder:text-[#64748B] focus:border-[#18181B] focus:ring-2 focus:ring-[#18181B]/15"
                    placeholder="Ex. Atelier Martin"
                  />
                  <p className="mt-2 text-xs leading-5 text-[#64748B]">
                    Ce nom sera reproduit à l’identique sur toutes les diapositives de cette formation.
                  </p>
                </div>
              ) : (
                <p className="mt-5 text-sm text-[#64748B]">Aucun nom ne sera affiché sur les diapositives.</p>
              )}
            </div>

            <div>
              <p className="mb-2 text-xs font-semibold text-[#52525B]">Aperçu</p>
              <div className="overflow-hidden rounded-lg border border-[#D4D4D8] bg-[#020617]">
                <SlidePreviewFrame
                  slide={previewSlide}
                  renderProps={{ brandName: displayedName }}
                  maxWidth={440}
                  padding={0}
                />
              </div>
              <p className="mt-2 text-xs leading-5 text-[#71717A]">Le contenu de la diapositive reste inchangé.</p>
            </div>
          </div>

          <footer className="flex flex-wrap justify-end gap-2 border-t border-[#E4E4E7] bg-[#FAFAFA] px-5 py-4 sm:px-7">
            <button type="button" className="min-h-11 rounded-lg border border-[#D4D4D8] bg-white px-4 text-sm font-semibold text-[#3F3F46] hover:bg-[#F4F4F5]">
              Revenir au planning
            </button>
            <button
              type="button"
              disabled={enabled && !companyName.trim()}
              className="min-h-11 rounded-lg bg-[#18181B] px-4 text-sm font-semibold text-white hover:bg-[#27272A] disabled:cursor-not-allowed disabled:bg-[#A1A1AA]"
            >
              Valider la demande
            </button>
          </footer>
        </section>
      </div>
    </main>
  )
}
