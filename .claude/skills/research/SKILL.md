---
name: research
description: 手動呼叫 research subagent（見 .claude/agents/research.md）去查文件、程式碼或外部資料，並整理成摘要回報。用法："/research <你想查的問題或主題>"。
---

用 Agent 工具呼叫 `subagent_type: research`，把使用者在 args 提供的問題或主題當作 prompt 的核心內容傳給它，並附上足夠的背景（目前在做哪個 Step、為什麼需要查這個、應該去哪裡找）。

等 research subagent 回報後，直接把它的「結論／依據／未確認部分」整理呈現給使用者，不要自己重新做一次相同的搜尋。如果 research subagent 建議升級成 sonnet（見 `.claude/agents/research.md` 的規則），把這個建議明確轉達給使用者，讓使用者決定是否要重跑。

回報時一律使用繁體中文，符合 CLAUDE.md 的語言規則。
