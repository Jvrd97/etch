# [review:need-review] PHASE-03/106
# summary: app assembled by create_app(config) — CORS allowlist from settings, docs off in prod, dev-mode auth warning on startup
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
    categories,
    daily_summary,
    entries,
    health,
    insights,
    journal,
    onboarding,
    table,
)
from app.core.auth import require_api_key, warn_if_auth_disabled
from app.core.config import Settings, settings

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
    categories.router,
    entries.router,
    journal.router,
    table.router,
    insights.router,
    onboarding.router,
    daily_summary.router,
    health.router,
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
