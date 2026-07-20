"""progress-lint: flag PROGRESS.md Completed entries that violate CLAUDE.md's
"PROGRESS.md 撰寫規則" (each entry should be a 1-2 line status summary with
details pushed out to docs/, not a full technical log).

Run from the project root:
    python .claude/skills/progress-lint/scripts/lint_progress.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.platform == "win32":
    # Windows consoles default to a non-UTF-8 code page; without this,
    # printing Chinese preview text or the em dash in guideline messages
    # raises UnicodeEncodeError or silently mangles into garbled bytes.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[4]
PROGRESS_PATH = ROOT / "PROGRESS.md"

# A 1-2 line summary in this project's established style tends to land well
# under this many characters; entries past it are almost always the old
# "full technical log" style this rule was written to stop. Not a hard
# science -- a tunable heuristic, not a strict spec.
MAX_ENTRY_CHARS = 220

DETAILS_MARKER_RE = re.compile(r"Details:\s*docs/\S+\.md")


def _extract_completed_entries(lines: list[str]) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    in_completed = False
    for i, line in enumerate(lines, start=1):
        if line.strip() == "## Completed":
            in_completed = True
            continue
        if in_completed and line.startswith("## "):
            break
        if in_completed and line.startswith("- "):
            entries.append((i, line.rstrip("\n")))
    return entries


def main() -> int:
    if not PROGRESS_PATH.exists():
        print(f"[progress-lint] PROGRESS.md not found at {PROGRESS_PATH}")
        return 1

    lines = PROGRESS_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    entries = _extract_completed_entries(lines)

    if not entries:
        print("[progress-lint] No '## Completed' section found, or it is empty.")
        return 0

    flagged = []
    for line_no, entry in entries:
        char_count = len(entry)
        has_details_marker = bool(DETAILS_MARKER_RE.search(entry))
        too_long = char_count > MAX_ENTRY_CHARS
        missing_details_but_long = char_count > MAX_ENTRY_CHARS // 2 and not has_details_marker
        if too_long or missing_details_but_long:
            preview = entry[:40].lstrip("- ")
            flagged.append((line_no, char_count, has_details_marker, preview))

    print(f"[progress-lint] Checked {len(entries)} Completed entries in PROGRESS.md.")
    if not flagged:
        print("[progress-lint] All entries look within the 1-2 line guideline. Nothing to flag.")
        return 0

    print(f"\n[progress-lint] {len(flagged)} entries may need trimming:\n")
    for line_no, char_count, has_details_marker, preview in flagged:
        marker_note = "has Details: link" if has_details_marker else "NO Details: link"
        print(f"  - line {line_no}: {char_count} chars, {marker_note}")
        print(f"    preview: \"{preview}...\"")

    print(
        "\n[progress-lint] Guideline (CLAUDE.md \"PROGRESS.md 撰寫規則\"): each entry should be "
        "1-2 lines with a 'Details: docs/xxx.md §N' pointer for anything longer."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
