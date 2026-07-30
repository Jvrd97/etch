# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: registered daily-summary router (draft/apply) under API-key auth
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    categories,
    daily_summary,
    entries,
    insights,
    journal,
    onboarding,
    table,
)
from app.core.auth import require_api_key
from app.core.config import settings

# Создаём приложение FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="""
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
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры (все под API-key auth)
API_KEY_DEPENDENCIES = [Depends(require_api_key)]

app.include_router(
    categories.router, prefix=settings.API_V1_PREFIX, dependencies=API_KEY_DEPENDENCIES
)
app.include_router(
    entries.router, prefix=settings.API_V1_PREFIX, dependencies=API_KEY_DEPENDENCIES
)
app.include_router(
    journal.router, prefix=settings.API_V1_PREFIX, dependencies=API_KEY_DEPENDENCIES
)
app.include_router(
    table.router, prefix=settings.API_V1_PREFIX, dependencies=API_KEY_DEPENDENCIES
)
app.include_router(
    insights.router, prefix=settings.API_V1_PREFIX, dependencies=API_KEY_DEPENDENCIES
)
app.include_router(
    onboarding.router, prefix=settings.API_V1_PREFIX, dependencies=API_KEY_DEPENDENCIES
)
app.include_router(
    daily_summary.router,
    prefix=settings.API_V1_PREFIX,
    dependencies=API_KEY_DEPENDENCIES,
)


@app.get("/")
async def root() -> dict[str, str]:
    """
    Корневой endpoint.
    Перенаправляет на документацию API.
    """
    return {
        "message": "Habit Tracker API",
        "version": settings.VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
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
    print("🚀 Starting Habit Tracker API...")
    print("📚 Documentation: http://localhost:8000/docs")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """
    Действия при остановке приложения.
    """
    print("👋 Shutting down Habit Tracker API...")
