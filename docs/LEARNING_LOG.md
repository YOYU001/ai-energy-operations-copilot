# Learning Log

> 用途：記錄我在 NVIDIA AI Applied Engineer 作品集專案中的實際學習成果。  
> 原則：只記真正理解、親自操作或完成驗證的內容；工程進度放在 `PROGRESS.md`，Anthropic 課程對照放在 `ANTHROPIC_LEARN_MAP.md`。

---

## 使用方式

每完成一個重要 Step、解決一個有價值的 bug、學會新的工具，或完成 milestone 時，新增一筆紀錄。

請保持精簡，不貼完整 terminal log，不記錄 API key、密碼、公司機密或敏感資料。

### 熟練程度

| Level | 定義 |
|---|---|
| Level 1 — Understand | 能用自己的話解釋概念與用途 |
| Level 2 — Operate | 能親自執行 command 或操作工具 |
| Level 3 — Build | 能在指導下完成小功能、測試與文件 |
| Level 4 — Explain and Defend | 能在面試中說明設計、trade-off、替代方案與驗證 |

---

## Learning Index

| Date | Project | Step / Topic | Skill Area | Level | Status |
|---|---|---|---|---|---|
| YYYY-MM-DD | EnergyOps Copilot | Example: Dataset API | API Engineering | Level 1 | To review |
| 2026-07-13 | EnergyOps Copilot | Step 5: Dataset API | API Engineering / Testing Strategy | Level 2–3 | Reviewed |

---

## Entry Template

### YYYY-MM-DD — Project / Step / Topic

#### Learning Goal
這次要學會什麼？

#### What I Learned
- 

#### Key Concepts
- 

#### What I Operated Manually
- 執行的 command：
- 閱讀的 output：
- 親自做的判斷或修改：

#### What Claude Code Assisted With
- 

#### Files I Can Explain
| File | 我目前能解釋的內容 |
|---|---|
| `path/to/file` | |

#### Commands I Can Explain
| Command | 用途 | 風險或注意事項 |
|---|---|---|
| `command` | | |

#### Errors and Diagnosis
- Symptom：
- Root-cause hypothesis：
- Actual cause：
- Fix：
- How verified：

#### Git / GitHub Practice
- Branch：
- `git status` / `git diff` review：
- Commit：
- Pull Request / Issue：
- 我學到的版本控制概念：

#### Verification
- Tests run：
- Result：
- Known limitations：

#### My Current Level
- Skill：
- Level：
- Evidence：

#### What I Can Explain Independently
- 

#### What Still Needs Practice
- 

#### NVIDIA Interview Connection
- Problem：
- My contribution：
- Technical decision：
- Trade-off：
- Validation：
- One-minute answer：

#### Next Learning Step
- 

---

## Completed Learning Entries

<!-- Claude Code 應把新的學習紀錄加在此區塊下方，最新日期放前面。 -->

### 2026-07-13 — EnergyOps Copilot / Step 5: Dataset API

#### Learning Goal
在 Step 4 完成的資料驗證與入庫（`datasets`、`energy_timeseries`）基礎上，補上四個 read-only 查詢端點，讓已入庫的資料第一次可以被讀取，並建立一套不依賴真實 test database 的自動化測試策略。

