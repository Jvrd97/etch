# [review:need-review] PHASE-03/109
# summary: DTOs of the browser session — the key goes in, only a boolean and a lifetime come back
from pydantic import BaseModel, Field


class SessionOpenRequest(BaseModel):
    """Единственное место, где ключ вообще появляется в браузере — и то на один запрос."""

    api_key: str = Field(min_length=1)


class SessionState(BaseModel):
    """
    Состояние сессии. Ключа здесь нет и быть не может.

    `expires_in_s` — то же значение, что в `Max-Age` куки; оно нужно интерфейсу,
    чтобы сказать «вход на 30 дней», и не раскрывает ничего, чего не видно в
    заголовке `Set-Cookie`.
    """

    authenticated: bool
    expires_in_s: int | None = None
