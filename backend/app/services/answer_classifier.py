"""Step 12 Sub-step 3B: deterministic capability guard.

Per docs/step12_substep3_plan.md section 9, the closed tool registry alone
only constrains WHICH internal data the model can fetch -- it does nothing
to stop the model from answering a question directly from general training
knowledge without calling any tool. This module's job is to decide, before
the model is called, whether the current user message requires an
evidence-backed (tool-grounded) answer; app/main.py's generate() uses that
decision to reject a zero-tool-call answer to such a message (see the
capability-guard enforcement in generate()).

Originally an opt-in keyword list (only messages matching a diagnostic
keyword required evidence). Found in practice to have a real, non-edge-case
gap: plain document-lookup questions with no diagnostic-sounding wording
(e.g. "新進人員實習表中，實習人員與導師姓名分別是誰？") matched no
keyword, so the guard never fired and the model was free to fabricate a
plausible-looking answer with zero tool calls -- confirmed via a real
LLM-as-a-Judge run (see TODO.md, 2026-08-26) that scored several such
answers as fully invented.

Flipped to opt-out instead: every message requires evidence UNLESS it
matches the short conversational-opener allowlist below. This is still a
conservative heuristic, not an NLP intent classifier -- but the direction
of the remaining false-negative risk is now safe (a real diagnostic
question could in principle be misread as conversational only if it opens
with one of these exact greeting words as its very first token, which none
of the project's test questions do), rather than the previous direction
(any non-keyword-matching evidence-seeking question silently bypassing the
guard).
"""

import re

_CONVERSATIONAL_OPENERS = [
    "hello", "hi", "hey", "你好", "嗨", "哈囉",
    "thanks", "thank you", "謝謝", "感謝",
    "good morning", "good afternoon", "good evening", "早安", "午安", "晚安",
]
_CONVERSATIONAL_MAX_LENGTH = 40  # short greetings only; a long message starting with "hi" still needs evidence


def looks_like_diagnostic_question(content: str) -> bool:
    stripped = content.strip()
    if len(stripped) > _CONVERSATIONAL_MAX_LENGTH:
        return True
    lowered = stripped.lower()
    return not any(lowered.startswith(opener) for opener in _CONVERSATIONAL_OPENERS)


# A softer fix for this same confusion (rewording the get_dataset_timeseries/
# search_documents tool descriptions in tool_registry.py) was tried first and
# confirmed NOT to work via a real LLM-as-a-Judge rerun (TODO.md, 2026-08-26):
# gpt-4o-mini still called get_dataset_timeseries/get_dataset_summary with a
# guessed dataset_id for "表4"-style questions, pulling in unrelated live CSV
# rows and answering from those instead of the PDF. This regex-based detector
# lets app/main.py._build_provider_messages inject an explicit, per-turn
# system instruction only when the message actually contains a PDF table/
# figure reference, which is a much stronger signal than a static tool
# description the model apparently does not weigh heavily enough on its own.
_PDF_TABLE_OR_FIGURE_PATTERN = re.compile(r"(表|圖|table|figure)\s*\d+", re.IGNORECASE)


def looks_like_pdf_table_or_figure_reference(content: str) -> bool:
    return _PDF_TABLE_OR_FIGURE_PATTERN.search(content) is not None
