'use client';
// [review:need-review] PHASE-03/93
// summary: the goal board both shells draw — levels 0-5 with the `⚠ подтверди` lines kept apart from the prose, ten milestones whose «Открывается чем» is a row of chips that read differently once the milestone they wait on is closed, and the five goals of the current quarter

import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import { useGoals } from '@/hooks/useGoals';
import type { Milestone, MilestoneStatus } from '@/lib/api';

/** What each status is called on screen; the codes stay in the database. */
const STATUS_LABEL: Record<MilestoneStatus, string> = {
  open: 'открыт',
  'in-progress': 'в работе',
  done: 'закрыт',
  dropped: 'снят',
};

/** Shown where a milestone waits on one that is not closed yet. */
export const WAITING_LABEL = 'ждёт';

/** Shown where the milestone it waits on is already closed. */
export const OPENED_LABEL = 'открыт';

export const EMPTY_GOALS_TEXT =
  'Целей пока нет: импортируйте goal.md — уровни, милстоны и квартал живут в нём.';

/**
 * `**Небольшой дом**` as the words a reader sees.
 *
 * The columns are markdown by contract — `goal.md` writes them that way and the
 * import keeps them as written — and only `plan_item` has a `text_plain` twin.
 * Bold is the only markup these three fields ever carry, so this is a strip
 * rather than a renderer: turning the board into a markdown surface would let
 * the file decide what the screen may draw.
 */
function plain(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, '$1');
}

/** The status a click on a milestone moves it to. */
function nextStatus(status: MilestoneStatus): MilestoneStatus {
  return status === 'done' ? 'open' : 'done';
}

interface DependencyChipsProps {
  milestone: Milestone;
  statuses: Map<string, MilestoneStatus>;
}

/**
 * «Открывается чем», one chip per milestone waited on.
 *
 * The chip changes wording and colour the moment the milestone it names is
 * closed — that is the acceptance case: M10 shows M9 and M8, and closing M9
 * has to be visible on M10 rather than only on M9.
 */
function DependencyChips({ milestone, statuses }: DependencyChipsProps) {
  if (milestone.depends_on.length === 0) {
    return <span className="text-xs text-text-secondary">ничем не заблокирован</span>;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {milestone.depends_on.map((code) => {
        const closed = statuses.get(code) === 'done';
        return (
          <span
            key={code}
            className={`text-xs px-2 py-1 rounded-xl border ${
              closed
                ? 'border-success/40 text-success'
                : 'border-white/10 text-text-secondary'
            }`}
          >
            {code} · {closed ? OPENED_LABEL : WAITING_LABEL}
          </span>
        );
      })}
    </div>
  );
}

export interface GoalsBoardProps {
  /** Mobile trims the type scale; the structure is identical. */
  compact?: boolean;
}

/**
 * Levels, milestones and the quarter, in the order `goal.md` puts them.
 *
 * One component for both shells because the board is a reading surface: the
 * only thing a person does here is close a milestone, and that is one button.
 * A second copy of this markup would be a second place for the graph to go
 * stale.
 */
export default function GoalsBoard({ compact = false }: GoalsBoardProps) {
  const { payload, loading, error, saving, markMilestone } = useGoals();

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorAlert message={error} />;
  if (!payload) return <p className="text-text-secondary">{EMPTY_GOALS_TEXT}</p>;

  const statuses = new Map(payload.milestones.map((one) => [one.code, one.status]));
  const card = `bg-card border border-white/5 rounded-3xl ${compact ? 'p-4' : 'p-6'}`;

  return (
    <div className={compact ? 'space-y-4' : 'space-y-6'}>
      <section className={card}>
        <h2 className="text-text-primary text-lg mb-4">Уровни</h2>
        <div className="space-y-4">
          {payload.levels.map((level) => (
            <article key={level.level}>
              <h3 className="text-text-primary">
                Уровень {level.level} — {level.title}
              </h3>
              {level.body_md && (
                <p className="text-sm text-text-secondary whitespace-pre-line mt-1">
                  {plain(level.body_md)}
                </p>
              )}
              {level.open_questions.map((question) => (
                <p key={question} className="text-xs text-warning mt-1">
                  {question}
                </p>
              ))}
            </article>
          ))}
        </div>
      </section>

      <section className={card}>
        <h2 className="text-text-primary text-lg mb-4">Милстоны</h2>
        <ul className="space-y-3">
          {payload.milestones.map((one) => (
            <li key={one.code} className="border-t border-white/5 pt-3 first:border-0 first:pt-0">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-text-primary">
                    {one.code} · {plain(one.title)}
                  </p>
                  {one.done_criterion && (
                    <p className="text-xs text-text-secondary">
                      Сделано :: {plain(one.done_criterion)}
                    </p>
                  )}
                  {one.when_text && (
                    <p className="text-xs text-text-secondary">
                      Когда :: {plain(one.when_text)}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => markMilestone(one.code, nextStatus(one.status))}
                  disabled={saving.has(one.code)}
                  className="text-xs px-3 py-1 rounded-xl border border-white/10 text-text-secondary disabled:opacity-50"
                >
                  {STATUS_LABEL[one.status]}
                  {one.done_on ? ` · ${one.done_on}` : ''}
                </button>
              </div>
              <div className="mt-2">
                <DependencyChips milestone={one} statuses={statuses} />
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className={card}>
        <h2 className="text-text-primary text-lg mb-4">Квартал {payload.quarter}</h2>
        <ol className="space-y-2">
          {payload.goals.map((one) => (
            <li key={one.id} className="text-text-primary">
              {one.ord}. {plain(one.text_md)}
              {one.milestone_code && (
                <span className="text-xs text-text-secondary"> — {one.milestone_code}</span>
              )}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
