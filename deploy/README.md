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

6. Бэкапы — раздел «Бэкап» ниже. Это не последний пункт установки, а условие эксплуатации: с тикета #88 база — единственная копия дня.

## Периметр (тикет #106)

Продовый override задаёт `ENVIRONMENT=prod`. В этом режиме две дырявые настройки роняют старт контейнера с сообщением, называющим переменную:

- пустой `API_KEY` — он выключает аутентификацию целиком;
- `*` в `CORS_ORIGINS` — он разрешает вызывать API со страницы любого сайта.

`CORS_ORIGINS` — список origin'ов через запятую, без кавычек и скобок: `CORS_ORIGINS=http://habit.tailnet:3000`. Пустое значение (по умолчанию в проде) допустимо и безопасно: фронтенд на Next.js проксирует `/api/v1` на бэкенд серверной стороной (`API_PROXY_TARGET`), поэтому браузер кросс-доменных запросов не делает. Заполнять — только под клиент, который ходит в API из браузера напрямую.

**Решение по документации API: в `prod` `/docs`, `/redoc` и `openapi.json` отключены целиком** (в dev остаются) — Swagger UI грузится браузером и не может послать заголовок `X-API-Key`, так что «закрыть ключом» для него не работает; вернуть их можно будет вместе с сессионной кукой (#109).

Разработка не меняется: без `ENVIRONMENT` настройки по умолчанию — `dev`, пустой ключ и `CORS_ORIGINS=*`. Про выключенную аутентификацию бэкенд печатает предупреждение один раз на старте.

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

## Бэкап (тикет #96)

С тикета #88 отметки дня живут только в базе: `.html` в `.gitignore`, git больше не журнал изменений дня. Потеря базы стоит не отметок, а всего. Поэтому бэкап — условие эксплуатации, а не пожелание.

Три скрипта, каждый со своей задачей:

| Скрипт | Когда | Что делает | Когда падает |
| --- | --- | --- | --- |
| `backup.sh` | ежедневно, 03:00 | `pg_dump` → `backups/habit_tracker_<стамп>.sql.gz`, ротация | дамп не снялся, поток не читается gzip'ом, дамп меньше 1 КБ |
| `restore-check.sh` | еженедельно, пн 04:30 | восстанавливает свежий дамп в одноразовую базу и печатает числа дней, планов, пунктов и отметок | дампа нет; свежий старше 36 ч; предыдущий `backup.sh` записал FAIL; дамп битый; в дампе нашлась строка, похожая на секрет; в восстановленной базе ноль дней |
| `export-md.sh` | еженедельно, пн 04:15 | прогоняет `app.exports.personal_os` — прошедшая неделя ложится в `backups/exports/<YYYY-Www>/plans/YYYY/MM/*.md` | экспортёр не записал ни одного файла |

Установка:

```bash
chmod +x /opt/habit-tracker/deploy/{backup.sh,restore-check.sh,export-md.sh}
crontab -e
```

```cron
0  3 * * *  /opt/habit-tracker/deploy/backup.sh       >> /var/log/habit-backup.log 2>&1
15 4 * * 1  /opt/habit-tracker/deploy/export-md.sh    >> /var/log/habit-backup.log 2>&1
30 4 * * 1  /opt/habit-tracker/deploy/restore-check.sh >> /var/log/habit-backup.log 2>&1
```

**Ротация — 14 дней, но не до нуля.** `backup.sh` удаляет дампы старше `KEEP_DAYS=14` и при этом всегда оставляет три самых свежих (`MIN_KEEP=3`), сколько бы им ни было лет. Чистая ротация по возрасту опустошает каталог через две недели после того, как cron молча умер, — ровно в тот момент, когда дамп нужен.

**Провал виден в трёх местах.** `backup.sh` пишет `backups/backup-status` на каждом прогоне (`OK` или `FAIL stage=… exit=…`), возвращает ненулевой код и печатает строку в stderr — она попадает в `/var/log/habit-backup.log`. `restore-check.sh` читает этот же файл и отказывается, если там `FAIL` или если свежему дампу больше 36 часов. То есть недельная проверка ловит и «дамп не снялся», и «cron вообще не запускался». Мониторинга в проекте нет намеренно (Out of Scope #96) — минимум раз в неделю посмотреть на хвост лога всё ещё придётся глазами:

```bash
tail -n 40 /var/log/habit-backup.log
cat /opt/habit-tracker/backups/backup-status
```

**Дамп не должен содержать секретов, и это проверяется.** `restore-check.sh` перед восстановлением гоняет по распакованному дампу `grep -E` по списку `SECRET_PATTERNS` (префиксы токенов Google `ya29.`/`1//0`, ключи `sk-ant-`, `CLAUDE_CODE_OAUTH_TOKEN`, `BEGIN … PRIVATE KEY`, `telethon.session`) и падает на первом совпадении. Ложное срабатывание на тексте плана лечится переопределением `SECRET_PATTERNS` в окружении, а не игнорированием отказа.

Проверить руками в любой момент:

```bash
gzip -dc /opt/habit-tracker/backups/habit_tracker_<стамп>.sql.gz \
  | grep -nE 'ya29\.|sk-ant-|CLAUDE_CODE_OAUTH_TOKEN|BEGIN [A-Z ]*PRIVATE KEY'
```

Пустой вывод — то, что нужно.

## Что делать, когда база потеряна

Порядок доводит от дампа до открытой страницы дня. Ничего, кроме этого раздела и содержимого `backups/`, для восстановления не нужно.

1. **Найти самый свежий дамп и убедиться, что он живой.**

   ```bash
   ls -1 /opt/habit-tracker/backups/habit_tracker_*.sql.gz | sort -r | head -3
   cat /opt/habit-tracker/backups/backup-status
   /opt/habit-tracker/deploy/restore-check.sh
   ```

   `restore-check OK` и строка `restored: days=… plans=… items=… marks=…` — дамп восстанавливается и в нём есть дни. Скрипт делает это в одноразовой базе и удаляет её за собой, боевую он не трогает.

2. **Поднять пустой постгрес,** если контейнер потерян вместе с томом:

   ```bash
   cd /opt/habit-tracker/habit-tracker
   docker compose -f docker-compose.yml -f ../deploy/docker-compose.prod.yml up -d postgres
   ```

3. **Снести остатки боевой базы и создать её заново.** Шаг необратимый — делать только после пункта 1.

   ```bash
   docker exec -i habit_postgres psql -U habit_user -d postgres \
     -c 'DROP DATABASE IF EXISTS habit_tracker;' -c 'CREATE DATABASE habit_tracker;'
   ```

4. **Залить дамп.**

   ```bash
   gzip -dc /opt/habit-tracker/backups/habit_tracker_<стамп>.sql.gz \
     | docker exec -i habit_postgres psql -U habit_user -v ON_ERROR_STOP=1 -q -d habit_tracker
   ```

5. **Догнать миграции.** Дамп снят с той схемы, что была ночью; код мог уехать вперёд.

   ```bash
   docker compose -f docker-compose.yml -f ../deploy/docker-compose.prod.yml up -d --build
   docker compose exec backend alembic upgrade head
   docker compose exec backend alembic heads   # ровно одна голова
   ```

6. **Открыть день и посмотреть на него глазами.** Восстановление считается удавшимся, когда на `http://<magicdns-имя>:3000/day/<дата>` есть план с секциями и отметки стоят там, где стояли. Ручкой:

   ```bash
   curl -s -H "X-API-Key: <ключ>" http://<magicdns-имя>:8000/api/v1/day/2026-08-28 | head -c 400
   ```

7. **Что потеряно между дампом и падением.** Всё, что произошло после ночного `pg_dump`: отметки сегодняшнего дня, блокнот, входящие. Восстановить это неоткуда — репликации и PITR в проекте нет намеренно (Out of Scope #96). Частично помогает недельный экспорт `backups/exports/<YYYY-Www>/`: он читается глазами и его можно перенабрать руками.

8. **Восстановить секреты** — они в дамп не входят, см. следующий раздел.

## Что бэкап не покрывает

Дамп покрывает Postgres и экспорт `.md`. Три вещи в него не попадают **намеренно**: секреты в ротируемом файле на том же диске — худшая из возможных схем хранения секретов. Ни одна из трёх не является потерей данных, каждая перевыпускается.

| Что | Где лежит | Как получить заново |
| --- | --- | --- |
| `secrets/gmail_token.json` | на VPS рядом с приложением (тикет #100) | пройти OAuth Google заново с тем же `client_id`; токен переполучается за минуту, старый после этого можно отозвать в аккаунте Google |
| `secrets/telethon.session` | там же (тикет #102) | повторный логин в Telegram: запустить клиент Telethon, ввести номер и код из приложения; сессия создастся новая, старую отозвать в Telegram → Устройства |
| Ключ mac-агента в Keychain | связка ключей на маке, не на сервере (ADR-0019) | перевыпустить: сгенерировать новый ключ агента, положить в Keychain, прописать на сервере; старый отозвать |

`API_KEY` и `CLAUDE_CODE_OAUTH_TOKEN` живут в `habit-tracker/.env` и в дамп тоже не попадают. `API_KEY` генерируется заново (`openssl rand -hex 32`) с заменой на всех клиентах; токен CLI — `claude setup-token` на хосте.

## Проверка восстановления руками (один раз после установки)

Автоматика проверяет, что дамп восстанавливается и что в нём есть дни. Что в нём есть **нужный** день с планом и отметками, один раз проверяет человек:

```bash
/opt/habit-tracker/deploy/restore-check.sh --keep-db          # база остаётся
docker exec -i habit_postgres psql -U habit_user -d postgres -c '\l' | grep habit_restore_check
docker exec -i habit_postgres psql -U habit_user -d <имя-базы-из-вывода> -c "
  SELECT i.code, i.text_plain, m.state, m.note
  FROM plan_item i
  JOIN plan_section s ON s.id = i.section_id
  JOIN day_plan p     ON p.id = s.plan_id
  LEFT JOIN plan_mark m ON m.item_id = i.id
  WHERE p.day_date = DATE '2026-08-28' ORDER BY s.ord, i.ord;"
docker exec -i habit_postgres psql -U habit_user -d postgres -c 'DROP DATABASE "<имя-базы-из-вывода>";'
```

Строки с текстом пунктов и отметками — проверка пройдена. Дата и результат прогона записываются сюда:

| Дата | Дамп | Дней / планов / пунктов / отметок | Кто |
| --- | --- | --- | --- |
| — | — | — | прогон на VPS ещё не выполнялся |

## Проверка acceptance

- С iPhone (Tailscale включён): `curl -H "X-API-Key: <ключ>" http://<magicdns-имя>:8000/api/v1/categories` отдаёт 200, без заголовка — 401. `/docs` в проде отключён (см. «Периметр»), поэтому проверка ключа идёт curl'ом, а не через Swagger.
- Убрать `API_KEY` из `.env` и поднять заново: контейнер backend не стартует, в `docker compose logs backend` — строка про `API_KEY` и `ENVIRONMENT=prod`. Вернуть ключ.
- Из открытого интернета `curl http://<публичный-ip>:8000` — таймаут/refused. Если порт виден — закрыть публикацию 8000 на публичном интерфейсе (ufw или binding на tailscale0).
- `docker ps` — оба контейнера `restart: always`.

## Обновление версии

```bash
cd /opt/habit-tracker && git pull
cd habit-tracker && docker compose -f docker-compose.yml -f ../deploy/docker-compose.prod.yml up -d --build
docker compose exec backend alembic upgrade head
```
