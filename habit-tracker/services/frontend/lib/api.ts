/**
 * API Client for Habit Tracker Backend
 */
// [review:need-review] PHASE-01/73-dashboard-hero-today-ring, PHASE-03/86, PHASE-03/90, PHASE-03/91, PHASE-03/92, PHASE-03/93, PHASE-03/94, PHASE-03/109, PHASE-03/110, PHASE-03/111, PHASE-03/115, PHASE-03/116, PHASE-03/117, PHASE-03/118, PHASE-03/121, PHASE-03/124, PHASE-03/125, PHASE-03/134, PHASE-03/143, PHASE-03/147, PHASE-03/152
// summary: entriesAPI.getAll takes the backend's `sort` — `created_at_desc` plus a limit fetches the last written entry without pulling the history; dayAPI reads one day with the rule it is judged by, its plan, its marks and its итог, and writes back a whole plan, a single mark, the day's notebook or one of the two touches that close the day — the 15:40 review and the evening final, each idempotent by its own key — edits one line of the plan at a time, marks the anchors of a day by kind, writes its training, and reads and edits the work intervals a day's measured time is made of; goalsAPI reads the goal board and moves one milestone; rolesAPI reads the distribution of a day's minutes together with its acts and writes both by hand; trainingAPI reads the derived state with its gated suggestion and opens or closes a complaint; chatAPI keeps the conversation feed, streams one turn through fetch + ReadableStream instead of waiting for a whole body, resets a stuck dialogue, reads back the day card the prompt carried, and applies a plan the chat proposed; dayRulesAPI reads every version of the day canon and publishes the next one; daysAPI reads a range of days, weeksAPI reads and writes one week, and quickMarksAPI is the whole contract of a quick mark — the directory with today's state on it, the button entered, patched, reordered and deleted by hand, one POST per tap whose answer already carries the new sum, the undo of the last tap and the split of taps by source
// summary: every request now carries the session cookie (`credentials: 'include'`) and a 401 sends the reader to the login screen; authAPI trades the key for that cookie and drops it again
import { loginRedirectTarget } from './auth';
import { ChatStreamParser, type ChatStreamEvent } from '@/lib/chat-stream';

// Relative by default: requests go to the same origin that served the page and
// are proxied to the backend by the Next rewrite (see next.config.ts). Keeps the
// app reachable from any device on the LAN without host-specific config.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

export class APIError extends Error {
  /**
   * The body's `detail` as it arrived, beside the message built from it.
   *
   * FastAPI answers a rule of the plan with an object — `{error, message,
   * item_code}` — and flattening it into a string loses the code the screen
   * needs in order to point at the field. `message` stays a sentence for
   * everything that only ever shows one.
   */
  readonly detail: unknown;

