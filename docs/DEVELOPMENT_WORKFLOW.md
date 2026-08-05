# Development Workflow

## 1. 工作原則

Claude Code 必須採用 incremental development。

每次只做一個小步驟。  
每個步驟都要能被測試。  
不要一次實作多個大型模組。

---

## 2. 修改前回報格式

每次 coding 前，先說明：

```text
Goal:
這一步要完成什麼

Expected files to change:
預計修改或新增哪些檔案

Assumptions:
目前假設是什麼

Risks:
可能風險或限制
```

大型修改需等待使用者確認後再開始。

---

## 3. 修改後回報格式

每次 coding 後，回報：

```text
Files changed:
列出修改檔案

Implemented:
完成了什麼

How to run:
如何啟動

How to test:
如何測試

Known limitations:
目前限制

Next recommended step:
下一步建議
```

---

## 4. Git / Versioning 規則

目前 `main` 可作為 MVP v1 baseline。

後續功能會用 feature branches 疊加。

分支命名範例：

```text
feature/rag-ingestion
feature/dashboard
feature/case-similarity
feature/green-index
feature/optimization-v2
feature/web-search-v2
```

MVP v1 不等於最終產品。  
不要把 v2 / v3 的功能提前塞進 main。

---

## 5. 建議專案結構

```text
ai-energy-operations-copilot/
  frontend/
  backend/
  database/
  data/
  docs/
  scripts/
  README.md
  CLAUDE.md
```

### frontend/

Next.js application。

用途：
- Dashboard
- Dataset Manager
- Knowledge Base
- Case Similarity
- Copilot Chat
- Analysis Report

### backend/

FastAPI application。

用途：
- API endpoints
- CSV ingestion
- RAG ingestion
- analysis services
- database access
- role-based response orchestration

### database/

用途：
- schema
- migrations
- seed data
- pgvector setup

### data/

用途：
- sample CSV
- sample Case Records
- demo documents

### docs/

用途：
- MVP spec
- data schema
- workflow rules
- architecture notes

### scripts/

用途：
- ingestion scripts
- seed scripts
- utility scripts

---

## 6. MVP v1 Build Order

### Step 1: Project Skeleton

只建立資料夾與 placeholder files。

不要實作 business logic。

### Step 2: Backend Foundation

建立 FastAPI backend。

Basic endpoints:

```text
GET /health
GET /version
```

### Step 3: Database Foundation

建立 PostgreSQL connection。

優先啟用 pgvector。

建立 initial tables:

```text
documents
document_chunks
datasets
energy_timeseries
case_records
analysis_runs
chat_messages
```

### Step 4: Dataset Ingestion

實作 CSV upload / import。

需做：
- 欄位檢查
- 型別轉換
- warning report
- 寫入 PostgreSQL

### Step 5: Dataset API

實作：

```text
GET /datasets
GET /datasets/{dataset_id}
GET /datasets/{dataset_id}/summary
GET /datasets/{dataset_id}/timeseries
```

### Step 6: RAG Feasibility Spike

在正式進入 Frontend/Dashboard/RAG 開發前，先用小範圍 spike 驗證 RAG/OCR 相關能力是否可行。

範圍：3–5 份真實但非機密文件（含文字型與掃描型 PDF）、10–20 題固定測試問題、OpenAI Embeddings/LLM、script/notebook 等級，不做正式 UI 或完整 pipeline。

完整規格見 `docs/RAG_SPIKE_PLAN.md`；本次決策記錄見 `docs/DECISIONS.md` ADR-007、`docs/PROJECT_ALIGNMENT_REVIEW.md`。

### Step 7: Frontend Foundation

建立 Next.js frontend。

建立基本頁面：

```text
Operations Dashboard
Knowledge Base
Dataset Manager
Case Similarity
Copilot Chat
Analysis Report
```

### Step 8: Dashboard Charts

實作固定圖表：

```text
PV forecast vs actual
Load vs contract capacity
Battery SOC
Battery power
Electricity price
Cost comparison
Green Operations Index
Anomaly timeline
```

MVP 第一階段聚焦 `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT` 場景相關圖表，其餘固定圖表類型後續擴充。`Cost comparison`、`Green Operations Index` 兩張圖依賴 Step 13 的資料，補在 Step 13。`Anomaly timeline` 列為後續擴充，不在 Step 13/14 範圍內。

### Step 9: Rule-Based Analysis

實作：

```text
anomaly diagnosis
battery scheduling suggestion
cost estimation
green operations index
```

