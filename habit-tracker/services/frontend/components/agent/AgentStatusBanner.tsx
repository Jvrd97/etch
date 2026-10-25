// [review:need-review] PHASE-03/164
// summary: the banners of the agent on the day screen — silence, a missing Accessibility, the titles switch — each saying what is lost and what to press; drawn only for today, because silence now says nothing about an earlier day

import Link from 'next/link';
import { AlertTriangle, Info } from 'lucide-react';
import { bannersFor, type AgentBanner } from '@/lib/agent-status';
import type { AgentStatus } from '@/lib/api';

export interface AgentStatusBannerProps {
  /** Null until the first answer; nothing is drawn for it. */
  status: AgentStatus | null;
  /** `YYYY-MM-DD` of the day on screen. */
  date: string;
  /** `YYYY-MM-DD` of today, a parameter so a test can pin it. */
  today: string;
}

function Banner({ banner }: { banner: AgentBanner }) {
  // The switch is a decision, so it is quiet; the other two are lost data.
  const lost = banner.kind !== 'titles_off';
  const Icon = lost ? AlertTriangle : Info;
  return (
    <div
      role="status"
      data-banner={banner.kind}
      className={`rounded-3xl border p-4 flex items-start gap-3 ${
        lost ? 'bg-warning/10 border-warning/40' : 'bg-surface border-white/5'
      }`}
    >
      <Icon
        className={`w-5 h-5 flex-shrink-0 mt-0.5 ${lost ? 'text-warning' : 'text-text-secondary'}`}
        strokeWidth={2}
      />
      <div className="min-w-0">
        <h3 className="text-sm font-medium text-text-primary">
          {banner.title}
          {banner.agentLabel !== null && (
            <span className="ml-2 text-xs font-normal text-text-secondary">
              мак {banner.agentLabel}
            </span>
          )}
        </h3>
        <p className="text-sm text-text-secondary mt-1">{banner.body}</p>
        {banner.action !== null && (
          <Link
            href={banner.action.href}
            className="inline-block mt-2 text-sm text-lime hover:underline"
          >
            {banner.action.label}
          </Link>
        )}
      </div>
    </div>
  );
}

export default function AgentStatusBanner({ status, date, today }: AgentStatusBannerProps) {
  if (status === null || date !== today) return null;
  const banners = bannersFor(status);
  if (banners.length === 0) return null;
  return (
    <div className="space-y-3">
      {banners.map((banner) => (
        <Banner key={banner.key} banner={banner} />
      ))}
    </div>
  );
}
