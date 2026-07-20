---
name: ocr-page-diagnose
description: 對指定 PDF 的每一頁跑現有的 text/near_empty/scanned/ocr_failed 四態分類器，列出每頁的分類結果與判斷依據（字元數、圖片覆蓋率），並對被判為 scanned 的頁面實際跑 OCR 驗證可讀性。對應 CLAUDE.md Gotchas「掃描頁判斷勿用單一門檻」——曾經誤判過近空白頁，這個 skill 讓你在正式 ingest 新文件前先檢查會不會重蹈覆轍。用法："/ocr-page-diagnose <PDF 路徑> [--ocr]"。
---

執行 `python .claude/skills/ocr-page-diagnose/scripts/diagnose_pages.py <PDF 路徑> [--ocr]`（從 repo 根目錄執行）。

這支 script 會：
1. 用 `spike.pdf_parser.parse_pdf_pages` 對每一頁分類，列出：頁碼、`page_status`（text/near_empty/scanned/ocr_failed）、字元數、圖片覆蓋率。
2. 特別標記出 `near_empty` 與 `scanned` 的頁面——這兩者的邊界就是 Sub-step 2 曾經誤判過的地方（近乎空白但合法的分隔頁 vs. 真正的掃描頁），列出來讓你肉眼複查。
3. 預設不跑 OCR（避免不必要的 easyocr 模型載入時間）。加上 `--ocr` 參數時，會對所有 `scanned` 頁面實際呼叫 `spike.ocr_fallback.ocr_page`，回報 OCR 後的字元數與是否被重新分類為 `ocr_failed`（代表 OCR 也讀不出東西）。
4. 最後印出總覽：幾頁 text、幾頁 near_empty、幾頁 scanned、幾頁 ocr_failed。

如果某一頁被分成 `near_empty` 但你人工檢查後發現其實是掃描內容遺漏（或反之），代表這份文件的版面跟現有 4 種文件不一樣，`IMAGE_COVERAGE_THRESHOLD`／`TEXT_LENGTH_THRESHOLD` 這兩個門檻（`spike/pdf_parser.py`）可能需要重新校準，不要直接改文件本身去遷就 heuristic。
