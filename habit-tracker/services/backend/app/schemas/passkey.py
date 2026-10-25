# [review:need-review] 205
# summary: DTOs of passkey sign-in — whether it is on, the WebAuthn options handed to the browser, the browser's answer, and a key as the settings list shows it (no key material)
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.webauthn_credential import PASSKEY_NAME_MAX

PasskeyName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=PASSKEY_NAME_MAX),
]


class PasskeyStatus(BaseModel):
    """Включён ли passkey на сервере. Интерфейс по этому флагу показывает кнопки."""

    enabled: bool


class PasskeyOptions(BaseModel):
    """
    Параметры церемонии для `navigator.credentials.create()` / `.get()`.

    JSON-форма WebAuthn как есть: двоичные поля в base64url, их декодирует
    `frontend/lib/passkey.ts`. Вызов (challenge) здесь виден, но проверяется по
    подписанной куке, а не по тому, что вернёт клиент.
    """

    options: dict[str, Any]


class PasskeyRegistrationRequest(BaseModel):
    """Ответ аутентификатора на регистрацию и имя, под которым ключ виден в списке."""

    model_config = ConfigDict(extra="forbid")

    name: PasskeyName
    credential: dict[str, Any]


class PasskeyLoginRequest(BaseModel):
    """Ответ аутентификатора на вход. Имени пользователя нет: ключ сам его несёт."""

    model_config = ConfigDict(extra="forbid")

    credential: dict[str, Any]


class PasskeyRead(BaseModel):
    """Ключ в списке настроек. Ни `credential_id`, ни открытый ключ наружу не уходят."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    last_used_at: datetime | None
