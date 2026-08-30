"""
Смоук изоляции: живой `claude`, настоящий счёт токенов первого хода.

**Зачем живой вызов.** `--setting-sources ""` проверен на CLI 2.1.250 и в
общем списке опций описан скупо. Обновление бинарника может вернуть
50-килотокенный префикс вместе с личными хуками, и заметить это нечем: ответы
останутся правильными, изменится только цена и поведение. Юнит-тесты на сборку
аргументов ловят пропажу флага из кода, но не пропажу его смысла из CLI.

**Порог и как его пересматривать.** `MAX_FIRST_TURN_INPUT_TOKENS = 1000` при
замере ADR-0017 в 282 токена с изоляцией и 52 555 без неё (замер 2026-08-31 на
той же CLI 2.1.250 — 290 против 21 620 при снятом `--strict-mcp-config`) — запас
втрое на рост собственного системного промпта и ни одного порядка в сторону
преамбулы CLI.
Порог поднимают только вместе с намеренным ростом `ONESHOT_SYSTEM_PROMPT` и
только в этом файле: цифра, поднятая «чтобы прошло», отменяет весь смоук.
Прыжок сразу в десятки тысяч — это не порог мал, это изоляция отвалилась.

**Почему не в каждом локальном прогоне.** Нужен бинарник и подписка, поэтому
смоук идёт по признаку окружения `LLM_CLI_SMOKE=1` (`make smoke`, `make
preflight` перед выкатом), а без него пропускается с причиной. Вход только по
`CLAUDE_CODE_OAUTH_TOKEN`: явный `CLAUDE_CONFIG_DIR` отключает тот, что бинарник
нашёл бы сам, — то же предусловие деплоя, что у чата (`#119`).
"""

# [review:need-review] PHASE-03/120
# summary: live-CLI smoke — one real isolated `claude -p` call whose first-turn input_tokens + cache_creation_input_tokens must stay under the ceiling and whose answer must carry no trace of the host's personal skills and hooks; skipped with a reason when the binary, the subscription or the pre-deploy flag is absent
import asyncio
import json
import os
import shutil
from typing import Any

import pytest

from app.core.config import settings
from app.llm.cli import CLI_BINARY, ISOLATION_FLAGS, CliInsightsClient
from app.llm.prompts import ONESHOT_SYSTEM_PROMPT

# Настоящие каталоги запуска, снятые на импорте — до того, как автофикстура
# conftest подменит их временными. Смоук проверяет тот процесс, который поедет
# в прод: его каталог конфигурации хранит учётные данные подписки, а во
# временном пустом их нет. На машине разработчика оба каталога задаются
# окружением (`make smoke` подставляет личный `~/.claude` и каталог в /tmp) —
# и это самая сильная форма проверки: личная конфигурация рядом, а в префикс
# не попадает.
REAL_CONFIG_DIR = settings.CHAT_CLAUDE_CONFIG_DIR
REAL_CWD = settings.CHAT_CLI_CWD

# Порог цены первого хода: вход вместе с созданием кеша. Пересматривается по
# правилу из docstring модуля, не «чтобы прошло».
MAX_FIRST_TURN_INPUT_TOKENS = 1000

# Признак окружения, по которому смоук включается. Строкой, а не булевым
# `in os.environ`: пустая переменная в CI не должна означать «включено».
SMOKE_ENV_FLAG = "LLM_CLI_SMOKE"
SMOKE_ENV_ON = "1"

# Отказ по аутентификации отличается от сломанного флага по тексту итога:
# «Not logged in · Please run /login». Проверять заранее нечем — на macOS
# учётные данные лежат в связке ключей, а не файлом в каталоге конфигурации,
# так что подписку видно только по ответу самого CLI.
OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
NOT_LOGGED_IN_MARKERS = ("not logged in", "/login", "invalid api key", "unauthorized")

# Формат ответа смоука: json несёт usage, которого нет у text. Сам `generate`
# остаётся на text — три юзкейса разбирают голый текст.
JSON_OUTPUT_ARGS: tuple[str, ...] = ("--output-format", "json")

# Живой вызов короткий, но сетевой: минуты хватает, вечности ждать нечего.
SMOKE_TIMEOUT_SECONDS = 90.0

PROBE_PROMPT = "Ответь ровно одним словом: ГОТОВ."

# Следы личной конфигурации хоста в ответе. Список — из того самого прогона,
# в котором модель отработала личный скилл `/set` и написала об этом
# пользователю: имена скиллов, файлов настроек и источников, которых у
# изолированного процесса быть не может.
HOST_CONFIG_MARKERS = (
    "/set",
    "claude.md",
    "personal-os",
    "sessionstart",
    "statusline",
    "graphify",
    "mcp",
    "скилл",
    "skill",
)

# Однословный ответ на однословный вопрос. Всё, что длиннее, — уже не «ГОТОВ»,
# а рассказ о том, как модель собиралась работать.
MAX_PROBE_ANSWER_CHARS = 200


