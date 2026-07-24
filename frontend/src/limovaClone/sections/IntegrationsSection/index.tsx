import { useMemo, useState } from "react";
import "./SavingsSection.css";

const formatEuros = (value: number) =>
  new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);

const clampNumber = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, Number.isFinite(value) ? value : min));

export const IntegrationsSection = () => {
  const [trainingDays, setTrainingDays] = useState(8);
  const [dailyRate, setDailyRate] = useState(650);
  const [cadrenzaBudget, setCadrenzaBudget] = useState(300);

  const simulation = useMemo(() => {
    const freelanceCost = trainingDays * dailyRate;
    const savings = Math.max(0, freelanceCost - cadrenzaBudget);
    const savingsRate =
      freelanceCost > 0 ? Math.round((savings / freelanceCost) * 100) : 0;
    const cadrenzaRatio =
      freelanceCost > 0
        ? Math.max(4, Math.min(100, (cadrenzaBudget / freelanceCost) * 100))
        : 4;

    return { freelanceCost, savings, savingsRate, cadrenzaRatio };
  }, [cadrenzaBudget, dailyRate, trainingDays]);

  return (
    <section id="pilotage" className="cadrenza-savings">
      <div className="cadrenza-savings__inner">
        <header className="cadrenza-savings__header">
          <span className="cadrenza-savings__label">
            Simulateur d’économies
          </span>
          <h2>Mesurez ce que Pierre peut vous faire économiser.</h2>
          <p>
            Comparez le coût mensuel d’un formateur freelance avec le budget
            d’un professeur IA Cadrenza. Ajustez les hypothèses à votre
            activité.
          </p>
        </header>

        <div className="cadrenza-savings__inputs" aria-label="Hypothèses du calcul">
          <label>
            <span>Journées par mois</span>
            <span className="cadrenza-savings__input-shell">
              <input
                type="number"
                min="1"
                max="31"
                value={trainingDays}
                onChange={(event) =>
                  setTrainingDays(
                    clampNumber(event.currentTarget.valueAsNumber, 1, 31),
                  )
                }
              />
              <small>jours</small>
            </span>
          </label>
          <label>
            <span>Tarif du freelance</span>
            <span className="cadrenza-savings__input-shell">
              <input
                type="number"
                min="100"
                max="3000"
                step="50"
                value={dailyRate}
                onChange={(event) =>
                  setDailyRate(
                    clampNumber(event.currentTarget.valueAsNumber, 100, 3000),
                  )
                }
              />
              <small>€ / jour</small>
            </span>
          </label>
          <label>
            <span>Budget Cadrenza estimé</span>
            <span className="cadrenza-savings__input-shell">
              <input
                type="number"
                min="0"
                max="10000"
                step="50"
                value={cadrenzaBudget}
                onChange={(event) =>
                  setCadrenzaBudget(
                    clampNumber(event.currentTarget.valueAsNumber, 0, 10000),
                  )
                }
              />
              <small>€ / mois</small>
            </span>
          </label>
        </div>

        <div className="cadrenza-savings__comparison">
          <div className="cadrenza-savings__row cadrenza-savings__row--human">
            <div className="cadrenza-savings__row-heading">
              <span>
                <strong>Formateur freelance</strong>
                <small>
                  {trainingDays} jours × {formatEuros(dailyRate)}
                </small>
              </span>
              <strong>{formatEuros(simulation.freelanceCost)} / mois</strong>
            </div>
            <div className="cadrenza-savings__track" aria-hidden="true">
              <span />
            </div>
          </div>

          <div className="cadrenza-savings__row cadrenza-savings__row--ai">
            <div className="cadrenza-savings__row-heading">
              <span>
                <strong>Professeur IA Pierre</strong>
                <small>Budget mensuel renseigné</small>
              </span>
              <strong>{formatEuros(cadrenzaBudget)} / mois</strong>
            </div>
            <div className="cadrenza-savings__track" aria-hidden="true">
              <span style={{ width: `${simulation.cadrenzaRatio}%` }} />
            </div>
          </div>

          <div className="cadrenza-savings__result" aria-live="polite">
            <span>
              <small>Économie mensuelle estimée</small>
              <strong>{formatEuros(simulation.savings)}</strong>
            </span>
            <span className="cadrenza-savings__percentage">
              {simulation.savingsRate}% de budget en moins
            </span>
          </div>
        </div>

        <p className="cadrenza-savings__disclaimer">
          Simulation indicative hors taxes, calculée à partir des montants que
          vous renseignez. Elle n’inclut pas les éventuels frais annexes d’un
          formateur.
        </p>

        <div className="cadrenza-savings__actions">
          <a
            className="cadrenza-savings__primary"
            href="/connexion-centre?mode=signup"
          >
            Créer un espace
            <span aria-hidden="true">→</span>
          </a>
          <a className="cadrenza-savings__secondary" href="tel:+33768533382">
            Parler à un conseiller
          </a>
        </div>
      </div>
    </section>
  );
};
