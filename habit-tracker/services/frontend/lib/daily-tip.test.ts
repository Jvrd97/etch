// [review:need-review] PHASE-01/73-dashboard-hero-today-ring
// summary: case matrix for the tip-of-the-day rules — all logged, nothing logged, streak at risk, stale journal, and the priority between them

import { describe, expect, it } from 'bun:test';
import { pickDailyTip, type DailyTipInput } from './daily-tip';

const PUSHUPS = { id: 1, name: 'Pushups' };
const WATER = { id: 2, name: 'Water' };
const SLEEP = { id: 3, name: 'Sleep' };

/** A day where everything is in order: both habits logged, journal written today. */
const SETTLED_DAY: DailyTipInput = {
  trackedToday: [PUSHUPS, WATER],
  loggedCategoryIds: [PUSHUPS.id, WATER.id],
  loggedYesterday: true,
  hour: 20,
  daysSinceJournal: 0,
};

describe('pickDailyTip', () => {
  it('confirms the day is complete when everything tracked is logged', () => {
    const tip = pickDailyTip(SETTLED_DAY);

    expect(tip.kind).toBe('all-logged');
    expect(tip.text).toContain('logged');
  });

  it('asks for a first entry when nothing is logged yet', () => {
    const tip = pickDailyTip({
      ...SETTLED_DAY,
      loggedCategoryIds: [],
      loggedYesterday: false,
      hour: 9,
    });

    expect(tip.kind).toBe('nothing-logged');
    expect(tip.text).toContain('Nothing logged');
  });

  it('warns about the run only late in the day, when yesterday was logged', () => {
    const tip = pickDailyTip({ ...SETTLED_DAY, loggedCategoryIds: [], hour: 21 });

    expect(tip.kind).toBe('streak-at-risk');
  });

  it('does not cry streak in the morning — the day is still ahead', () => {
    const tip = pickDailyTip({ ...SETTLED_DAY, loggedCategoryIds: [], hour: 8 });

    expect(tip.kind).toBe('nothing-logged');
  });

  it('names the habit that is still missing today', () => {
    const tip = pickDailyTip({ ...SETTLED_DAY, loggedCategoryIds: [PUSHUPS.id] });

    expect(tip.kind).toBe('category-missing');
    expect(tip.text).toContain('Water');
  });

  it('nudges the journal when the last note is old', () => {
    const tip = pickDailyTip({ ...SETTLED_DAY, daysSinceJournal: 5 });

    expect(tip.kind).toBe('journal-stale');
    expect(tip.text).toContain('5 days');
  });

  it('nudges the journal when there is no note at all', () => {
    const tip = pickDailyTip({ ...SETTLED_DAY, daysSinceJournal: null });

    expect(tip.kind).toBe('journal-stale');
  });

  it('leaves a recent journal note alone', () => {
    const tip = pickDailyTip({ ...SETTLED_DAY, daysSinceJournal: 1 });

    expect(tip.kind).toBe('all-logged');
  });

  it('puts an untouched day ahead of a stale journal', () => {
    const tip = pickDailyTip({
      ...SETTLED_DAY,
      loggedCategoryIds: [],
      hour: 9,
      daysSinceJournal: 9,
    });

    expect(tip.kind).toBe('nothing-logged');
  });

  it('names the first missing habit, so two gaps do not make the tip ambiguous', () => {
    const tip = pickDailyTip({
      ...SETTLED_DAY,
      trackedToday: [PUSHUPS, WATER, SLEEP],
      loggedCategoryIds: [PUSHUPS.id],
    });

    expect(tip.text).toContain('Water');
    expect(tip.text).not.toContain('Sleep');
  });

  it('stays sensible when nothing is tracked for today at all', () => {
    const tip = pickDailyTip({ ...SETTLED_DAY, trackedToday: [], loggedCategoryIds: [] });

    expect(tip.kind).toBe('streak-at-risk');
    expect(tip.text.length).toBeGreaterThan(0);
  });
});
