# AI Energy Operations Copilot

AI Energy Operations Copilot 是一個面向能源營運場景的 MVP 專案，目標是建立一套結合 **Energy Operations Dashboard** 與 **AI Copilot** 的智慧能源分析系統。

本專案定位為 NVIDIA 求職作品集專案，重點展示 AI engineering、RAG、能源資料分析、rule-based decision support、系統設計與前後端整合能力。

---

## 1. Project Goal

本專案的 MVP v1 目標是建立一個可展示的能源營運助手，協助使用者：

- 查看太陽光電、負載、儲能與電價資料
- 分析能源異常事件
- 產生 rule-based 儲能排程建議
- 估算尖離峰電價、超約風險與綠電浪費
- 透過 RAG 查詢內部能源研究文件
- 以 AI Copilot 方式回答營運問題

MVP v1 不追求真實 EMS 控制，而是建立一個可解釋、可展示、可逐步擴充的 AI 能源營運原型。

---

## 2. Product Positioning

本產品不是單純的 chatbot，而是：

```text
Energy Operations Dashboard + AI Copilot
```

Dashboard 負責呈現能源數據與分析結果，AI Copilot 負責解釋異常、引用文件、生成建議與協助決策。

---

## 3. MVP v1 Scope

MVP v1 包含以下核心功能：

1. **Energy Dashboard**
   - PV forecast vs actual
   - Load trend
   - Battery SOC
   - Battery temperature
   - Grid import/export
   - Electricity price
   - Green Operations Index

2. **CSV Data Ingestion**
   - 匯入模擬能源 time-series CSV
   - 驗證欄位格式
   - 儲存至 PostgreSQL

3. **Rule-based Anomaly Diagnosis**
   - PV forecast deviation
   - Over contract risk
   - Low SOC risk
   - Battery health risk
   - Peak-period abnormal charging
   - Battery should discharge but did not
   - Green energy waste

4. **Battery Scheduling Suggestion**
   - 根據 SOC、電價、負載、PV、溫度產生建議
   - MVP v1 使用 rule-based logic，不做 optimization solver

5. **Cost and Green Energy Analysis**
   - TOU cost estimation
   - over-contract risk estimation
   - green energy waste estimation
   - second-life battery bonus

6. **Document Q&A / RAG**
   - 僅回答內部文件與 approved dataset 範圍內的問題
   - 使用 pgvector 優先，Chroma 僅作 fallback

7. **AI Copilot**
   - 回答能源營運問題
   - 解釋異常原因
   - 提供可執行建議
   - 引用內部資料來源

---

## 4. Tech Stack

### Frontend

```text
Next.js
React
TypeScript
```

### Backend

```text
FastAPI
Python
```

### Database

```text
PostgreSQL
pgvector
```

### AI / RAG

```text
OpenAI API
Embeddings
Internal Knowledge Only RAG
```

### Data

```text
Synthetic CSV
Taiwan energy research concepts
Public energy dataset concepts
```

---

## 5. Repository Structure

建議專案結構如下：

```text
ai-energy-operations-copilot/
  frontend/
  backend/
  database/
  data/
  docs/
    MVP_V1_SPEC.md
    DATA_SCHEMA.md
    DEVELOPMENT_WORKFLOW.md
    MVP1_RULES.md
    SAMPLE_DATA_PLAN.md
    WORKFLOW_SHORT.md
    Claude_Code_Learning_Workflow.md
    LEARNING_LOG.md
    ANTHROPIC_LEARN_MAP.md
    DECISIONS.md
    OFFICIAL_UPDATE_LOG.md
  CLAUDE.md
  PROGRESS.md
  README.md
```

---

## 6. Important Docs

