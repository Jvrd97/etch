# [review:need-review] PHASE-03/106, PHASE-03/109
# summary: keys compared as bytes (a non-ASCII header gives 401, not 500); the dev-mode warning moved to startup; a valid session cookie is now accepted alongside X-API-Key
"""
Аутентификация: заголовок с ключом или сессионная кука.

Все роутеры API зависят от `require_api_key`. Схем аутентификации две, и они
живут параллельно:

* `X-API-Key` — iOS, mac-агент и скиллы, у которых ключ лежит в Keychain;
* сессионная кука — браузер, которому ключ хранить негде (`app/core/session.py`).

Ни одна ручка не теряет старого способа: заголовок проверяется первым, кука —
вторым, а отказ у обеих один и тот же — 401 с одинаковым текстом. Разные
сообщения дали бы неаутентифицированному клиенту способ различать «ключ не тот»
и «кука протухла», не имея ни того, ни другого.

Ожидаемый ключ берётся из `API_KEY`; пустое значение выключает аутентификацию
и достижимо только в разработке — `ENVIRONMENT=prod` с ним не стартует (см.
`app.core.config`). Значение ключа не логируется никогда.

Две детали, которые выглядят косметикой и ею не являются:

* обе стороны сравниваются как байты. `secrets.compare_digest` бросает
  TypeError на не-ASCII `str`, а Starlette декодирует заголовки как latin-1,
  поэтому заголовок с кириллицей раньше заканчивался 500 — по коду ответа
  неаутентифицированный клиент отличал кривой ключ от неверного;
* предупреждение «аутентификация выключена» печатается один раз на старте
  (`warn_if_auth_disabled`), а не на каждый запрос: строку, повторяющуюся на
  каждом запросе, перестают читать через минуту.
"""

import logging
import secrets

from fastapi import Cookie, Header, HTTPException, status

from app.core.config import settings
from app.core.session import SESSION_COOKIE_NAME, session_token_is_valid

logger = logging.getLogger(__name__)

# Один текст отказа на обе схемы: он не должен подсказывать, какая из них
# сработала бы, если бы клиент угадал.
UNAUTHORIZED_DETAIL = "Missing or invalid API key"

_warned_auth_disabled = False


def auth_is_disabled() -> bool:
    """Выключена ли аутентификация целиком (пустой `API_KEY`, только разработка)."""
    return not settings.API_KEY


def warn_if_auth_disabled() -> None:
    """Say once, on startup, that an empty API_KEY leaves the API unauthenticated."""
    global _warned_auth_disabled
    if not auth_is_disabled() or _warned_auth_disabled:
        return
    _warned_auth_disabled = True
    logger.warning("API_KEY is not set; auth is DISABLED (dev mode)")


def api_key_is_valid(candidate: str | None) -> bool:
    """
    Совпадает ли предъявленный ключ с настроенным.

    Отвечает `False` при выключенной аутентификации: «ключа нет» и «любой ключ
    подходит» — разные утверждения, и второе принимает вызывающий, а не эта
    функция.
    """
    if candidate is None or auth_is_disabled():
        return False
    return secrets.compare_digest(
        candidate.encode("utf-8"), settings.API_KEY.encode("utf-8")
    )


def session_cookie_is_valid(token: str | None) -> bool:
    """Жива ли предъявленная сессионная кука по действующему секрету и сроку."""
    if token is None:
        return False
    return session_token_is_valid(
        token,
        secret=settings.session_signing_secret,
        max_age_s=settings.SESSION_MAX_AGE_S,
    )


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> None:
    """Reject the request with 401 unless a valid key header or session cookie is present."""
    if auth_is_disabled():
        return
    if api_key_is_valid(x_api_key) or session_cookie_is_valid(session_cookie):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=UNAUTHORIZED_DETAIL,
    )
