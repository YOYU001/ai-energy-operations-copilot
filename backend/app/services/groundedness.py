"""Deterministic post-generation groundedness check (TODO.md bug 3,
2026-08-26): a "high-risk fact gate" that catches flagrant fabrication of
numbers/dates/percentages/names the model was never given, without an
extra LLM call on the request path (that tradeoff -- and why an always-on
LLM judge was rejected for the hot path -- is discussed in TODO.md; a real
LLM-as-a-Judge run confirmed this failure mode: the model called
search_documents, got the correct PDF chunk back, and still invented
timestamps/SOC percentages/kW values, and separately, person names, not
present anywhere in it).

This is explicitly NOT a correctness prover: it can only catch a claim that
is verbatim-absent from the evidence text (after light normalization), not
a legitimately-derived-but-wrong computation, nor a qualitative error (e.g.
misinterpreting what a negative value means). It is a floor, not a ceiling.
"""

from __future__ import annotations

import json
import re

# `(?<!\d)` before the optional `-` (TODO.md "mode 2" finding, 2026-08-28):
# without it, a hyphenated ID/filename like "2415-1304研究報告-智能貨櫃屋.pdf"
# -- which the model legitimately cites in its Evidence section -- gets
# split into TWO numeric claims, "2415" and "-1304", because "-1304" alone
# parses as a valid negative number. That second claim's leading "-" is
# then correctly recognized as adjacent to another digit (the "5" in
# "2415") by _claim_in_unit's digit-boundary check, and correctly-boundary-
# aware substring matching for "-1304" specifically fails to find it inside
# "2415-1304" for the same reason -- a real false positive that discarded
# an otherwise-correct answer citing its own source filename. The fix is at
# the source: a "-" immediately preceded by another digit is a hyphen
# separating two numbers/IDs, not a minus sign attached to the second one,
# so it should never have been captured as part of a numeric claim.
#
# The comma-group alternative (`\d{1,3}(?:,\d{3})+`), tried FIRST, is a
# separate fix (multi-agent failure-mode sweep, TODO.md 2026-08-28/31): the
# old pattern had no notion of a thousands separator, so "1,234" tokenized
# as two independent claims "1" (dropped as single-digit noise) and "234".
# _claim_in_unit then rejected "234" as a false positive: evidence
# normalization (_normalize) strips the comma, turning "1,234" into
# contiguous "1234", and "234" is a digit-adjacent substring of that longer
# number -- exactly the pattern the digit-boundary check exists to reject.
# Capturing "1,234" as ONE token instead means _normalize's comma-stripping
# produces the matching claim "1234" (the whole number), not a fragment of
# it. Comma-group must come first in the alternation so `finditer` prefers
# the longer match at each position instead of stopping at the plain
# `\d+` alternative.
_NUMERIC_CLAIM_PATTERN = re.compile(r"(?<!\d)-?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<!\d)-?\d+(?:\.\d+)?%?")


def extract_numeric_claims(text: str) -> list[str]:
    """Pull out number-like tokens worth checking -- percentages, decimals,
    and multi-digit integers. Bare single digits (e.g. Markdown list
    markers "1.", "2.") are skipped as noise: they're extremely common and
    essentially never the kind of fabricated fact this check exists to
    catch."""
    claims = []
    for match in _NUMERIC_CLAIM_PATTERN.finditer(text):
        token = match.group()
        digits_only = token.lstrip("-").rstrip("%").replace(".", "").replace(",", "")
        if len(digits_only) < 2 and "." not in token and "%" not in token:
            continue
        claims.append(token)
    return claims


