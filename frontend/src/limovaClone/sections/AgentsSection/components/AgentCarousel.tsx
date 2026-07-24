import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import "./AgentCarousel.css";

type ArrowId = "slides" | "training" | "students";
type ArrowPoint = { x: number; y: number };
type ArrowPoints = Record<ArrowId, ArrowPoint>;
type CalloutPositions = Record<ArrowId, ArrowPoint>;
type ArrowHandleKind = "curve" | "tip";
type DraggedCallout = {
  id: ArrowId;
  offsetX: number;
  offsetY: number;
};

const ARROW_STORAGE_KEY = "cadrenza-pierre-arrow-points";
const CURVE_STORAGE_KEY = "cadrenza-pierre-arrow-curves";
const CALLOUT_STORAGE_KEY = "cadrenza-pierre-callout-positions";
const CALLOUT_WIDTH = 236;
const CALLOUT_HEIGHT = 64;
const defaultArrowPoints: ArrowPoints = {
  slides: { x: 424, y: 228 },
  training: { x: 680, y: 224 },
  students: { x: 756, y: 148 },
};
const defaultCurvePoints: ArrowPoints = {
  slides: { x: 330, y: 154 },
  training: { x: 450, y: 420 },
  students: { x: 830, y: 165 },
};
const defaultCalloutPositions: CalloutPositions = {
  slides: { x: 0, y: 122 },
  training: { x: 0, y: 498 },
  students: { x: 884, y: 140 },
};

const capabilities = [
  {
    className: "cadrenza-pierre-callout--slides",
    id: "slides" as const,
    index: "01",
    text: "Prépare les diapositives du module",
  },
  {
    className: "cadrenza-pierre-callout--training",
    id: "training" as const,
    index: "02",
    text: "Anime les journées de formation",
  },
  {
    className: "cadrenza-pierre-callout--students",
    id: "students" as const,
    index: "03",
    text: "Interagit avec les élèves en direct",
  },
];

