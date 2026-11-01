// [review:need-review] #311
// summary: the screens' shared read cache, in memory only — one entry per key with its data, the time it was taken and the request in flight; readers of one key join that request instead of asking again, only the newest answer (or a later local write) lands, a re-visited screen draws what it already has and re-reads behind it, and the whole cache is dropped on logout or 401

/**
 * Why a cache at all: every screen used to read everything again on each visit
 * and hold a spinner until the slowest answer, and the same list (categories,
 * the quick-mark directory) was asked for by several hooks of one page.
 *
 * Memory only, on purpose. Keeping a user's data on the device (localStorage,
 * IndexedDB) is the owner's decision, not this module's; a reload starts empty.
 *
 * Nothing here reads the API, so `lib/api` can clear the cache on a 401
 * without an import cycle.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';

/**
 * What a screen draws from one key.
 *
 * `ready` keeps the data through a re-read (`refreshing`) and through a failed
 * re-read (`error`): numbers one round trip old are a better screen than a
 * spinner or a banner instead of them. `error` alone means there is nothing to
 * draw and the read failed.
 */
export type QueryState<T> =
  | { status: 'loading' }
  /** `answeredAt`: `Date.now()` the data landed (a server answer or a local write). */
  | { status: 'ready'; data: T; refreshing: boolean; error: unknown; answeredAt: number }
  | { status: 'error'; error: unknown };

type Source<T> = () => Promise<T>;

interface CacheEntry {
  data: unknown;
  hasData: boolean;
  /** `Date.now()` of the answer (or local write) the data came from; 0 marks it stale. */
  updatedAt: number;
  /** Like `updatedAt`, but an invalidation leaves it: how old the data really is. */
  answeredAt: number;
  /** The read of the newest request, so an invalidation can ask again with it. */
  lastSource: Source<unknown> | null;
  error: unknown;
  inflight: Promise<unknown> | null;
  /** `Date.now()` the request in flight was started at. */
  inflightSince: number;
  /** Sequence number of the newest request started for this key. */
  started: number;
  /** Sequence number of the newest answer or local write that landed. */
  applied: number;
  snapshot: QueryState<unknown>;
}

/**
 * A re-visit within this window draws the cached data without asking again.
 *
 * Not a freshness promise: it is what keeps ten readers of one key, mounted a
 * moment after the first answer, from turning into ten more requests. Anything
 * older is drawn at once and re-read behind it.
 */
export const REVALIDATE_AFTER_MS = 2_000;

/**
 * A request out longer than this is not joined any more: a fetch that hangs must
 * not answer every later reader of its key. The next read starts a new request,
 * and whichever of the two answers later is dropped if it is the older one.
 */
export const JOIN_LIMIT_MS = 15_000;

const LOADING: QueryState<never> = { status: 'loading' };

const entries = new Map<string, CacheEntry>();
const listeners = new Map<string, Set<() => void>>();
/** Global order of requests and writes; per-key comparison decides who lands. */
let sequence = 0;
/** Bumped by `clearQueryCache`: an answer of an older generation lands nowhere. */
let generation = 0;

function entryOf(key: string): CacheEntry {
  let entry = entries.get(key);
  if (entry === undefined) {
    entry = {
      data: undefined,
      hasData: false,
      updatedAt: 0,
      answeredAt: 0,
      lastSource: null,
      error: null,
      inflight: null,
      inflightSince: 0,
      started: 0,
      applied: 0,
      snapshot: LOADING,
    };
    entries.set(key, entry);
  }
  return entry;
}

function snapshotFor(entry: CacheEntry): QueryState<unknown> {
  const refreshing = entry.inflight !== null;
  if (entry.hasData) {
    return { status: 'ready', data: entry.data, refreshing, error: entry.error, answeredAt: entry.answeredAt };
  }
  if (refreshing || entry.error === null) return LOADING;
  return { status: 'error', error: entry.error };
}

function publish(key: string): void {
  const entry = entries.get(key);
  if (entry !== undefined) entry.snapshot = snapshotFor(entry);
  for (const listener of listeners.get(key) ?? []) listener();
}

