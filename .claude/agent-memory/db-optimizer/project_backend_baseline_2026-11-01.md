---
name: backend-baseline-2026-11-01
description: Baseline SQL/latency numbers of iOS-facing backend endpoints (40 cats x 365 days) and how the scout stand was built — use as "before" for any optimization of /table, /days, /dashboard/summary, /quick-marks
metadata:
  type: project
---

Scout 2026-11-01 (local stand, 40 categories x 365 days, ~9.7k entries, 19k values, 7.3k plan items), p50 ms / SQL:
- GET /table 365d: 187 ms, 3 SQL, 1.5 MB raw (41 KB gzip) — iOS CategoryDetail chart asks all categories for a year.
- GET /days 4y (Life): 173 ms, SQL 6->7 (selectinload chunks of 500); plan ORM load 117 ms vs 7 ms with a column projection.
- GET /dashboard/summary: 116 ms, 9 SQL constant; _load_histories reads every value of all history in Python (57 ms/call vs 11 ms SQL aggregate).
- GET /quick-marks: SQL 8->32 (per-button day_state, documented as deliberate in docstring); ETag computed after all SQL.
- Writes (POST /entries, PUT checklist, quick-mark tap): ~3 ms, 6-8 SQL, no sync side work.
- No GZipMiddleware; prod is bare uvicorn single process (Dockerfile).

**Why:** owner sees every extra 100 ms over Tailscale; these are the "before" numbers.
**How to apply:** compare after-numbers against these on the same volume. Stand gotchas: run uvicorn NOT from services/backend cwd (pydantic loads its .env); set LLM_BACKEND=api with empty ANTHROPIC_API_KEY so no real AI; fieldtype enum values in SQL are uppercase ('BOOLEAN'); rm/pkill in scratchpad are permission-denied — kill by PID, expect temp files to stay. Full report was scratchpad scout-backend.md (session-scoped, may be gone). Related: [[backend-sql-count-tests]]
