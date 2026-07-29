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
          <div>
            <span>Simulateur de budget</span>
            <h2>Estimez le coût de votre parcours.</h2>
          </div>
          <p>
            Ajustez le rythme et la durée de la formation. L’estimation compare
            immédiatement un formateur freelance avec Pierre, professeur IA
            Cadrenza.
          </p>
        </header>

        <div className="cadrenza-savings__comparison">
          <div className="cadrenza-savings__calculator">
            <div className="cadrenza-savings__panel-heading">
              <strong>Paramètres du parcours</strong>
              <span>{result.totalTrainingDays} jours au total</span>
            </div>

            <label
              className="cadrenza-savings__range cadrenza-savings__range--frequency"
              htmlFor="weekly-training-days"
            >
              <span className="cadrenza-savings__range-heading">
                <span>
                  <strong>Journées de formation</strong>
                  <small>Rythme hebdomadaire</small>
                </span>
                <output htmlFor="weekly-training-days">
                  {weeklyTrainingDays} jour{weeklyTrainingDays > 1 ? "s" : ""}
                  <small> / semaine</small>
                </output>
              </span>
              <input
                id="weekly-training-days"
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
              <span className="cadrenza-savings__range-limits" aria-hidden="true">
                <span>1 jour</span>
                <span>5 jours</span>
              </span>
            </label>

            <label
              className="cadrenza-savings__range cadrenza-savings__range--duration"
              htmlFor="training-weeks"
            >
              <span className="cadrenza-savings__range-heading">
                <span>
                  <strong>Durée du parcours</strong>
                  <small>Calendrier prévisionnel</small>
                </span>
                <output htmlFor="training-weeks">
                  {trainingWeeks} semaine{trainingWeeks > 1 ? "s" : ""}
                </output>
              </span>
              <input
                id="training-weeks"
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
              <span className="cadrenza-savings__range-limits" aria-hidden="true">
                <span>1 semaine</span>
                <span>52 semaines</span>
              </span>
            </label>
          </div>

          <div className="cadrenza-savings__estimate" aria-live="polite">
            <div className="cadrenza-savings__panel-heading">
              <strong>Estimation hors taxes</strong>
              <span>{result.totalTrainingDays} jours de formation</span>
            </div>

            <dl className="cadrenza-savings__budgets">
              <div>
                <dt>
                  <strong>Formateur freelance</strong>
                  <small>{formatEuros(FREELANCE_DAY_RATE)} par jour</small>
                </dt>
                <dd>{formatEuros(result.freelanceCost)}</dd>
              </div>
              <div className="cadrenza-savings__budget--cadrenza">
                <dt>
                  <strong>Pierre, professeur IA</strong>
                  <small>{formatEuros(CADRENZA_DAY_PRICE)} par jour</small>
                </dt>
                <dd>{formatEuros(result.cadrenzaCost)}</dd>
              </div>
            </dl>

            <div className="cadrenza-savings__result">
              <span>
                <small>Budget économisé</small>
                <strong>{formatEuros(result.savings)}</strong>
              </span>
              <p>
                Votre estimation est inférieure de <strong>{result.rate}%</strong>{" "}
                au budget freelance.
              </p>
            </div>

            <a
              className="cadrenza-savings__cta"
              href="/connexion-centre?mode=signup"
            >
              Créer un espace centre
              <span aria-hidden="true">→</span>
            </a>
          </div>
        </div>

        <p className="cadrenza-savings__note">
          Estimation indicative, calculée sur une base de{" "}
          {formatEuros(CADRENZA_DAY_PRICE)} par journée Cadrenza et{" "}
          {formatEuros(FREELANCE_DAY_RATE)} par journée freelance.
        </p>
      </div>
    </section>
  );
};
