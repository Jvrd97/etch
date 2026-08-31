'use client';
// [review:need-review] PHASE-03/125
// summary: the quick-mark directory screen shared by both shells — the whole list including switched-off buttons, the order moved a step at a time, delete behind a confirmation that says what it does not touch, and the editor whose filled-in form survives a taken-key refusal

import { useState } from 'react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import QuickMarkEditor from '@/components/QuickMarkEditor';
import { useQuickMarkAdmin } from '@/hooks/useQuickMarkAdmin';
import type { QuickMark } from '@/lib/api';
import {
  KIND_LABELS,
  draftFromMark,
  draftToPayload,
  emptyDraft,
  type QuickMarkFormDraft,
} from '@/lib/quick-mark-form';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

export const SCREEN_TITLE = 'Быстрые отметки';

/** Why the screen exists at all, said where the reader is standing. */
export const SCREEN_INTRO =
  'Справочник кнопок Today и плавающего окна. Кнопка заводится здесь, а не SQL-запросом: ' +
  'шаг воды меняется чаще, чем схема базы.';

export const NEW_MARK_LABEL = 'Новая кнопка';
export const EDIT_LABEL = 'Править';
export const DELETE_LABEL = 'Удалить';
export const EMPTY_TEXT =
  'Справочник пуст. Пока в нём нет ни одной кнопки, на Today нет и секции быстрых отметок.';

/** Said in the confirmation, because the fear it answers is losing the history. */
export const DELETE_CONFIRM_HINT =
  'Записанные значения и события журнала остаются: удаляется кнопка, а не прожитый день. ' +
  'Клавиша освобождается и её можно назначить другой кнопке.';
export const DELETE_CONFIRM_LABEL = 'Удалить кнопку';
export const DELETE_CANCEL_LABEL = 'Не удалять';

/** Accessible name of the control that moves one button up the list. */
export function moveMarkUpLabel(position: number): string {
  return `Поднять кнопку ${position}`;
}

/** Accessible name of the control that moves one button down the list. */
export function moveMarkDownLabel(position: number): string {
  return `Опустить кнопку ${position}`;
}

/** The one line under a row's label: what the tap does and where it is shown. */
export function markSummary(mark: QuickMark): string {
  const parts: string[] = [KIND_LABELS[mark.kind]];
  if (mark.step !== null) parts.push(`шаг ${mark.step}${mark.unit_label ? ` ${mark.unit_label}` : ''}`);
  if (mark.hotkey !== null) parts.push(`клавиша ${mark.hotkey}`);
  parts.push(mark.show_in_agent ? 'в окне агента' : 'только на Today');
  if (!mark.is_active) parts.push('выключена');
  return parts.join(' · ');
}

export interface QuickMarksScreenProps {
  /** Draw on the mobile type scale and size every control as a touch target. */
  compact?: boolean;
}

/**
 * The directory, editable.
 *
 * One screen for both shells: the button is entered where it is later pressed,
 * and the phone is where it is pressed. `compact` changes the type scale and
 * the size of the controls, not what the screen can do — a directory that could
 * only be edited from a desktop would send the person back to SQL exactly when
 * he is away from it.
 */
export default function QuickMarksScreen({ compact = false }: QuickMarksScreenProps) {
  const { marks, categories, loading, error, conflict, create, update, remove, move, dismiss } =
    useQuickMarkAdmin();
  /** The button being edited, `'new'` while entering one, or null. */
  const [editing, setEditing] = useState<number | 'new' | null>(null);
  const [draft, setDraft] = useState<QuickMarkFormDraft>(emptyDraft);
  const [confirming, setConfirming] = useState<number | null>(null);

  const startNew = () => {
    dismiss();
    setDraft(emptyDraft());
    setEditing('new');
  };

  const startEdit = (mark: QuickMark) => {
    dismiss();
    setDraft(draftFromMark(mark));
    setEditing(mark.id);
  };

  const submit = async () => {
    const payload = draftToPayload(draft);
    const saved =
      editing === 'new' ? await create(payload) : await update(editing as number, payload);
    // Форма закрывается только на успехе: отказ по занятой клавише обязан
    // оставить заполненное на экране, иначе человек набирает всё заново.
    if (saved) setEditing(null);
  };

  const sizing = compact ? { minHeight: TAP_TARGET_PX } : undefined;
  const titleClass = compact ? 'text-xl font-semibold' : 'text-2xl font-semibold';

  if (loading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className={`${titleClass} text-text-primary`}>{SCREEN_TITLE}</h1>
        <p className="text-sm text-text-secondary">{SCREEN_INTRO}</p>
      </header>

      {error !== null && conflict === null && <ErrorAlert message={error} onDismiss={dismiss} />}

      {editing === null ? (
        <button
          type="button"
          onClick={startNew}
          className="px-4 py-2 rounded-2xl bg-lime text-black text-sm font-medium"
          style={sizing}
        >
          {NEW_MARK_LABEL}
        </button>
      ) : (
        <section className="bg-card border border-white/5 rounded-3xl p-5">
          <QuickMarkEditor
            draft={draft}
            onChange={setDraft}
            categories={categories}
            conflict={conflict}
            editing={editing !== 'new'}
            onSubmit={() => void submit()}
            onCancel={() => setEditing(null)}
            touch={compact}
          />
        </section>
      )}

      {marks.length === 0 ? (
        <p className="text-sm text-text-secondary">{EMPTY_TEXT}</p>
      ) : (
        <ul className="space-y-3">
          {marks.map((mark, index) => (
            <li
              key={mark.id}
              className={`bg-card border border-white/5 rounded-3xl p-4 ${
                mark.is_active ? '' : 'opacity-60'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">{mark.label}</p>
                  <p className="text-xs text-text-secondary mt-1">{markSummary(mark)}</p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    type="button"
                    aria-label={moveMarkUpLabel(index + 1)}
                    disabled={index === 0}
                    onClick={() => void move(mark.id, -1)}
                    className="px-2 py-1 text-text-secondary disabled:text-text-disabled"
                    style={sizing}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    aria-label={moveMarkDownLabel(index + 1)}
                    disabled={index === marks.length - 1}
                    onClick={() => void move(mark.id, 1)}
                    className="px-2 py-1 text-text-secondary disabled:text-text-disabled"
                    style={sizing}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    onClick={() => startEdit(mark)}
                    className="px-3 py-1 rounded-2xl border border-white/10 text-xs text-text-secondary"
                    style={sizing}
                  >
                    {EDIT_LABEL}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirming(mark.id)}
                    className="px-3 py-1 rounded-2xl border border-danger/40 text-xs text-danger"
                    style={sizing}
                  >
                    {DELETE_LABEL}
                  </button>
                </div>
              </div>

              {confirming === mark.id && (
                <div className="mt-3 border-t border-white/5 pt-3 space-y-2">
                  <p className="text-xs text-text-secondary">{DELETE_CONFIRM_HINT}</p>
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        setConfirming(null);
                        if (editing === mark.id) setEditing(null);
                        void remove(mark.id);
                      }}
                      className="px-3 py-1 rounded-2xl bg-danger text-black text-xs font-medium"
                      style={sizing}
                    >
                      {DELETE_CONFIRM_LABEL}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirming(null)}
                      className="px-3 py-1 rounded-2xl border border-white/10 text-xs text-text-secondary"
                      style={sizing}
                    >
                      {DELETE_CANCEL_LABEL}
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
