// [review:need-review] #78
// summary: decorative sparkline of a trend row - one path per run of days with a value, so a missing day is a gap, drawn in the row's color

import { sparklineSegments, type SparklinePoint, type TrendPoint } from '@/lib/trends';

const VIEW_WIDTH = 120;
const VIEW_HEIGHT = 32;
const STROKE_WIDTH_PX = 2;
const COORDINATE_DECIMALS = 1;

interface TrendSparklineProps {
  points: TrendPoint[];
  color: string;
}

/** `M x y L x y ...`; a lone day is `h0`, which a round cap turns into a dot. */
function pathData(segment: SparklinePoint[]): string {
  const [first, ...rest] = segment;
  const start = `M${first.x.toFixed(COORDINATE_DECIMALS)} ${first.y.toFixed(COORDINATE_DECIMALS)}`;
  if (rest.length === 0) return `${start} h0`;
  return `${start} ${rest
    .map((point) => `L${point.x.toFixed(COORDINATE_DECIMALS)} ${point.y.toFixed(COORDINATE_DECIMALS)}`)
    .join(' ')}`;
}

/**
 * Hidden from assistive technology on purpose: the row's text already says the
 * average and the change, and a 30-point line has nothing more to read out.
 */
export function TrendSparkline({ points, color }: TrendSparklineProps) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      preserveAspectRatio="none"
      overflow="visible"
      className="h-8 w-16 shrink-0 sm:w-40"
    >
      {sparklineSegments(points, VIEW_WIDTH, VIEW_HEIGHT).map((segment) => (
        <path
          key={segment[0].x}
          d={pathData(segment)}
          fill="none"
          stroke={color}
          strokeWidth={STROKE_WIDTH_PX}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}
