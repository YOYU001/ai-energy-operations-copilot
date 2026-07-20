"""Tests for Step 6 Sub-step 3 chunking strategies.

Run from the project root: python -m pytest spike/tests -v
"""

from pathlib import Path

from spike.chunker import (
    MAX_ROW_GROUP_OVERSHOOT_RATIO,
    STRATEGIES,
    chunk_document,
    chunk_document_fixed_baseline,
    chunk_document_structured,
)
from spike.pdf_parser import PageParseResult, parse_pdf_pages

DOCS_DIR = Path(__file__).resolve().parents[2] / "data" / "spike_documents"
DOC3_LOW_CARBON = DOCS_DIR / "2415-1304研究報告-智能貨櫃屋 .pdf"
DOC4_BMS = DOCS_DIR / "A 完整版本  鋰電池二次利用之電池管理系統開發研究完成報告.pdf"


def _make_page(page_index: int, text: str, section_title=None) -> PageParseResult:
    return PageParseResult(
        page_index=page_index,
        pdf_page_number=page_index + 1,
        printed_page_number=str(page_index + 1),
        section_title=section_title,
        page_status="text",
        extraction_method="text_layer",
        text=text,
        char_count=len(text.strip()),
    )


def _synthetic_table_pages():
    """A small synthetic document mirroring 表4's actual one-cell-per-line
    extraction shape: intro paragraph ending in a colon, a multi-line
    unit-annotated header, several date-grouped row groups (including a
    6-row group for 2024/8/30 matching the real document, one value per
    line), then a trailing caption. Deliberately small so a tight
    chunk_size forces a real split decision to be tested.
    """
    page0_text = (
        " 這是介紹段落，說明系統的超約防護機制與相關背景資訊，內容足夠長以確保\n"
        "被視為獨立段落而不會被誤判為表格標題列，這裡先用一段夠長的文字結尾：\n"
        "日期\n時間\n需量 (kW)\n市電 (kW)\nPV (kW)\n儲能 (kW)\n儲能SOC (%)\n"
        "2024年8月21日\n"
        "08:45~09:00\n1.3\n1.1\n0.2\n0\n91\n"
        "09:00~09:15\n2.4\n2.2\n0.2\n0\n91\n"
        "09:15~09:30\n2.3\n1.5\n0.8\n0\n91\n"
        "2024年8月30日\n"
        "10:30~10:45\n1.7\n1.6\n0.2\n-0.1\n90.5\n"
        "10:45~11:00\n2.4\n2.2\n0.2\n0\n91\n"
        "11:00~11:15\n1.5\n1.3\n0.2\n0\n91\n"
        "14:00~14:15\n1.5\n1.3\n0.2\n0\n90\n"
        "14:15~14:30\n2.3\n2.1\n0.2\n0\n90\n"
        "14:30~14:45\n2.1\n1.5\n0.8\n-0.2\n90\n"
        "表4. 系統超約事件紀錄\n"
        " 接下來是分析段落，說明第一階段與第二階段的差異，內容同樣足夠長以確保\n"
        "被視為獨立的散文段落而不會與前面的表格內容混在一起。\n"
    )
    return [_make_page(0, page0_text, section_title="四、實驗結果 › 4.2.2 儲能系統調控邏輯驗證")]


def test_synthetic_table_8_30_row_group_atomic_when_within_overshoot_allowance():
    pages = _synthetic_table_pages()
    # chunk_size chosen so the 8/30 group's full text (~253 chars including
    # the repeated title+header prefix) is within the 20% overshoot
    # allowance (chunk_size * 1.2 >= 253), so it must stay a single unit.
    chunks = chunk_document_structured(pages, "synthetic.pdf", chunk_size=220, overlap=10, strategy_name="test_small")

    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert table_chunks, "expected at least one table chunk"

    chunks_containing_830 = [c for c in table_chunks if "2024年8月30日" in c.text]
    assert len(chunks_containing_830) == 1, "the 8/30 date label should appear in exactly one table chunk"

    target = chunks_containing_830[0]
    for row_time in ["10:30~10:45", "10:45~11:00", "11:00~11:15", "14:00~14:15", "14:15~14:30", "14:30~14:45"]:
        assert row_time in target.text, f"time-range {row_time!r} missing from the chunk containing the 8/30 date label"
    assert "-0.2" in target.text  # last row's distinctive value


