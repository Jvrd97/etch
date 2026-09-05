# [review:need-review] 2026-07-14-night-triage#session-4
# summary: PreToolUse guard — blocks ClickUp create/update task MCP calls missing mandatory fields (name formula, description template sections)
import json
import re
import sys

RULES_DOC = "docs/GENERAL/how-to/task-template.md"

REQUIRED_SECTIONS = ["## Goal", "## Шаги", "## Acceptance"]
MIN_DESCRIPTION_LEN = 150
MIN_NAME_WORDS = 3

CREATE_TOOLS = re.compile(r"create_(task|bulk_tasks)$|clickup_create_task$")
UPDATE_TOOLS = re.compile(r"update_(task|bulk_tasks)$|clickup_update_task$")


def get_description(task: dict) -> str | None:
    for key in ("markdown_description", "description", "markdown_content"):
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def check_name(name: str, errors: list[str]) -> None:
    stripped = name.strip()
    if len(stripped.split()) < MIN_NAME_WORDS:
        errors.append(
            f"название «{stripped}» не по формуле «глагол + что сделать + результат» "
            f"(минимум {MIN_NAME_WORDS} слова)"
        )
    if stripped.startswith("["):
        errors.append(
            f"название «{stripped}» начинается с «[…]» — имя исполнителя не место в названии"
        )


def check_description(desc: str, errors: list[str]) -> None:
    missing = [s for s in REQUIRED_SECTIONS if s not in desc]
    if missing:
        errors.append(f"в описании нет обязательных секций: {', '.join(missing)}")
    if not re.search(r"^Type:\s*\S", desc, re.MULTILINE):
        errors.append("в описании нет строки «Type: AFK|human-in-the-loop | Size: …»")
    if len(desc.strip()) < MIN_DESCRIPTION_LEN:
        errors.append(
            f"описание короче {MIN_DESCRIPTION_LEN} символов — не самодостаточно "
            "(человек вне контекста не поймёт задачу)"
        )


def check_task(task: dict, is_create: bool, label: str, errors: list[str]) -> None:
    local: list[str] = []
    name = task.get("name")
    if is_create:
        if not (isinstance(name, str) and name.strip()):
            local.append("нет названия")
        else:
            check_name(name, local)
        desc = get_description(task)
        if desc is None:
            local.append("нет описания (markdown_description)")
        else:
            check_description(desc, local)
    else:
        # update: валидируем только переданные поля, чтобы не блокировать смену статуса
        if isinstance(name, str) and name.strip():
            check_name(name, local)
        desc = get_description(task)
        if desc is not None:
            check_description(desc, local)
    errors.extend(f"{label}: {e}" for e in local)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    is_create = bool(CREATE_TOOLS.search(tool_name))
    is_update = bool(UPDATE_TOOLS.search(tool_name))
    if not (is_create or is_update):
        sys.exit(0)

    tasks = tool_input.get("tasks")
    errors: list[str] = []
    if isinstance(tasks, list):
        for i, task in enumerate(tasks):
            if isinstance(task, dict):
                check_task(task, is_create, f"tasks[{i}]", errors)
    else:
        check_task(tool_input, is_create, "task", errors)

    if errors:
        lines = "\n".join(f"- {e}" for e in errors)
        sys.stderr.write(
            "BLOCKED: задача не проходит канон постановки (решение грила 2026-07-14 — "
            f"все поля жёстко обязательны). Шаблон: {RULES_DOC}\n{lines}\n"
            "Исправь поля и повтори вызов. Напоминание: после create через MCP дожми "
            "due/assignee/estimate/теги прямым API и подтверди GET'ом — MCP их не ставит.\n"
        )
        sys.exit(2)

    sys.exit(0)


main()
