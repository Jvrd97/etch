'use client';
// [review:need-review] PHASE-03/120
// summary: the thought of the model as a collapsed line that says what it is busy with right now and expands to the words behind it — folded shut by itself the moment the answer starts, and never merged into the answer's own text

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import {
  activityLabel,
  hasProgress,
  thinkingVolume,
  THINKING_WORDLESS,
  type TurnProgress,
} from '@/lib/chat-progress';

export const THINKING_TESTID = 'thinking-block';
export const THINKING_TOGGLE_TESTID = 'thinking-toggle';
export const THINKING_WORDS_TESTID = 'thinking-words';

export interface ThinkingBlockProps {
  progress: TurnProgress;
  /** True, как только пошёл видимый ответ: блок сворачивается сам. */
  answering: boolean;
}

/**
 * Ход мысли рядом с ответом, а не вместо него.
 *
 * Свёрнут по умолчанию и тише ответа во всём — мельче кегль, приглушённый цвет,
 * отбивка слева вместо пузыря. Это сознательная иерархия: мысль объясняет паузу,
 * читать её никто не обязан, и раскрытый по умолчанию блок отодвигал бы ответ
 * вниз ровно тогда, когда его ждут.
 *
 * Свёрнутая строка отвечает на «чем оно занято сейчас», а не «сколько шагов
 * было»: человек смотрит на неё в ожидании, и счётчик шагов в этот момент не
 * говорит ему ничего.
 *
 * Когда ответ пошёл, блок закрывается сам — один раз. Дальше он подчиняется
 * человеку: открыл посреди ответа — значит, читает, и захлопывать блок под
 * пальцем на следующем куске текста нельзя.
 */
export default function ThinkingBlock({ progress, answering }: ThinkingBlockProps) {
  const [open, setOpen] = useState(false);
  // Сворачивание на переходе «ответа не было — ответ пошёл», правкой состояния
  // прямо в рендере: это тот самый способ отреагировать на смену входа, который
  // React предлагает вместо эффекта. Эффект здесь дорисовал бы кадр с раскрытым
  // блоком и захлопнул его следующим — то есть моргнул бы ровно в тот момент,
  // когда человек начал читать ответ.
  const [wasAnswering, setWasAnswering] = useState(answering);
  if (wasAnswering !== answering) {
    setWasAnswering(answering);
    if (answering) setOpen(false);
  }

  if (!hasProgress(progress)) return null;

  const volume = thinkingVolume(progress);

  return (
    <div className="mb-2" data-testid={THINKING_TESTID}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        data-testid={THINKING_TOGGLE_TESTID}
        className="inline-flex items-center gap-1.5 text-left text-[11px] text-text-disabled transition-colors hover:text-text-secondary"
      >
        {open ? (
          <ChevronDown className="w-3 h-3 shrink-0" strokeWidth={2} />
        ) : (
          <ChevronRight className="w-3 h-3 shrink-0" strokeWidth={2} />
        )}
        <span>{activityLabel(progress)}</span>
        {volume !== null && <span>· {volume}</span>}
      </button>

      {open && (
        <div
          data-testid={THINKING_WORDS_TESTID}
          className="mt-1.5 border-l border-white/10 pl-3 text-[11px] leading-relaxed text-text-disabled whitespace-pre-wrap break-words"
        >
          {/* Слов может не быть вовсе: на подписке CLI подменяет рассуждение
              подписью. Пустое раскрытие читалось бы как поломка, поэтому здесь
              стоит фраза, а не пустота. */}
          {progress.thinking.length > 0 ? progress.thinking : THINKING_WORDLESS}
        </div>
      )}
    </div>
  );
}
