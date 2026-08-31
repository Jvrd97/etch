'use client';
// [review:need-review] PHASE-03/127, PHASE-03/128, PHASE-03/129
// summary: the Today block of obligations — the cards of the ones running now, the separate «Предложено» block of what the model proposed and nobody has taken on yet, the failure mode and budget chosen at creation, and the button that counts today by hand; one component so both shells mount the same behaviour

import { useState } from 'react';
import ChallengeCard from '@/components/ChallengeCard';
import ProposedChallengeCard from '@/components/ProposedChallengeCard';
import { useChallenges } from '@/hooks/useChallenges';
import { isOnToday, isProposal } from '@/lib/challenges';
import type {
  Category,
  Challenge,
  ChallengeFailureMode,
  ChallengeRuleKind,
} from '@/lib/api';
import { todayISO } from '@/lib/date';

interface ChallengesSectionProps {
  /** Categories already loaded by the Today screen; the rule points into one. */
  categories: Category[];
}

/** The four promises, with the wording a person reads rather than the code. */
const RULE_LABELS: { value: ChallengeRuleKind; label: string; needsTarget: boolean }[] = [
  { value: 'metric_at_least', label: 'не меньше, чем', needsTarget: true },
  { value: 'metric_at_most', label: 'не больше, чем', needsTarget: true },
  { value: 'checked', label: 'отмечено', needsTarget: false },
  { value: 'abstain', label: 'без срыва', needsTarget: false },
];

/** Default window: a week, because that is the promise people actually keep. */
const DEFAULT_WINDOW_DAYS = 6;

/**
 * Как обязательство заканчивается.
 *
 * Бюджет промахов стоит рядом с «первый промах заваливает» не ради мягкости:
 * «месяц без единого пропуска» ставится один раз и заваливается на пятый день,
 * после чего челлендж превращается в мёртвую строку.
 */
/** Заголовок блока предложений — он же то, за что цепляется тест. */
export const PROPOSED_TITLE = 'Предложено';

const FAILURE_LABELS: { value: ChallengeFailureMode; label: string }[] = [
  { value: 'any_miss', label: 'первый промах заваливает' },
  { value: 'budget', label: 'бюджет промахов' },
];

function isoDaysFromToday(offset: number): string {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  return day.toISOString().slice(0, 10);
}

/**
 * Обязательства на экране сегодняшнего дня.
 *
 * На Today показаны только идущие: завершённые остаются фактом в общем списке,
 * но сегодняшний экран — про то, что делается сегодня.
 */
