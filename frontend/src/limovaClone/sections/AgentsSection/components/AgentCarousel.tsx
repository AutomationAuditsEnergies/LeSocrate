import { useEffect, useState, type KeyboardEvent, type PointerEvent } from "react";
import "./AgentCarousel.css";

type ArrowId = "slides" | "training" | "students";
type ArrowPoint = { x: number; y: number };
type ArrowPoints = Record<ArrowId, ArrowPoint>;

const ARROW_STORAGE_KEY = "cadrenza-pierre-arrow-points";
const defaultArrowPoints: ArrowPoints = {
  slides: { x: 424, y: 228 },
  training: { x: 680, y: 224 },
  students: { x: 756, y: 148 },
};

const capabilities = [
  {
    className: "cadrenza-pierre-callout--slides",
    index: "01",
    text: "Prépare les diapositives du module",
  },
  {
    className: "cadrenza-pierre-callout--training",
    index: "02",
    text: "Anime les journées de formation",
  },
  {
    className: "cadrenza-pierre-callout--students",
    index: "03",
    text: "Interagit avec les élèves en direct",
  },
];

export const AgentCarousel = () => {
  const [arrowPoints, setArrowPoints] = useState<ArrowPoints>(() => {
    if (typeof window === "undefined") return defaultArrowPoints;

    try {
      const savedPoints = window.localStorage.getItem(ARROW_STORAGE_KEY);
      return savedPoints
        ? ({ ...defaultArrowPoints, ...JSON.parse(savedPoints) } as ArrowPoints)
        : defaultArrowPoints;
    } catch {
      return defaultArrowPoints;
    }
  });
  const [draggedArrow, setDraggedArrow] = useState<ArrowId | null>(null);
  const [copyLabel, setCopyLabel] = useState("Copier le réglage");
  const isArrowEditMode =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("editArrows") === "1";

  useEffect(() => {
    window.localStorage.setItem(
      ARROW_STORAGE_KEY,
      JSON.stringify(arrowPoints),
    );
  }, [arrowPoints]);

  const moveArrow = (id: ArrowId, point: ArrowPoint) => {
    setArrowPoints((currentPoints) => ({
      ...currentPoints,
      [id]: {
        x: Math.round(Math.min(1100, Math.max(20, point.x))),
        y: Math.round(Math.min(630, Math.max(20, point.y))),
      },
    }));
  };

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!draggedArrow) return;

    const bounds = event.currentTarget.getBoundingClientRect();
    moveArrow(draggedArrow, {
      x: ((event.clientX - bounds.left) / bounds.width) * 1120,
      y: ((event.clientY - bounds.top) / bounds.height) * 650,
    });
  };

  const handleArrowKeyDown = (
    event: KeyboardEvent<SVGCircleElement>,
    id: ArrowId,
  ) => {
    const movements: Partial<Record<string, ArrowPoint>> = {
      ArrowLeft: { x: -4, y: 0 },
      ArrowRight: { x: 4, y: 0 },
      ArrowUp: { x: 0, y: -4 },
      ArrowDown: { x: 0, y: 4 },
    };
    const movement = movements[event.key];
    if (!movement) return;

    event.preventDefault();
    moveArrow(id, {
      x: arrowPoints[id].x + movement.x,
      y: arrowPoints[id].y + movement.y,
    });
  };

  const copyArrowSettings = async () => {
    await navigator.clipboard.writeText(JSON.stringify(arrowPoints));
    setCopyLabel("Réglage copié");
    window.setTimeout(() => setCopyLabel("Copier le réglage"), 1800);
  };

  return (
    <article className="cadrenza-pierre-showcase">
      <header className="cadrenza-pierre-intro">
        <div className="cadrenza-pierre-identity">
          <span className="cadrenza-pierre-avatar" aria-hidden="true">
            <img src="/robot-blue.png" alt="" />
          </span>
          <span>
            <strong>Pierre</strong>
            <small>Formateur TP CRCD</small>
          </span>
        </div>

        <p>
          Pierre prépare vos supports pédagogiques, anime les journées de
          formation et accompagne les élèves tout au long du cours.
        </p>
      </header>

      <div className="cadrenza-pierre-stage">
        {isArrowEditMode && (
          <div className="cadrenza-arrow-editor" role="status">
            <span>Glisse les points bleus</span>
            <button type="button" onClick={copyArrowSettings}>
              {copyLabel}
            </button>
            <button
              type="button"
              onClick={() => setArrowPoints(defaultArrowPoints)}
            >
              Réinitialiser
            </button>
          </div>
        )}

        <div className="cadrenza-pierre-visual">
          <figure
            className="cadrenza-classroom-monitor"
            aria-label="Écran de présentation de Pierre"
          >
            <span
              className="cadrenza-classroom-monitor__camera"
              aria-hidden="true"
            />
            <span className="cadrenza-classroom-monitor__display">
              <img
                src="/cadrenza-chapter-slide.png"
                alt="Diapo du chapitre 1 sur la communication professionnelle"
              />
            </span>
          </figure>
          <img
            className="cadrenza-pierre-foreground"
            src="/pierre-classe-ia.png"
            alt="Pierre, professeur IA, présente un cours devant trois postes élèves"
          />
        </div>

        <svg
          className={`cadrenza-pierre-connectors ${
            isArrowEditMode ? "cadrenza-pierre-connectors--editable" : ""
          }`}
          viewBox="0 0 1120 650"
          role={isArrowEditMode ? "group" : "presentation"}
          aria-label={
            isArrowEditMode
              ? "Points de réglage des flèches de Pierre"
              : undefined
          }
          aria-hidden={!isArrowEditMode}
          onPointerMove={handlePointerMove}
          onPointerUp={() => setDraggedArrow(null)}
          onPointerCancel={() => setDraggedArrow(null)}
          onPointerLeave={() => setDraggedArrow(null)}
        >
          <defs>
            <marker
              id="cadrenza-arrow"
              markerWidth="8"
              markerHeight="8"
              refX="6.5"
              refY="4"
              orient="auto"
            >
              <path d="M0 0L8 4L0 8Z" />
            </marker>
          </defs>
          <path
            d={`M236 154C315 154 ${arrowPoints.slides.x - 90} ${
              arrowPoints.slides.y - 26
            } ${arrowPoints.slides.x} ${arrowPoints.slides.y}`}
          />
          <path
            d={`M236 484C360 484 ${arrowPoints.training.x - 202} ${
              arrowPoints.training.y + 90
            } ${arrowPoints.training.x} ${arrowPoints.training.y}`}
          />
          <path
            d={`M884 172C835 172 ${arrowPoints.students.x + 47} ${
              arrowPoints.students.y + 10
            } ${arrowPoints.students.x} ${arrowPoints.students.y}`}
          />
          {(Object.keys(arrowPoints) as ArrowId[]).map((id) => (
            <circle
              key={id}
              className={
                isArrowEditMode ? "cadrenza-pierre-arrow-handle" : undefined
              }
              cx={arrowPoints[id].x}
              cy={arrowPoints[id].y}
              r={isArrowEditMode ? 10 : 5}
              role={isArrowEditMode ? "slider" : undefined}
              aria-label={
                isArrowEditMode ? `Déplacer la flèche ${id}` : undefined
              }
              aria-valuetext={
                isArrowEditMode
                  ? `${arrowPoints[id].x}, ${arrowPoints[id].y}`
                  : undefined
              }
              tabIndex={isArrowEditMode ? 0 : undefined}
              onPointerDown={(event) => {
                event.currentTarget.setPointerCapture(event.pointerId);
                setDraggedArrow(id);
              }}
              onKeyDown={(event) => handleArrowKeyDown(event, id)}
            />
          ))}
        </svg>

        <ul className="cadrenza-pierre-callouts">
          {capabilities.map((capability) => (
            <li
              className={`cadrenza-pierre-callout ${capability.className}`}
              key={capability.text}
            >
              <span aria-hidden="true">{capability.index}</span>
              <p>{capability.text}</p>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
};
