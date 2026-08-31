# [review:need-review] PHASE-03/98
# summary: the credential vault — secrets are stored encrypted in the row of their source instead of being named by an env variable, the key is derived from SESSION_SECRET so no second secret has to be deployed, and the plaintext never leaves this module upwards
"""
Учётные данные источников: в базе, зашифрованными.

**Почему не переменная окружения.** Первый срез (`#97`) назвал секрет именем
env-переменной, и это стоило человеку доступа к машине: подключить второй
воркспейс ClickUp значило зайти на VPS, править `.env`, пересобирать контейнер.
Источник обязан становиться рабочим из интерфейса — иначе «добавить рабочий
ClickUp» это задача на выкат, а не действие.

**Цена названа прямо.** Секрет в базе попадает в дамп: `deploy/backup.sh` кладёт
дампы файлом на диск VPS. Поэтому он лежит зашифрованным, а ключ живёт в
окружении процесса и в дамп не попадает — украденный дамп сам по себе
бесполезен. Против того, у кого есть и дамп, и машина, это не защищает, и
притворяться иначе нельзя: у такого человека есть и `.env`.

**Ключ выводится из `SESSION_SECRET`**, а не заводится вторым. Второй секрет
означает второе место, где он может быть пуст в проде, и второй способ потерять
данные при ротации. Вывод — HKDF с фиксированной солью контура: тот же
`SESSION_SECRET` даёт тот же ключ, а знание ключа сессий не даёт знания ключа
хранилища напрямую.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

__all__ = ["SecretUnreadable", "decrypt_secret", "encrypt_secret"]

# Соль вывода ключа. Константа, а не случайность: ключ обязан получаться тем же
# самым при каждом старте процесса, иначе расшифровать вчерашнюю строку нечем.
HKDF_SALT = b"habit-tracker/inbox-credentials/v1"
HKDF_INFO = b"fernet-key"


class SecretUnreadable(Exception):
    """
    Секрет есть, а прочитать его нечем.

    Так выглядит смена `SESSION_SECRET` при живых строках: ключ другой, и
    расшифровка не проходит. Это состояние источника — «нужен повторный ввод», —
    а не поломка приложения, и подниматься наружу оно должно именно так.
    """


def _key() -> bytes:
    """Ключ Fernet из секрета приложения."""
    material = settings.SESSION_SECRET.encode("utf-8")
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=HKDF_SALT,
        info=HKDF_INFO,
    ).derive(material)
    return base64.urlsafe_b64encode(derived)


def encrypt_secret(plaintext: str) -> str:
    """Зашифровать секрет для хранения в строке источника."""
    return Fernet(_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """
    Прочитать секрет.

    Открытый текст не возвращается никуда, кроме адаптера, который сейчас же
    кладёт его в заголовок запроса: ни в лог, ни в DTO, ни в текст исключения он
    не попадает — исключение здесь несёт только факт, что прочитать не вышло.
    """
    try:
        return Fernet(_key()).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as error:
        raise SecretUnreadable(
            "Секрет не читается этим ключом. Обычно это смена SESSION_SECRET: "
            "введите учётные данные источника заново."
        ) from error
