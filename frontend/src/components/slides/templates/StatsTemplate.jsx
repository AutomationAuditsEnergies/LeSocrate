import React from "react";

const StatsTemplate = ({
  eyebrow = "We Provide To",
  title = "Marketplace",
  description,
  stats = [],
  columns = [],
  badge = "TP-CRCD",
  brandName = "SALES HACKING"
}) => {
  // Stats par défaut si non fournis
  const defaultStats = stats.length > 0 ? stats : [
    { number: "2M" },
    { number: "100K" },
    { number: "82%" }
  ];

  // Colonnes de texte par défaut
  const defaultColumns = columns.length > 0 ? columns : [
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore.",
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore.",
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore."
  ];

  return (
    <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)] relative">

      {/* HEADER */}
      <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5] z-10">
        <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">
          {badge}
        </div>
        <div className="flex items-center">
          <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">
            {brandName}
          </span>
        </div>
      </div>

      {/* MAIN CONTENT */}
      <div className="flex-1 px-14 py-4 flex flex-col items-center justify-start">

        {/* SECTION TITRE */}
        <div className="text-center mb-3 max-w-[800px]">
          <div className="font-['Poppins'] text-[0.8rem] font-semibold tracking-widest text-[#666] uppercase mb-1">
            {eyebrow}
          </div>
          <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] leading-tight mb-2 uppercase">
            {title}
          </h1>
          <p className="font-['Poppins'] text-[0.9rem] text-[#555] leading-relaxed">
            {description || "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore."}
          </p>
        </div>

        {/* BANDEAU STATS */}
        <div className="w-full bg-[#81D4FA] rounded-[20px] border-2 border-[#2d241e] shadow-[8px_8px_0_rgba(0,0,0,0.05)] py-2 flex justify-around items-center mb-4">
          {defaultStats.map((stat, idx) => (
            <div key={idx} className="text-center">
              <div className="font-['Fredoka'] text-[3rem] font-bold text-[#2d241e] leading-none">
                {stat.number}
              </div>
            </div>
          ))}
        </div>

        {/* COLONNES TEXTE */}
        <div className="flex justify-between w-full gap-8">
          {defaultColumns.map((text, idx) => (
            <div key={idx} className="flex-1 text-center font-['Poppins'] text-[0.9rem] text-[#4a4a4a] leading-relaxed px-4">
              {text}
            </div>
          ))}
        </div>

      </div>
    </div>
  );
};

export default StatsTemplate;
