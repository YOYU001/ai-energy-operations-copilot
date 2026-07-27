# AGENTS.md

本檔案給 Codex 等 AI coding agent 在 review 這個 repo 的程式碼（尤其是 PR）時參考，內容從 `CLAUDE.md` 擷取與「程式碼品質、範圍是否合理」直接相關的部分。互動式教學流程、`PROGRESS.md` 撰寫規則等只適用於 Claude Code 一般開發 session 的規則，不在這裡重複——那些跟「這段 diff 寫得好不好、該不該存在」無關。

完整專案脈絡、開發流程規則見 `CLAUDE.md`；本檔案只聚焦在 review 時該檢查的具體標準。

## 專案定位

**AI Energy Operations Copilot MVP v1**：能源營運情境的企業級 AI Copilot 原型，涵蓋太陽光電、EMS、儲能排程、異常診斷、相似案件搜尋、成本估算與綠能營運指數分析。本專案定位是 NVIDIA 面試作品集與 AI 工程能力展示，功能範圍應嚴格對齊下方「MVP v1 範圍」，超出範圍的功能會稀釋展示重點。

## MVP v1 範圍（review PR 時，若新增的功能不在這 10 項內，應該提出質疑）

1. 內部文件知識庫問答
2. CSV 能源時間序列資料匯入與分析
3. 固定圖表 Dashboard
4. Rule-based 異常診斷
5. 簡化版相似案件搜尋
6. Rule-based 儲能排程建議
7. 成本估算
8. Green Operations Index / 綠能營運指數
9. 角色化回答模式
10. 分析報告產生

以下功能保留至未來版本，**除非 PR 描述裡有明確提到使用者已核准，否則出現在 diff 裡應該被標記出來**：Real EMS control、Real web search、Optimization algorithms、Self-trained PV/load forecasting models、Multi-agent architecture、Full carbon accounting / ESG reporting、Real power trading integration、Real ancillary service revenue calculation。

## Tech Stack 關鍵決策

- Frontend：Next.js；Backend：FastAPI；Database：PostgreSQL
- **Vector Search**：優先使用 pgvector，Chroma 僅作為未來 fallback，目前不應出現任何 Chroma 相關程式碼。
- **Default mode**：Internal Knowledge Only——AI 回答邏輯只能用 uploaded documents、imported CSV datasets、case records、built-in MVP rules 作答，不可依賴模型自身訓練知識推測作答，內部資料不足時應明確回覆「資料不足」。
- MVP v1 優先採用 rule-based 分析，不使用 optimization algorithms。

## Python 程式碼風格（`backend/app/`）

核心原則：**效率優先，不是行數最少**。判斷標準是「計算某份資料或查詢某筆記錄時，是否用了最少的計算量/查詢次數得到答案」。

- 避免重複計算：同一個值在函式裡若會用到多次，算一次存起來。
- 避免 N+1 查詢：迴圈裡逐筆查資料庫/外部 API，應改成一次查詢/batch 操作。
- 需要判斷「是否存在」或做查找時優先用 `set`/`dict`，不要對 `list` 做重複線性掃描。
- 已經在用 pandas 的地方，能用向量化操作（`.apply`、boolean masking、groupby）就不要退回 Python-level for-loop。
- 能在資料庫層用 `SUM`/`COUNT`/`GROUP BY` 算完的，不要把整份資料撈進 Python 再算一次。
- 全面使用 type hint；`Optional[X]` 而非 `X | None`。
- Docstring 只在「非顯而易見」時才寫，且說明 WHY，不是重述程式碼在做什麼。
- Response schema 一律用 Pydantic `BaseModel`，欄位命名 snake_case。
- Import 順序：標準庫 → 第三方套件 → 本地模組，各段之間空一行。
- 此風格規則主要適用於 `backend/app/`；`spike/` 是探索性原型，定位不同，不要直接套用同一套標準去要求 `spike/` 的程式碼。

## Frontend / React 慣例（`frontend/`）

- **Server Component 為預設**，只有真的需要 client-side state/effect 才加 `"use client"`。
- **`lib/api/` 是呼叫 backend 的唯一入口**：`client.ts`（`server-only` + `fetch`，需明確區分 timeout / network error / non-OK / 非 JSON 四種失敗情境）+ `types.ts`（純 interface 定義）。頁面元件不應直接呼叫 `fetch`。
- **用 runtime type guard 驗證 API response**，不要用 `as SomeType` 直接硬轉型。
- `components/layout/` 用 PascalCase 檔名，一個檔案一個 component。
- **Import 一律走 `@/*` path alias**，不要用相對路徑（包含同目錄的 `./`）。
- 需要即時 backend 資料的頁面，需明確標註 `export const dynamic = "force-dynamic"`。
- **Tailwind dark mode 成對寫**，例如 `border-black/10 dark:border-white/10`，不要只寫 light mode 忘記補 dark。
- UI 文字（使用者看得到的）用繁體中文；code comment 目前維持英文。
- `/assistant` 頁面的資料來源預設走 Internal Knowledge Only；介面上的「內部／外部搜尋」切換目前只能是 UI 佔位，**外部搜尋分支不可以接任何真正呼叫外部網路的邏輯**（對應上方 MVP v1 Out of Scope 的 Real web search）。

## 高頻踩坑點（review 時可對照，這些都是這個專案真實發生過的問題）

- conda 環境名稱不可含空白（`ai_copilot` 不是 `AI Copilot`）。
- torch CPU 版安裝需加 `--extra-index-url https://download.pytorch.org/whl/cpu`。
- 自行拆分多語句 SQL 的邏輯，若檔案開頭有註解區塊，可能誤吞後面的 `CREATE EXTENSION` 陳述式，套用 schema 後務必實際驗證 extension 是否真的建立。
- PDF 頁面「近乎空白」與「掃描頁」不要用單一文字量門檻判斷，會誤判合法的近空白頁；應使用 text / near_empty / scanned / ocr_failed 四態分類。

## Git 慣例

- `main` 是 baseline；功能開發走 feature branch，命名慣例例如 `feature/rag-ingestion`、`feature/dashboard`、`feature/case-similarity`。
