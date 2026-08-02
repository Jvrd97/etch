'use client';
// [review:need-review] PHASE-01/84-voice-day-input
// summary: mobile day-summary screen — text + date into useDailySummary, the plan rendered by the shared DayPlanPreview (the cards moved there when the voice sheet on /m/today became their second reader), one apply button

import { useRouter } from 'next/navigation';
import { Sparkles } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import DayPlanPreview, {
  EMPTY_PLAN_MESSAGE,
  planHasWrites,
  planIsEmpty,
} from '@/components/mobile/DayPlanPreview';
import { useDailySummary } from '@/hooks/useDailySummary';
import { MOBILE_PATH_PREFIX } from '@/lib/routes';
import { TAP_TARGET_PX, entryInputClass } from '@/lib/ui-constants';

const PRIMARY_BUTTON_CLASS =
  'w-full inline-flex items-center justify-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-transform duration-200 active:scale-95 disabled:opacity-40 disabled:active:scale-100';

const SECONDARY_BUTTON_CLASS =
  'w-full inline-flex items-center justify-center px-5 py-3 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-transform duration-200 active:scale-95';

export default function MobileDailySummaryPage() {
  const router = useRouter();
  const day = useDailySummary({
    onApplied: () => router.push(`${MOBILE_PATH_PREFIX}/entries`),
  });
  const generate = () => void day.generate();

  return (
    <div className="space-y-4 animate-fade-rise">
      <p className="text-sm text-text-secondary">
        Расскажите, как прошёл день — получите план записей и запишите выбранное одним
        нажатием.
      </p>

      <input
        type="date"
        value={day.entryDate}
        onChange={(e) => day.setEntryDate(e.target.value)}
        aria-label="Дата дня"
        style={{ minHeight: TAP_TARGET_PX }}
        className={entryInputClass}
      />

      <textarea
        value={day.transcript}
        onChange={(e) => day.setTranscript(e.target.value)}
        rows={6}
        aria-label="Как прошёл день"
        placeholder="Например: отжался 30 раз, пробежал 5 километров"
        className={`${entryInputClass} resize-y`}
      />

      <button
        type="button"
        onClick={generate}
        disabled={!day.canGenerate}
        style={{ minHeight: TAP_TARGET_PX }}
        className={PRIMARY_BUTTON_CLASS}
      >
        <Sparkles className="w-4 h-4" strokeWidth={2} />
        Разобрать день
      </button>

      {day.draft.status === 'loading' && <LoadingSpinner size="lg" />}

      {day.draft.status === 'error' && (
        <div className="space-y-3">
          <ErrorAlert message={day.draft.message} />
          <button
            type="button"
            onClick={generate}
            style={{ minHeight: TAP_TARGET_PX }}
            className={SECONDARY_BUTTON_CLASS}
          >
            Retry
          </button>
        </div>
      )}

      {day.draft.status === 'done' &&
        (planIsEmpty(day) ? (
          <p className="text-sm text-text-secondary">{EMPTY_PLAN_MESSAGE}</p>
        ) : (
          <div className="space-y-3">
            <DayPlanPreview day={day} />

            {day.applyState.status === 'error' && (
              <ErrorAlert message={day.applyState.message} />
            )}

            {planHasWrites(day) && (
              <button
                type="button"
                onClick={() => void day.apply()}
                disabled={day.applyState.status === 'applying' || !day.canApply}
                style={{ minHeight: TAP_TARGET_PX }}
                className={PRIMARY_BUTTON_CLASS}
              >
                {day.applyState.status === 'applying'
                  ? 'Записываем…'
                  : `Записать выбранное (${day.enabledCount})`}
              </button>
            )}
          </div>
        ))}
    </div>
  );
}
