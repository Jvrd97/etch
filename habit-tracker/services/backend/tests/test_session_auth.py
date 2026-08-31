"""
Тесты сессии веб-клиента: обмен ключа на куку и жизнь этой куки.

Почти всё здесь происходит до обработчика — заголовок, кука, подпись, срок — и
базы не требует. Постгрес берут только два теста, которым нужен успешный ответ
защищённой ручки: «кука пускает» доказывается двухсоткой, а не тем, что ответ
оказался не 401.
"""

# [review:need-review] PHASE-03/109
# summary: key -> cookie exchange, cookie attributes read off Set-Cookie, tampered/expired/foreign-secret cookies, X-API-Key still working, logout
import time
from collections.abc import AsyncGenerator
from http.cookies import SimpleCookie

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.auth as api_auth
from app.core import auth as auth_module
from app.core.config import DEV_SESSION_SECRET, PerimeterError, Settings
from app.core.database import get_db
from app.core.session import SESSION_COOKIE_NAME, issue_session_token
from app.main import app

SESSION_URL = "/api/v1/auth/session"
PROTECTED_URL = "/api/v1/categories"
TEST_KEY = "session-tests-api-key"
TEST_SECRET = "session-tests-signing-secret"
MAX_AGE_S = 30 * 24 * 60 * 60
# The cookie carries `Secure`; over http it would never leave the jar.
SECURE_BASE_URL = "https://test"


def session_settings(**overrides: object) -> Settings:
    """Настройки процесса, у которого обе схемы аутентификации включены."""
    values: dict[str, object] = {
        "ENVIRONMENT": "dev",
        "API_KEY": TEST_KEY,
        "SESSION_SECRET": TEST_SECRET,
        "SESSION_MAX_AGE_S": MAX_AGE_S,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]  # BaseSettings takes **kwargs


def _use(monkeypatch: pytest.MonkeyPatch, config: Settings) -> Settings:
    """
    Подменить настройки в обоих модулях, которые их читают.

    Зависимость аутентификации смотрит в `app.core.auth.settings`, ручки входа —
    в `app.api.auth.settings`. Подменить один конец значит проверить ключ из
    `conftest`, а не свой.
    """
    monkeypatch.setattr(auth_module, "settings", config)
    monkeypatch.setattr(api_auth, "settings", config)
    return config


@pytest.fixture(scope="function")
def configured(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Обе схемы включены: ключ настроен, секрет подписи свой."""
    return _use(monkeypatch, session_settings())


@pytest.fixture(scope="function")
async def client(configured: Settings) -> AsyncGenerator[AsyncClient, None]:
    """
    Клиент без единого заголовка аутентификации по умолчанию и без базы.

    Схема `https` тут не косметика: кука выпускается с атрибутом `Secure`, и по
    http её не отправит ни браузер, ни банка httpx. На http «кука пускает»
    превратилось бы в «кука не доехала».
    """
    async with AsyncClient(
        app=app, base_url=SECURE_BASE_URL, follow_redirects=True
    ) as ac:
        yield ac


@pytest.fixture(scope="function")
async def db_client(
    configured: Settings, db_session: AsyncSession
) -> AsyncGenerator[AsyncClient, None]:
    """Тот же клиент, но защищённая ручка доходит до живой базы и отвечает 200."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        app=app, base_url=SECURE_BASE_URL, follow_redirects=True
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


def set_cookie_header(response: Response) -> str:
    """Сырой `Set-Cookie` ответа — атрибуты куки проверяются по нему, а не по объекту клиента."""
    header = response.headers.get("set-cookie")
    assert header is not None, "response carries no Set-Cookie"
    return header


def replace_cookie(client: AsyncClient, value: str) -> None:
    """
    Заменить сессионную куку в банке клиента, а не добавить вторую.

    `cookies.set` кладёт куку с другим доменом рядом с уже лежащей, и httpx
    отправляет обе — живая перебивает испорченную, а тест «подделанная подпись
    даёт 401» зеленеет по неправильной причине.
    """
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, value)


def cookie_value(response: Response) -> str:
    """Значение сессионной куки, вынутое из `Set-Cookie`."""
    jar: SimpleCookie = SimpleCookie()
    jar.load(set_cookie_header(response))
    return jar[SESSION_COOKIE_NAME].value


# --- обмен ключа на куку ---------------------------------------------------


