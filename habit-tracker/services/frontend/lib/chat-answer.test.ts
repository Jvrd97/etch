// [review:need-review] PHASE-03/189
// summary: tests for visibleAnswer — the blocks a model addresses to the server (`need`, `plan`) are dropped from what the bubble shows, fenced or bare, while ordinary prose, ordinary code blocks and a brace inside a plan string survive untouched

import { describe, expect, it } from 'bun:test';

import { carriesPlan, visibleAnswer } from './chat-answer';

const PLAN = {
  plan: {
    entry_date: '2026-09-01',
    journal: { op: 'write_journal', content: 'день прошёл' },
  },
};

describe('visibleAnswer', () => {
  it('drops a fenced plan block and keeps the words around it', () => {
    const content = `Записал бы так.\n\n\`\`\`json\n${JSON.stringify(PLAN)}\n\`\`\``;
    expect(visibleAnswer(content)).toBe('Записал бы так.');
  });

  it('drops a fenced need block', () => {
    const need = { need: [{ query: 'inbox_tasks', params: { state: 'new' } }] };
    const content = `Сейчас посмотрю.\n\n\`\`\`json\n${JSON.stringify(need)}\n\`\`\`\n\nНовых задач нет.`;
    expect(visibleAnswer(content)).toBe('Сейчас посмотрю.\n\nНовых задач нет.');
  });

  it('drops a bare block the model forgot to fence', () => {
    expect(visibleAnswer(`Готово.\n\n${JSON.stringify(PLAN)}`)).toBe('Готово.');
  });

  it('leaves an ordinary answer exactly as it was', () => {
    const content = 'Плана на этот день нет. Собрать?';
    expect(visibleAnswer(content)).toBe(content);
  });

  it('leaves a code block that is not addressed to the server', () => {
    const content = 'Вот пример:\n\n```python\nprint({"a": 1})\n```';
    expect(visibleAnswer(content)).toBe(content);
  });

  it('is not fooled by a brace inside a line of the plan', () => {
    const withBrace = {
      plan: {
        entry_date: '2026-09-01',
        journal: { op: 'write_journal', content: 'дочитал главу про {} в JSON' },
      },
    };
    const content = `Записал.\n\n\`\`\`json\n${JSON.stringify(withBrace)}\n\`\`\``;
    expect(visibleAnswer(content)).toBe('Записал.');
  });

  it('gives back an empty string when the answer was nothing but a block', () => {
    expect(visibleAnswer(`\`\`\`json\n${JSON.stringify(PLAN)}\n\`\`\``)).toBe('');
  });

});

describe('carriesPlan', () => {
  it('sees a plan the server ended up refusing', () => {
    /*
     * Отвергнутый план не оставляет ни плашки, ни следа: блок вырезан из показа,
     * а строки в `chat_plans` нет. Человек читает «вот план на сегодня» и
     * пустоту под ним. Признак «блок был» — единственное, чем экран может
     * отличить это от ответа, который ничего не предлагал.
     */
    const content = `Вот план.\n\n\`\`\`json\n${JSON.stringify(PLAN)}\n\`\`\``;

    expect(carriesPlan(content)).toBe(true);
  });

  it('does not see one in an ordinary answer', () => {
    expect(carriesPlan('Плана на этот день нет. Собрать?')).toBe(false);
  });

  it('does not mistake a retrieval for a plan', () => {
    const need = { need: [{ query: 'inbox_tasks' }] };
    expect(carriesPlan(`Смотрю.\n\n${JSON.stringify(need)}`)).toBe(false);
  });
});
