# [review:need-review] PHASE-03/112
# summary: where the CLI keeps a session on disk and the one predicate that decides whether a turn may continue it — session id present, working directory unchanged, system prompt of the same version, file still there — plus the strategy a turn is run under
"""
Сессия CLI и выбор стратегии хода.

**Сессия — оптимизация поверх таблицы, а не память.** Разговор целиком лежит в
`chat_messages`; файл `<CLAUDE_CONFIG_DIR>/projects/<слаг-cwd>/<session_id>.jsonl`
всего лишь позволяет не пересчитывать его на каждом ходу. Поэтому здесь нет ни
одной ветки, которая при отсутствии файла отказывает: любая непройденная
проверка означает «идём реплеем», то есть дороже, но верно.

**Четыре условия, и каждое из них ломается по-своему.** `cli_session_id` пуст —
разговор ещё не начинали через CLI или его начинали через API. `cli_cwd` не
совпал — процесс запустится в другом каталоге, а файл сессии ключуется именно
им, и `--resume` не найдёт ничего. `context_version` разошёлся — системный промпт
переписали, и продолжать под ним сессию, собранную под прежним, значит смешать
две разные модели поведения. Файла нет на диске — том потеряли, каталог чистили
руками, контейнер пересоздали.

**Слаг каталога считается так же, как его считает CLI:** каждый символ вне
`A-Za-z0-9-` заменяется на дефис, поэтому `/data/claude-chat/workspace`
превращается в `-data-claude-chat-workspace`. Совпадение обязательное: путь
вычисляется здесь, а файл кладёт туда чужой процесс.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

# Каталог внутри CLAUDE_CONFIG_DIR, в котором CLI держит сессии, и расширение
# файла одной сессии. Оба — часть чужого формата, поэтому названы, а не вписаны
# в выражение пути.
PROJECTS_DIR_NAME = "projects"
SESSION_FILE_SUFFIX = ".jsonl"

# Что CLI заменяет дефисом в имени каталога сессий. Дефис в исходном пути
# остаётся дефисом, всё прочее — точки, подчёркивания, слеши — становится им.
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9-]")

# Две стратегии хода. Третьей не будет: либо сессия продолжается, либо разговор
# пересобирается из таблицы целиком.
MODE_RESUME = "resume"
MODE_REPLAY = "replay"


@dataclass(frozen=True)
class ResumeHint:
    """
    Что таблица помнит о сессии прошлого хода.

    Именно подсказка, а не состояние: все три поля могут быть пустыми, и
    разговор при этом работает. Отдельно от ORM-модели затем, что `app/llm` не
    должен знать, из какой таблицы это приехало.
    """

    session_id: str | None
    cwd: str | None
    context_version: int


@dataclass(frozen=True)
class TurnStrategy:
    """
    Как запускается один ход: продолжением или заново, и под каким id сессии.

    `session_id` заполнен всегда. На реплее это новый uuid, который уйдёт в
    `--session-id`: id, придуманный до запуска, записывается в таблицу даже
    тогда, когда финальный `result` до нас не доехал.
    """

    mode: str
    session_id: str

    @property
    def resumes(self) -> bool:
        """Продолжает ли этот ход прежнюю сессию."""
        return self.mode == MODE_RESUME


def project_slug(cwd: str) -> str:
    """Имя каталога сессий по рабочему каталогу процесса."""
    return _SLUG_UNSAFE.sub("-", cwd)


def session_file(config_dir: str, cwd: str, session_id: str) -> Path:
    """Путь к файлу одной сессии CLI."""
    return (
        Path(config_dir)
        / PROJECTS_DIR_NAME
        / project_slug(cwd)
        / f"{session_id}{SESSION_FILE_SUFFIX}"
    )


def can_resume(
    *,
    hint: ResumeHint | None,
    cwd: str | None,
    config_dir: str,
    context_version: int,
) -> bool:
    """
    Можно ли продолжить сессию, а не пересобирать разговор.

    `cwd is None` — это API-бэкенд: процесса с рабочим каталогом у него нет,
    сессий тоже, и ответ здесь всегда «нельзя». Не ошибка: у такого разговора
    `cli_session_id` так и остаётся пустым.
    """
    if cwd is None or hint is None or not hint.session_id:
        return False
    if hint.cwd != cwd:
        return False
    if hint.context_version != context_version:
        return False
    return session_file(config_dir, cwd, hint.session_id).is_file()


def choose_strategy(
    *,
    hint: ResumeHint | None,
    cwd: str | None,
    config_dir: str,
    context_version: int,
) -> TurnStrategy:
    """Стратегия одного хода: продолжение прежней сессии либо реплей в новую."""
    # Условие на `hint.session_id` повторяет проверку внутри `can_resume` не
    # ради надёжности, а ради типа: без него id, уходящий в `--resume`, остаётся
    # `str | None`.
    if (
        hint is not None
        and hint.session_id
        and can_resume(
            hint=hint, cwd=cwd, config_dir=config_dir, context_version=context_version
        )
    ):
        return TurnStrategy(mode=MODE_RESUME, session_id=hint.session_id)
    return TurnStrategy(mode=MODE_REPLAY, session_id=str(uuid.uuid4()))
