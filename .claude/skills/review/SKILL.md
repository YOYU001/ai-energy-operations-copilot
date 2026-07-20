---
name: review
description: 手動呼叫 reviewer subagent（見 .claude/agents/reviewer.md）審查目前的 git diff 或指定檔案，找正確性問題與可簡化之處。用法："/review [檔案路徑，留空代表審查目前未 commit 的 git diff]"。
---

用 Agent 工具呼叫 `subagent_type: reviewer`。若使用者在 args 指定了檔案路徑，請 reviewer 針對那些檔案審查；若沒有指定，請它先跑 `git diff`（唯讀）取得目前未 commit 的變更範圍，再針對這個 diff 審查。

reviewer subagent 只審查、不修改檔案。收到它的 `Review Findings` 回報後，直接依原格式呈現給使用者，不要自己重新改寫或篩選內容；如果使用者要求依這些發現直接修正，才由母 agent（我）動手改，reviewer 本身不做修正。

回報時一律使用繁體中文，符合 CLAUDE.md 的語言規則；這個 skill 對應 `docs/WORKFLOW_SHORT.md`「Git / GitHub 快速規則」裡建議的 commit 前 review 步驟。
