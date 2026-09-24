// [review:need-review] PHASE-01/174
// summary: dashboard card lists active avoid categories and their current clean-day streaks
'use client';

import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import type { AvoidStreak } from '@/hooks/useDashboard';
import { formatDays } from '@/lib/streak-format';

interface CurrentStreaksProps {
  streaks: AvoidStreak[];
  compact?: boolean;
}

export function CurrentStreaks({ streaks, compact = false }: CurrentStreaksProps) {
  return (
    <section
      aria-labelledby="current-streaks-title"
      className={`bg-card border border-white/5 rounded-3xl ${compact ? 'p-4' : 'p-6'}`}
    >
      <div className="flex items-center justify-between gap-4">
        <h2 id="current-streaks-title" className="text-lg font-semibold text-text-primary">
          Current streaks
        </h2>
        <Link
          href="/categories"
          className="inline-flex items-center gap-1 text-sm font-medium text-text-secondary hover:text-lime"
        >
          View all
          <ArrowRight className="h-4 w-4" strokeWidth={2} />
        </Link>
      </div>
      {streaks.length === 0 ? (
        <p className="mt-4 text-sm text-text-secondary">No avoid habits yet</p>
      ) : (
        <ul className="mt-4 space-y-3" aria-label="Avoid habit streaks">
          {streaks.map(({ category, streak }) => (
            <li key={category.id} className="flex items-center justify-between gap-3">
              <span className="flex min-w-0 items-center gap-3">
                <span
                  aria-hidden="true"
                  className="h-3 w-3 shrink-0 rounded-full"
                  style={{ backgroundColor: category.color ?? '#B8FF36' }}
                />
                <span className="truncate text-sm font-medium text-text-primary">
                  {category.name}
                </span>
              </span>
              <span className="shrink-0 text-sm text-text-secondary">
                {formatDays(streak.current_streak)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
