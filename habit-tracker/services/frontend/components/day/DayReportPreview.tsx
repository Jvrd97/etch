'use client';
// [review:need-review] PHASE-03/145
// summary: панель предпросмотра отчёта дня — свёрнута по умолчанию, разворачивается перед сборкой плана, показывает текст ревизии, переключатель ревизий и строку каждого источника с объяснением, почему он пуст

import { useCallback, useEffect, useState } from 'react';
import Markdown from '@/components/Markdown';
import { dayAPI, type DayReport } from '@/lib/api';

export const REPORT_TITLE = 'Отчёт дня';
export const REPORT_HINT =
  'На этом будет построен план на завтра. Разверните, прежде чем нажимать кнопку.';
export const REPORT_EXPAND = 'Развернуть';
export const REPORT_COLLAPSE = 'Свернуть';
export const REPORT_BUILD = 'Пересобрать отчёт';
export const REPORT_BUILDING = 'Собираю…';
export const REPORT_NONE = 'Отчёт этого дня ещё не собирали.';
export const REPORT_FAILED = 'Отчёт не собрался';
export const SOURCES_TITLE = 'Источники';
export const REVISION_LABEL = 'Ревизия';

/** Русское имя источника. Сервер шлёт ключ, экран переводит — как и везде. */
const SOURCE_LABEL: Record<string, string> = {
  marks: 'отметки',
  notes: 'заметки «как прошло»',
  notebook: 'блокнот дня',
  training: 'тренировка',
  signals: 'сигналы',
};

export function sourceLabel(key: string): string {
  return SOURCE_LABEL[key] ?? key;
}

/** Ошибка «отчёта нет»: 404 на чтении, отличённый по полю, а не по классу. */
export function notFound(cause: unknown): boolean {
  return (
    typeof cause === 'object' &&
    cause !== null &&
    'status' in cause &&
    (cause as { status: unknown }).status === 404
  );
}

export interface DayReportPreviewProps {
  date: string;
  /** Раскрыта ли панель при первом рендере; в жизни — нет, в тестах бывает да. */
  initiallyOpen?: boolean;
  compact?: boolean;
}

/**
 * Предпросмотр отчёта дня — того самого, из которого вырастет завтрашний план.
 *
 * Свёрнута по умолчанию, потому что это не то, что читают каждый раз, открывая
 * день. Но до `#145` этого нельзя было увидеть вообще: отчёт собирался в момент
 * нажатия кнопки и исчезал в файле. Панель отвечает на вопрос «на чём именно
 * будет построен завтрашний день» до нажатия, а не после.
 *
 * Читает сама, а не получает пропом: отчёт — не часть дня, он пересобирается
 * своей кнопкой и живёт своими ревизиями, и тащить его через весь экран дня
 * значило бы перерисовывать день на каждую пересборку.
 */
export default function DayReportPreview({
  date,
  initiallyOpen = false,
  compact = false,
}: DayReportPreviewProps) {
  const [open, setOpen] = useState(initiallyOpen);
  const [report, setReport] = useState<DayReport | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (revision?: number) => {
      setError(null);
      try {
        const loaded = await dayAPI.getReport(date, revision);
        setReport(loaded);
        setMissing(false);
      } catch (cause) {
        // 404 — «не собирали», а не поломка: под него рисуется кнопка сборки.
        // Статус читается с самой ошибки, а не через `instanceof APIError`:
        // 26 тест-файлов подменяют весь модуль `@/lib/api`, и подмена без
        // класса ломала бы импорт этого компонента ещё до первого рендера.
        if (notFound(cause)) {
          setReport(null);
          setMissing(true);
          return;
        }
        setError(cause instanceof Error ? cause.message : REPORT_FAILED);
      }
    },
    [date]
  );

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open, load]);

  const rebuild = async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await dayAPI.buildReport(date, 'button'));
      setMissing(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : REPORT_FAILED);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="bg-card border border-white/5 rounded-3xl p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          className={`${compact ? 'text-lg' : 'text-xl'} font-semibold text-text-primary`}
        >
          {REPORT_TITLE}
        </h2>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="text-sm text-lime hover:underline"
        >
          {open ? REPORT_COLLAPSE : REPORT_EXPAND}
        </button>
      </div>
      <p className="mt-2 text-sm text-text-secondary">{REPORT_HINT}</p>

      {open && (
        <div className="mt-5 pt-5 border-t border-white/5 space-y-4">
          {error !== null && <p className="text-sm text-red-400">{error}</p>}
          {missing && <p className="text-sm text-text-secondary">{REPORT_NONE}</p>}

          {report !== null && report.revisions.length > 1 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-text-secondary">{REVISION_LABEL}</span>
              {report.revisions.map((one) => (
                <button
                  key={one}
                  type="button"
                  onClick={() => void load(one)}
                  aria-pressed={one === report.revision}
                  className={`px-3 py-1 rounded-full text-sm ${
                    one === report.revision
                      ? 'bg-lime text-background'
                      : 'bg-surface text-text-secondary hover:text-text-primary'
                  }`}
                >
                  {one}
                </button>
              ))}
            </div>
          )}

          {report !== null && (
            <>
              <div className="text-text-primary space-y-2">
                <Markdown content={report.content_md} />
              </div>
              <div>
                <p className="text-sm text-text-secondary">{SOURCES_TITLE}</p>
                <ul className="mt-2 space-y-1">
                  {Object.entries(report.sources).map(([key, source]) => (
                    <li key={key} className="text-sm text-text-secondary">
                      <span className="text-text-primary">{sourceLabel(key)}</span>:{' '}
                      {source.count}
                      {source.note !== '' && ` — ${source.note}`}
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}

          <button
            type="button"
            disabled={busy}
            onClick={() => void rebuild()}
            className="rounded-2xl bg-surface px-4 py-2 text-text-primary disabled:opacity-50"
          >
            {busy ? REPORT_BUILDING : REPORT_BUILD}
          </button>
        </div>
      )}
    </section>
  );
}
