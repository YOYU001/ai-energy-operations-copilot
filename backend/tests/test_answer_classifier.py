"""Step 12 Sub-step 3B: tests for the deterministic capability-guard
heuristic in app/services/answer_classifier.py. Originally an opt-in
keyword list; flipped to opt-out (default True, conversational-only
allowlist for False) after a real LLM-as-a-Judge run (TODO.md, 2026-08-26)
found plain document-lookup questions with no diagnostic-sounding wording
were slipping through the old keyword list and getting fabricated
zero-tool-call answers.

The opt-out check was later tightened (Codex review of PR #70): a message
is conversational ONLY if the WHOLE message decomposes into greeting /
thanks tokens. A greeting followed by any real content -- a question, a
document/table/figure reference, even a bare word that merely starts with
"hi" like "history" -- is diagnostic. This file documents that boundary
the same way the old one did: via explicit, non-skipped tests."""

import pytest

from app.services.answer_classifier import looks_like_diagnostic_question, looks_like_pdf_table_or_figure_reference


@pytest.mark.parametrize(
    "content",
    [
        "為什麼 12 號電池今天沒有依排程放電？",
        "why did battery 12 not discharge on schedule?",
        "dataset 5 有沒有異常？",
        "案件 case-0001 的處理方式是什麼？",
        "這份文件裡有沒有提到過契約容量？",
        "what is the root cause of this anomaly?",
        "分析一下這個資料集",
        "estimate the cost impact of this schedule change",
        # regression cases: real questions the OLD keyword list missed
        # entirely (no diagnostic keyword present), confirmed via the
        # 2026-08-26 answer-accuracy benchmark to produce fabricated
        # zero-tool-call answers under the old opt-in behavior.
        "新進人員實習表中，實習人員與導師姓名分別是誰？",
        "表4中，2024年8月30日這天記錄了幾個超約時段？",
        "It stopped working as expected around 2pm yesterday, can you look into it?",
        # regression cases: Codex review of PR #70 -- the old
        # `startswith(opener)` allowlist waved these through because they
        # begin with a greeting token (or, for "history", a bare prefix of
        # one). A greeting attached to a real data/document question must
        # still require evidence.
        "Hi，這份文件的結論是什麼？",
        "你好，表 4 的數值是多少？",
        "hello, what is the contract capacity in this dataset?",
        "history of the battery system",  # bare word starting with "hi"
        "thanks, that helps -- now what does table 4 say?",
        # a bare acknowledgement with extra prose (not a pure "thanks") is
        # no longer on the allowlist: only a standalone greeting/thanks is.
        "thanks, that helps",
    ],
)
def test_diagnostic_messages_are_classified_as_diagnostic(content):
    assert looks_like_diagnostic_question(content) is True


@pytest.mark.parametrize(
    "content",
    [
        "hello",
        "Hi",
        "hi!",
        "Hey there",
        "你好",
        "謝謝",
        "謝謝你！",
        "thanks",
        "thank you",
        "thank you so much!",
        "good morning",
        "你好，謝謝",  # two greeting tokens, still nothing but greetings
        "  Hi there  ",
    ],
)
def test_conversational_messages_are_classified_as_conversational(content):
    assert looks_like_diagnostic_question(content) is False


def test_greeting_followed_by_a_real_question_still_requires_evidence():
    """A message that merely opens with a greeting is not safe to skip
    evidence for: only a message that is *nothing but* greeting/thanks
    tokens is conversational. "hi, why did battery 12 not discharge?"
    still needs evidence."""
    content = "hi, why did battery 12 not discharge on schedule yesterday afternoon around 3pm?"
    assert looks_like_diagnostic_question(content) is True


def test_empty_or_whitespace_message_is_not_diagnostic():
    """An empty turn has nothing to answer and nothing to fabricate."""
    assert looks_like_diagnostic_question("") is False
    assert looks_like_diagnostic_question("   \n  ") is False


# ---------------------------------------------------------------------------
# looks_like_pdf_table_or_figure_reference: a second, stronger fix for the
# "表4" vs dataset_id confusion (TODO.md, 2026-08-26). A softer fix -- just
# rewording the tool descriptions in tool_registry.py -- was tried first and
# confirmed via a real LLM-as-a-Judge rerun to NOT stop gpt-4o-mini from
# still guessing a dataset_id for these questions, hence this regex-based
# per-turn instruction injection (see app/main.py's _build_provider_messages).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "表4中，2024年8月30日這天記錄了幾個超約時段？",
        "表 3 的總表裡有列出哪些設備？",
        "圖2顯示的是什麼流程？",
        "What does Table 3 say about the inverter rating?",
        "please refer to figure 5 for the layout",
    ],
)
def test_pdf_table_or_figure_references_are_detected(content):
    assert looks_like_pdf_table_or_figure_reference(content) is True


@pytest.mark.parametrize(
    "content",
    [
        "新進人員實習表中，實習人員與導師姓名分別是誰？",
        "dataset 5 有沒有異常？",
        "為什麼電池沒有放電？",
        "hello",
    ],
)
def test_non_table_figure_messages_are_not_detected(content):
    assert looks_like_pdf_table_or_figure_reference(content) is False
