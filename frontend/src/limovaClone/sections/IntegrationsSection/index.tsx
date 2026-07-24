import { useMemo, useState, type CSSProperties } from "react";
import "./SavingsSection.css";

const formatEuros = (value: number) =>
  new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);

const CADRENZA_DAY_PRICE = 30;
const FREELANCE_DAY_RATE = 650;

const rangeStyle = (value: number, min: number, max: number) =>
  ({
    "--range-progress": `${((value - min) / (max - min)) * 100}%`,
  }) as CSSProperties;

export const IntegrationsSection = () => {
  const [weeklyTrainingDays, setWeeklyTrainingDays] = useState(2);
  const [trainingWeeks, setTrainingWeeks] = useState(8);

  const result = useMemo(() => {
    const totalTrainingDays = weeklyTrainingDays * trainingWeeks;
    const cadrenzaCost = totalTrainingDays * CADRENZA_DAY_PRICE;
    const freelanceCost = totalTrainingDays * FREELANCE_DAY_RATE;
    const savings = Math.max(0, freelanceCost - cadrenzaCost);
    const rate =
      freelanceCost > 0 ? Math.round((savings / freelanceCost) * 100) : 0;

    return {
      cadrenzaCost,
      freelanceCost,
      rate,
      savings,
      totalTrainingDays,
    };
  }, [trainingWeeks, weeklyTrainingDays]);

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
          <div className="cadrenza-savings__calculator">
            <label className="cadrenza-savings__range cadrenza-savings__range--frequency">
              <span className="cadrenza-savings__range-heading">
                <span>
                  <strong>Journées de formation</strong>
                  <small>Rythme hebdomadaire</small>
                </span>
                <strong>{weeklyTrainingDays} / semaine</strong>
              </span>
              <input
                type="range"
                min="1"
                max="5"
                step="1"
                value={weeklyTrainingDays}
                style={rangeStyle(weeklyTrainingDays, 1, 5)}
                aria-label="Nombre de journées de formation par semaine"
                onChange={(event) =>
                  setWeeklyTrainingDays(event.currentTarget.valueAsNumber)
                }
              />
            </label>

            <label className="cadrenza-savings__range cadrenza-savings__range--duration">
              <span className="cadrenza-savings__range-heading">
                <span>
                  <strong>Durée du parcours</strong>
                  <small>De 1 à 52 semaines</small>
                </span>
                <strong>
                  {trainingWeeks} semaine{trainingWeeks > 1 ? "s" : ""}
                </strong>
              </span>
              <input
                type="range"
                min="1"
                max="52"
                step="1"
                value={trainingWeeks}
                style={rangeStyle(trainingWeeks, 1, 52)}
                aria-label="Durée de la formation en semaines"
                onChange={(event) =>
                  setTrainingWeeks(event.currentTarget.valueAsNumber)
                }
              />
            </label>

            <div
              className="cadrenza-savings__budgets"
              aria-label="Budgets estimés pour la formation"
            >
              <span>
                <small>Formateur freelance</small>
                <strong>{formatEuros(result.freelanceCost)}</strong>
              </span>
              <span>
                <small>Professeur IA Pierre</small>
                <strong>{formatEuros(result.cadrenzaCost)}</strong>
              </span>
            </div>

            <div className="cadrenza-savings__result" aria-live="polite">
              <span>
                <small>Économie estimée sur toute la formation</small>
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
            Simulation HT basée sur {formatEuros(CADRENZA_DAY_PRICE)} par
            journée Cadrenza et {formatEuros(FREELANCE_DAY_RATE)} par journée
            freelance.
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