export default function ChallengesSection({ categories }: ChallengesSectionProps) {
  const {
    challenges,
    loading,
    error,
    create,
    countToday,
    counting,
    accept,
    decline,
    answering,
  } = useChallenges();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [fieldId, setFieldId] = useState<number | null>(null);
  const [ruleKind, setRuleKind] = useState<ChallengeRuleKind>('metric_at_least');
  const [target, setTarget] = useState('');
  const [failureMode, setFailureMode] = useState<ChallengeFailureMode>('any_miss');
  const [allowedMisses, setAllowedMisses] = useState('0');
  const [startsOn, setStartsOn] = useState(isoDaysFromToday(0));
  const [endsOn, setEndsOn] = useState(isoDaysFromToday(DEFAULT_WINDOW_DAYS));
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const running = challenges.filter(isOnToday);
  // Отдельным списком, а не вперемешку: предложение — это не обязательство, и
  // в счёте активных ему делать нечего.
  const proposed = challenges.filter(isProposal);
  const category = categories.find((item) => item.id === categoryId) ?? null;
  const fields = category?.fields ?? [];
  const needsTarget =
    RULE_LABELS.find((rule) => rule.value === ruleKind)?.needsTarget ?? false;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (saving || categoryId === null || fieldId === null) return;

    setSaving(true);
    setFormError(null);
    try {
      await create({
        title: title.trim(),
        category_id: categoryId,
        field_id: fieldId,
        rule_kind: ruleKind,
        target: needsTarget ? target : undefined,
        starts_on: startsOn,
        ends_on: endsOn,
        failure_mode: failureMode,
        // `any_miss` бюджета не имеет, и сервер отказывает ненулевому: два
        // способа сказать «первый промах заваливает» — это один способ и одна
        // ошибка.
        allowed_misses: failureMode === 'budget' ? Number(allowedMisses) : 0,
      });
      setOpen(false);
      setTitle('');
      setTarget('');
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Не удалось завести челлендж');
    } finally {
      setSaving(false);
    }
  };

  if (loading && running.length === 0 && proposed.length === 0) return null;

  return (
    <section className="space-y-3" aria-label="Челленджи">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text-primary">Челленджи</h2>
        <button
          type="button"
          className="text-sm text-lime"
          onClick={() => setOpen((current) => !current)}
        >
          {open ? 'Отмена' : 'Новый'}
        </button>
      </div>

      {error && <p className="text-sm text-rose-500">{error}</p>}

      {proposed.length > 0 && (
        <section className="space-y-2" aria-label={PROPOSED_TITLE}>
          <h3 className="text-sm font-medium uppercase tracking-widest text-lime">
            {PROPOSED_TITLE}
          </h3>
          {proposed.map((challenge) => (
            <ProposedChallengeCard
              key={challenge.id}
              challenge={challenge}
              categories={categories}
              onAccept={(item: Challenge) => void accept(item.id)}
              onDecline={(item: Challenge) => void decline(item.id)}
              answering={answering.has(challenge.id)}
            />
          ))}
        </section>
      )}

      {running.map((challenge) => (
        <ChallengeCard
          key={challenge.id}
          challenge={challenge}
          onCountToday={(item: Challenge) => void countToday(item.id, todayISO())}
          counting={counting.has(challenge.id)}
        />
      ))}

      {open && (
        <form onSubmit={submit} className="space-y-2 rounded-xl border border-white/10 p-4">
          <input
            aria-label="Название"
            className="w-full bg-transparent border-b border-white/10 py-1"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="7 дней подряд ≥ 2 л воды"
            required
          />

          <select
            aria-label="Категория"
            className="w-full bg-transparent border-b border-white/10 py-1"
            value={categoryId ?? ''}
            onChange={(event) => {
              setCategoryId(Number(event.target.value));
              setFieldId(null);
            }}
            required
          >
            <option value="">категория</option>
            {categories.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>

          <select
            aria-label="Поле"
            className="w-full bg-transparent border-b border-white/10 py-1"
            value={fieldId ?? ''}
            onChange={(event) => setFieldId(Number(event.target.value))}
            required
          >
            <option value="">поле</option>
            {fields.map((field) => (
              <option key={field.id} value={field.id}>
                {field.name}
              </option>
            ))}
          </select>

          <select
            aria-label="Правило"
            className="w-full bg-transparent border-b border-white/10 py-1"
            value={ruleKind}
            onChange={(event) => setRuleKind(event.target.value as ChallengeRuleKind)}
          >
            {RULE_LABELS.map((rule) => (
              <option key={rule.value} value={rule.value}>
                {rule.label}
              </option>
            ))}
          </select>

          <select
            aria-label="Режим провала"
            className="w-full bg-transparent border-b border-white/10 py-1"
            value={failureMode}
            onChange={(event) =>
              setFailureMode(event.target.value as ChallengeFailureMode)
            }
          >
            {FAILURE_LABELS.map((mode) => (
              <option key={mode.value} value={mode.value}>
                {mode.label}
              </option>
            ))}
          </select>

          {failureMode === 'budget' && (
            <input
              aria-label="Бюджет промахов"
              className="w-full bg-transparent border-b border-white/10 py-1"
              value={allowedMisses}
              onChange={(event) => setAllowedMisses(event.target.value)}
              inputMode="numeric"
              required
            />
          )}

          {needsTarget && (
            <input
              aria-label="Порог"
              className="w-full bg-transparent border-b border-white/10 py-1"
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              inputMode="decimal"
              required
            />
          )}

          <div className="flex gap-2">
            <input
              aria-label="Начало"
              type="date"
              className="flex-1 bg-transparent border-b border-white/10 py-1"
              value={startsOn}
              onChange={(event) => setStartsOn(event.target.value)}
              required
            />
            <input
              aria-label="Конец"
              type="date"
              className="flex-1 bg-transparent border-b border-white/10 py-1"
              value={endsOn}
              onChange={(event) => setEndsOn(event.target.value)}
              required
            />
          </div>

          {formError && <p className="text-sm text-rose-500">{formError}</p>}

          <button type="submit" className="text-sm text-lime" disabled={saving}>
            {saving ? 'Сохраняю…' : 'Завести'}
          </button>
        </form>
      )}
    </section>
  );
}
