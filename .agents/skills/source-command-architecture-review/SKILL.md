---
name: "source-command-architecture-review"
description: "Audit architecture documentation for consistency, completeness, and adherence to standards. Use after /write-architecture to catch contradictions, missing ADRs, level violations. Returns audit report — does not modify files."
---

# source-command-architecture-review

Use this skill when the user asks to run the migrated source command `architecture-review`.

## Command Template

Spawn `architecture-reviewer` sub-agent.

## Process

The reviewer will audit `docs/current/architecture/` and `docs/<PHASE-NN>/ADRs/` (plus `docs/GENERAL/ADRs/` for cross-phase decisions) for:

1. **Diagram-prose consistency** — every box and arrow explained
2. **C4 level discipline** — no mixing levels in same diagram
3. **Ownership clarity** — each entity owned by exactly one service
4. **ADR coverage** — every architectural decision has corresponding ADR
5. **Failure mode documentation** — every cross-service flow has failure section
6. **Cross-cutting concerns** — auth, observability, PII have documented sections
7. **Vocabulary consistency** — glossary matches usage in other docs
8. **Evolution readiness** — coupling and dependency direction sensible

## Output

The reviewer returns a report in chat (and saves to `docs/current/architecture/reviews/_review-YYYY-MM-DD.md`).
Formatting follows the `review-format` skill: per-finding blocks (heading +
Where/What/Fix bullets), one fact per bullet, no `;`-chained lists.

```markdown
# Architecture Review: <date>

**Verdict**: PASS | PASS WITH CONDITIONS | FAIL
**Findings**: 🔴 X critical | 🟡 Y warnings | 🔵 Z suggestions

## 🔴 Critical issues

### 1. <Short title>

- **Where**: <file>
- **What**: <one sentence>
- **Why critical**: <one sentence>
- **Fix**: <one sentence>

## 🟡 Warnings

### 1. <Short title>

- **Where**: <file>
- **What**: <one sentence>
- **Fix**: <one sentence>

## 🔵 Suggestions

- <file> — <suggestion, one per bullet>

## Summary

- Strongest area: ...
- Weakest area: ...
- Recommended next session: ...
```

## Verdict thresholds

| Critical | Warnings | Verdict |
|---|---|---|
| 0 | ≤3 | PASS |
| 0 | >3 | PASS WITH CONDITIONS (fix top 3) |
| ≥1 | any | FAIL (block until resolved) |

## What this command does NOT do

- ❌ Modify any files — pure audit
- ❌ Propose alternative architecture — use `/grill-me-arch` for redesign
- ❌ Grade subjectively — only objective consistency checks
- ❌ Demand patterns that aren't necessary

After review:
- If PASS → proceed with implementation (per-service PRDs)
- If PASS WITH CONDITIONS → address top warnings before next iteration
- If FAIL → fix critical issues, re-run `/architecture-review`

If reviewer finds the same critical issue twice across runs — flag that the underlying design has a problem, suggest `/grill-me-arch` revisit.
