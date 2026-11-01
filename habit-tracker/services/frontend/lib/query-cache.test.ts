// [review:need-review] #311
// summary: tests for the shared read cache — a re-visit draws the cached data in its first frame, readers of one key mounted together cost one request, a late answer never overwrites a newer one or a local write, and a cleared cache shows nothing of the previous session

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import {
  clearQueryCache,
  fetchQuery,
  getQueryData,
  invalidateQueries,
  setQueryData,
  useQuery,
  type QueryState,
} from '@/lib/query-cache';

afterEach(() => {
  cleanup();
});

/** A promise and the hands that settle it, so a test decides the order of answers. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const never = <T,>() => new Promise<T>(() => {});

describe('useQuery: a re-visited screen', () => {
  it('draws the cached data in the first frame while the source does not answer', async () => {
    const first = renderHook(() => useQuery('goals', () => Promise.resolve(['M1'])));
    await waitFor(() => expect(first.result.current.state.status).toBe('ready'));
    first.unmount();

    const frames: QueryState<string[]>[] = [];
    const source = mock(() => never<string[]>());
    renderHook(() => {
      const { state } = useQuery('goals', source);
      frames.push(state);
      return state;
    });

    expect(frames[0]).toMatchObject({ status: 'ready', data: ['M1'] });
  });

  it('re-reads behind the cached data once the revalidation window has passed', async () => {
    setQueryData('week:current', 'old');
    const realNow = Date.now;
    Date.now = () => realNow() + 60_000;
    try {
      const source = mock(() => Promise.resolve('new'));
      const { result } = renderHook(() => useQuery('week:current', source));
      expect(result.current.state).toMatchObject({ status: 'ready', data: 'old', refreshing: true });
      await waitFor(() => expect(result.current.state).toMatchObject({ data: 'new', refreshing: false }));
      expect(source).toHaveBeenCalledTimes(1);
    } finally {
      Date.now = realNow;
    }
  });

  it('shows the spinner state only while there is nothing to draw', () => {
    const { result } = renderHook(() => useQuery('journal', () => never<string>()));
    expect(result.current.state.status).toBe('loading');
  });
});

describe('useQuery: readers of one key mounted together', () => {
  for (const readers of [1, 3, 10]) {
    it(`${readers} reader(s) in one render cost exactly one request`, async () => {
      const source = mock(() => Promise.resolve(['sport']));
      const { result } = renderHook(() =>
        Array.from({ length: readers }, () => useQuery('categories:active', source).state)
      );
      await waitFor(() => expect(result.current.every((state) => state.status === 'ready')).toBe(true));
      expect(source).toHaveBeenCalledTimes(1);
    });
  }
});

describe('fetchQuery: the newest answer wins', () => {
  it('drops a late answer of an older request', async () => {
    const older = deferred<string>();
    const newer = deferred<string>();
    void fetchQuery('day:2026-11-01', () => older.promise);
    // A write elsewhere made the first read stale: the next one is a request of its own.
    invalidateQueries('day:');
    void fetchQuery('day:2026-11-01', () => newer.promise);

    await act(async () => {
      newer.resolve('fresh');
      await newer.promise;
    });
    await act(async () => {
      older.resolve('stale');
      await older.promise;
    });

    expect(getQueryData<string>('day:2026-11-01')).toBe('fresh');
  });

  it('keeps a local write over an answer taken before it', async () => {
    const read = deferred<number>();
    void fetchQuery('quickMarks', () => read.promise);
    setQueryData('quickMarks', 5);

    await act(async () => {
      read.resolve(4);
      await read.promise;
    });

    expect(getQueryData<number>('quickMarks')).toBe(5);
  });

  it('keeps the data through a failed re-read and says the re-read failed', async () => {
    setQueryData('dashboard:week', 'numbers');
    const { result } = renderHook(() => useQuery('dashboard:week', () => Promise.reject(new Error('offline'))));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.state).toMatchObject({ status: 'ready', data: 'numbers', refreshing: false });
    expect((result.current.state as { error: Error }).error.message).toBe('offline');
  });
});

describe('clearQueryCache: the session ended', () => {
  it('leaves nothing to draw, and an answer that was out lands nowhere', async () => {
    setQueryData('journal', ['previous user']);
    const late = deferred<string[]>();
    void fetchQuery('journal', () => late.promise, { maxAge: 0 }).catch(() => {});
    // `maxAge: 0` asks the server even though data is cached: a request is out when the session ends.
    clearQueryCache();
    await act(async () => {
      late.resolve(['previous user, late']);
      await late.promise;
    });

    expect(getQueryData('journal')).toBeUndefined();
    const { result } = renderHook(() => useQuery('journal', () => never<string[]>()));
    expect(result.current.state.status).toBe('loading');
  });

  it('turns a mounted reader back to loading', async () => {
    const { result } = renderHook(() => useQuery('goals', () => Promise.resolve(['M1'])));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    act(() => {
      clearQueryCache();
    });
    expect(result.current.state.status).toBe('loading');
  });
});
