import React from 'react';
import '../styles/playful.css';

/* --- LES DOODLES SVG --- */
const StarDoodle = () => (
  <svg className="playful-doodle playful-doodle-star" viewBox="0 0 100 100" fill="none" stroke="#F59E0B" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M50 5 L63 35 L95 35 L70 55 L80 85 L50 70 L20 85 L30 55 L5 35 L37 35 Z" />
  </svg>
);

const PlaneDoodle = () => (
  <svg className="playful-doodle playful-doodle-plane" viewBox="0 0 100 100" fill="#3B82F6" stroke="#1d4ed8" strokeWidth="2">
    <path d="M10 50 L90 10 L50 90 L40 60 L10 50 Z" />
  </svg>
);

const ClipDoodle = () => (
  <svg className="playful-doodle playful-doodle-clip" viewBox="0 0 50 100" fill="none" stroke="#FCD34D" strokeWidth="6" strokeLinecap="round">
    <path d="M15 20 L15 80 A10 10 0 0 0 35 80 L35 10 A10 10 0 0 0 15 10 L15 60" />
  </svg>
);

const CloudDoodle = () => (
  <svg className="playful-doodle playful-doodle-cloud" viewBox="0 0 100 60" fill="none" stroke="#d1d5db" strokeWidth="2">
    <path d="M10 50 Q20 30 40 40 T70 30 T90 50" />
  </svg>
);

const PlayfulTemplate = ({ title, cards, badge = "TP-CRCD", brandName = "Sales Hacking" }) => {
  return (
    <div className="playful-slide-container">

      {/* HEADER IDENTITÉ */}
      <div className="playful-header-bar">
        <div className="playful-header-badge">{badge}</div>
        <div className="playful-header-right">
          <span className="playful-brand-name">{brandName}</span>
        </div>
      </div>

      {/* CONTENU */}
      <div className="playful-main-content">

        {/* Les décorations */}
        <StarDoodle />
        <PlaneDoodle />
        <ClipDoodle />
        <CloudDoodle />

        <h1 className="playful-main-title">{title}</h1>

        <div className="playful-cards-grid">
          {cards.map((card, idx) => (
            <div key={idx} className="playful-card">
              <div className="playful-image-container">
                <img src={card.img} alt={card.title} className="playful-card-img" />
              </div>
              <h3 className="playful-card-title">{card.title}</h3>
              <p className="playful-card-desc">{card.desc}</p>
            </div>
          ))}
        </div>

      </div>
    </div>
  );
};

export default PlayfulTemplate;
