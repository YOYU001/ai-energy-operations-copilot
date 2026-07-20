# CLAUDE.md

## 專案定位

本專案是 **AI Energy Operations Copilot MVP v1**：能源營運情境的企業級 AI Copilot 原型，涵蓋太陽光電、EMS、儲能排程、異常診斷、相似案件搜尋、成本估算與綠能營運指數分析。

主要使用者：能源調度人員、EMS 工程師、非工程背景主管、新進或培訓中的新人。

## Required Reading

每次 session 開始、`clear` 之後、以及每個新 Step 開始前，必讀以下三份文件：

- `CLAUDE.md`
- `PROGRESS.md`
- `docs/WORKFLOW_SHORT.md`

實作任務前依主題再讀：`docs/MVP_V1_SPEC.md`、`docs/DATA_SCHEMA.md`、`docs/DEVELOPMENT_WORKFLOW.md`、`docs/MVP1_RULES.md`、`docs/SAMPLE_DATA_PLAN.md`。其餘較長的追蹤文件依 `docs/WORKFLOW_SHORT.md` 指引，只在相關時才讀，以節省 token。

`CLAUDE.md` 只放高層規則，詳細需求放在 `docs/`。

## MVP v1 範圍

本階段僅實作以下 10 項 MVP v1 功能，其餘一律視為未來版本範圍：

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

以下功能保留至未來版本，僅在使用者明確核准後才可實作：Real EMS control、Real web search、Optimization algorithms、Self-trained PV/load forecasting models、Multi-agent architecture、Full carbon accounting / ESG reporting、Real power trading integration、Real ancillary service revenue calculation。

## Tech Stack 關鍵決策

技術棧（Next.js / FastAPI / PostgreSQL）可由原始碼推斷，此處只記錄非顯而易見的決策：

- **Vector Search**：優先使用 pgvector，Chroma 僅作為未來 fallback（目前完全未實作，先以 pgvector 驗證可行性）。
- **Default mode**：Internal Knowledge Only，規則詳見「資料與回答原則」章節。

## 模組化規則

以下規則檔案透過 `@` import 引入，內容見 `.claude/rules/README.md`：

@.claude/rules/code-style.md
@.claude/rules/frontend/react.md

## 常用指令 (Commands)

Conda environment：`AI_Copilot`（Python 3.11）。所有 Python 開發限定在此獨立環境中進行，因為 backend 依賴（torch、easyocr 等）版本特殊，混用 `base` 或全域 Python 容易造成套件衝突、難以重現的環境問題。安裝 Python package 前須先詢問使用者並取得同意，安裝後同步更新 `requirements.txt` 與 `environment.yml`；frontend package 則更新於 `package.json`。

**啟動資料庫（Docker，PostgreSQL + pgvector）：**
```bash
docker compose up -d
docker exec -i <container_name> psql -U ai_copilot -d ai_copilot < database/schema.sql
```
需要根目錄 `.env`（可從 `.env.example` 複製後填入密碼）。

**啟動 backend dev server（於 repo 根目錄，在 `AI_Copilot` 環境中）：**
```bash
uvicorn app.main:app --reload --app-dir backend
```

**執行測試：**
```bash
pytest                                              # 全部測試
pytest backend/tests/test_ingestion.py              # 單一檔案
pytest backend/tests/test_ingestion.py::test_name   # 單一測試
```
無 `pytest.ini` / `pyproject.toml`，採用 pytest 預設探索方式。測試分佈於 `backend/tests/`（backend API/ingestion）與 `spike/tests/`（RAG spike）。

**執行 RAG spike 腳本（於 repo 根目錄，以 module 方式執行）：**
```bash
python -m spike.run_parsing_validation
python -m spike.run_chunking_comparison
python -m spike.run_embedding_ingestion
python -m spike.run_retrieval_comparison
python -m spike.run_retrieval_benchmark
```
每個腳本會在 `spike/` 下輸出對應的 `*_report.json`。目前未設定 linting/formatting 工具。

## 架構總覽 (Architecture Overview)

**Backend 分層（`backend/app/`）：** `main.py`（FastAPI routes，保持薄）→ `datasets_queries.py`（SQL 查詢邏輯）／`ingestion.py`（CSV 解析與驗證）→ `db.py`（SQLAlchemy engine、`get_connection()`，以及供測試覆寫用的 `get_db_dependency()`）。`schemas.py` 存放 Pydantic response models。DB 存取一律透過 `Depends` 注入，測試以 `backend/tests/fakes.py` 的 `FakeConnection` 取代真實資料庫。

**資料庫 schema（`database/schema.sql`，純 SQL，無 ORM/Alembic）：** 7 張表 —— `documents`/`document_chunks`（RAG 用，含 pgvector `vector(1536)`）、`datasets`/`energy_timeseries`（CSV 匯入，`dataset_id` 外鍵）、`case_records`（含 embedding 的案例記錄）、`analysis_runs`（每個 dataset 的 JSONB 分析結果）、`chat_messages`（copilot 對話紀錄）。

**RAG Spike（`spike/`）：** Step 6 探索性原型，與正式 backend 明確分離，使用獨立 schema `spike/schema_spike.sql`。Pipeline：`pdf_parser.py` → `ocr_fallback.py` → `chunker.py` → `hashing.py` → `embedding_provider.py` → `vector_store.py` → `hybrid_retrieval.py` → `query_parser.py`/`retrieval_metrics.py`，由 `run_*.py` 腳本驅動，以 `spike/test_questions.json` 為評估基準。此原型尚未穩定，**不是**正式資料遷移；正式的 Step 10 遷移方案待 spike 結束後才設計。

