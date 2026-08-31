"""Tests for app.services.groundedness (TODO.md bug 3, 2026-08-26)."""

from app.services.groundedness import (
    _parse_chinese_numeral,
    extract_chinese_numeral_claims,
    extract_name_claims,
    extract_numeric_claims,
    find_unsupported_claims,
)


def _search_documents_evidence(*chunk_contents: str) -> list[dict]:
    """Builds a realistic evidence_results entry matching what
    generate() actually gathers (TODO.md "mode 2", 2026-08-27):
    {"tool_name": ..., "result": {"results": [{"content": ...}, ...]}} --
    one dict per chunk_contents argument, each its own separate chunk."""
    return [
        {
            "tool_name": "search_documents",
            "result": {"results": [{"content": content} for content in chunk_contents]},
        }
    ]


def test_extract_numeric_claims_skips_bare_single_digits():
    claims = extract_numeric_claims("1. 第一項\n2. 第二項\n共 3 筆資料")
    assert claims == []


def test_extract_numeric_claims_keeps_multi_digit_percentages_and_decimals():
    claims = extract_numeric_claims("SOC 從 91.9% 變化到 89.9%，功率 -0.6 kW，共 24 筆")
    assert claims == ["91.9%", "89.9%", "-0.6", "24"]


def test_find_unsupported_claims_empty_when_no_evidence():
    assert find_unsupported_claims("SOC is 91.9%", []) == []


def test_find_unsupported_claims_flags_fabricated_numbers():
    evidence = _search_documents_evidence("SOC 從 91.9% 變化到 89.9%")
    unsupported = find_unsupported_claims("儲能 SOC 從 91.9% 變化到 89.9%，另外還有 42.5% 的異常值", evidence)
    # sentence-scoped (TODO.md "mode 2", 2026-08-27): 42.5% isn't in the evidence chunk, so the
    # WHOLE sentence's claims are rejected together, not just the fabricated one -- see
    # test_find_unsupported_claims_flags_only_the_sentence_containing_the_fabrication below for
    # the case where the real and fabricated claims are in separate sentences instead.
    assert unsupported == ["91.9%", "89.9%", "42.5%"]


def test_find_unsupported_claims_passes_when_all_numbers_appear_in_evidence():
    evidence = _search_documents_evidence("19:30~19:45 儲能 -0.6kW")
    unsupported = find_unsupported_claims("該時段儲能為 -0.6 kW", evidence)
    assert unsupported == []


def test_extract_name_claims_finds_surname_led_tokens():
    claims = extract_name_claims("實習人員姓名:劉宥羽 導師姓名:廖健翔")
    assert claims == ["劉宥羽", "廖健翔"]


def test_extract_name_claims_empty_when_no_surname_present():
    assert extract_name_claims("本場域使用的混合型變流器型號與額定功率是多少") == []


def test_find_unsupported_claims_flags_fabricated_names():
    evidence = _search_documents_evidence("實習人員姓名:劉宥羽 導師姓名:廖健翔")
    unsupported = find_unsupported_claims("實習人員姓名為：劉彥翎，導師姓名為：陳健練。", evidence)
    assert unsupported == ["劉彥翎", "陳健練"]


def test_find_unsupported_claims_passes_when_names_appear_in_evidence():
    evidence = _search_documents_evidence("實習人員姓名:劉宥羽 導師姓名:廖健翔")
    unsupported = find_unsupported_claims("實習人員為劉宥羽，導師為廖健翔。", evidence)
    assert unsupported == []


# ---------------------------------------------------------------------------
# Section-scoped checking (TODO.md "mode 1" finding, 2026-08-26): a real
# end-to-end test showed find_unsupported_claims flagging ordinary words in
# "Possible causes"/"Confidence" (e.g. "程度高", "高信心") as fabricated
# names, because those sections are allowed by design to contain non-
# evidence content (hypotheses, general commentary) -- the check must not
# apply there.
# ---------------------------------------------------------------------------


