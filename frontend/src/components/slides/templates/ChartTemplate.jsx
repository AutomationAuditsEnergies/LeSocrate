import React from "react";
import "../styles/chart.css";

/* --- COMPOSANT GRAPHIQUE SVG --- */
const PlayfulAreaChart = ({ data }) => {
  const width = 500;
  const height = 350;
  const padding = 40;

  const chartW = width - padding * 2;
  const chartH = height - padding * 2;

  // Utiliser les données fournies ou des données par défaut
  const defaultPaths = [
    { path: `M 0,${chartH} L 0,200 L 100,150 L 200,50 L 300,45 L 420,20 L 420,${chartH} Z`, fill: "#81D4FA", stroke: "#29B6F6" },
    { path: `M 0,${chartH} L 0,250 L 120,230 L 220,120 L 300,140 L 420,80 L 420,${chartH} Z`, fill: "#CE93D8", stroke: "#AB47BC" },
    { path: `M 0,${chartH} L 0,${chartH-20} L 140,${chartH-60} L 240,${chartH-130} L 320,${chartH-110} L 420,${chartH-120} L 420,${chartH} Z`, fill: "#DCE775", stroke: "#CDDC39" }
  ];

  const paths = data?.paths || defaultPaths;
  const yLabels = data?.yLabels || [140, 112, 84, 56, 28, 0];
  const xLabels = data?.xLabels || ["Item 1", "Item 2", "Item 3", "Item 4", "Item 5"];

  return (
    <div className="chart-frame">
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
      >
        {/* Grille de fond (Lignes horizontales) */}
        {yLabels.map((label, i) => {
          const y = padding + (chartH / (yLabels.length - 1)) * i;
          return (
            <g key={i}>
              <line
                x1={padding}
                y1={y}
                x2={width - padding}
                y2={y}
                className="chart-grid-line"
              />
              <text
                x={padding - 10}
                y={y + 5}
                textAnchor="end"
                className="chart-text"
                style={{ fontSize: "12px", opacity: 0.6 }}
              >
                {label}
              </text>
            </g>
          );
        })}

        {/* Zone de dessin décalée par le padding */}
        <g transform={`translate(${padding}, ${padding})`}>
          {paths.map((pathData, idx) => (
            <path
              key={idx}
              d={pathData.path}
              fill={pathData.fill}
              stroke={pathData.stroke}
              strokeWidth="2"
              fillOpacity={0.6 + idx * 0.1}
            />
          ))}
        </g>

        {/* Labels Axe X */}
        {xLabels.map((label, i) => (
          <text
            key={i}
            x={padding + (chartW / (xLabels.length - 1)) * i}
            y={height - 15}
            textAnchor="middle"
            className="chart-text"
            style={{ fontWeight: 600 }}
          >
            {label}
          </text>
        ))}
      </svg>
    </div>
  );
};

const ChartTemplate = ({ title, description, chartData, badge = "TP-CRCD", brandName = "SALES HACKING" }) => {
  return (
    <div className="chart-slide-container">
      {/* HEADER */}
      <div className="chart-header-bar">
        <div className="chart-header-badge">{badge}</div>
        <div className="chart-header-right">
          <span className="chart-brand-name">{brandName}</span>
        </div>
      </div>

      {/* MAIN CONTENT */}
      <div className="chart-main-content">
        {/* GAUCHE : TEXTE */}
        <div className="chart-text-column">
          <h1 className="chart-slide-title">{title}</h1>
          <p className="chart-slide-desc">{description}</p>
        </div>

        {/* DROITE : GRAPHIQUE */}
        <div className="chart-chart-column">
          <PlayfulAreaChart data={chartData} />
        </div>
      </div>
    </div>
  );
};

export default ChartTemplate;
