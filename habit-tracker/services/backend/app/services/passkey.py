# [review:need-review] 205
# summary: the two WebAuthn ceremonies behind passkey sign-in — options with a challenge carried in a signed short-lived token, verification of the browser's answer against RP ID, origins, signature, user verification and the signature counter, and a replay guard that needs no table (the key row is read FOR UPDATE, so a parallel replay waits and is refused)
"""
Вход по passkey: регистрация ключа и вход им (ADR-0022).

Обе церемонии устроены одинаково. Сервер выпускает случайный вызов
(challenge) и отдаёт параметры для `navigator.credentials.create()` или
`.get()`; браузер подписывает вызов ключом аутентификатора; сервер проверяет
ответ. Проверку подписи, `clientDataJSON`, хеша RP ID, флагов присутствия и
верификации и счётчика делает `py_webauthn`; здесь — всё вокруг неё.

**Вызов живёт в подписанном токене, а не в таблице.** Токен кладётся в
короткую `HttpOnly`-куку: соль своя (`CHALLENGE_SALT`), срок —
`CHALLENGE_TTL_S`, назначение (`register` или `login`) записано внутри, так что
вызов регистрации на входе не примешь. Сервер ничего не хранит между двумя
запросами церемонии, как не хранит и сессий (`app/core/session.py`).

**Повтор ответа отбивается без таблицы.** Кука, украденная вместе с ответом,
прошла бы проверку подписи ещё раз за время своей жизни, а счётчик подписей у
синхронизируемых passkey (iCloud Keychain) всегда ноль и повтор не ловит.
Поэтому вход отклоняется, если вызов выпущен не позже последнего использования
этого ключа: после успешного входа `last_used_at` уходит вперёд, и всякий
старый вызов для этого ключа протухает. Цена — два одновременных входа одним
ключом: второй получит отказ и повторит.

**Пользователь один (ADR-0003).** `user.id` у всех ключей один и тот же
(`PASSKEY_USER_ID`), поэтому на входе имя не спрашивается: ключ discoverable
(resident key), и браузер сам предлагает его в окне Face ID.
"""

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    base64url_to_bytes,
    bytes_to_base64url,
    options_to_json_dict,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import Settings
from app.crud import passkey as passkey_crud
from app.models.webauthn_credential import WebAuthnCredential

logger = logging.getLogger(__name__)

# Кука, в которой между двумя запросами церемонии лежит подписанный вызов.
CHALLENGE_COOKIE_NAME = "habit_passkey_challenge"

# Соль подписи вызова. Тот же секрет подписывает сессию, и без своей соли
# токен вызова можно было бы предъявить вместо сессионной куки — или наоборот.
CHALLENGE_SALT = "habit-tracker.passkey-challenge"

# Сколько живёт вызов. Face ID занимает секунды; пять минут — запас на то,
# чтобы человек достал телефон, а не на то, чтобы вызов жил долго.
CHALLENGE_TTL_S = 5 * 60
CEREMONY_TIMEOUT_MS = CHALLENGE_TTL_S * 1000

# Идентификатор и имя пользователя WebAuthn. Пользователь один, поэтому они —
# константы; имя видно в списке паролей на телефоне.
PASSKEY_USER_ID = b"habit-tracker-owner"
PASSKEY_USER_NAME = "habit-tracker"

Purpose = Literal["register", "login"]


class PasskeyRejected(Exception):
    """
    Церемония не прошла.

    Текст — для журнала, клиенту он не уходит: ответ на отказ одинаков, чтобы
    по нему нельзя было отличить «ключ не тот» от «вызов протух».
    """


class PasskeyAlreadyRegistered(PasskeyRejected):
    """Этот ключ уже есть в списке."""


@dataclass(frozen=True)
class Ceremony:
    """Начатая церемония: параметры для браузера и токен вызова для куки."""

    options: dict[str, Any]
    challenge_token: str


@dataclass(frozen=True)
class _Challenge:
    value: bytes
    issued_at: float


def _serializer(secret: str) -> URLSafeSerializer:
    return URLSafeSerializer(secret, salt=CHALLENGE_SALT)


def issue_challenge(
    purpose: Purpose, *, secret: str, issued_at: float | None = None
) -> tuple[bytes, str]:
    """Новый случайный вызов и подписанный токен с ним. `issued_at` — для тестов."""
    challenge = secrets.token_bytes(32)
    token = _serializer(secret).dumps(
        {
            "purpose": purpose,
            "challenge": bytes_to_base64url(challenge),
            "issued_at": time.time() if issued_at is None else issued_at,
        }
    )
    return challenge, token


