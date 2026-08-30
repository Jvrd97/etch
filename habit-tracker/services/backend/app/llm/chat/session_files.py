# [review:need-review] PHASE-03/117
# summary: where the CLI keeps the .jsonl of one chat session and how it is removed — the path is derived from the working directory the way the CLI derives it, and a file that would land outside CHAT_CLAUDE_CONFIG_DIR is never touched, only reported by machine code
"""
Файл сессии CLI: где он лежит и как его снести.

**Путь считается так же, как его считает сам CLI.** Файл разговора живёт в
`<CHAT_CLAUDE_CONFIG_DIR>/projects/<каталог по cwd>/<session_id>.jsonl`, а имя
каталога — рабочий каталог процесса, в котором каждый символ, не являющийся
буквой или цифрой, заменён дефисом (`/data/claude-chat/workspace` →
`-data-claude-chat-workspace`). Отсюда и требование `#111` держать cwd
настройкой, а не временным каталогом на вызов.

**Удаление никогда не бросает.** У файла три законных причины отсутствовать:
разговор шёл по API-бэкенду, разговор реплеился без сессии, том с сессиями
пересоздан. Ни одна из них не должна мешать снести строки разговора, поэтому
наружу уходит код исхода, а не исключение.

**За пределы каталога конфигурации не ходим вообще.** `cli_session_id` —
строка из базы; подделанная, она обязана не удалить ничего. Проверяется не
подстрокой, а собранным путём: файл обязан лежать ровно в каталоге проекта и
внутри каталога конфигурации, иначе исход — `outside_config_dir`, и ни одного
обращения к диску не происходит.
"""

from __future__ import annotations

import re
from pathlib import Path

# Подкаталог, в котором CLI держит разговоры, и расширение одного файла сессии.
PROJECTS_DIR_NAME = "projects"
SESSION_FILE_SUFFIX = ".jsonl"

# Имя каталога проекта: всё, что не буква и не цифра, становится дефисом.
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")

# Исходы удаления. Строки машинные: они уходят в лог и в тест, но не человеку.
OUTCOME_REMOVED = "removed"
OUTCOME_ABSENT = "absent"
OUTCOME_NO_SESSION = "no_session"
OUTCOME_OUTSIDE_CONFIG_DIR = "outside_config_dir"
OUTCOME_REMOVE_FAILED = "remove_failed"


def project_dir_name(cwd: str) -> str:
    """Имя каталога проекта по рабочему каталогу процесса."""
    return _NON_ALNUM.sub("-", cwd)


def session_file_path(*, config_dir: str, cwd: str, session_id: str) -> Path:
    """
    Путь файла сессии — как его собрал бы CLI, без проверок и без диска.

    Отдельная функция, потому что её ответ нужен тесту и `#112`: возобновление
    сессии обязано смотреть на тот же файл, который удаление сносит.
    """
    return (
        Path(config_dir)
        / PROJECTS_DIR_NAME
        / project_dir_name(cwd)
        / f"{session_id}{SESSION_FILE_SUFFIX}"
    )


def remove_session_file(
    *, config_dir: str, cwd: str | None, session_id: str | None
) -> str:
    """
    Снести файл сессии и вернуть машинный код исхода.

    Возвращается один из `OUTCOME_*`. Исключений нет ни одного: вызывающий код
    удаляет строки разговора, и состояние диска не имеет права этому помешать.
    """
    if not session_id or not cwd:
        return OUTCOME_NO_SESSION

    try:
        root = Path(config_dir).resolve()
        expected_dir = (
            Path(config_dir) / PROJECTS_DIR_NAME / project_dir_name(cwd)
        ).resolve()
        candidate = session_file_path(
            config_dir=config_dir, cwd=cwd, session_id=session_id
        ).resolve()
    except (OSError, ValueError):
        # Строка из базы, которую операционная система вообще не считает путём
        # (нулевой байт, слишком длинное имя). Это тот же случай «за пределами
        # каталога»: трогать нечего, отвечать 500 не за что.
        return OUTCOME_OUTSIDE_CONFIG_DIR

    # Два условия, а не одно: первое держит файл в каталоге конфигурации,
    # второе — в каталоге именно этого разговора. Без второго подделанный
    # `../<чужой проект>/<id>` остался бы внутри каталога конфигурации и снёс
    # бы сессию соседнего разговора.
    if candidate.parent != expected_dir or not candidate.is_relative_to(root):
        return OUTCOME_OUTSIDE_CONFIG_DIR

    try:
        candidate.unlink()
    except FileNotFoundError:
        return OUTCOME_ABSENT
    except OSError:
        # Класс ошибки не пересылается и не поднимается: строки разговора уже
        # удалены, а осиротевший файл — мусор, на который никто не сошлётся.
        return OUTCOME_REMOVE_FAILED
    return OUTCOME_REMOVED
