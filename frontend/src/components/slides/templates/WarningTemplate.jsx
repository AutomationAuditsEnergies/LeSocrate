import React from "react";
import "../styles/WarningTemplate.css";

const Header = ({ badge = "TP-CRCD", brandName = "SALES HACKING" }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-gray-200 z-10">
    <div className="bg-red-600 text-white font-bold py-2 px-4 text-sm rounded-md">
      {badge}
    </div>
    <span className="font-bold text-sm uppercase tracking-wide">{brandName}</span>
  </div>
);

const AlertTriangle = () => (
  <svg className="warning-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
    <line x1="12" y1="9" x2="12" y2="13"/>
    <line x1="12" y1="17" x2="12.01" y2="17"/>
  </svg>
);

const WarningTemplate = ({ title, text, badge, brandName }) => {
  return (
    <div className="warning-slide">
      <Header badge={badge} brandName={brandName} />

      <div className="flex-1 flex flex-col items-center justify-center p-8">
        {/* Zone d'alerte principale */}
        <div className="warning-container">
          {/* Bande latérale rouge */}
          <div className="warning-stripe"></div>

          {/* Contenu */}
          <div className="warning-content">
            {/* En-tête avec icône */}
            <div className="warning-header">
              <div className="warning-icon-wrapper">
                <AlertTriangle />
              </div>
              <span className="warning-badge">ATTENTION</span>
            </div>

            {/* Titre */}
            <h1 className="font-fredoka text-3xl warning-title">
              {title}
            </h1>

            {/* Ligne de séparation */}
            <div className="warning-divider"></div>

            {/* Texte explicatif */}
            <p className="font-poppins text-lg warning-text">
              {text}
            </p>
          </div>
        </div>

        {/* Indicateur visuel en bas */}
        <div className="warning-footer">
          <span className="warning-footer-text">Erreur fréquente à éviter</span>
        </div>
      </div>
    </div>
  );
};

export default WarningTemplate;
