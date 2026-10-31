---
name: project-backend-suite-runtime
description: Full backend pytest in a swarm worktree takes ~16 min, has no pytest-xdist; run it in background and wait with an until-loop
metadata:
  type: project
---

Full backend `pytest tests/` (≈3470 tests, Postgres on 55432) took 15:40 on 2026-10-30; `-n auto` fails — pytest-xdist is not installed.

**Why:** a foreground Bash call times out at 10 min, and chaining `sleep` is blocked by the harness.
**How to apply:** start the full suite with `run_in_background: true`, keep the short loop to `tests/test_health*.py`-style subsets, and do iOS/web work while it runs. Related: [[ios-simulator-limit]].
