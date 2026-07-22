import { useMemo, useState } from "react";
import "./ProductPreview.css";

const DAYS = [
  { id: "lun", short: "L", label: "Lundi" },
  { id: "mar", short: "M", label: "Mardi" },
  { id: "mer", short: "M", label: "Mercredi" },
  { id: "jeu", short: "J", label: "Jeudi" },
  { id: "ven", short: "V", label: "Vendredi" },
];

export const ProductPreview = () => {
  const [selectedDays, setSelectedDays] = useState(["mar", "jeu"]);
  const [weeks, setWeeks] = useState(8);

  const totalCourses = useMemo(
    () => selectedDays.length * weeks,
    [selectedDays.length, weeks],
  );

  const toggleDay = (day: string) => {
    setSelectedDays((current) => {
      if (current.includes(day)) {
        return current.length === 1 ? current : current.filter((item) => item !== day);
      }
      return [...current, day];
    });
  };

  return (
    <div className="cadrenza-course-planner">
      <div className="cadrenza-course-planner__topbar">
        <div className="cadrenza-course-planner__brand">
          <img src="/cadrenza-mark.svg" alt="" />
          <span>Cadrenza</span>
        </div>
        <span className="cadrenza-course-planner__status"><i /> Agent prêt</span>
      </div>

      <div className="cadrenza-course-planner__content">
        <div className="cadrenza-course-planner__heading">
          <span>Planification du cours</span>
          <h2>Choisissez le rythme de votre formation</h2>
          <p>L’agent IA délivrera automatiquement le cours aux jours sélectionnés.</p>
        </div>

        <fieldset className="cadrenza-course-planner__days">
          <legend>Jours de diffusion</legend>
          <div>
            {DAYS.map((day) => {
              const selected = selectedDays.includes(day.id);
              return (
                <button
                  key={day.id}
                  type="button"
                  className={selected ? "is-selected" : ""}
                  onClick={() => toggleDay(day.id)}
                  aria-pressed={selected}
                  aria-label={day.label}
                >
                  <span>{day.short}</span>
                  <i aria-hidden="true" />
                </button>
              );
            })}
          </div>
        </fieldset>

        <div className="cadrenza-course-planner__duration">
          <div>
            <span>Durée du parcours</span>
            <strong>{weeks} semaine{weeks > 1 ? "s" : ""}</strong>
          </div>
          <div className="cadrenza-course-planner__stepper">
            <button type="button" onClick={() => setWeeks((value) => Math.max(1, value - 1))} disabled={weeks === 1} aria-label="Retirer une semaine">−</button>
            <span>{weeks}</span>
            <button type="button" onClick={() => setWeeks((value) => Math.min(52, value + 1))} disabled={weeks === 52} aria-label="Ajouter une semaine">+</button>
          </div>
        </div>

        <div className="cadrenza-course-planner__summary">
          <div className="cadrenza-course-planner__calendar-icon" aria-hidden="true">
            <span>09:00</span>
          </div>
          <div>
            <strong>{selectedDays.length} cours par semaine</strong>
            <span>{totalCourses} cours programmés au total</span>
          </div>
          <span className="cadrenza-course-planner__check" aria-hidden="true">✓</span>
        </div>

        <p className="cadrenza-course-planner__note">
          Préparation automatique 24 h avant chaque cours
        </p>
      </div>
    </div>
  );
};
