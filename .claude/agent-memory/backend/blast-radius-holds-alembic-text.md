---
name: blast-radius-holds-alembic-text
description: the harness Blast Radius check holds any Bash command that runs or merely contains the text `alembic upgrade`, and waits 10 minutes for a human who is usually absent
metadata:
  type: feedback
---

В рое команды с `alembic upgrade` останавливает проверка Blast Radius: «no answer within 10 minutes», команда не выполняется, повторять её нельзя без просьбы человека. Проверка срабатывает и на текст: heredoc с записью в SESSION_REVIEW, где было написано `alembic upgrade`, тоже был остановлен, хотя ничего не запускал.

**Why:** 2026-10-25, круг 1 тикета #105. Первый раз остановлена настоящая `alembic upgrade head` на `habit_live_105`, второй раз — запись текста через `cat <<EOF`. Оба раза 10 минут простоя.

**How to apply:** миграцию проверяй офлайн (`command.upgrade(config, "a:b", sql=True)` внутри pytest, как в `tests/test_categories.py`) и `alembic heads`; для живой проверки экрана строй схему из моделей (`Base.metadata.create_all`) в своей `habit_test_<id>`. Текст про `alembic upgrade` в файлы пиши инструментами Edit/Write, а не через shell. В сдаче честно напиши, что применение ревизии на живой базе не запускалось.
