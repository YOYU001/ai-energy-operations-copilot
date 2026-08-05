"""Step 12 Sub-step 3B: deterministic capability guard.

Per docs/step12_substep3_plan.md section 9, the closed tool registry alone
only constrains WHICH internal data the model can fetch -- it does nothing
to stop the model from answering a diagnostic/evidence-seeking question
directly from general training knowledge without calling any tool. This
module's job is to decide, before the model is called, whether the current
user message is diagnostic/evidence-seeking; app/main.py's generate()
uses that decision to reject a zero-tool-call answer to such a message
(see the capability-guard enforcement in generate()).

This is a conservative MVP keyword heuristic, not an NLP intent
classifier -- explicitly NOT a safety guarantee. It is deliberately biased
toward over-matching: a false positive (treating a conversational message
as diagnostic) is safe, just possibly unnecessary; a false negative (a
real diagnostic question with none of these terms slipping through as
conversational) is an accepted, documented tradeoff for MVP scope, not a
hidden gap -- see test_answer_classifier.py for an explicit example of the
boundary this leaves.
"""

from __future__ import annotations

_DIAGNOSTIC_KEYWORDS = [
    # Chinese
    "電池", "異常", "排程", "案件", "文件", "成本", "綠能", "契約容量",
    "資料集", "資料", "為什麼", "原因", "診斷", "分析", "放電", "充電",
    # English
    "battery", "anomaly", "schedule", "case", "document", "cost", "green",
    "dataset", "soc", "why", "diagnos", "analysis", "analyze", "discharge",
    "charge",
]


def looks_like_diagnostic_question(content: str) -> bool:
    lowered = content.lower()
    return any(keyword.lower() in lowered for keyword in _DIAGNOSTIC_KEYWORDS)
