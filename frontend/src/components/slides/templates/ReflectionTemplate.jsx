import React from 'react';
import '../styles/reflection.css';

/* --- DOODLES SVG --- */
const BulbDoodle = () => (
  <svg className="reflection-doodle reflection-doodle-bulb" viewBox="0 0 100 120" fill="none" stroke="#FCD34D" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
    <path d="M30 90 L70 90 L70 110 L30 110 Z M50 90 L50 100" stroke="#d97706" />
    <path d="M20 60 A30 30 0 0 1 80 60 C80 80 70 90 70 90 L30 90 C30 90 20 80 20 60 Z" stroke="#d97706" />
    <path d="M40 30 L60 30" stroke="#d97706" />
    <path d="M45 45 L55 45" stroke="#d97706" />
  </svg>
);

const StarDoodle = () => (
  <svg className="reflection-doodle reflection-doodle-star" viewBox="0 0 100 100" fill="none" stroke="#F59E0B" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M50 5 L63 35 L95 35 L70 55 L80 85 L50 70 L20 85 L30 55 L5 35 L37 35 Z" />
  </svg>
);

const SquiggleDoodle = () => (
  <svg className="reflection-doodle reflection-doodle-squig" viewBox="0 0 100 100" fill="none" stroke="#EF4444" strokeWidth="4" strokeLinecap="round">
    <path d="M10 50 Q 25 25, 50 50 T 90 50" />
  </svg>
);

const ReflectionTemplate = ({ title, text, badge = "TP-CRCD", brandName = "SALES HACKING" }) => {
  return (
    <div className="reflection-slide-container">

      {/* HEADER */}
      <div className="reflection-header-bar">
        <div className="reflection-header-badge">{badge}</div>
        <div className="reflection-header-right">
          <span className="reflection-brand-name">{brandName}</span>
        </div>
      </div>

      {/* CONTENU PRINCIPAL */}
      <div className="reflection-main-content">

        {/* Les décos de fond */}
        <BulbDoodle />
        <StarDoodle />
        <SquiggleDoodle />

        {/* Le Panneau Jaune (Clipboard) */}
        <div className="reflection-clipboard-board">

          {/* L'attache noire complexe (CSS pur) */}
          <div className="reflection-clipboard-clip"></div>

          <h1 className="reflection-clipboard-title">{title}</h1>

          <p className="reflection-clipboard-text">{text}</p>
        </div>

      </div>
    </div>
  );
};

export default ReflectionTemplate;