  constructor(public status: number, message: string, detail?: unknown) {
    super(message);
    this.name = 'APIError';
    this.detail = detail ?? message;
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

/** The sentence inside a `detail`, whether it arrived as a string or an object. */
function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (
    typeof detail === 'object' &&
    detail !== null &&
    'message' in detail &&
    typeof (detail as { message: unknown }).message === 'string'
  ) {
    return (detail as { message: string }).message;
  }
  return null;
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
    throw new APIError(
      response.status,
      detailMessage(error.detail) ?? 'An error occurred',
      error.detail
    );
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
/**
 * The `Idempotency-Key` header, or nothing at all.
 *
 * An absent key is a valid request rather than an error: a `curl` from a script
 * has no reason to invent one, and the touch has to work without it — just
 * without protection from a double press.
 */
function idempotency(key?: string): Record<string, string> {
  return key === undefined ? {} : { 'Idempotency-Key': key };
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
   * Edit one line of the plan in place, keeping its id and its mark.
   *
   * Only the fields sent are touched: `null` means "clear this", and a key left
   * out means "do not touch this". The whole-plan `savePlan` is the generator's
   * operation — it replaces the document; this is the person's, and it is the
   * only one under which `plan_item.id` survives a change of wording.
   */
  patchPlanItem: async (date: string, itemId: string, patch: PlanItemPatch) => {
    return fetcher<PlanEdit>(`/day/${date}/plan/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  },

  /** Add a line to a section; it lands at the end of its level. */
  addPlanItem: async (date: string, sectionId: string, draft: PlanItemDraft) => {
    return fetcher<PlanEdit>(`/day/${date}/plan/sections/${sectionId}/items`, {
      method: 'POST',
      body: JSON.stringify(draft),
    });
  },

  /** Remove a line together with its children — a minimum leaves with its task. */
  deletePlanItem: async (date: string, itemId: string) => {
    return fetcher<PlanEdit>(`/day/${date}/plan/items/${itemId}`, {
      method: 'DELETE',
    });
  },

  /**
   * Move a line to a place: another position, another parent, another section.
   *
   * Its own request rather than an `ord` in the patch — one drag renumbers a
   * whole level, and writing positions one at a time is what leaves a plan with
   * holes and twins halfway through.
   */
  movePlanItem: async (date: string, itemId: string, move: PlanItemMove) => {
    return fetcher<PlanEdit>(`/day/${date}/plan/items/${itemId}/move`, {
      method: 'POST',
      body: JSON.stringify(move),
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

  /**
   * The rules this day's plan broke.
   *
   * `warn` is a person's own edit, stored and annotated rather than refused;
   * `block` is a draft that never reached the database and lies here as the
   * explanation of why the day has no plan.
   */
  violations: async (date: string) => {
    return fetcher<PlanViolation[]>(`/day/${date}/plan/violations`);
  },

  /**
   * Build the day out of the canon, without a model.
   *
   * The insurance of `#147`: the day is never left without a plan, whatever the
   * model does. Writes only on `date` — the neighbours are not touched.
   */
  buildSkeleton: async (date: string) => {
    return fetcher<Plan>(`/day/${date}/plan/skeleton`, { method: 'POST' });
  },

  /**
   * Mark the anchors of a day, by kind rather than by position.
   *
   * The kind is what a write names: the order of the list is a property of the
   * screen, and a request that leaned on it would break the first time a kind
   * is added to the catalogue. Several anchors travel in one request because
   * the evening closes three of them in one gesture.
   */
  setAnchors: async (date: string, anchors: AnchorMarkDraft[]) => {
    return fetcher<DayAnchors>(`/day/${date}/anchors`, {
      method: 'PUT',
      body: JSON.stringify({ anchors }),
    });
  },

  /** Read the anchors of a day on their own, without the rest of the day. */
  getAnchors: async (date: string) => {
    return fetcher<DayAnchors>(`/day/${date}/anchors`);
  },

  /**
   * Write the training of a day; an absent field is left alone.
   *
   * The morning writes the plan and the evening writes the fact, so a
   * whole-row replace would let the second erase the first by omission.
   */
  saveTraining: async (date: string, draft: TrainingDayDraft) => {
    return fetcher<TrainingDay>(`/day/${date}/training`, {
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
   * Касание около 15:40: факт по работе, без вердикта.
   *
   * Стадия дня становится `reviewed`, `verdict` остаётся null — «рано», а не
   * «проиграл». `null` в любом поле — «не трогать записанное».
   */
  review: async (date: string, draft: DayReviewDraft, key?: string) => {
    return fetcher<DaySummary>(`/day/${date}/close/review`, {
      method: 'POST',
      body: JSON.stringify(draft),
      headers: idempotency(key),
    });
  },

  /**
   * Вечернее касание: закрыть день, вынести вердикт, пересчитать стрик.
   *
   * Касание идёт одним документом — минуты работы, проза и переопределение
   * читаются вместе или вердикт неверен, а API «по полю за раз» оставил бы
   * день наполовину закрытым, и ничто бы об этом не говорило. То, что закрытие
   * бывает в два приёма, сказано стадией, а не набором заполненных полей.
   *
   * Ключ повтора необязателен. С ним второе нажатие той же кнопки не
   * перезакрывает день: сервер отвечает той же строкой и ничего не пишет.
   */
  closeFinal: async (date: string, draft: DayCloseDraft, key?: string) => {
    return fetcher<DaySummary>(`/day/${date}/close/final`, {
      method: 'POST',
      body: JSON.stringify(draft),
      headers: idempotency(key),
    });
  },

  /**
   * Устаревший синоним `closeFinal`.
   *
   * Оставлен ради вызовов, написанных до того, как касаний стало два; новый
   * код зовёт `closeFinal`, потому что имя без стадии больше не однозначно.
   */
  close: async (date: string, draft: DayCloseDraft) => {
    return dayAPI.closeFinal(date, draft);
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
  overtime_lost_min: number;
  max_study_items: number;
  /** `HH:MM:SS` hard edges of the day, as the canon writes them. */
  wake_at: string;
  work_start: string;
  review_at: string;
  bedtime_max: string;
  free_evening_start: string;
  free_evening_end: string;
  relationship_anchor_required: boolean;
  relationship_evening_start: string;
  relationship_evening_end: string;
  workdays: number[];
  /** Days off — not the complement of `workdays`, a list of its own. */
  days_off: number[];
  nocode_days: number[];
  required_anchors: string[];
  hard_edge_kinds: string[];
  anchors: string[];
  verdict_rule: Record<string, unknown>;
  /** Судит ли канон рабочий день по акту роли, отличной от тимлида. */
  role_clause_enabled: boolean;
  /** Коды ролей клауза через запятую. */
  role_clause_roles: string;
  note_md: string;
}

/** One hard edge of the day; `at` is null for an edge the canon does not clock. */
export interface DayEdge {
  kind: string;
  label: string;
  at: string | null;
}

/** A stretch of the evening, named by its two wall-clock ends. */
export interface DayInterval {
  start: string;
  end: string;
}

/**
 * The map of the day: where the hard points stand, which evening stays free.
 *
 * Every number is a column of the rule row, so a change of canon changes the
 * screen without a line of this app being touched.
 */
export interface DayMap {
  rule_set_id: number;
  edges: DayEdge[];
  free_evening: DayInterval;
  relationship_evening: DayInterval;
  relationship_anchor_required: boolean;
  work_cap_min: number;
  work_hard_cap_min: number;
  overtime_lost_min: number;
  work_stop_at: string;
  max_work_tasks: number;
  max_study_items: number;
  anchors: string[];
  hard_edge_kinds: string[];
  workdays: number[];
  days_off: number[];
  nocode_days: number[];
  /** Conditions that lower a day, in the order they are weighed. */
  verdict_reasons: VerdictReason[];
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
  /** Судить ли рабочий день по акту роли, отличной от тимлида. */
  role_clause_enabled: boolean;
  /** Коды ролей клауза через запятую. */
  role_clause_roles: string;
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

/**
 * A patch of one plan line: only what is sent gets written.
 *
 * Every field is optional twice over — it may be absent (do not touch) or
 * `null` (clear). The two are different orders, and merging them would wipe
 * half a task on every corrected word.
 */
export interface PlanItemPatch {
  kind?: PlanItemKind;
  rigidity?: PlanRigidity;
  text_md?: string;
  /** "ЧЧ:ММ-ЧЧ:ММ" in the day's local clock, or null to take the window off. */
  window?: string | null;
  window_comment?: string | null;
  code?: string | null;
  done_criterion?: string | null;
  why_md?: string | null;
  plan_md?: string | null;
  quarter_goal_id?: number | null;
  unlinked_reason?: string | null;
}

/** A new line for a section. Position is not sent: it lands at the end. */
export interface PlanItemDraft {
  parent_id?: string | null;
  kind?: PlanItemKind;
  rigidity?: PlanRigidity;
  text_md: string;
  window?: string | null;
  window_comment?: string | null;
  code?: string | null;
  done_criterion?: string | null;
  quarter_goal_id?: number | null;
  unlinked_reason?: string | null;
}

/** Where a line goes: which section, under which parent, in which place. */
export interface PlanItemMove {
  section_id: string;
  parent_id?: string | null;
  position: number;
}

/**
 * What a rule broken by a human's edit looks like on the wire.
 *
 * The same shape a 422 carries, because it is the same rule — the difference is
 * only who broke it. A machine's document is refused; a person's edit is saved
 * and told.
 */
export interface PlanWarning {
  error: string;
  message: string;
  item_code: string | null;
  item_text: string | null;
}

/**
 * The answer of any per-item edit: the plan whole, the line touched, the
 * warnings earned.
 *
 * The plan comes back whole because editing one line moves its neighbours, the
 * schedule and the overlap list; a second read for what the server already knew
 * would be a round trip per keystroke.
 */
export interface PlanEdit {
  plan: Plan;
  item: PlanItem | null;
  warnings: PlanWarning[];
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

/** Which rule of the canon a draft plan broke. Mirrors `app/day/constraints.py`. */
export type PlanRuleCode =
  | 'hard_edges_only'
  | 'free_evening_empty'
  | 'work_cap'
  | 'task_cap'
  | 'health_before_work'
  | 'relationship_anchor_required'
  | 'no_overlap'
  | 'target_day_only';

/**
 * One broken rule, recorded beside the day.
 *
 * `detail` carries item ids and numbers and never the text of a line: the row
 * outlives the plan that produced it, and a task can be named after a
 * diagnosis. The screen therefore looks a line up by id rather than reading a
 * quote out of the violation.
 */
export interface PlanViolation {
  id: number;
  day_date: string;
  rule_code: PlanRuleCode;
  severity: 'block' | 'warn';
  origin: 'ai' | 'fallback' | 'human';
  detail: Record<string, unknown>;
  created_at: string;
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
 * Ordered on the server as `not_closed → overtime → anchors → tasks`, by which
 * one is worth being sent to repair: overtime is named before the anchors
 * because anchors missed after the ninth hour are its consequence, and pointing
 * at them would send the reader to fix the wrong thing. An empty string means
 * every condition was met.
 */
export type VerdictReason =
  | 'tasks'
  | 'anchors'
  | 'overtime'
  | 'not_closed'
  | 'role_act';

/**
 * One condition of the canon and how the day stood against it.
 *
 * The verdict is derived from the list rather than counted beside it, so a
 * screen showing the clauses is showing the reasoning itself and not a
 * paraphrase of it.
 */
export interface DayClause {
  code: VerdictReason;
  passed: boolean;
  detail: string;
}

/** What the day could not be judged on. `work_minutes` is "не измерено". */
export type MissingData = 'work_minutes' | 'anchor_kinds';

/**
 * Как далеко зашло закрытие дня.
 *
 * `open` — никто не начинал; `reviewed` — прошло касание 15:40 и вердикта ещё
 * нет; `closed` — день закрыт. Это дискриминант, а не пара булевых флагов:
 * «не закрыл», «рано» и «проиграл» — три разных ответа, и два флага рано или
 * поздно разошлись бы между собой.
 */
export type ClosingStage = 'open' | 'reviewed' | 'closed';

/**
 * The итог of a day: the verdict, what it stands on, and the prose beside it.
 *
 * `closed` is false while nobody has closed the day; the counters are then a
 * live recount, `verdict` is null and `verdict_reason` is `not_closed`. That is
 * what keeps «не закрыл» a different answer from «проиграл», and `stage` splits
 * that further: `verdict: null` на стадии `reviewed` значит «рано».
 */
export interface DaySummary {
  day_date: string;
  closed: boolean;
  stage: ClosingStage;
  /** Когда прошло касание 15:40; null — его не было. */
  reviewed_at: string | null;
  /** День закрыт одним касанием: ревью в 15:40 не случилось. */
  review_skipped: boolean;
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
  /** Условия канона, взвешенные для этого дня, в порядке взвешивания. */
  clauses?: DayClause[];
  /** Texts of the anchors that were neither closed nor set aside. */
  missing_anchors: string[];
  source: 'close' | 'import';
}

/**
 * Что говорит о дне касание 15:40.
 *
 * Отметок пунктов здесь нет: они уже записаны через `dayAPI.setMark`, и второй
 * путь для того же факта означал бы два ответа на один вопрос. `null` в любом
 * поле — «не трогать записанное», а не «стереть».
 */
export interface DayReviewDraft {
  work_minutes?: number | null;
  body_md?: string | null;
  wrote_from_scratch?: number | null;
  education_debt?: number | null;
  reviewed_today?: number | null;
}

/**
 * What the evening touch says about the day — only the fields actually filled in.
 *
 * The server writes the keys it is given and leaves the rest of the row alone,
 * so an omitted field is «не сказал», not «обнулить». That is what lets the
 * override travel as two fields without erasing the prose and the minutes of a
 * day the agent closed through the CLI. Removing an override is an explicit
 * `verdict_override: false`.
 */
export interface DayCloseDraft {
  work_minutes?: number | null;
  body_md?: string | null;
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
  /** The map of the day drawn by the same rule row. */
  day_map: DayMap;
  plan: Plan | null;
  has_plan: boolean;
  /** One entry per item that has a mark; an item missing here is `pending`. */
  marks: Mark[];
  task_counts: TaskCounts;
  /** The day's free text, or null when nothing was written. */
  notebook: string | null;
  /** One entry per kind of the catalogue, including the ones nobody answered. */
  anchors: DayAnchors;
  /** null when nothing is recorded for this date — not the same as a skip. */
  training: TrainingDay | null;
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
/** One role over a period: minutes, share, the target and the gap from it. */
export interface RoleSummarySlice {
  role_id: number;
  role_code: string;
  title: string;
  minutes: number;
  share_pct: number;
  /** Гипотеза квартала, не норма периода. */
  target_share_pct: number | null;
  /** Доля минус целевая, в пунктах; null — целевой нет. */
  delta_pct: number | null;
  /** Акты по видам за период. */
  act_counts: Record<string, number>;
  act_total: number;
}

/**
 * The fold of a period — what the Friday report is assembled from.
 *
 * `markdown` is the finished block, rendered on the server. The screen shows
 * that very text rather than building its own: a second formatter would drift
 * from the first on the first edit of the target shares, and silently.
 */
export interface RoleSummary {
  date_from: string;
  date_to: string;
  total_minutes: number;
  roles: RoleSummarySlice[];
  unassigned_minutes: number;
  unassigned_share_pct: number;
  window_from: string;
  window_minutes: number;
  window_unassigned_share_pct: number;
  lag_threshold_pct: number;
  /** Правила разметки отстали: доля `unassigned` за окно выше порога. */
  rules_lag: boolean;
  markdown: string;
}

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

  /**
   * Свёртка ролей за произвольный период — неделя, месяц, что угодно.
   *
   * Готовый текст пятничного отчёта приезжает полем `markdown` того же ответа,
   * поэтому второго запроса за ним нет и второго форматирования — тоже.
   */
  summary: async (dateFrom: string, dateTo: string) => {
    return fetcher<RoleSummary>(
      `/roles/summary?date_from=${dateFrom}&date_to=${dateTo}`
    );
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

/**
 * What one conversation has cost the subscription so far.
 *
 * Three counters rather than one total: a token read from the cache is not
 * priced like a fresh input token, and the sum would hide the very effect the
 * number is shown for — the second turn being cheaper than the first.
 */
export interface ChatUsage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  message_count: number;
  latency_ms_median: number | null;
}

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
  usage: ChatUsage;
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
  /**
   * What the model pulled while answering this message.
   *
   * Name, parameters and size — never the data. The row exists to answer «какие
   * мои данные покинули сервер» without reading the data itself, and a field
   * carrying the rows back would undo exactly that.
   */
  retrievals?: ChatRetrieval[];
}

/** One named retrieval as the audit trail records it. */
export interface ChatRetrieval {
  id: number;
  query_name: string;
  params: Record<string, unknown>;
  row_count: number;
  chars: number;
  created_at: string;
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
  /**
   * Whether the next turn continues the CLI session or rebuilds the dialogue
   * from the table. Computed by the server on every read: the session file can
   * disappear between two turns, and four conditions the browser cannot see
   * stand behind this one flag.
   */
  resume_ready: boolean;
}

/**
 * Что чат видит: карточка дня тем же текстом, каким она ушла в системный промпт.
 *
 * `text` не пересказ — раскрывашка «что чат видит» существует ровно затем, чтобы
 * фразу из ответа модели можно было найти здесь глазами. `dropped_sections`
 * называет секции, у которых потолок съел строки.
 */
export interface ChatContext {
  conversation_id: number;
  entry_date: string;
  text: string;
  chars: number;
  max_chars: number;
  truncated: boolean;
  dropped_sections: string[];
}

export const chatAPI = {
  list: async (limit = 50) => {
    return fetcher<ChatConversation[]>(`/chat/conversations?limit=${limit}`);
  },

  /**
   * Start a conversation.
   *
   * `started_on` is the day the conversation is about, and it travels
   * explicitly: the server defaults it to its own today, which is the wrong
   * day for a question asked from a Today screen showing an earlier date.
   * Omitting it keeps that server default, which is what the bare chat screen
   * wants.
   */
  /**
   * Start a conversation.
   *
   * `started_on` is the day the conversation is about, and it travels
   * explicitly: the server defaults it to its own today, which is the wrong
   * day for a question asked from a Today screen showing an earlier date.
   * Omitting it keeps that server default, which is what the bare chat screen
   * wants.
   */
  create: async (
    options: { kind?: ConversationKind; started_on?: string } = {}
  ) => {
    const { kind = 'general', started_on } = options;
    return fetcher<ChatConversation>('/chat/conversations', {
      method: 'POST',
      body: JSON.stringify(started_on === undefined ? { kind } : { kind, started_on }),
    });
  },

  get: async (id: number) => {
    return fetcher<ChatConversationDetail>(`/chat/conversations/${id}`);
  },

  /**
   * Unstick a dialogue whose turn nobody will ever close.
   *
   * The case is narrow and real: the worker died together with the CLI
   * process, so the answer row stayed `streaming` and every later POST is a
   * 409. Returns how many turns were reset — zero means the dialogue was free
   * all along, which is worth showing rather than hiding behind a 204.
   */
  reset: async (id: number) => {
    return fetcher<{ reset: number }>(`/chat/conversations/${id}/reset`, {
      method: 'POST',
    });
  },

  /** Карточка дня разговора — то, что модель увидела перед ответом. */
  context: async (id: number) => {
    return fetcher<ChatContext>(`/chat/conversations/${id}/context`);
  },

  /**
   * Delete one conversation — rows and the CLI session file both.
   *
   * 204 carries no body, and `fetcher` is fine with that; what the server does
   * to the `.jsonl` on disk is a machine code in its log, not a status here.
   */
  remove: async (id: number) => {
    return fetcher<Record<string, never>>(`/chat/conversations/${id}`, {
      method: 'DELETE',
    });
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
      // Same as every `fetcher` call: the browser authenticates by the session
      // cookie of #109, and a turn sent without it is a 401 in mid-conversation.
      credentials: 'include',
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

// -- Days range and weeks ---------------------------------------------------

/**
 * One day of a range, in the shape the old `/api/days` answered with.
 *
 * `verdict` carries three states, not two: `won`, `lost` and `null` — «день не
 * закрыт». The square of the timeline is painted from this field alone, which
 * is what `life.py` could not do while it was reading prose with a regexp.
 */
export interface DayListItem {
  date: string;
  /** Title of the day's plan; empty when there is no plan or it had none. */
  title: string;
  verdict: Verdict | null;
  /** Work tasks closed, and work tasks planned. */
  done: number;
  total: number;
}

/** One line of «На разбор в воскресенье», with its own tick. */
export interface WeekReviewItem {
  id: string;
  ord: number;
  text_md: string;
  done: boolean;
}

/**
 * One week as a fixed snapshot: counters taken at `computed_at`, prose beside
 * them. Reopening a day moves the counters and leaves the prose alone.
 */
export interface Week {
  iso_code: string;
  starts_on: string;
  ends_on: string;
  won_days: number;
  total_days: number;
  /** null when no day of the week was closed — not the same as a streak of 0. */
  streak_end: number | null;
  retro_md: string;
  blockers_md: string;
  mgmt_retro_md: string;
  weekly_number_md: string;
  review_items: WeekReviewItem[];
  computed_at: string;
}

/** What a week write says. The counters are the server's and cannot be sent. */
export interface WeekDraft {
  retro_md?: string;
  blockers_md?: string;
  mgmt_retro_md?: string;
  weekly_number_md?: string;
  review_items?: { text_md: string; done: boolean }[];
}

export const daysAPI = {
  /**
   * The days of `[from, to]`, oldest first.
   *
   * One request for a whole range rather than one per square: the timeline
   * draws a year at a time and the sidebar the whole history.
   */
  range: async (from: string, to: string) => {
    return fetcher<DayListItem[]>(`/days?from=${from}&to=${to}`);
  },
};

export const weeksAPI = {
  /** One week by its ISO code. A week nobody wrote about answers too. */
  get: async (iso: string) => {
    return fetcher<Week>(`/weeks/${iso}`);
  },

  /** The week the server's day boundary says is running. */
  getCurrent: async () => {
    return fetcher<Week>('/weeks');
  },

  /** Replace the retro of a week; the counters stay the server's. */
  put: async (iso: string, draft: WeekDraft) => {
    return fetcher<Week>(`/weeks/${iso}`, {
      method: 'PUT',
      body: JSON.stringify(draft),
    });
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

// -- Anchors and training --------------------------------------------------

/**
 * What an anchor of a day can say. Absence of an answer is `null`, not a word.
 *
 * The same three words a plan mark uses, and deliberately the same type: the
 * anchor box and the mark box sit one above the other on the day screen, walk
 * the same ring, and a second vocabulary that happened to coincide would be one
 * edit away from not coinciding.
 */
export type AnchorState = MarkState;

/**
 * One anchor of one day.
 *
 * Every kind of the catalogue arrives, answered or not: «вечера с близкими
 * сегодня не было» has to read differently from «про вечер с близкими не
 * спрашивали», and the second is where the third priority of `config.md` spent
 * its whole existence.
 */
export interface DayAnchor {
  kind: string;
  title: string;
  ord: number;
  counts_for_verdict: boolean;
  /** True for `relationship`: the canon expects it in an evening that is not work. */
  required_in_nonwork_evening: boolean;
  state: AnchorState | null;
  note: string | null;
  /** The line of the plan this anchor is written on, when there is one. */
  item_id: string | null;
  /** Whether the canon of *this* day is judged by this kind at all. */
  required_today: boolean;
}

export interface DayAnchors {
  day_date: string;
  anchors: DayAnchor[];
  done: number;
  total: number;
  /** Titles of the anchors the day neither closed nor set aside. */
  missing: string[];
}

/** A write of one anchor; `state: null` takes the mark off. */
export interface AnchorMarkDraft {
  kind: string;
  state: AnchorState | null;
  note?: string | null;
}

/** What one date planned, did and set aside as its minimum. */
export interface TrainingDay {
  day_date: string;
  patterns: string[];
  heavy_patterns: string[];
  planned_md: string | null;
  done_md: string | null;
  skipped: boolean;
  outdoor_done: boolean | null;
  near_failure: boolean;
  note_md: string | null;
  minimum_md: string | null;
  /** The plan line the minimum is ticked on — its own tick, not the training's. */
  minimum_item_id: string | null;
  sets: Record<string, number>;
}

/** A write of one date's training; an absent field is left alone. */
export interface TrainingDayDraft {
  patterns?: string[];
  heavy_patterns?: string[];
  planned_md?: string | null;
  done_md?: string | null;
  skipped?: boolean;
  outdoor_done?: boolean | null;
  near_failure?: boolean;
  note_md?: string | null;
  minimum_md?: string | null;
  minimum_item_id?: string | null;
  sets?: Record<string, number>;
}

/** One complaint — a symptom that gates a suggestion, never a diagnosis. */
export interface BodyComplaint {
  id: string;
  opened_on: string;
  area: string;
  context: string | null;
  severity: string | null;
  status: 'open' | 'closed';
  closed_on: string | null;
  closed_reason: string | null;
}

export interface PersonalRecord {
  id: string;
  exercise: string;
  variant: string | null;
  sets: string | null;
  best_plain: number | null;
  achieved_on: string;
  target: string | null;
}

/** One movement that will not be suggested today, and the gate that removed it. */
export interface TrainingExclusion {
  exercise: string;
  gate: string;
  reason: string;
}

export interface TrainingGate {
  code: string;
  reason: string;
}

/**
 * What may be trained today, and why the list is what it is.
 *
 * The exclusions travel beside the offer rather than being subtracted in
 * silence: «сегодня без подтягиваний, плечо open с 10.08» is a sentence a
 * person can disagree with; a shorter list with no explanation is one that
 * gets ignored.
 */
export interface TrainingSuggestion {
  exercises: string[];
  excluded: TrainingExclusion[];
  gates: TrainingGate[];
  rir: string;
  volume_factor: number;
}

/** The derived snapshot of the body, recomputed on every read. */
export interface TrainingState {
  as_of: string;
  last_heavy_pull: string | null;
  last_heavy_push: string | null;
  last_legs: string | null;
  last_run: string | null;
  last_outdoor: string | null;
  last_cardio: string | null;
  near_failure_days: string[];
  week_sets: Record<string, number>;
  progression_stage: Record<string, string>;
  skipped_days: number;
  /** When the snapshot was folded — it is derived, and says so. */
  recomputed_at: string;
  open_complaints: BodyComplaint[];
  /** Personal records, most recent first — each with its date and its target. */
  records: PersonalRecord[];
  suggestion: TrainingSuggestion;
}

export const trainingAPI = {
  /** The state, its suggestion and the open complaints, in one request. */
  getState: async () => {
    return fetcher<TrainingState>('/training/state');
  },

  /** Write the one authored part of the state — where the progression stands. */
  setProgression: async (progression_stage: Record<string, string>) => {
    return fetcher<TrainingState>('/training/state', {
      method: 'PUT',
      body: JSON.stringify({ progression_stage }),
    });
  },

  complaints: async (openOnly = false) => {
    return fetcher<BodyComplaint[]>(`/body-complaints?open_only=${openOnly}`);
  },

  openComplaint: async (draft: {
    area: string;
    context?: string | null;
    severity?: string | null;
    opened_on?: string | null;
  }) => {
    return fetcher<BodyComplaint>('/body-complaints', {
      method: 'POST',
      body: JSON.stringify(draft),
    });
  },

  /** Close a complaint — and return the movements it was taking out. */
  closeComplaint: async (id: string, closed_reason?: string) => {
    return fetcher<BodyComplaint>(`/body-complaints/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'closed', closed_reason }),
    });
  },

  records: async () => {
    return fetcher<PersonalRecord[]>('/personal-records');
  },
};


/** What a quick-mark button does when it is tapped. Mirrors `app/models/quick_mark.py`. */
export type QuickMarkKind = 'increment' | 'check' | 'set_value' | 'relapse';

/** Which client a tap came from; the backend records it on every event. */
export type QuickMarkSource = 'web' | 'ios' | 'agent' | 'plan';

/**
 * One button of the directory, already carrying the state of the day it was
 * read for.
 *
 * `today_total` is null for a tick — a box is not a quantity — and `done` is
 * the field both kinds answer. The client never sees `category_id` as a thing
 * to act on: what the button means is the server's business, and the only id a
 * tap sends is `id`.
 */
export interface QuickMark {
  id: number;
  label: string;
  category_id: number;
  field_id: number;
  kind: QuickMarkKind;
  step: number | null;
  unit_label: string | null;
  icon: string | null;
  color: string | null;
  hotkey: string | null;
  order: number;
  show_in_agent: boolean;
  is_active: boolean;
  entry_date: string;
  today_total: number | null;
  done: boolean;
  /**
   * The plan of `entry_date` names this button.
   *
   * Decided by the server, like the order it buys: the same one selection
   * serves the web, the agent window and iOS, and a flag computed in the
   * browser would be a flag the other two do not have.
   */
  planned: boolean;
  /** The plan line that named it; a tap on the button closes that line. */
  plan_item_id: string | null;
}

/** The recorded tap and the state it produced — one call per tap, no refetch. */
export interface QuickMarkEvent {
  event_id: number;
  quick_mark_id: number;
  entry_id: number | null;
  entry_date: string;
  occurred_at: string;
  today_total: number | null;
  done: boolean;
}

/** Which client is asking; `agent` gets only the buttons marked for it. */
export type QuickMarkSurface = 'web' | 'agent' | 'ios';

/**
 * A new button, or a patch of one.
 *
 * The same shape both ways: the create refuses a missing `label`, the patch
 * takes whatever it is given. `hotkey: null` in a patch takes the key off; a
 * key left out of the object does not touch it.
 */
export interface QuickMarkDraft {
  label?: string;
  category_id?: number;
  field_id?: number;
  kind?: QuickMarkKind;
  step?: number | null;
  unit_label?: string | null;
  icon?: string | null;
  color?: string | null;
  hotkey?: string | null;
  order?: number;
  show_in_agent?: boolean;
  is_active?: boolean;
}

/**
 * The body of a 409: the key is taken, and by which button.
 *
 * Named rather than counted, because the repair is "take it off that one" and
 * the person has to know which one that is without opening the database.
 */
export interface HotkeyTaken {
  error: 'hotkey_taken';
  message: string;
  hotkey: string;
  quick_mark_id: number;
  label: string;
}

/** A tap taken back, and the state the day is left in. */
export interface QuickMarkUndo {
  event_id: number;
  quick_mark_id: number;
  entry_date: string;
  undone_at: string;
  today_total: number | null;
  done: boolean;
}

/** How many taps one client contributed over the period, and how many were undone. */
export interface QuickMarkSourceUsage {
  source: QuickMarkSource;
  events: number;
  undone: number;
}


export interface QuickMarkTap {
  /** Overrides the button's step; for a tick, 0 unticks. */
  value?: number;
  source?: QuickMarkSource;
  utc_offset_minutes?: number;
}

export const quickMarksAPI = {
  /**
   * The directory with today's state on it.
   *
   * No date is sent: which day is running is the server's answer
   * (`local_date()`), and a browser that computed its own would disagree with
   * it between midnight and the boundary hour.
   *
   * `surface` narrows the list the way the asking client needs it; an unknown
   * value is a 422 rather than a full list, so a typo is found on the first
   * call instead of a month later.
   */
  list: async (options: { surface?: QuickMarkSurface; activeOnly?: boolean } = {}) => {
    const query = new URLSearchParams();
    if (options.surface) query.set('surface', options.surface);
    if (options.activeOnly === false) query.set('active_only', 'false');
    const suffix = query.size > 0 ? `?${query.toString()}` : '';
    return fetcher<QuickMark[]>(`/quick-marks${suffix}`);
  },

  /** Enter a button. 409 carries the button that holds the key it asked for. */
  create: async (draft: QuickMarkDraft) => {
    return fetcher<QuickMark>('/quick-marks', {
      method: 'POST',
      body: JSON.stringify(draft),
    });
  },

  /** Edit a button; only the fields sent are written. */
  update: async (id: number, draft: QuickMarkDraft) => {
    return fetcher<QuickMark>(`/quick-marks/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(draft),
    });
  },

  /**
   * Remove a button. Nothing it ever recorded is removed with it — the day's
   * values stay where they are, and only the button leaves the screen.
   */
  remove: async (id: number) => {
    return fetcher<Record<string, never>>(`/quick-marks/${id}`, {
      method: 'DELETE',
    });
  },

  /**
   * Reorder the directory by sending the ids top to bottom.
   *
   * A list rather than a number per button: order is a property of the list,
   * and a client that sends numbers eventually sends two of the same.
   */
  reorder: async (ids: number[]) => {
    return fetcher<QuickMark[]>('/quick-marks/order', {
      method: 'PATCH',
      body: JSON.stringify({ ids }),
    });
  },

  /**
   * Tap one button.
   *
   * `utc_offset_minutes` is stored, not obeyed — it explains a tap made abroad
   * and never decides the day it lands in.
   */
  tap: async (id: number, tap: QuickMarkTap = {}, idempotencyKey?: string) => {
    return fetcher<QuickMarkEvent>(`/quick-marks/${id}/events`, {
      method: 'POST',
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
      body: JSON.stringify({
        source: 'web',
        utc_offset_minutes: -new Date().getTimezoneOffset(),
        ...tap,
      }),
    });
  },

  /**
   * Take the last tap back.
   *
   * One call, and its answer carries the state the day is left in, exactly as a
   * tap does — the row repaints from it rather than refetching the directory.
   * A 409 is not a failure of the request but the server's answer that this tap
   * is no longer the one that can be undone; the caller shows the reason.
   */
  undo: async (eventId: number) => {
    return fetcher<QuickMarkUndo>(`/quick-marks/events/${eventId}/undo`, {
      method: 'POST',
    });
  },

  /** How the taps of a period split between the clients that made them. */
  sources: async (params: { from?: string; to?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.from) query.set('from', params.from);
    if (params.to) query.set('to', params.to);
    const suffix = query.toString();
    return fetcher<QuickMarkSourceUsage[]>(
      `/quick-marks/events/sources${suffix ? `?${suffix}` : ''}`
    );
  },
};
