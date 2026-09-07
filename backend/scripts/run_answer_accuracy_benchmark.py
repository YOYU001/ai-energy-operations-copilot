"""AI 最終生成回答的正確率量化評測（含 LLM-as-a-Judge）。

與 run_retrieval_benchmark.py 的差異：那支腳本只測「retrieval 撈到的候選 chunk
準不準」，這支腳本測的是「AI 走完整套 orchestration（檢索 -> tool call -> 生成）
之後，最終回答的文字內容對不對」-- 兩者是不同的評測對象，見
docs/NVIDIA_AI_EVALUATION_ROADMAP.md 第 5 節 Answer Accuracy vs Context Recall
的區分。

作法：
  1. 重用 spike/test_questions.json 裡 retrieval_eval_eligible=true 的題目。
  2. 對每一題，透過真實 HTTP API（POST /conversations、POST .../messages）走
     一次完整的 /assistant 對話流程，取得 AI 真正生成的最終回答文字 -- 不重寫
     一套生成邏輯，直接打真實 endpoint，跟前端做的事完全一樣。
  3. 用該題 expected_location 對應的 document_chunks 真實全文，當作 Judge
     評分的 ground truth 參考文字。
  4. 用 gpt-5.6-terra（跟生成答案的 gpt-4o-mini 是不同模型，避免自評偏誤）當
     裁判，輸出結構化 JSON 分數：correctness / groundedness / completeness
     （各 1-5 分）。

THIS SCRIPT MAKES REAL OpenAI API CALLS (chat generation once per question via
the running backend, plus one gpt-5.6-terra judge call per question) and
therefore has a real dollar cost. Do not run it without the user's explicit
go-ahead for that specific run.

Prerequisites:
  - the backend dev server must already be running:
      uvicorn app.main:app --reload --app-dir backend
  - OPENAI_API_KEY must be set (.env)
  - doc1/doc3/doc4 must already be ingested into the production documents/
    document_chunks tables (reuses ensure_documents_ingested from
    run_retrieval_benchmark.py -- will ingest them if missing, which itself
    costs embedding API calls the first time)

Run from the backend/ directory:
    cd backend && python -m scripts.run_answer_accuracy_benchmark
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from sqlalchemy import text as sql_text

load_dotenv()

from app.db import get_connection  # noqa: E402
from scripts.run_retrieval_benchmark import (  # noqa: E402
    DOC_ID_TO_FILENAME,
    _load_questions,
    ensure_documents_ingested,
)

BASE_URL = os.environ.get("BENCHMARK_API_BASE_URL", "http://localhost:8000")
JUDGE_MODEL = "gpt-5.6-terra"
# main.py's OVERALL_GENERATION_TIMEOUT_SECONDS caps the stream itself at 60s;
# _finalize_with_fallback then still needs time to write the terminal DB row
# (up to two retries) before the server emits its closing SSE frame, so the
# client-side read timeout must leave real headroom above the server's own
# cap, not equal it.
GENERATION_TIMEOUT_SECONDS = 90

JUDGE_SYSTEM_PROMPT = (
    "You are grading a RAG assistant's answer for an internal energy-operations "
    "knowledge base. You will be given a question, a ground-truth reference "
    "passage taken verbatim from the source document, and the assistant's "
    "actual answer. The answer follows a fixed seven-section structure: "
    "Confirmed facts / Finding, Evidence, Possible causes, General engineering "
    "background, Suggested actions / Next checks, Confidence, Citations. By "
    "design, only the first two sections (Confirmed facts / Finding and "
    "Evidence) are required to be strictly supported by the reference passage. "
    "The other sections are deliberately allowed to go beyond the reference: "
    "Possible causes are explicitly labeled hypotheses, General engineering "
    "background is general domain knowledge (not a specific claim about this "
    "document), and Suggested actions/Confidence/Citations are commentary, not "
    "factual claims. Score the assistant's answer on three dimensions, each on "
    "a 1-5 integer scale: correctness (does the answer's factual content match "
    "the reference), groundedness (is every claim in the Confirmed facts/"
    "Finding and Evidence sections specifically actually supported by the "
    "reference, as opposed to invented -- do NOT penalize groundedness for "
    "content in Possible causes/General engineering background/Suggested "
    "actions that goes beyond the reference, since that is expected there by "
    "design), and completeness (does the answer cover what the reference "
    "says, not just a fragment). Respond with the requested JSON schema only."
)

JUDGE_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "answer_judgement",
        "schema": {
            "type": "object",
            "properties": {
                "correctness": {"type": "integer", "minimum": 1, "maximum": 5},
                "groundedness": {"type": "integer", "minimum": 1, "maximum": 5},
                "completeness": {"type": "integer", "minimum": 1, "maximum": 5},
                "reasoning": {"type": "string"},
            },
            "required": ["correctness", "groundedness", "completeness", "reasoning"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def _fetch_ground_truth_text(
    conn, file_name: str, pdf_page_number: int, expected_content_keywords: list[str] | None = None
) -> str | None:
    """Return an active chunk's full content covering pdf_page_number in
    file_name's current active document, or None if no such chunk exists
    (e.g. the page number wasn't captured by any chunk boundary).

    A page can be covered by MULTIPLE active chunks -- dense tables (e.g.
    doc3's "表4. 系統超約事件紀錄") get split across several chunk
    boundaries that all still overlap the same pdf_page_number. An earlier
    version of this function ordered candidates by chunk_id (a content
    hash, unrelated to document order or relevance) and took the first one
    -- effectively a near-random pick among the candidates. This produced
    real, observed judge errors (TODO.md "mode 1/2" benchmark investigation,
    2026-08-26): for q06 ("2024年8月30日 ... 超約時段"), the judge was
    sometimes hand a different date's table chunk than the one the question
    asks about, and correctly reported it could not verify the answer --
    not because the answer was wrong, but because the ground truth itself
    was the wrong passage.

    Fix: when expected_content_keywords is given, prefer whichever
    same-page chunk actually contains all of them -- the keywords already
    exist in test_questions.json specifically to pin down the expected
    content, so reusing them here (rather than introducing a new field)
    disambiguates the same way a human checking "did I grab the right
    excerpt" would. Falls back to the old chunk_id-ordered pick if no
    candidate contains all keywords (e.g. questions with no keywords, or a
    keyword mismatch) -- same behavior as before this change for that
    case."""
    rows = conn.execute(
        sql_text(
            """
            SELECT c.content
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.file_name = :file_name
              AND d.status = 'ready'
              AND c.is_active = true
              AND :page BETWEEN c.pdf_page_number_start AND c.pdf_page_number_end
            ORDER BY c.chunk_id
            """
        ),
        {"file_name": file_name, "page": pdf_page_number},
    ).mappings().all()
    if not rows:
        return None
    if expected_content_keywords:
        for row in rows:
            if all(keyword in row["content"] for keyword in expected_content_keywords):
                return row["content"]
    return rows[0]["content"]


class GenerationNotCompleted(RuntimeError):
    """Raised when the assistant's final message status isn't 'completed'
    (e.g. 'failed' or 'aborted') -- its persisted content may be empty or a
    mid-sentence fragment left over from whatever interrupted generation,
    and must never be silently graded as if it were a real answer."""


def _generate_answer(client: httpx.Client, question: str) -> str:
    """Create a disposable conversation, post the question, drain the SSE
    stream to completion, then read back the persisted assistant content --
    simpler and more robust than parsing token deltas out of the stream,
    since the DB row is the single source of truth for final content
    (see main.py's generate() docstring: what streams and what persists are
    guaranteed identical -- note this guarantee is about the *content*
    matching, not about the content being a complete/successful answer, so
    status is checked separately below)."""
    conv = client.post("/conversations", json={"role_mode": None})
    conv.raise_for_status()
    conversation_id = conv.json()["id"]

    with client.stream(
        "POST", f"/conversations/{conversation_id}/messages", json={"content": question},
        timeout=GENERATION_TIMEOUT_SECONDS,
    ) as response:
        response.raise_for_status()
        for _ in response.iter_lines():
            pass  # drain to completion; final content is read from the DB below, not parsed here

    messages = client.get(f"/conversations/{conversation_id}/messages")
    messages.raise_for_status()
    assistant_messages = [m for m in messages.json() if m["role"] == "assistant" and m["is_active"]]
    if not assistant_messages:
        raise RuntimeError(f"conversation {conversation_id}: no active assistant message after generation")
    final = assistant_messages[-1]
    if final["status"] != "completed":
        raise GenerationNotCompleted(f"conversation {conversation_id}: assistant message status={final['status']!r}")
    return final["content"]


def _judge_answer(judge_client, question: str, ground_truth: str, answer: str) -> dict:
    response = judge_client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"Ground-truth reference passage:\n{ground_truth}\n\n"
                    f"Assistant's answer:\n{answer}"
                ),
            },
        ],
        response_format=JUDGE_RESPONSE_SCHEMA,
    )
    return json.loads(response.choices[0].message.content)


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set in environment (.env) -- refusing to proceed")

    from openai import OpenAI

    judge_client = OpenAI()
    questions = _load_questions()

    with get_connection() as conn:
        ensure_documents_ingested(conn)

    eligible = [q for q in questions if q.get("retrieval_eval_eligible") and q.get("expected_location")]
    skipped = [
        {"id": q["id"], "reason": q.get("eligibility_reason") or "no expected_location for ground truth lookup"}
        for q in questions
        if not (q.get("retrieval_eval_eligible") and q.get("expected_location"))
    ]

    results = {}
    with get_connection() as conn, httpx.Client(base_url=BASE_URL) as client:
        for q in eligible:
            file_name = DOC_ID_TO_FILENAME[q["source_document"]]
            pdf_page = q["expected_location"]["pdf_page_number"]

            ground_truth = _fetch_ground_truth_text(
                conn, file_name, pdf_page, q.get("expected_content_keywords")
            )
            if ground_truth is None:
                skipped.append({"id": q["id"], "reason": f"no active chunk covers {file_name} page {pdf_page}"})
                continue

            try:
                start = time.monotonic()
                answer = _generate_answer(client, q["question"])
                generation_seconds = time.monotonic() - start
                judgement = _judge_answer(judge_client, q["question"], ground_truth, answer)
            except (GenerationNotCompleted, httpx.HTTPError) as exc:
                # one question's failure (timeout, aborted/failed generation)
                # must not discard the real money already spent on every
                # other question this run -- record it as skipped and keep
                # going, rather than letting the exception propagate and
                # skip the report write at the end of main().
                skipped.append({"id": q["id"], "reason": str(exc)})
                continue

            results[q["id"]] = {
                "question": q["question"],
                "source_document": q["source_document"],
                "ground_truth": ground_truth,
                "answer": answer,
                "generation_seconds": round(generation_seconds, 2),
                "judgement": judgement,
            }
            print(f"{q['id']}: correctness={judgement['correctness']} groundedness={judgement['groundedness']} completeness={judgement['completeness']}")

    def _average(field: str) -> float | None:
        scores = [r["judgement"][field] for r in results.values()]
        return round(sum(scores) / len(scores), 2) if scores else None

    report = {
        "judge_model": JUDGE_MODEL,
        "generation_model": "gpt-4o-mini",
        "skipped_questions": skipped,
        "results": results,
        "averages": {
            "correctness": _average("correctness"),
            "groundedness": _average("groundedness"),
            "completeness": _average("completeness"),
        },
    }

    out_path = Path(__file__).resolve().parent / "answer_accuracy_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"graded={len(results)} skipped={len(skipped)}")
    print(f"averages={report['averages']}")
    print(f"Full report written to {out_path}")


if __name__ == "__main__":
    main()
