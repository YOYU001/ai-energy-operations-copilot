"""Step 6 Sub-step 5: deterministic query parsing (no LLM).

Scope, deliberately narrow:
  - extract_date_candidates only recognizes the "YYYY年M月D日" pattern --
    the exact date format used throughout doc3's tables and in q06-style
    questions -- tolerant of the irregular whitespace PyMuPDF's extraction
    produces around it (e.g. the real ingested text is "2024 年8 月30 日",
    not "2024年8月30日"). Slash/dash date formats ("2024/5") are
    intentionally NOT matched: they appear in this corpus's prose (e.g.
    q05's "2024/5-12") as loose period references, not as row-identifying
    dates, and treating them as exact-match targets would misfire.
  - looks_like_table_question is a keyword/pattern heuristic, not a
    classifier. It only checks for an explicit "表<digit>" reference (e.g.
    "表4"), matching the same convention this corpus's table captions use
    (see TABLE_TITLE_RE in chunker.py). It deliberately does not try to
    guess from vaguer signals like "SOC"/"kW"/"時段", since those also
    appear in plain prose describing the same events (see q03/q04's
    question text) and would over-trigger the table boost on non-table
    questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_TABLE_REF_RE = re.compile(r"表\s*\d+")


@dataclass(frozen=True)
class DateCandidate:
    year: int
    month: int
    day: int

    def match_regex(self) -> re.Pattern:
        """Regex tolerant of the irregular whitespace real extracted table text has around 年/月/日."""
        return re.compile(rf"{self.year}\s*年\s*{self.month}\s*月\s*{self.day}\s*日")


def extract_date_candidates(query_text: str) -> list[DateCandidate]:
    return [DateCandidate(int(y), int(m), int(d)) for y, m, d in _DATE_RE.findall(query_text)]


def looks_like_table_question(query_text: str) -> bool:
    return bool(_TABLE_REF_RE.search(query_text))