async def test_valid_key_opens_a_session(client: AsyncClient) -> None:
    response = await client.post(SESSION_URL, json={"api_key": TEST_KEY})
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "expires_in_s": MAX_AGE_S}


async def test_response_body_never_carries_the_key_or_the_token(
    client: AsyncClient,
) -> None:
    response = await client.post(SESSION_URL, json={"api_key": TEST_KEY})
    body = response.text
    assert TEST_KEY not in body
    assert cookie_value(response) not in body


async def test_wrong_key_is_refused_without_a_cookie(client: AsyncClient) -> None:
    response = await client.post(SESSION_URL, json={"api_key": "not-the-key"})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


async def test_empty_key_is_rejected_by_the_schema(client: AsyncClient) -> None:
    """Пустая строка — не ключ; отказ приходит валидацией, а не сравнением."""
    response = await client.post(SESSION_URL, json={"api_key": ""})
    assert response.status_code == 422


async def test_the_key_is_never_logged(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        await client.post(SESSION_URL, json={"api_key": TEST_KEY})
        await client.post(SESSION_URL, json={"api_key": "wrong-key-value"})
    assert TEST_KEY not in caplog.text
    assert "wrong-key-value" not in caplog.text


# --- атрибуты куки ---------------------------------------------------------


async def test_cookie_is_httponly_secure_and_lax(client: AsyncClient) -> None:
    """Читается заголовок, а не объект клиента: браузеру приезжает именно он."""
    header = set_cookie_header(
        await client.post(SESSION_URL, json={"api_key": TEST_KEY})
    ).lower()
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=lax" in header
    assert f"max-age={MAX_AGE_S}" in header
    assert "path=/" in header


async def test_secure_attribute_can_be_switched_off_for_plain_http(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Внутри tailnet фронтенд отдаётся по http, и `Secure`-куку браузер не сохранит.

    Поэтому атрибут — настройка, а не константа: по умолчанию он есть,
    выключается явным `SESSION_COOKIE_SECURE=false`.
    """
    _use(monkeypatch, session_settings(SESSION_COOKIE_SECURE=False))
    header = set_cookie_header(
        await client.post(SESSION_URL, json={"api_key": TEST_KEY})
    ).lower()
    assert "httponly" in header
    assert "secure" not in header


# --- кука как пропуск ------------------------------------------------------


async def test_cookie_alone_opens_a_protected_endpoint(db_client: AsyncClient) -> None:
    """Браузер после входа ключа не видит — и ходит одной кукой."""
    await db_client.post(SESSION_URL, json={"api_key": TEST_KEY})
    assert "x-api-key" not in {name.lower() for name in db_client.headers}
    assert (await db_client.get(PROTECTED_URL)).status_code == 200


async def test_no_cookie_and_no_header_is_401(client: AsyncClient) -> None:
    response = await client.get(PROTECTED_URL)
    assert response.status_code == 401
    assert response.json()["detail"] == auth_module.UNAUTHORIZED_DETAIL


async def test_tampered_signature_is_401_not_500(client: AsyncClient) -> None:
    """Испорченный на один символ токен — отказ, а не пятисотка."""
    await client.post(SESSION_URL, json={"api_key": TEST_KEY})
    token = client.cookies[SESSION_COOKIE_NAME]
    # Портится первый символ подписи, а не последний символ токена. Подпись —
    # base64url, и у последнего символа часть битов не значащая: замена там
    # раскодируется в те же байты, токен остаётся валидным, и тест краснел раз
    # в несколько прогонов — по длине подписи, а не по коду.
    head, dot, signature = token.rpartition(".")
    assert dot and signature
    spoiled = ("a" if signature[0] != "a" else "b") + signature[1:]
    replace_cookie(client, f"{head}.{spoiled}")
    assert (await client.get(PROTECTED_URL)).status_code == 401


async def test_garbage_cookie_is_401_not_500(client: AsyncClient) -> None:
    replace_cookie(client, "not-even-a-token")
    assert (await client.get(PROTECTED_URL)).status_code == 401


async def test_cookie_signed_with_another_secret_is_refused(
    client: AsyncClient,
) -> None:
    """Токен с чужим секретом не пускает — на этом стоит «сменить SESSION_SECRET»."""
    replace_cookie(client, issue_session_token("some-other-deployment-secret"))
    assert (await client.get(PROTECTED_URL)).status_code == 401


async def test_cookie_older_than_max_age_does_not_let_in(client: AsyncClient) -> None:
    expired = issue_session_token(TEST_SECRET, issued_at=time.time() - MAX_AGE_S - 60)
    replace_cookie(client, expired)
    assert (await client.get(PROTECTED_URL)).status_code == 401


async def test_logging_in_again_issues_a_fresh_cookie(db_client: AsyncClient) -> None:
    """Протухла — заходишь заново и получаешь новую."""
    replace_cookie(
        db_client,
        issue_session_token(TEST_SECRET, issued_at=time.time() - MAX_AGE_S - 60),
    )
    assert (await db_client.get(PROTECTED_URL)).status_code == 401
    await db_client.post(SESSION_URL, json={"api_key": TEST_KEY})
    assert (await db_client.get(PROTECTED_URL)).status_code == 200


# --- вторая схема не сломана ----------------------------------------------


async def test_x_api_key_still_works_without_any_cookie(db_client: AsyncClient) -> None:
    """iOS, mac-агент и скиллы ходят как ходили — их код не правится."""
    response = await db_client.get(PROTECTED_URL, headers={"X-API-Key": TEST_KEY})
    assert response.status_code == 200


async def test_x_api_key_wins_over_a_dead_cookie(db_client: AsyncClient) -> None:
    """Дохлая кука не отбирает доступ у клиента, предъявившего ключ."""
    replace_cookie(db_client, "not-even-a-token")
    response = await db_client.get(PROTECTED_URL, headers={"X-API-Key": TEST_KEY})
    assert response.status_code == 200


async def test_wrong_header_and_valid_cookie_still_passes(
    db_client: AsyncClient,
) -> None:
    await db_client.post(SESSION_URL, json={"api_key": TEST_KEY})
    response = await db_client.get(PROTECTED_URL, headers={"X-API-Key": "wrong"})
    assert response.status_code == 200


# --- статус и выход --------------------------------------------------------


async def test_status_without_a_cookie_says_not_authenticated(
    client: AsyncClient,
) -> None:
    response = await client.get(SESSION_URL)
    assert response.status_code == 200
    assert response.json()["authenticated"] is False


async def test_status_after_login_says_authenticated(client: AsyncClient) -> None:
    await client.post(SESSION_URL, json={"api_key": TEST_KEY})
    assert (await client.get(SESSION_URL)).json()["authenticated"] is True


async def test_logout_clears_the_cookie_and_the_next_request_is_401(
    client: AsyncClient,
) -> None:
    await client.post(SESSION_URL, json={"api_key": TEST_KEY})
    logout = await client.delete(SESSION_URL)
    assert logout.status_code == 200
    assert logout.json() == {"authenticated": False, "expires_in_s": None}
    assert SESSION_COOKIE_NAME in set_cookie_header(logout)
    assert cookie_value(logout) == ""
    assert (await client.get(PROTECTED_URL)).status_code == 401


async def test_logging_out_twice_is_not_an_error(client: AsyncClient) -> None:
    await client.post(SESSION_URL, json={"api_key": TEST_KEY})
    await client.delete(SESSION_URL)
    assert (await client.delete(SESSION_URL)).status_code == 200


# --- секрет подписи --------------------------------------------------------


def test_prod_with_empty_session_secret_refuses_to_start() -> None:
    """Пустой секрет в проде роняет старт тем же способом, что пустой API_KEY."""
    with pytest.raises(PerimeterError, match="SESSION_SECRET"):
        session_settings(ENVIRONMENT="prod", SESSION_SECRET="", CORS_ORIGINS=[])


def test_prod_with_a_secret_starts() -> None:
    config = session_settings(ENVIRONMENT="prod", CORS_ORIGINS=[])
    assert config.session_signing_secret == TEST_SECRET


def test_dev_falls_back_to_the_publicly_known_secret() -> None:
    """Пустой секрет в разработке не мешает странице входа работать."""
    config = session_settings(SESSION_SECRET="")
    assert config.session_signing_secret == DEV_SESSION_SECRET


def test_session_max_age_must_be_positive() -> None:
    """Нулевой срок — не «вечная кука», а сломанная настройка; ловится при сборке."""
    with pytest.raises(ValueError):
        session_settings(SESSION_MAX_AGE_S=0)