function start<T>(key: string, entry: CacheEntry, source: Source<T>): Promise<T> {
  sequence += 1;
  const mine = sequence;
  const born = generation;
  entry.started = mine;
  entry.lastSource = source;
  const request: Promise<T> = Promise.resolve()
    .then(source)
    .then(
      (data) => {
        settle(() => {
          if (mine <= entry.applied) return;
          entry.applied = mine;
          entry.data = data;
          entry.hasData = true;
          entry.updatedAt = Date.now();
          entry.answeredAt = entry.updatedAt;
          entry.error = null;
        });
        return data;
      },
      (error: unknown) => {
        settle(() => {
          // Only the failure of the newest request speaks for the key.
          if (mine === entry.started && mine > entry.applied) entry.error = error;
        });
        throw error;
      }
    );
  entry.inflight = request;
  entry.inflightSince = Date.now();
  publish(key);
  return request;

  function settle(land: () => void) {
    // The cache was cleared while this request was out: its answer belongs to a session that is gone.
    if (born !== generation) return;
    land();
    if (entry.inflight === request) entry.inflight = null;
    publish(key);
  }
}

export interface FetchOptions {
  /** Data younger than this is returned without asking. */
  maxAge?: number;
  /**
   * Start a request of its own instead of joining one already out: the caller has
   * just written, and a request sent before the write cannot carry it.
   */
  fresh?: boolean;
}

/**
 * Read `key` through the cache.
 *
 * A request already in flight for the key is joined, not repeated. Data younger
 * than `maxAge` is returned as it is. Otherwise a new request starts. The promise
 * rejects with the read's own error; the entry records it either way.
 */
export function fetchQuery<T>(
  key: string,
  source: Source<T>,
  { maxAge = 0, fresh = false }: FetchOptions = {}
): Promise<T> {
  const entry = entryOf(key);
  if (!fresh && entry.inflight !== null && Date.now() - entry.inflightSince < JOIN_LIMIT_MS) {
    return entry.inflight as Promise<T>;
  }
  if (entry.hasData && Date.now() - entry.updatedAt < maxAge) {
    return Promise.resolve(entry.data as T);
  }
  return start(key, entry, source);
}

/** The data cached under `key`, or undefined when there is none. */
export function getQueryData<T>(key: string): T | undefined {
  const entry = entries.get(key);
  return entry?.hasData ? (entry.data as T) : undefined;
}

/**
 * Write `key` locally — an optimistic change, or an answer a write returned.
 *
 * A local write is newer than any request already out for the key: that
 * request's answer was taken before the write and is dropped when it lands, and
 * the next read starts a request of its own instead of joining it.
 */
export function setQueryData<T>(key: string, next: T | ((previous: T | undefined) => T)): void {
  const entry = entryOf(key);
  const previous = entry.hasData ? (entry.data as T) : undefined;
  entry.data = typeof next === 'function' ? (next as (previous: T | undefined) => T)(previous) : next;
  entry.hasData = true;
  entry.updatedAt = Date.now();
  entry.answeredAt = entry.updatedAt;
  entry.error = null;
  sequence += 1;
  entry.applied = sequence;
  entry.inflight = null;
  publish(key);
}

/**
 * Mark every key starting with `prefix` stale after a write changed it.
 *
 * The data stays on screen until the next read; a request already out is
 * dropped (it predates the write), and the next read asks the server.
 */
export function invalidateQueries(prefix: string): void {
  for (const [key, entry] of entries) {
    if (!key.startsWith(prefix)) continue;
    entry.updatedAt = 0;
    sequence += 1;
    entry.applied = sequence;
    // A first load that was out has nothing on screen to fall back to: its
    // answer is dropped, so it is asked again rather than left loading for good.
    const retry = !entry.hasData && entry.inflight !== null ? entry.lastSource : null;
    entry.inflight = null;
    if (retry !== null) void start(key, entry, retry).catch(recordedInEntry);
    else publish(key);
  }
}

/**
 * Forget everything: the session ended (logout, 401).
 *
 * Readers still mounted fall back to `loading`, and answers of requests that
 * were out when this ran are dropped, so the next person on this tab never sees
 * the previous one's data.
 */
export function clearQueryCache(): void {
  generation += 1;
  entries.clear();
  for (const key of listeners.keys()) publish(key);
}

/**
 * A rejection already stored in the entry: the snapshot carries it to the screen,
 * so the background caller has nothing more to do with it.
 */
function recordedInEntry(): void {}