| File | Purpose |
|---|---|
| `CLAUDE.md` | high-level project rules for Claude Code |
| `PROGRESS.md` | current progress, current phase, next step |
| `docs/MVP_V1_SPEC.md` | detailed MVP v1 product scope |
| `docs/DATA_SCHEMA.md` | dataset and database schema definitions |
| `docs/DEVELOPMENT_WORKFLOW.md` | implementation order and workflow |
| `docs/MVP1_RULES.md` | rule-based analysis and scheduling logic |
| `docs/SAMPLE_DATA_PLAN.md` | synthetic demo dataset design |
| `docs/WORKFLOW_SHORT.md` | mandatory short workflow read at every session and Step |
| `docs/Claude_Code_Learning_Workflow.md` | complete learning-by-building, Git, and NVIDIA interview workflow |
| `docs/LEARNING_LOG.md` | actual learning, manual operation, debugging, and interview notes |
| `docs/ANTHROPIC_LEARN_MAP.md` | mapping between project tasks and Anthropic Learn topics |
| `docs/DECISIONS.md` | important technical decision records |
| `docs/OFFICIAL_UPDATE_LOG.md` | reviewed Anthropic official updates and adoption decisions |
| `docs/PROJECT_ALIGNMENT_REVIEW.md` | confirmed product definition, decision log, MVP scope, non-goals, risks, and architecture direction |
| `docs/RAG_SPIKE_PLAN.md` | scope and validation plan for the RAG Feasibility Spike (new Step 6) |

---

## 7. Required Reading for Claude Code

At the start of every Claude Code session, after `clear`, and before every new development Step, read:

```text
CLAUDE.md
PROGRESS.md
docs/WORKFLOW_SHORT.md
```

Before implementation, read the documents relevant to the task. For example:

```text
docs/MVP_V1_SPEC.md
docs/DATA_SCHEMA.md
docs/DEVELOPMENT_WORKFLOW.md
docs/MVP1_RULES.md
docs/SAMPLE_DATA_PLAN.md
```

Long workflow and tracking files are read only when required by `docs/WORKFLOW_SHORT.md`, which keeps context and token use controlled.

---

## 8. Data Policy

MVP v1 預設採用 **Internal Knowledge Only**。

AI Copilot 不應自行搜尋網路，也不應編造真實台電營運資料。若資料來自模擬 CSV，必須明確視為 demo data。

Allowed data sources:

- synthetic CSV
- approved internal markdown docs
- approved internal PDF-derived notes
- public dataset concepts if explicitly included in the repo

Not allowed in MVP v1:

- real EMS control
- real-time grid operation
- unapproved web search
- unsupported claims about real Taipower operations

---

## 9. MVP v1 Non-goals

MVP v1 不做以下項目：

- real EMS control
- real-time hardware control
- optimization solver
- self-trained forecasting model
- multi-agent system
- production authentication system
- large-scale cloud deployment
- real-time streaming infrastructure

這些可作為 MVP v2 或 future work。

---

## 10. Demo Value

這個專案展示的能力包含：

- AI application system design
- RAG pipeline design
- structured energy data analysis
- rule-based decision support
- dashboard product thinking
- FastAPI + Next.js full-stack MVP
- PostgreSQL + pgvector integration
- domain-aware AI Copilot design

---

## 11. Current Status

Current phase:

```text
Step 5: Dataset API completed
Project Alignment Review completed
Next: New Step 6 — RAG Feasibility Spike
```

Completed foundations include:

- Project skeleton
- FastAPI backend with health and version endpoints
- PostgreSQL + pgvector through Docker
- Initial seven-table database schema
- Database connectivity check
- CSV upload, validation, type conversion, warning report, and PostgreSQL insertion
- Dataset API: GET /datasets, GET /datasets/{dataset_id}, GET /datasets/{dataset_id}/summary, GET /datasets/{dataset_id}/timeseries, with dependency-injected database access and 36 passing tests

A five-phase Project Alignment Review confirmed the product stays energy-vertical (Energy Operations Dashboard + AI Assistant for EMS engineers), locked in the first end-to-end scenario (`BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`), and reordered the roadmap to validate RAG/OCR feasibility before Frontend/Dashboard work. Full record: `docs/PROJECT_ALIGNMENT_REVIEW.md`.

The next implementation Step is a small, bounded RAG Feasibility Spike (not full production RAG), validating PDF parsing, OCR, chunking, retrieval accuracy, and citation accuracy on a handful of real non-confidential documents. Full plan: `docs/RAG_SPIKE_PLAN.md`.

See `PROGRESS.md` for the latest verified project state.
