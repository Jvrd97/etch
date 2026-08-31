# [review:need-review] PHASE-03/86, PHASE-03/92, PHASE-03/93, PHASE-03/94, PHASE-03/106, PHASE-03/109, PHASE-03/111, PHASE-03/121, PHASE-03/127, PHASE-03/134, PHASE-03/152
# summary: app assembled by create_app(config) — CORS allowlist from settings, docs off in prod, dev-mode auth warning, the day boundary read from day_rule_set on startup, and the goals, days, weeks, roles, chat, day-rules, challenge and quick-marks routers in the API-key perimeter
# summary: the auth router is mounted OUTSIDE that perimeter — logging in is what a client without a key or a cookie has to be able to do
# summary: app assembled by create_app(config) — CORS allowlist from settings, docs off in prod, dev-mode auth warning, the day boundary read from day_rule_set on startup, and the goals, training and chat routers in the API-key perimeter
"""
Сборка FastAPI-приложения.

Приложение собирается функцией `create_app(config)`, а не на импорте модуля:
периметр (список разрешённых origin'ов, наличие схемы API) зависит от
настроек, и тест обязан уметь собрать приложение с другим `Settings`, не
подменяя глобальный объект. Точка входа для gunicorn/uvicorn прежняя —
`app.main:app`.
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agent,
    auth,
    categories,
    challenges,
    chat,
    daily_summary,
    day,
    day_rules,
    entries,
    goals,
    health,
    insights,
    journal,
    onboarding,
    quick_marks,
    roles,
    table,
    week,
    training,
)
from app.core.auth import require_api_key, warn_if_auth_disabled
from app.core.config import Settings, settings
from app.core.database import AsyncSessionLocal
from app.crud import day as day_crud

API_DESCRIPTION = """
    ## Habit Tracker API

    Мощный API для отслеживания привычек и создания персонального дашборда.

    ### Основные возможности:

    * **Динамические категории** - создавайте свои категории (сон, витамины, медитация и т.д.)
    * **Гибкие поля** - для каждой категории определяйте свои поля
    * **Записи данных** - добавляйте ежедневные записи с любыми данными
    * **Дневник** - ведите личный дневник с настроением и тегами
    * **Фильтрация** - получайте данные за любой период для графиков

    ### Быстрый старт:

    1. Создайте категорию (например, "Сон")
    2. Добавьте к ней поля (например, "Продолжительность", "Качество")
    3. Создавайте ежедневные записи
    4. Получайте данные для графиков через API

    ### Архитектура:

    - PostgreSQL 16 для хранения данных
    - EAV модель для гибкости структуры
    - Async/Await для высокой производительности
    - Полный CRUD для всех сущностей
    """

# Роутеры, которые подключаются под API-key auth с общим префиксом
API_ROUTERS = (
    agent.router,
    categories.router,
    entries.router,
    journal.router,
    table.router,
    insights.router,
    onboarding.router,
    daily_summary.router,
    health.router,
    day.router,
    day_rules.router,
    goals.router,
    roles.router,
    training.router,
    chat.router,
    week.days_router,
    week.weeks_router,
    quick_marks.router,
    challenges.router,
)


async def _publish_day_boundary() -> None:
    """
    Прочитать действующее правило дня и отдать его границу суток в `daytime`.

    Читается на старте, чтобы `local_date()` отвечал по таблице с первого
    запроса, а не по настройкам до первого обращения к дню. База может быть
    недоступна или ещё не мигрирована — это не повод не стартовать: в этом
    случае остаётся запасной источник (`APP_TIMEZONE`/`DAY_START_HOUR`), чьи
    значения по умолчанию равны сидовой строке правила.
    """
    try:
        async with AsyncSessionLocal() as session:
            if not await day_crud.refresh_day_boundary(session):
                print(
                    "⚠️  day_rule_set is empty: the day boundary falls back to "
                    "APP_TIMEZONE/DAY_START_HOUR until the migration runs"
                )
    except Exception as error:  # noqa: BLE001 - старт не зависит от базы
        print(
            f"⚠️  could not read day_rule_set at startup ({error!r}); the day "
            "boundary falls back to APP_TIMEZONE/DAY_START_HOUR"
        )


def create_app(config: Settings) -> FastAPI:
    """Собрать приложение по настройкам: периметр берётся из них, не из констант."""
    docs_url = "/docs" if config.docs_enabled else None
    redoc_url = "/redoc" if config.docs_enabled else None
    openapi_url = (
        f"{config.API_V1_PREFIX}/openapi.json" if config.docs_enabled else None
    )

    app = FastAPI(
        title=config.PROJECT_NAME,
        version=config.VERSION,
        description=API_DESCRIPTION,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    # CORS: в разработке список равен ["*"], в проде — явное перечисление
    # origin'ов фронтенда (звёздочка там роняет старт, см. app/core/config.py).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Sessions live outside the perimeter on purpose: a browser with neither a
    # key nor a cookie must still be able to log in and to ask whether it is
    # logged in. The three handlers return a boolean and a lifetime, nothing else.
    app.include_router(auth.router, prefix=config.API_V1_PREFIX)

    api_key_dependencies = [Depends(require_api_key)]
    for router in API_ROUTERS:
        app.include_router(
            router, prefix=config.API_V1_PREFIX, dependencies=api_key_dependencies
        )

    @app.get("/")
    async def root() -> dict[str, str]:
        """
        Корневой endpoint.
        Перенаправляет на документацию API.
        """
        return {
            "message": config.PROJECT_NAME,
            "version": config.VERSION,
            "docs": docs_url or "disabled",
            "redoc": redoc_url or "disabled",
        }

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """
        Проверка здоровья сервиса.
        Используется для мониторинга и health checks в Docker.
        """
        return {"status": "healthy", "service": "habit-tracker-backend"}

    # Event handlers
    @app.on_event("startup")
    async def startup_event() -> None:
        """
        Действия при запуске приложения.
        """
        warn_if_auth_disabled()
        await _publish_day_boundary()
        print("🚀 Starting Habit Tracker API...")
        print(f"📚 Documentation: {docs_url or 'disabled (ENVIRONMENT=prod)'}")

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        """
        Действия при остановке приложения.
        """
        print("👋 Shutting down Habit Tracker API...")

    return app


app = create_app(settings)
