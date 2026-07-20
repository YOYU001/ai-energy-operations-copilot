"""Step 6 Sub-step 3: chunking strategies for the RAG spike.

Four strategies are provided:
  - "fixed_baseline_600_100": raw fixed-size character windows, ignoring all
    document structure. Worst-case baseline for comparison.
  - "structured_400_80" / "structured_600_100" / "structured_800_120":
    paragraph-aware + sentence-boundary + table-aware splitting, at three
    different (chunk_size, overlap) settings.

Table handling (structured strategies only): a detected table region is
packed into one or more table chunks. Each table chunk always repeats the
table title and column header line, and never splits an individual "row
group" (see _extract_blocks) across two chunks -- a row group is the natural
grouping unit found in this corpus's tables (e.g. all sub-rows under one
date in "表 4. 系統超約事件紀錄"), not a single physical line, because the
explicit requirement is that a full logical record (e.g. all of 2024/8/30's
six rows) must not be split apart, not merely that no single physical line
is split.

Table and paragraph detection are heuristics tuned to the actual layout
observed in this spike's four documents (unit-annotated column headers like
"(kW)"/"(%)", trailing "表 N. ..." captions, indent-marked paragraph starts).
They are not a general-purpose PDF table/paragraph parser -- documented as a
known limitation, not silently assumed to generalize.

Sub-step 8 (doc4 table detection) added a SECOND, independent table-entry
path ("caption-first", state "table_captionfirst" in _extract_blocks) for
tables whose caption precedes the data (doc4's "表 3-1 ...", "表 4-1 ..."
style) instead of doc3's Table 4, whose caption trails the data. This path
is anchored on CAPTION_FIRST_TITLE_RE (the "表N-M" hyphen format doc4 uses,
deliberately NOT the "表N." period format TABLE_TITLE_RE/doc3 uses, so this
new path can never fire on doc3's caption line) and only ever triggers from
"prose" state, exactly like the existing DATE_LINE_RE-anchored path -- the
two are independent elif branches that cannot interact, so doc3's existing
behavior is provably unaffected. Unlike the DATE_LINE_RE path, this new path
does NOT attempt to distinguish header lines from data lines (doc4's row
labels are category names or battery-cell IDs, not a uniform key like
doc3's dates, so there is no reliable forward anchor for "header ends,
data begins"); instead it packs every line as its own single-line RowGroup,
in original order, and stores an empty header_line. See docs/RAG_SPIKE_PLAN.md
Sub-step 8 for the full rationale and known limitations of this approach.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Union

from spike.pdf_parser import PageParseResult

# ---------------------------------------------------------------------------
# Regex heuristics
# ---------------------------------------------------------------------------

# A line consisting mostly of unit-annotated column names, e.g.
# "日期 時間 需量 (kW) 市電 (kW) PV (kW) 儲能 (kW) 儲能 SOC (%)".
_UNIT_PAREN_RE = re.compile(r"\([^()]{0,8}(kW|kWh|%|°C|Wh|V|A|Ah|SOC)\)")

# A trailing table caption, e.g. "表 4. 系統超約事件紀錄" or "表 3. 場域主要設備規格總表".
TABLE_TITLE_RE = re.compile(r"^表\s*\d+[\.．]\s*\S")

# A date line that starts a new logical row-group within a table, e.g.
# "2024 年5 月4 日" or "2024年8月30日" (PyMuPDF extracts this corpus's table
# cells one-per-line, so spacing around each component is inconsistent;
# \s* tolerates all the spacing variants actually observed).
DATE_LINE_RE = re.compile(r"^\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$")

# A paragraph-start line in this corpus's extracted text: indented with a
# leading space or full-width space before the first non-space character.
_PARA_START_RE = re.compile(r"^[ 　]+\S")

# Sentence boundary for splitting an oversized paragraph (keeps the
# terminator attached to the preceding sentence).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])")

# A header-token line: short, and not ending in clause/sentence punctuation
# (used only when scanning backward from a detected DATE_LINE_RE match).
_MAX_HEADER_TOKEN_LEN = 15
_HEADER_TOKEN_STOP_CHARS = "：:。！？，,"

# A physical table row's leading cell, e.g. "10:30~10:45" -- used only to
# find sub-row boundaries *within* an oversized row group when it must be
# split further (see MAX_ROW_GROUP_OVERSHOOT_RATIO below). Not used for the
# main table state-machine transitions in _extract_blocks.
_TIME_RANGE_RE = re.compile(r"^\d{1,2}[:：]\d{2}\s*[~\-]\s*\d{1,2}[:：]\d{2}")

# --- Sub-step 8: doc4 "caption-first" table detection (see module docstring) ---

# A doc4-style table caption, e.g. "表 3-1 電池系統組成之電壓與容量" -- the
# hyphenated "表N-M" format, deliberately distinct from TABLE_TITLE_RE's
# period format so this never matches a doc3-style caption.
CAPTION_FIRST_TITLE_RE = re.compile(r"^表\s*\d+-\d+\s*\S")

# A table-of-contents dot-leader line, e.g. "表 3-1 電池系統組成之電壓與容量
# .......................... 15". Any candidate caption line containing a run
# of 3+ dots is rejected outright -- real captions in this corpus never
# contain dot leaders, only ToC entries do.
_TOC_DOT_LEADER_RE = re.compile(r"\.{3,}")

# A figure caption, e.g. "圖 3-1 電池組與電池管理系統示意圖" -- observed in
# doc4 to immediately follow every caption-first table's body, so it is used
# as one of that path's exit signals.
_FIGURE_CAPTION_RE = re.compile(r"^圖\s*\d+")

# A numbered section heading, e.g. "3.2.2 電池內部結構量測與失效分析" or
# "4.3.5 簡易型三段式電價分析" -- observed to immediately follow a
# caption-first table's body about as often as a figure caption does. This
# is a reliable exit signal because it is structurally distinct from any
# table cell content in this corpus (a dotted multi-level number followed by
# real heading text, never seen inside a table body). \s+ (not \s*) is
# required: without it, a bare decimal table value like "3.381" also matches
# via regex backtracking (\d+ gives back a digit to satisfy a trailing \S)
# -- confirmed and fixed after it silently truncated 表 3-2's data rows.
_SECTION_HEADING_RE = re.compile(r"^\d+(?:\.\d+)+\s+\S")

# Looser than _looks_like_header_token (which stays reserved for the
# DATE_LINE_RE path and is tuned for short column-header cells): some doc4
# table cells are a full instruction sentence (e.g. "先用1.5A 進行CC 充電，
# 直到電壓達到4.1V", ~24 chars) rather than a short label, so the entry/
# continuation check needs a larger length budget. It still rejects a line
# ending in sentence-final punctuation, since a genuinely resumed prose
# paragraph line reliably differs from a table cell on that point even when
# both are under the length cutoff.
_MAX_TABLE_BODY_LINE_LEN = 40


def _looks_like_table_body_line(text: str) -> bool:
    if not text or len(text) > _MAX_TABLE_BODY_LINE_LEN:
        return False
    return text[-1] not in _HEADER_TOKEN_STOP_CHARS


def _is_captionfirst_exit_line(text: str) -> bool:
    """True if `text` is a new table caption / doc3-style caption / figure
    caption / section heading -- i.e. a line that must end the CURRENT
    caption-first table, never be absorbed as one more body line of it.

    Used both by the entry-time forward lookahead (_forward_table_body_run)
    and by the main state-machine loop's continuation check, so the two
    can never disagree. An earlier version only used _looks_like_table_body_line
    for the lookahead, which is also true of a short caption line -- it
    silently swallowed 表 4-13's caption into 表 4-12's body before the main
    loop's exit check ever got a chance to see it. Fixed by sharing this
    single predicate everywhere a caption-first table might need to end.
    """
    if CAPTION_FIRST_TITLE_RE.match(text) and not _TOC_DOT_LEADER_RE.search(text):
        return True
    if TABLE_TITLE_RE.match(text):
        return True
    if _FIGURE_CAPTION_RE.match(text):
        return True
    if _SECTION_HEADING_RE.match(text):
        return True
    return False


# Minimum number of consecutive table-body-shaped lines that must follow a
# CAPTION_FIRST_TITLE_RE match (after tolerating a small number of leading
# blank lines -- doc4 sometimes has one between the caption and the first
# header cell, e.g. 表 3-2 and 表 4-1) before it is accepted as a real table.
# This is the structural gate that rejects ToC entries even if the
# dot-leader check somehow missed one, since ToC lines are long and don't
# form a run of short lines; see _forward_table_body_run.
MIN_CAPTION_FIRST_BODY_LINES = 3
MAX_LEADING_BLANK_LINES_BEFORE_HEADER = 2

# How far forward to scan for that run before giving up.
MAX_HEADER_LOOKAHEAD = 10

# Safety valve mirroring MAX_LINES_PER_TABLE_REGION, scoped smaller: this
# path's exit signals (next caption/figure/heading/page boundary) are less
# certain than the DATE_LINE_RE path's, so failing safe sooner is preferred.
MAX_LINES_PER_CAPTION_FIRST_TABLE = 60


def _forward_table_body_run(doc_lines: list, start_i: int, max_lookahead: int) -> tuple:
    """From start_i, first tolerate up to MAX_LEADING_BLANK_LINES_BEFORE_HEADER
    blank lines, then collect a contiguous run of table-body-shaped lines (a
    blank line or an over-length/punctuated line stops the run). Deliberately
    does NOT try to decide which of these lines are header cells vs. data
    cells -- see module docstring for why that split isn't attempted this
    round. Returns (run, next_i) so the caller knows exactly how many lines
    (including any skipped leading blanks) to advance past.
    """
    i = start_i
    n = len(doc_lines)
    blanks_skipped = 0
    while i < n and not doc_lines[i].text and blanks_skipped < MAX_LEADING_BLANK_LINES_BEFORE_HEADER:
        i += 1
        blanks_skipped += 1

    run: list = []
    while i < n and len(run) < max_lookahead:
        stripped = doc_lines[i].text
        if not stripped or _is_captionfirst_exit_line(stripped) or not _looks_like_table_body_line(stripped):
            break
        run.append(doc_lines[i])
        i += 1
    return run, i


# A row group (e.g. all six rows under one date in Table 4) is normally kept
# as a single atomic unit. It may push a chunk up to 20% over the nominal
# chunk_size before that is no longer tolerated; beyond that, the row group
# is split at physical-row boundaries (never mid-row) so packing can still
# make progress on unusually large tables.
MAX_ROW_GROUP_OVERSHOOT_RATIO = 1.2


def _looks_like_header_token(text: str) -> bool:
    if not text or len(text) > _MAX_HEADER_TOKEN_LEN:
        return False
    return text[-1] not in _HEADER_TOKEN_STOP_CHARS


def _extract_header_backward(para_lines: list, max_lookback: int = 12):
    """Scan backward from the end of para_lines for a run of short
    header-token lines (this corpus's tables extract one cell per line, so a
    multi-line header run immediately precedes the first DATE_LINE_RE row).
    Returns (remaining_para_lines, header_doc_lines) in original order.
    """
    header_lines: list = []
    i = len(para_lines) - 1
    count = 0
    while i >= 0 and count < max_lookback and _looks_like_header_token(para_lines[i].text):
        header_lines.append(para_lines[i])
        i -= 1
        count += 1
    header_lines.reverse()
    return para_lines[: i + 1], header_lines


# ---------------------------------------------------------------------------
# Intermediate data structures
# ---------------------------------------------------------------------------


@dataclass
class DocLine:
    text: str
    page_index: int
    pdf_page_number: int
    printed_page_number: Optional[str]
    section_title: Optional[str]


@dataclass
class ProseParagraph:
    text: str
    page_start: int
    page_end: int
    pdf_page_start: int
    pdf_page_end: int
    printed_pages: list = field(default_factory=list)
    section_title: Optional[str] = None


@dataclass
class RowGroup:
    lines: list  # list[DocLine]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass
class TableRegion:
    header_line: str
    table_title: Optional[str]
    row_groups: list  # list[RowGroup]


Block = Union[ProseParagraph, TableRegion]


@dataclass
class _Contribution:
    text: str
    page_start: int
    page_end: int
    pdf_page_start: int
    pdf_page_end: int
    printed_pages: list
    section_title: Optional[str]


@dataclass
class Chunk:
    chunk_id: str
    source_filename: str
    chunk_type: str  # "prose" | "table"
    text: str
    char_count: int
    page_index_range: tuple
    pdf_page_number_range: tuple
    printed_page_number_list: list
    section_title: Optional[str]
    strategy_name: str
    table_title: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source_filename": self.source_filename,
            "chunk_type": self.chunk_type,
            "text": self.text,
            "char_count": self.char_count,
            "page_index_range": list(self.page_index_range),
            "pdf_page_number_range": list(self.pdf_page_number_range),
            "printed_page_number_list": self.printed_page_number_list,
            "section_title": self.section_title,
            "strategy_name": self.strategy_name,
            "table_title": self.table_title,
        }


# ---------------------------------------------------------------------------
# Section-title carry-forward (page-granular, reuses Sub-step 2's per-page
# heading detection instead of re-implementing line-level heading regexes)
# ---------------------------------------------------------------------------


def _carry_forward_section_titles(pages: list[PageParseResult]) -> list[Optional[str]]:
    titles: list[Optional[str]] = []
    current: Optional[str] = None
    for page in pages:
        if page.section_title:
            current = page.section_title
        titles.append(current)
    return titles


def _build_doc_lines(pages: list[PageParseResult], section_titles: list[Optional[str]]) -> list[DocLine]:
    doc_lines: list[DocLine] = []
    for page, section_title in zip(pages, section_titles):
        for raw_line in page.text.splitlines():
            doc_lines.append(
                DocLine(
                    text=raw_line.strip(),
                    page_index=page.page_index,
                    pdf_page_number=page.pdf_page_number,
                    printed_page_number=page.printed_page_number,
                    section_title=section_title,
                )
            )
    return doc_lines


# ---------------------------------------------------------------------------
# Block extraction (paragraph / table state machine)
# ---------------------------------------------------------------------------


def _extract_blocks(doc_lines: list[DocLine]) -> list[Block]:
    """Split a document's lines into ProseParagraph and TableRegion blocks.

    Table detection is anchored on DATE_LINE_RE, not a single-line header
    match: this corpus's PDF table extraction puts one cell per physical
    line, so a would-be header like "日期 時間 需量 (kW) ..." is actually
    7 separate short lines, not one line with multiple unit-in-parens
    matches. When a DATE_LINE_RE line is seen while in prose mode, we look
    backward through the lines just accumulated for a run of short,
    punctuation-free "header token" lines; if that run contains at least one
    unit-annotated token (e.g. "(kW)"), it is accepted as the table header
    and we enter table mode. This intentionally only detects date-indexed
    tables like "表 4. 系統超約事件紀錄" -- documented as a known scope
    limitation, not assumed to generalize to every table shape.
    """
    blocks: list[Block] = []

    state = "prose"
    para_lines: list[DocLine] = []

    table_header: Optional[str] = None
    row_groups: list[RowGroup] = []
    current_group_lines: list[DocLine] = []

    # Safety valve: if a table region never finds its trailing caption and
    # keeps consuming lines indefinitely (heuristic failure on an
    # unanticipated document shape), force-close it rather than silently
    # swallowing the rest of the document as "table" content.
    MAX_LINES_PER_TABLE_REGION = 500

    # --- Sub-step 8: doc4 "caption-first" table state (independent of the
    # table_header/row_groups/current_group_lines vars above, which remain
    # exclusively owned by the DATE_LINE_RE-anchored path) ---
    cf_title: Optional[str] = None
    cf_start_page: Optional[int] = None
    cf_row_groups: list[RowGroup] = []

    def flush_captionfirst():
        nonlocal cf_title, cf_start_page, cf_row_groups
        if cf_row_groups:
            blocks.append(TableRegion(header_line="", table_title=cf_title, row_groups=list(cf_row_groups)))
        cf_title = None
        cf_start_page = None
        cf_row_groups = []

    def flush_para():
        nonlocal para_lines
        if para_lines:
            blocks.append(
                ProseParagraph(
                    text=" ".join(line.text for line in para_lines),
                    page_start=para_lines[0].page_index,
                    page_end=para_lines[-1].page_index,
                    pdf_page_start=para_lines[0].pdf_page_number,
                    pdf_page_end=para_lines[-1].pdf_page_number,
                    printed_pages=sorted({l.printed_page_number for l in para_lines if l.printed_page_number}),
                    section_title=para_lines[0].section_title,
                )
            )
        para_lines = []

    def flush_group():
        nonlocal current_group_lines
        if current_group_lines:
            row_groups.append(RowGroup(lines=list(current_group_lines)))
        current_group_lines = []

    def flush_table(discovered_title: Optional[str]):
        nonlocal table_header, row_groups
        flush_group()
        if row_groups:
            blocks.append(TableRegion(header_line=table_header or "", table_title=discovered_title, row_groups=list(row_groups)))
        table_header = None
        row_groups = []

    i = 0
    n = len(doc_lines)
    total_table_lines = 0
    while i < n:
        line = doc_lines[i]
        stripped = line.text

        if not stripped:
            if state == "prose":
                flush_para()
            i += 1
            continue

        if state == "prose":
            if DATE_LINE_RE.match(stripped):
                remaining, header_lines = _extract_header_backward(para_lines)
                has_unit = any(_UNIT_PAREN_RE.search(h.text) for h in header_lines)
                if has_unit:
                    para_lines = remaining
                    flush_para()
                    state = "table"
                    table_header = " ".join(h.text for h in header_lines)
                    row_groups = []
                    current_group_lines = [line]
                    total_table_lines = 1
                    i += 1
                    continue
                # DATE_LINE_RE matched but no header-like run precedes it:
                # treat as an ordinary prose line (e.g. a date mentioned
                # inline is very unlikely to occupy a whole isolated line,
                # but this guards against that false-positive risk anyway).

            if CAPTION_FIRST_TITLE_RE.match(stripped) and not _TOC_DOT_LEADER_RE.search(stripped):
                body_run, after_body_i = _forward_table_body_run(doc_lines, i + 1, MAX_HEADER_LOOKAHEAD)
                if len(body_run) >= MIN_CAPTION_FIRST_BODY_LINES:
                    flush_para()
                    state = "table_captionfirst"
                    cf_title = stripped
                    cf_start_page = line.page_index
                    cf_row_groups = [RowGroup(lines=[l]) for l in body_run]
                    i = after_body_i
                    continue
                # Not enough of a table-body-shaped run follows -- this is
                # either a ToC entry the dot-leader check missed, or a plain
                # inline mention of a table number in prose. Fall through and
                # treat this line as ordinary prose.

            if not para_lines or _PARA_START_RE.match(line.text):
                flush_para()
                para_lines = [line]
            else:
                para_lines.append(line)
            i += 1
            continue

        if state == "table_captionfirst":
            # NOTE: an earlier version of this exit condition used
            # _PARA_START_RE (leading-whitespace-based), but DocLine.text is
            # already .strip()'d in _build_doc_lines, so that check can never
            # match -- it was dead code (this is also true of the existing
            # DATE_LINE_RE-anchored path's identical check, a pre-existing
            # quirk, not something this sub-step introduced or relies on).
            # The working replacement: _is_captionfirst_exit_line (shared
            # with the entry-time forward lookahead, see its docstring for
            # why sharing it matters) plus, as a second line of defense, a
            # table-body line is bounded in length/punctuation per
            # _looks_like_table_body_line -- a real prose paragraph line
            # resuming after the table reliably fails that check even when
            # none of the other exit signals fired first.
            crossed_page = line.page_index != cf_start_page
            looks_like_prose_resumed = not _looks_like_table_body_line(stripped)
            if _is_captionfirst_exit_line(stripped) or crossed_page or looks_like_prose_resumed:
                flush_captionfirst()
                state = "prose"
                continue  # reprocess this same line under prose rules
            cf_row_groups.append(RowGroup(lines=[line]))
            i += 1
            if len(cf_row_groups) >= MAX_LINES_PER_CAPTION_FIRST_TABLE:
                flush_captionfirst()
                state = "prose"
            continue

        # state == "table"
        if TABLE_TITLE_RE.match(stripped):
            flush_table(stripped)
            state = "prose"
            i += 1
            continue
        if DATE_LINE_RE.match(stripped):
            flush_group()
            current_group_lines = [line]
            i += 1
            total_table_lines += 1
            continue
        # Any other line encountered in table mode belongs to the current
        # row group (this corpus's tables put one value per line, so a row's
        # time range and its numeric cells are each separate lines).
        current_group_lines.append(line)
        i += 1
        total_table_lines += 1
        if total_table_lines >= MAX_LINES_PER_TABLE_REGION:
            flush_table(None)
            state = "prose"

    if state == "prose":
        flush_para()
    elif state == "table_captionfirst":
        flush_captionfirst()
    else:
        flush_table(None)

    return blocks


# ---------------------------------------------------------------------------
# Oversized-paragraph splitting (sentence-boundary aware)
# ---------------------------------------------------------------------------


def _split_oversized(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s]
    pieces: list[str] = []
    buf = ""
    for sentence in sentences:
        if buf and len(buf) + len(sentence) > limit:
            pieces.append(buf)
            buf = sentence
        else:
            buf += sentence
    if buf:
        pieces.append(buf)

    final: list[str] = []
    for piece in pieces:
        if len(piece) <= limit:
            final.append(piece)
        else:
            # a single sentence longer than the limit: hard-slice as a last resort
            for j in range(0, len(piece), limit):
                final.append(piece[j : j + limit])
    return final


# ---------------------------------------------------------------------------
# Packing contributions (prose) into size-bounded, overlap-aware chunks
# ---------------------------------------------------------------------------


def _current_len(contributions: list[_Contribution]) -> int:
    if not contributions:
        return 0
    return len("\n".join(c.text for c in contributions))


def _make_prose_chunk(buf: list[_Contribution], source_filename: str, strategy_name: str, index: int) -> Chunk:
    text = "\n".join(c.text for c in buf)
    page_starts = [c.page_start for c in buf]
    page_ends = [c.page_end for c in buf]
    pdf_starts = [c.pdf_page_start for c in buf]
    pdf_ends = [c.pdf_page_end for c in buf]
    printed = sorted({p for c in buf for p in c.printed_pages if p})
    return Chunk(
        chunk_id=f"{source_filename}::{strategy_name}::prose::{index:04d}",
        source_filename=source_filename,
        chunk_type="prose",
        text=text,
        char_count=len(text),
        page_index_range=(min(page_starts), max(page_ends)),
        pdf_page_number_range=(min(pdf_starts), max(pdf_ends)),
        printed_page_number_list=printed,
        section_title=buf[0].section_title,
        strategy_name=strategy_name,
    )


def _pack_contributions(
    contributions: list[_Contribution], chunk_size: int, overlap: int, source_filename: str, strategy_name: str, start_index: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[_Contribution] = []

    def flush():
        nonlocal buf
        if not buf:
            return
        chunks.append(_make_prose_chunk(buf, source_filename, strategy_name, start_index + len(chunks)))
        last = buf[-1]
        buf = []
        return last

    for contribution in contributions:
        trial = buf + [contribution]
        if buf and _current_len(trial) > chunk_size:
            last = flush()
            if overlap > 0 and chunks:
                tail_text = chunks[-1].text[-overlap:]
                if tail_text.strip() and last is not None:
                    buf = [
                        _Contribution(
                            text=tail_text,
                            page_start=last.page_start,
                            page_end=last.page_end,
                            pdf_page_start=last.pdf_page_start,
                            pdf_page_end=last.pdf_page_end,
                            printed_pages=last.printed_pages,
                            section_title=last.section_title,
                        )
                    ]
        buf.append(contribution)
    flush()
    return chunks


# ---------------------------------------------------------------------------
# Table packing: never split a row group; always repeat title + header
# ---------------------------------------------------------------------------


def _split_row_group_into_rows(group: RowGroup) -> list[RowGroup]:
    """Split an oversized row group into its individual physical rows (a
    time-range cell plus its associated value cells). Each resulting
    RowGroup is still atomic -- a single physical row's cells are never
    split apart, only the grouping *above* the row level is broken.

    The group's leading label line(s) (e.g. the date line, which precedes
    the first time-range) are kept attached to the first physical row rather
    than becoming their own near-empty unit.
    """
    sub_rows: list[list] = []
    current: list = []
    started_row = False
    for line in group.lines:
        if _TIME_RANGE_RE.match(line.text):
            if started_row:
                sub_rows.append(current)
                current = [line]
            else:
                current.append(line)
                started_row = True
        else:
            current.append(line)
    if current:
        sub_rows.append(current)
    if len(sub_rows) <= 1:
        return [group]
    return [RowGroup(lines=lines) for lines in sub_rows]


def _pack_table_region(region: TableRegion, chunk_size: int, source_filename: str, strategy_name: str, start_index: int) -> list[Chunk]:
    title = region.table_title or "(unknown table title)"
    header = region.header_line
    prefix = f"{title}\n{header}\n"
    overshoot_limit = chunk_size * MAX_ROW_GROUP_OVERSHOOT_RATIO

    # A row group that alone would push a chunk more than 20% over
    # chunk_size is expanded into its individual physical rows first, so the
    # packer below can still make progress without ever splitting a single
    # data row (see _split_row_group_into_rows).
    units: list[RowGroup] = []
    for group in region.row_groups:
        solo_len = len(prefix) + len(group.text)
        if solo_len > overshoot_limit:
            units.extend(_split_row_group_into_rows(group))
        else:
            units.append(group)

    chunks: list[Chunk] = []
    buf_units: list[RowGroup] = []

    def flush():
        nonlocal buf_units
        if not buf_units:
            return
        body = "\n".join(u.text for u in buf_units)
        text = prefix + body
        all_lines = [ln for u in buf_units for ln in u.lines]
        page_idx = [ln.page_index for ln in all_lines]
        pdf_pages = [ln.pdf_page_number for ln in all_lines]
        printed = sorted({ln.printed_page_number for ln in all_lines if ln.printed_page_number})
        chunks.append(
            Chunk(
                chunk_id=f"{source_filename}::{strategy_name}::table::{start_index + len(chunks):04d}",
                source_filename=source_filename,
                chunk_type="table",
                text=text,
                char_count=len(text),
                page_index_range=(min(page_idx), max(page_idx)),
                pdf_page_number_range=(min(pdf_pages), max(pdf_pages)),
                printed_page_number_list=printed,
                section_title=all_lines[0].section_title,
                strategy_name=strategy_name,
                table_title=title,
            )
        )
        buf_units = []

    for unit in units:
        candidate_len = len(prefix) + len("\n".join(u.text for u in buf_units + [unit]))
        if buf_units and candidate_len > chunk_size:
            flush()
        buf_units.append(unit)
    flush()
    return chunks


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def chunk_document_structured(pages: list[PageParseResult], source_filename: str, chunk_size: int, overlap: int, strategy_name: str) -> list[Chunk]:
    section_titles = _carry_forward_section_titles(pages)
    doc_lines = _build_doc_lines(pages, section_titles)
    blocks = _extract_blocks(doc_lines)

    chunks: list[Chunk] = []
    prose_buffer: list[_Contribution] = []

    def flush_prose():
        nonlocal prose_buffer
        if prose_buffer:
            chunks.extend(_pack_contributions(prose_buffer, chunk_size, overlap, source_filename, strategy_name, len(chunks)))
            prose_buffer = []

    for block in blocks:
        if isinstance(block, ProseParagraph):
            for piece in _split_oversized(block.text, chunk_size):
                prose_buffer.append(
                    _Contribution(
                        text=piece,
                        page_start=block.page_start,
                        page_end=block.page_end,
                        pdf_page_start=block.pdf_page_start,
                        pdf_page_end=block.pdf_page_end,
                        printed_pages=block.printed_pages,
                        section_title=block.section_title,
                    )
                )
        else:
            flush_prose()
            chunks.extend(_pack_table_region(block, chunk_size, source_filename, strategy_name, len(chunks)))

    flush_prose()
    return chunks


def chunk_document_fixed_baseline(pages: list[PageParseResult], source_filename: str, chunk_size: int, overlap: int, strategy_name: str = "fixed_baseline") -> list[Chunk]:
    section_titles = _carry_forward_section_titles(pages)

    full_text_parts: list[str] = []
    char_page_index: list[int] = []
    char_pdf_page: list[int] = []
    char_printed: list[Optional[str]] = []

    for page in pages:
        text = page.text + "\n"
        full_text_parts.append(text)
        char_page_index.extend([page.page_index] * len(text))
        char_pdf_page.extend([page.pdf_page_number] * len(text))
        char_printed.extend([page.printed_page_number] * len(text))

    full_text = "".join(full_text_parts)
    step = max(1, chunk_size - overlap)

    chunks: list[Chunk] = []
    i = 0
    while i < len(full_text):
        j = min(i + chunk_size, len(full_text))
        text = full_text[i:j]
        if text.strip():
            seg_pages = char_page_index[i:j]
            seg_pdf_pages = char_pdf_page[i:j]
            seg_printed = sorted({p for p in char_printed[i:j] if p})
            section = section_titles[seg_pages[0]] if seg_pages else None
            chunks.append(
                Chunk(
                    chunk_id=f"{source_filename}::{strategy_name}::prose::{len(chunks):04d}",
                    source_filename=source_filename,
                    chunk_type="prose",
                    text=text,
                    char_count=len(text),
                    page_index_range=(min(seg_pages), max(seg_pages)),
                    pdf_page_number_range=(min(seg_pdf_pages), max(seg_pdf_pages)),
                    printed_page_number_list=seg_printed,
                    section_title=section,
                    strategy_name=strategy_name,
                )
            )
        if j >= len(full_text):
            break
        i += step
    return chunks


STRATEGIES = [
    {"name": "fixed_baseline_600_100", "kind": "fixed", "chunk_size": 600, "overlap": 100},
    {"name": "structured_400_80", "kind": "structured", "chunk_size": 400, "overlap": 80},
    {"name": "structured_600_100", "kind": "structured", "chunk_size": 600, "overlap": 100},
    {"name": "structured_800_120", "kind": "structured", "chunk_size": 800, "overlap": 120},
]


def chunk_document(pages: list[PageParseResult], source_filename: str, strategy: dict) -> list[Chunk]:
    if strategy["kind"] == "fixed":
        return chunk_document_fixed_baseline(pages, source_filename, strategy["chunk_size"], strategy["overlap"], strategy["name"])
    return chunk_document_structured(pages, source_filename, strategy["chunk_size"], strategy["overlap"], strategy["name"])
