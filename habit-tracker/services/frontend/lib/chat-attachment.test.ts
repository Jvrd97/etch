// [review:need-review] PHASE-03/193
// summary: tests for attachToDraft — a text file lands as a labelled block after what was already typed, a binary is refused by name, an empty file is refused as nothing to send, and a file that would not fit the message ceiling is refused with the numbers said out loud

import { describe, expect, it } from 'bun:test';

import { MESSAGE_MAX_CHARS, attachToDraft, isTextFile } from './chat-attachment';

describe('isTextFile', () => {
  it('takes the extensions a day is described in', () => {
    for (const name of ['notes.md', 'log.txt', 'week.csv', 'plan.json', 'run.log']) {
      expect(isTextFile(name, '')).toBe(true);
    }
  });

  it('takes anything the browser itself calls text', () => {
    expect(isTextFile('README', 'text/plain')).toBe(true);
  });

  it('refuses what it cannot read as words', () => {
    for (const name of ['photo.png', 'report.pdf', 'archive.zip']) {
      expect(isTextFile(name, 'application/octet-stream')).toBe(false);
    }
  });
});

describe('attachToDraft', () => {
  it('puts the file under what was already typed', () => {
    const outcome = attachToDraft('разбери это', 'notes.md', 'первая строка');

    expect(outcome.status).toBe('ok');
    if (outcome.status !== 'ok') return;
    expect(outcome.draft.startsWith('разбери это')).toBe(true);
    expect(outcome.draft).toContain('notes.md');
    expect(outcome.draft).toContain('первая строка');
  });

  it('works on an empty field too', () => {
    const outcome = attachToDraft('', 'notes.md', 'первая строка');

    expect(outcome.status).toBe('ok');
    if (outcome.status !== 'ok') return;
    expect(outcome.draft.startsWith('---')).toBe(true);
  });

  it('refuses a file with nothing in it', () => {
    // Пустой файл — это не вложение, а промах мимо кнопки.
    expect(attachToDraft('', 'empty.md', '   ').status).toBe('refused');
  });

  it('refuses a file that would not fit and says by how much', () => {
    const huge = 'я'.repeat(MESSAGE_MAX_CHARS + 1);

    const outcome = attachToDraft('', 'huge.log', huge);

    expect(outcome.status).toBe('refused');
    if (outcome.status !== 'refused') return;
    expect(outcome.reason).toContain(String(MESSAGE_MAX_CHARS));
  });

  it('counts what is already typed against the ceiling', () => {
    /*
     * Потолок у реплики, а не у файла: почти полное поле плюс маленький файл
     * упираются в него так же, как пустое поле плюс огромный. Считать только
     * файл значило бы отдать серверу отказ, которого экран мог избежать.
     */
    const typed = 'я'.repeat(MESSAGE_MAX_CHARS - 10);

    expect(attachToDraft(typed, 'small.md', 'ещё сто знаков').status).toBe('refused');
  });
});
