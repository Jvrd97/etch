---
name: python-standards
description: "Python coding standards for this project. Use when writing or modifying Python code: FastAPI services, SQLAlchemy models, Alembic migrations, pytest tests, async logic, exception handling, logging. Triggers on Python file creation/edit, code review, refactoring."
---

# Python Coding Standards

Полный гайд для написания Python кода в этом проекте. Критические правила также продублированы в AGENTS.md.

## Tooling

- **Package manager**: `uv` (НЕ poetry, НЕ pip напрямую)
  - `uv sync` — установить deps
  - `uv add <pkg>` — добавить
  - `uv run <cmd>` — запуск в окружении
- **Lint/format**: `ruff` (лучше чем black + isort + flake8 вместе)
- **Type check**: `mypy --strict`
- **Tests**: `pytest` + `pytest-asyncio` для async
- **Pre-commit**: ruff + mypy на pre-commit hook

## Type Hints

```python
# ✅ Правильно (Python 3.10+ style)
def get_users(ids: list[int]) -> dict[int, User | None]:
    ...

async def fetch(client: AsyncClient) -> list[Result]:
    ...

# ❌ Старый стиль — не использовать
from typing import List, Dict, Optional
def get_users(ids: List[int]) -> Dict[int, Optional[User]]:  # NO
    ...
```

- Все public функции/методы типизированы
- Internal helpers — желательно типизировать, но не блокер
- Никогда `Any` без inline комментария-обоснования
- `# type: ignore` только с reason: `# type: ignore[arg-type]  # legacy lib stub broken`

## FastAPI

### Routes
```python
# ✅ Async route, DTO для response, Depends для shared logic
@router.get("/{user_id}", response_model=UserResponseDTO)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> UserResponseDTO:
    user = await user_service.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return UserResponseDTO.model_validate(user)
```

### Тонкий роутер (MANDATORY)
Роутер только парсит вход, дёргает один метод сервиса и возвращает DTO. Бизнес-логика,
работа с БД (`db.add/commit/refresh`), проверки, публикация событий и `model_validate`
живут в `app/services/` (где есть `repositories/`/`crud/` — доступ к БД там, сервис
оркестрирует). Эталон: `collection-service` (`allergies.py` + `allergy_service.py`).
Обоснование — `docs/GENERAL/ADRs/done/ADR-001-thin-routers-service-layer.md`.

```python
# ✅ роутер тонкий
def _svc(db: AsyncSession = Depends(get_session)) -> AllergyService:
    return AllergyService(db)

@router.post("/me", response_model=AllergyResponse, status_code=201)
async def create_allergy(payload: AllergyCreate, svc: AllergyService = Depends(_svc)):
    return await svc.create(user.user_id, payload)

# ❌ db.add/commit/model_validate прямо в роутере — логика утекла из сервиса
```

### Don'ts
- Никогда не возвращай domain model напрямую — всегда DTO
- Никаких `db.add/commit/refresh` и доменной логики в роутере — это работа сервиса
- Никаких I/O операций в middleware (только трансформация request/response)
- Не делай blocking calls (`requests.get`, `time.sleep`) в async route — используй `httpx.AsyncClient`, `await asyncio.sleep`

### Структура сервиса
```
services/<name>/
├── app/
│   ├── api/                  # routes (только thin layer)
│   ├── services/             # бизнес-логика
│   ├── models/               # SQLAlchemy
│   ├── schemas/              # Pydantic DTO
│   ├── crud/                 # DB operations (если используется)
│   ├── clients/              # external API clients
│   ├── core/                 # config, deps, security
│   └── alembic/              # миграции
```

## SQLAlchemy 2.0

```python
# ✅ Правильно — типизированные модели
class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    profile: Mapped["UserProfile | None"] = relationship(back_populates="user")
```

```python
# ❌ Старый стиль — не использовать
class User(Base):
    id = Column(UUID, primary_key=True)
    email = Column(String(255))
```

### Async sessions
```python
async with AsyncSession(engine) as session:
    result = await session.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()
```

### Don'ts
- Не используй `query()` API (legacy) — только `select()`
- Не вытаскивай объекты из закрытой сессии — DetachedInstanceError
- Не делай N+1 — `selectinload()` или `joinedload()` для relationships

## Alembic Migrations

### Создание
```bash
uv run alembic revision --autogenerate -m "add_user_profile_table"
```

### Правила
1. **Никогда** не редактируй применённую миграцию (даже свою). Пиши новую.
2. **Всегда** заполни `downgrade()` — миграция должна быть reversible
3. **Никогда** не делай data migration в DDL миграции — отдельный alembic скрипт или одноразовый Python script
4. Multi-step rollouts (add column nullable → backfill → make NOT NULL) — три миграции, не одна

