/**
 * API Client for Habit Tracker Backend
 */
// [review:need-review] PHASE-01/73-dashboard-hero-today-ring, PHASE-03/86, PHASE-03/90, PHASE-03/91, PHASE-03/93, PHASE-03/111, PHASE-03/152
// summary: entriesAPI.getAll takes the backend's `sort` — `created_at_desc` plus a limit fetches the last written entry without pulling the history; dayAPI reads one day with the rule it is judged by, its plan, its marks and its итог, and writes back a whole plan, a single mark, the day's notebook or the close that judges the day, and reads and edits the work intervals a day's measured time is made of; goalsAPI reads the goal board and moves one milestone; chatAPI keeps the conversation feed and streams one turn through fetch + ReadableStream instead of waiting for a whole body; dayRulesAPI reads every version of the day canon and publishes the next one, and has no way to edit one that exists

import { ChatStreamParser, type ChatStreamEvent } from '@/lib/chat-stream';

// Relative by default: requests go to the same origin that served the page and
// are proxied to the backend by the Next rewrite (see next.config.ts). Keeps the
// app reachable from any device on the LAN without host-specific config.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

class APIError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'APIError';
  }
}

async function fetcher<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'An error occurred' }));
    throw new APIError(response.status, error.detail || 'An error occurred');
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