## 高頻踩坑點 (Gotchas)

- **conda 環境名稱不可含空白**：`conda create -n AI Copilot ...` 會被拆成環境名 `AI` + 套件名 `Copilot`，需用底線，例如 `ai_copilot`。
- **torch CPU 版安裝**：需加 `--extra-index-url https://download.pytorch.org/whl/cpu`，否則 `pip install -r requirements.txt` 會失敗。
- **Starlette TestClient 依賴 httpx2**：新版 Starlette 優先使用 `httpx2`，只裝 `httpx`會出現 deprecation warning，需同時安裝 `httpx2`。
- **SQL DDL 拆分陷阱**：`ensure_schema()` 這類自行拆分多語句 SQL 的邏輯，若檔案開頭有註解區塊，可能誤吞後面的 `CREATE EXTENSION` 陳述式，套用 schema 後務必實際驗證 extension 是否真的建立。
- **掃描頁判斷勿用單一門檻**：PDF 頁面「近乎空白」與「掃描頁」用單一文字量門檻判斷會誤判合法的近空白頁（例如僅印刷頁碼的分隔頁）；改用 text / near_empty / scanned / ocr_failed 四態分類，OCR 僅在 `scanned` 狀態觸發。

## 資料與回答原則

系統預設只能使用內部資料回答：uploaded documents、imported CSV datasets、case records、built-in MVP rules。這是為了讓每個回答都能追溯到可驗證的內部來源，避免使用者誤信未經查證的內容。若內部資料不足，須明確告知使用者「資料不足」，並具體說明還需要哪些資料或文件才能回答，而不是依常識或訓練知識推測作答。

## Learning Mode / Teaching Role

本專案採用 learning-by-building 模式，詳見 `docs/Claude_Code_Learning_Workflow.md`。Claude Code 在本專案中同時是 coding assistant 與 **teacher / technical tutor**。

**每個 Step 開始前**：先用繁體中文完整教學，涵蓋目的、在整體專案中的角色、會用到的技術概念、會修改的檔案與各自職責、設計理由、常見陷阱、與下一步的連接。教學完成後提出 implementation plan（依 `docs/DEVELOPMENT_WORKFLOW.md` 格式），等待使用者確認後才可修改檔案。

**實作時**：保持小步驟，一次只做一小範圍；修改前說明準備做什麼，修改後說明改了什麼。

**每個 Step 完成後**：除 `docs/DEVELOPMENT_WORKFLOW.md` 的標準回報格式（files changed / implemented / how to run / how to test / known limitations / next recommended step）外，額外附上：What you learned、Key concepts explained、Common pitfalls、How this connects to the next step。

**衝突處理**：任務與 `docs/Claude_Code_Learning_Workflow.md`、`docs/DEVELOPMENT_WORKFLOW.md`、`docs/MVP1_RULES.md` 或本檔案衝突時，先停下並詢問使用者取得裁示後再繼續，因為這些文件代表使用者對流程的明確共識，單方面判斷容易偏離已溝通過的方向。

**語言規則**：教學與說明文字使用繁體中文；技術指令、檔名、API endpoint、package/function name 保持英文，同一段落避免中英文過度混用。回覆重點清楚、避免冗長，使用者要求詳細教學時再展開。

## 開發規則

每次只做一小步，因為本專案採 learning-by-building 模式，小步驟能讓使用者每次都能看懂並確認變更，也能在出錯時快速定位是哪一步造成的。修改前先說明這一步要做什麼、預計修改哪些檔案、有哪些假設或風險。修改後回報 files changed / what was implemented / how to run/test / known limitations / next recommended step，且新增或修改的 pytest 測試須全數通過（exit code 0）才算完成這一步。只修改任務相關檔案，僅實作已討論過的功能，保持模組化以利未來分支擴充。

## PROGRESS.md 撰寫規則

`PROGRESS.md` 是專案的「目前狀態快照」，不是開發日誌，每次 session 開頭都會被完整讀入。新增 `Completed` 項目時：

- 每個 Step / Sub-step 只寫 1–2 行摘要（做了什麼、關鍵結果、測試數量）。
- 詳細技術過程、bug 修復細節、參數命名寫進對應的 `docs/` 檔案（例如 `docs/RAG_SPIKE_PLAN.md`、`docs/DECISIONS.md`），並在該行結尾以「Details: docs/xxx.md §N」指向章節。
- 若一個 Completed 項目超過 2–3 行，先精簡再寫入。

## Git / Versioning

目前將 `main` 視為 MVP v1 baseline。未來以 feature branches 疊加功能，例如 `feature/rag-ingestion`、`feature/dashboard`、`feature/case-similarity`、`feature/optimization-v2`、`feature/web-search-v2`。本專案定位是 NVIDIA 面試作品集與 AI 工程能力展示，功能範圍應嚴格對齊本文件「MVP v1 範圍」，超出範圍的功能會稀釋展示重點、拖慢完成時程。

## 回覆語言規則

Claude Code 預設使用繁體中文回覆。以下情況保留英文：技術術語、程式碼關鍵字、檔案名稱、函式名稱、API 名稱、CLI 指令、錯誤訊息、套件名稱、框架名稱。

範例：Git 術語統一保持英文（例如使用 `git commit`）；`API endpoint` 等英文技術術語更清楚時直接保留；`FastAPI`、`Next.js`、`PostgreSQL`、`pgvector` 保持原文。同一段落避免中英文過度混用；說明文字使用繁體中文，技術指令在適合時保留英文。
