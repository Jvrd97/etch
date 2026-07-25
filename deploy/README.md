# Деплой на VPS (тикет #02)

Целевая схема: VPS в tailnet, порты наружу не публикуются, доступ только через Tailscale (ADR-0003).

## Шаги (один раз)

1. Завести VPS (Ubuntu 22.04+, минимальный тариф достаточен). Поставить Docker: `curl -fsSL https://get.docker.com | sh`.
2. Поставить Tailscale: `curl -fsSL https://tailscale.com/install.sh | sh && tailscale up` (логин под твоим аккаунтом).
3. Склонировать репозиторий в `/opt/habit-tracker` (или `rsync` папки `habit-tracker/` + `deploy/`).
4. Задать ключ: `echo "API_KEY=<длинный случайный ключ>" > /opt/habit-tracker/habit-tracker/.env` (генерация: `openssl rand -hex 32`).
5. Запуск:

```bash
cd /opt/habit-tracker/habit-tracker
docker compose -f docker-compose.yml -f ../deploy/docker-compose.prod.yml up -d --build
docker compose exec backend alembic upgrade head
```

6. Бэкапы: `chmod +x /opt/habit-tracker/deploy/backup.sh` и добавить в crontab строку из шапки скрипта. Один раз проверить восстановление дампа.

## AI-инсайты через claude CLI

Бэкенд ходит в LLM через `claude -p` (`LLM_BACKEND=cli`), а не через `ANTHROPIC_API_KEY`. Бинарь `claude` вшит в образ backend (Node 22 + `@anthropic-ai/claude-code`), логин — только с хоста.

Аутентификация, два варианта:

1. **Долгоживущий токен (рекомендуется для сервера).** На хосте `claude setup-token`, затем дописать в `habit-tracker/.env` строку `CLAUDE_CODE_OAUTH_TOKEN=<токен>`. Не зависит от файлов логина и от того, где именно CLI держит креды.
2. **Логин с хоста томом.** На хосте один раз `claude` и пройти вход — креды лягут в `~/.claude/.credentials.json`. Compose монтирует `~/.claude` и `~/.claude.json` внутрь контейнера в `/root`. Файл `~/.claude.json` должен существовать до `up`, иначе Docker создаст на его месте директорию.

Проверка после `up`:

```bash
docker compose exec backend claude --version
echo "Reply with exactly: OK" | docker compose exec -T backend claude -p --output-format text
```

Если второй командой возвращается `Not logged in`, аутентификация не проброшена — `POST /api/v1/insights` будет отдавать 503 (`no LLM backend available`) или 502.

Таймаут gunicorn в prod поднят до 180s: генерация отчёта за 30 дней — один длинный синхронный запрос с лимитом 120s на стороне приложения.

## Проверка acceptance

- С iPhone (Tailscale включён): `http://<magicdns-имя>:8000/docs` открывается, Authorize с API-ключом работает.
- Из открытого интернета `curl http://<публичный-ip>:8000` — таймаут/refused. Если порт виден — закрыть публикацию 8000 на публичном интерфейсе (ufw или binding на tailscale0).
- `docker ps` — оба контейнера `restart: always`.

## Обновление версии

```bash
cd /opt/habit-tracker && git pull
cd habit-tracker && docker compose -f docker-compose.yml -f ../deploy/docker-compose.prod.yml up -d --build
docker compose exec backend alembic upgrade head
```
