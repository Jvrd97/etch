# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: the JSON-plan flow both LLM features share — fence-tolerant extraction, parse into a Pydantic model, one repair pass
from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.client import LLMClient

ModelT = TypeVar("ModelT", bound=BaseModel)


class PlanError(Exception):
    """
    A model answer that could not be parsed or failed validation.

    Every feature raises its own subclass so an endpoint can still tell whose
    plan failed, while :func:`generate_with_repair` catches the common base and
    stays free of any one feature's error type.
    """


def extract_json(text: str) -> str:
    """
    Pull the JSON object out of a response that may wrap it in prose or fences.

    Raises ValueError when the text carries no object at all; callers that owe
    a typed failure to their feature go through :func:`parse_json_plan`.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence line (``` or ```json) and the closing fence.
        without_open = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = without_open.rsplit("```", 1)[0].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in the response")
    return stripped[start : end + 1]


def parse_json_plan(
    text: str, model_cls: type[ModelT], error_cls: type[PlanError]
) -> ModelT:
    """
    Parse a raw model answer into `model_cls`, form validation only.

    Every failure mode — no object, broken JSON, wrong shape — surfaces as
    `error_cls` carrying a reason the repair prompt can act on. The reason is
    built from the schema and the parser, never from the user's own words.
    """
    try:
        payload = extract_json(text)
    except ValueError as exc:
        raise error_cls(str(exc)) from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise error_cls(f"invalid JSON: {exc.msg}") from exc
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise error_cls(f"plan does not match schema: {exc.errors()}") from exc


def build_repair_prompt(base_prompt: str, previous: str, error: str) -> str:
    """Ask the model to fix its previous output given the validation error."""
    return (
        f"{base_prompt}\n\n"
        f"## Your previous answer was rejected\n{previous}\n\n"
        f"## Reason\n{error}\n\n"
        "Return a corrected JSON object that fixes the problem. JSON only."
    )


async def generate_with_repair(
    llm: LLMClient,
    base_prompt: str,
    parse_and_validate: Callable[[str], ModelT],
    build_repair: Callable[[str, str, str], str] = build_repair_prompt,
) -> ModelT:
    """
    Ask for a plan, and on a rejected answer ask exactly once more.

    One retry, not a loop: a model that failed twice on the same reason is not
    converging, and every extra round costs the user a wait plus a call. The
    second failure propagates as the feature's own `PlanError` subclass, which
    the endpoints map to 502.

    The prompt and the raw answer stay inside this function — neither is
    logged, and neither is the rejection reason, which can quote them.
    """
    raw = await llm.generate(base_prompt)
    try:
        return parse_and_validate(raw)
    except PlanError as first_error:
        repaired = await llm.generate(build_repair(base_prompt, raw, str(first_error)))
        return parse_and_validate(repaired)
