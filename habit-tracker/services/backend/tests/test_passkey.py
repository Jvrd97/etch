"""
Вход по passkey: регистрация и вход на настоящих данных WebAuthn.

Данные строит программный аутентификатор `SoftAuthenticator` — ключ P-256,
`authenticatorData`, `clientDataJSON`, CBOR-объект аттестации `none` и подпись
ECDSA собираются тут по спецификации, без подмены библиотеки проверки. Поэтому
«чужой origin» и «откат счётчика» здесь — те же байты, которые прислал бы
браузер, а не флажок в заглушке.
"""

# [review:need-review] 205
# summary: passkey ceremonies end to end — register under a session, list, delete, log back in by passkey; rejected on foreign origin / RP ID, replay, expired challenge, sign_count rollback, unknown or deleted key, no session on the registration endpoints, passkey switched off
import base64
import hashlib
import json
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.session import SESSION_COOKIE_NAME
from app.main import app
from app.models.webauthn_credential import WebAuthnCredential
from app.services.passkey import CHALLENGE_COOKIE_NAME, issue_challenge

RP_ID = "localhost"
ORIGIN = "http://localhost:3805"
# Cookies carry `Secure`; over http httpx would never send them back.
BASE_URL = "https://test"
PROTECTED_URL = "/api/v1/categories"
STATUS_URL = "/api/v1/auth/passkey/status"
REGISTER_OPTIONS_URL = "/api/v1/auth/passkey/register/options"
REGISTER_VERIFY_URL = "/api/v1/auth/passkey/register/verify"
LOGIN_OPTIONS_URL = "/api/v1/auth/passkey/login/options"
LOGIN_VERIFY_URL = "/api/v1/auth/passkey/login/verify"
LIST_URL = "/api/v1/auth/passkeys"

# authenticatorData flag bits (WebAuthn §6.1).
FLAG_USER_PRESENT = 0x01
FLAG_USER_VERIFIED = 0x04
FLAG_ATTESTED_DATA = 0x40
# COSE key labels for an EC2 P-256 key with ES256 (RFC 9053).
COSE_KTY, COSE_ALG, COSE_CRV, COSE_X, COSE_Y = 1, 3, -1, -2, -3
COSE_KTY_EC2, COSE_ALG_ES256, COSE_CRV_P256 = 2, -7, 1
P256_COORD_BYTES = 32


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SoftAuthenticator:
    """
    Платформенный аутентификатор в памяти: то, что делает Face ID, без Face ID.

    Один ключ — один passkey. `rp_id`/`origin` по умолчанию совпадают с
    настроенными; негативные тесты подменяют их на вызове.
    """

    def __init__(self, *, sign_count: int = 0) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.sign_count = sign_count
        self.user_handle = b""

    def _cose_public_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                COSE_KTY: COSE_KTY_EC2,
                COSE_ALG: COSE_ALG_ES256,
                COSE_CRV: COSE_CRV_P256,
                COSE_X: numbers.x.to_bytes(P256_COORD_BYTES, "big"),
                COSE_Y: numbers.y.to_bytes(P256_COORD_BYTES, "big"),
            }
        )

    def create(
        self, options: dict[str, Any], *, origin: str = ORIGIN, rp_id: str = RP_ID
    ) -> dict[str, Any]:
        """Ответ `navigator.credentials.create()` в JSON-форме браузера."""
        self.user_handle = b64url_decode(options["user"]["id"])
        client_data = json.dumps(
            {
                "type": "webauthn.create",
                "challenge": options["challenge"],
                "origin": origin,
                "crossOrigin": False,
            }
        ).encode()
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([FLAG_USER_PRESENT | FLAG_USER_VERIFIED | FLAG_ATTESTED_DATA])
            + self.sign_count.to_bytes(4, "big")
            + bytes(16)  # AAGUID: zeros, as for attestation "none"
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + self._cose_public_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": b64url(client_data),
                "attestationObject": b64url(attestation),
                "transports": ["internal", "hybrid"],
            },
        }

    def get(
        self,
        options: dict[str, Any],
        *,
        origin: str = ORIGIN,
        rp_id: str = RP_ID,
        sign_count: int | None = None,
    ) -> dict[str, Any]:
        """Ответ `navigator.credentials.get()`; счётчик растёт, если не задан явно."""
        if sign_count is None:
            self.sign_count += 1 if self.sign_count else 0
            sign_count = self.sign_count
        client_data = json.dumps(
            {
                "type": "webauthn.get",
                "challenge": options["challenge"],
                "origin": origin,
                "crossOrigin": False,
            }
        ).encode()
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([FLAG_USER_PRESENT | FLAG_USER_VERIFIED])
            + sign_count.to_bytes(4, "big")
        )
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": b64url(self.user_handle),
            },
        }


