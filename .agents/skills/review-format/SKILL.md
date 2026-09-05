---
name: review-format
description: "Human-readable format for review documents. Triggers when writing any review artifact: code-review / inventory reviews in docs/**/reviews/, reviewer sub-agent reports, architecture-review reports, SESSION_REVIEW.md entries. Enforces one-fact-per-bullet, short table cells, per-finding blocks. Fixes the 'wall of text' anti-pattern."
---

# Review Document Format

Review docs are read by tired humans scanning for «что сломано и что делать».
Optimize for scanning, not density. The anti-pattern this skill kills: facts
mashed into run-on paragraphs like `**Gap:** a; b; c; d; e.` — grammatically
fine, unreadable in practice.

## Hard rules

1. **One fact = one bullet.** Never chain facts with `;` inside a paragraph or
   a single bullet. If you typed `;` between two findings — split them.
2. **No `**Label:** <paragraph>` lines.** A labeled group (`Реализовано`, `Gap`,
   `Red flags`) becomes a `####` heading or a bold lead-in line, with facts as
   bullets underneath — one per line.
3. **Table cells ≤ 8 words, single line.** Tables are for enumerable facts
   (verdict, owner, status, counts). Sentences go to bullets below the table,
   never inside cells.
4. **Bold is for severity and verdicts only** (`**working**`, `**LEGAL BLOCKER**`,
   file paths that must not be missed). Not for decoration, not for every label.
5. **Blank line between every block** — heading, list, paragraph, table. Dense
   stacking is what makes docs look «слито».
6. **Start with a TL;DR**: a short verdict table + 3-5 bullets of what matters.
   A reader who stops after the TL;DR must still leave with the right picture.
7. **Headings over labels.** If a section has 3+ labeled groups, promote the
   labels to `####` headings so the doc outline is navigable.

## Per-finding block (reviewer / architecture-review reports)

```markdown
### <N>. <Short finding title>

- **Severity**: 🔴 blocker | 🟡 warning | 🔵 suggestion
- **Where**: `path/to/file.py:42`
- **What**: one sentence — what is wrong.
- **Fix**: one sentence — what to do.
```

## Per-service section (inventory / code-review docs)

```markdown
### SVC-NN <Name> — <verdict>

Owner: <name>. <One-sentence orientation: what this service is in one breath.>

#### Реализовано

- <fact>
- <fact>

#### Против AC

- ✅ <criterion> — done
- ❌ <criterion> — missing / broken: <why>

#### Gap

- <missing thing>

#### Red flags

- <problem> (если нет — одной строкой «нет»)
```

## Forbidden patterns

- ❌ Paragraph with 3+ facts separated by `;`
- ❌ Table cell containing a full sentence or two clauses
- ❌ `**Label:** long text` instead of a heading + bullets
- ❌ Section without a blank line before/after lists
- ❌ Bold on more than ~10% of words in any paragraph

---

## Cognitive cost of the text

The project-wide canon applies on top of this skill:
`~/.Codex/skills/copywriter/reference/cognitive-load.md` (Russian).

Optimize new useful information per unit of reading effort, not length. Minimum: conclusion in
the first paragraph of a section; one name per concept throughout; each point stated once;
constraints placed next to what they constrain; plain verbs instead of noun-blobs; no filler
connectives. Simplify the wording, never the subject.
