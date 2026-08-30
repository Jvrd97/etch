# [review:need-review] PHASE-03/106
# summary: keys compared as bytes (a non-ASCII header gives 401, not 500); the dev-mode warning moved to startup
"""
API-key authentication.

All API routers depend on `require_api_key`. The expected key comes from the
`API_KEY` env var; an empty value disables auth and is reachable in development
only — `ENVIRONMENT=prod` refuses to start with it (see `app.core.config`).
The key value itself is never logged.

Two details that look cosmetic and are not:

* both sides are compared as bytes. `secrets.compare_digest` raises TypeError
  on non-ASCII `str`, and Starlette decodes headers as latin-1, so a header
  with Cyrillic in it used to end as 500 — an unauthenticated caller could tell
  a malformed key from a wrong one by the status code alone.
* the "auth is disabled" warning is printed once on startup
  (`warn_if_auth_disabled`), not per request: a line repeated on every request
  stops being read within a minute of a dev session.
"""

import logging
import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

_warned_auth_disabled = False


def warn_if_auth_disabled() -> None:
    """Say once, on startup, that an empty API_KEY leaves the API unauthenticated."""
    global _warned_auth_disabled
    if settings.API_KEY or _warned_auth_disabled:
        return
    _warned_auth_disabled = True
    logger.warning("API_KEY is not set; auth is DISABLED (dev mode)")


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Reject the request with 401 unless a valid X-API-Key header is present."""
    if not settings.API_KEY:
        return
    if x_api_key is None or not secrets.compare_digest(
        x_api_key.encode("utf-8"), settings.API_KEY.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )
