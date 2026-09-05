---
name: "source-command-git-commands-git-cleanup"
description: "Find and remove local feature branches already merged to main. Always asks before deleting."
---

# source-command-git-commands-git-cleanup

Use this skill when the user asks to run the migrated source command `git-commands-git-cleanup`.

## Command Template

Cleanup local branches already merged to main.

Process:
1. Switch to main if not already there:
   - If user not on main: ask "Switch to main first? [y/n]"
   - Otherwise STOP — can't delete branch you're on

2. `git fetch --prune` to clean up tracking refs

3. Find merged branches (excluding current and main):
   ```bash
   git branch --merged main | grep -v "^\*" | grep -v "main$" | grep -v "master$"
   ```

4. Find squash-merged branches (merged via squash, not detected by `--merged`):
   For each local branch:
   - Get the merge-base with main: `git merge-base main <branch>`
   - Get the tree of branch tip: `git rev-parse <branch>^{tree}`
   - Try a virtual commit on main with that tree: if `git cherry-tree` matches an existing commit on main → it was squash-merged

   (Simpler heuristic if above is too complex: just list branches that haven't had a commit in 30+ days as candidates.)

5. Show user the list:
   ```
   Branches merged to main:
     - feat/01-inject-lab-results (merged 3 days ago)
     - fix/15-cache-bug (merged 1 day ago)

   Branches that look stale (>30 days no commits):
     - chore/old-experiment (last commit 45 days ago)
   ```

6. Ask user:
   - `[a]ll` — delete all merged
   - `[s]elect` — go through one by one with y/n
   - `[c]ancel`

7. Execute deletion safely:
   - For merged: `git branch -d <branch>` (safe, won't delete unmerged)
   - For stale (unmerged): `git branch -D <branch>` (force, only after explicit confirmation)

8. Optionally clean up remote tracking:
   - Show `git remote prune origin --dry-run`
   - Ask: prune deleted remote branches? `[y/n]`

Rules:
- NEVER use `-D` (force delete) without explicit user confirmation per branch
- Don't touch branches with active worktrees (`git worktree list` to check)
- Don't delete branches that have unpushed commits (warn instead)
- Don't auto-delete remote branches
