# [review:need-review] PHASE-03/134
# summary: pure tests of the rule resolver — a deliberate conflict of two rules resolves to the smaller priority, an equal priority resolves to the smaller id (deterministically, in both input orders), a sample nothing matched returns None so the caller can charge it to `unassigned`, and a rule of another source or a broken regex never fires
"""
Tests of `app.roles.matcher`.

No database: the hard part of the markup is the total order over the rules that
matched, and it deserves to be checked with literals. The database half — the
fallback to `unassigned` — is exercised in `test_roles.py`.
"""

from app.models.role import (
    MATCHER_BUNDLE_ID,
    MATCHER_CLICKUP_TAG,
    MATCHER_COMMIT_PREFIX,
    MATCHER_REPO_PATH_GLOB,
    MATCHER_WINDOW_TITLE_REGEX,
    SOURCE_APP_USAGE,
    SOURCE_CLICKUP,
    SOURCE_GIT,
)
from app.roles.matcher import MatchSample, RuleCandidate, resolve_rule

ROLE_CTO = 1
ROLE_ARCHITECT = 2
ROLE_TECHLEAD = 3


def rule(
    rule_id: int,
    role_id: int,
    *,
    source: str = SOURCE_APP_USAGE,
    matcher_kind: str = MATCHER_WINDOW_TITLE_REGEX,
    pattern: str = ".",
    priority: int = 100,
) -> RuleCandidate:
    return RuleCandidate(
        id=rule_id,
        role_id=role_id,
        source=source,
        matcher_kind=matcher_kind,
        pattern=pattern,
        priority=priority,
    )


# One window that honestly looks like two roles at once: an ADR being written in
# an editor. That is the conflict the priorities exist for.
ADR_WINDOW = MatchSample(
    source=SOURCE_APP_USAGE,
    bundle_id="com.microsoft.VSCode",
    window_title="ADR-0020-healthkit-and-cto-metrics.md — habit_tracker_ai",
)


class TestConflict:
    def test_smaller_priority_wins(self) -> None:
        """Two rules match the same window; the stronger one names the role."""
        rules = [
            rule(
                1,
                ROLE_TECHLEAD,
                matcher_kind=MATCHER_BUNDLE_ID,
                pattern="com.microsoft.VSCode",
                priority=100,
            ),
            rule(2, ROLE_ARCHITECT, pattern=r"^ADR-\d+", priority=10),
        ]
        match = resolve_rule(ADR_WINDOW, rules)
        assert match is not None
        assert match.role_id == ROLE_ARCHITECT
        assert match.rule_id == 2

    def test_order_of_the_input_does_not_decide(self) -> None:
        """The same rules in the other order give the same answer."""
        rules = [
            rule(2, ROLE_ARCHITECT, pattern=r"^ADR-\d+", priority=10),
            rule(
                1,
                ROLE_TECHLEAD,
                matcher_kind=MATCHER_BUNDLE_ID,
                pattern="com.microsoft.VSCode",
                priority=100,
            ),
        ]
        match = resolve_rule(ADR_WINDOW, rules)
        assert match is not None
        assert match.role_id == ROLE_ARCHITECT

    def test_equal_priority_is_broken_by_the_smaller_id(self) -> None:
        """
        Equal weight is not a coin toss.

        The rule that was already there keeps its meaning when one of equal
        weight arrives, and the answer does not depend on the order the rows
        came back in.
        """
        older = rule(7, ROLE_ARCHITECT, pattern=r"^ADR-\d+", priority=50)
        newer = rule(9, ROLE_CTO, pattern="cto", priority=50)
        for rules in ([older, newer], [newer, older]):
            match = resolve_rule(ADR_WINDOW, rules)
            assert match is not None
            assert match.role_id == ROLE_ARCHITECT
            assert match.rule_id == 7