#### What I Learned
- Step 5 完成四個端點：`GET /datasets`、`GET /datasets/{dataset_id}`、`GET /datasets/{dataset_id}/summary`、`GET /datasets/{dataset_id}/timeseries`。
- 用 FastAPI `Depends()` 把資料庫連線變成可注入依賴（`get_db_dependency`），讓測試能用 `app.dependency_overrides` 換成假連線，不需要真實 test database 就能做 HTTP 層測試（含 404/422）。
- Summary 統計（19 個數值欄位的 min/mean/max）直接重用 `ingestion.py` 已驗證的欄位清單（`NUMERIC_FLOAT_COLUMNS` + `NUMERIC_INT_COLUMNS`），避免文件與程式碼兩處定義漂移——這是延續 Step 4 Consistency Fix 學到的教訓。
- 全部用 SQL 原生聚合函式（`MIN`/`AVG`/`MAX`/`COUNT`），不用 pandas 做統計，確保缺值序列化成 JSON `null` 而非 `NaN`。
- Pagination（`limit`/`offset`/`total`）用兩條獨立 SQL（`COUNT(*)` 與 `LIMIT/OFFSET` 查詢）處理，`total` 不受分頁影響；`limit`（1–1000）、`offset`（>=0）邊界由 FastAPI `Query(..., ge=..., le=...)` 自動驗證，超出範圍直接回 422，不會打到資料庫。
- 404（資源不存在）與 422（請求格式本身不合法）是不同層次的錯誤：404 由應用程式邏輯 `raise HTTPException` 產生，422 由 FastAPI 框架在呼叫路由函式之前就自動處理，兩者的測試策略也不同（422 測試不需要 dependency override）。

#### Key Concepts
- FastAPI dependency injection（`Depends`）與 dependency override 測試法
- SQL aggregate functions（`COUNT`、`MIN`、`AVG`、`MAX`、`GROUP` 語意下的 NULL 處理）
- Pagination 設計（`limit`/`offset`/`total` 三者分工）
- 404 vs 422 的語意差異
- Test double（`FakeConnection`/`FakeResult`）作為輕量測試替身，而非真實資料庫

#### What I Operated Manually
- 逐步審閱每個小步驟的 implementation plan，並在關鍵設計點提出修正：更正 numeric 欄位實際數量（18+1=19，避免寫死在程式碼與測試中）、要求先確認 `datasets_queries.py` import `ingestion.py` 沒有 circular import、指定排序需用 `ORDER BY timestamp ASC NULLS LAST, id ASC`、明確劃分 query test 與 API test 的職責邊界。
- 每個小步驟的 execution report（pytest 結果、curl 驗收內容）都經過審閱確認才進入下一步，未跳過任何一步的驗證。
- 待後續練習：親自執行 curl / pytest 指令並判讀輸出（Step 4 Consistency Fix 時已操作過一次，Step 5 這輪主要由 Claude Code 執行並回報結果）。

#### What Claude Code Assisted With
- 撰寫 `datasets_queries.py`、`schemas.py`、`main.py` 的實際程式碼，`FakeConnection`/`FakeResult` 測試替身，以及 query 層、HTTP 層共 30 個新測試。
- 執行 pytest、啟動/關閉臨時測試用 server、執行 curl 驗收並回報結果。
- 統整四個端點的整體架構、request flow 與面試講法。

#### Files I Can Explain
| File | 我目前能解釋的內容 |
|---|---|
| `backend/app/main.py` | 四個新 route 如何用 `Depends(get_db_dependency)`、`Query(...)`、`HTTPException` 組成完整的 HTTP 層邏輯 |
| `backend/app/datasets_queries.py` | 每個查詢函式對應的 SQL、為什麼 summary 重用 ingestion 的欄位清單 |
| `backend/app/db.py` | `get_db_dependency()` 這個 generator wrapper 為什麼能被 FastAPI 當作可注入、可覆寫的依賴 |
| `backend/app/schemas.py` | `DatasetSummary`、`DatasetSummaryStatistics`、`TimeseriesRow`、`TimeseriesPage` 各自對應哪個端點 |
| `backend/tests/fakes.py` | `FakeConnection`/`FakeResult` 如何模擬 SQLAlchemy 介面，`responses` 佇列如何支援一個 request 多次查詢 |

#### Commands I Can Explain
| Command | 用途 | 風險或注意事項 |
|---|---|---|
| `python -m pytest tests/ -v` | 執行全部自動化測試 | 需在 `AI_Copilot` conda 環境下執行，否則版本可能不一致 |
| `curl "http://127.0.0.1:8001/datasets/1/timeseries?limit=1&offset=0"` | 手動驗證分頁行為 | 需先確認 Docker 資料庫與本機 server 都在跑 |
| `python -m pip index versions <pkg>` / `pip install --dry-run` | 安裝套件前先確認版本與相容性，不實際安裝 | 純查詢，不改動環境 |

