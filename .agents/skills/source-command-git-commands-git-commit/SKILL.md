---
name: "source-command-git-commands-git-commit"
description: "Generate a commit message from the staged diff using conventional commits format. Auto-references active issue."
---

# source-command-git-commands-git-commit

Use this skill when the user asks to run the migrated source command `git-commands-git-commit`.

## Command Template

Generate a commit message for currently staged changes.

Process:
1. Run `git diff --cached --stat` to see what's staged. If nothing is staged — STOP and ask the user to stage files first (don't auto-stage).

2. Run `git diff --cached` to read actual changes.

3. Detect the **type** based on changes:
   - `feat`: new functionality
   - `fix`: bug fix
   - `refactor`: code change that neither fixes nor adds (no behavior change)
   - `test`: adding/modifying tests only
   - `docs`: documentation only
   - `chore`: tooling, configs, build, dependencies
   - `perf`: performance improvement
   - `style`: formatting, no logic change

4. Detect the **scope** from changed file paths:
   - `services/auth/*` → scope `auth`
   - `services/billing/*` → scope `billing`
   - Multiple unrelated → no scope
   - Single small file → no scope

5. Find the **active issue** (if exists):
   - Check `issues/*.md` for files matching current branch name
   - Or look at `git log -1` for last commit's issue reference
   - If found, will append `Closes #<issue>` to body

6. Format:
   ```
   <type>(<scope>): <subject under 60 chars>

   <optional body if changes are non-obvious>
   <optional Closes #<issue-number-or-name>>
   ```

7. Show the proposed message to user. Ask: `[y]es / [e]dit / [n]o`.
   - `y` → run `git commit -m "<message>"`
   - `e` → user edits, then commit
   - `n` → cancel

Rules:
- Subject: imperative mood ("add", not "added"), no period at end, lowercase first letter after type/scope
- Body: only if subject can't carry the meaning. Skip body for one-line obvious changes.
- Never invent claims about behavior — only describe what's in the diff
- Never include `Co-Authored-By` unless user explicitly asks
