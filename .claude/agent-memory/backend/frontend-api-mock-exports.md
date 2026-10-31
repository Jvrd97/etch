---
name: frontend-api-mock-exports
description: bun test freezes the export list of '@/lib/api' at the first mock.module; a new top-level export imported by a screen breaks other suites at link time
metadata:
  type: project
---

35 frontend test files mock `@/lib/api` with a fixed object. Bun fixes a mocked module's export names for the whole run, so a named import of an export the mock lacks fails at link time: `SyntaxError: Export named 'X' not found` (seen for `healthAPI` at baseline 8dc958d).

**Why:** the full `bun test` runs every file in one process. A screen hook that imports a new `fooAPI` from `@/lib/api` breaks whichever suite renders that screen after a mocking suite has run.

**How to apply:** a new API client used by a day/today screen goes through `import * as api from '@/lib/api'`, read at call time, plus an injectable client for its own hook test (see `hooks/usePlanFacts.ts`, #200). Do not import `APIError` as a value in shared helpers either: read the error's `detail` by shape. The other way is to add the stub to all 35 mocks, which collides with every other swarm worker.
