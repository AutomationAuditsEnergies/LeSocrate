import React from 'react';
import '../styles/facilitator.css';

/* --- ICONS UNIVERSELLES --- */
const IconTarget = () => (
  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#2d241e" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10"></circle>
    <circle cx="12" cy="12" r="6"></circle>
    <circle cx="12" cy="12" r="2"></circle>
  </svg>
);

const IconGear = () => (
  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#2d241e" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/>
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1Z"/>
  </svg>
);

const IconFlash = () => (
  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#2d241e" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
  </svg>
);

const IconFlag = () => (
  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#2d241e" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"></path>
    <line x1="4" y1="22" x2="4" y2="15"></line>
  </svg>
);

/* --- FLÈCHE SIMPLE ET PROPRE --- */
const ArrowDoodle = () => (
  <div className="facilitator-arrow-connector">
    <svg width="60" height="24" viewBox="0 0 60 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Ligne principale */}
      <path
        d="M 2 12 L 50 12"
        stroke="#2d241e"
        strokeWidth="2"
        strokeLinecap="round"
      />
      {/* Pointe de flèche (triangle) */}
      <path
        d="M 42 6 L 52 12 L 42 18"
        stroke="#2d241e"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  </div>
);

// Mapping des icônes par type
const ICON_MAP = {
  target: IconTarget,
  gear: IconGear,
  flash: IconFlash,
  flag: IconFlag,
};

// Mapping des formes par couleur
const SHAPE_MAP = {
  orange: 'facilitator-shape-orange',
  purple: 'facilitator-shape-purple',
  lime: 'facilitator-shape-lime',
  blue: 'facilitator-shape-blue',
};

const FacilitatorTemplate = ({ title, steps, badge = "TP-CRCD", brandName = "SALES HACKING" }) => {
  return (
    <div className="facilitator-slide-container">

      {/* HEADER */}
      <div className="facilitator-header-bar">
        <div className="facilitator-header-badge">{badge}</div>
        <div className="facilitator-header-right">
          <span className="facilitator-brand-name">{brandName}</span>
        </div>
      </div>

      {/* CONTENU */}
      <div className="facilitator-main-content">

        <h1 className="facilitator-slide-title">{title}</h1>

        <div className="facilitator-process-container">

          {steps.map((step, idx) => {
            const IconComponent = ICON_MAP[step.icon] || IconTarget;
            const shapeClass = SHAPE_MAP[step.color] || 'facilitator-shape-orange';

            return (
              <React.Fragment key={idx}>
                {/* Étape */}
                <div className="facilitator-process-step">
                  <div className={`facilitator-icon-wrapper ${shapeClass}`}>
                    <IconComponent />
                  </div>
                  <h3 className="facilitator-step-title">{step.title}</h3>
                  <p className="facilitator-step-desc">{step.desc}</p>
                </div>

                {/* Flèche (sauf après la dernière étape) */}
                {idx < steps.length - 1 && <ArrowDoodle />}
              </React.Fragment>
            );
          })}

        </div>

      </div>
    </div>
  );
};

export default FacilitatorTemplate;
