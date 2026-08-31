// [review:need-review] PHASE-03/134
// summary: countable Russian in one place — the three forms a number picks between; `streakLabel` and the role screen both ask here instead of each carrying the same modulo arithmetic

/**
 * `count` with the right of three Russian forms.
 *
 * The arithmetic is short and easy to write from memory, which is exactly why
 * it should exist once: the teens are the case everyone forgets (11 дней, not
 * 11 день), and a second copy is a second chance to forget them.
 *
 * @param one form for 1, 21, 31 — «день», «акт»
 * @param few form for 2-4, 22-24 — «дня», «акта»
 * @param many form for 0, 5-20 — «дней», «актов»
 */
export function countable(count: number, one: string, few: string, many: string): string {
  const lastTwo = Math.abs(count) % 100;
  const last = count % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return `${count} ${many}`;
  if (last === 1) return `${count} ${one}`;
  if (last >= 2 && last <= 4) return `${count} ${few}`;
  return `${count} ${many}`;
}