def _read_challenge(
    token: str | None, purpose: Purpose, *, secret: str, now: float
) -> _Challenge:
    """Достать вызов из токена или отказать: нет, подделан, чужое назначение, протух."""
    if token is None:
        raise PasskeyRejected("no challenge cookie")
    try:
        payload = _serializer(secret).loads(token)
    except BadSignature as error:
        raise PasskeyRejected("challenge token signature mismatch") from error
    if not isinstance(payload, dict) or payload.get("purpose") != purpose:
        raise PasskeyRejected(f"challenge was not issued for {purpose}")
    issued_at, encoded = payload.get("issued_at"), payload.get("challenge")
    if not isinstance(issued_at, (int, float)) or not isinstance(encoded, str):
        raise PasskeyRejected("challenge token is malformed")
    if now - issued_at > CHALLENGE_TTL_S:
        raise PasskeyRejected("challenge expired")
    return _Challenge(value=base64url_to_bytes(encoded), issued_at=float(issued_at))


async def begin_registration(
    db: AsyncSession, config: Settings, *, now: float
) -> Ceremony:
    """Параметры регистрации нового ключа; уже известные ключи браузер не примет."""
    challenge, token = issue_challenge(
        "register", secret=config.session_signing_secret, issued_at=now
    )
    known = [
        PublicKeyCredentialDescriptor(
            id=row.credential_id,
            transports=[AuthenticatorTransport(item) for item in row.transports],
        )
        for row in await passkey_crud.list_credentials(db)
    ]
    options = generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name=config.WEBAUTHN_RP_NAME,
        user_id=PASSKEY_USER_ID,
        user_name=PASSKEY_USER_NAME,
        user_display_name=config.WEBAUTHN_RP_NAME,
        challenge=challenge,
        timeout=CEREMONY_TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=known,
    )
    return Ceremony(options=options_to_json_dict(options), challenge_token=token)


async def finish_registration(
    db: AsyncSession,
    config: Settings,
    *,
    name: str,
    credential: dict[str, Any],
    challenge_token: str | None,
    now: float,
) -> WebAuthnCredential:
    """Проверить ответ аутентификатора и сохранить ключ под именем `name`."""
    challenge = _read_challenge(
        challenge_token, "register", secret=config.session_signing_secret, now=now
    )
    try:
        parsed = parse_registration_credential_json(credential)
        verified = verify_registration_response(
            credential=parsed,
            expected_challenge=challenge.value,
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGINS,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError) as error:
        raise PasskeyRejected(f"registration: {error}") from error
    try:
        return await passkey_crud.add_credential(
            db,
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=[item.value for item in parsed.response.transports or []],
            name=name,
        )
    except IntegrityError as error:
        # The unique index is the one judge of "already registered": a check
        # before the insert would let two parallel requests both pass it.
        raise PasskeyAlreadyRegistered("credential id is already registered") from error


def begin_login(config: Settings, *, now: float) -> Ceremony:
    """Параметры входа без списка ключей: браузер сам предложит свой passkey."""
    challenge, token = issue_challenge(
        "login", secret=config.session_signing_secret, issued_at=now
    )
    options = generate_authentication_options(
        rp_id=config.WEBAUTHN_RP_ID,
        challenge=challenge,
        timeout=CEREMONY_TIMEOUT_MS,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return Ceremony(options=options_to_json_dict(options), challenge_token=token)


async def finish_login(
    db: AsyncSession,
    config: Settings,
    *,
    credential: dict[str, Any],
    challenge_token: str | None,
    now: float,
) -> WebAuthnCredential:
    """
    Проверить ответ на вход; на успехе сдвинуть счётчик и время использования.

    Строка ключа читается под блокировкой: параллельный повтор того же ответа
    ждёт, пока этот вход закоммитит новый `last_used_at`, и после этого
    отклоняется. Коммитит вызывающий — до того, как отдать куку сессии.
    """
    challenge = _read_challenge(
        challenge_token, "login", secret=config.session_signing_secret, now=now
    )
    try:
        parsed = parse_authentication_credential_json(credential)
    except (WebAuthnException, ValueError) as error:
        raise PasskeyRejected(f"login: {error}") from error
    row = await passkey_crud.get_by_credential_id(db, parsed.raw_id, lock=True)
    if row is None:
        raise PasskeyRejected("unknown credential")
    if (
        row.last_used_at is not None
        and challenge.issued_at <= row.last_used_at.timestamp()
    ):
        raise PasskeyRejected("challenge predates the last use of this key (replay)")
    try:
        verified = verify_authentication_response(
            credential=parsed,
            expected_challenge=challenge.value,
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGINS,
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError) as error:
        raise PasskeyRejected(f"login: {error}") from error
    row.sign_count = verified.new_sign_count
    row.last_used_at = datetime.fromtimestamp(now, tz=timezone.utc)
    await db.flush()
    return row


def log_rejection(ceremony: Purpose, error: PasskeyRejected) -> None:
    """
    Записать причину отказа: что именно не сошлось, без ключа и без вызова.

    Через `%r`: в причине бывает origin из `clientDataJSON`, то есть строка
    клиента, и перевод строки в ней не должен рисовать в журнале чужую запись.
    """
    logger.info("passkey %s rejected: %r", ceremony, str(error))
