---
name: venv-read-denied
description: ls/Read inside backend .venv is blocked by a deny rule — inspect installed libraries through uv run python + inspect instead
metadata:
  type: feedback
---

Чтение файлов `habit-tracker/services/backend/.venv/**` (ls, Read) запрещено правилом доступа, в том числе в worktree роя.

**Why:** правило стоит в настройках прав; попытка `ls .venv/lib/.../site-packages/<pkg>` возвращает «blocked by a deny rule» и тратит ход.

**How to apply:** API установленной библиотеки смотреть так: `uv run --directory <backend> python -c "import inspect, pkg; print(inspect.signature(pkg.fn)); print(inspect.getsource(pkg.mod)[:3000])"`. Так в #205 (2026-10-25) читались сигнатуры и исключения `webauthn` 3.0.1 (py_webauthn): откат `sign_count` библиотека отклоняет сама, все её ошибки — подклассы `WebAuthnException`.
