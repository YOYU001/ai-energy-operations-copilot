"""SessionStart hook: surface open GitHub PRs at the start of every session
in this repo, so the user doesn't have to remember to ask "are there any
PRs to review". Pure detection + reporting -- never comments, reviews, or
merges anything itself. Actually reviewing a surfaced PR is Claude's job
in the conversation, following the workflow in
.claude/skills/git-worktree/SKILL.md.

Fails silently (emits {}) on any error -- not a git repo, gh not
authenticated, no network, gh not installed -- so a broken environment
never blocks session start.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

GH_CMD = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def main() -> int:
    try:
        result = subprocess.run(
            [
                GH_CMD, "pr", "list", "--state", "open",
                "--json", "number,title,author,isDraft,updatedAt",
            ],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        print("{}")
        return 0

    if result.returncode != 0 or not result.stdout.strip():
        print("{}")
        return 0

    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("{}")
        return 0

    open_prs = [pr for pr in prs if not pr.get("isDraft")]
    if not open_prs:
        print("{}")
        return 0

    lines = [
        f"There are {len(open_prs)} open PR(s) in this repo. "
        "Proactively mention this to the user near the start of your first "
        "reply this session (don't review or act on any of them without "
        "being asked -- just let the user know they exist):"
    ]
    for pr in open_prs:
        author = (pr.get("author") or {}).get("login", "unknown")
        lines.append(f"- #{pr['number']} \"{pr['title']}\" by {author} (updated {pr.get('updatedAt', '?')})")

    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
