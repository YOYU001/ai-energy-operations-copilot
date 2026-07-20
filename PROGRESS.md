# PROGRESS.md

## Current Goal
打造 **AI Energy Operations Copilot MVP v1**，作為 NVIDIA 面試作品集與 AI 工程能力展示專案。

## Current Phase
Step 5 已完成 → Project Alignment Review 已完成 → Step 6：RAG Document Ingestion Spike 已正式結案（Go，8 個 sub-step 全數完成，結案紀錄見 docs/RAG_SPIKE_PLAN.md §18）→ **Step 7：Frontend Foundation — 驗收通過（完成）**，段落 A–F 全部完成，`npm run lint`／`npm run build` 通過。Step 10（Knowledge Base / RAG production integration）已完整規劃（schema gap analysis、migration order、rollback plan — docs/RAG_SPIKE_PLAN.md §17）但尚未執行；roadmap 順序維持不變（docs/PROJECT_ALIGNMENT_REVIEW.md §9）。下一步：**Step 8：Dashboard Charts**（聚焦 BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT 場景相關圖表，尚未開始）。

## Completed
- 定義 MVP v1 產品範圍、技術棧、Internal Knowledge Only 原則、初版 data schema，以及 Claude Code learning-by-building / 漸進式開發流程。
- 建立專案骨架資料夾（frontend/、backend/、database/、data/、scripts/）。
- 實作最小版 FastAPI backend，含 GET /health 與 GET /version。
- 實作資料庫基礎建設：透過 Docker 部署 PostgreSQL + pgvector、初版 7 張表的 schema（database/schema.sql）、SQLAlchemy 連線、GET /db-check。
- Step 4 — Dataset Ingestion：POST /datasets/upload（CSV 驗證、型別轉換、警告報告、寫入 datasets/energy_timeseries）。新增 ems_mode/equipment_status 的 canonical enum 驗證（詳見 docs/DECISIONS.md ADR-001）。6 個測試通過。
- 在 docs/WORKFLOW_SHORT.md 定義「Beginner Teaching Mode」與「執行與教學必須分離」的流程規則（單一標準 7 步驟工作流程：plan → confirm → execute → test → report → confirm → teach）。
- Step 5 — Dataset API：GET /datasets、/datasets/{id}、/datasets/{id}/summary、/datasets/{id}/timeseries，建立在可測試的 DI-based db connection 之上。共 36 個測試通過。已對實際 dev 資料庫驗證。
- 在 Step 6 開始前完成五階段 Project Alignment Review（確認能源垂直領域範圍、鎖定 16 項產品／架構決策、重新排序 Step 6–13 roadmap）。完整紀錄見 docs/PROJECT_ALIGNMENT_REVIEW.md。
- Step 6 Sub-step 1 — Test Corpus and Evaluation Set：選定 4 份 spike PDF，草擬 17 題固定測試問題（spike/test_questions.json）作為評估基準。詳見 docs/RAG_SPIKE_PLAN.md。
- Step 6 Sub-step 2 — PDF Parsing and OCR Validation：建立 spike/pdf_parser.py、spike/ocr_fallback.py；四態頁面分類（text/near_empty/scanned/ocr_failed）。7 個測試通過。詳見 docs/RAG_SPIKE_PLAN.md §3.1、§8。
- Step 6 Sub-step 3 — Chunking Design：建立 spike/chunker.py（4 種策略，含 table-aware row-group packing）。建議採用 structured_600_100。12 個測試通過。詳見 docs/RAG_SPIKE_PLAN.md §9。
- Step 6 Sub-step 4 — Embedding and Vector Storage Spike：建立 spike/hashing.py、embedding_provider.py、vector_store.py、schema_spike.sql；已對實際資料庫驗證 idempotent upsert（124 個 chunk、0 duplicate）。共 29 個測試通過。詳見 docs/RAG_SPIKE_PLAN.md §10。
- Step 6 Sub-step 5 — Hybrid Retrieval Scoring：建立 spike/query_parser.py、hybrid_retrieval.py（semantic + date-match + table-match 加權評分）。已對實際資料庫驗證；修正 Sub-step 4 一個因 preview 截斷而誤判的問題（q06 的 retrieval 結果其實一直是正確的）。共 43 個測試通過。詳見 docs/RAG_SPIKE_PLAN.md §11。
- Step 6 Sub-step 6 — Active Chunk Lifecycle / Blue-Green Cutover：schema 新增 supersedes_document_id 欄位；新 chunk 一律以 is_active=false 先行 ingest，再於單一 transaction 內原子化切換（啟用新的、停用被取代的），並附 rollback 與異常防護機制。Retrieval 查詢現在會過濾 is_active=true。新增 9 個測試，累計 52 個測試通過。已用一份可拋棄的測試文件對實際資料庫驗證（既有的 124 個 doc1/doc3 chunk 未受影響）。詳見 docs/RAG_SPIKE_PLAN.md §13。
- Step 6 Sub-step 7 — Retrieval Evaluation Dataset Expansion：測試集從 17 題擴充到 29 題；建立 spike/retrieval_metrics.py 與 spike/run_retrieval_benchmark.py。累計 69 個測試通過。以實際資料庫跑 benchmark：hybrid retrieval 在 hit@1 上勝過 vector-only（7/11 對 5/11），無 regression；global scope 揭露真實存在的 cross-document interference（16.4%）。詳見 docs/RAG_SPIKE_PLAN.md §14。
- Step 6 Sub-step 8 Phase 1 — doc4 Table Detection（僅離線分析，未 ingest）：為 spike/chunker.py 新增第二條「caption-first」table-detection 路徑，對應 doc4「caption 在前、資料在後」的表格風格，與 doc3 既有路徑各自獨立。新增 8 個測試，累計 77 個測試通過。實際跑 doc4 的結果：18 個表格中有 14 個被正確偵測（其餘 4 個沒有可擷取的表格文字，已確認不是 heuristic 的缺陷）；doc1/doc2/doc3 不受影響。詳見 docs/RAG_SPIKE_PLAN.md §15。
- Step 6 Sub-step 8 Phase 2 — doc4 Ingestion：透過既有的 blue-green lifecycle 將 doc4（157 個 chunk：143 個 prose + 14 個 table）ingest 進 spike_document_chunks；呼叫 2 次 embedding API、共 72,049 tokens、0 個失敗，並重新驗證 idempotency（重跑時 0 次呼叫／0 筆新增）。已對資料庫驗證：157/157 全部 active、0 個 null embedding、0 個重複 chunk_id。q27/q28 轉為 retrieval_eval_eligible=true（hit@3/5 已確認）；q15 維持 false —— 已確認 ground truth chunk 確實存在於資料庫中，但實際的 vector-similarity search 在 pool_size=30 的範圍內始終無法將其檢索出來（已記錄，本輪不修）。正式 benchmark 重跑結果：doc1/doc3 的指標與 Sub-step 7 完全相同（hybrid 7/11 對 vector-only 5/11，以 hit@1 計），零 regression。累計 113 個測試通過。詳見 docs/RAG_SPIKE_PLAN.md §16。
- 本機開發工具鏈架構（非 RAG spike 的 sub-step，於 Sub-step 8 期間同步建置）：`.claude/agents/`（research.md 用 haiku、qa.md 與 reviewer.md 用 sonnet，各自限制可用工具範圍）以及 `.claude/skills/`（db-bootstrap、progress-lint、chunk-inspect、embed-cost-estimate、ocr-page-diagnose、retrieval-debug 等腳本型 skill，加上呼叫對應 agent 的 /research、/qa、/review command skill）。9 項全數以真實專案資料與真實 subagent 呼叫驗證過（db-bootstrap 有實際執行；/qa、/research、/review 各自真的呼叫了對應 agent 並回傳格式正確的報告）。
- reviewer subagent 第一次真實審查（spike/hybrid_retrieval.py）發現 2 個真實的 LOW-severity 問題，均已修正：`fetch_candidates` 的 `ORDER BY` 重新計算了 vector-distance 運算式，而不是重複使用 `distance` 這個 SELECT alias；`run_hybrid_query` 的 `filename_filter` 型別提示原本是 `str`，應為 `str | None`，與 `fetch_candidates` 已記載的「支援 unscoped query」行為不一致。修正後 113 個測試通過，無 regression。
- Step 6 結案：8 個 sub-step 全數完成後正式驗收通過（Go）。最終採用的決策、非阻塞性的已知限制，以及 Step 10 production integration 計畫（schema gap analysis、migration order、reuse/refactor list、測試層級、rollback plan）均記錄於 docs/RAG_SPIKE_PLAN.md §18 與 §17。依使用者決定，roadmap 順序維持不變，未新增 ADR。113 個測試通過；doc1/doc3/doc4 共 ingest 281 個真實 chunk；17 題符合資格的 benchmark 問題（doc1/doc3 上 hit@1 64%／hit@3 91%／hit@5 100%，零 regression）。
- 新增一支 PreToolUse hook（`.claude/settings.json` + `.claude/hooks/check_conda_env.ps1`），會擋下任何未指名 `AI_Copilot` 環境的 Bash-tool `python` 呼叫，讓 CLAUDE.md 的 Python Environment Rules 自動生效、不再依賴人工記憶——這取代了原本只寫在 Gotchas 文字裡的做法，起因是本次 session 修 hybrid_retrieval.py 時真的誤用了 base 環境。已在全新 session 中端對端驗證：裸的 `python` 指令會被正確擋下並附上根據 CLAUDE.md 的理由，`conda activate AI_Copilot && python ...` 會被正確放行，非 python 指令則不受影響。
- 新增第二支 PreToolUse hook（`.claude/hooks/check_md_language.ps1`，註冊於 `.claude/settings.local.json`），會擋下內文以英文為主的新建 `.md` 檔案，落實 CLAUDE.md 的「回覆語言規則」。驗證過程中修正兩個真實 bug：腳本需要 UTF-8 BOM 才能在 Windows PowerShell 5.1 下正確解析中文註解，以及 `[Console]::InputEncoding` 必須明確設定才能正確讀取 piped stdin。已在全新 session 中端對端驗證（英文為主的 `.md` 被擋下、中文 `.md` 正常放行）。
- 透過 `.mcp.json` + `.claude/settings.local.json` 的 `enabledMcpjsonServers` 連接 Context7 MCP（`@upstash/context7-mcp`），依使用者決定採用 project-scoped（而非帳號層級）的長期連線，安裝前已用 WebSearch 驗證過套件來源。已在全新 session 中端對端驗證：正確回傳目前最新的 FastAPI `Depends`/`Annotated` 用法，並將答案連結回 `backend/app/db.py` 實際的 dependency-injection 用法。
- 新增 `trend-scout` subagent（`.claude/agents/trend-scout.md`，sonnet，僅限 WebSearch/WebFetch）與對應的 `/trend-scout` command skill —— 與 `research`（針對特定任務查資料）角色不同：trend-scout 會主動從不限來源的公開資訊調查業界做法（chunking、OCR、RAG、agent 設計），對來源可信度分級，且不會直接建議立即採用。已端對端驗證：一次真實的 chunking 策略趨勢查詢，正確區分出可信的 arXiv 來源與可信度較低的 SEO 部落格，並將結論連結回 `docs/RAG_SPIKE_PLAN.md` 既有的 `structured_600_100` 決策，判斷目前尚無需變更。
- Step 7 — Frontend Foundation：驗收通過。Next.js 骨架、Overview／Datasets 真實串接 FastAPI，lint/build 通過。Details: docs/STEP7_FRONTEND_PLAN.md §11。

