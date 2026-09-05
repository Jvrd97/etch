---
name: "source-command-git-commands-git-review-self"
description: "Review your own staged or branch changes before commit/push. Quick checklist of common issues."
---

# source-command-git-commands-git-review-self

Use this skill when the user asks to run the migrated source command `git-commands-git-review-self`.

## Command Template

Self-review of changes before commit or push. Faster than full `/review` (no sub-agent), focused on common mistakes.

Process:
1. Determine what to review:
   - If staged changes exist (`git diff --cached --stat` non-empty) → review staged
   - Else if uncommitted changes exist → ask: "review unstaged?" (uncommon but possible)
   - Else if on a feature branch → review `<branch>..main`

2. Read the diff.

3. Check against this checklist (flag what you find, with file:line):

   **Smell — Debug leftovers**
   - `console.log` / `console.dir` / `console.debug` in non-test code
   - `print(...)` in non-test Python (except logging or CLI)
   - `debugger` statements
   - `breakpoint()` in Python

   **Smell — Code health**
   - Commented-out code blocks (>2 lines)
   - `TODO` / `FIXME` / `XXX` without issue reference
   - New `any` (TS) without inline `// reason: ...` comment
   - New `# type: ignore` (Python) without inline `# reason: ...` comment
   - Empty `try: except: pass` or `catch (e) {}` без логирования
   - Magic numbers > 1 (literals like 86400, 3600 used directly)

   **Smell — Test coverage**
   - New non-trivial functions without corresponding test changes
   - Tests that look like `assert True` / `expect(true).toBe(true)`
   - Tests with no assertions (just calls)

   **Smell — Architecture**
   - New files with <30 LOC exporting a single function (potential shallow module)
   - Direct DB queries in route handlers (should be in service layer)
   - Direct LLM calls outside orchestration layer (per AGENTS.md §4)

   **Smell — Security**
   - Hardcoded credentials, tokens, URLs with embedded secrets
   - String concatenation in SQL (should be parameterized)
   - `eval()`, `exec()`, `Function()` constructor

4. Output:
   ```markdown
   ## Self-Review for <branch or staged>

   **Files changed:** <count>, **Lines:** +<adds>/-<dels>

   ### 🔴 Must fix before commit (<count>)
   - <file>:<line> — <issue>

   ### 🟡 Should fix (<count>)
   - <file>:<line> — <issue>

   ### 🔵 Consider (<count>)
   - <file>:<line> — <issue>

   ### ✅ Good
   <Brief positive notes if anything stood out — clean structure, good tests, etc.>
   ```

5. If 🔴 blockers exist — recommend NOT committing yet. Otherwise — proceed.

Rules:
- Be specific (file:line, not "somewhere in the codebase")
- Don't repeat the same smell 5 times — say "and N similar"
- Don't nitpick if formatter is configured (formatter is source of truth on style)
- Don't run tests here (that's `/review` or feedback-loop hook)