def _seven_part_answer(finding: str, possible_causes: str) -> str:
    return (
        f"## Confirmed facts / Finding\n{finding}\n\n"
        f"## Evidence\n（來自文件）\n\n"
        f"## Possible causes\n{possible_causes}\n\n"
        "## General engineering background\n（無）\n\n"
        "## Suggested actions / Next checks\n（無）\n\n"
        "## Confidence\n高信心\n\n"
        "## Citations\n（無）"
    )


def test_find_unsupported_claims_ignores_surname_like_words_outside_evidence_sections():
    evidence = _search_documents_evidence("實習人員姓名:劉宥羽 導師姓名:廖健翔")
    answer = _seven_part_answer(
        finding="實習人員為劉宥羽，導師為廖健翔。",
        possible_causes="程度高的實習可能需要許多工時投入，這是常見安排。",
    )
    assert find_unsupported_claims(answer, evidence) == []


def test_find_unsupported_claims_still_flags_fabrication_inside_finding_section():
    evidence = _search_documents_evidence("實習人員姓名:劉宥羽 導師姓名:廖健翔")
    answer = _seven_part_answer(
        finding="實習人員姓名為：劉彥翎，導師姓名為：陳健練。",
        possible_causes="程度高的實習可能需要許多工時投入。",
    )
    assert find_unsupported_claims(answer, evidence) == ["劉彥翎", "陳健練"]


def test_find_unsupported_claims_falls_back_to_full_text_without_seven_part_headings():
    evidence = _search_documents_evidence("SOC 從 91.9% 變化到 89.9%")
    unsupported = find_unsupported_claims("SOC 是 42.5%，沒有段落標題", evidence)
    assert unsupported == ["42.5%"]


# ---------------------------------------------------------------------------
# Per-chunk co-location (TODO.md "mode 2" core finding, 2026-08-27): a real
# production case had the model combine a real quantity from one chunk
# ("8-12顆退役Gogoro電池") with a different chunk's unrelated figures
# ("120kWh"/"60kW", actually describing a different 144-module scenario in
# the same PDF) into one sentence. Each number individually existed
# *somewhere* in the evidence, so the old flattened-blob substring check
# passed it -- but the two numbers were never stated together anywhere.
# ---------------------------------------------------------------------------


def test_find_unsupported_claims_flags_numbers_stitched_together_from_different_chunks():
    evidence = _search_documents_evidence(
        "以兩顆退役Gogoro電池、SOH約80%估算，實際可用能量範圍為1.4至1.6kWh",  # correct chunk
        "每櫃配置72顆Gogoro電池模組，共計144顆，總儲能容量超過120kWh，額定充放電功率可達60kW",  # different, unrelated chunk
    )
    answer = "若將Gogoro退役電池擴展至8至12顆以上，可形成的容量超過120kWh，並且能實現60kW的充電能力。"
    unsupported = find_unsupported_claims(answer, evidence)
    assert set(unsupported) == {"12", "120", "60"}


def test_find_unsupported_claims_passes_when_all_numbers_in_one_sentence_share_a_chunk():
    evidence = _search_documents_evidence(
        "以兩顆退役Gogoro電池、SOH約80%估算，實際可用能量範圍為1.4至1.6kWh",
        "每櫃配置72顆Gogoro電池模組，共計144顆，總儲能容量超過120kWh，額定充放電功率可達60kW",
    )
    answer = "以兩顆退役Gogoro電池估算，實際可用能量範圍為1.4至1.6kWh。"
    assert find_unsupported_claims(answer, evidence) == []


def test_find_unsupported_claims_flags_only_the_sentence_containing_the_fabrication():
    evidence = _search_documents_evidence("SOC 從 91.9% 變化到 89.9%")
    answer = "該時段SOC從91.9%變化到89.9%。另外還有42.5%的異常值。"
    unsupported = find_unsupported_claims(answer, evidence)
    assert unsupported == ["42.5%"]


# ---------------------------------------------------------------------------
# Hyphenated filename/ID numbers (TODO.md "mode 2" false-positive finding,
# 2026-08-28): "2415-1304研究報告-智能貨櫃屋.pdf" was being split into two
# numeric claims "2415" and "-1304", incorrectly discarding an otherwise-
# correct answer that legitimately cited its own source filename.
# ---------------------------------------------------------------------------


