// [review:need-review] PHASE-01/73-dashboard-hero-today-ring
// summary: deterministic tip-of-the-day rules — one pure function picking between an untouched day, a run about to break, a habit still missing, a stale journal, and a day already complete

/** A category the dashboard expects an entry for today. */
export interface TrackedCategory {
  id: number;
  name: string;
}

/** Everything the rules look at. No clock, no network — the caller supplies both. */
export interface DailyTipInput {
  /** Categories on the Today screen, in the order they are shown there. */
  trackedToday: TrackedCategory[];
  /** Category ids that already have an entry dated today. */
  loggedCategoryIds: number[];
  /** Whether yesterday holds any entry at all — what a run would break from. */
  loggedYesterday: boolean;
  /** Local hour of the day, 0..23. */
  hour: number;
  /** Days since the newest journal note; `null` when there is none at all. */
  daysSinceJournal: number | null;
}

/**
 * Which rule fired. Screens key styling off this rather than off the text, so
 * rewording a tip never silently changes how it is drawn.
 */
export type DailyTipKind =
  | 'nothing-logged'
  | 'streak-at-risk'
  | 'category-missing'
  | 'journal-stale'
  | 'all-logged';

export interface DailyTip {
  kind: DailyTipKind;
  text: string;
}

/**
 * From this hour on, an empty day is worth warning about. Earlier than that the
 * day is still ahead of the user, and "your run is about to break" at breakfast
 * is noise that teaches people to ignore the line.
 */
const LATE_DAY_HOUR = 18;

/** A journal note older than this is worth a nudge; yesterday's is not. */
const STALE_JOURNAL_DAYS = 3;

function journalStaleText(daysSinceJournal: number | null): string {
  if (daysSinceJournal === null) {
    return 'No journal note yet — write a line about today.';
  }
  return `No journal note for ${daysSinceJournal} days — write a line about today.`;
}

function isJournalStale(daysSinceJournal: number | null): boolean {
  return daysSinceJournal === null || daysSinceJournal >= STALE_JOURNAL_DAYS;
}

/**
 * The one line the hero card shows under today's ring.
 *
 * Rules, not a model: the tip is on screen on every load, so it has to be
 * free, instant and the same for the same day — and a wrong-but-fluent
 * sentence about the user's own habits costs more trust than a plain one.
 * The generated commentary lives next to it in the AI summary block instead.
 *
 * Priority is by how much the day still needs from the user. An untouched day
 * outranks everything, including a run about to break — except that late in the
 * day the run is the sharper way to say the same thing. A named missing habit
 * outranks the journal, because it is the smaller ask of the two.
 */
export function pickDailyTip(input: DailyTipInput): DailyTip {
  const { trackedToday, loggedCategoryIds, loggedYesterday, hour, daysSinceJournal } = input;

  if (loggedCategoryIds.length === 0) {
    if (loggedYesterday && hour >= LATE_DAY_HOUR) {
      return {
        kind: 'streak-at-risk',
        text: 'Your run ends at midnight — one entry keeps it alive.',
      };
    }
    return {
      kind: 'nothing-logged',
      text: 'Nothing logged today yet — one entry is enough to start.',
    };
  }

  const logged = new Set(loggedCategoryIds);
  const missing = trackedToday.find((category) => !logged.has(category.id));
  if (missing !== undefined) {
    return {
      kind: 'category-missing',
      text: `You haven't logged ${missing.name} today.`,
    };
  }

  if (isJournalStale(daysSinceJournal)) {
    return { kind: 'journal-stale', text: journalStaleText(daysSinceJournal) };
  }

  return { kind: 'all-logged', text: 'Everything you track is logged today. Nice.' };
}
