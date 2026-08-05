"""Step 12 Sub-step 3B: tests for the deterministic capability-guard
heuristic in app/services/answer_classifier.py. This is explicitly a
conservative keyword heuristic, not an NLP intent classifier -- this file
also documents (via an explicit, non-skipped test) a real known-limitation
false negative, so the heuristic's actual boundary is visible in the test
suite rather than hidden."""

import pytest

from app.services.answer_classifier import looks_like_diagnostic_question


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
    ],
)
def test_diagnostic_messages_are_classified_as_diagnostic(content):
    assert looks_like_diagnostic_question(content) is True


@pytest.mark.parametrize(
    "content",
    [
        "hello",
        "你好",
        "thanks, that helps",
        "謝謝",
        "good morning",
    ],
)
def test_conversational_messages_are_classified_as_conversational(content):
    assert looks_like_diagnostic_question(content) is False


def test_known_false_negative_documented_not_hidden():
    """A real diagnostic question phrased with none of the listed keywords
    slips through as conversational -- this is the accepted, documented
    heuristic boundary from docs/step12_substep3b_plan.md section 1, not a
    bug to fix here. Recorded as an explicit regression test so the
    boundary stays visible."""
    content = "It stopped working as expected around 2pm yesterday, can you look into it?"
    assert looks_like_diagnostic_question(content) is False