def test_extract_numeric_claims_splits_hyphenated_id_into_two_positive_numbers():
    claims = extract_numeric_claims("根據文件2415-1304研究報告-智能貨櫃屋.pdf")
    assert claims == ["2415", "1304"]


def test_extract_numeric_claims_still_keeps_a_genuine_negative_number():
    claims = extract_numeric_claims("該時段儲能為 -0.6 kW")
    assert claims == ["-0.6"]


def test_find_unsupported_claims_passes_when_answer_cites_its_own_source_filename():
    evidence = _search_documents_evidence(
        "額定功率為5 kW，切換時間小於4 ms（來源：2415-1304研究報告-智能貨櫃屋.pdf）"
    )
    answer = "額定功率為5 kW，切換時間小於4 ms，根據文件2415-1304研究報告-智能貨櫃屋.pdf。"
    assert find_unsupported_claims(answer, evidence) == []


# ---------------------------------------------------------------------------
# Citations section verification (multi-agent failure-mode sweep, TODO.md
# 2026-08-28/31): "Citations" was the one seven-part section this checker
# never looked at, so the model could cite a page number or document name
# never actually retrieved this turn and nothing would catch it.
# ---------------------------------------------------------------------------


def _search_documents_evidence_chunk(document_id: int, file_name: str, page: int, content: str) -> list[dict]:
    return [
        {
            "tool_name": "search_documents",
            "result": {
                "results": [
                    {
                        "document_id": document_id,
                        "file_name": file_name,
                        "chunk_id": 1,
                        "pdf_page_number_start": page,
                        "pdf_page_number_end": page,
                        "section_title": None,
                        "content": content,
                    }
                ]
            },
        }
    ]


def test_find_unsupported_claims_flags_a_citation_page_number_never_actually_retrieved():
    evidence = _search_documents_evidence_chunk(7, "2415-1305研究報告-太陽光發電預測.pdf", 12, "額定功率為5 kW")
    answer = (
        "## Confirmed facts / Finding\n額定功率為5 kW\n\n"
        "## Evidence\n（來自文件）\n\n"
        "## Possible causes\n（無）\n\n"
        "## General engineering background\n（無）\n\n"
        "## Suggested actions / Next checks\n（無）\n\n"
        "## Confidence\n高信心\n\n"
        "## Citations\n來源：2415-1305研究報告-太陽光發電預測.pdf 第37頁"
    )
    # page 37 was never retrieved this turn (only page 12 was) -- the whole
    # Citations sentence's claims must be rejected together, same
    # sentence-scoped rule as every other section.
    unsupported = find_unsupported_claims(answer, evidence)
    assert "37" in unsupported


def test_find_unsupported_claims_passes_when_citation_matches_retrieved_chunk():
    evidence = _search_documents_evidence_chunk(7, "2415-1305研究報告-太陽光發電預測.pdf", 12, "額定功率為5 kW")
    answer = (
        "## Confirmed facts / Finding\n額定功率為5 kW\n\n"
        "## Evidence\n（來自文件）\n\n"
        "## Possible causes\n（無）\n\n"
        "## General engineering background\n（無）\n\n"
        "## Suggested actions / Next checks\n（無）\n\n"
        "## Confidence\n高信心\n\n"
        "## Citations\n來源：2415-1305研究報告-太陽光發電預測.pdf 第12頁"
    )
    assert find_unsupported_claims(answer, evidence) == []


def test_find_unsupported_claims_ignores_empty_citations_placeholder():
    evidence = _search_documents_evidence_chunk(7, "2415-1305研究報告-太陽光發電預測.pdf", 12, "額定功率為5 kW")
    answer = (
        "## Confirmed facts / Finding\n額定功率為5 kW\n\n"
        "## Evidence\n（來自文件）\n\n"
        "## Possible causes\n（無）\n\n"
        "## General engineering background\n（無）\n\n"
        "## Suggested actions / Next checks\n（無）\n\n"
        "## Confidence\ninsufficient data\n\n"
        "## Citations\n（無）"
    )
    assert find_unsupported_claims(answer, evidence) == []


