# [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
# summary: shared interpretation of EAV text values (boolean truthiness, number parsing) and the one way a number is rendered back into that column
import logging

logger = logging.getLogger(__name__)

# String values treated as "true" for boolean fields (EAV stores text)
BOOLEAN_TRUE_VALUES = frozenset({"true", "1", "yes"})


def is_true_value(value: str | None) -> bool:
    """Whether a stored boolean field value means true."""
    if value is None:
        return False
    return value.strip().lower() in BOOLEAN_TRUE_VALUES


def parse_number(
    value: str | None, *, field_id: int | None = None, entry_id: int | None = None
) -> float | None:
    """
    Parse a stored number field value, or None when it carries no number.

    A missing or blank value is silently None: the entry form submits an empty
    string for every field the user did not touch, so blanks are expected and
    must not produce log noise. Text that is present but unparsable is a real
    data problem and is logged as a warning — the value itself is never logged
    (PII-safe), only the ids needed to locate the row.
    """
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        logger.warning(
            "non-numeric value in number field",
            extra={"field_id": field_id, "entry_id": entry_id},
        )
        return None


def format_number(value: float) -> str:
    """
    Render a number back into the EAV text column the way the entry form would.

    A whole number loses its decimal tail, so a day-plan "30", a table
    aggregate of 30.0 and a hand-typed "30" are one and the same string and no
    reader can tell them apart. Fractions go through `str`, not `repr`: on a
    float those agree in modern Python, and `str` is the one that stays a
    rendering rather than a debug representation if the input type ever widens.

    The single home of the rule: every writer of a numeric value calls this, so
    "how a number looks in the database" is decided in one place.
    """
    if value.is_integer():
        return str(int(value))
    return str(value)
