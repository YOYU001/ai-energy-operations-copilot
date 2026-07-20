---
name: chunk-inspect
description: 對指定的 PDF 檔案跑過 spike/chunker.py 現有的 4 種 chunking 策略（fixed_baseline_600_100、structured_400_80/600_100/800_120），回報每種策略切出的 chunk 數量、大小分布、table chunk 是否有正確保留 row group。用於評估新文件是否適合現有 chunking 邏輯，不會寫入資料庫或呼叫任何付費 API。用法："/chunk-inspect <PDF 路徑>"。
---

執行 `python .claude/skills/chunk-inspect/scripts/inspect_chunks.py <PDF 路徑>`（從 repo 根目錄執行，PDF 路徑可為相對或絕對路徑）。

這支 script 會：
1. 用 `spike.pdf_parser.parse_pdf_pages` 解析 PDF（純文字層，不做 OCR——若你需要先確認掃描頁分類，改用 `ocr-page-diagnose` skill）。
2. 對 `spike.chunker.STRATEGIES` 裡定義的 4 種策略各跑一次 `chunk_document`。
3. 每種策略回報：chunk 總數、prose/table chunk 各自數量、字元數的 min/max/平均、以及所有 table chunk 的標題列表（方便肉眼確認 table 有沒有被正確偵測到，還是全部退化成 prose）。
4. 純讀取、純記憶體運算，不寫資料庫、不呼叫 OpenAI API，可以放心對任何新文件先跑一次再決定要不要真的 ingest。

如果所有策略都回報 0 個 table chunk，但你知道這份文件裡有表格，代表 `chunker.py` 目前的表格偵測 heuristic（鎖定日期索引表或 `表N-M` caption-first 格式）沒有辨識出這份文件的表格格式，這是已知的 scope 限制，不是 bug——需要另外擴充偵測規則才能處理。
