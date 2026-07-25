# [review:need-review] PHASE-01/13-backend-uv-mypy-ruff
# summary: image built with uv (uv.lock, no requirements.txt); venv outside /app to survive the compose bind mount; + node & claude CLI for the cli insights backend
FROM python:3.10-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node + claude CLI: LLM_BACKEND=cli shells out to `claude -p`, and
# resolve_insights_client() disables insights (503) when the binary is
# absent. Credentials are not baked in — the host's ~/.claude is mounted
# by docker-compose at runtime.
ENV NODE_MAJOR=22
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

# Keep the venv outside /app: docker-compose bind-mounts the source dir
# over /app, which would shadow an in-project .venv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install locked dependencies first (layer cache friendly)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application code
COPY . .

ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8000

# Startup command lives in docker-compose
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
