---
name: embed-cost-estimate
description: 在真正呼叫 OpenAI embedding API 之前，先估算某份 PDF 用指定 chunking 策略切分後，ingest 會花多少 token 與美金。純本地估算，不呼叫任何 API、不花任何錢。用法："/embed-cost-estimate <PDF 路徑> [strategy 名稱，預設 structured_600_100]"。
---

執行 `python .claude/skills/embed-cost-estimate/scripts/estimate_cost.py <PDF 路徑> [strategy_name]`（從 repo 根目錄執行）。

這支 script 會：
1. 用 `spike.pdf_parser.parse_pdf_pages` 解析 PDF、用 `spike.chunker.chunk_document` 切成 chunk（預設策略 `structured_600_100`，可用第二個參數指定其他 3 種策略之一）。
2. 累加所有 chunk 的字元數，用一個**校準過的字元／token 比例**估算 token 數（見下方「估算依據」）。
3. 用 OpenAI `text-embedding-3-small` 的公開定價（每 100 萬 token US$0.02）換算成美金。
4. 印出：chunk 數量、估算 token 數、估算美金成本，並明確標註「這是估算值，不是精確計算」。

## 估算依據

字元／token 比例（約 1.05 字元 ≈ 1 token）不是憑空假設，而是從 Sub-step 4 真實 ingest doc3 的資料反推校準：122 個 chunk 實際字元數與 OpenAI 回報的 `total_tokens=60836` 相除得出，適用於本專案中英文混合、以繁體中文為主的文件。若要更精確（例如逐字元用官方 tokenizer 計算），需要安裝 `tiktoken`——這不在目前依賴清單裡，依 CLAUDE.md 規則，安裝前必須先詢問使用者，因此這個 skill 預設不裝，只給估算值。如果估算值與之後真的 ingest 後的實際 `total_tokens` 落差明顯，回報給使用者，這代表校準比例可能需要更新。