## Important Decisions
- Frontend：Next.js
- Backend：FastAPI
- Database：PostgreSQL
- Vector Search：優先使用 pgvector，Chroma 僅作為 fallback
- Default mode：Internal Knowledge Only
- MVP v1 優先採用 rule-based 分析，不使用 optimization algorithms。
- MVP v1 應聚焦於 dashboard + 結構化分析 + AI assistant，不只是聊天介面。

## MVP v1 Scope
MVP v1 應涵蓋：
- 內部文件知識庫問答
- CSV 能源時間序列資料匯入與分析
- 固定圖表 Dashboard
- Rule-based 異常診斷
- 簡化版相似案件搜尋
- Rule-based 儲能排程建議
- 成本估算
- Green Operations Index / 綠能營運指數
- 角色化回答模式
- 分析報告產生

## Out of Scope for MVP v1
除非使用者明確核准，否則不實作：
- Real EMS control
- Real web search
- Optimization algorithms
- Self-trained PV/load forecasting models
- Multi-agent architecture
- Full carbon accounting / ESG reporting
- Real power trading integration
- Real ancillary service revenue calculation

## Current Known Issues
- Frontend 手機寬度的 responsive 行為（Sidebar 收合）尚未以真實窄 viewport 截圖完成視覺驗證；已用程式碼審查確認 `md:` breakpoint 與 toggle 邏輯正確，列為非阻擋性限制。
- 開發階段的 `error.tsx` 畫面仍可能直接顯示完整 backend URL 與底層錯誤訊息（例如 `Failed to reach backend at http://localhost:8000/...`）；正式環境前需要評估是否要遮蔽內部網址與錯誤細節。
- 範例 CSV dataset 尚未建立。
- RAG ingestion pipeline 尚未實作。
- Rule-based 分析邏輯尚未實作。
- 尚無 ORM model。
- 尚無 Alembic migration。
- 需要保持 Docker Desktop 執行中，資料庫相關 endpoint 才能運作。
- 尚無 authentication。
- 尚無防止重複上傳的機制。
- 目前的 batch insert 方式適用於 MVP 規模的資料集，但尚未針對大量資料 ingestion 做 benchmark 或優化。
- `DOCUMENTATION_FIX_REPORT.md` 與 `VALIDATION_RESULTS.md` 仍留在 repository 根目錄；暫時保留，待之後決定是否歸檔或移除。
- Repository 尚未初始化為 git repository；git 初始化規劃為獨立、完整教學過的一個 Step，而非附帶在其他 Step 裡順便做。
- 尚無針對真實資料庫的自動化整合測試（Step 5 的測試使用 fake connection）；列為獨立後續項目，不屬於 Step 5 或 RAG spike 的範圍。
- Data lifecycle 欄位（status/version/effective_from/effective_until/archived_at/deleted_at/superseded_by/retention_until）已確認可在不需大改的情況下加入 schema，但尚未加入；時機留待實際需要時再處理。
- 詳細風險與盲點（幻覺、citation 準確性、OCR 品質、confidence 門檻、成本等）已記錄於 `docs/PROJECT_ALIGNMENT_REVIEW.md` 第 6 節，此處不重複列出。