// Categories API
export const categoriesAPI = {
  getAll: async (activeOnly = true) => {
    return fetcher<Category[]>(`/categories?active_only=${activeOnly}`);
  },

  getById: async (id: number) => {
    return fetcher<Category>(`/categories/${id}`);
  },

  create: async (data: CategoryCreate) => {
    return fetcher<Category>('/categories', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  update: async (id: number, data: Partial<CategoryCreate>) => {
    return fetcher<Category>(`/categories/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  delete: async (id: number) => {
    return fetcher<void>(`/categories/${id}`, {
      method: 'DELETE',
    });
  },

  getStreak: async (id: number) => {
    return fetcher<CategoryStreak>(`/categories/${id}/streak`);
  },

  addField: async (categoryId: number, field: FieldCreate) => {
    return fetcher<Field>(`/categories/${categoryId}/fields`, {
      method: 'POST',
      body: JSON.stringify(field),
    });
  },

  // Apply an additive-only plan transactionally: every op lands in one commit
  // or none do. Used by onboarding to turn a preview into real categories.
  applyBatch: async (operations: PlanOperation[]) => {
    return fetcher<CategoryBatchResponse>('/categories/batch', {
      method: 'POST',
      body: JSON.stringify({ operations }),
    });
  },
};

/**
 * Ordering of `GET /entries`.
 *
 * `entry_date_desc` answers "what happened later" and is the backend default,
 * so omitting the parameter keeps every existing call unchanged.
 * `created_at_desc` answers "what was written last" — the only way to ask for
 * the most recent record without reading the whole list to find it.
 */
export type EntrySort = 'entry_date_desc' | 'created_at_desc';

// Entries API
export const entriesAPI = {
  getAll: async (params?: {
    categoryId?: number;
    startDate?: string;
    endDate?: string;
    skip?: number;
    limit?: number;
    sort?: EntrySort;
  }) => {
    const query = new URLSearchParams();
    if (params?.categoryId) query.append('category_id', params.categoryId.toString());
    if (params?.startDate) query.append('start_date', params.startDate);
    if (params?.endDate) query.append('end_date', params.endDate);
    if (params?.skip) query.append('skip', params.skip.toString());
    if (params?.limit) query.append('limit', params.limit.toString());
    if (params?.sort) query.append('sort', params.sort);

    return fetcher<Entry[]>(`/entries?${query.toString()}`);
  },

  getById: async (id: number) => {
    return fetcher<Entry>(`/entries/${id}`);
  },

  create: async (data: EntryCreate) => {
    return fetcher<Entry>('/entries', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  update: async (id: number, data: Partial<EntryCreate>) => {
    return fetcher<Entry>(`/entries/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  delete: async (id: number) => {
    return fetcher<void>(`/entries/${id}`, {
      method: 'DELETE',
    });
  },

  upsertChecklist: async (data: ChecklistUpsert) => {
    return fetcher<Entry>('/entries/checklist', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  getByDateRange: async (categoryId: number, startDate: string, endDate: string) => {
    return fetcher<Entry[]>(
      `/entries/category/${categoryId}/range?start_date=${startDate}&end_date=${endDate}`
    );
  },
};

// Table API
export const tableAPI = {
  get: async (dateFrom: string, dateTo: string) => {
    return fetcher<TableResponse>(
      `/table?date_from=${dateFrom}&date_to=${dateTo}`
    );
  },
};

// Insights API
export const insightsAPI = {
  create: async (periodDays?: number) => {
    return fetcher<AIReport>('/insights', {
      method: 'POST',
      body: JSON.stringify(periodDays !== undefined ? { period_days: periodDays } : {}),
    });
  },

  getAll: async () => {
    return fetcher<AIReportListItem[]>('/insights');
  },

  getById: async (id: number) => {
    return fetcher<AIReport>(`/insights/${id}`);
  },
};

// Onboarding API
export const onboardingAPI = {
  draft: async (transcript: string) => {
    return fetcher<OnboardingPlan>('/onboarding/draft', {
      method: 'POST',
      body: JSON.stringify({ transcript }),
    });
  },
};

// Daily summary API: a day told in text becomes a plan of numeric records, and
// the checked part of that plan is written in one transaction.
export const dailySummaryAPI = {
  draft: async (transcript: string, entryDate: string) => {
    return fetcher<DailySummaryPlan>('/daily-summary/draft', {
      method: 'POST',
      body: JSON.stringify({ transcript, entry_date: entryDate }),
    });
  },

  /**
   * Write the day in one transaction.
   *
   * `idempotencyKey` is what makes a second click harmless: the server
   * recognises the replay, answers with the first result and writes nothing —
   * neither second entries nor a second copy of the text appended to itself.
   * It is required rather than optional precisely because forgetting it is
   * silent: the call still succeeds, and the day quietly doubles.
   */
  apply: async (
    entryDate: string,
    metrics: LogMetricOp[],
    checklist: CheckOp[],
    journal: JournalOp | null,
    idempotencyKey: string
  ) => {
    return fetcher<DailySummaryApplyResponse>('/daily-summary/apply', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ entry_date: entryDate, metrics, checklist, journal }),
    });
  },
};

// Journal API
export const journalAPI = {
  getAll: async (params?: {
    startDate?: string;
    endDate?: string;
    mood?: string;
    search?: string;
    skip?: number;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.startDate) query.append('start_date', params.startDate);
    if (params?.endDate) query.append('end_date', params.endDate);
    if (params?.mood) query.append('mood', params.mood);
    if (params?.search) query.append('search', params.search);
    if (params?.skip) query.append('skip', params.skip.toString());
    if (params?.limit) query.append('limit', params.limit.toString());

    return fetcher<JournalListResponse>(`/journal?${query.toString()}`);
  },

  getById: async (id: number) => {
    return fetcher<JournalEntry>(`/journal/${id}`);
  },

  create: async (data: JournalEntryCreate) => {
    return fetcher<JournalEntry>('/journal', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  update: async (id: number, data: Partial<JournalEntryCreate>) => {
    return fetcher<JournalEntry>(`/journal/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  delete: async (id: number) => {
    return fetcher<void>(`/journal/${id}`, {
      method: 'DELETE',
    });
  },

  getByDate: async (date: string) => {
    return fetcher<JournalEntry[]>(`/journal/date/${date}`);
  },
};

// Day API
export const dayAPI = {
  /**
   * Today, decided by the server's day boundary rather than the browser's
   * calendar: at 00:30 the day that is still running is yesterday's, and the
   * screen has to open the same day everything else writes into.
   */
  getToday: async () => {
    return fetcher<DayDetail>('/day');
  },

  get: async (date: string) => {
    return fetcher<DayDetail>(`/day/${date}`);
  },

  /**
   * The same two reads, but saying that a person is looking at the day.
   *
   * `opened=true` is what fills `day.opened_at`. It is a separate call rather
   * than the default because an agent, an import and a cron job also read days,
   * and if reading counted as opening, "не открывал" — one of the four kinds of
   * empty this screen has to tell apart — would stop being establishable.
   */
  openToday: async () => {
    return fetcher<DayDetail>('/day?opened=true');
  },

  open: async (date: string) => {
    return fetcher<DayDetail>(`/day/${date}?opened=true`);
  },

  /**
   * Send the whole plan of a day, replacing whatever was there.
   *
   * Whole rather than per-item: the bar on the number of tasks and "only the
   * edges of the day may be hard" are properties of a plan, and the server
   * cannot judge them one line at a time. A rejection comes back as a 422
   * whose body names the line that broke a rule.
   */
  savePlan: async (date: string, document: PlanDocument) => {
    return fetcher<Plan>(`/day/${date}/plan`, {
      method: 'POST',
      body: JSON.stringify(document),
    });
  },

  /**
   * Mark one item of the day, or take its mark off with `state: null`.
   *
   * The request names the state rather than asking for "the next one": two open
   * tabs would otherwise get a result that depends on which of them arrived
   * first. The cycle a click walks lives in `lib/marks.ts`.
   */
  setMark: async (date: string, itemId: string, draft: MarkDraft) => {
    return fetcher<Mark>(`/day/${date}/marks/${itemId}`, {
      method: 'PUT',
      body: JSON.stringify(draft),
    });
  },

  /**
   * The intervals of measured work of a day, and their sum.
   *
   * `work_minutes: null` is «не измерено», not zero: the day then skips the
   * overtime check instead of reading as comfortably short.
   */
  workIntervals: async (date: string) => {
    return fetcher<WorkDay>(`/day/${date}/work-intervals`);
  },

  /**
   * Add one interval. Manual entry is the first-class path, not the fallback:
   * `source` defaults to `manual` and an interval typed by hand is no lesser a
   * measurement than one the agent proposed.
   */
  addWorkInterval: async (date: string, draft: WorkIntervalDraft) => {
    return fetcher<WorkInterval>(`/day/${date}/work-intervals`, {
      method: 'POST',
      body: JSON.stringify(draft),
    });
  },

  /**
   * Edit one interval; the server keeps what the agent proposed beside it.
   *
   * Only the keys present move, so an edit of the note cannot reopen an
   * interval that finished hours ago.
   */
  updateWorkInterval: async (
    date: string,
    intervalId: string,
    patch: WorkIntervalPatch
  ) => {
    return fetcher<WorkInterval>(`/day/${date}/work-intervals/${intervalId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  },

  /** Remove one interval; deleting the last returns the day to «не измерено». */
  deleteWorkInterval: async (date: string, intervalId: string) => {
    return fetcher<void>(`/day/${date}/work-intervals/${intervalId}`, {
      method: 'DELETE',
    });
  },

  /** Replace the day's notebook text; it stays one entry per date. */
  saveNotebook: async (date: string, content: string) => {
    return fetcher<{ day_date: string; content: string; updated_at: string | null }>(
      `/day/${date}/notebook`,
      { method: 'PUT', body: JSON.stringify({ content }) }
    );
  },

  /**
   * Close the day: the server judges it and writes the итог.
   *
   * The whole day goes in one request — the minutes of work, the prose and the
   * override are read together or the verdict is wrong, and a field-at-a-time
   * API would leave a day half closed with nothing saying so.
   */
  close: async (date: string, draft: DayCloseDraft) => {
    return fetcher<DaySummary>(`/day/${date}/close`, {
      method: 'POST',
      body: JSON.stringify(draft),
    });
  },
};

// Day rules API: the canon of a day, versioned. There is no update and no
// delete here, and that is the contract rather than an omission — a rule row
// that has already judged days is never edited, only superseded from a date
// that has not happened yet.
export const dayRulesAPI = {
  /**
   * Every version, plus the earliest date a new one may start on.
   *
   * That date is the server's answer, not `new Date()`: the day turns at the
   * boundary hour written in the canon itself, so at 00:30 the browser's
   * «завтра» is still the server's «сегодня» — the one date publishing is not
   * allowed to start on.
   */
  getHistory: async () => {
    return fetcher<DayRuleSetHistory>('/day-rule-sets');
  },

  /** The version in force; 404 when the rule table has never been migrated. */
  getCurrent: async () => {
    return fetcher<DayRuleSet>('/day-rule-sets/current');
  },

  /**
   * Publish a new version from `valid_from` onwards.
   *
   * The server closes the version in force at that same date and inserts this
   * one, in a single transaction. Verdicts of days already lived are not
   * recomputed: each of them is judged by the rule that covered its date, and
   * that rule keeps its numbers.
   */
  publish: async (payload: DayRuleSetPublish) => {
    return fetcher<DayRuleSet>('/day-rule-sets', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
};

// Types
export type CategoryDisplayMode = 'form' | 'checklist';
export type CategoryStreakMode = 'build' | 'avoid';

export interface CategoryStreak {
  category_id: number;
  streak_mode: CategoryStreakMode;
  current_streak: number;
  best_streak: number;
  last_relapse_date: string | null;
}

export interface Category {
  id: number;
  name: string;
  description?: string;
  icon?: string;
  color?: string;
  display_mode: CategoryDisplayMode;
  streak_mode: CategoryStreakMode;
  group?: string | null;
  /**
   * Whether the category is on the Today screen. `null` (and, on rows written
   * before the column existed, absent) means "decide by the heuristic";
   * `true`/`false` is the user's own choice and overrides it.
   */
  show_in_today?: boolean | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  fields: Field[];
}

export interface CategoryCreate {
  name: string;
  description?: string;
  icon?: string;
  color?: string;
  display_mode?: CategoryDisplayMode;
  streak_mode?: CategoryStreakMode;
  group?: string | null;
  show_in_today?: boolean | null;
  is_active?: boolean;
  fields?: FieldCreate[];
}

export type FieldType =
  | 'text'
  | 'number'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'time'
  | 'select'
  | 'duration';

export interface Field {
  id: number;
  category_id: number;
  name: string;
  field_type: FieldType;
  is_required: boolean;
  options?: string;
  order: number;
  created_at: string;
  updated_at: string;
}

export interface FieldCreate {
  // Present only when editing an existing field: lets the backend diff-sync
  // fields by id (update in place, preserve history) instead of replacing them.
  id?: number;
  name: string;
  field_type: FieldType;
  is_required?: boolean;
  options?: string;
  order?: number;
}

export interface Entry {
  id: number;
  category_id: number;
  entry_date: string;
  notes?: string;
  created_at: string;
  updated_at: string;
  values: EntryValue[];
}

export interface EntryCreate {
  category_id: number;
  entry_date: string;
  notes?: string;
  values: EntryValueCreate[];
}

export interface EntryValue {
  id: number;
  entry_id: number;
  field_id: number;
  value: string;
  field?: Field;
}

export interface EntryValueCreate {
  field_id: number;
  value: string;
}

export interface ChecklistUpsert {
  category_id: number;
  entry_date: string;
  values: Record<number, boolean>;
}

export interface JournalEntry {
  id: number;
  title: string;
  content: string;
  entry_date: string;
  mood?: string;
  tags?: string;
  created_at: string;
  updated_at: string;
}

export interface JournalEntryCreate {
  title: string;
  content: string;
  entry_date: string;
  mood?: string;
  tags?: string;
}

export interface JournalListResponse {
  total: number;
  items: JournalEntry[];
}

// Onboarding: additive-only category plan (preview only, never persisted).
export interface PlanField {
  name: string;
  field_type: FieldType;
  is_required: boolean;
  options?: string | null;
  order: number;
}

export interface CreateCategoryOp {
  op: 'create_category';
  name: string;
  description?: string | null;
  icon?: string | null;
  color?: string | null;
  display_mode: CategoryDisplayMode;
  streak_mode: CategoryStreakMode;
  group?: string | null;
  fields: PlanField[];
  name_conflict: boolean;
}

export interface AddFieldOp {
  op: 'add_field';
  category_id: number;
  field: PlanField;
}

export type PlanOperation = CreateCategoryOp | AddFieldOp;

export interface OnboardingPlan {
  operations: PlanOperation[];
}

// Daily summary: a write-only plan for one day. There is no operation for
// deleting, renaming or retyping anything — the shape itself forbids it.
export interface LogMetricOp {
  op: 'log_metric';
  /** Resolution is by id alone; names never take part (see #57). */
  category_id: number;
  field_id: number;
  value: number;
  /** The wording the number was read from, shown next to its checkbox. */
  source_text: string;
  /** The model placed it without confidence — the row arrives unchecked. */
  uncertain: boolean;
  /** The number itself looks wrong — the row arrives unchecked. */
  implausible: boolean;
  /**
   * Nobody said this number: the model derived it from a description, which in
   * practice means a meal. "Отжался 30 раз" carries its own 30; "съел борщ"
   * carries a calorie count only if something estimates it.
   *
   * Not the doubt `uncertain` carries. That one is about where a number goes,
   * and an estimate can be confidently placed in Питание · Калории while still
   * being a guess about the portion — so an estimated row arrives checked, like
   * any confidently placed metric, and says on its face that it is an estimate.
   *
   * Optional on the wire while a frontend can outrun its backend: a draft from
   * before the flag existed reads as "the user said it", which is what every
   * metric written then actually was.
   */
  estimated?: boolean;
}

/**
 * One checklist box the plan proposes to tick.
 *
 * There is no value here, and that absence is the whole safety of the feature:
 * the checklist endpoint takes the day's full map, so a plan able to say
 * `false` would untick every box the retelling failed to mention. Silence is
 * "не сказал", never "не сделал" — so the word for unticking does not exist.
 */
export interface CheckOp {
  op: 'check';
  category_id: number;
  field_id: number;
  /** The wording the tick was read from, shown next to its checkbox. */
  source_text: string;
  /** The model was not confident the retelling meant this box — arrives unchecked. */
  uncertain: boolean;
}

/** Something numeric the model heard but could not place. Creates nothing. */
export interface UnresolvedMetric {
  text: string;
  reason?: string | null;
}

/**
 * How the day's text meets whatever the date already holds.
 *
 * `append` and `create` are the same intent — keep what is there — and differ
 * only in whether anything is there. `replace` is the one mode that loses text,
 * so the draft never proposes it: it exists because the user may ask for it.
 */
export type JournalMode = 'append' | 'create' | 'replace';

/** The day written out, plus what the backend found at that date. */
export interface JournalOp {
  op: 'write_journal';
  title: string | null;
  content: string;
  mood: string | null;
  tags: string | null;
  mode: JournalMode;
  /** The entry the text would join, when the day already has one. */
  existing_entry_id: number | null;
}

/**
 * The draft the backend produces from a retelling.
 *
 * `metrics` and `unresolved` are required because `POST /daily-summary/draft`
 * has always sent them: a response without either is a broken backend, not an
 * older one, and typing them optional would push a `?? []` into every reader
 * for a case that cannot happen.
 *
 * `checklist` and `journal` are optional only as deployment slack — each was
 * added by a later slice (#75 and #74), and a frontend that ships ahead of the
 * backend must read an old draft as "no boxes"/"no text" rather than crash the
 * preview. Dropping the `?` on both is issue #83
 * (`issues/PHASE-01/backlog/83-daily-summary-plan-fields-required.md`), which
 * unblocks once no backend older than #75 can answer this frontend — i.e. after
 * the next deploy in which backend and frontend go out together.
 */
export interface DailySummaryPlan {
  metrics: LogMetricOp[];
  /** Boxes the retelling ticked. Absent on an older backend; never a full map. */
  checklist?: CheckOp[];
  unresolved: UnresolvedMetric[];
  /** Null when the retelling held nothing worth reading back later. */
  journal?: JournalOp | null;
}

/** What an apply wrote: one entry per category the day touched, plus its text. */
export interface DailySummaryApplyResponse {
  entry_ids: number[];
  journal_entry_id?: number | null;
}

// What POST /categories/batch returns: the categories it created and the fields
// it appended to existing ones.
export interface CategoryBatchResponse {
  categories: Category[];
  fields: Field[];
}

export interface AIReport {
  id: number;
  period_days: number;
  content: string;
  model: string;
  created_at: string;
}

export interface AIReportListItem {
  id: number;
  period_days: number;
  model: string;
  created_at: string;
  preview: string;
}

export interface TableCategoryMeta {
  id: number;
  name: string;
  display_mode: CategoryDisplayMode;
  group: string | null;
  primary_field_id: number | null;
  primary_field_name: string | null;
  primary_field_type: string | null;
}

export interface TableCell {
  category_id: number;
  field_id: number;
  aggregated_value: string | null;
  entry_count: number;
}

export interface TableDay {
  date: string;
  cells: TableCell[];
}

export interface TableResponse {
  categories: TableCategoryMeta[];
  days: TableDay[];
}

/** Whether the day is a working one; frozen when the day was created. */
export type DayKind = 'work' | 'off';

/**
 * The canon a day is judged by, in force over an interval of dates.
 *
 * Versioned on the server: the ceiling and the task bar changed on 2026-08-17,
 * and a day from before that is read against the numbers it was lived under.
 */
export interface DayRuleSet {
  id: number;
  valid_from: string;
  /** First date the rule no longer applies; null while it is still in force. */
  valid_to: string | null;
  timezone: string;
  /** Local hour a day starts at — 4 means 00:30 still belongs to yesterday. */
  day_start_hour: number;
  work_cap_min: number;
  work_hard_cap_min: number;
  /** `HH:MM:SS` wall-clock time work stops at. */
  work_stop_at: string;
  max_work_tasks: number;
  /** Share of planned tasks that has to be closed, as a decimal string. */
  tasks_required_ratio: string;
  overtime_disqualifies: boolean;
  /** ISO weekday numbers, 1 = Monday. */
  workdays: number[];
  nocode_days: number[];
  required_anchors: string[];
  note_md: string;
}

/**
 * A new version of the canon, as the screen sends it.
 *
 * No `id` and no `valid_to`: the first would be an edit of a row and the second
 * a hole in the canon, and a date with no rule covering it has no verdict at
 * all. The end of an interval is written by the server, when the next version
 * closes it.
 */
export interface DayRuleSetPublish {
  /** First day lived under the new version; never today or earlier. */
  valid_from: string;
  timezone: string;
  day_start_hour: number;
  work_cap_min: number;
  work_hard_cap_min: number;
  /** `HH:MM:SS`. */
  work_stop_at: string;
  max_work_tasks: number;
  /** Decimal string, `1.00` for «закрыты все». */
  tasks_required_ratio: string;
  overtime_disqualifies: boolean;
  workdays: number[];
  nocode_days: number[];
  required_anchors: string[];
  note_md: string;
}

/** Every version of the canon, and what the screen needs to publish the next. */
export interface DayRuleSetHistory {
  /** Today by the day boundary of the rule in force, not by the browser's clock. */
  today: string;
  /** Earliest `valid_from` the server will accept — tomorrow. */
  earliest_valid_from: string;
  /** id of the version in force; null when the rule table is empty. */
  current_id: number | null;
  /** Oldest interval first. */
  rules: DayRuleSet[];
}

export interface Day {
  date: string;
  kind: DayKind;
  is_nocode: boolean;
  /** When the day was first opened; null when nobody ever came. */
  opened_at: string | null;
  last_touched_at: string | null;
}

/** What kind of line of a plan this is; only `task` counts against the bar. */
export type PlanItemKind =
  | 'bullet'
  | 'step'
  | 'table_row'
  | 'task'
  | 'anchor'
  | 'hard_point'
  | 'minimum';

/** How movable a line is. `free` items can carry no window at all. */
export type PlanRigidity = 'hard' | 'soft' | 'free';

export interface PlanItem {
  id: string;
  parent_id: string | null;
  ord: number;
  kind: PlanItemKind;
  rigidity: PlanRigidity;
  text_md: string;
  text_plain: string;
  /** ISO moment, or null when the line claims no piece of the clock. */
  starts_at: string | null;
  ends_at: string | null;
  window_comment: string | null;
  code: string | null;
  done_criterion: string | null;
  why_md: string | null;
  plan_md: string | null;
  external_ref: Record<string, unknown> | null;
  /** Every `Подпись :: значение` without a column of its own. */
  extra: Record<string, unknown>;
  quarter_goal_id: number | null;
  unlinked_reason: string | null;
  carried_from_item_id: string | null;
  carry_count: number;
  children: PlanItem[];
}

export interface PlanSection {
  id: string;
  ord: number;
  title: string | null;
  kind: string;
  items: PlanItem[];
}

/**
 * One line of the day's schedule.
 *
 * `minutes` is the server's, not a subtraction here: a window that runs past
 * midnight is sixty minutes only to someone who knows where the day ends.
 */
export interface ScheduleEntry {
  item_id: string;
  section_id: string;
  code: string | null;
  text_plain: string;
  kind: PlanItemKind;
  rigidity: PlanRigidity;
  starts_at: string;
  ends_at: string;
  minutes: number;
  window_comment: string | null;
}

/** Two lines whose windows intersect, as the database found them. */
export interface ScheduleOverlap {
  left_item_id: string;
  right_item_id: string;
  overlap_minutes: number;
}

export interface Plan {
  id: string;
  day_date: string;
  title: string | null;
  title_marker: string | null;
  lede: string | null;
  purpose_md: string | null;
  quarter_goal_id: number | null;
  counters: unknown[];
  condition_tomorrow: string | null;
  status: 'draft' | 'active' | 'closed';
  source: 'day-open' | 'import' | 'manual';
  created_at: string;
  updated_at: string;
  sections: PlanSection[];
  schedule: ScheduleEntry[];
  overlaps: ScheduleOverlap[];
}

/**
 * A plan on its way to the server.
 *
 * Neither a section nor an item carries `ord`: the server numbers what it
 * receives, so the order on screen is the order that was sent and two sections
 * can never claim the same place. A window goes as `"23:30-00:30"` — wall
 * clock, because that is what a human and `/day-open` both write.
 */
export interface PlanItemDraft {
  kind?: PlanItemKind;
  rigidity?: PlanRigidity;
  text_md: string;
  window?: string | null;
  window_comment?: string | null;
  code?: string | null;
  done_criterion?: string | null;
  why_md?: string | null;
  plan_md?: string | null;
  external_ref?: Record<string, unknown> | null;
  extra?: Record<string, unknown>;
  quarter_goal_id?: number | null;
  unlinked_reason?: string | null;
  children?: PlanItemDraft[];
}

export interface PlanSectionDraft {
  title?: string | null;
  kind?: string;
  items?: PlanItemDraft[];
}

export interface PlanDocument {
  title?: string | null;
  title_marker?: string | null;
  lede?: string | null;
  purpose_md?: string | null;
  quarter_goal_id?: number | null;
  counters?: unknown[];
  condition_tomorrow?: string | null;
  status?: Plan['status'];
  source?: Plan['source'];
  raw_md?: string | null;
  sections: PlanSectionDraft[];
}

/** Whether the day was won. `null` is "не закрыл", which is not "проиграл". */
export type Verdict = 'won' | 'lost';

/**
 * Which condition of the canon was not met.
 *
 * Ordered on the server as `not_closed → overtime → anchors → tasks`, which is
 * the priority of `config.md`: здоровье > работа > отношения. An empty string
 * means every condition was met.
 */
export type VerdictReason = 'tasks' | 'anchors' | 'overtime' | 'not_closed';

/** What the day could not be judged on. `work_minutes` is "не измерено". */
export type MissingData = 'work_minutes';

/**
 * The итог of a day: the verdict, what it stands on, and the prose beside it.
 *
 * `closed` is false while nobody has closed the day; the counters are then a
 * live recount, `verdict` is null and `verdict_reason` is `not_closed`. That is
 * what keeps «не закрыл» a different answer from «проиграл».
 */
export interface DaySummary {
  day_date: string;
  closed: boolean;
  /** The canon this day was judged by — it changed on 2026-08-17. */
  rule_set_id: number;
  verdict: Verdict | null;
  verdict_reason: VerdictReason | '';
  verdict_override: boolean;
  verdict_override_note: string | null;
  anchors_done: number;
  anchors_total: number;
  tasks_done: number;
  tasks_total: number;
  /** null means the work was never measured, not that it was zero. */
  work_minutes: number | null;
  streak_after: number | null;
  wrote_from_scratch: number | null;
  education_debt: number | null;
  reviewed_today: number | null;
  body_md: string;
  missing_data: MissingData[];
  /** Texts of the anchors that were neither closed nor set aside. */
  missing_anchors: string[];
  source: 'close' | 'import';
}

/** What closing a day says about it. */
export interface DayCloseDraft {
  work_minutes?: number | null;
  body_md?: string;
  wrote_from_scratch?: number | null;
  education_debt?: number | null;
  reviewed_today?: number | null;
  /** Requires a note; the server refuses the pair without one. */
  verdict_override?: boolean;
  verdict_override_note?: string | null;
}

/** One day, the rule it is judged by, and its plan when there is one. */
export interface DayDetail {
  day: Day;
  rule: DayRuleSet;
  plan: Plan | null;
  has_plan: boolean;
  /** One entry per item that has a mark; an item missing here is `pending`. */
  marks: Mark[];
  task_counts: TaskCounts;
  /** The day's free text, or null when nothing was written. */
  notebook: string | null;
  /** Always present — a live recount while the day is not closed. */
  summary: DaySummary;
  /** The intervals the day's measured time is made of, and their sum. */
  work: WorkDay;
}

/** Who put an interval there; `corrected` is a state, not a writer. */
export type WorkIntervalSource = 'manual' | 'agent' | 'corrected';

/** What the interval says the person was doing; only `work` adds up. */
export type WorkMode = 'work' | 'off';

/**
 * One recorded stretch of work or pause.
 *
 * `auto_started_at`/`auto_ended_at` hold what the agent proposed before a
 * person moved it, so a corrected interval can show both values at once —
 * «исправил руками» and «агент так и посчитал» have to stay tellable apart.
 *
 * There is no field for a window title, and there is no column behind one: the
 * privacy line of the day model runs through this table. Screenshots do not
 * exist anywhere in this system.
 */
export interface WorkInterval {
  id: string;
  day_date: string;
  started_at: string;
  /** null means the interval is running right now. */
  ended_at: string | null;
  running: boolean;
  /** Length as the server counts it; an open interval is measured to now. */
  minutes: number;
  source: WorkIntervalSource;
  mode: WorkMode;
  auto_started_at: string | null;
  auto_ended_at: string | null;
  app_bundle_id: string | null;
  note: string | null;
  /** When a person intervened; null means nobody has. */
  edited_at: string | null;
}

/** The work of one day: its intervals and what they add up to. */
export interface WorkDay {
  day_date: string;
  intervals: WorkInterval[];
  /** null means «не измерено» — no intervals at all — and never zero. */
  work_minutes: number | null;
  running: boolean;
}

/** A new interval. `corrected` cannot be declared: it is reached by editing. */
export interface WorkIntervalDraft {
  started_at: string;
  ended_at?: string | null;
  source?: 'manual' | 'agent';
  mode?: WorkMode;
  app_bundle_id?: string | null;
  note?: string | null;
}

/**
 * An edit of an interval; only the keys present are touched.
 *
 * `ended_at: null` reopens a closed interval, an absent `ended_at` leaves it
 * alone — which is why this is a partial object rather than the whole row.
 */
export interface WorkIntervalPatch {
  started_at?: string;
  ended_at?: string | null;
  mode?: WorkMode;
  app_bundle_id?: string | null;
  note?: string | null;
}

/** What a mark can say. Absence of a mark is the fourth answer, and it is not a value. */
export type MarkState = 'done' | 'failed' | 'skipped';

/** Who wrote a mark: a click, the local agent, the import, a suggestion. */
export type MarkSource = 'web' | 'agent' | 'import' | 'llm';

export interface Mark {
  item_id: string;
  /** null after the mark was taken off — the line is back to "не дошёл". */
  state: MarkState | null;
  note: string | null;
  /** When the current state was set; a note edited later does not move it. */
  marked_at: string | null;
  updated_at: string | null;
  source: MarkSource | null;
}

/**
 * The day's work tasks split by what happened to them.
 *
 * `skipped` is counted apart from both `done` and `failed`: a task that stopped
 * being relevant was neither closed nor missed.
 */
export interface TaskCounts {
  planned: number;
  done: number;
  failed: number;
  skipped: number;
  pending: number;
}

/** The body of a mark write; `state: null` takes the mark off. */
export interface MarkDraft {
  state: MarkState | null;
  note?: string | null;
  source?: MarkSource;
}

// -- Goals -----------------------------------------------------------------

/** One `## Уровень N` block of `goal.md`. */
export interface GoalLevel {
  level: number;
  title: string;
  body_md: string;
  /** The `⚠ подтверди` lines: what the author guessed rather than confirmed. */
  open_questions: string[];
}

/** The four states a milestone can be in, as the database spells them. */
export type MilestoneStatus = 'open' | 'in-progress' | 'done' | 'dropped';

export interface Milestone {
  code: string;
  title: string;
  done_criterion: string | null;
  when_text: string | null;
  ord: number;
  status: MilestoneStatus;
  /** Filled the day the milestone was closed; null while it is not. */
  done_on: string | null;
  /** Codes this milestone waits on — `["M8", "M9"]` for M10, not a sentence. */
  depends_on: string[];
}

export interface QuarterGoal {
  id: number;
  quarter: string;
  ord: number;
  text_md: string;
  milestone_code: string | null;
  status: string;
}

/** The whole goal board, as one request answers it. */
export interface GoalsPayload {
  levels: GoalLevel[];
  milestones: Milestone[];
  /** The quarter the server's day boundary says is running — `2026-Q3`. */
  quarter: string;
  goals: QuarterGoal[];
}

export const goalsAPI = {
  get: async () => {
    return fetcher<GoalsPayload>('/goals');
  },

  /**
   * Move one milestone to another status.
   *
   * `done` is what dates it, and the date is the server's day rather than the
   * browser's: the day runs from 04:00, and a milestone closed at half past
   * midnight belongs to the day that is still running.
   */
  patchMilestone: async (code: string, status: MilestoneStatus) => {
    return fetcher<Milestone>(`/goals/milestones/${code}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  },
};

// ============ Chat ============

/** Why a conversation was started. Mirrors `CONVERSATION_KINDS` on the server. */
export type ConversationKind = 'general' | 'day_open' | 'day_close';

/** Who said it. `system_note` is the server speaking, not the model. */
export type ChatRole = 'user' | 'assistant' | 'system_note';

/**
 * State of one message.
 *
 * `interrupted` and `failed` are different facts: the first has the text that
 * arrived before the connection died, the second has no text and a machine code.
 */
export type ChatMessageStatus = 'streaming' | 'complete' | 'interrupted' | 'failed';

export interface ChatConversation {
  id: number;
  title: string | null;
  started_on: string;
  kind: ConversationKind;
  llm_backend: string | null;
  context_version: number;
  last_message_at: string | null;
  archived: boolean;
  created_at: string;
}

export interface ChatMessage {
  id: number;
  seq: number;
  role: ChatRole;
  content: string;
  status: ChatMessageStatus;
  error_code: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read_tokens: number | null;
  latency_ms: number | null;
  model: string | null;
  created_at: string;
  /** The plan proposed in this message, if it proposed one. */
  plan_id?: number | null;
}

/**
 * What the chat may propose to write — and, more to the point, what it may not.
 *
 * There is no operation for unticking, deleting or renaming anything: the class
 * of destructive writes is closed by the type, not by the prompt. A model that
 * answers past its instructions still cannot say a word the shape does not have.
 */
export interface ChatPlanMetricOp {
  op: 'log_metric';
  category_id: number;
  field_id: number;
  value: number;
  source_text: string;
  uncertain?: boolean;
  suspicious?: boolean;
}

/** A box to tick. There is deliberately no field able to carry a `false`. */
export interface ChatPlanCheckOp {
  op: 'check';
  category_id: number;
  field_id: number;
  source_text: string;
  uncertain?: boolean;
}

/** The day's text. `replace` is not among the modes the chat can name. */
export interface ChatPlanJournalOp {
  op: 'write_journal';
  content: string;
  title?: string | null;
  mood?: string | null;
  tags?: string | null;
  mode: 'append' | 'create';
}

export interface ChatPlanBody {
  entry_date: string;
  metrics: ChatPlanMetricOp[];
  checklist: ChatPlanCheckOp[];
  journal: ChatPlanJournalOp | null;
}

export type ChatPlanStatus = 'proposed' | 'applied' | 'dismissed' | 'stale';

export interface ChatPlan {
  id: number;
  message_id: number;
  entry_date: string;
  status: ChatPlanStatus;
  plan: ChatPlanBody;
  operation_count: number;
  applied_summary_id: number | null;
  applied_at: string | null;
  created_at: string;
}

/** What the person left ticked when they pressed «применить». */
export interface ChatPlanSelection {
  metrics?: ChatPlanMetricOp[];
  checklist?: ChatPlanCheckOp[];
  journal?: ChatPlanJournalOp | null;
}

export interface ChatPlanApplyResult {
  plan: ChatPlan;
  entry_ids: number[];
  journal_entry_id: number | null;
  applied_operations: number;
}

/** A conversation read back with its messages — what a reload of `/chat` draws. */
export interface ChatConversationDetail extends ChatConversation {
  messages: ChatMessage[];
}

export const chatAPI = {
  list: async (limit = 50) => {
    return fetcher<ChatConversation[]>(`/chat/conversations?limit=${limit}`);
  },

  create: async (kind: ConversationKind = 'general') => {
    return fetcher<ChatConversation>('/chat/conversations', {
      method: 'POST',
      body: JSON.stringify({ kind }),
    });
  },

  get: async (id: number) => {
    return fetcher<ChatConversationDetail>(`/chat/conversations/${id}`);
  },

  /** One plan, however many turns ago it was shown. */
  getPlan: async (planId: number) => {
    return fetcher<ChatPlan>(`/chat/plans/${planId}`);
  },

  /**
   * Apply what is still ticked.
   *
   * The server narrows the selection to the plan it stored, so a row the card
   * never showed cannot be smuggled in here. `Idempotency-Key` makes the second
   * tap a 200 that writes nothing, exactly as on the day-review screen.
   */
  applyPlan: async (
    planId: number,
    selection: ChatPlanSelection,
    idempotencyKey: string,
  ) => {
    return fetcher<ChatPlanApplyResult>(`/chat/plans/${planId}/apply`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(selection),
    });
  },

  dismissPlan: async (planId: number) => {
    return fetcher<void>(`/chat/plans/${planId}/dismiss`, { method: 'POST' });
  },

  /**
   * Send one turn and read the answer as it is produced.
   *
   * Not `fetcher`: that one waits for the whole body, which is exactly what
   * this endpoint exists to avoid. `signal` lets the screen abandon a turn;
   * the server still stores what it had, with status `interrupted`.
   */
  streamMessage: async (
    id: number,
    content: string,
    onEvent: (event: ChatStreamEvent) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const response = await fetch(`${API_BASE_URL}/chat/conversations/${id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
      signal,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'An error occurred' }));
      throw new APIError(response.status, error.detail || 'An error occurred');
    }
    if (!response.body) {
      throw new APIError(response.status, 'Поток ответа недоступен в этом браузере');
    }

    const reader = response.body.getReader();
    // `stream: true` on the decoder is what keeps a multi-byte character whole
    // when a chunk ends in the middle of it — Russian text splits routinely.
    const decoder = new TextDecoder();
    const parser = new ChatStreamParser();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const event of parser.push(decoder.decode(value, { stream: true }))) {
          onEvent(event);
        }
      }
      for (const event of parser.flush()) onEvent(event);
    } finally {
      reader.releaseLock();
    }
  },
};

// ============ Challenges ============

/** Which of the four promises a challenge holds its category to. */
export type ChallengeRuleKind =
  | 'metric_at_least'
  | 'metric_at_most'
  | 'checked'
  | 'abstain';

/**
 * The state of one day of an obligation.
 *
 * `pending` exists because today has not closed yet: an obligation's day
 * becomes a miss when `local_date()` names the next date, not at browser
 * midnight, so the browser never decides this for itself.
 */
export type ChallengeDayVerdict = 'done' | 'miss' | 'pending';

/** Who put the verdict there. A recompute never overwrites `manual`. */
export type ChallengeDaySource = 'computed' | 'manual';

/** `any_miss` — the first miss ends it; `budget` — the (allowed + 1)-th does. */
export type ChallengeFailureMode = 'any_miss' | 'budget';

export type ChallengeStatus = 'active' | 'won' | 'failed' | 'abandoned';

export interface ChallengeDay {
  day: string;
  verdict: ChallengeDayVerdict;
  source: ChallengeDaySource;
  note: string | null;
}

export interface Challenge {
  id: number;
  title: string;
  category_id: number;
  field_id: number;
  rule_kind: ChallengeRuleKind;
  /** Decimal over the wire: the server never rounds a threshold into a float. */
  target: string | null;
  starts_on: string;
  ends_on: string;
  failure_mode: ChallengeFailureMode;
  allowed_misses: number;
  status: ChallengeStatus;
  failed_on: string | null;
  total_days: number;
  day_number: number;
  done_count: number;
  misses_used: number;
  /** How many misses the obligation still survives; 0 under `any_miss`. */
  misses_left: number;
  /** null when today is outside the window. */
  today_verdict: ChallengeDayVerdict | null;
  created_at: string;
}

export interface ChallengeDetail extends Challenge {
  days: ChallengeDay[];
}

export interface ChallengeDraft {
  title: string;
  category_id: number;
  field_id: number;
  rule_kind: ChallengeRuleKind;
  target?: string;
  starts_on: string;
  ends_on: string;
  failure_mode?: ChallengeFailureMode;
  allowed_misses?: number;
}

export interface ChallengePatch {
  title?: string;
  target?: string | null;
  ends_on?: string;
  failure_mode?: ChallengeFailureMode;
  allowed_misses?: number;
  /**
   * The only status a person sets. `won` and `failed` are derived from the
   * misses, and the server refuses them here.
   */
  status?: 'abandoned';
}

/** A verdict put on a day by hand. `pending` is deliberately not offerable. */
export interface ChallengeDayDraft {
  verdict: 'done' | 'miss';
  note?: string;
}

/**
 * Reading a challenge is what advances it.
 *
 * There is no scheduler in this project — every line of code runs inside an
 * HTTP request — so the verdicts of the days that passed are materialized by
 * the read itself. That is why the card never computes a count of its own: the
 * numbers it prints are the ones the server just wrote down.
 */
export const challengesAPI = {
  list: async () => {
    return fetcher<Challenge[]>('/challenges');
  },

  get: async (id: number) => {
    return fetcher<ChallengeDetail>(`/challenges/${id}`);
  },

  create: async (draft: ChallengeDraft) => {
    return fetcher<Challenge>('/challenges', {
      method: 'POST',
      body: JSON.stringify(draft),
    });
  },

  patch: async (id: number, patch: ChallengePatch) => {
    return fetcher<Challenge>(`/challenges/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  },

  recompute: async (id: number) => {
    return fetcher<Challenge>(`/challenges/${id}/recompute`, { method: 'POST' });
  },

  /**
   * Count a day, or refuse it, by hand.
   *
   * A recompute never overwrites this afterwards, and the status is recomputed
   * from it — which is the only way a failed challenge comes back to active.
   */
  setDayVerdict: async (id: number, day: string, draft: ChallengeDayDraft) => {
    return fetcher<ChallengeDetail>(`/challenges/${id}/days/${day}`, {
      method: 'PUT',
      body: JSON.stringify(draft),
    });
  },
};