#### Errors and Diagnosis
- Symptom：`starlette.testclient` 印出 `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
- Root-cause hypothesis：`httpx` 版本過舊或與 FastAPI 版本不相容。
- Actual cause：讀 `starlette/testclient.py` 原始碼發現它現在優先 `import httpx2 as httpx`，只有找不到 `httpx2` 才 fallback 到 `httpx` 並印警告——不是版本問題，是套件本身已經轉向 `httpx2`。
- Fix：改安裝 `httpx2==2.5.0`，移除 `httpx`。
- How verified：`python -c "import starlette.testclient as m; print(m.httpx.__name__)"` 印出 `httpx2`；`pytest` 重跑後警告消失，`pip check` 無相依衝突。

#### Git / GitHub Practice
- 目前這個資料夾還不是 git repository，本次沒有實際的 branch/commit/PR 操作。
- 已在 `docs/WORKFLOW_SHORT.md` 中規劃：git 初始化與 Git/GitHub 基礎會另外獨立成一個完整教學的 Step，而不是附帶在其他 Step 裡處理。

#### Verification
- Tests run：`python -m pytest tests/ -v`（`backend/tests/test_ingestion.py`、`test_datasets_queries.py`、`test_datasets_api.py`）
- Result：36 passed（6 個 ingestion 測試 + 30 個 Dataset API 相關測試）
- Known limitations：沒有連真實資料庫的自動化整合測試（列為 Step 5 完成後的獨立待辦事項）；curl 驗收只涵蓋跑過的那幾個 case，不是自動化、不會在未來改動時自動重跑。

#### My Current Level
- Skill：API design、FastAPI dependency injection、SQL aggregation、分層測試策略
- Level：Level 2（Operate）到 Level 3（Build）之間——能看懂並審閱程式碼與測試設計、能主導架構決策（例如發現並要求修正 numeric 欄位數量、circular import 檢查），但這次 Step 5 的實際 command 執行主要由 Claude Code 完成
- Evidence：36 個 pytest 全數通過；curl 驗收涵蓋 200/404/422 全部路徑；四個小步驟的 plan 皆經過審閱與修正才進入執行

#### What I Can Explain Independently
- 為什麼要用 `Depends()` 而不是直接在函式內呼叫 `get_connection()`
- summary 統計為什麼不會出現 `NaN`
- pagination 的 `limit`/`offset`/`total` 分工
- 404 與 422 的差異與各自的測試策略

#### What Still Needs Practice
- 親自執行 pytest / curl 並獨立判讀輸出（尤其是失敗案例的 debug）
- 親自寫一個新的 query function 並補上對應的三層測試（query test / API test / curl）
- Git / GitHub 基礎操作（規劃為獨立 Step）

#### NVIDIA Interview Connection
- Problem：Step 4 之後資料寫得進去、讀不出來，Dashboard 與規則引擎都無法接上。
- My contribution：規劃並審閱四個 read-only 端點的設計，主動抓出並要求修正欄位數量錯誤、circular import 風險、排序 NULL 處理等細節。
- Technical decision：用 dependency override 取代真實 test database，在 MVP 階段用最小成本換取完整 HTTP 層測試覆蓋率。
- Trade-off：犧牲了「測試對真實資料庫行為的保證」，換取「不需要維護額外測試基礎設施」；用手動 curl 補足這個缺口。
- Validation：36 個 pytest 全數通過 + curl 驗收涵蓋 200/404/422 全部路徑。
- One-minute answer：見本次 Step 5 Teaching phase 的英文面試簡介段落。

#### Next Learning Step
- Step 6：Frontend Foundation（尚未開始）。
- 獨立待辦：真實 PostgreSQL test database 與完整 integration test framework。

