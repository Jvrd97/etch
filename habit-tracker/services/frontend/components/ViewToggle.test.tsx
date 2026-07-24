// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/42-mobile-categories-and-detail
// summary: tests for the cold-start restore of ViewToggle — it must redirect into the mobile twin and carry the query string along

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, waitFor } from '@testing-library/react';
import { VIEW_MODE_STORAGE_KEY } from '@/lib/view-mode';

let pathname: string;
let searchParams: URLSearchParams;
let replace: ReturnType<typeof mock>;
let push: ReturnType<typeof mock>;

// Same process-wide replacement rule as the API mock: the hooks other suites
// import have to stay present even though this component never calls them.
mock.module('next/navigation', () => ({
  usePathname: () => pathname,
  useSearchParams: () => searchParams,
  useRouter: () => ({ replace, push }),
  useParams: () => ({}),
}));

const { default: ViewToggle } = await import('./ViewToggle');

beforeEach(() => {
  pathname = '/entries';
  searchParams = new URLSearchParams();
  replace = mock(() => {});
  push = mock(() => {});
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, 'mobile');
});

afterEach(() => {
  cleanup();
});

describe('ViewToggle cold-start restore', () => {
  it('redirects into the mobile twin of the current route', async () => {
    render(<ViewToggle />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith('/m/entries'));
  });

  it('keeps the query string when it swaps the route for its mobile twin', async () => {
    searchParams = new URLSearchParams('new=1');
    render(<ViewToggle />);

    // Dropping it here turns a "+ / log an entry" deep link into a plain list:
    // the restore fires before the screen ever reads ?new=1.
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/m/entries?new=1'));
  });

  it('does not redirect when the stored preference is desktop', async () => {
    window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, 'desktop');
    render(<ViewToggle />);

    await waitFor(() => expect(window.sessionStorage.length).toBeGreaterThan(0));
    expect(replace).not.toHaveBeenCalled();
  });
});