MVP 第一階段先只實作 `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT` 這一條規則（見 `docs/MVP1_RULES.md` 4.6 節），其餘 7 種異常類型後續擴充。

Step 9 實際交付範圍僅 anomaly diagnosis 一項；`battery scheduling suggestion`、`cost estimation`、`green operations index` 三項未在 Step 9 實作，已移至新 Step 13（見下方）。

### Step 10: Knowledge Base / RAG

實作：

```text
PDF/TXT/MD ingestion
document chunking
embedding generation
pgvector storage
internal-only retrieval
```

基於 Step 6 RAG Feasibility Spike 的結論展開正式實作，不是從零開始設計。

### Step 11: Case Similarity

實作簡化版相似案件搜尋。

使用：

```text
event_type
symptoms
tags
root_cause
operator_action
embedding similarity
```

### Step 12: Copilot Chat / AI Assistant

實作角色化回答：

```text
Operator Mode
Engineer Mode
Executive Mode
Training Mode
```

Structured data 查詢採受控 tool-calling，複用 Step 5 既有查詢函式（`backend/app/datasets_queries.py`），不做 unrestricted Text-to-SQL（見 `docs/DECISIONS.md` ADR-002）。回答格式依 `docs/MVP1_RULES.md` 第 8 節的七部分結構。

### Step 13: Rule-Based Scheduling / Cost / Green Operations 補完

實作 `docs/MVP1_RULES.md` §5、§6、§7 三組規則，補齊 Step 9 當初漏做的部分：

```text
battery scheduling suggestion（charge / discharge / idle recommendation）
cost estimation（energy cost、arbitrage saving、over-contract risk）
green operations index（100 分權重公式）
```

對應 backend API 與測試需一併完成；`database/schema.sql` 的 `analysis_runs`（`analysis_type TEXT` + `result_json JSONB`）已是通用設計，不需要新增 migration。Dashboard 需補上 Step 8 原定但當時未做的兩張圖：`Cost comparison`、`Green Operations Index`。

MVP v1 正式完成條件之一：本 Step 完成，且三項功能各自有對應的 backend API 與測試。

### Step 14（原 Step 13）: Analysis Report

根據以下資料產生報告：

```text
dataset summary
anomalies
schedule suggestions
similar cases
cost estimate
green operations index
limitations
```

依賴 Step 13 完成——`schedule suggestions`、`cost estimate`、`green operations index` 三個區塊需要 Step 13 產出的真實資料，不可用假資料填補或讓必要區塊無故空白。

MVP v1 正式完成條件之一：本 Step 完成，且 7 個必要區塊都有真實資料支撐。

### Step 15（選配）: AI Assistant Tool Registry 擴充

讓 Step 12 的 AI Assistant 聊天工具也能引用 Step 13 產出的排程建議／成本估算／綠能指數。列為選配，**不是 MVP v1 完成的必要條件**——Analysis Report 頁面能直接使用這些資料即可，聊天工具支援可留給後續版本。

---

## 7. First Milestone

第一個可運作 milestone 只需要證明：

1. FastAPI 可以啟動
2. Next.js 可以啟動
3. PostgreSQL 可以連線
4. CSV 可以匯入
5. Dataset list 可以在前端顯示
6. 一個簡單 Dashboard 可以從 backend 讀資料

---

## 8. Important Constraints

不要做：

```text
Real EMS control
Real web search
Optimization algorithms
Self-trained PV/load forecasting
Multi-agent orchestration
Official carbon accounting
Power trading integration
Overly complex UI before data flow works
```

---

## 9. 常見陷阱

### 不要過早美化 UI

先讓資料流跑通，再做 UI polish。

### 不要讓 AI 直接亂查資料庫

MVP v1 優先使用 backend-defined API 和 service functions。

### 不要讓 AI 預設上網

Default mode 是 Internal Knowledge Only。

### 不要把 Green Operations Index 說成正式碳盤查

它只是 operational sustainability score。

### 不要把 rule-based scheduler 說成最佳化模型

MVP v1 沒有 optimization algorithm。

---

## 10. 給 Claude Code 的第一個任務範例

```md
Please read CLAUDE.md, docs/MVP_V1_SPEC.md, docs/DATA_SCHEMA.md, and docs/DEVELOPMENT_WORKFLOW.md first.

We are building AI Energy Operations Copilot MVP v1.

Start only with Step 1: Project Skeleton.

Do not implement business logic yet.

Create the project folder structure and minimal placeholder files only.

After finishing, report changed files, what was created, how to verify, and the next recommended step.
```