# Chinese has no capitalization signal, so there is no cheap way to detect
# "this is a proper noun" the way English "starts with an uppercase letter"
# would. This is a heuristic, not NER.
#
# First version (2026-08-26) matched any common-surname character followed
# by 1-2 more Chinese characters, anywhere in the text. Real end-to-end
# testing (TODO.md "mode 1" finding, 2026-08-26) showed this false-
# positived heavily on ordinary words that happen to contain a surname
# character mid-word (e.g. "工程背景" -> "程背景", "高信心" -> "高信心"),
# discarding otherwise-correct answers. Requiring an explicit label
# immediately before the candidate (matching how this project's documents
# actually present names -- "姓名:劉宥羽", "導師姓名:廖健翔", table headers
# like "指導人員"/"組長"/"主任"/"承辦") removes nearly all of that false-
# positive surface. Trade-off, deliberately accepted: a name with no label
# adjacent to it (e.g. a bare table cell with no visible header in the
# flattened OCR text) will not be caught -- consistent with this whole
# module being "a floor, not a ceiling" (see module docstring): missing a
# fabrication is a smaller harm than discarding a correct answer.
_NAME_LABEL_KEYWORDS = "姓名|指導人員|導師|主管|組長|主任|承辦"
_NAME_CLAIM_PATTERN = re.compile(rf"(?:{_NAME_LABEL_KEYWORDS})(?:為)?[：:]\s*([一-鿿]{{2,4}})")


def extract_name_claims(text: str) -> list[str]:
    """Pull out candidate person names that immediately follow a name-ish
    label (see _NAME_LABEL_KEYWORDS) and a colon."""
    return _NAME_CLAIM_PATTERN.findall(text)


def _normalize(token: str) -> str:
    return token.rstrip("%").replace(",", "")


# Unit-equivalence for kW/W, kWh/Wh, kVA/VA (multi-agent failure-mode sweep,
# TODO.md 2026-08-28/31): this module has no unit awareness at all, so a
# genuinely correct answer stating "50 kW" against evidence that literally
# says "50000 W" (the same fact, different unit) was rejected as
# unsupported -- "50" is a digit-boundary-violating substring of "50000",
# so even the boundary-aware check in _claim_in_unit correctly refuses to
# match it. Scoped to the three unit pairs actually seen in this project's
# domain (battery/inverter specs); a general unit-conversion system is out
# of scope. Longer unit names ("kWh"/"Wh") must be tried before their
# shorter prefixes ("kW"/"W") in the alternation, or "50kWh" would be
# mis-parsed as "50kW" followed by a stray "h".
_KILO_SCALE = 1000
_UNIT_PAIRS = [("kWh", "Wh"), ("kW", "W"), ("kVA", "VA")]
_UNIT_CLAIM_PATTERN = re.compile(
    r"(?<!\d)(-?\d+(?:\.\d+)?)\s*(" + "|".join(re.escape(u) for pair in _UNIT_PAIRS for u in pair) + r")\b"
)


