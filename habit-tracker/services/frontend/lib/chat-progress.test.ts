// [review:need-review] PHASE-03/120
// summary: tests for the turn's progress state — the thought accumulating in its own field and never in the answer, the label that names the current activity, the volume shown as an estimate, and the identity kept on events that change nothing so a delta storm does not repaint the collapsed line

import { describe, expect, it } from 'bun:test';
import {
  activityLabel,
  applyProgress,
  hasProgress,
  NO_PROGRESS,
  THINKING_LABEL,
  THINKING_WORDLESS,
  thinkingVolume,
  TOOL_LABELS,
  UNNAMED_TOOL_LABEL,
  WRITING_LABEL,
  type TurnProgress,
} from './chat-progress';
import type { ChatStreamEvent } from './chat-stream';

/** Сложить ход из последовательности событий, как это делает экран. */
function fold(events: ChatStreamEvent[]): TurnProgress {
  return events.reduce(applyProgress, NO_PROGRESS);
}

describe('applyProgress: чем модель занята', () => {
  it('ничего не показывает, пока бэкенд не назвал ни одного шага', () => {
    expect(hasProgress(NO_PROGRESS)).toBe(false);
    expect(hasProgress(fold([{ kind: 'delta', text: 'ответ' }]))).toBe(false);
  });

  it('называет мысль мыслью, как только она началась', () => {
    const progress = fold([
      { kind: 'thinking', index: 0, thinking: '', thinkingTokens: null },
    ]);

    expect(hasProgress(progress)).toBe(true);
    expect(activityLabel(progress)).toBe(THINKING_LABEL);
  });

  it('копит слова мысли в своём поле и не трогает ответ', () => {
    const progress = fold([
      { kind: 'thinking', index: 0, thinking: 'он спрашивает ', thinkingTokens: null },
      { kind: 'delta', text: 'Сон' },
      { kind: 'thinking', index: 0, thinking: 'про сон', thinkingTokens: 96 },
    ]);

    expect(progress.thinking).toBe('он спрашивает про сон');
    expect(progress.thinkingTokens).toBe(96);
  });

  it('переключается на ответ, когда пошёл видимый текст', () => {
    const progress = fold([
      { kind: 'thinking', index: 0, thinking: '', thinkingTokens: null },
      { kind: 'writing', index: 1 },
    ]);

    expect(activityLabel(progress)).toBe(WRITING_LABEL);
  });

  it('держит подпись между двумя блоками, а не гасит её', () => {
    // `step_end` — «блок закрылся», а не «модель ничем не занята»: подпись,
    // мигающая в пустоту на миллисекунды, читается хуже, чем стоящая.
    const progress = fold([
      { kind: 'thinking', index: 0, thinking: '', thinkingTokens: null },
      { kind: 'stepEnd', index: 0 },
    ]);

    expect(activityLabel(progress)).toBe(THINKING_LABEL);
  });

  it('называет выборку тем, что она достаёт', () => {
    const progress = fold([
      {
        kind: 'retrieval',
        queryName: 'day_card',
        rowCount: 1,
        chars: 620,
        refusal: null,
      },
    ]);

    expect(activityLabel(progress)).toBe('читает: карточка дня');
  });

  it('называет инструмент по-русски, а незнакомый — как есть', () => {
    expect(activityLabel(fold([{ kind: 'acting', index: 1, tool: 'Grep' }]))).toBe(
      TOOL_LABELS.Grep
    );
    expect(activityLabel(fold([{ kind: 'acting', index: 1, tool: 'Task' }]))).toBe(
      'работает: Task'
    );
    expect(activityLabel(fold([{ kind: 'acting', index: 1, tool: null }]))).toBe(
      UNNAMED_TOOL_LABEL
    );
  });

  it('забирает оценку объёма из остановки, когда её не было раньше', () => {
    const progress = fold([
      { kind: 'thinking', index: 0, thinking: '', thinkingTokens: null },
      { kind: 'stop', reason: 'end_turn', thinkingTokens: 1200 },
    ]);

    expect(thinkingVolume(progress)).toBe('~1 200 токенов мысли');
  });

  it('молчит об объёме, которого никто не измерял', () => {
    expect(thinkingVolume(NO_PROGRESS)).toBeNull();
  });

  it('возвращает тот же объект на событии, которое ничего не меняет', () => {
    // Иначе каждый кусок ответа — десятки в секунду — перерисовывал бы
    // свёрнутую строку впустую.
    const before = fold([{ kind: 'thinking', index: 0, thinking: 'мысль', thinkingTokens: 5 }]);

    expect(applyProgress(before, { kind: 'delta', text: 'ок' })).toBe(before);
    expect(applyProgress(before, { kind: 'stepEnd', index: 0 })).toBe(before);
    expect(applyProgress(before, { kind: 'done', messageId: 1, seq: 2, status: 'complete' })).toBe(
      before
    );
    expect(applyProgress(before, { kind: 'stop', reason: 'end_turn', thinkingTokens: null })).toBe(
      before
    );
  });

  it('объясняет пустое раскрытие фразой, а не пустотой', () => {
    // На подписке слов мысли не приходит вовсе. Пустой раскрытый блок читался
    // бы как поломка экрана.
    expect(THINKING_WORDLESS.length).toBeGreaterThan(0);
  });
});
