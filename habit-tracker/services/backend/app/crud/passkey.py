# [review:need-review] 205
# summary: the four reads and writes of the passkey table — list in the order added, find by credential id, add, delete
"""
Доступ к таблице passkey.

Только запросы: проверка подписей, вызовы и куки живут в
`app/services/passkey.py`. Каждая функция — один запрос; список ключей у
одного пользователя короткий, постраничного чтения нет.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webauthn_credential import WebAuthnCredential


async def list_credentials(db: AsyncSession) -> list[WebAuthnCredential]:
    """Все ключи в порядке добавления."""
    rows = await db.scalars(
        select(WebAuthnCredential).order_by(
            WebAuthnCredential.created_at, WebAuthnCredential.id
        )
    )
    return list(rows)


async def get_by_credential_id(
    db: AsyncSession, credential_id: bytes
) -> WebAuthnCredential | None:
    """Ключ по идентификатору, который прислал аутентификатор."""
    row: WebAuthnCredential | None = await db.scalar(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == credential_id
        )
    )
    return row


async def add_credential(
    db: AsyncSession,
    *,
    credential_id: bytes,
    public_key: bytes,
    sign_count: int,
    transports: list[str],
    name: str,
) -> WebAuthnCredential:
    """Записать новый ключ и вернуть строку с выданными базой `id` и `created_at`."""
    row = WebAuthnCredential(
        credential_id=credential_id,
        public_key=public_key,
        sign_count=sign_count,
        transports=transports,
        name=name,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def delete_credential(db: AsyncSession, passkey_id: int) -> bool:
    """Удалить ключ; `False`, если такого нет."""
    deleted = await db.scalar(
        delete(WebAuthnCredential)
        .where(WebAuthnCredential.id == passkey_id)
        .returning(WebAuthnCredential.id)
    )
    return deleted is not None
