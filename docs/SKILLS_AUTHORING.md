# SKILLS_AUTHORING.md — Claude Code Skills 撰寫完整參考

濃縮自 Claude Code 官方 docs「使用 skills 擴展 Claude」。日常重點在 `.claude/rules/skills-authoring.md`（常駐載入）；這份是要寫或改 skill 時才查的完整版。官方索引：https://code.claude.com/docs/llms.txt

---

## 1. 概念

- Skill = 一個目錄，進入點 `SKILL.md`（YAML frontmatter + markdown 主體）。Claude 相關時自動載入，或使用者 `/skill-name` 手動叫用。
- 與 `CLAUDE.md` 不同：skill 主體只在被叫用時載入，長參考在需要前幾乎不花 context。`description` 則常駐（讓 Claude 知道有這個 skill 可用）。
- 何時建立：一再貼上同一份劇本／檢查清單／多步驟程序時；或 `CLAUDE.md` 某段從「事實」長成「程序」時。
- 自訂命令已併入 skills：`.claude/commands/deploy.md` 與 `.claude/skills/deploy/SKILL.md` 都產生 `/deploy`，行為相同；同名時 skill 優先。舊 `.claude/commands/` 檔案仍可用。
- 遵循 Agent Skills 開放標準（agentskills.io），Claude Code 另加：叫用控制、subagent 執行、動態 context 注入。

## 2. 位置與優先序

| 層級 | 路徑 | 適用 |
|---|---|---|
| 企業 | 見 managed settings | 組織所有人 |
| 個人 | `~/.claude/skills/<name>/SKILL.md` | 你所有專案 |
| 專案 | `.claude/skills/<name>/SKILL.md` | 僅此專案（commit 進版控） |
| 外掛 | `<plugin>/skills/<name>/SKILL.md` | 啟用外掛處，命名空間 `plugin:skill` |

- 同名優先序：企業 > 個人 > 專案；任一層同名也會覆蓋 bundled skill（例：專案 `.claude/skills/code-review/` 取代內建 `/code-review`）。外掛 skill 用 `plugin-name:skill-name` 命名空間，不會衝突。
- **父目錄自動發現**：從起始目錄往上到 repo root 每層 `.claude/skills/` 都載入，所以在子目錄啟動 Claude 仍抓得到 root 的 skill。
- **巢狀目錄按需載入**（monorepo）：Claude 讀／改子目錄檔案時，該子目錄 `.claude/skills/` 才變可用。與其他 skill 同名時兩者都保留，巢狀的以目錄限定名出現（`apps/web:deploy`）；叫用未限定名會載入 root 版並附上限定變體清單。需 v2.1.203+。
- **`--add-dir` / `/add-dir`**：例外地會自動載入其 `.claude/skills/`（`settings.json` 的 `permissions.additionalDirectories` 不會）。其他 `.claude/` 設定不從 add-dir 載入。
- **即時變更偵測**：`~/.claude/skills/`、專案 `.claude/skills/`、`--add-dir` 內的 `.claude/skills/` 新增／編輯／移除 `SKILL.md` 文字，當前 session 即生效免重啟。新建「頂層」skills 目錄才需重啟。也是 plugin 的 skill 資料夾，其 `hooks/`、`.mcp.json`、`agents/`、`output-styles/` 變更要 `/reload-plugins`。
- symlink：`<skill-name>` 項目可 symlink 到別處目錄，Claude Code 會跟隨；同一 target 從多處可達只載入一次。
- 加 `.claude-plugin/plugin.json` 到 skill 資料夾 → 載入為 plugin `<name>@skills-dir`，可捆綁 agents／hooks／MCP（專案 `.claude/skills/` 內需先過 workspace trust 對話）。

## 3. Frontmatter 欄位（全部可選，建議只寫 `description`）

