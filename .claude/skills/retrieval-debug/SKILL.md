---
name: retrieval-debug
description: 對一個查詢字串跑 hybrid retrieval，印出每個候選 chunk 的完整文字（不截斷）與 semantic/date/table 各項加權分數拆解。對應 Sub-step 4 曾經因為只看 150 字 preview 誤判 q06「日期查錯」、Sub-step 5 才發現其實是誤讀的教訓——這個 skill 從一開始就印完整文字，避免重蹈覆轍。會呼叫 1 次真實 OpenAI embedding API（查詢本身），需要資料庫已有 ingest 過的 chunk 資料。用法："/retrieval-debug \"<查詢字串>\" [filename_filter] [top_k]"。
---

執行 `python .claude/skills/retrieval-debug/scripts/debug_retrieval.py "<查詢字串>" [filename_filter] [top_k]`（從 repo 根目錄執行）。

這支 script 會：
1. 用 `spike.embedding_provider.OpenAIEmbeddingProvider` 把查詢字串嵌入（1 次 API call，token 花費可忽略，比照 Sub-step 5/7 的實測成本）。
2. 用 `spike.hybrid_retrieval.fetch_candidates` 抓 top-30 候選池，分別跑「純向量排序」與「hybrid 加權排序」兩種結果。
3. 對每個候選 chunk 印出：**完整文字內容**（不像 preview 只給前 150 字）、`vector_distance`、`semantic_score`、`exact_date_match`、`table_query_match`、`final_score`，讓你可以肉眼確認排序是否合理，而不是只看一小段摘要就下結論。
4. 並排比較 vector-only 與 hybrid 的排名差異，標出哪些 chunk 因為 date/table bonus 而被拉到更前面。

`filename_filter` 可省略（跑全域 cross-document 查詢，比照 Sub-step 7 揭露的 16.4% 跨文件干擾情境）；`top_k` 預設 5。需要根目錄 `.env` 有 `DATABASE_URL` 與 `OPENAI_API_KEY`，且資料庫裡已經有 ingest 過的 chunk（先用 `db-bootstrap` 或既有的 `spike.run_embedding_ingestion` 準備好資料）。
