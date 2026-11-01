// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today, #311
// summary: bun:test preload — registers happy-dom globals so React hooks can be rendered in tests, and empties the shared read cache after every test

import { afterEach } from 'bun:test';
import { GlobalRegistrator } from '@happy-dom/global-registrator';
import { clearQueryCache } from '@/lib/query-cache';

if (typeof document === 'undefined') {
  GlobalRegistrator.register();
}

// React 19 renders through act(); without this flag it warns on every update.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Pin the real export set of the shared API module before any test mocks it, so a
// partial mock cannot strip an export from the files that link after it.
await import('@/lib/api');

// The read cache lives at module level for the whole run: without this a test
// would draw the data the previous one fetched instead of asking its own mock.
afterEach(() => {
  clearQueryCache();
});