def test_synthetic_table_8_30_row_group_splits_by_row_when_over_overshoot_allowance():
    pages = _synthetic_table_pages()
    # A small chunk_size that pushes the 8/30 group's solo length well past
    # its 120% allowance, so it must be split at physical-row boundaries
    # (never mid-row) rather than forced into one oversized chunk.
    chunks = chunk_document_structured(pages, "synthetic.pdf", chunk_size=80, overlap=10, strategy_name="test_small")

    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    chunks_containing_830 = [c for c in table_chunks if "2024年8月30日" in c.text]
    assert len(chunks_containing_830) >= 1

    for row_time, values in [
        ("10:30~10:45", "90.5"),
        ("10:45~11:00", "91"),
        ("11:00~11:15", "91"),
        ("14:00~14:15", "90"),
        ("14:15~14:30", "90"),
        ("14:30~14:45", "90"),
    ]:
        owners = [c for c in table_chunks if row_time in c.text]
        assert len(owners) == 1, f"row {row_time!r} should appear in exactly one chunk, found in {len(owners)}"
        assert values in owners[0].text, f"row {row_time!r}'s values missing from its own chunk"


def test_synthetic_table_chunks_repeat_title_and_header():
    pages = _synthetic_table_pages()
    chunks = chunk_document_structured(pages, "synthetic.pdf", chunk_size=80, overlap=10, strategy_name="test_small")
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) >= 1
    for c in table_chunks:
        assert c.table_title == "表4. 系統超約事件紀錄"
        assert "日期" in c.text and "需量 (kW)" in c.text


def test_fixed_baseline_respects_chunk_size():
    pages = _synthetic_table_pages()
    chunks = chunk_document_fixed_baseline(pages, "synthetic.pdf", chunk_size=100, overlap=20)
    assert len(chunks) > 1
    for c in chunks:
        assert c.char_count <= 100


def test_all_four_strategies_run_on_real_document_without_error():
    pages = parse_pdf_pages(str(DOC3_LOW_CARBON))
    for strategy in STRATEGIES:
        chunks = chunk_document(pages, DOC3_LOW_CARBON.name, strategy)
        assert len(chunks) > 0
        for c in chunks:
            assert c.page_index_range[0] <= c.page_index_range[1]
            assert c.pdf_page_number_range[0] == c.page_index_range[0] + 1
            assert c.pdf_page_number_range[1] == c.page_index_range[1] + 1
            assert c.char_count == len(c.text)


def test_real_table4_830_row_group_not_split_across_structured_strategies():
    pages = parse_pdf_pages(str(DOC3_LOW_CARBON))
    expected_time_ranges = ["10:30~10:45", "10:45~11:00", "11:00~11:15", "14:00~14:15", "14:15~14:30", "14:30~14:45"]
    for strategy in STRATEGIES:
        if strategy["kind"] != "structured":
            continue
        chunks = chunk_document(pages, DOC3_LOW_CARBON.name, strategy)
        candidates = [c for c in chunks if c.chunk_type == "table" and "2024 年8 月30 日" in c.text]
        assert len(candidates) == 1, f"strategy {strategy['name']}: expected exactly 1 chunk containing the 8/30 date label"
        target_text = candidates[0].text
        for row_time in expected_time_ranges:
            assert row_time in target_text, f"strategy {strategy['name']}: time-range {row_time!r} missing from the 8/30 chunk"
        assert "-0.2" in target_text
        assert "90.5" in target_text
        assert candidates[0].table_title == "表4. 系統超約事件紀錄"


