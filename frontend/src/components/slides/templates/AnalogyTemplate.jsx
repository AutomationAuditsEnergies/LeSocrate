import React from "react";
import "../styles/AnalogyTemplate.css";

const Header = ({ badge = "TP-CRCD", brandName = "SALES HACKING" }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-gray-200 z-10">
    <div className="bg-red-600 text-white font-bold py-2 px-4 text-sm rounded-md">
      {badge}
    </div>
    <span className="font-bold text-sm uppercase tracking-wide">{brandName}</span>
  </div>
);

const AnalogyTemplate = ({ title, text, concept, comparison, badge, brandName }) => {
  return (
    <div className="analogy-slide">
      <Header badge={badge} brandName={brandName} />

      <div className="flex-1 flex flex-col items-center justify-center p-8">
        {/* Titre principal */}
        <h1 className="font-fredoka text-3xl mb-5 text-center analogy-title">
          {title}
        </h1>

        {/* Zone de comparaison visuelle */}
        <div className="analogy-comparison-zone">
          {/* Concept */}
          <div className="analogy-box analogy-concept">
            <div className="analogy-icon">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
              </svg>
            </div>
            <span className="analogy-label">{concept || "Le concept"}</span>
          </div>

          {/* Symbole égal / comme */}
          <div className="analogy-equals">
            <span>=</span>
            <span className="analogy-comme">comme</span>
          </div>

          {/* Comparaison */}
          <div className="analogy-box analogy-like">
            <div className="analogy-icon analogy-icon-like">
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z"/>
              </svg>
            </div>
            <span className="analogy-label">{comparison || "L'analogie"}</span>
          </div>
        </div>

        {/* Explication */}
        <div className="analogy-explanation">
          <p className="font-poppins text-xl leading-relaxed text-gray-700">
            {text}
          </p>
        </div>
      </div>
    </div>
  );
};

export default AnalogyTemplate;
