"""embed-cost-estimate: estimate OpenAI embedding token/cost for a PDF's
chunks BEFORE actually calling the API. No network calls, no API key needed.

Token estimate is calibrated from Sub-step 4's real ingestion of doc3 (122
chunks, structured_600_100): actual chars / actual total_tokens reported by
OpenAI ~= 1.05 chars per token for this project's Chinese/English-mixed
corpus. This is an approximation, not an exact tokenizer count -- flagged
explicitly in the output.

Run from the project root:
    python .claude/skills/embed-cost-estimate/scripts/estimate_cost.py <pdf_path> [strategy_name]
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from spike.chunker import STRATEGIES, chunk_document  # noqa: E402
from spike.pdf_parser import parse_pdf_pages  # noqa: E402

# Calibrated against Sub-step 4's real ingestion report
# (spike/embedding_ingestion_report.json: doc3, 122 chunks, total_tokens=60836).
CHARS_PER_TOKEN_ESTIMATE = 1.05

# OpenAI text-embedding-3-small published pricing, USD per 1,000,000 tokens.
PRICE_PER_MILLION_TOKENS_USD = 0.02

DEFAULT_STRATEGY_NAME = "structured_600_100"


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("Usage: python estimate_cost.py <pdf_path> [strategy_name]")
        return 1

    pdf_path = Path(sys.argv[1])
    strategy_name = sys.argv[2] if len(sys.argv) == 3 else DEFAULT_STRATEGY_NAME

    if not pdf_path.exists():
        print(f"[embed-cost-estimate] PDF not found: {pdf_path}")
        return 1

    strategy = next((s for s in STRATEGIES if s["name"] == strategy_name), None)
    if strategy is None:
        valid = ", ".join(s["name"] for s in STRATEGIES)
        print(f"[embed-cost-estimate] Unknown strategy '{strategy_name}'. Valid options: {valid}")
        return 1

    print(f"[embed-cost-estimate] Parsing {pdf_path.name} and chunking with '{strategy_name}' ...")
    pages = parse_pdf_pages(str(pdf_path))
    chunks = chunk_document(pages, pdf_path.name, strategy)

    total_chars = sum(c.char_count for c in chunks)
    estimated_tokens = total_chars / CHARS_PER_TOKEN_ESTIMATE
    estimated_cost_usd = (estimated_tokens / 1_000_000) * PRICE_PER_MILLION_TOKENS_USD

    print(f"\n[embed-cost-estimate] chunks: {len(chunks)}")
    print(f"[embed-cost-estimate] total characters: {total_chars:,}")
    print(f"[embed-cost-estimate] ESTIMATED tokens: {estimated_tokens:,.0f}  (calibrated ratio, not an exact tokenizer count)")
    print(f"[embed-cost-estimate] ESTIMATED cost: US${estimated_cost_usd:.4f}  (text-embedding-3-small @ ${PRICE_PER_MILLION_TOKENS_USD}/1M tokens)")
    print(
        "\n[embed-cost-estimate] This is an approximation. If the real ingestion's reported "
        "total_tokens differs noticeably from this estimate, the calibration ratio may need updating."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
