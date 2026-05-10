import React from "react";
import "../styles/RecapTemplate.css";

const Header = ({ badge = "TP-CRCD", brandName = "SALES HACKING" }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-gray-200 z-10">
    <div className="bg-red-600 text-white font-bold py-2 px-4 text-sm rounded-md">
      {badge}
    </div>
    <span className="font-bold text-sm uppercase tracking-wide">{brandName}</span>
  </div>
);

const CheckIcon = () => (
  <svg className="check-icon" viewBox="0 0 100 100">
    <circle cx="50" cy="50" r="45" fill="#DCE775" stroke="none" opacity="0.5" />
    <path
      d="M20 50 L 40 70 L 85 20"
      fill="none"
      stroke="#2d241e"
      strokeWidth="8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const RecapTemplate = ({ title, points = [], badge, brandName }) => {
  return (
    <div className="recap-slide">
      <Header badge={badge} brandName={brandName} />

      <div className="flex-1 flex flex-col items-center justify-center p-6">
        <h1 className="font-fredoka text-5xl mb-5 text-center recap-title-text">
          {title}
        </h1>

        <div className="recap-sheet">
          <div className="tape-strip"></div>

          <ul className="check-list">
            {points.map((point, index) => (
              <li key={index} className="check-item">
                <CheckIcon />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
};

export default RecapTemplate;