def _format_converted_value(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _unit_alternates(text: str) -> dict[str, str]:
    """Maps each claim value that is immediately followed by a recognized
    kilo/base unit in `text` to its unit-converted equivalent value (e.g.
    "50" -> "50000" for a "50 kW" occurrence), for find_unsupported_claims
    to also accept as evidence-supported."""
    alternates: dict[str, str] = {}
    for match in _UNIT_CLAIM_PATTERN.finditer(text):
        value_str, unit = match.group(1), match.group(2)
        value = float(value_str)
        for kilo_unit, base_unit in _UNIT_PAIRS:
            if unit == kilo_unit:
                alternates[_normalize(value_str)] = _format_converted_value(value * _KILO_SCALE)
                break
            if unit == base_unit:
                alternates[_normalize(value_str)] = _format_converted_value(value / _KILO_SCALE)
                break
    return alternates


# Chinese-style date claims (multi-agent failure-mode sweep, TODO.md
# 2026-08-28/31): a date like "114年09月22日" tokenizes into THREE
# independent numeric claims ("114", "09", "22") under the ordinary
# per-sentence co-location check, since "年"/"月"/"日" aren't digits and
# so break up _NUMERIC_CLAIM_PATTERN's matches. That check only requires
# each of the three to appear SOMEWHERE in the same evidence unit -- so a
# unit containing two different real dates (e.g. "114年01月22日" and
# "116年09月01日") could let a FABRICATED composite date slip through
# ("114年09月22日" isn't really in there, but 114/09/22 each individually
# are, just from different dates). Treating a matched date as ONE
# contiguous claim instead closes that gap: it must appear as a
# contiguous substring of the evidence (after zero-padding normalization,
# see _normalize_date_digits), not as three independently-located digit
# groups. This is checked BEFORE the ordinary per-sentence claim
# extraction, and the matched span is removed from the sentence
# afterward so its digits aren't ALSO independently re-checked.
_DATE_CLAIM_PATTERN = re.compile(r"(?<!\d)\d{2,4}年\d{1,2}月\d{1,2}日(?!\d)")


def _normalize_date_digits(text: str) -> str:
    """Strips leading zeros from every digit run so a zero-padding
    difference ("09月" in the answer vs "9月" in evidence, or vice versa)
    doesn't cause a false-positive mismatch on an otherwise-correct date."""
    return re.sub(r"\d+", lambda m: str(int(m.group())), text)


def _date_in_unit(date_str: str, unit: str) -> bool:
    return _normalize_date_digits(date_str) in _normalize_date_digits(unit)


# Chinese numeral claims (multi-agent failure-mode sweep, TODO.md
# 2026-08-28/31): _NUMERIC_CLAIM_PATTERN only matches Arabic digits, so a
# fabricated claim written as a Chinese number word ("兩百", "十二")
# completely bypasses this module -- not a false positive/negative on an
# existing check, a total silent gap. This project's documents are almost
# always Arabic-digit formatted (low real-world trigger frequency, per the
# failure-mode sweep's own finding), so this is deliberately conservative:
# these characters double as ordinary Chinese vocabulary (unlike Arabic
# digits, which are unambiguous), so an aggressive parser would flag
# correct prose as fabricated. Only multi-character spans are considered,
# and a small blocklist of common non-numeric words excludes the most
# obvious false-positive collisions -- not exhaustive; add to the
# blocklist if real use turns up more, rather than loosening the parser.
_CHINESE_DIGIT_VALUES = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CHINESE_UNIT_VALUES = {"十": 10, "百": 100, "千": 1000}
_CHINESE_SECTION_UNIT_VALUES = {"萬": 10_000, "億": 100_000_000}
_CHINESE_NUMERAL_CHARS = "".join(_CHINESE_DIGIT_VALUES) + "".join(_CHINESE_UNIT_VALUES) + "".join(
    _CHINESE_SECTION_UNIT_VALUES
)
_CHINESE_NUMERAL_SPAN_PATTERN = re.compile(f"[{_CHINESE_NUMERAL_CHARS}]{{2,}}")
_CHINESE_NUMERAL_BLOCKLIST = {"萬一", "千萬", "十分", "一定", "一般", "一起", "一直", "十足", "一切", "萬萬"}


def _parse_chinese_numeral(span: str) -> int | None:
    """Standard section-based Chinese-numeral-to-Arabic parse: 十/百/千
    accumulate within a "section", 萬/億 close out and multiply the
    section so far. Returns None if a unit character appears with no
    preceding value where one is structurally required in a way this
    simple left-to-right accumulator can't resolve -- not guessed at,
    consistent with the rest of this module preferring to miss a claim
    over inventing structure that isn't there."""
    total = 0
    section = 0
    number: int | None = None
    for ch in span:
        if ch in _CHINESE_DIGIT_VALUES:
            number = _CHINESE_DIGIT_VALUES[ch]
        elif ch in _CHINESE_UNIT_VALUES:
            section += (number if number is not None else 1) * _CHINESE_UNIT_VALUES[ch]
            number = None
        elif ch in _CHINESE_SECTION_UNIT_VALUES:
            total += (section + (number or 0)) * _CHINESE_SECTION_UNIT_VALUES[ch]
            section = 0
            number = None
    return total + section + (number or 0)


def extract_chinese_numeral_claims(text: str) -> list[str]:
    """Returns the ORIGINAL Chinese-numeral spans found in `text` (e.g.
    "十二", not "12") -- find_unsupported_claims reports the claim as the
    model actually wrote it, and separately looks up its Arabic-converted
    form via _chinese_numeral_alternates to check against evidence, the
    same alternates mechanism _unit_alternates already uses for kW/W."""
    claims = []
    for match in _CHINESE_NUMERAL_SPAN_PATTERN.finditer(text):
        span = match.group()
        if span in _CHINESE_NUMERAL_BLOCKLIST:
            continue
        value = _parse_chinese_numeral(span)
        if value:  # 0 and None (nothing parsed) are both not worth checking
            claims.append(span)
    return claims


def _chinese_numeral_alternates(text: str) -> dict[str, str]:
    alternates: dict[str, str] = {}
    for span in extract_chinese_numeral_claims(text):
        value = _parse_chinese_numeral(span)
        if value:
            alternates[span] = str(value)
    return alternates


def _claim_in_unit(claim: str, unit: str) -> bool:
    """Boundary-aware containment: True if `claim` appears in `unit` and is
    not merely a digit-substring of a DIFFERENT, longer number (e.g. "12"
    must not match inside "120"). Found while testing the per-chunk
    co-location fix (TODO.md "mode 2", 2026-08-27): plain `in` would defeat
    that fix -- a short claim like "12" (from "8-12顆") is a literal prefix
    of an unrelated number like "120" (from a different scenario's kWh
    figure) sitting in the very same wrong chunk, so without this check the
    wrong chunk would still "corroborate" every claim in the fabricated
    sentence via digit-substring coincidence alone. Not needed for name
    claims (Chinese characters have no adjacency false-positive of this
    kind), but harmless to apply there too since Han characters are never
    "digits"."""
    for match in re.finditer(re.escape(claim), unit):
        start, end = match.start(), match.end()
        before_is_digit = start > 0 and unit[start - 1].isdigit()
        after_is_digit = end < len(unit) and unit[end].isdigit()
        if not before_is_digit and not after_is_digit:
            return True
    return False


# Tolerant heading matching (multi-agent failure-mode sweep, TODO.md
# 2026-08-28/31): the original implementation matched the exact literal
# strings "## Confirmed facts / Finding" / "## Possible causes" / "## Citations".
# Any deviation the model might plausibly produce -- a wrong heading level
# ("### Possible causes"), a heading written in Chinese, extra/missing
# whitespace around the "/" -- made `str.find` return -1. Worse, when the
# START heading matched but the END heading didn't, the old fallback was
# "start to end-of-string", which pulls "Confidence"/"Suggested actions"
# (explicitly allowed to go beyond the evidence, e.g. a hedged percentage
# in Confidence) into the strictly-checked window, causing a well-grounded
# answer to be rejected as unsupported over content it was never supposed
# to be checked against evidence for in the first place.
#
# Matching by heading LINE (any "#" count, 1-6) instead of an exact string,
# and finding the end boundary as "the next heading that isn't itself an
# evidence-bound heading" (rather than one specific literal string), fixes
# both problems at once: heading-level/wording drift no longer breaks the
# match, and a missing/reworded end heading can never expand the window
# past the next real heading of any kind.
_HEADING_LINE_PATTERN = re.compile(r"^#{1,6}[ \t]*(.+?)[ \t]*$", re.MULTILINE)


def _heading_matches(heading_text: str, *keywords: str) -> bool:
    lowered = heading_text.lower()
    return all(keyword in lowered for keyword in keywords)


def _iter_headings(text: str) -> list[tuple[int, str]]:
    """Returns (start_index, heading_text) for every Markdown heading line
    in `text`, in order -- start_index is the position of the leading "#",
    usable directly as a slice boundary."""
    return [(m.start(), m.group(1)) for m in _HEADING_LINE_PATTERN.finditer(text)]


def _extract_evidence_restricted_text(answer_text: str) -> str:
    """Only "Confirmed facts / Finding" and "Evidence" are required by
    main.py's _SEVEN_PART_INSTRUCTION to come exclusively from tool
    results -- "Possible causes" is explicitly hypotheses, "General
    engineering background" is explicitly general knowledge, and
    "Confidence"/"Suggested actions" are meta commentary, not factual
    claims. "Citations" is evidence-bound too, but it is checked
    separately by _extract_citations_text -- see that function's docstring
    for why it can't share this same start/end window. Checking the full
    answer text against evidence let ordinary words in those later
    sections (e.g. "程度高", "高信心") get flagged as fabricated person
    names purely because they start with a common surname character -- a
    real false positive that discarded otherwise-correct answers (TODO.md
    "mode 1" finding, 2026-08-26). Restricting the check to the two
    evidence-bound sections removes that false-positive surface without
    weakening the check where it actually matters. Falls back to the full
    text if no heading matching "Confirmed facts"+"Finding" is found at all
    (e.g. a non-diagnostic answer) -- same behavior as before this change
    for that case."""
    headings = _iter_headings(answer_text)
    start_idx = next(
        (i for i, (_, text) in enumerate(headings) if _heading_matches(text, "confirmed facts", "finding")), None
    )
    if start_idx is None:
        return answer_text
    start = headings[start_idx][0]
    end = len(answer_text)
    for pos, text in headings[start_idx + 1 :]:
        if _heading_matches(text, "evidence"):
            continue  # still inside the evidence-bound window
        end = pos
        break
    return answer_text[start:end]


def _extract_citations_text(answer_text: str) -> str:
    """The multi-agent failure-mode sweep (TODO.md, 2026-08-28/31) found
    that "Citations" was the one seven-part section find_unsupported_claims
    never looked at: the model could write a page number or a document
    name that was never actually retrieved this turn, and nothing would
    catch it -- directly undermining the "every answer traceable to a
    verifiable internal source" principle (CLAUDE.md 資料與回答原則).
    Citations legitimately references document_id/file_name/page-number
    values that already exist verbatim in evidence_results (a
    search_documents chunk's own JSON fields), so the same claim-in-unit
    machinery used for Confirmed facts/Evidence applies unchanged here --
    no new NER-style name/file matching needed, since a real citation is
    just numbers (a page number, a document_id) or characters (a filename)
    that must co-locate with a real evidence chunk the same way any other
    claim does.

    A separate window, not folded into _extract_evidence_restricted_text,
    because Citations is the LAST heading in SEVEN_PART_HEADINGS -- there
    is no next heading to bound it, so it always runs to end-of-string,
    unlike the Finding/Evidence window which is bounded by the next
    non-Evidence heading on both sides."""
    headings = _iter_headings(answer_text)
    idx = next((i for i, (_, text) in enumerate(headings) if _heading_matches(text, "citations")), None)
    return answer_text[headings[idx][0] :] if idx is not None else ""


_SENTENCE_SPLIT_PATTERN = re.compile(r"[。\n]")


def _evidence_units(evidence_results: list[dict]) -> list[str]:
    """Splits evidence into independently-checkable units instead of one
    flattened blob (TODO.md "mode 2" finding, 2026-08-27): a real
    production case had two numbers that each individually exist
    *somewhere* in the evidence, but in DIFFERENT chunks describing
    DIFFERENT scenarios in the same PDF (a 144-module fixed installation's
    120kWh/60kW figures, not the 8-12-battery home scenario the question
    actually asked about) -- the old flattened-blob substring check passed
    both, because each merely had to exist anywhere at all.

    search_documents' each result item (one PDF chunk) is already a
    natural, meaningful unit -- serialized on its own instead of joined
    into the surrounding JSON array. Other tools' results (dataset
    summaries etc., not chunk-structured) are kept as one whole unit each,
    same as the old flattened behavior for those."""
    units = []
    for evidence in evidence_results:
        result = evidence["result"]
        chunk_list = result.get("results") if isinstance(result, dict) else None
        if isinstance(chunk_list, list):
            for item in chunk_list:
                units.append(json.dumps(item, ensure_ascii=False))
        else:
            units.append(json.dumps(result, ensure_ascii=False))
    return units


def find_unsupported_claims(answer_text: str, evidence_results: list[dict]) -> list[str]:
    """Returns the numeric and name claims from answer_text's Confirmed
    facts/Evidence/Citations sections that aren't jointly corroborated by a
    single evidence unit (see _evidence_units) -- the raw tool result
    gathered THIS turn (see generate()'s evidence_results, scoped per-call
    so a prior conversation turn's tool results can never be mistaken for
    this turn's evidence). Citations is checked via the same mechanism
    (see _extract_citations_text) so a page number or document reference
    that was never actually retrieved this turn gets rejected exactly like
    a fabricated fact would.

    Claims are checked per-sentence, not independently (TODO.md "mode 2"
    finding, 2026-08-27): every numeric/name claim within the same
    sentence must be found TOGETHER in one evidence unit for any of them
    to pass. A sentence combining a real number from one chunk with a
    different, unrelated number from another chunk is not actually
    grounded, even though each number independently "exists somewhere" --
    that combination is itself the fabrication (this is exactly the real
    case above: "8-12顆...120kWh...60kW" combines a real quantity from the
    correct chunk with a different chunk's unrelated figures). Deliberately
    conservative: a sentence mixing one fabricated claim with otherwise-
    correct ones now has ALL of its claims rejected, not just the
    fabricated one -- accepted trade-off, same "floor not ceiling" spirit
    as the rest of this module."""
    if not evidence_results:
        return []
    units = [_normalize(u) for u in _evidence_units(evidence_results)]
    citations_text = _extract_citations_text(answer_text)
    checked_text = _extract_evidence_restricted_text(answer_text)
    if citations_text:
        checked_text = f"{checked_text}\n{citations_text}"

    unsupported: list[str] = []
    for sentence in _SENTENCE_SPLIT_PATTERN.split(checked_text):
        # Date claims checked as one contiguous unit BEFORE the ordinary
        # independent-digit-group check (see _DATE_CLAIM_PATTERN's
        # docstring) -- the matched span is removed from the working copy
        # either way, so its digits are never ALSO independently
        # re-checked by the loop below.
        working_sentence = sentence
        for date_match in _DATE_CLAIM_PATTERN.finditer(sentence):
            date_str = date_match.group()
            if not any(_date_in_unit(date_str, unit) for unit in units):
                unsupported.append(date_str)
            working_sentence = working_sentence.replace(date_str, "", 1)

        claims = (
            extract_numeric_claims(working_sentence)
            + extract_name_claims(working_sentence)
            + extract_chinese_numeral_claims(working_sentence)
        )
        if not claims:
            continue
        normalized_claims = [_normalize(c) for c in claims]
        alternates = {**_unit_alternates(working_sentence), **_chinese_numeral_alternates(working_sentence)}

        def _corroborated(claim: str, unit: str) -> bool:
            if _claim_in_unit(claim, unit):
                return True
            alternate = alternates.get(claim)
            return alternate is not None and _claim_in_unit(alternate, unit)

        if any(all(_corroborated(c, unit) for c in normalized_claims) for unit in units):
            continue  # one evidence unit corroborates every claim in this sentence together
        unsupported.extend(claims)
    return unsupported
