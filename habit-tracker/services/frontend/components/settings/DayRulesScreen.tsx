'use client';
// [review:need-review] PHASE-03/137, PHASE-03/152
// summary: экран правил дня — действующая версия целиком, история версий с датами и форма «новая версия с даты»; правка действующей строки недоступна и объяснена на месте, а рядом с кнопкой публикации написано, что вердикты прошедших дней не пересчитываются

import { useState, type FormEvent } from 'react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import { useDayRules } from '@/hooks/useDayRules';
import type { DayRuleSet } from '@/lib/api';
import {
  formatClock,
  formatMinutes,
  formatRatio,
  ruleLines,
  weekdayNames,
} from '@/lib/day-format';
import {
  draftFromRule,
  draftToPayload,
  ruleStanding,
  ruleStandingLabel,
  type RuleDraft,
} from '@/lib/day-rules';

export const SCREEN_TITLE = 'Правила дня';

/** Why the canon is a row with dates rather than a constant somewhere. */
export const SCREEN_INTRO =
  'Канон дня — версия с датой начала, а не настройка. День судится по той версии, ' +
  'которая действовала в его дату, поэтому изменение правил не переписывает прошлое.';

/** Said next to the current version, where an «изменить» button would be. */
export const NO_EDIT_NOTICE =
  'Действующую версию отредактировать нельзя — ни здесь, ни через API: по ней уже ' +
  'посчитаны вердикты прожитых дней. Единственный путь изменить канон — выпустить ' +
  'новую версию с будущей даты, ниже.';

/** The sentence the ticket asks for, in the one place it has to be read. */
export const PAST_UNCHANGED_WARNING =
  'Вердикты прошедших дней не изменятся: каждый день остаётся посчитанным по той ' +
  'версии, под которой он был прожит.';

export const PUBLISH_LABEL = 'Выпустить новую версию';
export const FORM_TITLE = 'Новая версия с даты';
export const CURRENT_TITLE = 'Действующая версия';
export const HISTORY_TITLE = 'История версий';
export const EMPTY_RULES_TEXT =
  'Правил дня нет ни одного: таблицу заполняет миграция. Пустая таблица — это ' +
  'незапущенная миграция, а не отсутствие настроек.';

const CARD = 'bg-card border border-white/5 rounded-3xl p-5';
const FIELD_LABEL = 'block text-xs uppercase tracking-wide text-text-secondary mb-1';
const FIELD_INPUT =
  'w-full bg-surface border border-white/10 rounded-2xl px-3 py-2 text-sm text-text-primary';

/** Since when — and until when — a version applies, spelled for the history list. */
function intervalText(rule: DayRuleSet): string {
  if (rule.valid_to === null) return `с ${rule.valid_from}, конца нет`;
  return `${rule.valid_from} — ${rule.valid_to}`;
}

/**
 * The free evening, which is a rule of the plan rather than a column here.
 *
 * Said out loud rather than left off the screen: the reader is looking for the
 * whole canon, and «этого поля нет в правиле» is an answer, while silence reads
 * as «свободного вечера больше нет».
 */
function freeEveningText(rule: DayRuleSet): string {
  return `после ${formatClock(rule.work_stop_at)} вечер свободный: жёсткими бывают только края дня, свободный блок задачами не расписывается (правило плана, отдельной колонки в версии у него нет)`;
}

interface RuleFactsProps {
  rule: DayRuleSet;
}

/** One version read out in full: edges, ceilings, anchors, the free evening. */
function RuleFacts({ rule }: RuleFactsProps) {
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
        {ruleLines(rule).map((line) => (
          <div key={line.label} className="flex justify-between gap-4 text-sm">
            <dt className="text-text-secondary">{line.label}</dt>
            <dd className="text-text-primary text-right">{line.value}</dd>
          </div>
        ))}
      </dl>

      <div className="text-sm">
        <span className="text-text-secondary">Обязательные якоря: </span>
        <span className="text-text-primary">
          {rule.required_anchors.length > 0 ? rule.required_anchors.join(', ') : 'нет'}
        </span>
      </div>

      <p className="text-xs text-text-secondary">Свободный вечер: {freeEveningText(rule)}</p>

      {rule.note_md !== '' && (
        <p className="text-xs text-text-secondary border-l-2 border-white/10 pl-3">
          {rule.note_md}
        </p>
      )}
    </div>
  );
}

interface DraftFieldProps {
  id: string;
  label: string;
  value: string;
  hint?: string;
  type?: 'text' | 'number' | 'date' | 'time';
  min?: string;
  onChange: (value: string) => void;
}

