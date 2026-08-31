# [review:need-review] PHASE-03/120
# summary: deploy & ops shortcuts; `preflight` delegates the pre-deploy run (check + live-CLI isolation smoke) to the backend; `up`/`deploy` end in `verify`, which fails the build when the containers are not running this commit
# habit-tracker/Makefile — deploy & ops shortcuts (run from this dir on the VPS),
# plus the local dev entrypoint (`make dev`) used on a laptop.
# Prod stack = base compose + prod override + the optional `web` (frontend) profile.
COMPOSE = docker compose --profile web -f docker-compose.yml -f ../deploy/docker-compose.prod.yml
# Local stack = base compose only, no prod override.
DEV_COMPOSE = docker compose -f docker-compose.yml

# The commit being deployed. Two jobs, both in deploy/docker-compose.prod.yml and
# deploy/verify-deploy.sh: it is stamped onto every image as the OCI label
# org.opencontainers.image.revision at build time, and it is what `verify` compares
# that label against afterwards. Exported so compose interpolation sees it.
# Note the `:=` — evaluated once, when make starts. `deploy` therefore does its
# `git pull` and then re-enters make (`$(MAKE) up`) instead of building inline: a
# fresh make process re-reads HEAD, so the images are labelled with the commit that
# was just pulled and not with the one that was checked out a minute earlier.
GIT_SHA := $(shell git -C .. rev-parse HEAD 2>/dev/null)
export GIT_SHA

BACKEND_DIR = services/backend
FRONTEND_DIR = services/frontend
# Where the local postgres listens. The machine's own instance sits on 5432;
# the docker one publishes 5433 — switch per run: `make dev PG_PORT=5433`.
PG_HOST ?= localhost
PG_PORT ?= 5432
# One database per branch would be safest; at minimum override PG_DB when a
# second checkout of this repo runs migrations from a different branch against
# the same postgres — a foreign revision leaves the shared database on a
# version the other branch cannot find.
PG_DB ?= habit_tracker
PG_USER = habit_user
DEV_DB_ENV = POSTGRES_HOST=$(PG_HOST) POSTGRES_PORT=$(PG_PORT) POSTGRES_DB=$(PG_DB)
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 3000

.DEFAULT_GOAL := help
.PHONY: help up down stop restart logs ps build migrate deploy verify preflight backup enable-boot \
        dev dev-back dev-front dev-deps dev-createdb dev-migrate dev-stop dev-db dev-docker \
        front-check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up: ## Build and start everything (backend, frontend, postgres), detached, then verify
	@test -n "$(GIT_SHA)" || { echo "make up: 'git rev-parse HEAD' gave nothing — is this a git checkout?"; exit 1; }
	$(COMPOSE) up -d --build
	@$(MAKE) --no-print-directory verify

down: ## Stop and remove containers (DB volume is kept)
	$(COMPOSE) down

stop: ## Stop containers without removing them
	$(COMPOSE) stop

restart: ## Restart all running services
	$(COMPOSE) restart

logs: ## Follow logs of all services
	$(COMPOSE) logs -f --tail=100

ps: ## Show container status
	$(COMPOSE) ps

build: ## Rebuild images without starting
	$(COMPOSE) build

migrate: ## Apply DB migrations (alembic upgrade head)
	$(COMPOSE) exec backend alembic upgrade head

deploy: ## Full redeploy: pull main, rebuild, restart, VERIFY, migrate (run `make preflight` first)
	git -C .. pull origin main
	@$(MAKE) --no-print-directory up
	$(COMPOSE) exec backend alembic upgrade head

verify: ## Prove the running containers are this commit's build; exits non-zero if not
	@COMPOSE="$(COMPOSE)" bash ../deploy/verify-deploy.sh

preflight: ## Pre-deploy run: backend check + the live-CLI isolation smoke (PHASE-03/120)
	$(MAKE) -C $(BACKEND_DIR) preflight

backup: ## Run a one-off DB backup (see deploy/backup.sh)
	bash ../deploy/backup.sh

enable-boot: ## Make Docker (and restart:always containers) start on system boot
	sudo systemctl enable --now docker
	@echo "Docker enabled on boot. Containers use 'restart: always', so they auto-start."

# --- local development ---------------------------------------------------
# No docker at all: uvicorn and next run straight on the host against a
# postgres that already runs there. Point PG_HOST/PG_PORT at whichever
# instance holds the habit_tracker database; the docker one publishes 5433,
# a brew-installed one listens on 5432.
# `make dev-db` / `make dev-docker` stay available for the container route.

dev: dev-migrate ## Run backend + frontend on the host; one Ctrl+C stops both
	@echo "backend  http://localhost:$(BACKEND_PORT)/docs"
	@echo "frontend http://localhost:$(FRONTEND_PORT)"
	@trap 'kill 0' INT TERM; \
	( cd $(BACKEND_DIR) && $(DEV_DB_ENV) uv run uvicorn app.main:app --reload --port $(BACKEND_PORT) 2>&1 | sed 's/^/[back ] /' ) & \
	( cd $(FRONTEND_DIR) && API_PROXY_TARGET=http://localhost:$(BACKEND_PORT) bun run dev --port $(FRONTEND_PORT) 2>&1 | sed 's/^/[front] /' ) & \
	wait

dev-back: ## Backend only, hot reload, no container
	cd $(BACKEND_DIR) && $(DEV_DB_ENV) uv run uvicorn app.main:app --reload --port $(BACKEND_PORT)

dev-front: ## Frontend only, hot reload, proxying /api/v1 to the backend port
	cd $(FRONTEND_DIR) && API_PROXY_TARGET=http://localhost:$(BACKEND_PORT) bun run dev --port $(FRONTEND_PORT)

dev-deps: ## Install backend (uv) and frontend (bun) dependencies
	cd $(BACKEND_DIR) && uv sync
	cd $(FRONTEND_DIR) && bun install

dev-createdb: ## Create the habit_tracker database if the local postgres lacks it
	@psql -h $(PG_HOST) -p $(PG_PORT) -d postgres -tAc \
		"select 1 from pg_database where datname='$(PG_DB)'" | grep -q 1 \
		&& echo "$(PG_DB) already exists" \
		|| createdb -h $(PG_HOST) -p $(PG_PORT) -O $(PG_USER) $(PG_DB)

dev-migrate: dev-createdb ## Apply migrations against the postgres at PG_HOST:PG_PORT
	cd $(BACKEND_DIR) && $(DEV_DB_ENV) uv run alembic upgrade head

dev-stop: ## Stop the host dev processes
	@pkill -f "uvicorn app.main:app" 2>/dev/null && echo "backend stopped" || echo "backend not running"
	@pkill -f "next dev" 2>/dev/null && echo "frontend stopped" || echo "frontend not running"

front-check: ## Build the frontend and prove the API key is not in the bundle (needs API_KEY)
	@test -n "$(API_KEY)" || (echo "front-check needs API_KEY=<the deployed key>"; exit 1)
	cd $(FRONTEND_DIR) && bun run build && bun run check:bundle $(API_KEY)

dev-db: ## Optional: start postgres in docker (publishes host port 5433)
	$(DEV_COMPOSE) up -d postgres

dev-docker: ## Optional: the whole stack in docker (base compose, no prod override)
	$(DEV_COMPOSE) up --build
