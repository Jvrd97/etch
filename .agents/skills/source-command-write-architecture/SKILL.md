---
name: "source-command-write-architecture"
description: "Generate the full architecture documentation set from a completed /grill-me-arch session. Produces system-context, container-diagram, component-diagrams, data-flow, data-model, ADRs, glossary as separate files."
---

# source-command-write-architecture

Use this skill when the user asks to run the migrated source command `write-architecture`.

## Command Template

Apply the `software-architect` skill (architecture mindset) and the `write-architecture` skill (output structure rules) and the `c4-diagrams` skill (diagram syntax) and the `adr-format` skill (ADR template).

This runs in main conversation context — file generation is interactive, you may need to ask user for clarifications on ambiguous grilling notes.

## Pre-conditions check

Verify before generating:

1. **Grilling artifact exists**: look for recent file in `brain-dumps/architecture/*.md`
2. **User confirms readiness**: ask "have you reviewed the grilling artifact and ready to write?" if not obvious from conversation
3. **Existing `docs/current/architecture/`** read first (don't blindly overwrite). `current` is a symlink to the active phase; phase marker is `docs/ROADMAP/STATUS.md`

If grilling artifact not found:
- Ask user to run `/grill-me-arch` first
- Or to provide path to grilling artifact if it's elsewhere

## Process

1. **Read grilling artifact** fully
2. **Read existing `docs/current/architecture/`** if any — diff against new decisions
3. **Generate file set** in `docs/current/architecture/`:
   - `README.md` (index, how to navigate)
   - `system-context.md` (C4 L1) — REQUIRED
   - `container-diagram.md` (C4 L2) — REQUIRED
   - `component-diagrams/<service>.md` (C4 L3) — for services with internal complexity
   - `data-flow/<flow-name>.md` (sequence diagrams) — for each key flow
   - `data-model.md` (entity ownership table)
   - `cross-cutting.md` (auth, observability, schema evolution, PII)
   - `glossary.md` (domain terms)
4. **Generate ADRs** in `docs/<PHASE-NN>/ADRs/` (cross-phase → `docs/GENERAL/ADRs/`):
   - One per cross-cutting decision visible in grilling
   - Use `adr-format` skill template
   - Filename: `YYYY-MM-DD-<slug>.md`
5. **Cross-link** documents (markdown links)
6. **Update `AGENTS.md`** if grilling produced new "always true" rules

## Validation during generation

For each file generated:
- Diagram uses C4 syntax (not generic flowchart) for arch views
- Sequence diagrams use `sequenceDiagram` for flows
- Every diagram has explanation in prose
- Every box/arrow in diagram is mentioned in prose
- ADRs have minimum 2 options each
- No mixed C4 levels in one diagram

## Output summary

After all files written, show user:

```
Architecture documentation generated:

docs/current/architecture/
├── README.md
├── system-context.md
├── container-diagram.md
├── component-diagrams/
│   ├── medical-service.md
│   └── ai-service.md
├── data-flow/
│   ├── wearable-ingest.md
│   └── voice-input.md
├── data-model.md
├── cross-cutting.md
└── glossary.md

docs/<PHASE-NN>/ADRs/
├── 2026-05-09-service-transport.md
├── 2026-05-09-zero-parsing-connector.md
└── 2026-05-09-llm-orchestration-isolation.md

AGENTS.md updated with new rule: "<rule>" (if applicable)

Next steps:
1. Review generated files
2. Run /architecture-review to audit consistency
3. Per-service PRDs if needed: /grill-me for each affected service
4. Update ClickUp tasks tied to architectural changes
```

## When NOT to use this

- Grilling not complete → run `/grill-me-arch` first, don't shortcut
- Just want to update one file → edit directly, don't regenerate everything
- Documenting decision already made (no grilling) → just write ADR directly via `adr-format` skill
- Per-service detail → use `/write-prd` not this
