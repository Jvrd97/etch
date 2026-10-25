# [review:need-review] 205
# summary: `webauthn_credential` — one row per passkey: the authenticator's credential id and public key, its signature counter, transports, a human name and when it was added and last used
"""
Ключи passkey.

Строка — один passkey, которым можно получить сессию браузера (ADR-0022).
Владельца у строки нет: пользователь один (ADR-0003), и passkey — второй
способ войти тем же человеком, а не учётная запись.

`credential_id` и `public_key` приходят от аутентификатора при регистрации и
дальше не меняются. `sign_count` — счётчик подписей: аутентификатор
увеличивает его на каждом входе, и значение меньше сохранённого означает
клон ключа. Синхронизируемые passkey (iCloud Keychain) всегда шлют ноль —
для них проверка счётчика не срабатывает, и это нормально.
`BigInteger`, потому что счётчик беззнаковый 32-битный и в `Integer` Postgres
не помещается.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

# Длина имени ключа («iPhone», «MacBook рабочий»). Имя читает человек в
# списке, а не машина, поэтому сотни символов ему не нужны.
PASSKEY_NAME_MAX = 64


class WebAuthnCredential(Base):
    """Один зарегистрированный passkey."""

    __tablename__ = "webauthn_credential"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credential_id: Mapped[bytes] = mapped_column(
        LargeBinary, unique=True, nullable=False
    )
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Подсказка браузеру, как дотянуться до ключа (`internal`, `hybrid`, ...).
    transports: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    name: Mapped[str] = mapped_column(String(PASSKEY_NAME_MAX), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