def _make_oversized_group_page():
    """A single date with 20 physical rows (6 lines each = 120 lines), large
    enough that the whole row group alone exceeds 120% of a small
    chunk_size, forcing the row-level split path."""
    lines = [
        " 這是介紹段落，說明系統的超約防護機制與相關背景資訊，內容足夠長以確保\n",
        "被視為獨立段落而不會被誤判為表格標題列，這裡先用一段夠長的文字結尾：\n",
        "日期\n時間\n需量 (kW)\n市電 (kW)\nPV (kW)\n儲能 (kW)\n儲能SOC (%)\n",
        "2024年8月30日\n",
    ]
    for h in range(20):
        lines.append(f"{h:02d}:00~{h:02d}:15\n1.7\n1.6\n0.2\n-0.1\n90.5\n")
    lines.append("表4. 系統超約事件紀錄\n")
    lines.append(" 接下來是分析段落，內容同樣足夠長以確保被視為獨立的散文段落。\n")
    text = "".join(lines)
    return [_make_page(0, text, section_title="四、實驗結果 › 4.2.2 儲能系統調控邏輯驗證")]


def test_oversized_row_group_splits_by_complete_row_not_mid_row():
    pages = _make_oversized_group_page()
    chunk_size = 60  # deliberately tiny: the 20-row group alone is far over 120% of this
    chunks = chunk_document_structured(pages, "synthetic_big.pdf", chunk_size=chunk_size, overlap=0, strategy_name="test_oversized")

    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) > 1, "expected the oversized date group to be split across multiple table chunks"


# ---------------------------------------------------------------------------
# Step 6 Sub-step 8: doc4 "caption-first" table detection
# ---------------------------------------------------------------------------


def test_doc3_regression_unaffected_by_captionfirst_path():
    """Locks in the exact known-good doc3 table/prose counts from before
    Sub-step 8 (Sub-step 3/4's baseline). doc3 has no "表N-M" hyphen-format
    captions at all, so the caption-first path should never fire on it --
    this is the primary regression guard for that claim.
    """
    pages = parse_pdf_pages(str(DOC3_LOW_CARBON))
    expected = {
        "structured_400_80": {"prose": 178, "table": 5, "total": 183},
        "structured_600_100": {"prose": 119, "table": 3, "total": 122},
        "structured_800_120": {"prose": 91, "table": 2, "total": 93},
    }
    for strategy in STRATEGIES:
        if strategy["name"] not in expected:
            continue
        chunks = chunk_document(pages, DOC3_LOW_CARBON.name, strategy)
        prose = sum(1 for c in chunks if c.chunk_type == "prose")
        table = sum(1 for c in chunks if c.chunk_type == "table")
        exp = expected[strategy["name"]]
        assert (prose, table, len(chunks)) == (exp["prose"], exp["table"], exp["total"]), strategy["name"]


def _captionfirst_synthetic_pages():
    """Mirrors 表 3-1's real doc4 structure: caption-first (caption BEFORE
    the table, opposite of doc3's 表4), category-keyed rows (not dates),
    immediately followed by a figure caption.
    """
    text = (
        " 這是介紹段落，說明電池系統的組成方式，內容足夠長以確保被視為獨立段落\n"
        "而不會被誤判為表格標題列，這裡先用一段夠長的文字結尾：\n"
        "表 3-1 電池系統組成之電壓與容量\n"
        "規模\n組成\n(標稱)電壓\n容量\n"
        "電池組\n4 個25Ah 3.2V 電池並\n聯\n3.2V\n84Ah\n"
        "電池模組\n16 串電池組串聯\n48V\n84Ah\n"
        "電池系統\n5 組48V 電池模組進行\n並聯\n48V\n420Ah\n"
        "圖 3-1 電池組與電池管理系統示意圖\n"
        " 接下來是分析段落，內容同樣足夠長以確保被視為獨立的散文段落。\n"
    )
    return [_make_page(0, text, section_title="3.1 鋰電池模組充放電狀況")]


def test_captionfirst_table_detected_with_category_keyed_rows():
    pages = _captionfirst_synthetic_pages()
    chunks = chunk_document_structured(pages, "synthetic_doc4.pdf", chunk_size=600, overlap=100, strategy_name="test")
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) == 1
    t = table_chunks[0]
    assert t.table_title == "表 3-1 電池系統組成之電壓與容量"
    assert "規模" in t.text and "容量" in t.text  # header preserved
    assert "電池組" in t.text and "84Ah" in t.text  # at least one real data row
    assert "圖 3-1" not in t.text  # did not swallow the following figure caption


