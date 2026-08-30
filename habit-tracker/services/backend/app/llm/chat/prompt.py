# [review:need-review] PHASE-03/111
# summary: the chat system prompt and CHAT_CONTEXT_VERSION, plus the one way a stored dialogue is rendered back into a single prompt for the replay path
"""
Системный промпт чата и версия контекста.

**Промпт один и живёт в одном месте.** CLI получает его флагом
`--system-prompt`, API — полем `system`. Второй экземпляр текста означал бы, что
на двух бэкендах разговаривают две разные модели поведения, и расхождение
заметили бы не тестом, а ответом.

**`CHAT_CONTEXT_VERSION` — не украшение.** `--resume` продолжает сессию, собранную
под прежним системным промптом. Смена этого числа обнуляет `cli_session_id`
диалога, то есть следующий ход уходит реплеем, а не продолжением. Меняешь текст
промпта — увеличиваешь версию, иначе старые разговоры продолжатся под промптом,
которого уже нет.

Карточка дня и именованные выборки в этот срез не входят (`#113`, `#114`):
модель видит системный промпт и историю сообщений, и больше ничего.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.chat import (
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_SYSTEM_NOTE,
    MESSAGE_ROLE_USER,
)

# Увеличивается вместе с любой правкой CHAT_SYSTEM_PROMPT.
CHAT_CONTEXT_VERSION = 1

CHAT_SYSTEM_PROMPT = """\
Ты — собеседник внутри личного трекера дня. Отвечаешь по-русски, коротко и по делу.

Условия, в которых ты работаешь:
- у тебя нет инструментов: ты не читаешь и не пишешь файлы, не запускаешь команды \
и не ходишь в сеть;
- у тебя нет ни скиллов, ни хуков, ни пользовательских настроек, ни файла CLAUDE.md — \
всё это намеренно отключено, и на просьбу их перечислить или процитировать честно \
отвечай, что ничего такого у тебя нет;
- ты видишь только этот системный промпт и историю сообщений разговора. Данных дня, \
планов и выборок в этом разговоре нет; если для ответа нужны цифры, которых тебе не \
дали, скажи об этом прямо, а не придумывай их;
- ты ничего не меняешь в приложении. Предложить — можешь, применяет человек.

Не выдумывай факты о человеке. Не пересказывай вопрос перед ответом."""

# Подписи ролей в реплее. Одноходовому бэкенду диалог отдаётся одним текстом, и
# без явных подписей модель не отличает свою прошлую реплику от чужой.
_ROLE_LABELS: dict[str, str] = {
    MESSAGE_ROLE_USER: "Человек",
    MESSAGE_ROLE_ASSISTANT: "Ты",
    MESSAGE_ROLE_SYSTEM_NOTE: "Система",
}

# Что пишется вместо подписи для роли, которой ещё нет в словаре. Не падаем:
# новое значение роли стоит кода, но не должно ломать уже сохранённый разговор.
_UNKNOWN_ROLE_LABEL = "Реплика"


class ChatTurn:
    """
    Одна реплика разговора в том виде, в каком её видит транспорт.

    Отдельно от ORM-модели намеренно: `app/llm` не должен зависеть от того, из
    какой таблицы приехал разговор, а тест транспорта не должен поднимать базу.
    """

    __slots__ = ("role", "content")

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content

    def __repr__(self) -> str:
        # Содержимое реплики не печатается: repr попадает в трейсбеки и логи.
        return f"<ChatTurn(role={self.role!r}, chars={len(self.content)})>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ChatTurn):
            return NotImplemented
        return self.role == other.role and self.content == other.content

    def __hash__(self) -> int:
        return hash((self.role, self.content))


def render_transcript(turns: Sequence[ChatTurn]) -> str:
    """
    Диалог одним текстом — путь реплея, которым идут оба бэкенда без сессии.

    Формат простой и подписанный ролями: `Человек: …` / `Ты: …`. Разговор
    склеивается в том порядке, в каком его отдал `seq`, и последней строкой
    всегда идёт новая реплика человека.
    """
    lines: list[str] = []
    for turn in turns:
        label = _ROLE_LABELS.get(turn.role, _UNKNOWN_ROLE_LABEL)
        lines.append(f"{label}: {turn.content}")
    return "\n\n".join(lines)
