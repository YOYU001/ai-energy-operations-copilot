# Skills 撰寫慣例

完整參考（所有 frontmatter 欄位、字串替換、skillOverrides、troubleshooting、eval 流程）見 `docs/SKILLS_AUTHORING.md`，只在真的要寫或改 skill 時讀。此檔只放每次都會用到的重點。

## 何時抽成 skill

當你一再貼上同一份劇本／檢查清單／多步驟流程，或 `CLAUDE.md`／某份 docs 的某段已從「事實」長成「程序」時，抽成 skill。skill 主體只在被叫用時才載入，長參考平時幾乎不佔 context。

## 基本結構

- 一個 skill = 一個目錄，進入點 `SKILL.md`（YAML frontmatter + markdown 主體）。目錄名就是 `/<name>` 指令。
- 本專案 skill 放 `.claude/skills/<name>/SKILL.md` 並 commit 進版控。
- frontmatter 全部可選，預設只寫 `description`：寫清楚「做什麼 + 什麼時候用」，Claude 靠它決定要不要自動載入；省略則取主體第一段。listing 裡 `description` + `when_to_use` 合計截斷到 1,536 字元，關鍵用途寫前面。

## 常用 frontmatter

- `disable-model-invocation: true`——只有使用者能 `/name` 叫用，Claude 不自動觸發，也不會被 subagent 預載或排程任務觸發。有副作用或要控制時機的流程（deploy、commit、送外部訊息）一律加。
- `user-invocable: false`——只有 Claude 能用，從 `/` 選單隱藏。純背景知識用。
- `allowed-tools`——skill 生效期間這些工具免許可提示（不縮小工具池，其餘工具仍照 `permissions` 設定）；checked-in 專案 skill 需先信任 workspace 才生效，信任 repo 前先看過專案 skill。
- `context: fork` + `agent: <type>`——在隔離 subagent 跑，看不到對話歷史；只對「有明確任務」的 skill 有意義，純參考型 fork 會空手而回。`Explore`／`Plan` agent 會跳過 CLAUDE.md 與 git status。
- `paths`——glob，限定只有動到符合的檔案時才自動啟用（格式同 path-specific rules）。
- `model` / `effort`——覆蓋當回合的模型／努力級別，不寫回設定。
- `argument-hint` / `arguments`——自動完成提示與具名位置引數。

## 主體撰寫

- 被叫用的 `SKILL.md` 以單一訊息進入對話並**整個 session 常駐**，Claude 不會再重讀檔案——把「整個任務都適用」的指引寫成常設規則，不要寫成一次性步驟。
- 每一行都是重複 token 成本，套用與 `CLAUDE.md` 同一套精簡標準：講「要做什麼」，不敘述「怎麼做／為什麼」。
- `SKILL.md` 控制在 500 行內；細節拆到同目錄 `reference.md`／`examples.md`／`scripts/`，並在主體註明各檔內容與載入時機（script 是被執行，不是被載入）。

## 動態 context 注入

- `` !`<command>` `` 在 skill 內容送給 Claude 之前先執行，輸出就地取代預留位置（前處理，不是 Claude 執行；只跑一次，輸出不再被掃描）。只在行首或空白後的 `!` 生效；多行用 ` ```! ` fenced block。
- 字串替換：`$ARGUMENTS`、`$ARGUMENTS[N]`／`$N`（shell 式引號，`"多字"` 算一個引數）、`$name`、`${CLAUDE_SKILL_DIR}`（引用捆綁 script 用它，不依賴 cwd）、`${CLAUDE_PROJECT_DIR}`、`${CLAUDE_SESSION_ID}`、`${CLAUDE_EFFORT}`。字面 `$1` 用 `\$1` 跳脫。
- 內容裡任意處放 `ultrathink` 可強制該次更深推理。

## 評估

看到 skill 觸發不代表輸出正確。分開驗兩件事——「該觸發的 prompt 有沒有觸發」「觸發時輸出對不對」——都用 baseline 對照：同一批真實 prompt 在乾淨 session 跑 skill 開／關兩次比較（乾淨 session 很重要，寫 skill 當下的殘留 context 會蓋掉說明的漏洞）。`skill-creator` plugin 可自動化這個迴圈。
