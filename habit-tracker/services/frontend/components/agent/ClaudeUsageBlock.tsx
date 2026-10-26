// [review:need-review] PHASE-03/220
// summary: the Claude Code block of the day screen — sessions, assistant turns and tokens of one day from the mac agent's session aggregates, counters only (no message text, project or branch); a quiet zero on the server's today, nothing on an empty past day, and the caption that a session counts whole on the day it began

import { boundaryCaption, formatTokens } from '@/lib/claude-usage';
import type { ClaudeUsageDay } from '@/lib/api';

export interface ClaudeUsageBlockProps {
  /** Null until the first answer; nothing is drawn for it. */
  usage: ClaudeUsageDay | null;
  /** The phone shell: tighter padding and type. */
  compact?: boolean;
}

const HEADING_ID = 'claude-usage-heading';

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd className="text-sm font-medium text-text-primary tabular-nums">{value}</dd>
    </div>
  );
}

export default function ClaudeUsageBlock({ usage, compact = false }: ClaudeUsageBlockProps) {
  if (usage === null) return null;
  const isToday = usage.date === usage.today;
  const empty = usage.sessions === 0;
  // A past day with no sessions is just a day without Claude Code; today's zero is worth saying.
  if (empty && !isToday) return null;

  return (
    <section
      aria-labelledby={HEADING_ID}
      className={`rounded-3xl border border-white/5 bg-surface ${compact ? 'p-3' : 'p-4'}`}
    >
      <h3 id={HEADING_ID} className="text-sm font-medium text-text-primary">
        Claude Code
      </h3>
      {empty ? (
        <p className="text-sm text-text-secondary mt-1">Сегодня сессий Claude Code не было</p>
      ) : (
        <>
          <dl className={`mt-2 grid gap-x-6 gap-y-2 ${compact ? 'grid-cols-1' : 'grid-cols-2 lg:grid-cols-4'}`}>
            <Stat label="Сессии" value={String(usage.sessions)} />
            <Stat label="Ходы ассистента" value={String(usage.assistant_turns)} />
            <Stat
              label="Токены"
              value={`${formatTokens(usage.input_tokens)} вход · ${formatTokens(usage.output_tokens)} выход`}
            />
            <Stat
              label="Кеш"
              value={`${formatTokens(usage.cache_read_tokens)} чтение · ${formatTokens(usage.cache_creation_tokens)} запись`}
            />
          </dl>
          <p className="text-xs text-text-secondary mt-2">{boundaryCaption(usage.sessions_past_boundary)}</p>
        </>
      )}
    </section>
  );
}
