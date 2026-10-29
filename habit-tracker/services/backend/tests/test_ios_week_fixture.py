# [review:need-review] PHASE-03/243, PHASE-03/261
# summary: the answer the iOS Week tests decode (`WeekFixtures.reviewJSON`) is checked against the server's `WeekReviewResponse` on every run — same field names at every level, values the schema accepts — so a field renamed on the server turns this test red instead of leaving the app decoding a stale fixture
"""
The iOS fixture against the server schema (`#243`).

The app's Week tests decode a JSON answer kept in `WeekFixtures.swift`. It is
a copy of what `GET /week-review` returns, and a copy goes stale the day the
server renames a field: the app's tests stay green and the phone fails to
decode the real answer. This test reads that very JSON out of the Swift file
and holds it to `WeekReviewResponse`: every level has exactly the fields the
schema names, and the whole answer validates.

The Swift DTOs are held to the same schema (`#261`): an optional property whose
key the server does not send would silently decode as `nil`, so every property
of a Week DTO must be a field of its schema model.

Run inside a docker image of the backend, without the iOS sources, the tests
are skipped: there is nothing to compare. Anywhere else a missing source fails.
"""

import json
import re
import types
from pathlib import Path
from typing import Any, Union, get_args, get_origin

import pytest
from pydantic import BaseModel

from app.schemas import week_review
from app.schemas.week_review import WeekReviewResponse

REPO_HABIT_TRACKER = Path(__file__).resolve().parents[3]
FIXTURE_FILE = (
    REPO_HABIT_TRACKER
    / "ios"
    / "HabitTracker"
    / "HabitTrackerTests"
    / "WeekFixtures.swift"
)
DTO_FILE = (
    REPO_HABIT_TRACKER
    / "ios"
    / "HabitTracker"
    / "HabitTracker"
    / "API"
    / "DTOs+Week.swift"
)
DOCKER_MARKER = Path("/.dockerenv")
# Swift struct -> schema model.
DTO_MODELS = {
    "WeekWindowDTO": "WeekWindow",
    "WeekTotalsDTO": "WeekTotals",
    "WeekDeltaDTO": "WeekDelta",
    "WeekDayStatDTO": "WeekDayStat",
    "WeekRoleSliceDTO": "WeekRoleSlice",
    "WeekCategorySliceDTO": "WeekCategorySlice",
    "WeekHabitStreakDTO": "WeekHabitStreak",
    "WeekHealthMetricDTO": "WeekHealthMetric",
    "WeekReviewDTO": "WeekReviewResponse",
    "WeekNarrativeDTO": "WeekNarrativeResponse",
}
STRUCT_PATTERN = re.compile(
    r"^struct (?P<name>\w+): [^{]*\{(?P<body>.*?)^\}", re.DOTALL | re.MULTILINE
)
PROPERTY_PATTERN = re.compile(r"^    let (?P<name>\w+): ", re.MULTILINE)
SNAKE_PATTERN = re.compile(r"(?<!^)(?=[A-Z])")
RAW_JSON_PATTERN = re.compile(
    r'static let reviewJSON = """\n(?P<json>.*?)\n\s*"""', re.DOTALL
)


def _require_sources(path: Path) -> None:
    """Skip inside the backend's docker image; anywhere else a missing file is a failure."""
    if path.exists():
        return
    if DOCKER_MARKER.exists():
        pytest.skip("iOS sources are not next to the backend")
    pytest.fail(f"{path} is missing: did the iOS sources move?")


def _swift_properties() -> dict[str, set[str]]:
    """Wire keys (snake case) of every `let` in the Week DTO structs."""
    _require_sources(DTO_FILE)
    text = DTO_FILE.read_text(encoding="utf-8")
    found: dict[str, set[str]] = {}
    for match in STRUCT_PATTERN.finditer(text):
        names = PROPERTY_PATTERN.findall(match.group("body"))
        found[match.group("name")] = {SNAKE_PATTERN.sub("_", n).lower() for n in names}
    return found


def _fixture() -> dict[str, Any]:
    _require_sources(FIXTURE_FILE)
    match = RAW_JSON_PATTERN.search(FIXTURE_FILE.read_text(encoding="utf-8"))
    assert match, "WeekFixtures.reviewJSON was not found: did the fixture move?"
    parsed = json.loads(match.group("json"))
    assert isinstance(parsed, dict)
    return parsed


def _model_of(annotation: object) -> type[BaseModel] | None:
    """The pydantic model behind `Model`, `Model | None` or `list[Model]`."""
    origin = get_origin(annotation)
    if origin is None and isinstance(annotation, type):
        return annotation if issubclass(annotation, BaseModel) else None
    if origin is list or origin is Union or origin is types.UnionType:
        for argument in get_args(annotation):
            found = _model_of(argument)
            if found is not None:
                return found
    return None


def _compare(
    model: type[BaseModel], payload: dict[str, Any], path: str, problems: list[str]
) -> None:
    server = set(model.model_fields)
    fixture = set(payload)
    for name in sorted(server - fixture):
        problems.append(f"{path}.{name}: the server sends it, the fixture lacks it")
    for name in sorted(fixture - server):
        problems.append(f"{path}.{name}: the fixture has it, the server does not")
    for name, info in model.model_fields.items():
        nested = _model_of(info.annotation)
        value = payload.get(name)
        if nested is None or value is None:
            continue
        items = value if isinstance(value, list) else [value]
        for index, item in enumerate(items):
            if isinstance(item, dict):
                _compare(nested, item, f"{path}.{name}[{index}]", problems)


def test_the_ios_fixture_has_exactly_the_fields_of_the_server_schema() -> None:
    problems: list[str] = []
    _compare(WeekReviewResponse, _fixture(), "week", problems)
    assert problems == []


def test_the_ios_fixture_is_an_answer_the_server_schema_accepts() -> None:
    WeekReviewResponse.model_validate(_fixture())


def test_every_swift_dto_property_is_a_field_the_server_sends() -> None:
    """A wrong key on an optional property decodes as nil and nothing complains."""
    swift = _swift_properties()
    problems: list[str] = []
    for struct, model_name in DTO_MODELS.items():
        assert struct in swift, f"{struct} was not found in DTOs+Week.swift"
        model: type[BaseModel] = getattr(week_review, model_name)
        allowed = set(model.model_fields)
        problems += [
            f"{struct}.{name}: the server has no such field"
            for name in sorted(swift[struct] - allowed)
        ]
    assert problems == []


def test_a_swift_dto_misses_no_field_the_server_sends() -> None:
    swift = _swift_properties()
    problems: list[str] = []
    for struct, model_name in DTO_MODELS.items():
        model: type[BaseModel] = getattr(week_review, model_name)
        problems += [
            f"{struct}.{name}: the server sends it, the DTO lacks it"
            for name in sorted(set(model.model_fields) - swift[struct])
        ]
    assert problems == []