## Next Step
**Step 8：Dashboard Charts**（docs/PROJECT_ALIGNMENT_REVIEW.md §9，原 Step 7）—— 聚焦 `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT` 場景相關圖表。**尚未開始規劃或實作。** 下一步動作：比照 Step 7 的流程，先完成 Step 8 的教學與 implementation plan，經確認後再開始實作。依使用者決定，原始 roadmap 順序（docs/PROJECT_ALIGNMENT_REVIEW.md §9）維持不變：Step 10（RAG production integration）維持原訂排程，不提前。Step 6 剩餘的已知限制（q15 retrieval 盲點、q20 跨 chunk 失敗、doc4 有 5 個表格在句尾標點處被截斷、`is_active` 的保留／清理政策、q03/q04/q05 的 ground truth、`multi_chunk_coverage_threshold` 調整）已記錄於 docs/RAG_SPIKE_PLAN.md §18，列為可接受、非阻塞、延後至 Step 10 實際執行時再處理。

## Files To Read Next Time
每次一定要先讀：
- `CLAUDE.md`
- `PROGRESS.md`
- `docs/WORKFLOW_SHORT.md`

實作任務前依主題再讀：
- `docs/MVP_V1_SPEC.md`：產品範圍與 non-goals
- `docs/DATA_SCHEMA.md`：dataset、驗證邏輯、資料庫 schema
- `docs/DEVELOPMENT_WORKFLOW.md`：建置順序與實作流程
- `docs/MVP1_RULES.md`：rule-based 分析與排程邏輯
- `docs/SAMPLE_DATA_PLAN.md`：合成示範資料
- `docs/PROJECT_ALIGNMENT_REVIEW.md`：已確認的產品定義、決策紀錄、MVP 範圍、non-goals、風險、架構方向
- `docs/RAG_SPIKE_PLAN.md`：開始 Step 6 RAG Feasibility Spike 前必讀

只在相關時才讀：
- `docs/Claude_Code_Learning_Workflow.md`
- `docs/ANTHROPIC_LEARN_MAP.md`
- `docs/DECISIONS.md`
- `docs/OFFICIAL_UPDATE_LOG.md`
- `docs/LEARNING_LOG.md`
- `skills/*`

## Working Rule
每次只做一小步。修改前先說明，修改後要測試並回報。不要修改無關檔案，不要加入未討論功能。
