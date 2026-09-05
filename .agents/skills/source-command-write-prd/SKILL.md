---
name: "source-command-write-prd"
description: "Generate a PRD from the alignment achieved in grill-me. Saves to issues/<active-phase>/PRDs/in-review/."
---

# source-command-write-prd

Use this skill when the user asks to run the migrated source command `write-prd`.

## Command Template

Apply the `write-a-prd` skill.

If a `grill-me` session has not happened in this conversation, STOP and tell the user to run `/grill-me` first. PRD without alignment = garbage.

Otherwise, fill the PRD template using ONLY information that was discussed. Do not invent details. Resolve the active phase from the `issues/current` symlink and save to `issues/<active-phase>/PRDs/in-review/PRD-<slug>.md` (fallback to `issues/PRD-<slug>.md` only if that structure is absent). Report the path.

Do NOT read the PRD back to the user as a lecture — just report the file path.
