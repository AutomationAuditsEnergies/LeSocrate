import React from "react";
import "../styles/TransitionTemplate.css";

const Header = ({ badge = "TP-CRCD", brandName = "SALES HACKING" }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-gray-200 z-10">
    <div className="bg-red-600 text-white font-bold py-2 px-4 text-sm rounded-md">
      {badge}
    </div>
    <span className="font-bold text-sm uppercase tracking-wide">{brandName}</span>
  </div>
);

const ArrowIcon = () => (
  <svg className="transition-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="5" y1="12" x2="19" y2="12"/>
    <polyline points="12 5 19 12 12 19"/>
  </svg>
);

const TransitionTemplate = ({ title, from_topic, to_topic, badge, brandName }) => {
  return (
    <div className="transition-slide">
      <Header badge={badge} brandName={brandName} />

      <div className="flex-1 flex flex-col items-center justify-center p-8">
        {/* Titre principal */}
        <h1 className="font-fredoka text-4xl transition-title">
          {title || "Passons à la suite"}
        </h1>

        {/* Zone de transition visuelle */}
        {(from_topic || to_topic) && (
          <div className="transition-flow">
            {/* Sujet précédent */}
            {from_topic && (
              <div className="transition-topic transition-from">
                <span className="transition-label">On quitte</span>
                <span className="transition-topic-text">{from_topic}</span>
              </div>
            )}

            {/* Flèche animée */}
            <div className="transition-arrow-container">
              <div className="transition-arrow-line"></div>
              <ArrowIcon />
            </div>

            {/* Nouveau sujet */}
            {to_topic && (
              <div className="transition-topic transition-to">
                <span className="transition-label">On aborde</span>
                <span className="transition-topic-text">{to_topic}</span>
              </div>
            )}
          </div>
        )}

        {/* Décoration de points */}
        <div className="transition-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>
    </div>
  );
};

export default TransitionTemplate;
