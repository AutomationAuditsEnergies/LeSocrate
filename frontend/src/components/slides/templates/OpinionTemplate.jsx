import React from "react";
import "../styles/OpinionTemplate.css";

const Header = ({ badge = "TP-CRCD", brandName = "SALES HACKING" }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-gray-200 z-10">
    <div className="bg-red-600 text-white font-bold py-2 px-4 text-sm rounded-md">
      {badge}
    </div>
    <span className="font-bold text-sm uppercase tracking-wide">{brandName}</span>
  </div>
);

const QuoteIcon = () => (
  <svg className="opinion-quote-icon" viewBox="0 0 24 24" fill="currentColor">
    <path d="M6 17h3l2-4V7H5v6h3zm8 0h3l2-4V7h-6v6h3z"/>
  </svg>
);

const UserIcon = () => (
  <svg className="opinion-user-icon" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
  </svg>
);

const OpinionTemplate = ({ title, text, badge, brandName }) => {
  return (
    <div className="opinion-slide">
      <Header badge={badge} brandName={brandName} />

      <div className="flex-1 flex flex-col items-center justify-center p-8">
        {/* Container principal */}
        <div className="opinion-container">
          {/* Icône de citation en arrière-plan */}
          <div className="opinion-quote-bg">
            <QuoteIcon />
          </div>

          {/* Badge "Point de vue" */}
          <div className="opinion-badge">
            <UserIcon />
            <span>POINT DE VUE DU FORMATEUR</span>
          </div>

          {/* Titre */}
          <h1 className="font-fredoka text-3xl opinion-title">
            {title}
          </h1>

          {/* Bulle d'opinion */}
          <div className="opinion-bubble">
            <p className="font-poppins text-xl opinion-text">
              "{text}"
            </p>
            <div className="opinion-bubble-tail"></div>
          </div>

          {/* Signature */}
          <div className="opinion-signature">
            <div className="opinion-avatar">
              <UserIcon />
            </div>
            <div className="opinion-author">
              <span className="opinion-author-label">Votre formateur</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OpinionTemplate;
