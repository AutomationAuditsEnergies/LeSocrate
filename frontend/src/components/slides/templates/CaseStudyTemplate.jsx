import React from 'react';
import '../styles/casestudy.css';

const CaseStudyTemplate = ({ title = "Case Study", cases, badge = "TP-CRCD", brandName = "SALES HACKING" }) => {
  // Couleurs de cartes et de numéros par défaut (cycle sur 3)
  const cardColors = ['casestudy-card-yellow', 'casestudy-card-green', 'casestudy-card-blue'];
  const numColors = ['casestudy-num-purple', 'casestudy-num-orange', 'casestudy-num-lime'];

  return (
    <div className="casestudy-slide-container">

      {/* HEADER */}
      <div className="casestudy-header-bar">
        <div className="casestudy-header-badge">{badge}</div>
        <div className="casestudy-header-right">
          <span className="casestudy-brand-name">{brandName}</span>
        </div>
      </div>

      {/* CONTENU PRINCIPAL */}
      <div className="casestudy-main-content">

        {/* Titre */}
        <h1 className="casestudy-main-title">{title}</h1>

        {/* La Grille de cartes */}
        <div className="casestudy-case-grid">

          {cases.map((caseItem, idx) => (
            <div key={idx} className={`casestudy-case-card ${cardColors[idx % 3]}`}>
              <h2 className="casestudy-case-title">{caseItem.title}</h2>
              <p className="casestudy-case-desc">{caseItem.desc}</p>
              <div className={`casestudy-case-number ${numColors[idx % 3]}`}>
                {idx + 1}
              </div>
            </div>
          ))}

        </div>

      </div>
    </div>
  );
};

export default CaseStudyTemplate;
