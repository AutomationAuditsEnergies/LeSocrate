import React from "react";
import "../styles/StoryTemplate.css";

const Header = ({ badge = "TP-CRCD", brandName = "SALES HACKING" }) => (
  <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-gray-200 z-10">
    <div className="bg-red-600 text-white font-bold py-2 px-4 text-sm rounded-md">
      {badge}
    </div>
    <span className="font-bold text-sm uppercase tracking-wide">{brandName}</span>
  </div>
);

const QuoteIconLeft = () => (
  <svg className="quote-mark quote-left" viewBox="0 0 24 24">
    <path d="M6 17h3l2-4V7H5v6h3zm8 0h3l2-4V7h-6v6h3z" />
  </svg>
);

const QuoteIconRight = () => (
  <svg className="quote-mark quote-right" viewBox="0 0 24 24">
    <path d="M6 17h3l2-4V7H5v6h3zm8 0h3l2-4V7h-6v6h3z" />
  </svg>
);

const StoryTemplate = ({ title, narrative, moral, badge, brandName }) => {
  return (
    <div className="story-slide">
      <Header badge={badge} brandName={brandName} />

      <div className="flex-1 flex flex-col items-center justify-center px-16 pb-12">
        {/* Bandeau Titre Sombre */}
        <div className="story-title-banner w-full py-6 px-12 mt-8 mb-12 text-left rounded shadow-lg">
          <h1 className="font-fredoka text-4xl uppercase tracking-wider m-0 text-white">
            {title}
          </h1>
        </div>

        {/* Zone Citation */}
        <div className="story-quote-wrapper relative max-w-4xl text-left mb-12 px-12">
          <QuoteIconLeft />
          <p className="font-poppins text-3xl leading-relaxed text-gray-800 font-normal">
            {narrative}
          </p>
          <QuoteIconRight />
        </div>

        {/* Bloc Morale Orange */}
        <div className="story-moral-box py-6 px-12 rounded-xl">
          <p className="font-fredoka text-xl text-center m-0 text-amber-900">
            {moral}
          </p>
        </div>
      </div>
    </div>
  );
};

export default StoryTemplate;
