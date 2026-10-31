// [review:need-review] #302
// summary: «Инсайт недели» - the ready text of the server with the moment it was made (server wall clock), a link to the history; no insight says so instead of inventing one

import Link from 'next/link';
import { ArrowRight, Sparkles } from 'lucide-react';
import type { DashboardInsight } from '@/lib/api';
import { formatGeneratedAt } from '@/lib/dashboard-summary';
import { MOBILE_PATH_PREFIX } from '@/lib/routes';
import { DashboardCard, EmptyLine } from './DashboardCard';

interface InsightBlockProps {
  insight: DashboardInsight | null;
  mobile?: boolean;
}

export function InsightBlock({ insight, mobile = false }: InsightBlockProps) {
  const madeAt = insight === null ? '' : formatGeneratedAt(insight.generated_at);
  return (
    <DashboardCard
      title={
        <span className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-lime" strokeWidth={2} aria-hidden="true" />
          Инсайт недели
        </span>
      }
      mobile={mobile}
    >
      {insight === null ? (
        <EmptyLine>Данных мало: инсайт появится, когда накопится неделя записей.</EmptyLine>
      ) : (
        <>
          <p className="text-base leading-relaxed text-text-primary">{insight.text}</p>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            {madeAt !== '' && (
              <span className="text-[13px] text-text-secondary">Сформирован {madeAt}</span>
            )}
            <Link
              href={`${mobile ? MOBILE_PATH_PREFIX : ''}/insights`}
              className="inline-flex items-center gap-1 text-sm font-medium text-lime hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lime"
            >
              История разборов
              <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
            </Link>
          </div>
        </>
      )}
    </DashboardCard>
  );
}