class TestNoMatch:
    def test_nothing_matched_is_none(self) -> None:
        """No rule fired: the answer is None, and the caller says `unassigned`."""
        rules = [rule(1, ROLE_CTO, pattern="^бюджет")]
        assert resolve_rule(ADR_WINDOW, rules) is None

    def test_empty_rule_set_is_none(self) -> None:
        assert resolve_rule(ADR_WINDOW, []) is None

    def test_a_rule_of_another_source_never_fires(self) -> None:
        """
        A commit-prefix rule does not decide what a window in focus means.

        The resolver is handed the whole table so a day of mixed samples can be
        attributed against one read; the source is what keeps them apart.
        """
        rules = [
            rule(
                1,
                ROLE_CTO,
                source=SOURCE_GIT,
                matcher_kind=MATCHER_COMMIT_PREFIX,
                pattern="ADR",
                priority=1,
            )
        ]
        assert resolve_rule(ADR_WINDOW, rules) is None

    def test_a_field_the_sample_does_not_carry_never_fires(self) -> None:
        """A window with no repo path is not matched by a repo glob."""
        rules = [
            rule(
                1,
                ROLE_TECHLEAD,
                matcher_kind=MATCHER_REPO_PATH_GLOB,
                pattern="*/habit_tracker_ai/*",
            )
        ]
        assert resolve_rule(ADR_WINDOW, rules) is None

    def test_a_broken_regex_misses_instead_of_raising(self) -> None:
        """
        A pattern that cannot compile takes down that rule, not the markup.

        The API refuses such a pattern on the way in; a row that got there some
        other way — `psql`, a restored dump — must not stop every other rule
        from firing.
        """
        rules = [
            rule(1, ROLE_CTO, pattern="([unclosed", priority=1),
            rule(2, ROLE_ARCHITECT, pattern=r"^ADR-\d+", priority=50),
        ]
        match = resolve_rule(ADR_WINDOW, rules)
        assert match is not None
        assert match.role_id == ROLE_ARCHITECT

    def test_an_unknown_matcher_kind_misses_instead_of_raising(self) -> None:
        """The vocabulary is a string column; a future kind must not break today."""
        rules = [rule(1, ROLE_CTO, matcher_kind="calendar_title", priority=1)]
        assert resolve_rule(ADR_WINDOW, rules) is None


class TestMatcherKinds:
    def test_bundle_id_is_exact(self) -> None:
        rules = [
            rule(
                1,
                ROLE_TECHLEAD,
                matcher_kind=MATCHER_BUNDLE_ID,
                pattern="com.microsoft.VSCod",
            )
        ]
        assert resolve_rule(ADR_WINDOW, rules) is None

    def test_commit_prefix_matches_the_beginning(self) -> None:
        sample = MatchSample(
            source=SOURCE_GIT, commit_message="feat(roles): роли становятся данными"
        )
        rules = [
            rule(
                1,
                ROLE_TECHLEAD,
                source=SOURCE_GIT,
                matcher_kind=MATCHER_COMMIT_PREFIX,
                pattern="feat(roles)",
            )
        ]
        match = resolve_rule(sample, rules)
        assert match is not None
        assert match.role_id == ROLE_TECHLEAD

    def test_repo_path_glob(self) -> None:
        sample = MatchSample(
            source=SOURCE_GIT, repo_path="/Users/d/MyProj/habit_tracker_ai/backend"
        )
        rules = [
            rule(
                1,
                ROLE_TECHLEAD,
                source=SOURCE_GIT,
                matcher_kind=MATCHER_REPO_PATH_GLOB,
                pattern="*/habit_tracker_ai/*",
            )
        ]
        match = resolve_rule(sample, rules)
        assert match is not None
        assert match.role_id == ROLE_TECHLEAD

    def test_clickup_tag_matches_one_of_many(self) -> None:
        sample = MatchSample(source=SOURCE_CLICKUP, clickup_tags=("hiring", "q3"))
        rules = [
            rule(
                1,
                ROLE_CTO,
                source=SOURCE_CLICKUP,
                matcher_kind=MATCHER_CLICKUP_TAG,
                pattern="hiring",
            )
        ]
        match = resolve_rule(sample, rules)
        assert match is not None
        assert match.role_id == ROLE_CTO
