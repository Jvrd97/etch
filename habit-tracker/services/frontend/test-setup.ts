// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: bun:test preload — registers happy-dom globals so React hooks can be rendered in tests

import { GlobalRegistrator } from '@happy-dom/global-registrator';

if (typeof document === 'undefined') {
  GlobalRegistrator.register();
}

// React 19 renders through act(); without this flag it warns on every update.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
