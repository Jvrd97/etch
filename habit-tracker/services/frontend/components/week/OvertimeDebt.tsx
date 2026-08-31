'use client';
// [review:need-review] PHASE-03/179
// summary: the debt block of the week screen — what was borrowed from which day and whether it came back, a debt older than a week drawn as a failed rule rather than as a note, and the sentence that explains why a week of won days is still not won

import { useEffect, useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import { profilesAPI, type DebtLedger, type Week } from '@/lib/api';
import {
  DEBT_TITLE,
  NO_DEBT_TEXT,
  STALE_DEBT_TEXT,
  debtLine,
  isStale,
  ledgerRows,
  weekBlockedLine,
} from '@/lib/day-profiles';

export interface OvertimeDebtProps {
  week: Week;
  compact?: boolean;
}

/**
 * What the raised ceiling still owes.
 *
 * A debt open longer than a week is drawn as a broken rule and not as a note:
 * the whole trade of `#179` is «гибкость покупается возвратом», and a debt that
 * is never returned is the trade quietly not happening.
 */
export default function OvertimeDebtBlock({ week, compact = false }: OvertimeDebtProps) {
  const [ledger, setLedger] = useState<DebtLedger | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const body = await profilesAPI.debt();
        if (!cancelled) setLedger(body);
      } catch (error) {
        console.warn('долг за переработку не прочитался', error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [week.iso_code]);

  const card = `bg-card border border-white/5 rounded-3xl ${compact ? 'p-4' : 'p-6'}`;
  const blocked = weekBlockedLine(week);

  return (
    <section className={card}>
      <h2 className={`text-text-primary ${compact ? 'text-base' : 'text-lg'}`}>
        {DEBT_TITLE}
      </h2>

      {blocked && (
        <p className="mt-1 inline-flex items-start gap-2 text-sm text-warning">
          <TriangleAlert className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={2} />
          {blocked}
        </p>
      )}

      {!ledger || ledger.debts.length === 0 ? (
        <p className="text-sm text-text-secondary mt-2">{NO_DEBT_TEXT}</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {ledgerRows(ledger).map((debt) => (
            <li
              key={debt.incurred_on}
              className={`text-sm ${debt.is_open ? 'text-text-primary' : 'text-text-secondary'}`}
            >
              {debtLine(debt)}
              {isStale(debt) && (
                <span className="block text-xs text-warning">{STALE_DEBT_TEXT}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
