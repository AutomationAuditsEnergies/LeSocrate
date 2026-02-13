import React from "react";
import "../styles/TipTemplate.css";

const Header = ({ badge = "TP-CRCD", brandName = "SALES HACKING" }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-gray-200 z-10">
    <div className="bg-red-600 text-white font-bold py-2 px-4 text-sm rounded-md">
      {badge}
    </div>
    <span className="font-bold text-sm uppercase tracking-wide">{brandName}</span>
  </div>
);

const LightbulbIcon = () => (
  <svg className="tip-icon" viewBox="0 0 24 24" fill="currentColor">
    <path d="M9 21c0 .55.45 1 1 1h4c.55 0 1-.45 1-1v-1H9v1zm3-19C8.14 2 5 5.14 5 9c0 2.38 1.19 4.47 3 5.74V17c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-2.26c1.81-1.27 3-3.36 3-5.74 0-3.86-3.14-7-7-7zm2.85 11.1l-.85.6V16h-4v-2.3l-.85-.6A4.997 4.997 0 017 9c0-2.76 2.24-5 5-5s5 2.24 5 5c0 1.63-.8 3.16-2.15 4.1z"/>
  </svg>
);

const StarIcon = () => (
  <svg className="tip-star" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/>
  </svg>
);

const TipTemplate = ({ title, text, badge, brandName }) => {
  return (
    <div className="tip-slide">
      <Header badge={badge} brandName={brandName} />

      <div className="flex-1 flex flex-col items-center justify-center p-8">
        {/* Carte principale */}
        <div className="tip-card">
          {/* Icône ampoule en haut */}
          <div className="tip-icon-container">
            <LightbulbIcon />
          </div>

          {/* Badge "Astuce" */}
          <div className="tip-badge-container">
            <StarIcon />
            <span className="tip-badge">ASTUCE PRO</span>
            <StarIcon />
          </div>

          {/* Titre */}
          <h1 className="font-fredoka text-3xl tip-title">
            {title}
          </h1>

          {/* Contenu */}
          <div className="tip-content">
            <p className="font-poppins text-lg tip-text">
              {text}
            </p>
          </div>

          {/* Décoration bottom */}
          <div className="tip-decoration">
            <div className="tip-dot"></div>
            <div className="tip-dot"></div>
            <div className="tip-dot"></div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TipTemplate;
