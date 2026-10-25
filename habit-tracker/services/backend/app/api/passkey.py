# [review:need-review] 205
# summary: /auth/passkey/* and /auth/passkeys — status, register and list/delete for a signed-in client, sign-in open like POST /auth/session and ending in the same habit_session cookie; 503 while passkey is not configured
"""
Ручки passkey (ADR-0022).

Роутер подключается вне периметра `require_api_key`, как и `app/api/auth.py`:
вход по passkey делает клиент, у которого ещё нет ни куки, ни ключа. Ручки,
которые меняют список ключей или показывают его, требуют входа сами — через
`dependencies` на каждой.

Ответы на отказ одинаковы внутри церемонии: 400 на регистрации (клиент уже
вошёл, ему можно сказать, что ключ не принят), 401 на входе. Причина — только
в журнале (`log_rejection`).
"""

import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.config import settings
from app.core.database import get_db
from app.core.session import issue_session_token, set_session_cookie
from app.crud import passkey as passkey_crud
from app.schemas.auth import SessionState
from app.schemas.passkey import (
    PasskeyLoginRequest,
    PasskeyOptions,
    PasskeyRead,
    PasskeyRegistrationRequest,
    PasskeyStatus,
)
from app.services import passkey as passkey_service
from app.services.passkey import (
    CHALLENGE_COOKIE_NAME,
    CHALLENGE_TTL_S,
    Ceremony,
    PasskeyAlreadyRegistered,
    PasskeyRejected,
)

router = APIRouter(prefix="/auth", tags=["auth"])

NOT_CONFIGURED_DETAIL = "Passkey is not configured"
REGISTRATION_FAILED_DETAIL = "Passkey verification failed"
ALREADY_REGISTERED_DETAIL = "This passkey is already registered"
LOGIN_FAILED_DETAIL = "Passkey sign-in failed"
PASSKEY_NOT_FOUND_DETAIL = "Passkey not found"


def _challenge_cookie_path() -> str:
    """Кука вызова нужна только ручкам церемоний — остальным запросам её не носить."""
    return f"{settings.API_V1_PREFIX}/auth/passkey"


def _require_passkey_enabled() -> None:
    """503, пока на сервере не заданы RP ID и origin: без них WebAuthn не работает."""
    if not settings.passkey_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=NOT_CONFIGURED_DETAIL,
        )


SIGNED_IN = [Depends(require_api_key), Depends(_require_passkey_enabled)]
CONFIGURED = [Depends(_require_passkey_enabled)]


def _start(response: Response, ceremony: Ceremony) -> PasskeyOptions:
    """Положить вызов в куку и отдать параметры церемонии."""
    response.set_cookie(
        key=CHALLENGE_COOKIE_NAME,
        value=ceremony.challenge_token,
        max_age=CHALLENGE_TTL_S,
        path=_challenge_cookie_path(),
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="strict",
    )
    return PasskeyOptions(options=ceremony.options)


def _finish(response: Response) -> None:
    """Стереть куку вызова: он одноразовый."""
    response.delete_cookie(
        key=CHALLENGE_COOKIE_NAME,
        path=_challenge_cookie_path(),
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="strict",
    )


@router.get("/passkey/status", response_model=PasskeyStatus)
async def passkey_status() -> PasskeyStatus:
    """Включён ли passkey. Открыта: страница входа решает по ней, показывать ли кнопку."""
    return PasskeyStatus(enabled=settings.passkey_enabled)


@router.post(
    "/passkey/register/options", response_model=PasskeyOptions, dependencies=SIGNED_IN
)
async def registration_options(
    response: Response, db: AsyncSession = Depends(get_db)
) -> PasskeyOptions:
    """Начать регистрацию ключа для уже вошедшего клиента."""
    ceremony = await passkey_service.begin_registration(db, settings, now=time.time())
    return _start(response, ceremony)


@router.post(
    "/passkey/register/verify",
    response_model=PasskeyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=SIGNED_IN,
)
async def register_passkey(
    payload: PasskeyRegistrationRequest,
    response: Response,
    challenge_token: str | None = Cookie(default=None, alias=CHALLENGE_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> PasskeyRead:
    """Проверить ответ аутентификатора и добавить ключ в список."""
    try:
        row = await passkey_service.finish_registration(
            db,
            settings,
            name=payload.name,
            credential=payload.credential,
            challenge_token=challenge_token,
            now=time.time(),
        )
    except PasskeyAlreadyRegistered as error:
        passkey_service.log_rejection("register", error)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ALREADY_REGISTERED_DETAIL
        ) from error
    except PasskeyRejected as error:
        passkey_service.log_rejection("register", error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=REGISTRATION_FAILED_DETAIL
        ) from error
    _finish(response)
    return PasskeyRead.model_validate(row)


@router.get("/passkeys", response_model=list[PasskeyRead], dependencies=SIGNED_IN)
async def list_passkeys(db: AsyncSession = Depends(get_db)) -> list[PasskeyRead]:
    """Ключи в порядке добавления: имя, когда добавлен, когда использован."""
    rows = await passkey_crud.list_credentials(db)
    return [PasskeyRead.model_validate(row) for row in rows]


@router.delete(
    "/passkeys/{passkey_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
    dependencies=SIGNED_IN,
)
async def delete_passkey(
    passkey_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    """Удалить ключ. Войти им после этого нельзя; сессии, уже открытые им, живут свой срок."""
    if not await passkey_crud.delete_credential(db, passkey_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=PASSKEY_NOT_FOUND_DETAIL
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/passkey/login/options", response_model=PasskeyOptions, dependencies=CONFIGURED
)
async def login_options(response: Response) -> PasskeyOptions:
    """Начать вход. Открыта, как `POST /auth/session`."""
    return _start(response, passkey_service.begin_login(settings, now=time.time()))


@router.post(
    "/passkey/login/verify", response_model=SessionState, dependencies=CONFIGURED
)
async def login_with_passkey(
    payload: PasskeyLoginRequest,
    response: Response,
    challenge_token: str | None = Cookie(default=None, alias=CHALLENGE_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> SessionState:
    """
    Проверить ответ на вход и выдать ту же сессионную куку, что и вход по ключу.

    Дальше браузер неотличим от вошедшего по ключу: периметр смотрит на
    `habit_session`, а не на то, чем её получили.
    """
    try:
        await passkey_service.finish_login(
            db,
            settings,
            credential=payload.credential,
            challenge_token=challenge_token,
            now=time.time(),
        )
    except PasskeyRejected as error:
        passkey_service.log_rejection("login", error)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_FAILED_DETAIL
        ) from error
    _finish(response)
    set_session_cookie(
        response,
        issue_session_token(settings.session_signing_secret),
        max_age_s=settings.SESSION_MAX_AGE_S,
        secure=settings.SESSION_COOKIE_SECURE,
    )
    return SessionState(authenticated=True, expires_in_s=settings.SESSION_MAX_AGE_S)