# ---------------------------------------------------------------------------
# Thousands-separator claims (multi-agent failure-mode sweep, TODO.md
# 2026-08-28/31): "1,234" used to tokenize into two independent claims "1"
# (dropped as noise) and "234", and "234" was then rejected by the
# digit-boundary check as a substring of the comma-stripped "1234" -- a
# correctly-cited number was flagged as fabricated.
# ---------------------------------------------------------------------------


def test_extract_numeric_claims_keeps_thousands_separated_number_as_one_token():
    claims = extract_numeric_claims("總建置成本約 1,234,567 元")
    assert claims == ["1,234,567"]


def test_find_unsupported_claims_passes_when_thousands_separated_number_matches_evidence():
    evidence = _search_documents_evidence("總建置成本約1234567元")
    unsupported = find_unsupported_claims("總建置成本約 1,234,567 元", evidence)
    assert unsupported == []


def test_find_unsupported_claims_flags_fabricated_thousands_separated_number():
    evidence = _search_documents_evidence("總建置成本約1234567元")
    unsupported = find_unsupported_claims("總建置成本約 9,999,999 元", evidence)
    assert unsupported == ["9,999,999"]


# ---------------------------------------------------------------------------
# kW/W unit-equivalence (multi-agent failure-mode sweep, TODO.md
# 2026-08-28/31): a correctly unit-converted answer ("50 kW" derived from
# evidence's "50000 W") was rejected as unsupported since this module had
# no unit awareness at all.
# ---------------------------------------------------------------------------


def test_find_unsupported_claims_passes_when_kw_answer_matches_w_evidence():
    evidence = _search_documents_evidence("額定功率為50000 W")
    unsupported = find_unsupported_claims("額定功率為50 kW", evidence)
    assert unsupported == []


def test_find_unsupported_claims_passes_when_w_answer_matches_kw_evidence():
    evidence = _search_documents_evidence("額定功率為50 kW")
    unsupported = find_unsupported_claims("額定功率為50000 W", evidence)
    assert unsupported == []


def test_find_unsupported_claims_passes_when_kwh_answer_matches_wh_evidence():
    evidence = _search_documents_evidence("可用電量為1500 Wh")
    unsupported = find_unsupported_claims("可用電量為1.5 kWh", evidence)
    assert unsupported == []


def test_find_unsupported_claims_still_flags_a_fabricated_kw_value():
    evidence = _search_documents_evidence("額定功率為50000 W")
    unsupported = find_unsupported_claims("額定功率為99 kW", evidence)
    assert unsupported == ["99"]


# ---------------------------------------------------------------------------
# Tolerant heading matching (multi-agent failure-mode sweep, TODO.md
# 2026-08-28/31): a wrong heading level or a reworded/missing end heading
# used to either break the section window entirely (falling back to
# checking the WHOLE answer, including "Confidence"/"Suggested actions"
# content that's explicitly allowed to go beyond the evidence) or leave it
# unbounded past where it should stop.
# ---------------------------------------------------------------------------


def test_find_unsupported_claims_tolerates_wrong_heading_level():
    evidence = _search_documents_evidence("SOC 從 91.9% 變化到 89.9%")
    answer = (
        "### Confirmed facts / Finding\nSOC 從 91.9% 變化到 89.9%\n\n"
        "### Evidence\n（來自文件）\n\n"
        "### Possible causes\n信心程度高，估計約 42.5% 的機率\n\n"
        "### General engineering background\n（無）\n\n"
        "### Suggested actions / Next checks\n（無）\n\n"
        "### Confidence\n高信心，估計 85%\n\n"
        "### Citations\n（無）"
    )
    # the fabricated-looking 42.5%/85% figures live in Possible
    # causes/Confidence, which must stay OUT of the checked window even
    # though every heading here uses "###" instead of "##".
    assert find_unsupported_claims(answer, evidence) == []


