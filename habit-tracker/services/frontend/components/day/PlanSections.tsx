'use client';
// [review:need-review] PHASE-03/87, PHASE-03/88, PHASE-03/110, PHASE-03/140, PHASE-03/147
// summary: PHASE-03/110 makes the line editable in place — a pencil that opens the editor on it, a button that adds a line to the section, and the warning of the canon printed under the line that earned it; the plan drawn as it was written — sections in order, items nested, a task showing its window and its criterion of being done, every label without a column of its own read back out of `extra`, and the mark of each line when the screen passes one in
// summary: the plan drawn as it was written — sections in order, items nested, a task showing its window and its criterion of being done, every label without a column of its own read back out of `extra`, the mark of each line when the screen passes one in, and the rule a line broke shown on the line itself — the edit stands, the note stays beside it

import {
  BadgeCheck,
  Clock,
  CornerDownRight,
  Link2,
  Pencil,
  Plus,
  TriangleAlert,
} from 'lucide-react';
import PlanItemEditor from '@/components/day/PlanItemEditor';
import PlanItemMark from '@/components/day/PlanItemMark';
import type {
  Mark,
  MarkState,
  PlanItem,
  PlanItemPatch,
  PlanSection,
  PlanViolation,
  Role,
} from '@/lib/api';
import { actIntentLine } from '@/lib/plan-roles';
import { ruleLabel } from '@/lib/plan-violations';
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

/**
 * What a line needs in order to be markable.
 *
 * Passed as one object rather than four props so that "this plan is read-only"
 * is a single `undefined` — a preview, a printed day and `#89`'s import all
 * render the same component without inventing handlers that write nothing.
 */
export interface PlanMarking {
  marks: Map<string, Mark>;
  saving: Set<string>;
  onCycle: (itemId: string) => void;
  onSetState: (itemId: string, state: MarkState | null) => void;
  onSetNote: (itemId: string, note: string) => void;
}

/** Text of the two controls the editor adds; named so tests can find them. */
export const EDIT_LINE_LABEL = 'Править пункт';
export const ADD_LINE_LABEL = 'Добавить пункт';

/**
 * What a line needs in order to be editable.
 *
 * One object again, and for the same reason as `PlanMarking`: a plan being
 * read — a preview, a printed day, the import of `#89` — leaves it out whole
 * and gets exactly the screen it had before this ticket.
 */
export interface PlanEditing {
  /** The line whose editor is open, or null when none is. */
  openId: string | null;
  /** Id of the line an edit is in flight for; its fields lock. */
  saving: string | null;
  /** Warnings of the canon by the code of the line that earned them. */
  warnings: Map<string, string>;
  onOpen: (itemId: string | null) => void;
  onSave: (itemId: string, patch: PlanItemPatch) => void;
  onDelete: (itemId: string) => void;
  onMove: (
    itemId: string,
    sectionId: string,
    position: number,
    parentId: string | null
  ) => void;
  onAdd: (sectionId: string) => void;
}

export interface PlanSectionsProps {
  sections: PlanSection[];
  /** Ids of items whose windows collide, so the line can say so where it is. */
  overlapping: Set<string>;
  /** Left out where the plan is only being read; then no line shows a box. */
  marking?: PlanMarking;
  /** Left out where the plan is only being read; then no line can be changed. */
  editing?: PlanEditing;
  /** Mobile trims the type scale; the structure is identical. */
  compact?: boolean;
  /**
   * Which rules each line broke, by item id.
   *
   * Empty is the normal case. A line that broke one is still drawn and still
   * markable — the edit stands; what it gains is a label saying which rule of
   * the canon it stepped over.
   */
  violations?: Map<string, PlanViolation[]>;
  /**
   * Справочник ролей (#140): подпись «архитектор · решение по модели данных» на
   * пункте, который несёт намерение на акт, и два поля в его редакторе.
   *
   * Пустой по умолчанию — план, который только читают, выглядит ровно как до
   * этого тикета.
   */
  roles?: Role[];
}

/**
 * The plan, section by section.
 *
 * The *text* used to be read-only, and `#110` ended that: the plan still
 * arrives from `/day-open` as one document, but a person now edits a line where
 * it is drawn. The whole-document rules did not go anywhere — the server runs
 * them after the write and hands back what a human's edit broke as a warning,
 * because "не перезакручивать" is advice to the author of the day, not a lock
 * on his own plan.
 *
 * The *marks* are not text. They are what a person adds to a plan while living
 * the day, they hang off the item's uuid rather than its position, and each one
 * is a write of its own — so `marking` turns them on without turning the plan
 * into an editor.
 */
