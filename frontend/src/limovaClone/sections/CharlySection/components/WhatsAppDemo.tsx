import "@sneas/telephone/iphone-16-max.js";
import "./WhatsAppDemo.css";

const CALENDAR_WEEKS = [
  [
    { day: 26, muted: true },
    { day: 27, muted: true },
    { day: 28, muted: true },
    { day: 29, muted: true },
    { day: 30, muted: true },
    { day: 31, muted: true },
    { day: 1 },
  ],
  [
    { day: 2, selected: true },
    { day: 3 },
    { day: 4 },
    { day: 5 },
    { day: 6 },
    { day: 7 },
    { day: 8 },
  ],
  [
    { day: 9 },
    { day: 10, selected: true },
    { day: 11 },
    { day: 12 },
    { day: 13 },
    { day: 14, selected: true },
    { day: 15 },
  ],
  [
    { day: 16, selected: true },
    { day: 17 },
    { day: 18 },
    { day: 19 },
    { day: 20 },
    { day: 21 },
    { day: 22 },
  ],
  [
    { day: 23 },
    { day: 24 },
    { day: 25, selected: true },
    { day: 26 },
    { day: 27 },
    { day: 28 },
    { day: 29 },
  ],
  [
    { day: 30 },
    { day: 31 },
    { day: 1, muted: true },
    { day: 2, muted: true },
    { day: 3, muted: true },
    { day: 4, muted: true },
    { day: 5, muted: true },
  ],
];

const DURATIONS = ["8 semaines", "9 semaines", "12 mois", "Personnalisée"];

export const WhatsAppDemo = () => (
  <div className="cadrenza-phone-demo col-end-[span_3] flex min-w-0 items-center justify-center">
    <iphone-16-max
      mode="dark"
      className="cadrenza-phone-device"
      aria-label="Aperçu mobile de la planification d’une formation"
    >
      <div className="cadrenza-phone-screen">
        <div className="cadrenza-phone-robot">
          <span className="cadrenza-phone-robot__glow" aria-hidden="true" />
          <img src="/robot-blue.png" alt="" />
        </div>

        <section className="cadrenza-phone-calendar" aria-label="Calendrier de formation">
          <h3>Jours de formation</h3>
          <div className="cadrenza-phone-calendar__weekdays" aria-hidden="true">
            {["L", "M", "M", "J", "V", "S", "D"].map((day, index) => (
              <span key={`${day}-${index}`}>{day}</span>
            ))}
          </div>
          <div className="cadrenza-phone-calendar__grid" aria-hidden="true">
            {CALENDAR_WEEKS.flat().map(({ day, muted, selected }, index) => (
              <span
                key={`${day}-${index}`}
                className={[
                  muted ? "is-muted" : "",
                  selected ? "is-selected" : "",
                ].filter(Boolean).join(" ")}
              >
                {day}
              </span>
            ))}
          </div>
        </section>

        <section className="cadrenza-phone-duration" aria-label="Durée du parcours">
          <h3>Durée du parcours</h3>
          <div className="cadrenza-phone-duration__options">
            {DURATIONS.map((duration) => (
              <div
                key={duration}
                className={duration === "12 mois" ? "is-selected" : ""}
              >
                <span aria-hidden="true" />
                <strong>{duration}</strong>
              </div>
            ))}
          </div>
        </section>
      </div>
    </iphone-16-max>
  </div>
);