### Запуск
```bash
uv run alembic upgrade head     # применить
uv run alembic downgrade -1     # откатить одну
uv run alembic current          # где сейчас
uv run alembic history          # все миграции
```

## Exception Handling

```python
# ✅ Правильно — конкретные exceptions, логирование, контекст
try:
    user = await fetch_user(user_id)
except UserNotFoundError as e:
    logger.warning("user_lookup_failed", user_id=user_id, reason=str(e))
    raise HTTPException(404, "User not found") from e
except HTTPError as e:
    logger.error("upstream_failed", user_id=user_id, status=e.response.status_code)
    raise HTTPException(503, "Service unavailable") from e
```

### Don'ts
```python
# ❌ Bare except
try:
    do_thing()
except:  # NEVER
    pass

# ❌ Generic Exception без обоснования
try:
    do_thing()
except Exception:
    pass  # NEVER - проглатывает баги

# ❌ Без `from e` — теряется trace
raise HTTPException(500) # лучше: raise ... from e
```

### Кастомные exceptions
```python
class DomainError(Exception):
    """Base for domain errors."""

class UserNotFoundError(DomainError):
    """User does not exist."""

class InsufficientPermissionsError(DomainError):
    """User lacks required permission."""
```

API layer мапит DomainError на HTTPException, services кидают DomainError.

## Tests

### Структура
```
tests/
├── unit/                    # быстрые, без I/O
├── integration/             # с реальным DB, Redis, etc — testcontainers
└── e2e/                     # полный flow, минимально
```

### Pytest patterns
```python
# ✅ Async test с fixture
@pytest.mark.asyncio
async def test_user_creation(db_session: AsyncSession):
    user = await user_service.create(db_session, email="a@b.com")
    assert user.id is not None

# ✅ Параметризация
@pytest.mark.parametrize("email,valid", [
    ("a@b.com", True),
    ("not-email", False),
    ("", False),
])
def test_email_validation(email, valid):
    assert is_valid_email(email) == valid
```

### Don'ts
- Никогда `time.sleep()` в тестах — используй `freezegun` для дат, `await asyncio.sleep(0)` для cooperative
- Никогда сетевых вызовов в unit tests — мокай через `pytest-httpx` или `respx`
- Никогда `assert True` или `expect()` без actual assertion — это smoke без проверки
- Тесты не зависят от порядка запуска — каждый создаёт свой state
- Fixture скоупы: `function` default, `module`/`session` только если оправдано

### Test coverage
- New non-trivial функции — обязательно тесты
- Bug fixes — обязательно regression test
- Внутренние helpers (private методы) — необязательно

## Logging

```python
import structlog

logger = structlog.get_logger()

# ✅ Структурированные логи
logger.info("user_logged_in", user_id=user.id, source="oauth_google")
logger.warning("rate_limit_hit", user_id=user.id, endpoint="/api/foo")
logger.error("payment_failed", user_id=user.id, amount=99.99, error_code="ECARD")
```

### Don'ts
- Никаких PII в логах (полный email, имена, медицинские данные, токены, пароли)
  - Используй: `user_id`, hash email, redact card numbers
- Никаких f-strings для error messages — используй структурированные fields:
  ```python
  # ❌ logger.error(f"Failed for user {user.email}")
  # ✅ logger.error("operation_failed", user_id=user.id)
  ```

## Configuration

```python
# ✅ Pydantic Settings, env-based
class Settings(BaseSettings):
    database_url: str
    redis_url: str
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")

settings = Settings()
```

- Никаких секретов в коде
- Никаких `os.environ.get(...)` разбросанных по коду — всё через Settings
- Локальные defaults в `.env.example`, реальные в `.env` (gitignored)

## Containers / Health

Каждый сервис должен иметь:
```python
@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}

@router.get("/readyz", include_in_schema=False)
async def readyz(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    # Проверка реальных зависимостей
    await db.execute(select(1))
    return {"status": "ready"}
```

## Code Review Checklist

Когда ревьюишь свой код перед `/git-commit`:

1. **Cleanup**: нет debug print, console.log, commented-out code, useless TODO
2. **Tests**: новый функционал имеет тесты, regression test для багов
3. **Contracts**: API типизирован, DTO для responses, никаких raw models
4. **Typing**: нет `Any`, нет `# type: ignore` без обоснования
5. **Security**: нет hardcoded secrets, нет SQL string concat, нет `eval()`
6. **Consistency**: следует существующим паттернам в репо

Если запускаешь `/review` — sub-agent это всё проверит автоматически.
