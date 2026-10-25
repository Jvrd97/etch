# [review:need-review] PHASE-03/105
# summary: six stable error classes for a source run (auth_expired, needs_login, rate_limited, network, remote_error, not_implemented) and the two folds that feed them — a refusal code to its class, an unexpected exception to a code made of its type name alone
"""
Классы ошибок прогона источника.

Экран источников отвечает на вопрос «что с ним делать», а не «что сказал
провайдер», поэтому детальных кодов отказа (`http_401`, `no_workspace`) ему мало:
из них складывается шесть классов, и каждый несёт свой следующий шаг.

- `needs_login` — войти: ключа или файла сессии нет, либо ключ не читается;
- `auth_expired` — войти заново: провайдер отозвал доступ (401, 403);
- `rate_limited` — подождать: провайдер просит не торопиться (429);
- `network` — ничего: источник недоступен, следующий прогон повторит сам;
- `remote_error` — смотреть логи: провайдер или наш разбор ответа сломался;
- `not_implemented` — ничего: у заготовки адаптера ещё нет.

**В `last_error_code` едет код, а не сообщение.** Текст исключения — первое место,
куда утекает тема письма, адрес и имя чата (ADR-0016, D2), поэтому неизвестное
исключение превращается в `error_<ИмяТипа>`: тип разработчик назвал сам, слова из
сообщения туда попасть не могут.
"""

from __future__ import annotations

import httpx

__all__ = [
    "ERROR_AUTH_EXPIRED",
    "ERROR_CLASSES",
    "ERROR_CODE_MAX_CHARS",
    "ERROR_NEEDS_LOGIN",
    "ERROR_NETWORK",
    "ERROR_NOT_IMPLEMENTED",
    "ERROR_RATE_LIMITED",
    "ERROR_REMOTE",
    "class_of_code",
    "code_of_exception",
    "describe",
]

ERROR_AUTH_EXPIRED = "auth_expired"
ERROR_NEEDS_LOGIN = "needs_login"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_NETWORK = "network"
ERROR_REMOTE = "remote_error"
ERROR_NOT_IMPLEMENTED = "not_implemented"
ERROR_CLASSES: tuple[str, ...] = (
    ERROR_AUTH_EXPIRED,
    ERROR_NEEDS_LOGIN,
    ERROR_RATE_LIMITED,
    ERROR_NETWORK,
    ERROR_REMOTE,
    ERROR_NOT_IMPLEMENTED,
)

# Ширина колонки `signal_sources.last_error_code`.
ERROR_CODE_MAX_CHARS = 64

# Коды, которыми отказывают сами адаптеры и прогон. Один код — один класс.
CODE_NO_CREDENTIALS = "no_credentials"
CODE_NO_WORKSPACE = "no_workspace"
CODE_SECRET_UNREADABLE = "secret_unreadable"
CODE_TRANSPORT_FAILED = "transport_failed"
CODE_NO_ADAPTER = "no_adapter"
CODE_SOURCE_DISABLED = "source_disabled"
CODE_HTTP_PREFIX = "http_"
CODE_EXCEPTION_PREFIX = "error_"

_CLASS_OF_CODE: dict[str, str] = {
    CODE_NO_CREDENTIALS: ERROR_NEEDS_LOGIN,
    CODE_NO_WORKSPACE: ERROR_NEEDS_LOGIN,
    CODE_SECRET_UNREADABLE: ERROR_NEEDS_LOGIN,
    CODE_TRANSPORT_FAILED: ERROR_NETWORK,
    CODE_NO_ADAPTER: ERROR_NOT_IMPLEMENTED,
}

_HTTP_AUTH_STATUSES = frozenset({401, 403})
_HTTP_RATE_LIMIT_STATUS = 429


def class_of_code(code: str | None) -> str | None:
    """
    Класс отказа по его коду; `None` — это не ошибка.

    «Выключен» (`source_disabled`) — решение человека, а не поломка. Код, которого
    здесь не знают, — `remote_error`: забытая запись в таблице должна давать
    «сломалось, смотри логи», а не пустое место на экране.
    """
    if code is None or code == CODE_SOURCE_DISABLED:
        return None
    if code in _CLASS_OF_CODE:
        return _CLASS_OF_CODE[code]
    if code.startswith(CODE_HTTP_PREFIX):
        status = code.removeprefix(CODE_HTTP_PREFIX)
        if status.isdigit() and int(status) in _HTTP_AUTH_STATUSES:
            return ERROR_AUTH_EXPIRED
        if status.isdigit() and int(status) == _HTTP_RATE_LIMIT_STATUS:
            return ERROR_RATE_LIMITED
    return ERROR_REMOTE


def code_of_exception(error: BaseException) -> str:
    """
    Код отказа для исключения, которого адаптер не предусмотрел.

    Тексту исключения здесь не доверяют вовсе: в код идёт только имя типа.
    Сетевой сбой и отсутствующий файл сессии узнаются по типу и получают коды,
    которые экран уже умеет читать.
    """
    if isinstance(error, httpx.HTTPStatusError):
        return f"{CODE_HTTP_PREFIX}{error.response.status_code}"
    if isinstance(error, httpx.TransportError):
        return CODE_TRANSPORT_FAILED
    if isinstance(error, FileNotFoundError):
        return CODE_NO_CREDENTIALS
    name = type(error).__name__
    return f"{CODE_EXCEPTION_PREFIX}{name}"[:ERROR_CODE_MAX_CHARS]


_DESCRIPTIONS: dict[str, str] = {
    ERROR_NEEDS_LOGIN: "Нужен вход: учётных данных нет или их не удалось прочитать.",
    ERROR_AUTH_EXPIRED: "Провайдер отозвал доступ. Войдите заново.",
    ERROR_RATE_LIMITED: "Провайдер просит подождать. Повторится само.",
    ERROR_NETWORK: "Источник недоступен.",
    ERROR_REMOTE: "Источник отказал или ответил не так, как ждали.",
    ERROR_NOT_IMPLEMENTED: "У источника нет адаптера.",
}


def describe(error_class: str | None) -> str:
    """
    Готовая фраза про класс — единственный текст, который уходит наружу из
    неожиданного исключения. Она написана здесь, а не собрана из сообщения.
    """
    return _DESCRIPTIONS.get(error_class or "", _DESCRIPTIONS[ERROR_REMOTE])