export default function PlanSections({
  sections,
  overlapping,
  marking,
  editing,
  compact = false,
  violations,
  roles = [],
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
            {section.items.map((item, index) => (
              <PlanLine
                key={item.id}
                item={item}
                sectionId={section.id}
                index={index}
                siblings={section.items.length}
                level={0}
                overlapping={overlapping}
                marking={marking}
                editing={editing}
                compact={compact}
                violations={violations}
                roles={roles}
              />
            ))}
          </ul>
          {editing && (
            <button
              type="button"
              onClick={() => editing.onAdd(section.id)}
              disabled={editing.saving === section.id}
              className="mt-3 inline-flex items-center gap-1 rounded-2xl bg-surface px-3 py-1.5 text-sm text-text-secondary"
            >
              <Plus className="w-4 h-4" strokeWidth={2} />
              {ADD_LINE_LABEL}
            </button>
          )}
        </section>
      ))}
    </div>
  );
}

interface PlanLineProps {
  item: PlanItem;
  /** The section this line lives in — a move needs to name it. */
  sectionId: string;
  /** Position among its siblings, and how many of them there are. */
  index: number;
  siblings: number;
  level: number;
  overlapping: Set<string>;
  marking?: PlanMarking;
  editing?: PlanEditing;
  compact: boolean;
  violations?: Map<string, PlanViolation[]>;
  roles: Role[];
}

/**
 * One line of the plan, and its children under it.
 *
 * A minimum is a child rather than a sentence inside its parent, and it is
 * drawn as its own line for exactly that reason: 29 August showed that a
 * minimum written inside a task does not get done.
 */
function PlanLine({
  item,
  sectionId,
  index,
  siblings,
  level,
  overlapping,
  marking,
  editing,
  compact,
  violations,
  roles,
}: PlanLineProps) {
  const broken = violations?.get(item.id) ?? [];
  const intent = actIntentLine(item, roles);
  const indent = Math.min(level, MAX_INDENT_LEVEL) * INDENT_PER_LEVEL;
  const kind = itemKindLabel(item.kind);
  const rigidity = rigidityLabel(item.rigidity);
  const extras = extraLines(item);
  const collides = overlapping.has(item.id);
  const text = compact ? 'text-sm' : 'text-base';
  // Предупреждение адресуется кодом пункта — тем же, которым его называет 422.
  const warning =
    editing && item.code ? (editing.warnings.get(item.code) ?? null) : null;

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
            {editing && editing.openId !== item.id && (
              <button
                type="button"
                aria-label={EDIT_LINE_LABEL}
                onClick={() => editing.onOpen(item.id)}
                className="rounded-2xl p-1 text-text-disabled hover:text-text-secondary"
              >
                <Pencil className="w-3.5 h-3.5" strokeWidth={2} />
              </button>
            )}
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
            {broken.map((violation) => (
              // Marked, not hidden and not blocked: «свой день человек правит
              // свободно», and a rule nobody is told about is a rule that does
              // not exist.
              <span
                key={violation.id}
                className="px-2 py-0.5 rounded-2xl bg-warning/10 text-xs text-warning"
                title={ruleLabel(violation.rule_code)}
              >
                {ruleLabel(violation.rule_code)}
              </span>
            ))}
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

          {intent !== null && (
            // Подпись, а не значок: «что закроет эта галочка» — предложение, и
            // читается оно на месте, без наведения мышью.
            <p className="mt-1 inline-flex items-center gap-2 text-sm text-lime">
              <BadgeCheck className="w-4 h-4 shrink-0" strokeWidth={2} />
              {intent}
            </p>
          )}

          {item.unlinked_reason && (
            <p className="mt-1 inline-flex items-start gap-2 text-sm text-text-secondary">
              <Link2 className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={2} />
              {item.unlinked_reason}
            </p>
          )}

          {warning !== null && (
            <p className="mt-1 inline-flex items-start gap-2 text-sm text-warning">
              <TriangleAlert className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={2} />
              {warning}
            </p>
          )}

          {editing && editing.openId === item.id && (
            <PlanItemEditor
              item={item}
              saving={editing.saving === item.id}
              atTop={index === 0}
              atBottom={index === siblings - 1}
              onSave={(patch) => editing.onSave(item.id, patch)}
              onDelete={() => editing.onDelete(item.id)}
              onMoveUp={() =>
                editing.onMove(item.id, sectionId, index - 1, item.parent_id)
              }
              onMoveDown={() =>
                editing.onMove(item.id, sectionId, index + 1, item.parent_id)
              }
              onCancel={() => editing.onOpen(null)}
              roles={roles}
            />
          )}

          {marking && (
            <div className="mt-2">
              <PlanItemMark
                itemId={item.id}
                state={marking.marks.get(item.id)?.state ?? null}
                note={marking.marks.get(item.id)?.note ?? ''}
                saving={marking.saving.has(item.id)}
                onCycle={marking.onCycle}
                onSetState={marking.onSetState}
                onSetNote={marking.onSetNote}
                compact={compact}
              />
            </div>
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
          {item.children.map((child, childIndex) => (
            <PlanLine
              key={child.id}
              item={child}
              sectionId={sectionId}
              index={childIndex}
              siblings={item.children.length}
              level={level + 1}
              overlapping={overlapping}
              marking={marking}
              editing={editing}
              compact={compact}
              violations={violations}
              roles={roles}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