| 欄位 | 說明 |
|---|---|
| `name` | skill 清單顯示名。預設目錄名。**不改變 `/` 後輸入的指令**（唯一例外：外掛根目錄 `SKILL.md`）。 |
| `description` | 做什麼 + 何時用。Claude 據此決定自動載入。省略則用主體第一段。 |
| `when_to_use` | 額外觸發脈絡（觸發短語、範例請求）。附加到 listing 的 `description` 後。 |
| `argument-hint` | 自動完成提示，如 `[issue-number]`、`[filename] [format]`。 |
| `arguments` | 具名位置引數，供主體 `$name` 替換。空格分隔字串或 YAML 清單，依序對應位置。 |
| `disable-model-invocation` | `true` = 只有使用者能叫用；防止自動載入、subagent 預載、以該 skill 為 prompt 的排程任務觸發。用於有副作用的流程。預設 `false`。 |
| `user-invocable` | `false` = 只有 Claude 能叫用，從 `/` 選單隱藏。用於背景知識。預設 `true`。 |
| `allowed-tools` | skill 生效期間免許可提示的工具（**不縮小**工具池，其餘工具仍照 `permissions`）。空格／逗號分隔或 YAML 清單。 |
| `disallowed-tools` | skill 生效期間從工具池移除的工具（如自主背景迴圈移除 `AskUserQuestion`）。下一則使用者訊息時解除。 |
| `model` | skill 生效期間的模型，覆蓋當回合、不寫回設定，下個 prompt 恢復。接受 `/model` 值或 `inherit`。被組織 `availableModels` 排除的值不採用。 |
| `effort` | `low`/`medium`/`high`/`xhigh`/`max`，覆蓋 session 努力級別。 |
| `context` | `fork` = 在分叉 subagent context 執行。 |
| `agent` | `context: fork` 時的 subagent 類型（`Explore`/`Plan`/`general-purpose` 或自訂）。預設 `general-purpose`。 |
| `hooks` | 限定此 skill 生命週期的 hooks。 |
| `paths` | glob，限定只有動到符合檔案時才自動啟用。逗號分隔或 YAML 清單，格式同 path-specific rules。 |
| `shell` | `bash`（預設）或 `powershell`，用於 `` !`cmd` `` 區塊。powershell 需 `CLAUDE_CODE_USE_POWERSHELL_TOOL=1`。 |

## 4. 叫用控制矩陣

| Frontmatter | 使用者可叫用 | Claude 可叫用 | context 載入 |
|---|---|---|---|
| （預設） | 是 | 是 | description 常駐；叫用時載入完整 skill |
| `disable-model-invocation: true` | 是 | 否 | description **不**常駐；使用者叫用時載入完整 skill |
| `user-invocable: false` | 否 | 是 | description 常駐；叫用時載入完整 skill |

subagent 預載 skill 時行為不同：完整內容在啟動時就注入。

## 5. 命令名稱來源

| Skill 位置 | 命令名來自 | 範例 |
|---|---|---|
| `~/.claude/skills/` 或 `.claude/skills/` 下目錄 | 目錄名 | `deploy-staging/SKILL.md` → `/deploy-staging` |
| 巢狀 `.claude/skills/`（與他人同名時） | 相對 cwd 的子目錄路徑 + 目錄名 | `apps/web/.claude/skills/deploy/` → `/apps/web:deploy` |
| `.claude/commands/` 下檔案 | 檔名（去副檔名） | `deploy.md` → `/deploy` |
| 外掛 `skills/` 子目錄 | 目錄名，加外掛命名空間 | `my-plugin/skills/review/` → `/my-plugin:review` |
| 外掛根目錄 `SKILL.md` | frontmatter `name`（後備：外掛目錄名） | `name: review` → `/my-plugin:review` |

## 6. 字串替換

| 變數 | 說明 |
|---|---|
| `$ARGUMENTS` | 所有引數。若主體沒有 `$ARGUMENTS`，引數改附加為 `ARGUMENTS: <value>`。 |
| `$ARGUMENTS[N]` / `$N` | 0-based 位置引數。shell 式引號，`"hello world" second` → `$0`=`hello world`、`$1`=`second`。 |
| `$name` | `arguments` frontmatter 宣告的具名引數，依序對應位置。 |
| `${CLAUDE_SESSION_ID}` | 當前 session ID。 |
| `${CLAUDE_EFFORT}` | 當前努力級別（ultracode 回報為 `xhigh`）。 |
| `${CLAUDE_SKILL_DIR}` | 含 `SKILL.md` 的目錄。引用捆綁 script／檔案用它，不依賴 cwd。外掛 skill 指向該 skill 子目錄，非外掛根。 |
| `${CLAUDE_PROJECT_DIR}` | 專案根目錄（v2.1.196+）。主體與 `allowed-tools` 都可用。 |