def _captionfirst_with_blank_line_pages():
    """Mirrors 表 3-2's real doc4 structure: a blank line between the
    caption and the first header cell, and ID-keyed columns (no dates, no
    unit-in-parens tokens at all).
    """
    text = (
        " 這是介紹段落，說明各電池串的充放電電壓量測結果，內容足夠長以確保被\n"
        "視為獨立段落而不會被誤判為表格標題列，這裡先用一段夠長的文字結尾：\n"
        "表 3-2 M01 模組V9-V16 電池串之充/放電最高與最低電壓\n"
        "\n"
        "V9\nV10\nV11\nV12\n"
        "最高\n電壓\n3.381\n3.387\n3.382\n3.594\n"
        "最低\n電壓\n3.252\n3.253\n3.253\n3.254\n"
        "圖 3-2 M01 電池模組充放電電壓對時間作圖\n"
        " 接下來是分析段落，內容同樣足夠長以確保被視為獨立的散文段落。\n"
    )
    return [_make_page(0, text, section_title="3.2 鋰電池失效分析試驗")]


def test_captionfirst_table_tolerates_blank_line_before_header():
    pages = _captionfirst_with_blank_line_pages()
    chunks = chunk_document_structured(pages, "synthetic_doc4b.pdf", chunk_size=600, overlap=100, strategy_name="test")
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) == 1, "a blank line between caption and header must not prevent detection"
    t = table_chunks[0]
    assert "V9" in t.text and "3.381" in t.text and "3.254" in t.text


def _toc_page_pages():
    """Mirrors doc4's real 表目錄 (table-of-contents) page: each entry is a
    single line with dot leaders and a trailing page number -- structurally
    similar to a real caption but must never be treated as a table region.
    """
    text = (
        "表目錄\n"
        "表 2-1 商業化陰極材料比較表 .................................................................................... 5\n"
        "表 3-1 電池系統組成之電壓與容量 .......................................................................... 15\n"
        "表 3-2 M01 模組V9-V16 電池串之充/放電最高與最低電壓 ................................. 16\n"
    )
    return [_make_page(0, text, section_title="目錄")]


def test_toc_page_produces_no_false_positive_table_chunks():
    pages = _toc_page_pages()
    chunks = chunk_document_structured(pages, "synthetic_toc.pdf", chunk_size=600, overlap=100, strategy_name="test")
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert table_chunks == [], "ToC entries (dot-leader lines) must never be detected as real tables"


def _cross_interference_pages():
    """A single synthetic document containing BOTH a doc3-style
    (DATE_LINE_RE-anchored, caption-after) table and a doc4-style
    (caption-first) table, to confirm the two detection paths coexist
    without interfering with each other.
    """
    text = (
        " 這是介紹段落一，說明超約事件的相關背景資訊，內容足夠長以確保被視為\n"
        "獨立段落而不會被誤判為表格標題列，這裡先用一段夠長的文字結尾：\n"
        "日期\n時間\n需量 (kW)\n市電 (kW)\nPV (kW)\n儲能 (kW)\n儲能SOC (%)\n"
        "2024年8月30日\n"
        "10:30~10:45\n1.7\n1.6\n0.2\n-0.1\n90.5\n"
        "10:45~11:00\n2.4\n2.2\n0.2\n0\n91\n"
        "表4. 系統超約事件紀錄\n"
        " 這是介紹段落二，說明電池系統的組成方式，內容足夠長以確保被視為獨立\n"
        "段落而不會被誤判為表格標題列，這裡先用一段夠長的文字結尾：\n"
        "表 3-1 電池系統組成之電壓與容量\n"
        "規模\n組成\n(標稱)電壓\n容量\n"
        "電池組\n4 個25Ah 3.2V 電池並\n聯\n3.2V\n84Ah\n"
        "圖 3-1 電池組與電池管理系統示意圖\n"
        " 接下來是分析段落，內容同樣足夠長以確保被視為獨立的散文段落。\n"
    )
    return [_make_page(0, text, section_title="mixed")]


