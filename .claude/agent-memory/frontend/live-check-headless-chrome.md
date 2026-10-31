---
name: live-check-headless-chrome
description: How a frontend worker without browser tools checks a screen live - headless Chrome over CDP with real mobile emulation, and what to do when the live DB is not migrated
metadata:
  type: reference
---

Workers in the swarm have no browser MCP. Plain `chrome --headless --window-size=390,...` is wrong for mobile checks: headless Chrome clamps the window to about 500 px, so the page lays out wider than the screenshot and looks cut off at the right.

**How to apply:** start `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --headless=new --remote-debugging-port=<own port> --user-data-dir=<scratchpad dir>`, read `http://localhost:<port>/json/list`, talk CDP over a WebSocket from a Bun script (Bun has `WebSocket`). `Emulation.setDeviceMetricsOverride {width:390,height:844,deviceScaleFactor:2,mobile:true}` gives the true mobile layout; `Runtime.evaluate` clicks and reads the DOM; `Page.captureScreenshot` with a `clip` from `getBoundingClientRect()` shoots one element. Kill Chrome, the dev server and any stub at the end.

If `habit_live_<id>` has no tables and `alembic upgrade head` is held by the permission gate, do not retry it. Run the Next dev server (`API_PROXY_TARGET=http://localhost:<back port>`) against a small Bun stub API in the scratchpad that answers `/api/v1/auth/session`, `/categories`, `/streaks`, `/table`, `/entries`, `/journal`, and say in the handback that the check was against a stub, not the real backend.