def smoke_skip_reason() -> str | None:
    """
    Почему смоук не поедет на этой машине, либо None.

    Две причины видны заранее — признак окружения и бинарник. Третья,
    отсутствие подписки, видна только по ответу CLI и разбирается в
    `run_isolated_probe`. Каждая называется вслух: без внятного текста пропуск
    неотличим от «тест есть, но давно ничего не проверяет».
    """
    if os.environ.get(SMOKE_ENV_FLAG) != SMOKE_ENV_ON:
        return (
            f"{SMOKE_ENV_FLAG}!={SMOKE_ENV_ON}: живой вызов CLI гоняется перед "
            "выкатом (`make smoke` / `make preflight`), а не в каждом локальном "
            "прогоне тестов"
        )
    if shutil.which(CLI_BINARY) is None:
        return f"бинарника `{CLI_BINARY}` на этой машине нет"
    return None


SMOKE_SKIP_REASON = smoke_skip_reason()


async def run_isolated_probe() -> dict[str, Any]:
    """
    Один настоящий изолированный вызов; наружу — разобранный `result`.

    Запуск собирается тем же `IsolatedCli`, что и рабочий `generate`: смоук
    обязан мерить то, чем ходят инсайты, а не свою копию командной строки.
    Отличие ровно одно — формат ответа, потому что счётчики токенов есть
    только в json.
    """
    client = CliInsightsClient(config_dir=REAL_CONFIG_DIR, cwd=REAL_CWD)
    process = await client.cli.spawn(
        system_prompt=ONESHOT_SYSTEM_PROMPT,
        output_args=JSON_OUTPUT_ARGS,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await asyncio.wait_for(
        process.communicate(PROBE_PROMPT.encode()), timeout=SMOKE_TIMEOUT_SECONDS
    )
    payload: Any = json.loads(stdout.decode()) if stdout.strip() else {}
    assert isinstance(payload, dict), "ответ `--output-format json` — не объект"

    if process.returncode != 0 or payload.get("is_error"):
        outcome = payload.get("result")
        text = outcome.lower() if isinstance(outcome, str) else ""
        if any(marker in text for marker in NOT_LOGGED_IN_MARKERS):
            pytest.skip(
                f"подписки нет: CLI отказал в аутентификации для {REAL_CONFIG_DIR}. "
                f"Залогиньтесь в этом каталоге или задайте {OAUTH_TOKEN_ENV}"
            )
        # Не текст ответа наружу, а только код: всё остальное — не наше дело
        # смоука, а вход в разбор руками.
        pytest.fail(
            f"claude вышел с кодом {process.returncode}: запуск сломан — "
            "чужой или неизвестный этой версии CLI флаг в наборе изоляции"
        )
    return payload


def first_turn_input_tokens(payload: dict[str, Any]) -> int:
    """
    Вход первого хода вместе с созданием кеша.

    Без слагаемого `cache_creation_input_tokens` проверка врёт: префикс,
    уехавший в кеш, стоит денег ровно один раз, но стоит.
    """
    usage = payload.get("usage")
    assert isinstance(usage, dict), "в ответе нет usage — мерить нечего"
    plain = usage.get("input_tokens")
    cached = usage.get("cache_creation_input_tokens")
    counted = isinstance(plain, int) or isinstance(cached, int)
    assert counted, "usage без счётчиков: формат ответа CLI изменился, смоук слеп"
    return (plain if isinstance(plain, int) else 0) + (
        cached if isinstance(cached, int) else 0
    )


class TestSmokeMeasuresTheRealCall:
    """Смоук меряет тот запуск, которым ходят инсайты, а не свою копию."""

    def test_probe_runs_the_full_isolation_set(self) -> None:
        """
        Пропажа любого флага из `ISOLATION_ARGS` меняет то, что запускает смоук.

        Оффлайн-половина проверки «смоук проверяет изоляцию, а не факт
        запуска»: живая половина — порог токенов ниже.
        """
        argv = CliInsightsClient().cli.build_argv(
            system_prompt=ONESHOT_SYSTEM_PROMPT, output_args=JSON_OUTPUT_ARGS
        )

        for flag, value in ISOLATION_FLAGS:
            assert flag in argv
            if value is not None:
                assert argv[argv.index(flag) + 1] == value


@pytest.mark.skipif(SMOKE_SKIP_REASON is not None, reason=str(SMOKE_SKIP_REASON))
class TestLiveCliIsolation:
    """Живой вызов: сколько он стоит и чем пахнет ответ."""

    async def test_first_turn_stays_under_the_price_ceiling(self) -> None:
        """
        Первый ход дешевле порога — значит преамбула CLI и личные настройки не приехали.

        Это и есть проверка, падающая при снятом `--setting-sources ""`:
        без него на машине с личной конфигурацией префикс — десятки тысяч
        токенов вместо сотен.
        """
        payload = await run_isolated_probe()

        tokens = first_turn_input_tokens(payload)
        assert tokens < MAX_FIRST_TURN_INPUT_TOKENS, (
            f"первый ход стоит {tokens} входных токенов при пороге "
            f"{MAX_FIRST_TURN_INPUT_TOKENS}: изоляция отвалилась или "
            "системный промпт вырос — см. docstring модуля"
        )

    async def test_answer_carries_no_trace_of_host_configuration(self) -> None:
        """Ни личных скиллов, ни хуков, ни рассказа о них — только ответ по существу."""
        payload = await run_isolated_probe()

        answer = payload.get("result")
        assert isinstance(answer, str) and answer.strip(), "пустой ответ CLI"
        lowered = answer.lower()
        for marker in HOST_CONFIG_MARKERS:
            trace = f"в ответе след личной конфигурации хоста: {marker!r}"
            assert marker not in lowered, trace
        assert len(answer.strip()) < MAX_PROBE_ANSWER_CHARS
