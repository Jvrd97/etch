---
name: "source-command-next-task"
description: "Pick the next unblocked AFK issue from issues/ and implement it via TDD. Use for autonomous loops."
---

# source-command-next-task

Use this skill when the user asks to run the migrated source command `next-task`.

## Command Template

Apply the `implement-issue` skill.

Process:
1. Scan `issues/*.md` (excluding `issues/closed/` и `issues/in-review/`)
2. Filter to `Type: AFK` only
3. Filter to issues whose `Blocked by` are all in `issues/closed/`
4. Sort by priority: critical bugs > infra > tracer-bullet features > polish
5. Pick the top one
6. Implement using strict TDD (red → green → refactor)
7. Run feedback loops; do not finish until green
8. **Review tracking** (см. AGENTS.md §9):
   - В каждый созданный/изменённый файл кода добавить header `# [review:need-review] <ticket-id>` + `# summary: <одна строка>`.
   - Дописать секцию в `backend/services/<svc>/SESSION_REVIEW.md`: дата, ticket-id, число тронутых файлов и список с `new`/`mod`.
   - Прогнать `bashs/review-status.sh` — убедиться, что счётчик отражает новые файлы.
9. On success: move file to `issues/in-review/` (создать папку, если нет), commit ссылаясь на тикет через `Refs <issue>` (НЕ `Closes` — тикет ещё не закрыт, ждёт code-review). Закрытие в `issues/closed/` — ручной шаг после прохождения review.
10. If no AFK issues remain: output "NO MORE AFK TASKS" and stop

Use the `explorer` sub-agent for codebase investigation. Keep main context lean.
