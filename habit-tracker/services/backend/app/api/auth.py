# [review:need-review] PHASE-03/109
# summary: POST/GET/DELETE /auth/session — the browser trades the key for an HttpOnly cookie, asks whether the session is alive, and logs out
"""
Ручки сессии веб-клиента.

Роутер сознательно подключается вне периметра `require_api_key`: войти обязан
клиент, у которого ещё нет ни куки, ни права слать ключ заголовком, а спросить
«жива ли сессия» нужно ровно затем, чтобы решить, показывать страницу входа или
нет. Ничего, кроме факта аутентификации, эти три ручки не отдают.
"""

from fastapi import APIRouter, Cookie, HTTPException, Response, status

from app.core.auth import UNAUTHORIZED_DETAIL, api_key_is_valid, auth_is_disabled
from app.core.config import settings
from app.core.session import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    issue_session_token,
    session_token_is_valid,
    set_session_cookie,
)
from app.schemas.auth import SessionOpenRequest, SessionState

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_is_alive(token: str | None) -> bool:
    """Жива ли кука. При выключенной аутентификации открыто и так — отвечаем «да»."""
    if auth_is_disabled():
        return True
    if token is None:
        return False
    return session_token_is_valid(
        token,
        secret=settings.session_signing_secret,
        max_age_s=settings.SESSION_MAX_AGE_S,
    )


@router.post("/session", response_model=SessionState)
async def open_session(payload: SessionOpenRequest, response: Response) -> SessionState:
    """
    Обменять ключ на сессионную куку.

    Ключ приходит телом, а не заголовком и не строкой запроса: строка запроса
    попадает в логи прокси и в историю браузера. Обратно уходит только флаг и
    срок — ни ключа, ни токена в теле нет, токен живёт в `Set-Cookie` и оттуда
    JavaScript его не достанет.

    При выключенной аутентификации (пустой `API_KEY`, только разработка)
    проверять нечего: API открыт целиком, и отказать здесь значило бы сделать
    страницу входа неработающей ровно там, где она никому не мешает.
    """
    if not auth_is_disabled() and not api_key_is_valid(payload.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=UNAUTHORIZED_DETAIL
        )
    token = issue_session_token(settings.session_signing_secret)
    set_session_cookie(
        response,
        token,
        max_age_s=settings.SESSION_MAX_AGE_S,
        secure=settings.SESSION_COOKIE_SECURE,
    )
    return SessionState(authenticated=True, expires_in_s=settings.SESSION_MAX_AGE_S)


@router.get("/session", response_model=SessionState)
async def read_session(
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> SessionState:
    """Ответить, жива ли сессия, и ничего больше. Ответ всегда 200 — это не ручка отказа."""
    return SessionState(authenticated=_session_is_alive(session_cookie))


@router.delete("/session", response_model=SessionState)
async def close_session(response: Response) -> SessionState:
    """
    Выйти: стереть куку.

    Сервер списка сессий не ведёт, поэтому выход выражается стиранием и ничем
    больше. Ручка идемпотентна — выйти дважды не ошибка.
    """
    clear_session_cookie(response, secure=settings.SESSION_COOKIE_SECURE)
    return SessionState(authenticated=False)
