'use client';
// [review:need-review] PHASE-03/221
// summary: the «Неделя» review screen on both shells — title with the period and an explicit note while the week is unfinished, neighbour-week links, the blocks of the week, and the AI narrative written on request; a week with nothing in it says so and does not offer the narrative

import Link from 'next/link';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import {
  CategoriesBlock,
  DaysBlock,
  HealthBlock,
  RolesBlock,
  StreaksBlock,
  TotalsBlock,
} from '@/components/week-review/WeekReviewSections';
import {
  useWeekReview,
  type NarrativeState,
  type WeekReviewClient,
} from '@/hooks/useWeekReview';
import {
  EMPTY_WEEK_TEXT,
  isEmptyWeek,
  partialNote,
  periodText,
  weekHref,
} from '@/lib/week-review';

export const NARRATIVE_BUTTON = 'Написать итог недели';
export const NARRATIVE_BUTTON_BUSY = 'Пишу итог…';
export const NARRATIVE_CAPTION = 'Текст написан моделью по цифрам выше и не сохраняется.';

export interface WeekReviewScreenProps {
  /** `null` on the bare route, where the server names the running week. */
  iso: string | null;
  compact?: boolean;
  /** Replaces the network client in tests. */
  client?: WeekReviewClient;
}

const LINK = 'inline-flex min-h-11 items-center text-sm font-medium text-lime hover:underline';

function Narrative({
  state,
  onWrite,
  disabled,
}: {
  state: NarrativeState;
  onWrite: () => void;
  disabled: boolean;
}) {
  const busy = state.status === 'loading';
  return (
    <section aria-label="Итог от ИИ" className="space-y-3">
      <h2 className="text-xl font-semibold text-text-primary">Итог от ИИ</h2>
      {state.status === 'ready' && (
        <div className="bg-card border border-white/5 rounded-3xl p-5">
          <p className="whitespace-pre-wrap break-words text-text-primary">{state.text}</p>
          <p className="mt-3 text-xs text-text-disabled">{NARRATIVE_CAPTION}</p>
        </div>
      )}
      {state.status === 'error' && (
        <p role="alert" className="text-sm text-danger">
          {state.message}
        </p>
      )}
      <button
        type="button"
        onClick={onWrite}
        disabled={disabled || busy}
        className="min-h-11 rounded-full bg-lime px-5 text-sm font-semibold text-black disabled:opacity-40"
      >
        {busy ? NARRATIVE_BUTTON_BUSY : state.status === 'ready' ? 'Написать заново' : NARRATIVE_BUTTON}
      </button>
    </section>
  );
}

export default function WeekReviewScreen({ iso, compact = false, client }: WeekReviewScreenProps) {
  const { state, narrative, reload, writeNarrative } = useWeekReview(iso, client);

  if (state.status === 'loading') return <LoadingSpinner size="lg" />;
  if (state.status === 'error') return <ErrorAlert message={state.message} onDismiss={reload} />;

  const { review } = state;
  const { window } = review;
  const note = partialNote(window);
  const empty = isEmptyWeek(review);

  return (
    <div className="space-y-8 animate-fade-rise">
      <header className="space-y-2">
        <h1
          className={`${compact ? 'text-2xl' : 'text-4xl'} font-bold text-text-primary tracking-tight`}
        >
          Неделя {window.iso_code}
          <span className="text-lime">.</span>
        </h1>
        <p className="text-text-secondary">
          {periodText(window)} · сутки с {window.day_start_hour}:00, {window.timezone}
        </p>
        {note !== null && (
          <p
            role="status"
            className="rounded-2xl border border-lime/40 bg-lime/10 px-4 py-3 text-sm text-text-primary"
          >
            {note}
          </p>
        )}
        <nav aria-label="Другие недели" className="flex flex-wrap gap-x-5">
          <Link href={weekHref(window.previous_iso_code)} className={LINK}>
            ← {window.previous_iso_code}
          </Link>
          <Link href={weekHref(window.next_iso_code)} className={LINK}>
            {window.next_iso_code} →
          </Link>
          <Link href={`/week/${window.iso_code}`} className={LINK}>
            Ретро недели
          </Link>
        </nav>
      </header>

      {empty ? (
        <p role="status" className="text-text-secondary">
          {EMPTY_WEEK_TEXT}
        </p>
      ) : (
        <>
          <TotalsBlock review={review} />
          <DaysBlock review={review} />
          <RolesBlock review={review} />
          <CategoriesBlock review={review} />
          <StreaksBlock review={review} />
          <HealthBlock review={review} />
        </>
      )}

      <Narrative state={narrative} onWrite={writeNarrative} disabled={empty} />
    </div>
  );
}
