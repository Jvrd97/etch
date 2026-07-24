// [review:need-review] PHASE-01/43-mobile-dashboard
// summary: shared dashboard progress ring — animated lime arc over a faint track, sizeable so the desktop and mobile shells render the same widget at different diameters

const RING_STROKE = 8;
const DEFAULT_RING_SIZE = 148;

interface ProgressRingProps {
  /** Fraction filled, clamped to 0..1. */
  progress: number;
  /** Outer diameter in px; the stroke stays constant across sizes. */
  size?: number;
}

export default function ProgressRing({ progress, size = DEFAULT_RING_SIZE }: ProgressRingProps) {
  const radius = (size - RING_STROKE) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.min(Math.max(progress, 0), 1));

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="-rotate-90"
      aria-hidden="true"
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="rgba(255,255,255,0.06)"
        strokeWidth={RING_STROKE}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="#B8FF36"
        strokeWidth={RING_STROKE}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        className="animate-ring-draw drop-shadow-[0_0_8px_rgba(184,255,54,0.45)]"
        style={{ '--ring-circumference': circumference } as React.CSSProperties}
      />
    </svg>
  );
}