def test_date_anchored_and_captionfirst_paths_coexist_without_interference():
    pages = _cross_interference_pages()
    chunks = chunk_document_structured(pages, "synthetic_mixed.pdf", chunk_size=600, overlap=100, strategy_name="test")
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) == 2
    titles = {c.table_title for c in table_chunks}
    assert titles == {"表4. 系統超約事件紀錄", "表 3-1 電池系統組成之電壓與容量"}
    doc3_style = next(c for c in table_chunks if c.table_title == "表4. 系統超約事件紀錄")
    doc4_style = next(c for c in table_chunks if c.table_title == "表 3-1 電池系統組成之電壓與容量")
    assert "2024年8月30日" in doc3_style.text
    assert "84Ah" in doc4_style.text
    # neither table's content leaked into the other's chunk
    assert "電池組" not in doc3_style.text
    assert "2024年8月30日" not in doc4_style.text


def test_captionfirst_table_exits_at_page_boundary():
    """A caption-first table with no other exit signal before the page ends
    must stop at the page boundary rather than bleed into the next page's
    unrelated content.
    """
    page0_text = (
        " 這是介紹段落，說明電池系統的組成方式，內容足夠長以確保被視為獨立段落\n"
        "而不會被誤判為表格標題列，這裡先用一段夠長的文字結尾：\n"
        "表 3-1 電池系統組成之電壓與容量\n"
        "規模\n組成\n(標稱)電壓\n容量\n"
        "電池組\n4 個25Ah 3.2V 電池並\n聯\n3.2V\n84Ah\n"
    )
    page1_text = "這是完全不相關的下一頁內容，不應該被併入前一頁的表格 chunk 之中。\n"
    pages = [
        _make_page(0, page0_text, section_title="3.1 鋰電池模組充放電狀況"),
        _make_page(1, page1_text, section_title="3.1 鋰電池模組充放電狀況"),
    ]
    chunks = chunk_document_structured(pages, "synthetic_pageboundary.pdf", chunk_size=600, overlap=100, strategy_name="test")
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) == 1
    assert "不相關的下一頁內容" not in table_chunks[0].text
    assert table_chunks[0].page_index_range == (0, 0)


def test_doc4_real_document_detects_four_target_tables():
    """Real-document acceptance test for the four originally-targeted doc4
    tables (see docs/RAG_SPIKE_PLAN.md Sub-step 8): each must be chunk_type
    "table", carry its complete table_title, include its header, and include
    at least one real data value -- read from the actual chunk text, not a
    preview.
    """
    pages = parse_pdf_pages(str(DOC4_BMS))
    strategy = next(s for s in STRATEGIES if s["name"] == "structured_600_100")
    chunks = chunk_document(pages, DOC4_BMS.name, strategy)
    table_chunks = {c.table_title: c for c in chunks if c.chunk_type == "table"}

    checks = {
        "表 3-1 電池系統組成之電壓與容量": ["規模", "容量", "電池組", "84Ah"],
        "表 3-2 M01 模組V9-V16 電池串之充/放電最高與最低電壓": ["V9", "V16", "3.381"],
        "表 3-3A、B 電池外觀尺寸量測值": ["長度", "(cm)", "A 電池", "7.08"],
        "表 4-1 不同種類電池用於梯次利用比較表": ["安全性", "LFP（鋰鐵）"],
    }
    for title, must_contain in checks.items():
        assert title in table_chunks, f"{title!r} was not detected as a table chunk"
        text = table_chunks[title].text
        for token in must_contain:
            assert token in text, f"{title!r} chunk is missing expected content {token!r}"


def test_doc4_toc_page_produces_no_table_chunks():
    """The real doc4 表目錄/圖目錄 page (page_index=15) must never itself
    produce a table chunk (its dot-leader ToC entries structurally resemble
    real captions but must be rejected)."""
    pages = parse_pdf_pages(str(DOC4_BMS))
    strategy = next(s for s in STRATEGIES if s["name"] == "structured_600_100")
    chunks = chunk_document(pages, DOC4_BMS.name, strategy)
    toc_page_tables = [c for c in chunks if c.chunk_type == "table" and c.page_index_range[0] == 15]
    assert toc_page_tables == []
