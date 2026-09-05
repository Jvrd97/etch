---
name: "source-command-git-commands-git-sync"
description: "Safely sync the current feature branch with main (rebase or merge). Shows what's coming before applying."
---

# source-command-git-commands-git-sync

Use this skill when the user asks to run the migrated source command `git-commands-git-sync`.

## Command Template

Safely sync the current feature branch with main.

Process:
1. Identify state:
   - Current branch: `git branch --show-current`
   - If on `main`/`master` — STOP, this command is for feature branches
   - Base branch: `main` (or `master` if main doesn't exist)

2. Check working tree is clean:
   - `git status --porcelain`
   - If dirty: ask user — stash, commit first, or cancel?

3. Fetch latest:
   ```bash
   git fetch origin
   ```

4. Show what's coming:
   ```bash
   git log HEAD..origin/<base> --oneline
   git diff HEAD..origin/<base> --stat
   ```
   Print summary: "X commits, Y files changed since you branched."

5. Show what's ours:
   ```bash
   git log origin/<base>..HEAD --oneline
   ```

6. Ask user: rebase or merge?
   - **Rebase**: cleaner history, replays our commits on top of base
     - Risk: if branch is shared, force-push needed (and force-push is denied by settings.json)
   - **Merge**: safer, preserves history, creates merge commit
     - Use when branch is already pushed and shared

   Default recommendation:
   - If branch never pushed → rebase
   - If branch is pushed and you're solo → rebase (you'll need to push later, but force-push is denied; use `git push --force-with-lease` which user must run manually)
   - If branch is shared → merge

7. Execute (with user confirmation):
   - Rebase: `git rebase origin/<base>`
   - Merge: `git merge origin/<base>`

8. Handle conflicts:
   - If conflicts arise, **DO NOT auto-resolve**.
   - List conflicting files
   - Tell user to resolve manually
   - Suggest commands: `git status` to see conflicts, edit files, `git add <file>`, then `git rebase --continue` or `git merge --continue`

9. After successful sync — show:
   - Final state: `git log -3 --oneline`
   - Suggested next step (push if branch was already pushed)

Rules:
- NEVER auto-resolve conflicts
- NEVER force-push (denied by settings.json anyway)
- Always show what's coming BEFORE applying
- If unclear which strategy → ask
