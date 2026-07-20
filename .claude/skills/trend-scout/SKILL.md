---
name: trend-scout
description: 手動呼叫 trend-scout subagent（見 .claude/agents/trend-scout.md）查詢業界在企業級 AI 助手／RAG／agent 架構上的最新做法，不限特定公司。用法："/trend-scout <想了解的主題，例如 chunking 策略、OCR 方案>"。
---

用 Agent 工具呼叫 `subagent_type: trend-scout`，把使用者在 args 提供的主題傳給它，並附上目前專案在這個主題上的既有做法（如果有的話，例如 `docs/RAG_SPIKE_PLAN.md` 裡記錄的決策），讓它能一併評估關聯性。

trend-scout 只負責觀察與回報，**不會**修改任何檔案，也不會替使用者做技術決策。等它回報後，把「結論／依據／與本專案的關聯性／未確認的部分」整理呈現給使用者，讓使用者自己決定要不要採用。

回報時一律使用繁體中文，符合 CLAUDE.md 的語言規則。
