'use client';
// [review:need-review] PHASE-03/138
// summary: the role summary block both the week page and /roles draw — a row per role with minutes, share, target labelled a hypothesis and the signed gap, `unassigned` on a row of its own with the 30% signal spelled out, the acts counted by kind, and the finished Friday-report text with one copy button

import { useState } from 'react';
import { Copy } from 'lucide-react';
import type { RoleSummary } from '@/lib/api';
import {
  COPY_DONE,
  COPY_FAILED,
  COPY_LABEL,
  EMPTY_SUMMARY,
  REPORT_TITLE,
  SUMMARY_TITLE,
  TARGET_HYPOTHESIS,
  UNASSIGNED_TITLE,
  actsText,
  copyReport,
  deltaText,
  summaryMinutes,
  targetText,
  unassignedNote,
  workingRoles,
} from '@/lib/role-share';

/**
 * Сводка ролей за период — место, где минуты наконец работают.
 *
 * В дневном вердикте их нет намеренно: доля дня шумит и провоцирует подгонять
 * разметку. Неделя — правильный масштаб: сорок минут архитектуры из сорока
 * часов видно только на ней, и именно этот перекос всё и затевалось
 * обнаруживать.
 *
 * Целевая доля подписана гипотезой рядом с числом, а не в сноске внизу: она
 * меняется от квартала к кварталу, и экран, называющий её нормой, врёт про её
 * природу.
 *
 * `unassigned` стоит строкой наравне с ролями, а не в «прочем». Это
 * единственный признак того, что правила разметки отстали: неверное правило
 * разложит месяц неправильно и само сигнала не подаст.
 *
 * Готовый текст отчёта приезжает с сервера полем `markdown` и показывается как
 * есть. Собирать его здесь значило бы завести второе форматирование, которое
 * разойдётся с первым на первой же правке целевых долей.
 */

export interface RoleWeekSummaryProps {
  summary: RoleSummary;
  /** Заголовок блока; страница недели подписывает его своим периодом. */
  title?: string;
}

export default function RoleWeekSummary({
  summary,
  title = SUMMARY_TITLE,
}: RoleWeekSummaryProps) {
  const [copied, setCopied] = useState<'idle' | 'done' | 'failed'>('idle');

  const copy = async () => {
    setCopied((await copyReport(summary.markdown)) ? 'done' : 'failed');
  };

  return (
    <section className="bg-card border border-white/5 rounded-3xl p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-lg text-text-primary">{title}</h2>
        <span className="text-sm text-text-secondary">
          {summary.date_from} — {summary.date_to}
        </span>
      </div>

      {summary.total_minutes === 0 ? (
        <p className="mt-4 text-text-secondary" data-testid="summary-empty">
          {EMPTY_SUMMARY}
        </p>
      ) : (
        <>
          <ul className="mt-4 space-y-3" data-testid="summary-roles">
            {workingRoles(summary).map((slice) => {
              const delta = deltaText(slice);
              const acts = actsText(slice);
              return (
                <li key={slice.role_id}>
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-text-primary">{slice.title}</span>
                    <span className="text-text-secondary text-sm">
                      {summaryMinutes(slice.minutes)} · {slice.share_pct}%
                      {' · цель '}
                      {targetText(slice)}
                      {delta !== null && ` · ${delta}`}
                    </span>
                  </div>
                  {acts !== '' && (
                    <p className="mt-0.5 text-xs text-text-disabled">
                      акты: {slice.act_total} — {acts}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>

          <p className="mt-2 text-xs text-text-disabled" data-testid="target-note">
            {TARGET_HYPOTHESIS}
          </p>

          {/* Строка неотнесённой работы: своя, но наравне с ролями, а не в
              «прочем» — спрятанная, она перестаёт быть сигналом. */}
          <div
            className={`mt-4 rounded-2xl px-4 py-3 ${
              summary.rules_lag ? 'bg-surface border border-warning/40' : 'bg-surface'
            }`}
            data-testid="summary-unassigned"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-text-primary">{UNASSIGNED_TITLE}</span>
              <span className="text-text-secondary text-sm">
                {summaryMinutes(summary.unassigned_minutes)} ·{' '}
                {summary.unassigned_share_pct}%
              </span>
            </div>
            <p
              className={`mt-1 text-xs ${
                summary.rules_lag ? 'text-warning' : 'text-text-disabled'
              }`}
              data-testid="unassigned-note"
            >
              {unassignedNote(summary)}
            </p>
          </div>

          <div className="mt-5 pt-5 border-t border-white/5">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <p className="text-sm text-text-secondary">{REPORT_TITLE}</p>
              <button
                type="button"
                onClick={() => void copy()}
                data-testid="copy-report"
                className="inline-flex items-center gap-1.5 text-sm text-lime"
              >
                <Copy className="w-3.5 h-3.5" strokeWidth={2} />
                {copied === 'done'
                  ? COPY_DONE
                  : copied === 'failed'
                    ? COPY_FAILED
                    : COPY_LABEL}
              </button>
            </div>
            <pre
              data-testid="report-markdown"
              className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-text-secondary"
            >
              {summary.markdown}
            </pre>
          </div>
        </>
      )}
    </section>
  );
}
