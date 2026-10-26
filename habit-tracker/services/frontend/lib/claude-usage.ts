// [review:need-review] PHASE-03/220
// summary: the words and numbers of the Claude Code block on the day screen — compact token counts (a day holds millions, mostly cache) and the caption that says a session counts whole on the day it began

const THOUSAND = 1000;
const UNITS = ['', ' тыс', ' млн', ' млрд'] as const;

function oneDecimal(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return String(rounded).replace('.', ',');
}

/** «950», «12,4 тыс», «1,3 млн»: one decimal, and a count that rounds up to 1000 moves to the next unit. */
export function formatTokens(count: number): string {
  let unit = 0;
  let value = count;
  while (unit < UNITS.length - 1 && (unit === 0 ? value >= THOUSAND : Math.round(value * 10) / 10 >= THOUSAND)) {
    value /= THOUSAND;
    unit += 1;
  }
  return unit === 0 ? String(count) : `${oneDecimal(value)}${UNITS[unit]}`;
}

const WHOLE_ON_START_DAY = 'Сессия считается целиком на день начала.';

/** What makes «tokens for the day» not a surprise: a session across the boundary is not split. */
export function boundaryCaption(pastBoundary: number): string {
  if (pastBoundary === 0) return WHOLE_ON_START_DAY;
  return `Сессий, продолжившихся после границы суток: ${pastBoundary}. ${WHOLE_ON_START_DAY}`;
}
