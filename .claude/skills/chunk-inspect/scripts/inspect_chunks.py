"""chunk-inspect: run all 4 chunking strategies (spike/chunker.py) against a
given PDF and report chunk count / size distribution / table detection, with
no database writes and no API calls -- safe to run against any new PDF before
deciding whether to actually ingest it.

Run from the project root:
    python .claude/skills/chunk-inspect/scripts/inspect_chunks.py <pdf_path>
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from spike.chunker import STRATEGIES, chunk_document  # noqa: E402
from spike.pdf_parser import parse_pdf_pages  # noqa: E402


def _char_stats(values: list[int]) -> str:
    if not values:
        return "n/a (0 chunks)"
    return f"min={min(values)}, max={max(values)}, avg={statistics.mean(values):.0f}"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python inspect_chunks.py <pdf_path>")
        return 1

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"[chunk-inspect] PDF not found: {pdf_path}")
        return 1

    print(f"[chunk-inspect] Parsing {pdf_path.name} ...")
    pages = parse_pdf_pages(str(pdf_path))
    print(f"[chunk-inspect] {len(pages)} pages parsed (text-layer only, no OCR).")

    for strategy in STRATEGIES:
        chunks = chunk_document(pages, pdf_path.name, strategy)
        prose_chunks = [c for c in chunks if c.chunk_type == "prose"]
        table_chunks = [c for c in chunks if c.chunk_type == "table"]

        print(f"\n=== {strategy['name']} (chunk_size={strategy['chunk_size']}, overlap={strategy.get('overlap', 0)}) ===")
        print(f"  total chunks: {len(chunks)}  (prose={len(prose_chunks)}, table={len(table_chunks)})")
        print(f"  prose char_count: {_char_stats([c.char_count for c in prose_chunks])}")
        print(f"  table char_count: {_char_stats([c.char_count for c in table_chunks])}")

        if table_chunks:
            titles = sorted({c.table_title for c in table_chunks if c.table_title})
            print(f"  table titles detected: {titles}")
        else:
            print("  table titles detected: none (all content fell back to prose)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
