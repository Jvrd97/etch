# [review:need-review] PHASE-03/93
# summary: `in_list()` — the text of a vocabulary CHECK built from the tuple the code already reads, so a model, a migration and a service cannot spell the same four words three ways
"""
The text of a vocabulary CHECK, spelled from the tuple the code reads.

Every table here that keeps a word out of a fixed set — `day_summary.verdict`,
`day_summary.source`, `milestone.status`, `quarter_goal.status` — needs the same
sentence in two places: the model, so `create_all` builds the constraint for the
tests, and the migration, so a real database gets it. Written twice by hand they
drift, and the drift is invisible until a fifth spelling reaches production and
is refused by one of the two.
"""

from __future__ import annotations

__all__ = ["in_list"]


def in_list(column: str, values: tuple[str, ...]) -> str:
    """`verdict IN ('won', 'lost')` — the CHECK body for a vocabulary column."""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"
