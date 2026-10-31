// [review:need-review] PHASE-03/264
// summary: tests for the journal form of /journal — a new entry is dated by the server's day (GET /day-mode), not the browser's calendar; an entry being edited keeps its own date

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
// A namespace read at call time, as the screens read it: suites that mock `@/lib/api` before this one replace its objects.
import * as api from '@/lib/api';
import type { DayMode, JournalEntry } from '@/lib/api';
import { replaceMethod } from '@/test-fixtures/replace-method';
import JournalPage from './page';

// A day no browser clock in this run is on: any read of the browser's calendar shows in the field.
const SERVER_DAY = '2031-03-05';
const OLD_DAY = '2030-12-24';

const OLD_ENTRY = {
  id: 4,
  title: 'Christmas Eve',
  content: 'quiet',
  entry_date: OLD_DAY,
  mood: null,
  tags: null,
} as unknown as JournalEntry;

const restores: (() => void)[] = [];
let listed: JournalEntry[];

beforeEach(() => {
  listed = [];
  restores.push(
    replaceMethod(api.journalAPI, 'getAll', mock(() => Promise.resolve({ items: listed, total: listed.length }))),
    replaceMethod(api.agentAPI, 'dayMode', mock(() => Promise.resolve({ date: SERVER_DAY } as DayMode)))
  );
});

afterEach(() => {
  cleanup();
  for (const restore of restores.splice(0)) restore();
});

const dateField = () => document.querySelector('input[type="date"]') as HTMLInputElement;

describe('the date of a journal entry on /journal', () => {
  it('dates a new entry by the server day', async () => {
    render(<JournalPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Write first entry' }));

    await waitFor(() => expect(dateField().value).toBe(SERVER_DAY));
  });

  it('keeps the date the reader picked when the server day arrives later', async () => {
    render(<JournalPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Write first entry' }));
    await waitFor(() => expect(dateField().value).toBe(SERVER_DAY));

    fireEvent.change(dateField(), { target: { value: OLD_DAY } });

    expect(dateField().value).toBe(OLD_DAY);
  });

  it('keeps the own date of an entry being edited', async () => {
    listed = [OLD_ENTRY];
    render(<JournalPage />);
    await screen.findByText('Christmas Eve');
    fireEvent.click(screen.getByRole('button', { name: 'Edit journal entry' }));

    await waitFor(() => expect(dateField().value).toBe(OLD_DAY));
  });
});
