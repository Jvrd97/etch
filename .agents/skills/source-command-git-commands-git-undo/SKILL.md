---
name: "source-command-git-commands-git-undo"
description: "Safely undo last git operation (commit, merge, rebase). Always confirms before destructive actions."
---

# source-command-git-commands-git-undo

Use this skill when the user asks to run the migrated source command `git-commands-git-undo`.

## Command Template

Safely undo the last git operation.

Process:
1. Detect what to undo. Run `git reflog -10` and identify the last action:
   - **commit** — last action was `commit:` or `commit (amend):`
   - **merge** — `merge` in reflog
   - **rebase** — `rebase` finished entries
   - **checkout** — switched branches (rarely needs undo)
   - **reset** — already reset, can re-reset to before that

2. Show user:
   ```
   Last 5 actions:
     1. commit: feat(auth): add login endpoint    (HEAD)
     2. commit: refactor(db): split user service
     3. checkout: moving from main to feat/auth
     4. commit: chore: bump deps
     5. merge: feat/payments into main
   ```

3. Ask user what to undo. Common cases:

   **Undo last commit (keep changes staged)**:
   ```bash
   git reset --soft HEAD~1
   ```
   Use when: bad commit message, want to add more changes before committing

   **Undo last commit (keep changes unstaged)**:
   ```bash
   git reset HEAD~1
   ```
   Use when: want to selectively re-stage

   **Undo last commit (DISCARD changes)**:
   ```bash
   git reset --hard HEAD~1
   ```
   ⚠️ DANGEROUS — settings.json may block this for `origin/main`. Always confirm.

   **Undo last merge** (no merge commit pushed yet):
   ```bash
   git reset --hard ORIG_HEAD
   ```

   **Undo last rebase** (find pre-rebase HEAD via reflog):
   ```bash
   git reset --hard <hash-from-reflog-before-rebase>
   ```

   **Undo a pushed commit** (create reverse commit, don't rewrite):
   ```bash
   git revert <hash>
   ```
   Use when: commit is already pushed, can't rewrite history

4. For destructive actions (`reset --hard`, undo rebase):
   - Show user EXACTLY what will be lost
   - Suggest creating a backup branch first: `git branch backup-<timestamp>`
   - Require explicit confirmation (`yes` typed, not just enter)

5. After undo:
   - Show new state: `git log -3 --oneline`
   - Show working tree: `git status`
   - Suggest next step

Rules:
- NEVER undo a pushed commit by rewriting history (use `revert` instead)
- NEVER `reset --hard` on branches that aren't yours (e.g., main, develop)
- ALWAYS create backup branch before destructive operations
- If user said "undo" but git state is unclear — show reflog and ask which entry
- Never auto-`reflog expire` or anything that destroys recovery options