- 字面 `$`（如散文中 `$1.00`）用反斜線跳脫：`\$1.00`。`\\$1` 保留兩反斜線且 `$1` 仍展開。
- `/code-review /fix-issue 123` 可堆疊 skill：載入兩者，尾字 `123` 作 `$ARGUMENTS` 傳給各 skill（v2.1.199+）。展開第一個 + 最多後續 5 個，遇到第一個「非 inline user-invocable skill」的 token 就停（fork skill、或引數以斜線命令開頭者如 `/loop` 也在此止），該 token 起全部成為引數文字。

## 7. 動態 context 注入

- `` !`<command>` `` 在 skill 內容送給 Claude 之前先執行，輸出就地取代預留位置。是**前處理**，Claude 只看到最終結果。對原始檔跑一次，輸出以純文字插入、不再被掃描（命令無法產生給後續 pass 展開的預留位置）。
- inline 形式只在 `!` 位於行首或緊接空白後才被辨識；`KEY=!`cmd`` 會保留字面、不執行。
- 多行命令用 ` ```! ` 開啟的 fenced block（非 inline 形式）。
- 停用（使用者／專案／外掛／add-dir 來源）：settings `"disableSkillShellExecution": true`，每個命令替換為 `[shell command execution disabled by policy]`。bundled／managed skill 不受影響。managed settings 設定最有效。
- 主體任意處放 `ultrathink` 可要求該次更深推理。

## 8. 支援檔案

```
my-skill/
├── SKILL.md        # 主要說明（必需）
├── reference.md    # 詳細 API，需要時才載入
├── examples.md     # 範例輸出
└── scripts/helper.py  # 被執行，不是被載入
```

- 從 `SKILL.md` 明確參考各檔並說明內容與載入時機。`SKILL.md` 保持 500 行內，細節移到獨立檔。
- 一個 pattern：捆綁任意語言 script 產生視覺輸出（互動 HTML：依賴圖、覆蓋率報告、schema 視覺化），`allowed-tools` 開對應執行權，script 路徑用 `${CLAUDE_SKILL_DIR}`。

## 9. 內容生命週期（撰寫時最關鍵）

- 被叫用的 `SKILL.md` 以單一訊息進入對話，**整個 session 常駐**；Claude 不會在後續回合重讀檔案。→ 把「整個任務適用」的指引寫成常設說明，不要寫成一次性步驟。
- 重新叫用且 render 內容與已在 context 的副本相同 → 只加一句「已載入」註記，不重複整份（v2.1.202+；之前每次重新叫用都附整份）。內容不同（引數變／動態輸出變）→ 附完整內容。
- 每一行都是常駐 token 成本。講「要做什麼」，不敘述「怎麼做／為什麼」，套用與 `CLAUDE.md` 同一套精簡測試。
- Auto-compact：摘要後重新附上每個 skill 的最近一次叫用，各取前 5,000 tokens，合計 25,000 tokens 預算，最近叫用優先填 → 一個 session 叫用很多 skill 時，較舊的 compaction 後可能整個被丟。
- 若 skill 第一個回應後似乎失效：內容通常還在，是模型選了別的做法。強化 `description` 與說明，或用 hooks 強制行為，或在 compaction 後重新叫用恢復完整內容。

## 10. 權限

- `allowed-tools` 在 skill 生效期間授予免提示；checked-in 專案 skill 需先接受 workspace trust 對話（同 `.claude/settings.json` 規則）。**信任 repo 前先看過專案 skill**——skill 可自行授予寬鬆工具存取。
- 限制 Claude 的 skill 存取：`/permissions` deny `Skill`（全部）；或 `Skill(name)` 精確 / `Skill(name *)` 前綴 允許或拒絕；或個別 skill 加 `disable-model-invocation: true`（從 Claude context 完全移除）。
- 部分內建命令可經 Skill 工具取得：`/init`、`/review`、`/security-review`（`/compact` 不行）。
- `user-invocable` 只控制選單可見性，不控制 Skill 工具存取；要擋程式化叫用用 `disable-model-invocation: true`。

## 11. skillOverrides（settings，不是 frontmatter）

`.claude/settings.local.json`：由設定而非 skill 自身 frontmatter 控制可見性。用於不想改 SKILL.md 的 skill（共享 repo、MCP 提供者）。`/skills` 選單會替你寫（Space 循環狀態，Enter 存檔）。

| 值 | 列給 Claude | 在 `/` 選單 |
|---|---|---|
| `"on"`（不存在時的預設） | 名稱 + 描述 | 是 |
| `"name-only"` | 只名稱 | 是 |
| `"user-invocable-only"` | 隱藏 | 是 |
| `"off"` | 隱藏 | 隱藏 |

`"off"` 自 v2.1.199 也對 Remote Control 用戶端與 Agent SDK 隱藏。外掛 skill 不受影響（改用 `/plugin`）。

## 12. Subagent 中執行（`context: fork`）

- skill 內容成為驅動 subagent 的 prompt，無法存取對話歷史。
- **只對有明確說明／任務的 skill 有意義**；純指南型（「用這些 API 慣例」但沒任務）fork 後會空手而回。

| 方法 | 系統提示 | 任務 | 也載入 |
|---|---|---|---|
| `context: fork` 的 skill | 來自 agent 類型 | SKILL.md 內容 | CLAUDE.md，除非 agent 是 Explore/Plan |
| 有 `skills` 欄位的 subagent | subagent markdown 主體 | Claude 的委派訊息 | 預載 skills + CLAUDE.md |

`Explore`／`Plan` 跳過 CLAUDE.md 與 git status → `agent: Explore` 的 fork skill 只看到 SKILL.md 內容 + agent 系統提示。

## 13. 評估與迭代

- 看到 skill 觸發 ≠ 它做了你要的。分開量兩件事：(1) 該觸發的 prompt 有沒有觸發；(2) 觸發時輸出對不對。
- 兩者都用 baseline 對照：收集現實 prompt，在**乾淨 session** 跑 skill 開一次、停用（`skillOverrides` `"off"`）再跑一次，比較。乾淨 session 很重要——寫 skill 的殘留 context 會蓋掉書面說明的漏洞。
- `skill-creator` 外掛自動化此迴圈：`/plugin install skill-creator@claude-plugins-official` → `/reload-plugins` → 要求 Claude「evaluate my <skill> skill with skill-creator」。測試案例存 skill 目錄內 `evals/evals.json`；每案生成隔離 subagent；`grading.json` 記通過／失敗 + 證據；`benchmark.json` 聚合通過率／時間／token（有 skill vs 無 skill）；支援盲 A/B 版本比較與 description 調整。

## 14. Troubleshooting

- **不觸發**：`description` 缺使用者會自然說出的關鍵字；確認出現在「What skills are available?」；換句話說重述請求；或直接 `/skill-name`。frontmatter YAML 格式錯 → skill 主體照載但 metadata 空（`/name` 仍可用，但 Claude 沒有 `description` 可比對）；跑 `--debug` 看解析錯誤。
- **觸發太頻繁**：`description` 更具體；或加 `disable-model-invocation: true`。
- **描述被截斷**：listing 預算動態縮放為模型 context window 的 1%；超出時從最少叫用的 skill 開始砍描述。`/doctor` 估算成本。提高：settings `skillListingBudgetFraction`（如 `0.02`）或 `SLASH_COMMAND_TOOL_CHAR_BUDGET`（固定字元數）。每項 `description` + `when_to_use` 合計硬上限 1,536 字元（`skillListingMaxDescChars` 可調），關鍵用途寫前面。釋放預算：低優先項設 `"name-only"`。`/context` 的 Skills 列報套用預算後的大小（v2.1.196+）。

## 15. Bundled skills

每個 session 可用（除非 settings `disableBundledSkills`），如 `/doctor`、`/code-review`、`/batch`、`/debug`、`/loop`、`/claude-api`。與直接執行固定邏輯的內建命令不同，bundled skills 是 prompt-based：給 Claude 詳細劇本再讓它用工具協調。`/run`、`/verify`、`/run-skill-generator` 三者搭配用於「對執行中的 app」驗證變更（非只跑測試）；前兩者免設定靠推斷啟動，`/run-skill-generator` 把可行配方寫成每專案 skill 到 `.claude/skills/run-<name>/`。

## 相關

- 除錯設定為何 skill 不出現／不觸發：`/docs/zh-TW/debug-your-config`
- eval 檔格式與迭代流程：https://agentskills.io/skill-creation/evaluating-skills
- skill 撰寫最佳實踐：https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Sub-agents、Plugins、Hooks、Memory、Commands、Permissions：`/docs/zh-TW/*`
