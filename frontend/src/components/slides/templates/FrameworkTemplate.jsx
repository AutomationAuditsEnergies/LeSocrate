import React from 'react';

const DEFAULT_PALETTE = [
  '#F4A332',
  '#7FCFC9',
  '#3FA6A0',
  '#A7B85A',
  '#F4D55A',
  '#E07A6F',
];

const VIEWBOX = 600;
const CENTER = VIEWBOX / 2;
const RING_RADIUS = 210;
const RING_STROKE = 36;
const CORE_RADIUS = 160;

const polar = (angle, radius) => [
  CENTER + radius * Math.cos(angle),
  CENTER + radius * Math.sin(angle),
];

const buildArc = (startAngle, endAngle) => {
  const [x1, y1] = polar(startAngle, RING_RADIUS);
  const [x2, y2] = polar(endAngle, RING_RADIUS);
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
  return `M ${x1} ${y1} A ${RING_RADIUS} ${RING_RADIUS} 0 ${largeArc} 1 ${x2} ${y2}`;
};

const buildArrow = (centerAngle) => {
  const headRadius = RING_RADIUS;
  const headWidth = 12;
  const tipExtension = 14;
  const [tipX, tipY] = polar(centerAngle, headRadius + tipExtension);
  const baseAngle = centerAngle - Math.PI / 2;
  const [b1x, b1y] = [
    CENTER + headRadius * Math.cos(centerAngle) + headWidth * Math.cos(baseAngle),
    CENTER + headRadius * Math.sin(centerAngle) + headWidth * Math.sin(baseAngle),
  ];
  const [b2x, b2y] = [
    CENTER + headRadius * Math.cos(centerAngle) - headWidth * Math.cos(baseAngle),
    CENTER + headRadius * Math.sin(centerAngle) - headWidth * Math.sin(baseAngle),
  ];
  return `M ${b1x} ${b1y} L ${tipX} ${tipY} L ${b2x} ${b2y} Z`;
};