export const AgentCarousel = () => {
  const stageRef = useRef<HTMLDivElement>(null);
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
  const [calloutPositions, setCalloutPositions] = useState<CalloutPositions>(
    () => {
      if (typeof window === "undefined") return defaultCalloutPositions;

      try {
        const savedPositions = window.localStorage.getItem(CALLOUT_STORAGE_KEY);
        return savedPositions
          ? ({
              ...defaultCalloutPositions,
              ...JSON.parse(savedPositions),
            } as CalloutPositions)
          : defaultCalloutPositions;
      } catch {
        return defaultCalloutPositions;
      }
    },
  );
  const [curvePoints, setCurvePoints] = useState<ArrowPoints>(() => {
    if (typeof window === "undefined") return defaultCurvePoints;

    try {
      const savedPoints = window.localStorage.getItem(CURVE_STORAGE_KEY);
      return savedPoints
        ? ({ ...defaultCurvePoints, ...JSON.parse(savedPoints) } as ArrowPoints)
        : defaultCurvePoints;
    } catch {
      return defaultCurvePoints;
    }
  });
  const draggedArrowRef = useRef<{
    id: ArrowId;
    kind: ArrowHandleKind;
  } | null>(null);
  const [draggedCallout, setDraggedCallout] =
    useState<DraggedCallout | null>(null);
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

  useEffect(() => {
    window.localStorage.setItem(
      CALLOUT_STORAGE_KEY,
      JSON.stringify(calloutPositions),
    );
  }, [calloutPositions]);

  useEffect(() => {
    window.localStorage.setItem(CURVE_STORAGE_KEY, JSON.stringify(curvePoints));
  }, [curvePoints]);

  const moveArrowHandle = (
    id: ArrowId,
    kind: ArrowHandleKind,
    point: ArrowPoint,
  ) => {
    const setPoints = kind === "tip" ? setArrowPoints : setCurvePoints;
    setPoints((currentPoints) => ({
      ...currentPoints,
      [id]: {
        x: Math.round(Math.min(1100, Math.max(20, point.x))),
        y: Math.round(Math.min(630, Math.max(20, point.y))),
      },
    }));
  };

  const handleArrowPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const draggedArrow = draggedArrowRef.current;
    if (!draggedArrow) return;

    const bounds = event.currentTarget.getBoundingClientRect();
    moveArrowHandle(
      draggedArrow.id,
      draggedArrow.kind,
      {
        x: ((event.clientX - bounds.left) / bounds.width) * 1120,
        y: ((event.clientY - bounds.top) / bounds.height) * 650,
      },
    );
  };

  const handleArrowKeyDown = (
    event: KeyboardEvent<SVGCircleElement>,
    id: ArrowId,
    kind: ArrowHandleKind,
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
    const currentPoint = kind === "tip" ? arrowPoints[id] : curvePoints[id];
    moveArrowHandle(id, kind, {
      x: currentPoint.x + movement.x,
      y: currentPoint.y + movement.y,
    });
  };

  const moveCallout = (event: PointerEvent<HTMLLIElement>) => {
    if (!draggedCallout || !stageRef.current) return;

    const bounds = stageRef.current.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * 1120;
    const y = ((event.clientY - bounds.top) / bounds.height) * 650;
    setCalloutPositions((currentPositions) => ({
      ...currentPositions,
      [draggedCallout.id]: {
        x: Math.round(
          Math.min(
            1120 - CALLOUT_WIDTH,
            Math.max(0, x - draggedCallout.offsetX),
          ),
        ),
        y: Math.round(
          Math.min(
            650 - CALLOUT_HEIGHT,
            Math.max(0, y - draggedCallout.offsetY),
          ),
        ),
      },
    }));
  };

  const getCalloutAnchor = (id: ArrowId) => {
    const position = calloutPositions[id];
    const target = arrowPoints[id];
    const center = {
      x: position.x + CALLOUT_WIDTH / 2,
      y: position.y + CALLOUT_HEIGHT / 2,
    };
    const deltaX = target.x - center.x;
    const deltaY = target.y - center.y;

    if (Math.abs(deltaX) >= Math.abs(deltaY)) {
      return {
        x: deltaX >= 0 ? position.x + CALLOUT_WIDTH : position.x,
        y: center.y,
      };
    }

    return {
      x: center.x,
      y: deltaY >= 0 ? position.y + CALLOUT_HEIGHT : position.y,
    };
  };

  const buildConnectorPath = (id: ArrowId) => {
    const start = getCalloutAnchor(id);
    const target = arrowPoints[id];
    const curve = curvePoints[id];

    return `M${start.x} ${start.y}Q${curve.x} ${curve.y} ${target.x} ${target.y}`;
  };

  const copyArrowSettings = async () => {
    await navigator.clipboard.writeText(
      JSON.stringify({
        arrows: arrowPoints,
        blocks: calloutPositions,
        curves: curvePoints,
      }),
    );
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

      <div
        className="cadrenza-pierre-stage"
        ref={stageRef}
        onPointerMove={handleArrowPointerMove}
        onPointerUp={() => {
          draggedArrowRef.current = null;
        }}
        onPointerCancel={() => {
          draggedArrowRef.current = null;
        }}
        onPointerLeave={() => {
          draggedArrowRef.current = null;
        }}
      >
        {isArrowEditMode && (
          <div className="cadrenza-arrow-editor" role="status">
            <span>Plein = pointe · creux = courbe · texte = bloc</span>
            <button type="button" onClick={copyArrowSettings}>
              {copyLabel}
            </button>
            <button
              type="button"
              onClick={() => {
                setArrowPoints(defaultArrowPoints);
                setCalloutPositions(defaultCalloutPositions);
                setCurvePoints(defaultCurvePoints);
              }}
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
        >
          <defs>
            <marker
              id="cadrenza-arrow"
              markerWidth="8"
              markerHeight="8"
              refX="8"
              refY="4"
              orient="auto"
            >
              <path d="M0 0L8 4L0 8Z" />
            </marker>
          </defs>
          {isArrowEditMode &&
            (Object.keys(arrowPoints) as ArrowId[]).map((id) => {
              const start = getCalloutAnchor(id);
              return (
                <polyline
                  key={`guide-${id}`}
                  className="cadrenza-pierre-curve-guide"
                  points={`${start.x},${start.y} ${curvePoints[id].x},${
                    curvePoints[id].y
                  } ${arrowPoints[id].x},${arrowPoints[id].y}`}
                />
              );
            })}
          <path d={buildConnectorPath("slides")} />
          <path d={buildConnectorPath("training")} />
          <path d={buildConnectorPath("students")} />
          {isArrowEditMode &&
            (Object.keys(curvePoints) as ArrowId[]).map((id) => (
              <circle
                key={`curve-${id}`}
                className="cadrenza-pierre-curve-handle"
                cx={curvePoints[id].x}
                cy={curvePoints[id].y}
                r="8"
                role="slider"
                aria-label={`Régler la courbe de la flèche ${id}`}
                aria-valuetext={`${curvePoints[id].x}, ${curvePoints[id].y}`}
                tabIndex={0}
                onPointerDown={(event) => {
                  event.preventDefault();
                  draggedArrowRef.current = { id, kind: "curve" };
                }}
                onKeyDown={(event) =>
                  handleArrowKeyDown(event, id, "curve")
                }
              />
            ))}
          {isArrowEditMode &&
            (Object.keys(arrowPoints) as ArrowId[]).map((id) => (
              <circle
                key={id}
                className="cadrenza-pierre-arrow-handle"
                cx={arrowPoints[id].x}
                cy={arrowPoints[id].y}
                r="10"
                role="slider"
                aria-label={`Déplacer la pointe de la flèche ${id}`}
                aria-valuetext={`${arrowPoints[id].x}, ${arrowPoints[id].y}`}
                tabIndex={0}
                onPointerDown={(event) => {
                  event.preventDefault();
                  draggedArrowRef.current = { id, kind: "tip" };
                }}
                onKeyDown={(event) => handleArrowKeyDown(event, id, "tip")}
              />
            ))}
        </svg>

        <ul className="cadrenza-pierre-callouts">
          {capabilities.map((capability) => (
            <li
              className={`cadrenza-pierre-callout ${capability.className} ${
                isArrowEditMode ? "cadrenza-pierre-callout--editable" : ""
              }`}
              key={capability.text}
              style={{
                left: `${(calloutPositions[capability.id].x / 1120) * 100}%`,
                top: `${(calloutPositions[capability.id].y / 650) * 100}%`,
              }}
              tabIndex={isArrowEditMode ? 0 : undefined}
              aria-label={
                isArrowEditMode
                  ? `Déplacer le bloc ${capability.index} : ${capability.text}`
                  : undefined
              }
              onPointerDown={(event) => {
                if (!isArrowEditMode || !stageRef.current) return;

                const bounds = stageRef.current.getBoundingClientRect();
                const pointerX =
                  ((event.clientX - bounds.left) / bounds.width) * 1120;
                const pointerY =
                  ((event.clientY - bounds.top) / bounds.height) * 650;
                event.currentTarget.setPointerCapture(event.pointerId);
                setDraggedCallout({
                  id: capability.id,
                  offsetX:
                    pointerX - calloutPositions[capability.id].x,
                  offsetY:
                    pointerY - calloutPositions[capability.id].y,
                });
              }}
              onPointerMove={moveCallout}
              onPointerUp={() => setDraggedCallout(null)}
              onPointerCancel={() => setDraggedCallout(null)}
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
