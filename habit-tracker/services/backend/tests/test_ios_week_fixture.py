# [review:need-review] PHASE-03/243
# summary: the answer the iOS Week tests decode (`WeekFixtures.reviewJSON`) is checked against the server's `WeekReviewResponse` on every run — same field names at every level, values the schema accepts — so a field renamed on the server turns this test red instead of leaving the app decoding a stale fixture
"""
The iOS fixture against the server schema (`#243`).

The app's Week tests decode a JSON answer kept in `WeekFixtures.swift`. It is
a copy of what `GET /week-review` returns, and a copy goes stale the day the
server renames a field: the app's tests stay green and the phone fails to
decode the real answer. This test reads that very JSON out of the Swift file
and holds it to `WeekReviewResponse`: every level has exactly the fields the
schema names, and the whole answer validates.

Run from the repository without the iOS sources (a docker image of the
backend), the test is skipped: there is nothing to compare.
"""

import json
import re
import types
from pathlib import Path
from typing import Any, Union, get_args, get_origin

import pytest
from pydantic import BaseModel

from app.schemas.week_review import WeekReviewResponse

REPO_HABIT_TRACKER = Path(__file__).resolve().parents[3]
FIXTURE_FILE = (
    REPO_HABIT_TRACKER
    / "ios"
    / "HabitTracker"
    / "HabitTrackerTests"
    / "WeekFixtures.swift"
)
RAW_JSON_PATTERN = re.compile(
    r'static let reviewJSON = """\n(?P<json>.*?)\n\s*"""', re.DOTALL
)


def _fixture() -> dict[str, Any]:
    if not FIXTURE_FILE.exists():
        pytest.skip("iOS sources are not next to the backend")
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
