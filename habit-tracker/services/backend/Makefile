# [review:need-review] PHASE-01/adhoc-makefile, PHASE-03/85-phase-03-bookkeeping, PHASE-03/120
# summary: containerless backend run — gunicorn with uvicorn workers, db in docker;
# summary: `check` also guards the migration chain against a second alembic head;
# summary: `preflight` = `check` plus the live-CLI isolation smoke, the run made before a deploy

# Postgres runs in docker published on host 5433 (5432 is taken by another dev instance)
DB_ENV = POSTGRES_HOST=localhost POSTGRES_PORT=5433
# conftest defaults to the docker-network host ("postgres"), which does not
# resolve from the host shell this Makefile runs in.
TEST_DB_ENV = $(DB_ENV) TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5433/habit_tracker_test
WORKERS ?= 4
PORT ?= 8000
PID_FILE = .gunicorn.pid

.PHONY: db migrate run dev test lint type heads check smoke preflight stop

## start postgres container (the only docker piece)
db:
	docker compose -f ../../docker-compose.yml up -d postgres

## apply alembic migrations
migrate: db
	$(DB_ENV) uv run alembic upgrade head

## production-style run: gunicorn master + uvicorn workers; master auto-respawns
## dead workers, --max-requests recycles them periodically
run: migrate
	$(DB_ENV) uv run gunicorn app.main:app \
		--workers $(WORKERS) \
		--worker-class uvicorn.workers.UvicornWorker \
		--bind 0.0.0.0:$(PORT) \
		--pid $(PID_FILE) \
		--max-requests 1000 --max-requests-jitter 50 \
		--graceful-timeout 30 --timeout 60 \
		--access-logfile - --error-logfile -

## dev run: single uvicorn with hot reload
dev: migrate
	$(DB_ENV) uv run uvicorn app.main:app --reload --port $(PORT)

test: db
	$(TEST_DB_ENV) uv run pytest tests/ -q

lint:
	uv run ruff check app tests && uv run ruff format --check app tests

type:
	uv run mypy --strict app

## the revision chain must be linear: exactly one head. Two heads mean two themes
## branched from the same parent and someone will have to hand-write a merge
## revision — reads the versions directory only, no database needed.
heads:
	@count=$$(uv run alembic heads 2>/dev/null | grep -c .); \
	if [ "$$count" -ne 1 ]; then \
		echo "alembic: expected exactly one head, found $$count:"; \
		uv run alembic heads; \
		echo "whoever branched second rebases their down_revision onto the other head."; \
		exit 1; \
	fi

check: lint type heads test

## live-CLI isolation smoke (PHASE-03/120). Needs the `claude` binary and a
## subscription, so it is off in the ordinary `pytest` run and switched on by
## LLM_CLI_SMOKE. Authentication goes through CLAUDE_CODE_OAUTH_TOKEN: an
## explicit CLAUDE_CONFIG_DIR turns off the login the binary would find on its
## own (keychain on macOS, mounted config in the container) — without the token
## the smoke skips with that reason instead of failing.
## SMOKE_CONFIG_DIR defaults to the developer's own `~/.claude`, which is the
## strongest form of the check: the personal configuration (its MCP servers
## above all) sits right there and must stay out of the prefix. On the server
## override SMOKE_CONFIG_DIR/SMOKE_CWD with the deployed paths.
SMOKE_CONFIG_DIR ?= $(HOME)/.claude
SMOKE_CWD ?= /tmp/claude-cli-smoke
smoke:
	LLM_CLI_SMOKE=1 \
	CHAT_CLAUDE_CONFIG_DIR=$(SMOKE_CONFIG_DIR) \
	CHAT_CLI_CWD=$(SMOKE_CWD) \
	uv run pytest tests/test_cli_isolation_smoke.py -q

## the run made before a deploy: everything `check` does plus the live smoke
preflight: check smoke

## stop everything: gunicorn (pidfile, fallback pkill), dev uvicorn, all docker containers
stop:
	@if [ -f $(PID_FILE) ]; then kill "$$(cat $(PID_FILE))" 2>/dev/null && echo "gunicorn stopped (pidfile)" || true; rm -f $(PID_FILE); \
	else pkill -f "gunicorn app.main:app" 2>/dev/null && echo "gunicorn stopped (pkill)" || echo "gunicorn not running"; fi
	@pkill -f "$(CURDIR)/.venv/bin/uvicorn app.main:app" 2>/dev/null && echo "dev uvicorn stopped" || echo "dev uvicorn not running"
	docker compose -f ../../docker-compose.yml stop
