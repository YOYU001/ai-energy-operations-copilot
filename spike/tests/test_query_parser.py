from spike.query_parser import DateCandidate, extract_date_candidates, looks_like_table_question


def test_extract_date_no_spaces():
    result = extract_date_candidates("表4中，2024年8月30日這天記錄了幾個超約時段？")
    assert result == [DateCandidate(2024, 8, 30)]


def test_extract_date_matches_irregular_pdf_extraction_spacing():
    # Real ingested table text from doc3 (see retrieval_smoke_test_report.json)
    # has irregular whitespace around 年/月/日, e.g. "2024 年8 月21 日".
    dc = DateCandidate(2024, 8, 21)
    chunk_text = "表4. 系統超約事件紀錄\n日期 時間 需量 (kW)\n2024 年8 月21 日\n10:45~11:00\n1.3"
    assert dc.match_regex().search(chunk_text) is not None


def test_extract_date_no_match_for_slash_format():
    result = extract_date_candidates("第一階段（2024/5–12）與第二階段（2025/1–12）的超約事件邏輯缺陷有何差異？")
    assert result == []


def test_extract_date_no_match_when_absent():
    assert extract_date_candidates("本場域使用的混合型變流器型號與額定功率是多少？") == []


def test_extract_multiple_dates():
    result = extract_date_candidates("比較2024年8月30日與2024年9月16日的超約事件")
    assert result == [DateCandidate(2024, 8, 30), DateCandidate(2024, 9, 16)]


def test_table_question_detected():
    assert looks_like_table_question("表4中，2024年8月30日這天記錄了幾個超約時段？") is True


def test_table_question_not_detected_for_plain_prose():
    assert looks_like_table_question("本場域使用的混合型變流器型號與額定功率是多少？") is False


def test_table_question_not_falsely_triggered_by_biao_without_digit():
    # "表格" (table/form, generic word) has no digit immediately following 表,
    # so it must NOT be treated as a "表<N>" table reference.
    assert looks_like_table_question("實習表中的表格總共列出幾個實習期間區段，天數分別是多少？") is False


def test_date_match_regex_does_not_match_different_day():
    dc = DateCandidate(2024, 8, 30)
    chunk_text = "2024 年8 月21 日\n10:45~11:00"
    assert dc.match_regex().search(chunk_text) is None
