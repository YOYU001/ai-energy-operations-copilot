---
name: qa
description: 手動呼叫 qa subagent（見 .claude/agents/qa.md）實際執行測試與驗證，回報 pass/fail 與具體證據。用法："/qa [要驗證的範圍，例如某個檔案、某個 endpoint、或留空代表跑全部測試]"。
---

用 Agent 工具呼叫 `subagent_type: qa`，把使用者在 args 指定的驗證範圍傳給它；若使用者沒有指定範圍，預設請它跑 `pytest`（全部測試）並回報結果。

qa subagent 只負責跑測試與回報，**不會**修改程式碼。如果它回報測試失敗，把失敗詳情原封不動轉達給使用者，由母 agent（我）或使用者決定下一步要怎麼修，不要自己接手動手修改，除非使用者明確要求。

回報時一律使用繁體中文，符合 CLAUDE.md 的語言規則；並依 `docs/WORKFLOW_SHORT.md` 第 10 節規則，把驗證結果視為「修改後回報」的一部分。
