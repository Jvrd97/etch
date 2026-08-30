/**
 * API Client for Habit Tracker Backend
 */
// [review:need-review] PHASE-01/73-dashboard-hero-today-ring, PHASE-03/86, PHASE-03/90, PHASE-03/93, PHASE-03/109, PHASE-03/134
// summary: entriesAPI.getAll takes the backend's `sort` — `created_at_desc` plus a limit fetches the last written entry without pulling the history; dayAPI reads one day with the rule it is judged by, its plan, its marks and its итог, and writes back a whole plan, a single mark, the day's notebook or the close that judges the day; goalsAPI reads the goal board and moves one milestone; rolesAPI reads the distribution of a day's minutes together with its acts and writes both by hand
// summary: every request now carries the session cookie (`credentials: 'include'`) and a 401 sends the reader to the login screen; authAPI trades the key for that cookie and drops it again

import { loginRedirectTarget } from './auth';

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

/**
 * Send an unauthenticated reader to the login screen.
 *
 * A hard navigation rather than the router: the app is on a screen whose data
 * it could not load, and every hook holding stale state has to go with it.
 * No-op on the server and on the login screen itself, where a 401 is the
 * message "wrong key" and a redirect would be a reload loop.
 */
function redirectToLoginIfNeeded(status: number): void {
  if (typeof window === 'undefined') return;
  const { pathname, search } = window.location;
  const target = loginRedirectTarget(status, pathname, search);
  if (target !== null) window.location.assign(target);
}

async function fetcher<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    // The browser authenticates with an HttpOnly session cookie and holds no
    // key of its own; without this the cookie is left at home on a cross-origin
    // deployment and every screen answers 401.
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    redirectToLoginIfNeeded(response.status);
    const error = await response.json().catch(() => ({ detail: 'An error occurred' }));
    throw new APIError(response.status, error.detail || 'An error occurred');
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

/** What the server says about the current browser session. Never carries the key. */
export interface SessionState {
  authenticated: boolean;
  expires_in_s: number | null;
}

/**
 * The session endpoints — the only place the key touches the browser.
 *
 * `login` sends it once and forgets it: the answer is a cookie the page cannot
 * read, so nothing here writes to localStorage, and nothing here returns the
 * key to its caller.
 */
export const authAPI = {
  login: async (apiKey: string) => {
    return fetcher<SessionState>('/auth/session', {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey }),
    });
  },

  status: async () => {
    return fetcher<SessionState>('/auth/session');
  },

  logout: async () => {
    return fetcher<SessionState>('/auth/session', { method: 'DELETE' });
  },
};

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

// ---------------------------------------------------------------------------
// Roles (PHASE-03/134)
// ---------------------------------------------------------------------------

/** One role of the directory. `target_share_pct` is a hypothesis, never a norm. */
export interface Role {
  id: number;
  code: string;
  title: string;
  description: string | null;
  target_share_pct: number | null;
  is_work: boolean;
  ord: number;
  is_active: boolean;
}

/** One role's share of one day: minutes, the share they make, and the acts. */
export interface RoleDaySlice {
  role_id: number;
  role_code: string;
  title: string;
  minutes: number;
  share_pct: number;
  target_share_pct: number | null;
  act_count: number;
}

/** Minutes charged to a role. `is_manual` is what the screen marks. */
export interface RoleTimeBlock {
  id: number;
  work_day: string;
  role_id: number;
  role_code: string;
  source: string;
  started_at: string | null;
  ended_at: string | null;
  minutes: number;
  confidence: string;
  external_ref: string | null;
  rule_id: number | null;
  note: string | null;
  is_manual: boolean;
}

/** One act: the role happened, and this is what it was. */
export interface RoleAct {
  id: number;
  work_day: string;
  role_id: number;
  role_code: string;
  act_kind: string;
  title: string;
  source: string;
  external_ref: string | null;
  confidence: string;
  occurred_at: string | null;
  note: string | null;
  is_manual: boolean;
}

/** Where a day went and which roles happened on it, in one answer. */
export interface RoleDay {
  work_day: string;
  total_minutes: number;
  roles: RoleDaySlice[];
  blocks: RoleTimeBlock[];
  acts: RoleAct[];
}

/** «Полтора часа на найм» as it is sent. The day is the server's when omitted. */
export interface RoleTimeBlockDraft {
  role_code: string;
  minutes: number;
  work_day?: string;
  note?: string | null;
}

/** «Написал ADR» as it is sent. */
export interface RoleActDraft {
  role_code: string;
  act_kind: string;
  title: string;
  work_day?: string;
  note?: string | null;
}

/**
 * The roles endpoints.
 *
 * `day()` without a date asks the server which day it is — the boundary runs
 * from 04:00 and only `app/core/daytime.py` answers that question, so the
 * browser never dates a screen from its own calendar.
 */
export const rolesAPI = {
  day: async (date?: string) => {
    return fetcher<RoleDay>(date ? `/roles/day/${date}` : '/roles/day');
  },

  listRoles: async () => {
    return fetcher<Role[]>('/roles');
  },

  addTimeBlock: async (draft: RoleTimeBlockDraft) => {
    return fetcher<RoleTimeBlock>('/role-time-blocks', {
      method: 'POST',
      body: JSON.stringify(draft),
    });
  },

  deleteTimeBlock: async (id: number) => {
    return fetcher<Record<string, never>>(`/role-time-blocks/${id}`, {
      method: 'DELETE',
    });
  },

  addAct: async (draft: RoleActDraft) => {
    return fetcher<RoleAct>('/role-acts', {
      method: 'POST',
      body: JSON.stringify(draft),
    });
  },

  deleteAct: async (id: number) => {
    return fetcher<Record<string, never>>(`/role-acts/${id}`, { method: 'DELETE' });
  },
};