def test_find_unsupported_claims_stops_at_a_reworded_possible_causes_heading():
    evidence = _search_documents_evidence("SOC 從 91.9% 變化到 89.9%")
    answer = (
        "## Confirmed facts / Finding\nSOC 從 91.9% 變化到 89.9%\n\n"
        "## Evidence\n（來自文件）\n\n"
        "## 可能原因\n信心程度高，估計約 42.5% 的機率\n\n"
        "## General engineering background\n（無）\n\n"
        "## Suggested actions / Next checks\n（無）\n\n"
        "## Confidence\n高信心，估計 85%\n\n"
        "## Citations\n（無）"
    )
    # "## Possible causes" was reworded to "## 可能原因" -- the checker must
    # still stop there (the next non-Evidence heading), not fall through to
    # end-of-string and flag 42.5%/85% as unsupported.
    assert find_unsupported_claims(answer, evidence) == []


def test_find_unsupported_claims_still_flags_fabrication_with_wrong_heading_level():
    evidence = _search_documents_evidence("SOC 從 91.9% 變化到 89.9%")
    answer = (
        "### Confirmed facts / Finding\nSOC 從 42.5% 變化到 89.9%\n\n"
        "### Evidence\n（來自文件）\n\n"
        "### Possible causes\n（無）"
    )
    assert find_unsupported_claims(answer, evidence) == ["42.5%", "89.9%"]


# ---------------------------------------------------------------------------
# Chinese-style date claims: zero-padding tolerance + composite-date
# fabrication (multi-agent failure-mode sweep, TODO.md 2026-08-28/31). A
# date like "114年09月22日" used to tokenize into three INDEPENDENT numeric
# claims, which let (a) a zero-padding mismatch ("09月" vs "9月") false-
# positive, and (b) a fabricated date stitched from two different real
# dates in the same chunk false-negative through, since each digit group
# only had to exist somewhere in that chunk, not as one contiguous date.
# ---------------------------------------------------------------------------


def test_find_unsupported_claims_tolerates_zero_padding_difference_in_dates():
    evidence = _search_documents_evidence("實習起始日期為114年9月22日")
    unsupported = find_unsupported_claims("實習起始日期為114年09月22日", evidence)
    assert unsupported == []


def test_find_unsupported_claims_passes_a_genuine_date_cited_verbatim():
    evidence = _search_documents_evidence("實習起始日期為114年09月22日")
    unsupported = find_unsupported_claims("實習起始日期為114年09月22日", evidence)
    assert unsupported == []


def test_find_unsupported_claims_flags_a_composite_date_stitched_from_two_real_dates():
    # 114/01/22 and 116/09/01 are each real, but "114年09月22日" is not --
    # each digit group individually "exists somewhere" in this chunk, but
    # never together as one contiguous date.
    evidence = _search_documents_evidence("第一階段起始日期為114年01月22日，第二階段結束日期為116年09月01日")
    unsupported = find_unsupported_claims("實習起始日期為114年09月22日", evidence)
    assert unsupported == ["114年09月22日"]


# ---------------------------------------------------------------------------
# Chinese numeral claims (multi-agent failure-mode sweep, TODO.md
# 2026-08-28/31): _NUMERIC_CLAIM_PATTERN only matches Arabic digits, so a
# fabricated claim written as a Chinese number word ("兩百", "十二")
# previously bypassed this check entirely -- not a false positive/negative
# on an existing check, a total silent gap.
# ---------------------------------------------------------------------------


def test_parse_chinese_numeral_handles_common_forms():
    assert _parse_chinese_numeral("十二") == 12
    assert _parse_chinese_numeral("兩百") == 200
    assert _parse_chinese_numeral("三十六") == 36
    assert _parse_chinese_numeral("一百二十") == 120
    assert _parse_chinese_numeral("五千") == 5000
    assert _parse_chinese_numeral("兩萬三千") == 23000


def test_extract_chinese_numeral_claims_skips_blocklisted_common_words():
    text = "這個系統效果十分良好，萬一發生異常會自動停機"
    # bare _NUMERIC_CLAIM_PATTERN never touches these anyway (no Arabic
    # digits); this asserts the Chinese-numeral scanner specifically
    # doesn't misparse "十分"/"萬一" as numbers 10 and 10001 respectively.
    assert extract_numeric_claims(text) == []
    assert extract_chinese_numeral_claims(text) == []


