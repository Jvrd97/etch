"""
Класс W2 закрыт типами, а не инструкцией.

Права чата разведены на три класса: R — сервер читает сам; W1 — добавление без
потерь (метрика, отметка, текст дня); W2 — снять отметку, переписать, удалить,
переименовать. Этот файл проверяет, что W2 **невыразим**: в JSON Schema
`ChatPlan` нет ни слова, которым его можно было бы сказать.

Проверяется схема, а не промпт. Промпт — это просьба, и модель вправе ответить
мимо неё; схема — это граница, и мимо неё ответить нельзя. Тест устроен так,
чтобы упасть, если операцию класса W2 в план когда-нибудь добавят: он смотрит на
полный набор операций, а не ищет конкретные запрещённые слова.
"""

# [review:need-review] PHASE-03/115
# summary: the JSON Schema of ChatPlan is asserted to expose exactly three operations — log_metric, check, write_journal — with no untick, delete or rename anywhere in it, and no field on `check` able to carry a false

from typing import Any

from app.schemas.chat import ChatPlan

# Ровно то, что чат вправе предложить. Список полный: тест падает и на лишней
# операции, и на пропавшей — вторая означала бы, что плашка тихо перестала
# что-то уметь.
ALLOWED_OPERATIONS = {"log_metric", "check", "write_journal"}

# Слова, которыми класс W2 мог бы себя выдать, если бы кто-то добавил операцию
# не через `op`. Второй рубеж после проверки полного набора операций.
#
# Ищутся они только в **именах** — ключах свойств и значениях `const`/`enum`, —
# а не в описаниях. Docstring `CheckOp` объясняет, почему снятия отметки нет, и
# слово «untick» в нём стоит ровно затем, чтобы следующий читатель не завёл
# такую операцию заново. Падать на объяснении запрета значило бы требовать, чтобы
# запрет было запрещено объяснять.
FORBIDDEN_WORDS = (
    "uncheck",
    "untick",
    "delete",
    "remove",
    "rename",
    "replace",
    "overwrite",
    "clear",
)


def collect_operation_literals(schema: dict[str, Any]) -> set[str]:
    """
    Все значения поля `op`, которые схема вообще допускает.

    Обход по всему документу, а не по известным местам: операция, добавленная в
    новое ответвление `$defs`, обязана попасть в этот набор так же, как
    добавленная в существующее.
    """
    found: set[str] = set()

    def walk(node: object, key: str | None = None) -> None:
        if isinstance(node, dict):
            if key == "op" and "const" in node:
                found.add(str(node["const"]))
            if key == "op" and "enum" in node:
                found.update(str(one) for one in node["enum"])
            for name, value in node.items():
                walk(value, name)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)

    walk(schema)
    return found


def test_the_plan_offers_exactly_three_operations() -> None:
    """
    Ни снятия отметки, ни удаления, ни переименования в объединении нет.

    Этот тест — и есть заявленная защита. Добавь кто-нибудь `uncheck_op` в
    `ChatPlan`, и он упадёт здесь, а не на ревью и не в проде.
    """
    schema = ChatPlan.model_json_schema()
    assert collect_operation_literals(schema) == ALLOWED_OPERATIONS


def collect_names(schema: dict[str, Any]) -> set[str]:
    """Каждое имя схемы: ключи свойств и все значения `const`/`enum`."""
    names: set[str] = set()

    def walk(node: object, key: str | None = None) -> None:
        if isinstance(node, dict):
            if key == "properties":
                names.update(str(one) for one in node)
            for name, value in node.items():
                if name == "const":
                    names.add(str(value))
                elif name == "enum" and isinstance(value, list):
                    names.update(str(one) for one in value)
                walk(value, name)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)

    walk(schema)
    return names


def test_no_name_in_the_schema_can_say_a_destructive_operation() -> None:
    """Второй рубеж: операция W2 мимо поля `op` тоже не проходит."""
    names = {one.lower() for one in collect_names(ChatPlan.model_json_schema())}
    for word in FORBIDDEN_WORDS:
        offenders = [name for name in names if word in name]
        assert not offenders, f"схема плана чата выговаривает «{word}»: {offenders}"


def test_a_tick_cannot_carry_a_false() -> None:
    """
    У операции `check` нет поля со значением — и это тоже граница, а не стиль.

    `PUT /entries/checklist` принимает карту дня целиком, поэтому операция,
    умеющая сказать `false`, снимала бы галочку, поставленную утром, из пересказа,
    который про неё просто не упомянул. Молчание в разговоре значит «не сказал»,
    никогда «не сделал».
    """
    schema = ChatPlan.model_json_schema()
    check = schema["$defs"]["CheckOp"]
    assert "value" not in check["properties"]
    assert check.get("additionalProperties") is False


def test_the_plan_itself_refuses_unknown_keys() -> None:
    """Ключ, которого в схеме нет, — отказ, а не молчаливое игнорирование."""
    schema = ChatPlan.model_json_schema()
    assert schema.get("additionalProperties") is False