const FrameworkTemplate = ({
  title = 'Les 4 forces de Porter',
  center = { title: 'Intensité de rivalité entre concurrents' },
  segments = [
    { title: 'Menace des nouveaux entrants', desc: "Barrières à l'entrée faibles." },
    { title: 'Menace des produits de substitution', desc: 'Alternatives plus efficaces.' },
    { title: 'Pouvoir de négociation des clients', desc: 'Clients nombreux ou concentrés.' },
    { title: 'Pouvoir de négociation des fournisseurs', desc: 'Fournisseurs peu nombreux.' },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => {
  const n = segments.length;
  const segmentAngle = (2 * Math.PI) / n;
  const gapAngle = 0.08;

  const arcs = segments.map((seg, i) => {
    const startAngle = -Math.PI / 2 + i * segmentAngle + gapAngle / 2;
    const endAngle = -Math.PI / 2 + (i + 1) * segmentAngle - gapAngle / 2;
    return {
      d: buildArc(startAngle, endAngle),
      arrow: buildArrow(endAngle),
      color: seg.color || DEFAULT_PALETTE[i % DEFAULT_PALETTE.length],
    };
  });

  // Adaptive elliptical placement, tuned per satellite type:
  // - lateral satellites (3h/9h on n=6, or n=4 quadrants): close to the ring;
  // - vertical-top satellites (Fidélisation/Prospection on n=6): wider apart
  //   horizontally, lower vertically (so they nest under the title without
  //   floating too high or overlapping the ring);
  // - vertical-bottom satellites (Closing/Argumentaire on n=6): kept where
  //   they were (validated visually).
  const SAT_WIDTH_PCT = 16.7; // 200px / 1200px
  const SAT_HALF_PCT = SAT_WIDTH_PCT / 2;
  const SAT_HEIGHT_PCT = 12; // approximate height of a 2-line title + 1-line desc
  const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

  const satellites = segments.map((seg, i) => {
    const angle = -Math.PI / 2 + (i + 0.5) * segmentAngle;
    const dx = Math.cos(angle);
    const dy = Math.sin(angle);

    const isLateral = Math.abs(dx) > 0.6;
    let dxFactor;
    let dyFactor;
    if (isLateral) {
      dxFactor = n >= 6 ? 0.18 : 0.22;
      dyFactor = 0.30;
    } else if (dy < 0) {
      dxFactor = n >= 6 ? 0.36 : 0.22;
      dyFactor = n >= 6 ? 0.34 : 0.30;
    } else {
      dxFactor = 0.22;
      dyFactor = n >= 6 ? 0.40 : 0.30;
    }

    const rawLeft = 50 + dx * dxFactor * 100;
    const rawTop = 50 + dy * dyFactor * 100;

    let translate;
    let textAlign;
    let leftMin = SAT_HALF_PCT;
    let leftMax = 100 - SAT_HALF_PCT;
    let topMin = SAT_HEIGHT_PCT / 2;
    let topMax = 100 - SAT_HEIGHT_PCT / 2;

    if (Math.abs(dx) > 0.6) {
      // Horizontal-dominant: anchor to the side, vertically centered.
      if (dx < 0) {
        translate = 'translate(-100%, -50%)';
        textAlign = 'right';
        leftMin = SAT_WIDTH_PCT;
        leftMax = 50;
      } else {
        translate = 'translate(0%, -50%)';
        textAlign = 'left';
        leftMin = 50;
        leftMax = 100 - SAT_WIDTH_PCT;
      }
    } else {
      // Vertical-dominant: anchor above/below the arc, horizontally centered.
      // Text aligns toward the outer edge of the slide so multi-line wraps lean
      // away from the ring (longer lines run outward, shorter ones tuck in).
      textAlign = dx < 0 ? 'left' : 'right';
      if (dy < 0) {
        translate = 'translate(-50%, -100%)';
        topMin = SAT_HEIGHT_PCT;
        topMax = 50;
      } else {
        translate = 'translate(-50%, 0%)';
        topMin = 50;
        topMax = 100 - SAT_HEIGHT_PCT;
      }
    }

    const left = clamp(rawLeft, leftMin, leftMax);
    const top = clamp(rawTop, topMin, topMax);

    return {
      ...seg,
      style: {
        left: `${left}%`,
        top: `${top}%`,
        transform: translate,
        textAlign,
      },
    };
  });

  return (
    <div className="aspect-video w-[90vw] max-w-[1200px] bg-[#FFF9E6] flex flex-col overflow-hidden shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)] relative">

      <div className="flex justify-between items-center px-10 py-3 bg-white border-b-2 border-[#E5E5E5] z-10">
        <div className="bg-[#DC2626] text-white font-['Poppins'] font-bold px-4 py-2 text-[0.85rem] rounded-md">
          {badge}
        </div>
        <span className="font-['Poppins'] font-bold text-[0.95rem] uppercase text-[#2d241e]">
          {brandName}
        </span>
      </div>

      <div className="flex-1 flex flex-col items-center px-10 pt-5 pb-4 relative">
        <h1 className="font-['Fredoka'] text-[2rem] text-[#2d241e] uppercase font-bold text-center leading-tight mb-2 max-w-[85%]">
          {title}
        </h1>

        <div className="relative flex-1 w-full flex items-center justify-center">
          <svg
            viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`}
            className="absolute inset-0 m-auto"
            style={{ height: '100%', width: '100%', maxHeight: '420px' }}
            preserveAspectRatio="xMidYMid meet"
          >
            {arcs.map((arc, i) => (
              <g key={i}>
                <path
                  d={arc.d}
                  stroke={arc.color}
                  strokeWidth={RING_STROKE}
                  fill="none"
                  strokeLinecap="butt"
                />
                <path d={arc.arrow} fill={arc.color} />
              </g>
            ))}

            <circle
              cx={CENTER}
              cy={CENTER}
              r={CORE_RADIUS}
              fill="white"
              stroke="#E5E5E5"
              strokeWidth="1.5"
            />

            <foreignObject
              x={CENTER - CORE_RADIUS + 14}
              y={CENTER - CORE_RADIUS + 14}
              width={CORE_RADIUS * 2 - 28}
              height={CORE_RADIUS * 2 - 28}
            >
              <div className="w-full h-full flex items-center justify-center text-center">
                <span className="font-['Poppins'] font-bold text-[1.25rem] uppercase text-[#2d241e] leading-tight tracking-wide">
                  {center?.title}
                </span>
              </div>
            </foreignObject>
          </svg>

          {satellites.map((sat, i) => (
            <div
              key={i}
              className="absolute z-10"
              style={{ ...sat.style, width: '200px' }}
            >
              <div
                className="font-['Poppins'] font-bold text-[#2d241e] text-[0.95rem] leading-tight mb-1"
                style={{ textAlign: sat.style.textAlign }}
              >
                {sat.title}
              </div>
              <div
                className="font-['Poppins'] text-[#555] text-[0.8rem] leading-snug"
                style={{ textAlign: sat.style.textAlign }}
              >
                {sat.desc}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default FrameworkTemplate;
