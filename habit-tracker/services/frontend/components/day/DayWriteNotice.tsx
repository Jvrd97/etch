// [review:need-review] #311
// summary: the line above a day that stays on screen while it cannot be written into or re-read — a failed re-read as an alert with a retry, and the lock on marks while «today» from the cache waits for the server's confirmation; the id lets the locked fieldset point at the reason

import ErrorAlert from '@/components/ErrorAlert';

/** The id of the lock sentence, for `aria-describedby` on the locked area. */
export const DAY_WRITE_LOCK_ID = 'day-write-lock';

/** Said while the cached day waits for the server to confirm it. */
export const DAY_CHECKING = 'Сверяю день с сервером — отметки откроются после ответа.';

/** Said when the day cannot be confirmed: the server did not answer. */
export const DAY_LOCKED = 'День не подтверждён сервером: отметки недоступны, пока не вернётся связь.';

interface DayWriteNoticeProps {
  /** Why the last re-read failed, or null. */
  error: string | null;
  /** Writes are locked: the day on screen is not confirmed. */
  locked: boolean;
  onRetry: () => void;
}

export default function DayWriteNotice({ error, locked, onRetry }: DayWriteNoticeProps) {
  if (error === null && !locked) return null;
  return (
    <div className="space-y-3">
      {error !== null && (
        <div role="alert">
          <ErrorAlert message={error} onDismiss={onRetry} />
        </div>
      )}
      {locked && (
        <p id={DAY_WRITE_LOCK_ID} role="status" className="text-sm text-text-secondary">
          {error === null ? DAY_CHECKING : DAY_LOCKED}
        </p>
      )}
    </div>
  );
}
