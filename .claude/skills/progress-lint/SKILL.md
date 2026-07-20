---
name: progress-lint
description: 檢查 PROGRESS.md 的 Completed 區塊是否有條目超過 CLAUDE.md「PROGRESS.md 撰寫規則」訂的 1–2 行門檻，列出需要精簡的項目與行號。用法："/progress-lint"。
---

執行 `python .claude/skills/progress-lint/scripts/lint_progress.py`（從 repo 根目錄執行）。

這支 script 會：
1. 讀取 `PROGRESS.md`，找到 `## Completed` 區塊。
2. 逐條檢查每個以 `- ` 開頭的項目，用「字數」和「是否有 `Details: docs/...` 指標」兩個訊號判斷是否過長（門檻：超過約 220 個字元，或明顯缺少指向 `docs/` 的細節連結卻寫了很多技術細節）。
3. 列出所有超標的項目（含行號與字數），並附上該行前 40 字預覽，方便快速定位。
4. 不會自動修改 `PROGRESS.md`——只回報，精簡動作由母 agent 或使用者決定怎麼改寫。

新增或修改 `PROGRESS.md` 的 Completed 項目後，建議跑一次這個 skill 做自我檢查，而不是單靠肉眼判斷「這樣算不算太長」。