@pytest.fixture
def passkey_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Passkey включён на `localhost`, как на живой проверке."""
    monkeypatch.setattr(settings, "WEBAUTHN_RP_ID", RP_ID)
    monkeypatch.setattr(settings, "WEBAUTHN_ORIGINS", [ORIGIN])


async def _client(db_session: AsyncSession) -> AsyncClient:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return AsyncClient(app=app, base_url=BASE_URL, follow_redirects=True)


@pytest.fixture
async def signed_in(
    db_session: AsyncSession, api_key: str
) -> AsyncGenerator[AsyncClient, None]:
    """Вошедший браузер: ключ один раз обменян на куку, заголовка нет."""
    async with await _client(db_session) as ac:
        opened = await ac.post("/api/v1/auth/session", json={"api_key": api_key})
        assert opened.status_code == 200
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def anonymous(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Браузер без сессии и без ключа — тот, кто стоит на `/login`."""
    async with await _client(db_session) as ac:
        yield ac
    app.dependency_overrides.clear()


async def register(
    client: AsyncClient, authenticator: SoftAuthenticator, name: str = "iPhone"
) -> dict[str, Any]:
    options = await client.post(REGISTER_OPTIONS_URL)
    assert options.status_code == 200, options.text
    credential = authenticator.create(options.json()["options"])
    verified = await client.post(
        REGISTER_VERIFY_URL, json={"name": name, "credential": credential}
    )
    assert verified.status_code == 201, verified.text
    body: dict[str, Any] = verified.json()
    return body


async def login_options(client: AsyncClient) -> dict[str, Any]:
    options = await client.post(LOGIN_OPTIONS_URL)
    assert options.status_code == 200, options.text
    body: dict[str, Any] = options.json()["options"]
    return body


def session_cookie_set(response: Any) -> bool:
    return any(
        header.startswith(f"{SESSION_COOKIE_NAME}=")
        for header in response.headers.get_list("set-cookie")
    )


# --- выключенный passkey -----------------------------------------------------


async def test_passkey_is_off_without_rp_id(
    signed_in: AsyncClient, anonymous: AsyncClient
) -> None:
    """Пустой `WEBAUTHN_RP_ID`: статус «выключен», ручки — 503, вход по ключу жив."""
    assert (await anonymous.get(STATUS_URL)).json() == {"enabled": False}
    assert (await signed_in.post(REGISTER_OPTIONS_URL)).status_code == 503
    assert (await signed_in.get(LIST_URL)).status_code == 503
    off = await anonymous.post(LOGIN_OPTIONS_URL)
    assert off.status_code == 503
    assert off.json()["detail"] == "Passkey is not configured"
    assert (await signed_in.get(PROTECTED_URL)).status_code == 200


async def test_status_reports_enabled(anonymous: AsyncClient, passkey_on: None) -> None:
    assert (await anonymous.get(STATUS_URL)).json() == {"enabled": True}


# --- регистрация, список, удаление ---------------------------------------------


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", REGISTER_OPTIONS_URL),
        ("POST", REGISTER_VERIFY_URL),
        ("GET", LIST_URL),
        ("DELETE", f"{LIST_URL}/1"),
    ],
)
async def test_registration_endpoints_require_a_session(
    anonymous: AsyncClient, passkey_on: None, method: str, url: str
) -> None:
    response = await anonymous.request(method, url, json={})
    assert response.status_code == 401


async def test_registered_passkey_is_listed(
    signed_in: AsyncClient, passkey_on: None
) -> None:
    created = await register(signed_in, SoftAuthenticator(), name="  iPhone  ")
    assert created["name"] == "iPhone"
    assert created["last_used_at"] is None

    listed = (await signed_in.get(LIST_URL)).json()
    assert [(item["id"], item["name"]) for item in listed] == [
        (created["id"], "iPhone")
    ]
    assert set(listed[0]) == {"id", "name", "created_at", "last_used_at"}


async def test_registration_options_exclude_known_keys(
    signed_in: AsyncClient, passkey_on: None
) -> None:
    """Повторно тот же аутентификатор не регистрируется: его id в `excludeCredentials`."""
    authenticator = SoftAuthenticator()
    await register(signed_in, authenticator)
    options = (await signed_in.post(REGISTER_OPTIONS_URL)).json()["options"]
    assert [item["id"] for item in options["excludeCredentials"]] == [
        b64url(authenticator.credential_id)
    ]
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["rp"]["id"] == RP_ID


