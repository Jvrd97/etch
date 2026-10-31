---
name: swarm-live-check
description: How a swarm worker can check UI live when no browser tool is attached and `alembic upgrade` on habit_live_<id> is held by the Blast Radius guard
metadata:
  type: project
---

In swarm runs (seen 2026-10-25, #207) `alembic upgrade head` on `habit_live_<id>` was held by the Blast Radius guard and timed out with no human answer; the guard says not to retry unless the user asks. The live check then ran the backend on `habit_test_<id>`, whose schema pytest had already created, and seeded data through the API.

**Why:** the subagent had no browser tool (no Chrome MCP or preview tool), but `/Applications/Google Chrome.app` exists, and the backend venv ships `websockets`.

**How to apply:** for a visual check, run headless Chrome (`--headless=new --remote-debugging-port=<port> --user-data-dir=<scratchpad>`) and drive it over CDP with a small Python script: viewport emulation, Runtime.evaluate, real clicks via Input.dispatchMouseEvent, and Page.captureScreenshot read back with Read. Before navigating, set localStorage `habit-tracker:view-mode` and sessionStorage `habit-tracker:view-mode-restored`, otherwise a stored mobile mode redirects /today to /m/today. The first visit to a route in `next dev` compiles for about 5 s, so wait longer before asserting. In the report, say that the check ran in headless Chrome, not on a device.
