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

Flipped to opt-out instead: every message requires evidence UNLESS the
WHOLE message is nothing but a greeting / thanks. An earlier version of the
opt-out check used `lowered.startswith(opener)`, which a Codex review of
PR #70 correctly flagged as unsafe -- "Hi, 這份文件的結論是什麼？",
"你好，表 4 的數值是多少？", and even a bare word like "history" (prefix
"hi") all slipped through. The check below is a full decomposition instead:
the message is conversational ONLY if, after greeting phrases and
punctuation are stripped, every remaining token is itself a standalone
greeting token. Anything with a real question, a data/document/table/figure
reference, or any other leftover content is diagnostic.
"""

import re

# Multi-word ASCII greetings, stripped before the message is tokenised
# (they contain spaces we would otherwise split on). Longest first so a
# longer phrase wins over a shorter prefix of it.
_GREETING_PHRASES = (
    "thank you so much",
    "thank you very much",
    "thanks a lot",
    "thanks so much",
    "thank you",
    "good morning",
    "good afternoon",
    "good evening",
    "hey there",
    "hi there",
    "hello there",
)

# Single standalone greeting / thanks tokens (already lowercased,
# punctuation- and space-free). A message is only treated as conversational
# if EVERY leftover token is in this set.
_GREETING_TOKENS = frozenset(
    {
        "hello", "hi", "hey", "hiya", "heya", "yo",
        "thanks", "thankyou", "thx", "ty",
        "你好", "妳好", "您好", "嗨", "哈囉", "哈啰", "早安", "午安", "晚安",
        "謝謝", "謝謝你", "謝謝妳", "謝謝您", "多謝", "感謝", "感謝你", "感謝您", "感恩",
    }
)

# Any run of whitespace or ASCII / CJK punctuation is a token separator.
_SEPARATOR_PATTERN = re.compile(
    r"[\s,.!?;:~\-–—…'\"“”‘’*()\[\]{}<>/\\|，。！？、；：（）「」『』【】]+"
)


def looks_like_diagnostic_question(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        # An empty turn has nothing to answer and nothing to fabricate;
        # don't force it through the evidence guard.
        return False

    lowered = stripped.lower()
    for phrase in _GREETING_PHRASES:
        lowered = lowered.replace(phrase, " ")

    leftover_tokens = [tok for tok in _SEPARATOR_PATTERN.split(lowered) if tok]

    # Conversational only if nothing but greeting tokens remain. Note CJK
    # has no spaces, so "你好表4的數值" stays one non-greeting token -> a
    # message that mixes a greeting with a real question does NOT decompose
    # cleanly and is correctly classified diagnostic.
    return not all(tok in _GREETING_TOKENS for tok in leftover_tokens)


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