async def test_registration_rejects_foreign_origin(
    signed_in: AsyncClient, passkey_on: None
) -> None:
    options = (await signed_in.post(REGISTER_OPTIONS_URL)).json()["options"]
    credential = SoftAuthenticator().create(options, origin="https://evil.example")
    response = await signed_in.post(
        REGISTER_VERIFY_URL, json={"name": "iPhone", "credential": credential}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Passkey verification failed"
    assert (await signed_in.get(LIST_URL)).json() == []


async def test_registration_rejects_replay_of_the_same_answer(
    signed_in: AsyncClient, passkey_on: None
) -> None:
    options = (await signed_in.post(REGISTER_OPTIONS_URL)).json()["options"]
    challenge_cookie = signed_in.cookies.get(CHALLENGE_COOKIE_NAME)
    body = {"name": "iPhone", "credential": SoftAuthenticator().create(options)}
    assert (await signed_in.post(REGISTER_VERIFY_URL, json=body)).status_code == 201

    assert challenge_cookie is not None
    signed_in.cookies.set(CHALLENGE_COOKIE_NAME, challenge_cookie)
    replay = await signed_in.post(REGISTER_VERIFY_URL, json=body)
    assert replay.status_code in (400, 409)
    assert len((await signed_in.get(LIST_URL)).json()) == 1


async def test_deleted_passkey_no_longer_logs_in(
    signed_in: AsyncClient, anonymous: AsyncClient, passkey_on: None
) -> None:
    authenticator = SoftAuthenticator()
    created = await register(signed_in, authenticator)

    deleted = await signed_in.delete(f"{LIST_URL}/{created['id']}")
    assert deleted.status_code == 204
    assert (await signed_in.get(LIST_URL)).json() == []
    assert (await signed_in.delete(f"{LIST_URL}/{created['id']}")).status_code == 404

    options = await login_options(anonymous)
    refused = await anonymous.post(
        LOGIN_VERIFY_URL, json={"credential": authenticator.get(options)}
    )
    assert refused.status_code == 401
    assert not session_cookie_set(refused)


# --- вход ---------------------------------------------------------------------


async def test_passkey_login_opens_the_same_session(
    signed_in: AsyncClient,
    anonymous: AsyncClient,
    passkey_on: None,
    db_session: AsyncSession,
) -> None:
    """Добавил в настройках, вышел, вошёл по passkey без ключа — и API пускает по куке."""
    authenticator = SoftAuthenticator(sign_count=1)
    created = await register(signed_in, authenticator)
    assert (await anonymous.get(PROTECTED_URL)).status_code == 401

    options = await login_options(anonymous)
    assert options["rpId"] == RP_ID
    assert options["allowCredentials"] == []
    assert options["userVerification"] == "required"
    response = await anonymous.post(
        LOGIN_VERIFY_URL, json={"credential": authenticator.get(options)}
    )

    assert response.status_code == 200, response.text
    assert response.json()["authenticated"] is True
    assert session_cookie_set(response)
    assert anonymous.cookies.get(CHALLENGE_COOKIE_NAME) is None
    assert (await anonymous.get(PROTECTED_URL)).status_code == 200

    row = await db_session.scalar(
        select(WebAuthnCredential).where(WebAuthnCredential.id == created["id"])
    )
    assert row is not None
    assert row.sign_count == authenticator.sign_count == 2
    assert row.last_used_at is not None
    listed = (await signed_in.get(LIST_URL)).json()
    assert listed[0]["last_used_at"] is not None


async def test_apple_style_zero_counter_logs_in_repeatedly(
    signed_in: AsyncClient, anonymous: AsyncClient, passkey_on: None
) -> None:
    """Синхронизируемые passkey (iCloud) всегда шлют `sign_count = 0` — это не откат."""
    authenticator = SoftAuthenticator(sign_count=0)
    await register(signed_in, authenticator)
    for _ in range(2):
        options = await login_options(anonymous)
        response = await anonymous.post(
            LOGIN_VERIFY_URL, json={"credential": authenticator.get(options)}
        )
        assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "tamper",
    [
        {"origin": "https://evil.example"},
        {"origin": "http://localhost:3000"},
        {"rp_id": "evil.example"},
    ],
    ids=["foreign-origin", "other-port", "foreign-rp-id"],
)
async def test_login_rejects_foreign_origin_and_rp_id(
    signed_in: AsyncClient,
    anonymous: AsyncClient,
    passkey_on: None,
    tamper: dict[str, str],
) -> None:
    authenticator = SoftAuthenticator()
    await register(signed_in, authenticator)
    options = await login_options(anonymous)
    response = await anonymous.post(
        LOGIN_VERIFY_URL, json={"credential": authenticator.get(options, **tamper)}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Passkey sign-in failed"
    assert not session_cookie_set(response)


async def test_login_rejects_replayed_answer(
    signed_in: AsyncClient, anonymous: AsyncClient, passkey_on: None
) -> None:
    """
    Тот же ответ с той же кукой вызова второй раз не пускает.

    Счётчик тут не помогает: у синхронизируемых passkey он всегда ноль. Отказ
    держится на том, что вызов выпущен раньше последнего использования ключа.
    """
    authenticator = SoftAuthenticator(sign_count=0)
    await register(signed_in, authenticator)
    options = await login_options(anonymous)
    challenge_cookie = anonymous.cookies.get(CHALLENGE_COOKIE_NAME)
    body = {"credential": authenticator.get(options)}
    assert (await anonymous.post(LOGIN_VERIFY_URL, json=body)).status_code == 200

    anonymous.cookies.clear()
    assert challenge_cookie is not None
    anonymous.cookies.set(CHALLENGE_COOKIE_NAME, challenge_cookie)
    replay = await anonymous.post(LOGIN_VERIFY_URL, json=body)
    assert replay.status_code == 401
    assert not session_cookie_set(replay)


async def test_login_rejects_expired_challenge(
    signed_in: AsyncClient, anonymous: AsyncClient, passkey_on: None
) -> None:
    authenticator = SoftAuthenticator()
    await register(signed_in, authenticator)
    challenge, token = issue_challenge(
        "login",
        secret=settings.session_signing_secret,
        issued_at=time.time() - 10 * 60,
    )
    anonymous.cookies.set(CHALLENGE_COOKIE_NAME, token)
    credential = authenticator.get({"challenge": b64url(challenge)})
    response = await anonymous.post(LOGIN_VERIFY_URL, json={"credential": credential})
    assert response.status_code == 401


async def test_login_rejects_a_registration_challenge(
    signed_in: AsyncClient, anonymous: AsyncClient, passkey_on: None
) -> None:
    """Вызов, выпущенный под регистрацию, на входе не принимается."""
    authenticator = SoftAuthenticator()
    await register(signed_in, authenticator)
    challenge, token = issue_challenge(
        "register", secret=settings.session_signing_secret
    )
    anonymous.cookies.set(CHALLENGE_COOKIE_NAME, token)
    credential = authenticator.get({"challenge": b64url(challenge)})
    response = await anonymous.post(LOGIN_VERIFY_URL, json={"credential": credential})
    assert response.status_code == 401


async def test_login_without_challenge_cookie_is_refused(
    signed_in: AsyncClient, anonymous: AsyncClient, passkey_on: None
) -> None:
    authenticator = SoftAuthenticator()
    await register(signed_in, authenticator)
    options = await login_options(anonymous)
    anonymous.cookies.clear()
    response = await anonymous.post(
        LOGIN_VERIFY_URL, json={"credential": authenticator.get(options)}
    )
    assert response.status_code == 401


async def test_login_rejects_sign_count_rollback(
    signed_in: AsyncClient, anonymous: AsyncClient, passkey_on: None
) -> None:
    """Счётчик меньше сохранённого — признак клона ключа: вход отклоняется."""
    authenticator = SoftAuthenticator(sign_count=5)
    await register(signed_in, authenticator)
    options = await login_options(anonymous)
    ok = await anonymous.post(
        LOGIN_VERIFY_URL, json={"credential": authenticator.get(options, sign_count=7)}
    )
    assert ok.status_code == 200

    anonymous.cookies.clear()
    options = await login_options(anonymous)
    rolled_back = await anonymous.post(
        LOGIN_VERIFY_URL, json={"credential": authenticator.get(options, sign_count=6)}
    )
    assert rolled_back.status_code == 401
    assert not session_cookie_set(rolled_back)


async def test_login_rejects_unknown_key(
    anonymous: AsyncClient, passkey_on: None
) -> None:
    stranger = SoftAuthenticator()
    stranger.user_handle = b"someone"
    options = await login_options(anonymous)
    response = await anonymous.post(
        LOGIN_VERIFY_URL, json={"credential": stranger.get(options)}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "credential",
    [{}, {"id": "x", "rawId": "!!", "type": "public-key", "response": {}}, "garbage"],
    ids=["empty", "broken", "not-an-object"],
)
async def test_login_rejects_malformed_credential(
    anonymous: AsyncClient, passkey_on: None, credential: Any
) -> None:
    """Мусор от клиента — 401 или 422, но не 500."""
    await login_options(anonymous)
    response = await anonymous.post(LOGIN_VERIFY_URL, json={"credential": credential})
    assert response.status_code in (401, 422)
