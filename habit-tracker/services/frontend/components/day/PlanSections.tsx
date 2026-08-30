// [review:need-review] PHASE-03/87
// summary: the plan drawn as it was written — sections in order, items nested, a task showing its window and its criterion of being done, and every label without a column of its own read back out of `extra`

import { Clock, CornerDownRight, Link2 } from 'lucide-react';
import type { PlanItem, PlanSection } from '@/lib/api';
import {
  EMPTY_PLAN_TEXT,
  extraLines,
  formatWindow,
  itemKindLabel,
  rigidityLabel,
  sectionTitle,
} from '@/lib/plan';

/** How deep a nested item is indented, in Tailwind's spacing scale. */
const INDENT_PER_LEVEL = 4;

/** Beyond this the indent stops growing; a plan nested deeper is a plan to fix. */
const MAX_INDENT_LEVEL = 3;

export interface PlanSectionsProps {
  sections: PlanSection[];
  /** Ids of items whose windows collide, so the line can say so where it is. */
  overlapping: Set<string>;
  /** Mobile trims the type scale; the structure is identical. */
  compact?: boolean;
}

/**
 * The plan, section by section.
 *
 * Read-only on purpose: `#87` moves the plan into rows, and the plan still
 * arrives from `/day-open` as one document. Editing a line here would be a
 * second way to write a plan, with none of the whole-document rules the server
 * applies — the bar on tasks and "only the edges may be hard" cannot be checked
 * one keystroke at a time.
 */
export default function PlanSections({
  sections,
  overlapping,
  compact = false,
}: PlanSectionsProps) {
  if (sections.length === 0) {
    return (
      <p className="text-text-secondary">{EMPTY_PLAN_TEXT}</p>
    );
  }

  return (
    <div className={compact ? 'space-y-4' : 'space-y-6'}>
      {sections.map((section) => (
        <section
          key={section.id}
          className={`bg-card border border-white/5 rounded-3xl ${compact ? 'p-4' : 'p-6'}`}
        >
          <h2
            className={`font-semibold text-text-primary ${compact ? 'text-base' : 'text-xl'}`}
          >
            {sectionTitle(section)}
          </h2>
          <ul className={compact ? 'mt-3 space-y-3' : 'mt-4 space-y-4'}>
            {section.items.map((item) => (
              <PlanLine
                key={item.id}
                item={item}
                level={0}
                overlapping={overlapping}
                compact={compact}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

interface PlanLineProps {
  item: PlanItem;
  level: number;
  overlapping: Set<string>;
  compact: boolean;
}

/**
 * One line of the plan, and its children under it.
 *
 * A minimum is a child rather than a sentence inside its parent, and it is
 * drawn as its own line for exactly that reason: 29 August showed that a
 * minimum written inside a task does not get done.
 */
function PlanLine({ item, level, overlapping, compact }: PlanLineProps) {
  const indent = Math.min(level, MAX_INDENT_LEVEL) * INDENT_PER_LEVEL;
  const kind = itemKindLabel(item.kind);
  const rigidity = rigidityLabel(item.rigidity);
  const extras = extraLines(item);
  const collides = overlapping.has(item.id);
  const text = compact ? 'text-sm' : 'text-base';

  return (
    <li style={{ marginLeft: `${indent * 0.25}rem` }}>
      <div className="flex items-start gap-2">
        {level > 0 && (
          <CornerDownRight
            className="w-4 h-4 mt-1 shrink-0 text-text-disabled"
            strokeWidth={2}
          />
        )}
        <div className="min-w-0 flex-1">
          <div className={`flex flex-wrap items-center gap-2 ${text}`}>
            {item.code && (
              <span className="font-mono text-xs text-text-secondary">
                {item.code}
              </span>
            )}
            <span className="text-text-primary">{item.text_plain}</span>
            {kind && (
              <span className="px-2 py-0.5 rounded-2xl bg-surface text-xs text-text-secondary">
                {kind}
              </span>
            )}
            {rigidity && (
              <span className="px-2 py-0.5 rounded-2xl bg-surface text-xs text-text-secondary">
                {rigidity}
              </span>
            )}
          </div>

          {item.starts_at && item.ends_at && (
            <p
              className={`mt-1 inline-flex items-center gap-2 text-sm ${
                collides ? 'text-warning' : 'text-text-secondary'
              }`}
            >
              <Clock className="w-4 h-4" strokeWidth={2} />
              {formatWindow(item.starts_at, item.ends_at)}
              <span className="text-text-disabled">·</span>
              {item.window_comment ?? ''}
            </p>
          )}

          {item.done_criterion && (
            <p className="mt-1 text-sm text-text-secondary">
              <span className="text-text-disabled">Сделано: </span>
              {item.done_criterion}
            </p>
          )}

          {item.unlinked_reason && (
            <p className="mt-1 inline-flex items-start gap-2 text-sm text-text-secondary">
              <Link2 className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={2} />
              {item.unlinked_reason}
            </p>
          )}

          {extras.length > 0 && (
            <dl className="mt-1 space-y-0.5 text-sm">
              {extras.map((line) => (
                <div key={line.label} className="flex gap-2">
                  <dt className="text-text-disabled">{line.label}:</dt>
                  <dd className="text-text-secondary">{line.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>

      {item.children.length > 0 && (
        <ul className="mt-2 space-y-2">
          {item.children.map((child) => (
            <PlanLine
              key={child.id}
              item={child}
              level={level + 1}
              overlapping={overlapping}
              compact={compact}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
