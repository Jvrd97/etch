---
name: swarm-live-check-guards
description: In swarm runs the Blast Radius guard holds `alembic upgrade` on habit_live_<id> and any `rm`; how the #200 live check still got done and what to report
metadata:
  type: project
---

On 2026-10-25 (swarm from 8dc958d) the guard held two commands for 10 minutes without an answer: `alembic upgrade head` against `habit_live_200` and a temp-file `rm -f`. A held command must not be retried unless the user asks.

**Why:** migrations and deletions need the user's approval, and the user is often away during a swarm.

**How to apply:** for a live UI check, the swarm test DB `habit_test_<id>` already carries the current schema from pytest's `create_all`. Seed the canon rows with a scratchpad script calling `day_crud.seed_rules`, run uvicorn on the worker's port against it, and drive a headless Chrome (own `--user-data-dir` in the scratchpad) through CDP from a bun script for screenshots at 1440 px and 390 px. A scratchpad script run by `uv run --directory <backend>` needs `env PYTHONPATH=<backend>`, or `import app` fails. Say in the report that the live copy was not migrated and that the check ran on the test DB. Avoid `rm` in commands: leave temp files in the scratchpad. Under swarm load (load average 150–340) frontend `PlanBuilder` tests time out at 5 s even when run alone; that is load, not a regression.
