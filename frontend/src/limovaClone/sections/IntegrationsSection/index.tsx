import { useMemo, useState, type CSSProperties } from "react";
import { WalletCards } from "lucide-react";
import "./SavingsSection.css";

const formatEuros = (value: number) =>
  new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);

const rangeStyle = (value: number, min: number, max: number) =>
  ({
    "--range-progress": `${((value - min) / (max - min)) * 100}%`,
  }) as CSSProperties;

export const IntegrationsSection = () => {
  const [freelanceCost, setFreelanceCost] = useState(1800);
  const [cadrenzaCost, setCadrenzaCost] = useState(300);

  const result = useMemo(() => {
    const savings = Math.max(0, freelanceCost - cadrenzaCost);
    const rate =
      freelanceCost > 0 ? Math.round((savings / freelanceCost) * 100) : 0;
    return { savings, rate };
  }, [cadrenzaCost, freelanceCost]);

  return (
    <section id="pilotage" className="cadrenza-savings">
      <div className="cadrenza-savings__inner">
        <header className="cadrenza-savings__header">
          <span>Votre budget formation</span>
          <h2>Formez davantage, sans multiplier les coûts.</h2>
          <p>
            Comparez directement votre budget formateur avec celui d’un
            professeur IA Cadrenza.
          </p>
        </header>

        <div className="cadrenza-savings__comparison">
          <aside className="cadrenza-savings__wallet" aria-hidden="true">
            <span className="cadrenza-savings__wallet-icon">
              <WalletCards strokeWidth={1.7} />
            </span>
            <strong>Budget maîtrisé</strong>
            <small>Deux curseurs, une estimation immédiate.</small>
          </aside>

          <div className="cadrenza-savings__calculator">
            <label className="cadrenza-savings__range cadrenza-savings__range--human">
              <span className="cadrenza-savings__range-heading">
                <span>
                  <strong>Formateur freelance</strong>
                  <small>Coût mensuel estimé</small>
                </span>
                <strong>{formatEuros(freelanceCost)} / mois</strong>
              </span>
              <input
                type="range"
                min="500"
                max="10000"
                step="100"
                value={freelanceCost}
                style={rangeStyle(freelanceCost, 500, 10000)}
                aria-label="Coût mensuel du formateur freelance"
                onChange={(event) =>
                  setFreelanceCost(event.currentTarget.valueAsNumber)
                }
              />
            </label>

            <label className="cadrenza-savings__range cadrenza-savings__range--ai">
              <span className="cadrenza-savings__range-heading">
                <span>
                  <strong>Professeur IA Pierre</strong>
                  <small>Budget Cadrenza estimé</small>
                </span>
                <strong>{formatEuros(cadrenzaCost)} / mois</strong>
              </span>
              <input
                type="range"
                min="50"
                max="2000"
                step="50"
                value={cadrenzaCost}
                style={rangeStyle(cadrenzaCost, 50, 2000)}
                aria-label="Budget mensuel Cadrenza"
                onChange={(event) =>
                  setCadrenzaCost(event.currentTarget.valueAsNumber)
                }
              />
            </label>

            <div className="cadrenza-savings__result" aria-live="polite">
              <span>
                <small>Économie mensuelle estimée</small>
                <strong>{formatEuros(result.savings)}</strong>
              </span>
              <span className="cadrenza-savings__percentage">
                {result.rate}% de budget en moins
              </span>
            </div>
          </div>
        </div>

        <div className="cadrenza-savings__footer">
          <p>
            Simulation indicative hors taxes, calculée à partir des montants
            sélectionnés.
          </p>
          <a href="/connexion-centre?mode=signup">
            Créer un espace
            <span aria-hidden="true">→</span>
          </a>
        </div>
      </div>
    </section>
  );
};