function subscribeKey(key: string, listener: () => void): () => void {
  let set = listeners.get(key);
  if (set === undefined) {
    set = new Set();
    listeners.set(key, set);
  }
  set.add(listener);
  return () => {
    set.delete(listener);
    if (set.size === 0) listeners.delete(key);
  };
}

function noSubscription(): () => void {
  return () => {};
}

function loadingSnapshot(): QueryState<never> {
  return LOADING;
}

export interface QueryHandle<T> {
  state: QueryState<T>;
  /**
   * Read the key again with a request of its own — what a screen calls after a
   * write or to retry; resolves when it has settled. The tab coming back joins a
   * request already out instead.
   */
  refresh: () => Promise<void>;
}

export interface UseQueryOptions {
  /** Read again when the tab or the installed app comes back into view. */
  refreshOnVisible?: boolean;
  /**
   * Cached data older than this (counted from the reader's mount) is not drawn:
   * the reader waits as if there were none. For data that goes stale with the
   * clock — today's day, which turns at 04:00 — where drawing yesterday would let
   * the screen write into it.
   */
  trustFor?: number;
}

/**
 * Subscribe a screen to `key`.
 *
 * The first frame of a re-visit is already `ready` with the cached data; the read
 * behind it only flips `refreshing`. A null `key` reads nothing and stays
 * `loading` (the argument it needs is not known yet). `source` may change identity
 * between renders; the newest one is used.
 */
export function useQuery<T>(
  key: string | null,
  source: Source<T>,
  { refreshOnVisible = false, trustFor }: UseQueryOptions = {}
): QueryHandle<T> {
  const [mountedAt] = useState(() => Date.now());
  const sourceRef = useRef(source);
  useEffect(() => {
    sourceRef.current = source;
  });

  const subscribe = useCallback(
    (listener: () => void) => (key === null ? noSubscription() : subscribeKey(key, listener)),
    [key]
  );
  const getSnapshot = useCallback(
    () => (key === null ? LOADING : (entries.get(key)?.snapshot ?? LOADING)),
    [key]
  );
  const cached = useSyncExternalStore(subscribe, getSnapshot, loadingSnapshot) as QueryState<T>;
  const state = trustFor === undefined ? cached : distrustOlder(cached, mountedAt - trustFor);

  useEffect(() => {
    if (key === null) return;
    void fetchQuery(key, () => sourceRef.current(), { maxAge: REVALIDATE_AFTER_MS }).catch(recordedInEntry);
  }, [key]);

  const refresh = useCallback(async () => {
    if (key === null) return;
    await fetchQuery(key, () => sourceRef.current(), { fresh: true }).then(recordedInEntry, recordedInEntry);
  }, [key]);

  const refreshWhenVisible = useCallback(() => {
    if (key === null || !refreshOnVisible) return;
    void fetchQuery(key, () => sourceRef.current()).catch(recordedInEntry);
  }, [key, refreshOnVisible]);
  useRefreshOnVisible(refreshWhenVisible);

  return { state, refresh };
}

/**
 * Subscribe to the data of `key` without reading it: for state a screen writes
 * itself (taps in flight) or a key another hook of the same screen reads.
 */
export function useQueryData<T>(key: string): T | undefined {
  const subscribe = useCallback((listener: () => void) => subscribeKey(key, listener), [key]);
  const getSnapshot = useCallback(() => entries.get(key)?.snapshot ?? LOADING, [key]);
  const state = useSyncExternalStore(subscribe, getSnapshot, loadingSnapshot) as QueryState<T>;
  return state.status === 'ready' ? state.data : undefined;
}

/** A state whose data landed before `before` is shown as if there were no data. */
function distrustOlder<T>(state: QueryState<T>, before: number): QueryState<T> {
  if (state.status !== 'ready' || state.answeredAt >= before) return state;
  if (state.refreshing || state.error === null || state.error === undefined) return LOADING;
  return { status: 'error', error: state.error };
}

/** The data of a state, or `fallback` while there is none. */
export function dataOr<T>(state: QueryState<T>, fallback: T): T {
  return state.status === 'ready' ? state.data : fallback;
}

/** The sentence of a state's error, or null when it has none. */
export function errorMessage(state: QueryState<unknown>, fallback: string): string | null {
  const error = state.status === 'loading' ? null : state.error;
  if (error === null || error === undefined) return null;
  return error instanceof Error ? error.message : fallback;
}
