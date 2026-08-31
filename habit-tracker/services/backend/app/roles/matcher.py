# [review:need-review] PHASE-03/134
# summary: the rule resolver — a pure function from (sample, rules) to the winning rule; smaller `priority` wins, an equal priority is broken by the smaller `id`, and no match at all is `None`, which the caller turns into `unassigned` rather than into NULL
"""
Which role a sample belongs to.

Deliberately free of the database and of the models: the whole hard part of the
markup is a total order over the rules that matched, and that order deserves to
be testable with two literals rather than a fixture. `app.crud.role` supplies
the rows, this module decides.

**The order.** Every active rule of the sample's source is tried; the ones that
match are ordered by `(priority, id)` and the first wins. Smaller `priority` is
stronger, as the ADR specifies. The tie-break on `id` is the part worth naming:
two rules with the same priority would otherwise be separated by whatever order
the database felt like returning them in, and the same sample would drift
between roles between two runs. Older wins — the rule that was already there
keeps its meaning when a new one of equal weight arrives.

**No match is not an error.** The answer is `None`, and the caller charges the
minutes to `unassigned`. A row that could not be attributed is a fact worth
seeing; a NULL is a fact nobody sees.

Nothing here is called by the manual entry path — a person picks the role
themselves. The first caller is the interval markup of `#135`; the resolver is
written and tested now because the two tickets share the rules table and the
conflict case is what makes the table worth having.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from app.models.role import (
    MATCHER_BUNDLE_ID,
    MATCHER_CLICKUP_LIST,
    MATCHER_CLICKUP_TAG,
    MATCHER_COMMIT_PREFIX,
    MATCHER_PLAN_SECTION,
    MATCHER_REPO_PATH_GLOB,
    MATCHER_WINDOW_TITLE_REGEX,
)

logger = logging.getLogger(__name__)

__all__ = ["MatchSample", "RoleMatch", "RuleCandidate", "resolve_rule"]


@dataclass(frozen=True)
class MatchSample:
    """
    The thing being attributed: one source and whatever that source knows.

    A single shape for all five sources rather than five: a rule is chosen by
    `source` first, so the fields another source would have filled are simply
    absent, and the caller does not have to know which subset its source owns.

    `window_title` is a sensitive string by ADR-0020 B5 — a document name, a
    correspondent, potentially a patient identifier. It is matched against and
    never logged, here or anywhere below.
    """

    source: str
    bundle_id: str | None = None
    window_title: str | None = None
    repo_path: str | None = None
    commit_message: str | None = None
    clickup_list: str | None = None
    clickup_tags: tuple[str, ...] = field(default_factory=tuple)
    plan_section: str | None = None


@dataclass(frozen=True)
class RuleCandidate:
    """One rule as the resolver needs it: no session, no ORM instance."""

    id: int
    role_id: int
    source: str
    matcher_kind: str
    pattern: str
    priority: int


@dataclass(frozen=True)
class RoleMatch:
    """The winning rule and the role it charges the sample to."""

    role_id: int
    rule_id: int


def _matches(rule: RuleCandidate, sample: MatchSample) -> bool:
    """
    Whether one rule fires on one sample.

    A matcher kind the resolver does not know returns False rather than raising:
    the vocabulary is a string column on purpose, so a row written by a future
    ticket must not take the markup of every other row down with it. It is
    logged, because a rule that never fires and never says so is worse than one
    that is refused.
    """
    pattern = rule.pattern
    if rule.matcher_kind == MATCHER_BUNDLE_ID:
        return sample.bundle_id == pattern
    if rule.matcher_kind == MATCHER_WINDOW_TITLE_REGEX:
        return sample.window_title is not None and _search(rule, sample.window_title)
    if rule.matcher_kind == MATCHER_REPO_PATH_GLOB:
        return sample.repo_path is not None and fnmatchcase(sample.repo_path, pattern)
    if rule.matcher_kind == MATCHER_COMMIT_PREFIX:
        return sample.commit_message is not None and sample.commit_message.startswith(
            pattern
        )
    if rule.matcher_kind == MATCHER_CLICKUP_LIST:
        return sample.clickup_list == pattern
    if rule.matcher_kind == MATCHER_CLICKUP_TAG:
        return pattern in sample.clickup_tags
    if rule.matcher_kind == MATCHER_PLAN_SECTION:
        return sample.plan_section == pattern
    logger.warning(
        "role rule %s has an unknown matcher_kind %r and matches nothing",
        rule.id,
        rule.matcher_kind,
    )
    return False


def _search(rule: RuleCandidate, title: str) -> bool:
    """
    `window_title_regex`, with a broken pattern treated as a rule that misses.

    The API compiles a pattern before storing it, so a `re.error` here means a
    row that got in another way — `psql`, an import, a restored dump. Taking the
    whole markup down over one bad row would be the wrong trade; the rule is
    reported by id and skipped. The title itself never reaches the log.
    """
    try:
        return re.search(rule.pattern, title) is not None
    except re.error as error:
        logger.warning(
            "role rule %s has an invalid window_title_regex and matches nothing: %s",
            rule.id,
            error,
        )
        return False


def resolve_rule(sample: MatchSample, rules: list[RuleCandidate]) -> RoleMatch | None:
    """
    The rule that wins on this sample, or `None` when none of them do.

    `rules` may hold rules of every source; the ones from another source are
    skipped here, so a caller can load the table once and attribute a whole day
    of mixed samples against the same list.
    """
    winners = [
        rule
        for rule in rules
        if rule.source == sample.source and _matches(rule, sample)
    ]
    if not winners:
        return None
    best = min(winners, key=lambda rule: (rule.priority, rule.id))
    return RoleMatch(role_id=best.role_id, rule_id=best.id)