def test_find_unsupported_claims_passes_a_chinese_numeral_claim_matching_evidence():
    evidence = _search_documents_evidence("可安裝退役電池十二顆")
    unsupported = find_unsupported_claims("可安裝退役電池十二顆", evidence)
    assert unsupported == []


def test_find_unsupported_claims_flags_a_fabricated_chinese_numeral_claim():
    evidence = _search_documents_evidence("可安裝退役電池十二顆")
    unsupported = find_unsupported_claims("可安裝退役電池兩百顆", evidence)
    assert unsupported == ["兩百"]


def test_find_unsupported_claims_matches_chinese_numeral_answer_against_arabic_evidence():
    # the model paraphrased evidence's Arabic "12" as the Chinese numeral
    # "十二" -- still a genuinely correct claim, must not be flagged.
    evidence = _search_documents_evidence("可安裝退役電池12顆")
    unsupported = find_unsupported_claims("可安裝退役電池十二顆", evidence)
    assert unsupported == []


# ---------------------------------------------------------------------------
# Codex CLI review findings (2026-08-31, second opinion before push): four
# real gaps found in the same-day implementation above, each fixed and
# regression-tested here before this code was pushed.
# ---------------------------------------------------------------------------


def test_find_unsupported_claims_flags_unit_conversion_against_wrong_dimension():
    # "50 kW" (power) must NOT be accepted just because the digits "50000"
    # happen to appear in evidence attached to a DIFFERENT unit ("Wh",
    # energy) -- these are different physical quantities, not a unit
    # conversion of the same fact.
    evidence = _search_documents_evidence("蓄電量為50000 Wh")
    unsupported = find_unsupported_claims("額定功率為50 kW", evidence)
    assert unsupported == ["50"]


def test_find_unsupported_claims_flags_date_stitched_with_an_unrelated_number_from_another_chunk():
    # the date is real (chunk A) and the number is real (chunk B), but
    # never stated TOGETHER anywhere -- the date must not be allowed to
    # corroborate independently of the rest of the sentence's claims.
    evidence = _search_documents_evidence(
        "於114年09月22日完成安裝",  # chunk A: real date, no capacity figure
        "系統容量為60kWh",  # chunk B: real capacity, different date context
    )
    answer = "於114年09月22日測得容量為60kWh。"
    unsupported = find_unsupported_claims(answer, evidence)
    assert set(unsupported) == {"114年09月22日", "60"}


def test_find_unsupported_claims_passes_date_and_number_stated_together_in_one_chunk():
    evidence = _search_documents_evidence("於114年09月22日測得容量為60kWh")
    unsupported = find_unsupported_claims("於114年09月22日測得容量為60kWh。", evidence)
    assert unsupported == []


def test_parse_chinese_numeral_sequential_digit_reading_is_not_extracted_as_a_claim():
    # "二〇二五" is a Chinese-style year (2,0,2,5 read one digit at a
    # time), not this project's accumulative counting-word grammar
    # ("十二", "兩百") -- extract_chinese_numeral_claims must not silently
    # misparse it as some other, unrelated small number.
    assert extract_chinese_numeral_claims("二〇二五年的資料") == []


def test_find_unsupported_claims_does_not_treat_unconfirmed_heading_as_the_evidence_bound_section():
    evidence = _search_documents_evidence("SOC 從 91.9% 變化到 89.9%")
    answer = (
        "## Unconfirmed facts / Finding\n這裡沒有標題匹配到的內容不該被當作證據約束段落\n\n"
        "## Possible causes\n42.5% 這種假設性數字不該被誤判成需要證據\n\n"
        "## Citations\n（無）"
    )
    # "Unconfirmed facts / Finding" must NOT match the "confirmed facts" +
    # "finding" keywords -- falls back to full-text scanning instead, so
    # the fabricated-looking "42.5%" (correctly, since there IS no real
    # seven-part structure here) still gets checked against evidence and
    # rejected, proving the heading wasn't silently misrecognized as a
    # scoped-out section.
    unsupported = find_unsupported_claims(answer, evidence)
    assert "42.5%" in unsupported
