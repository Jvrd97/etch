'use client';
// [review:need-review] PHASE-03/92
// summary: the training of a day on screen — what was planned, what was done, the minimum with its own tick beside the training's, the open complaint shown next to the suggestion rather than behind a second screen, the gates that shaped the offer, and the run of skipped days said out loud

import type { TrainingDay, TrainingState } from '@/lib/api';

export const TRAINING_TITLE = 'Тренировка';
export const TRAINING_EMPTY = 'На этот день ничего не записано';
export const PLANNED_TITLE = 'План';
export const DONE_TITLE = 'Факт';
export const MINIMUM_TITLE = 'Минимум';
export const MINIMUM_HAS_ITEM = 'отмечается своим пунктом плана';
export const MINIMUM_NO_ITEM = 'нет отдельного пункта — отметить его нечем';
export const SKIPPED_LABEL = 'Пропуск';
export const OUTDOOR_LABEL = 'Улица';
export const COMPLAINTS_TITLE = 'Открытые жалобы';
export const SUGGESTION_TITLE = 'Предложение на сегодня';
export const EXCLUDED_TITLE = 'Сегодня не предлагается';
export const SKIPPED_DAYS_TITLE = 'Пропусков подряд';
export const STATE_AS_OF = 'Состояние пересчитано на';
export const RECORDS_TITLE = 'Личные рекорды';

export interface DayTrainingProps {
  /** The training of the day being looked at; null when nothing is recorded. */
  training: TrainingDay | null;
  /** The derived state, its gated suggestion and the open complaints. */
  state: TrainingState | null;
  compact?: boolean;
}

/**
 * The training of one day, and the state of the body it was chosen against.
 *
 * Two things this block insists on. **The minimum is its own line.** 29 August
 * proved that a minimum declared inside the training block, with no tick of its
 * own, is not done; 30 August proved that giving it a tick is not enough
 * either. So the block says outright whether the minimum has a plan item to be
 * ticked on — that is the thing worth seeing, not the wording of the minimum.
 *
 * **The records stand here too.** «9/10/5/3, 10 августа, цель 4x8 RIR 1-2» is
 * the record and the diagnosis at once, and it belongs beside the offer it is
 * the reason for rather than on a screen nobody opens.
 *
 * **The open complaint stands next to the offer.** A suggestion that quietly
 * lacks pull-ups reads as an arbitrary list; a suggestion with «плечо open с
 * 10.08» beside it reads as a decision, and a person can disagree with a
 * decision.
 */
export default function DayTraining({
  training,
  state,
  compact = false,
}: DayTrainingProps) {
  const suggestion = state?.suggestion ?? null;

  return (
    <section className="bg-card border border-white/5 rounded-3xl p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold text-text-primary">
          {TRAINING_TITLE}
        </h2>
        {training?.skipped && (
          <span className="px-3 py-1 rounded-2xl bg-surface text-sm text-warning">
            {SKIPPED_LABEL}
          </span>
        )}
      </div>

      {training === null ? (
        <p className="mt-4 text-text-secondary">{TRAINING_EMPTY}</p>
      ) : (
        <div className={`mt-4 space-y-3 ${compact ? 'text-sm' : ''}`}>
          {training.planned_md && (
            <Line title={PLANNED_TITLE} body={training.planned_md} />
          )}
          {training.done_md && (
            <Line title={DONE_TITLE} body={training.done_md} />
          )}
          {training.minimum_md && (
            <div>
              <p className="text-sm text-text-secondary">{MINIMUM_TITLE}</p>
              <p className="text-text-primary">{training.minimum_md}</p>
              <p
                className={`text-xs ${
                  training.minimum_item_id === null
                    ? 'text-warning'
                    : 'text-text-disabled'
                }`}
              >
                {training.minimum_item_id === null
                  ? MINIMUM_NO_ITEM
                  : MINIMUM_HAS_ITEM}
              </p>
            </div>
          )}
          {training.outdoor_done !== null && (
            <p className="text-text-secondary">
              {OUTDOOR_LABEL}: {training.outdoor_done ? '✓' : '✕'}
            </p>
          )}
        </div>
      )}

      {state !== null && (
        <div className="mt-5 pt-5 border-t border-white/5 space-y-4">
          <p className="text-sm text-text-secondary">
            {SKIPPED_DAYS_TITLE}: {state.skipped_days}
          </p>

          {state.open_complaints.length > 0 && (
            <div>
              <p className="text-sm text-text-secondary">{COMPLAINTS_TITLE}</p>
              <ul className="mt-2 space-y-1">
                {state.open_complaints.map((complaint) => (
                  <li key={complaint.id} className="text-text-primary">
                    {complaint.area} — с {complaint.opened_on}
                    {complaint.severity ? `, ${complaint.severity}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {suggestion !== null && (
            <div>
              <p className="text-sm text-text-secondary">
                {SUGGESTION_TITLE} · {suggestion.rir}
              </p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {suggestion.exercises.map((exercise) => (
                  <li
                    key={exercise}
                    className="px-3 py-1 rounded-2xl bg-surface text-sm text-text-primary"
                  >
                    {exercise}
                  </li>
                ))}
              </ul>

              {suggestion.excluded.length > 0 && (
                <div className="mt-4">
                  <p className="text-sm text-text-secondary">
                    {EXCLUDED_TITLE}
                  </p>
                  <ul className="mt-2 space-y-1">
                    {suggestion.excluded.map((one) => (
                      <li key={one.exercise} className="text-sm">
                        <span className="text-text-primary">
                          {one.exercise}
                        </span>
                        <span className="text-text-secondary">
                          {' '}
                          — {one.reason}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {state.records.length > 0 && (
            <div>
              <p className="text-sm text-text-secondary">{RECORDS_TITLE}</p>
              <ul className="mt-2 space-y-1">
                {state.records.map((record) => (
                  <li key={record.id} className="text-sm">
                    <span className="text-text-primary">
                      {record.exercise}
                      {record.variant ? ` (${record.variant})` : ''}
                      {record.sets ? `: ${record.sets}` : ''}
                    </span>
                    <span className="text-text-secondary">
                      {' '}
                      — {record.achieved_on}
                      {record.target ? `, цель: ${record.target}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-xs text-text-disabled">
            {STATE_AS_OF} {state.as_of}
          </p>
        </div>
      )}
    </section>
  );
}

function Line({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <p className="text-sm text-text-secondary">{title}</p>
      <p className="text-text-primary">{body}</p>
    </div>
  );
}