function DraftField({ id, label, value, hint, type = 'text', min, onChange }: DraftFieldProps) {
  return (
    <div>
      <label className={FIELD_LABEL} htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type={type}
        min={min}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={FIELD_INPUT}
      />
      {hint !== undefined && <p className="text-xs text-text-secondary mt-1">{hint}</p>}
    </div>
  );
}

/**
 * Правила дня: что действует, что действовало и как выпустить следующую версию.
 *
 * Экран существует ради одной цены, названной ADR-0015: канон переехал в базу,
 * и без этой страницы «стоп теперь в 17:00» требует psql. Форма поэтому
 * заполнена действующей версией — меняют обычно одно число, а не переписывают
 * канон, — а всё остальное на странице только читается.
 */
export default function DayRulesScreen() {
  const { history, loading, error, publishing, publishError, publishedFrom, publish } =
    useDayRules();
  // Only what the person actually typed. The rest of the form is derived from
  // the canon on every render, so a publication — which replaces the version in
  // force — refills the form by itself instead of leaving the previous canon on
  // screen; and nothing here writes state from an effect.
  const [edited, setEdited] = useState<RuleDraft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const current =
    history === null
      ? null
      : (history.rules.find((rule) => rule.id === history.current_id) ?? null);
  const seeded =
    current === null || history === null
      ? null
      : draftFromRule(current, history.earliest_valid_from);
  const draft = edited ?? seeded;

  if (loading) return <LoadingSpinner />;
  if (error !== null) return <ErrorAlert message={error} />;
  if (history === null) return <ErrorAlert message={EMPTY_RULES_TEXT} />;

  const set = (field: keyof RuleDraft, value: string | boolean) => {
    if (draft === null) return;
    setEdited({ ...draft, [field]: value });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (draft === null) return;
    const result = draftToPayload(draft, history.earliest_valid_from);
    if (!result.ok) {
      setFormError(result.error);
      return;
    }
    setFormError(null);
    // On success the form goes back to mirroring the canon, which by then is
    // the version just published: keeping the edits would show a draft that no
    // longer differs from anything.
    if (await publish(result.payload)) setEdited(null);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-bold text-text-primary">{SCREEN_TITLE}</h1>
        <p className="text-sm text-text-secondary">{SCREEN_INTRO}</p>
      </header>

      {current === null ? (
        <div className={CARD}>
          <p className="text-sm text-text-secondary">{EMPTY_RULES_TEXT}</p>
        </div>
      ) : (
        <section className={CARD}>
          <div className="flex items-baseline justify-between gap-4 mb-4">
            <h2 className="text-lg font-semibold text-text-primary">{CURRENT_TITLE}</h2>
            <span className="text-xs text-text-secondary">{intervalText(current)}</span>
          </div>
          <RuleFacts rule={current} />
          <p className="text-xs text-text-secondary mt-4 border-t border-white/5 pt-3">
            {NO_EDIT_NOTICE}
          </p>
        </section>
      )}

      <section className={CARD}>
        <h2 className="text-lg font-semibold text-text-primary mb-1">{HISTORY_TITLE}</h2>
        <p className="text-xs text-text-secondary mb-4">
          Сегодня по границе суток — {history.today}.
        </p>
        <ol className="space-y-3">
          {[...history.rules].reverse().map((rule) => {
            const standing = ruleStanding(rule, history.today);
            return (
              <li key={rule.id} className="border-t border-white/5 pt-3 first:border-0 first:pt-0">
                <div className="flex items-baseline justify-between gap-4">
                  <span className="text-sm text-text-primary">{intervalText(rule)}</span>
                  <span className="text-xs text-text-secondary">
                    {ruleStandingLabel(standing)}
                  </span>
                </div>
                <p className="text-xs text-text-secondary mt-1">
                  работа {formatMinutes(rule.work_cap_min)}, исключение{' '}
                  {formatMinutes(rule.work_hard_cap_min)}, стоп{' '}
                  {formatClock(rule.work_stop_at)}, задач {rule.max_work_tasks} по{' '}
                  {formatRatio(rule.tasks_required_ratio)}, рабочие{' '}
                  {weekdayNames(rule.workdays).join(', ')}
                </p>
              </li>
            );
          })}
        </ol>
        {history.rules.length === 0 && (
          <p className="text-sm text-text-secondary">{EMPTY_RULES_TEXT}</p>
        )}
      </section>

      {draft !== null && (
        <form className={CARD} onSubmit={(event) => void submit(event)}>
          <h2 className="text-lg font-semibold text-text-primary mb-1">{FORM_TITLE}</h2>
          <p className="text-xs text-text-secondary mb-4">
            Поля заполнены действующей версией — поменяйте те, что меняются. Раньше{' '}
            {history.earliest_valid_from} версия начаться не может.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <DraftField
              id="valid-from"
              label="Действует с"
              type="date"
              min={history.earliest_valid_from}
              value={draft.validFrom}
              onChange={(value) => set('validFrom', value)}
            />
            <DraftField
              id="work-stop-at"
              label="Стоп работы"
              type="time"
              value={draft.workStopAt}
              onChange={(value) => set('workStopAt', value)}
            />
            <DraftField
              id="work-cap"
              label="Потолок работы, мин"
              type="number"
              value={draft.workCapMin}
              hint={`= ${formatMinutes(Number(draft.workCapMin) || 0)}`}
              onChange={(value) => set('workCapMin', value)}
            />
            <DraftField
              id="work-hard-cap"
              label="Потолок-исключение, мин"
              type="number"
              value={draft.workHardCapMin}
              hint={`= ${formatMinutes(Number(draft.workHardCapMin) || 0)}`}
              onChange={(value) => set('workHardCapMin', value)}
            />
            <DraftField
              id="max-tasks"
              label="Рабочих задач в день"
              type="number"
              value={draft.maxWorkTasks}
              onChange={(value) => set('maxWorkTasks', value)}
            />
            <DraftField
              id="tasks-percent"
              label="Закрыть задач, %"
              type="number"
              value={draft.tasksRequiredPercent}
              onChange={(value) => set('tasksRequiredPercent', value)}
            />
            <DraftField
              id="timezone"
              label="Зона"
              value={draft.timezone}
              onChange={(value) => set('timezone', value)}
            />
            <DraftField
              id="day-start-hour"
              label="Сутки начинаются в, ч"
              type="number"
              value={draft.dayStartHour}
              onChange={(value) => set('dayStartHour', value)}
            />
            <DraftField
              id="workdays"
              label="Рабочие дни (ISO)"
              value={draft.workdays}
              hint="1 — понедельник, 7 — воскресенье"
              onChange={(value) => set('workdays', value)}
            />
            <DraftField
              id="nocode-days"
              label="No-code дни (ISO)"
              value={draft.nocodeDays}
              onChange={(value) => set('nocodeDays', value)}
            />
          </div>

          <div className="mt-4 space-y-4">
            <DraftField
              id="anchors"
              label="Обязательные якоря"
              value={draft.requiredAnchors}
              hint="через запятую; по ним считается вердикт дня"
              onChange={(value) => set('requiredAnchors', value)}
            />
            <DraftField
              id="role-clause-roles"
              label="Роли клауза дня"
              value={draft.roleClauseRoles}
              hint="коды через запятую; акт любой из них закрывает рабочий день"
              onChange={(value) => set('roleClauseRoles', value)}
            />
            <DraftField
              id="note"
              label="Зачем поменяли"
              value={draft.noteMd}
              onChange={(value) => set('noteMd', value)}
            />
            <label className="flex items-center gap-2 text-sm text-text-primary">
              <input
                type="checkbox"
                checked={draft.overtimeDisqualifies}
                onChange={(event) => set('overtimeDisqualifies', event.target.checked)}
              />
              Переработка валит день
            </label>
            <label className="flex items-center gap-2 text-sm text-text-primary">
              <input
                type="checkbox"
                checked={draft.roleClauseEnabled}
                onChange={(event) => set('roleClauseEnabled', event.target.checked)}
              />
              Рабочий день закрывает акт роли
            </label>
          </div>

          <p className="text-xs text-text-secondary mt-5">{PAST_UNCHANGED_WARNING}</p>

          <button
            type="submit"
            disabled={publishing}
            className="mt-3 px-5 py-2 rounded-full bg-lime text-background text-sm font-medium disabled:opacity-50"
          >
            {PUBLISH_LABEL}
          </button>

          {formError !== null && (
            <p className="text-sm text-danger mt-3" role="alert">
              {formError}
            </p>
          )}
          {publishError !== null && (
            <p className="text-sm text-danger mt-3" role="alert">
              {publishError}
            </p>
          )}
          {publishedFrom !== null && publishError === null && formError === null && (
            <p className="text-sm text-success mt-3">
              Новая версия действует с {publishedFrom}. Прошедшие дни не пересчитаны.
            </p>
          )}
        </form>
      )}
    </div>
  );
}
