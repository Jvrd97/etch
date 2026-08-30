# [review:need-review] PHASE-03/109
# summary: signed browser session — mint/verify an itsdangerous token and write the HttpOnly cookie that carries it
"""
Сессия веб-клиента: подписанный токен вместо ключа в браузере.

Браузер — единственный из четырёх клиентов, которому негде хранить `API_KEY`:
Next.js собирается статически, и ключ в бандле уезжает в каждую вкладку, кеш и
скриншот devtools. Поэтому браузер один раз меняет ключ на куку и дальше ключа
не видит (`app/api/auth.py`). Остальные клиенты — iOS, mac-агент, скиллы —
ходят по `X-API-Key`, как ходили.

Сессия не хранится нигде: токен подписан `SESSION_SECRET` и несёт только время
выпуска. Отсюда два следствия, названных прямо, а не спрятанных:

* отозвать одну сессию нельзя — смена `SESSION_SECRET` гасит разом все;
* владельца в токене нет, потому что пользователь один (ADR-0003).

Кука ставится `HttpOnly` (JavaScript её не прочитает), `SameSite=Lax` (запрос
с чужой страницы куку не приложит) и `Secure`, если сервер отдаёт HTTPS.
"""

from typing import Literal

from itsdangerous import BadSignature, TimestampSigner
from starlette.responses import Response

# Имя куки. Одно на весь проект: его знают `app/core/auth.py` (читает),
# `app/api/auth.py` (ставит и стирает) и тесты.
SESSION_COOKIE_NAME = "habit_session"

# Соль подписи. Отделяет сессионные токены от любого другого применения того же
# секрета: токен, подписанный с другой солью, здесь не пройдёт.
SESSION_SALT = "habit-tracker.web-session"

# Полезная нагрузка токена. Пользователь один, поэтому в подписи нет ничего,
# кроме константы и метки времени; `#109` Out of Scope прямо говорит, что
# второй пользователь и `owner_id` сюда не приезжают.
SESSION_SUBJECT = "web"

# Путь куки. Явный, потому что стирание обязано указать тот же путь, что и
# установка, иначе браузер удалит не ту куку (или не удалит ничего).
SESSION_COOKIE_PATH = "/"

# Политика межсайтовой отправки. `lax` — CSRF с чужой страницы не срабатывает,
# а переход по ссылке из мессенджера сессию не теряет.
SESSION_COOKIE_SAMESITE: Literal["lax"] = "lax"


class _SessionSigner(TimestampSigner):
    """
    Подписчик с фиксируемыми часами.

    `issued_at` существует ради одного теста — «кука старше `SESSION_MAX_AGE_S`
    не пускает». Без него такой тест либо спит полчаса, либо патчит `time.time`
    глобально. Продовый код `issued_at` не передаёт никогда.
    """

    def __init__(self, secret: str, *, issued_at: float | None = None) -> None:
        super().__init__(secret, salt=SESSION_SALT)
        self._issued_at = issued_at

    def get_timestamp(self) -> int:
        if self._issued_at is None:
            return super().get_timestamp()
        return int(self._issued_at)


def issue_session_token(secret: str, *, issued_at: float | None = None) -> str:
    """Выпустить подписанный сессионный токен. `issued_at` — только для тестов."""
    return (
        _SessionSigner(secret, issued_at=issued_at)
        .sign(SESSION_SUBJECT)
        .decode("ascii")
    )


def session_token_is_valid(token: str, *, secret: str, max_age_s: int) -> bool:
    """
    Жив ли токен: подпись сходится и возраст не превышает `max_age_s`.

    Возвращает `False` на любую негодную строку, а не поднимает исключение:
    значение куки приходит от клиента, и испорченный на один символ токен
    обязан дать 401, а не 500. `SignatureExpired` — подкласс `BadSignature`,
    поэтому истёкший и подделанный ловятся одной веткой; различать их в ответе
    незачем — оба означают «войди заново».
    """
    try:
        subject = _SessionSigner(secret).unsign(token, max_age=max_age_s)
    except BadSignature:
        return False
    return subject == SESSION_SUBJECT.encode("ascii")


def set_session_cookie(
    response: Response, token: str, *, max_age_s: int, secure: bool
) -> None:
    """Положить токен в `HttpOnly`-куку с явным сроком жизни."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age_s,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    """
    Стереть куку — это весь выход.

    Атрибуты повторяют установку: браузер сопоставляет куку по имени, домену и
    пути, и `delete_cookie` без того же `path` оставил бы старую жить.
    """
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=SESSION_COOKIE_SAMESITE,
    )
