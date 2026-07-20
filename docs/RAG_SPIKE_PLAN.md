# Step 6: RAG Document Ingestion Spike

> 用途：保存 Step 6（RAG Document Ingestion Spike）的範圍、驗證項目、不做項目、驗收輸出與下一個最小步驟。
> 定位：詳見 `docs/PROJECT_ALIGNMENT_REVIEW.md` 第 8、9 節與 `docs/DECISIONS.md` ADR-007。這是**新 Step 6**，插入在原本 Step 6（Frontend Foundation，現為新 Step 7）之前。

子步驟命名：
- **Sub-step 1: Test Corpus and Evaluation Set**（已完成，見第 7 節；17 題已落檔 `spike/test_questions.json`，含 `verification_tier`）
- **Sub-step 2: PDF Parsing and OCR Validation**（已完成並驗收，見第 8 節）
- **Sub-step 3: Chunking Design**（已完成並驗收，見第 9 節；`structured_600_100` 為 provisional 推薦策略，非最終定案）
- **Sub-step 4: Embedding and Vector Storage Spike**（尚未開始，見第 10 節）

---

## 1. 定位

RAG Document Ingestion Spike **不是**提前實作正式 RAG Step（新 Step 10），**不是**正式產品功能。它只負責驗證技術可行性，完成後回到正式 roadmap（新 Step 7 起）。

## 2. 範圍

- 3–5 份真實但非機密文件，含文字型 PDF 與掃描型 PDF，至少 1–2 份掃描 PDF 用於 OCR 驗證
- 10–20 題固定測試問題（需事先寫好，每題附「預期答案應該包含什麼」，才能之後判斷 retrieval/citation 準不準）
- OpenAI Embeddings + LLM（見 `docs/DECISIONS.md` ADR-004：provider 不寫死、設定集中管理、metadata 記錄 model/version）
- 簡單 script/notebook 等級，可用 pgvector，但不做完整 API 或 Frontend

## 3. 必須驗證的 10 項

1. 文字型 PDF 解析正確性
2. 掃描型 PDF 經 OCR 後文字可用性 — **範圍限制**：本次僅驗證單頁表單型 scanned PDF（新進人員實習表，1 頁、含表格與印章）。**不代表**多頁掃描報告、手寫紀錄、複雜工程圖面、低解析度掃描件之 OCR 表現，這些情境尚未驗證，不可從本次結果直接推論。
3. 頁碼與來源 metadata 是否保留 — 統一 schema 見第 3.1 節
4. Chunking 是否保留足夠語意
5. Top-k retrieval 是否找到正確段落
6. Citation 是否指向正確文件與頁碼
7. 回答是否能清楚區分：已確認事實 / 可能原因 / 一般背景知識 / 下一步建議（對應 `docs/MVP1_RULES.md` 第 8 節七部分結構的可行性）
8. 證據不足時是否能保守回答、不硬猜
9. 表格、圖表、圖片、掃描品質造成的限制
10. Embedding model/version 是否被記錄，是否保留未來重新 embedding 的能力

### 3.1 頁碼與來源 metadata 統一 schema

| 欄位 | 型別 | 定義 |
|---|---|---|
| `page_index` | int | 0-based，程式內部使用 |
| `pdf_page_number` | int | 1-based，等於 `page_index + 1`，代表 PDF viewer 顯示的實體頁碼 |
| `printed_page_number` | str \| null | 頁面上印刷的頁碼（如 `"I"`、`"52"`）；無法可靠辨識時為 `null`，不可猜測 |
| `section_title` | str \| null | 頁面所屬章節標題；無法可靠辨識時為 `null`，不可猜測 |

`pdf_page_number` 與 `printed_page_number` **不保證相等**——報告類文件常有封面、聲明頁、摘要（羅馬數字）、目錄等前置頁，導致印刷頁碼相對 PDF 實體頁碼有位移量，且位移量因文件而異，程式不可寫死固定轉換公式。

## 4. Spike 不做

- 不做正式 UI
- 不做完整文件管理
- 不做正式 ingestion pipeline
- 不做完整權限系統
- 不做 NAS 部署
- 不做地端 LLM
- 不做大量文件壓力測試
- 不做 unrestricted Text-to-SQL
- 不提前整合完整 AI Assistant

## 5. 驗收輸出

1. 測試文件清單
2. 測試問題與預期答案
3. Retrieval 結果
4. Citation 正確性結果
5. OCR 成功與失敗案例
6. 已知限制
7. 是否適合進入正式 RAG 開發（新 Step 10）
8. 對新 Step 10 正式架構的建議
9. 是否需要調整新 Step 6 之後的 roadmap

## 6. 執行注意事項

- 建議 spike 程式碼放在獨立資料夾（例如 `spike/` 或 `experiments/`），和 `backend/app/` 的正式程式碼分開，避免拋棄式探索程式碼被誤認成正式功能的一部分。
- 實際開始寫 spike 時會需要新套件（PDF 解析、OCR、OpenAI SDK 等），依專案既有規則，安裝前需先詢問使用者、確認版本、同步更新 `requirements.txt`/`environment.yml`。
- 相似度門檻與 confidence 分級的具體數值規則，不在這次規劃階段預先假設，由 spike 第 3 項「Retrieval 結果」與第 4 項「Citation 正確性結果」的實測數據決定。

## 7. Sub-step 1 修正記錄（測試問題設計）

Sub-step 1 產出的 17 題測試問題中，事後審查發現並修正以下兩項：

- **Q6（表格相關問題）標準答案原本有誤**：原答案誤將 2024 年 8 月 30 日的超約事件寫成「3 個時段、5 筆資料列」。重新核對「低碳綠能與儲能整合技術研究」表 4 原始內容後，修正為：
  - 超約事件數：**2**（兩個不連續的超約發生時段，各自獨立）
  - 連續時段數：**2**（10:30–11:15、14:00–14:45）
  - timestamp／資料列數：**6**
  - 這也確立了「事件數」「時段數」「timestamp 數」「資料列數」是四個需分開定義的獨立指標，不可混用。
- **Q17 獨立分類為 `Capability Boundary Test`**：原本歸類於「表格/圖表相關」，但 Q17 測試的是「系統知不知道自己解析不了圖表曲線」（能力邊界的自我認知），與 Q6/Q7 測試「有沒有正確解析表格內容」性質不同，故獨立為第 8 種問題類型。

完整 17 題問題與預期答案已落檔為 `spike/test_questions.json`，作為 chunking/retrieval/citation 驗收的固定 evaluation baseline。頁碼引用的可信度分層記錄在該檔 `_meta.page_reference_status_note`：僅 q06（表4）已依第 3.1 節 schema 完整重新核對，其餘 16 題的 `pdf_page_number` 沿用 Sub-step 1 當時的原始頁籤引用（相信 pdf_page_number 本身正確，但 `printed_page_number`／`section_title` 未逐一重新核對，故留白，非猜測）。

## 8. Sub-step 2 執行結果（PDF Parsing and OCR Validation）

**狀態：已完成，含一次驗收後修正。**

- 新增檔案：`spike/pdf_parser.py`（逐頁文字擷取 + 四類頁面分類 + 頁碼/章節 metadata heuristic）、`spike/ocr_fallback.py`（easyocr 繁中+英文 OCR fallback）、`spike/run_parsing_validation.py`（對 4 份 PDF 執行解析並輸出報告）、`spike/tests/test_pdf_parser.py`（7 個 pytest，全數通過）。
- 套件安裝：`pymupdf==1.28.0`、`torch==2.13.0+cpu`（CPU-only，已確認 `torch.cuda.is_available() == False`）、`easyocr==1.7.2`，已同步寫入 `requirements.txt` 與 `environment.yml`，並在全新 conda 環境（`pip install -r requirements.txt` 與 `conda env create -f environment.yml` 兩種路徑）驗證過完整可重裝，非僅目前環境可 import。
- **頁面分類修正**：原本只用「文字 < 20 字元」單一門檻判定 scanned，會把合法近乎空白頁誤判成掃描頁。修正為四類：`text` / `near_empty` / `scanned` / `ocr_failed`，判斷邏輯：文字量低於門檻時，再看頁面圖片覆蓋率（`image_coverage_ratio`，用 `page.get_image_info()` 各圖片 bbox 面積加總 / 頁面面積估算）——覆蓋率 ≥ 50% 判定為 `scanned`（觸發 OCR），否則為 `near_empty`（不觸發 OCR）；OCR 執行後若文字量仍低於門檻，重新分類為 `ocr_failed`。
- 4 份文件最新實測結果（`spike/doc_summary.json`）：
  - `新進人員實習表.pdf`：1 頁，`{"scanned": 1}`，OCR 成功擷取 809 字元，可辨識出劉宥羽、廖健翔、114年09月22日等關鍵資訊（對應 Sub-step 1 的 Q11/Q12）。
  - `2415-1305研究報告-太陽光發電預測.pdf`：56 頁，`{"text": 56}`。
  - `2415-1304研究報告-智能貨櫃屋 .pdf`（低碳綠能與儲能整合技術研究）：87 頁，`{"text": 87}`。
  - `A 完整版本 鋰電池二次利用之電池管理系統開發研究完成報告.pdf`：120 頁，`{"text": 119, "near_empty": 1}`，**0 次 OCR**。原本被誤判為 scanned 的 `page_index=16`（`pdf_page_number=17`），經 PyMuPDF 實際渲染成圖片並目視確認後，證實是前置頁與正文間的空白分隔頁（僅印刷羅馬數字「XIII」，無圖片內容），修正後正確分類為 `near_empty`、不再觸發 OCR。
- 頁碼 metadata 驗證：以「低碳綠能與儲能整合技術研究」為例，實測確認 `page_index=11`（0-based）對應 `printed_page_number="1"`（本文第一頁），前置頁（封面/聲明/書脊/標題/摘要 I–IV/目錄 V–VII）共 11 頁造成的位移量與第 3.1 節 schema 定義一致。
- `section_title` heuristic（僅比對「一、...」「X.Y ...」等明確標題格式）在測試中運作正常，但尚未大規模驗證涵蓋率，屬於下一輪可以加強的項目。
- 目前 4 份文件皆未實際觸發 `ocr_failed` 狀態（`scanned` 頁面的 OCR 都成功超過門檻）；`ocr_failed` 分支邏輯已寫好並在程式碼層級可達，但尚無真實案例驗證，是已知的測試覆蓋缺口。

## 9. Sub-step 3 執行結果（Chunking Design）

**狀態：已完成。**

- 新增檔案：`spike/chunker.py`（四種策略：`fixed_baseline_600_100` + 三組 `structured_{400,600,800}_{80,100,120}`）、`spike/run_chunking_comparison.py`（跑 4 份文件 × 4 策略並輸出比較報告）、`spike/tests/test_chunker.py`（12 個 pytest，全數通過，含真實文件的表 4 迴歸測試）。
- 表格處理採第一次規劃修正後的規則：表格不強制單一 chunk，改為依「row group」（此語料表格中每個日期底下的完整資料列群組）為不可切割的最小單位貪婪打包；每個 table chunk 都重複表名與欄位標題。表格偵測本身是針對本語料實際觀察到的結構（單位標註表頭如 `(kW)`/`(%)`、表 4 標題出現在表格「之後」而非之前）調校的 heuristic，不是通用表格解析器，僅對 doc3 的表 4（日期索引表）有效——doc4 的表格未被偵測到，全部落入 prose chunk，這是誠實記錄的已知限制，不是 bug。
- `test_questions.json` 已補上 `verification_tier`（`verified`=2 題 q06/q11、`partially_verified`=11 題、`unverified`=4 題），正式的答案完整率只用 2 題 `verified` 計算。
- 完整比較結果與驗收詳見下方對話中的執行報告；已存檔 `spike/chunking_comparison_report.json`。
- **Provisional 推薦策略：`structured_600_100`**（不是最終定案）——三組 structured 策略在 2 題 verified 完整率上全部打平（2/2），差異只在切分粒度；`600_100` 的平均長度（500 字元）、table chunk 數（3）介於 `400_80`（較破碎，524 chunks）與 `800_120`（table chunk 曾超出上限至 921 字元）之間，是本輪僅能用 chunk 邊界品質判斷、尚未接上真實 retrieval 時的合理折衷。Sub-step 4 必須保留重新比較策略的能力，不可把它寫死成唯一選項。
- **目前 chunk metadata 欄位**：`source_filename`、`page_index_range`、`pdf_page_number_range`、`printed_page_number_list`、`section_title`、`chunk_type`（`table_title` 為 table chunk 專屬）。**下一步（Sub-step 4）需補**：`chunk_id`（目前 `Chunk.chunk_id` 已存在但格式未正式定案為跨 sub-step 穩定 ID）、`document_id`、`strategy_name`（已存在於 `Chunk` dataclass）、`content_hash`。
- **已知限制（彙整）**：
  1. 表格偵測目前主要針對表 4 這類「日期索引表」，`A 完整版本…BMS報告.pdf` 的表格尚未被辨識為 table chunk，落入 prose chunk。
  2. Overlap 的頁碼 attribution 是近似值（沿用前一個 chunk 最後一段內容的頁面資訊），未精確追蹤 overlap 文字片段本身跨越的頁碼邊界。
  3. 段落偵測依賴「行首縮排」heuristic，跨頁段落延續行若缺少該縮排特徵可能被誤判為新段落。
  4. `verified` 題目只有 2 題（q06、q11），樣本數小；`partially_verified`（11 題）與 `unverified`（4 題）僅供人工觀察，不可當作正式 accuracy。
  5. `structured_600_100` 尚未經過真實 retrieval 驗證，只是 chunk 邊界品質這一層的合理折衷。
  6. Table chunk 可能超過 nominal chunk size；已於 Sub-step 4 這輪修正為明確規則：容許超出 20%（`MAX_ROW_GROUP_OVERSHOOT_RATIO=1.2`），超過則依「完整資料列」（而非任意字元邊界）再分割，單一資料列本身仍不可被拆開。已補單元測試涵蓋此路徑（含真實文件與合成大表格兩種情境）。
  7. `ocr_failed` 狀態的分支邏輯已寫好但尚無真實案例觸發過，測試覆蓋率上是缺口。

## 10. Sub-step 4 執行結果（Embedding and Vector Storage Spike）

**狀態：已完成。**

- 新增檔案：`spike/hashing.py`（決定性 `chunk_id`／`embedding_content_hash`／`chunk_metadata_hash`）、`spike/embedding_provider.py`（`EmbeddingProvider` 抽象 + `OpenAIEmbeddingProvider`）、`spike/vector_store.py`（idempotent upsert 邏輯）、`spike/schema_spike.sql`（`spike_documents`/`spike_document_chunks`，**未修改**正式 `database/schema.sql`）、`spike/run_embedding_ingestion.py`、`spike/run_retrieval_smoke_test.py`；新增 15 個 pytest（`test_hashing.py`/`test_embedding_provider.py`/`test_vector_store.py`），全部搭配 fake/mock，不打真實 API 或 DB。
- 套件：`openai==2.45.0`，已確認與 Python 3.11 相容並寫入 `requirements.txt`/`environment.yml`。
- `chunk_id` 重新設計為**決定性 hash**（`sha256(document_content_hash + strategy_name + chunk_type + page_index_range + embedding_content_hash)`），不依賴 SERIAL id；文字不變則 `chunk_id` 不變，文字改變則自動產生新 `chunk_id`（舊列不刪除，僅遺留為孤兒列，尚未實作 archival/is_active 切換）。
- 真實環境驗證：pgvector extension（0.8.5）於既有 Docker 容器確認可用；對 doc1（新進人員實習表，驗證 Q11）+ doc3（低碳綠能報告，驗證 Q6）用 `structured_600_100` 完整 ingestion，寫入 124 個 chunk（doc1: 2、doc3: 122，含 3 個 table chunk），0 duplicate chunk_id，0 null embedding。
- Idempotent 驗收（真實 DB）：第二次 ingestion **0 個新 embedding API 呼叫、0 個新增列、124 個 unchanged_skipped**；「metadata 改變時更新、text 不變時不重新 embedding」則由 `test_vector_store.py` 的 3 個情境化單元測試覆蓋（未在真實 DB 上額外花費 API 成本重複驗證）。
- Retrieval smoke test（真實 pgvector brute-force cosine 查詢，無索引）：q06、q11 的 top-5 皆命中與 `expected_location` 重疊的頁碼範圍。**當時記錄的限制**：q06 top-1 的 `text_preview`（僅前 150 字元）顯示的是 8/21 那一段，因此推測「檢索到錯誤日期列」。**此推測已於 Sub-step 5 更正**：對該 chunk 的完整 `text`（547 字元，非截斷 preview）查詢後發現，該 chunk 實際上完整包含 8/21、8/30（全部 6 筆列，含 10:30–11:15、14:00–14:45 兩個連續時段）、9/7、9/12 四個日期的資料——因為 `structured_600_100` 的 packing 邏輯把多個 row group 打包進同一個 chunk。也就是說 top-1 從一開始就是正確答案的完整依據，只是 Sub-step 4 的判斷誤把「150 字元 preview 看起來是哪個日期」當成「chunk 實際內容是哪個日期」，這是一個判讀失誤，不是 retrieval 失誤。詳見第 11 節。
- 費用：pass 1 總計 61,946 tokens（doc1 1,110 + doc3 60,836），依 OpenAI 官方公開費率（`text-embedding-3-small` $0.02 / 1M tokens）估算約 **US$0.0012**，實際帳單金額請以 OpenAI 帳戶後台為準。

## 11. Sub-step 5 執行結果（Hybrid Retrieval Scoring）

**狀態：已完成。**

- 新增檔案：`spike/query_parser.py`（`extract_date_candidates`：只辨識「YYYY年M月D日」格式，容錯 PDF 抽取產生的不規則空白；`looks_like_table_question`：只辨識「表<數字>」樣式）、`spike/hybrid_retrieval.py`（`fetch_candidates` 取得 top-30 vector candidate pool、`score_candidates` 計算可解釋的 hybrid score、`WEIGHTS` 集中定義權重）、`spike/run_retrieval_comparison.py`（同一批 candidate pool 同時輸出 vector-only 與 hybrid 兩組排名，避免重複 embedding API 呼叫）；新增 `spike/tests/test_query_parser.py`（9 個）、`spike/tests/test_hybrid_retrieval.py`（5 個）。未修改 `schema_spike.sql`、未重新 ingest、未安裝新套件。
- **Scoring 公式**：`final_score = WEIGHTS["semantic"] * (1 - vector_distance) + (WEIGHTS["exact_date_match"] if 命中 else 0) + (WEIGHTS["table_query_match"] if 命中 else 0)`，其中 `WEIGHTS = {"semantic": 1.0, "exact_date_match": 0.5, "table_query_match": 0.2}`。當 query 沒有日期、也不像表格問題時，`final_score` 退化為 `1 - vector_distance` 的單調轉換，排序與 vector-only baseline 完全相同——這個「無訊號時自動退回 baseline」的性質由 `test_no_signals_preserves_vector_only_order` 驗證，不是額外的 fallback 分支邏輯。
- **重大更正發現**：q06 的正確答案 chunk（`chunk_id=45693d37...`）在 vector-only 與 hybrid 兩種模式下都排名 **第 1 名**，且該 chunk 完整文字確實包含「2024 年8 月30 日」與其下 6 筆資料列。Sub-step 4 記錄的「top-1 是錯誤日期」限制，實際上是只看了 150 字元 `text_preview` 造成的判讀失誤，並非真正的 retrieval 缺陷。q11 維持 top-1 命中兩個姓名，未劣化。
- False-positive 檢查（q02、q05、q13，皆為 doc3、無日期、無「表N」字樣的問題）：三題的 `parsed_date_candidates` 皆為空、`table_query_detected` 皆為 `false`，hybrid 排序與 vector-only 排序**逐筆完全相同**（chunk_id 順序、rank 一致），確認 boost 沒有誤觸發。
- Table-aware routing 採「加分」而非「排除」設計：`table_query_match` 只在查詢像表格問題 **且** 候選本身是 `chunk_type == "table"` 時才加分，prose chunk 不會被直接排除，避免 query classifier 誤判時完全找不到答案。
- 真實 API 呼叫：本輪 5 題（q06/q11/q02/q05/q13）各呼叫 1 次 embedding API（vector-only 與 hybrid 共用同一次查詢向量與同一批 candidate pool），共 **5 次 API 呼叫、185 tokens**，成本可忽略不計（遠低於 $0.0001）。未重新 ingest 文件、未重新 embedding 既有 124 個 chunk。
- `python -m pytest spike/tests -v` → **43 passed**（Sub-step 2–4 原有 29 個 + Sub-step 5 新增 14 個）。
- 已知限制／風險：
  1. `CANDIDATE_POOL_SIZE=30` 是硬性上限；若正確答案的 vector distance 排在 30 名之外，exact-date-match 也救不回來（本輪 q06 沒有觸發這個邊界，因為它本來就排第 1 名）。
  2. `exact_date_match` 只認得「YYYY年M月D日」格式，若未來題目用「8/30」「8月30日」（無年份）等變體提問，目前不會被抽取到，會安靜地退回 vector-only 排序而非報錯——這是刻意的保守設計，但需要在之後擴充題庫時留意。
  3. False-positive 檢查目前只涵蓋 3 題（q02/q05/q13），樣本數小，尚不能視為完整的迴歸測試集。
  4. 本輪的「q06 top-1 其實一直是對的」這個更正，也連帶說明了 Sub-step 3/4 用 150 字元 `text_preview` 做人工判讀有失真風險；建議往後的驗收流程改為讀取完整 `text` 欄位再下結論。

## 12. 下一個最小步驟

## 13. Sub-step 6 執行結果（Active Chunk Lifecycle / Blue-Green Cutover）

**狀態：已完成。**

- 修改檔案：`spike/schema_spike.sql`（新增 `spike_documents.supersedes_document_id INTEGER NULL REFERENCES spike_documents(id)`，用 `ALTER TABLE ADD COLUMN IF NOT EXISTS`，nullable、可加性，不破壞既有資料）、`spike/vector_store.py`（`get_or_create_document` 新增 supersedes 查找與寫入；`upsert_chunks` 新增 `initial_is_active: bool = False` 參數，新 chunk 一律以此值寫入，不再依賴 schema default；新增 `ChunkLifecycleAnomalyError`、`_chunk_activation_counts`、`cutover_document_version`、`execute_cutover_if_needed`）、`spike/run_embedding_ingestion.py`（呼叫 `upsert_chunks(..., initial_is_active=False)`，並在 `stats.failed_chunk_ids` 為空時才呼叫 `execute_cutover_if_needed`）、`spike/hybrid_retrieval.py`、`spike/run_retrieval_smoke_test.py`（查詢皆加上 `AND c.is_active = true`）。新增 `spike/tests/test_chunk_lifecycle.py`（9 個測試，含一個支援 commit/rollback 語意的 in-memory fake connection）。
- **Lifecycle state 判斷方式**：`execute_cutover_if_needed` 不依賴「這次 run 是否剛建立新 document_id」這種執行期旗標，而是每次都直接查詢該 `document_id` 目前在資料庫裡的 `is_active`/`inactive` 實際列數：
  - `active>0 且 inactive==0` → `"already_active"`，視為正常 idempotent 重跑，不做任何切換。
  - `active==0 且 inactive>0` → `"activated"`，執行 atomic cutover。
  - `active==0 且 inactive==0` → `"no_chunks"`，這次 ingestion 沒產生任何 chunk，不切換。
  - `active>0 且 inactive>0` → 拋出 `ChunkLifecycleAnomalyError`，**直接中止、不做任何切換**，因為這違反「同一 document_id 同一時間只能有一種狀態」的不變量，需要人工排查。
- **首次失敗後重跑的結果**（真實情境模擬，見 `test_retry_after_partial_failure_eventually_completes_cutover`）：v2 版本兩個 chunk 用 `embed_batch_size=1` 分兩批寫入，故意讓第二批 embedding 失敗 → `stats.failed_chunk_ids` 非空 → 呼叫端**不呼叫** cutover → 舊版本（v1）保持 `is_active=true`、新版本（v2）只有第一個 chunk 以 `is_active=false` 寫入。用相同 `document_content_hash` 重跑，`get_or_create_document` 命中同一個 `document_id`，只需補齊缺的那個 chunk（沿用既有 idempotent chunk_id 邏輯），這次 `failed_chunk_ids` 為空，`execute_cutover_if_needed` 依「目前資料庫實際狀態」（v2 全部 inactive）判斷需要 cutover，成功切換：v2 全部 active、v1 全部 inactive。
- **Atomic cutover 與 rollback 測試**：`test_cutover_transaction_failure_rolls_back_completely` 用一個支援 undo log 的 fake connection，故意讓 deactivate 舊版本那一步拋出例外 → 斷言 `cutover_document_version` 的 `try/except` 呼叫了 `conn.rollback()`，新版本剛被 activate 的 chunk 被撤銷回 `is_active=false`，舊版本的 chunk 完全沒被動過、仍是 `is_active=true`——確認「activate 新的」與「deactivate 舊的」在同一個 transaction 內要嘛全部生效、要嘛全部不生效。
- **Active/inactive 混合異常測試**：`test_mixed_active_inactive_state_raises_anomaly_and_does_not_switch` 人工建構一個違反不變量的狀態（同一 `document_id` 底下一個 active、一個 inactive），呼叫 `execute_cutover_if_needed` 確認拋出 `ChunkLifecycleAnomalyError`，且狀態完全未被更動（不會靜默解決成任何一個方向）。
- **`activated == 0` 防呆確認未誤傷正常 idempotent 重跑**：`test_same_content_rerun_produces_no_lifecycle_change` 確認同內容重跑時，因為 chunk 早已 `is_active=true`（`inactive==0`），`execute_cutover_if_needed` 走的是 `"already_active"` 分支，**根本不會呼叫** `cutover_document_version`，所以 `activated==0` 的防呆檢查完全不會被觸發於這個正常路徑——防呆只保護「真的呼叫了 cutover 但新版本卻 0 個 inactive chunk 可啟用」這種異常情境。
- **Metadata-only update 確認不影響 `is_active`**：`test_metadata_only_update_does_not_change_is_active` 確認 `upsert_chunks` 的 metadata-only UPDATE 陳述式（沿用 Sub-step 4 既有邏輯）本來就沒有觸碰 `is_active` 欄位，文字不變只改 metadata 時，chunk 的啟用狀態不受影響。
- **Retrieval 過濾結果**：`hybrid_retrieval.fetch_candidates`（連帶 `run_retrieval_comparison.py` 的 vector-only 與 hybrid 兩種模式）與 `run_retrieval_smoke_test.py` 的 SQL 都加上 `AND c.is_active = true`；真實 DB 驗收中用一個獨立、不影響 doc1/doc3 真實資料的 throwaway 檔名（`__lifecycle_smoke_test__.pdf`）驗證：v1 cutover 後查詢只回傳 v1；v2 cutover 後查詢**只回傳 v2 的內容，v1 完全不會出現**（confirmed via 直接呼叫真實 `fetch_candidates`，非模擬）。
- `python -m pytest spike/tests -v` → **52 passed**（Sub-step 2–5 原有 43 個 + Sub-step 6 新增 9 個）。
- **真實 DB 驗收結果**：用 throwaway 合成內容（非真實 PDF，幾個字的純文字 chunk）跑完整流程：(1) 首次 ingestion → chunk 以 `is_active=false` 寫入 → cutover → 變成 `is_active=true`；(2) 同內容重跑 → 0 次新 embedding API 呼叫、`action="already_active"`；(3) 內容改變（v2）→ `supersedes_document_id` 正確指向 v1 的 `document_id`（`4 → 3` 實際觀測值）→ cutover 後 v1 全部 `is_active=false`（列仍存在，未刪除）、v2 全部 `is_active=true`；(4) 真實 `fetch_candidates` 查詢確認只回傳 v2 內容。額外確認：既有 doc1/doc3 的 124 個真實 chunk（`document_id=1,2`）在整個過程中完全未被觸碰，仍是 `is_active=true`、`supersedes_document_id=NULL`（`ALTER TABLE ADD COLUMN IF NOT EXISTS` 對既有列的預設值行為符合預期）；並重跑一次 `run_retrieval_comparison.py`（q06/q11/q02/q05/q13）確認加上 `is_active` 過濾後結果與 Sub-step 5 完全一致，無回歸。
- **API 呼叫與 token usage**：lifecycle 真實 DB 驗收（throwaway 合成內容）3 次 API 呼叫、20 tokens；`run_retrieval_comparison.py` 回歸重跑 5 次 API 呼叫、185 tokens；本輪合計 **8 次呼叫、205 tokens**，成本可忽略不計。未重新 ingest 或重新 embedding doc1/doc3 既有的 124 個 chunk。
- **新發現的限制**：
  1. `filename` 作為 logical document identity 的既有限制原樣保留：文件重新命名會被視為全新文件（`supersedes_document_id` 不會自動建立關聯）；不同資料夾中的同名文件可能被誤判為彼此的版本。這是本輪明確接受、記錄、但不解決的限制。
  2. `ChunkLifecycleAnomalyError` 目前只會停止當次 ingestion（拋出例外），沒有告警/通知機制——在 spike 階段這是可接受的，但正式環境需要搭配監控才能及時發現這種不變量違反的情況。
  3. 舊版本 chunk 永遠不刪除（沿用 ADR-005），這次 lifecycle 機制讓「舊」和「新」清楚可辨識，但清理/保留期限策略依然沒有實作，是明確留給未來獨立 sub-step 的工作。
  4. `cutover_document_version` 目前用兩個獨立的 `UPDATE` 陳述式（先 activate 後 deactivate）包在同一個 transaction 裡；在極高並發情境下，兩個文件版本同時被 ingest（理論上因為 `document_content_hash` UNIQUE 約束不會真的衝突，但競爭條件下的鎖等待行為未實測），這在 spike 規模下不是問題，正式環境需要時再評估。

## 14. Sub-step 7 執行結果（Retrieval Evaluation Dataset Expansion）

**狀態：已完成。**

- 新增檔案：`spike/retrieval_metrics.py`（`document_correctness`/`page_correctness`/`exact_content_correctness`/`evaluate_candidate`/`single_chunk_hit_rank`/`hit_at_k`/`multi_chunk_keyword_coverage`/`multi_chunk_success`/`hybrid_matches_vector_only_order`，全部純函式，不碰資料庫或 API，供 unit test 與 driver 共用）、`spike/run_retrieval_benchmark.py`（正式 benchmark driver，document-scoped 與 global 兩種 retrieval scope 都會跑）、`spike/tests/test_retrieval_metrics.py`（13 個測試）、`spike/tests/test_run_retrieval_benchmark.py`（4 個測試）。
- 修改檔案：`spike/test_questions.json`（17 題擴充為 **29 題**，見下方分布）、`spike/hybrid_retrieval.py`（`fetch_candidates` 的 `filename_filter` 改為 optional，`None` 時查詢全部 active chunk 不分文件；`ScoredChunk` 與查詢新增 `filename` 欄位；**這是唯一觸碰到 `hybrid_retrieval.py` 的改動，`score_candidates` 的公式與 `WEIGHTS` 完全沒有修改**，純粹是為了支援 global scope 查詢所需的最小、可解釋的 query 層變動）、`spike/tests/test_hybrid_retrieval.py`（既有 `_row()` fixture 補上 `filename` 欄位以配合上述改動，不影響任何既有斷言）。未修改 `chunker.py`、`vector_store.py`、`schema_spike.sql`。

### 題目總數及分布

29 題（原 17 題 + 新增 12 題：q18–q29）。`verification_tier`：`verified`=16、`partially_verified`=9、`unverified`=4。`retrieval_eval_eligible`=15（其中 13 題可做完整 hit@k/exact-content 評分，另外 q05、q13 只用於 false-positive 訊號檢查，沒有 `expected_content_keywords`）。

題型涵蓋（依你要求的 5 種類型，每種至少 1 題且皆為本輪程式碼實際驗證過）：
- **prose factual**：q02（變流器型號+功率，本輪修正頁碼 bug）、q18（切換時間+額定功率）、q19（28.8 年回收年限）、q25（doc1 OCR，洪健恆）、q27/q28（doc4，content-verified 但不 eligible）
- **table exact-row**：q06（既有）、q21（2024/5/26，4 筆）、q22（2025/6/15 SOC 變化）、q23（2024/10/27 負值放電 -0.6）
- **date/number**：q19、q22、q23、q26（doc1 OCR 日期+天數）
- **OCR**：q11（既有）、q25、q26
- **cross-chunk / 難檢索**：q05（既有，false-positive control）、q20（multi_chunk，儲能容量+建置成本，兩個真實不同 chunk）、q24（multi_chunk，10.9 kWp vs 5.45 kWp，文件本身數字不一致）

`false_positive_control=true` 共 4 題：q02（新增）、q05、q13（既有）、q29（新增，EneSense 雲端平台）。

### verified / eligible 題目數量

`verified` 且 `retrieval_eval_eligible=true`：**13 題**（q02、q06、q11、q18、q19、q20、q21、q22、q23、q24、q25、q26、q29），達成「至少 10 題」的要求。另外 3 題 `verified` 但 `retrieval_eval_eligible=false`：q15（doc4，本輪修正定位）、q27、q28（doc4，新增，皆為 ground truth 已驗證但無法查詢）。

### Single-chunk 與 multi-chunk 評估方式

- **single_chunk**（11 題可評分）：`evaluate_candidate()` 對排序後的候選清單逐一計算 `document_correct`/`page_correct`/`content_correct`（**讀完整 `text` 欄位**），`single_chunk_hit_rank()` 找出第一個三者皆為真的候選排名，`hit_at_k()` 換算成 hit@1/3/5。
- **multi_chunk**（2 題：q20、q24）：不要求任何單一 chunk 包含全部答案，改用 `multi_chunk_keyword_coverage()` 對 top-1/top-3/top-5 候選的**完整文字聯集**檢查每個關鍵字是否出現，`multi_chunk_success()` 依門檻（本輪預設 1.0，即所有關鍵字都要出現）判斷成功與否。

### Scoped 與 global retrieval 實際執行情況

兩種 scope 都跑了（成本可忽略：doc1+doc3 合計僅 124 個 chunk）：
- **document_scoped**：沿用既有 filename 過濾，`document_correctness` 恆為 true（by construction），如實標記為「不是有意義的訊號」。
- **global**：`fetch_candidates(filename_filter=None)`，跨 doc1+doc3 全部 active chunk 查詢。**真實發現**：q26（doc1 OCR 題）在 global 模式下，top-5 候選中有 doc3 的 chunk 混入排名前段（rank 2、4、5 都是錯誤文件），導致該題真正命中的排名從 document-scoped 的第 2 名退到 global 的第 3 名（但仍在 hit@5 範圍內，最終 hit@5 沒有變化）。全部 11 題 single_chunk 的 top-5 候選中，**110 個候選裡有 18 個（16.4%）是錯誤文件**，證實 document-scoped 查詢確實隱藏了跨文件干擾，global 模式才是唯一能真正測出 `document_correctness` 的模式。

### Vector-only 與 hybrid 的 Hit@1/3/5（11 題 single_chunk，兩種 scope 結果一致）

| 指標 | vector-only | hybrid |
|---|---|---|
| hit@1 | 5/11（45%） | **7/11（64%）** |
| hit@3 | 10/11 | 10/11 |
| hit@5 | 11/11 | 11/11 |

Hybrid 在 hit@1 有明確提升（q22、q23 從 rank 2 提升到 rank 1，都是靠 `exact_date_match` boost），且**沒有任何一題因為 hybrid 排序而變差**（無 regression）。這是繼 q06 之後，第一次在多題樣本上正式量化 hybrid 的效果，而非只看單一題目。

### Multi-chunk keyword coverage

- **q20**（儲能容量 10 kWh + 建置成本 $100,000）：vector-only 與 hybrid 皆為 `coverage@1=0.5, @3=0.5, @5=0.5`，**`success_at_5=False`**——`$100,000` 這個關鍵字在兩種模式下都**從未進入 top-5**。這是本輪一個誠實的負面發現：容量規格與投資成本分屬報告中相距很遠的兩個章節，語意向量檢索無法同時把兩者都拉進同一個小範圍的候選集。
- **q24**（10.9 kWp vs 5.45 kWp）：`coverage@1=0.5, @3=0.5, @5=1.0`，`success_at_5=True`——兩個關鍵字最終都在 top-5 內出現，但要到第 5 名才湊齊。

### False-positive 結果

q02、q05、q13、q29 四題在 document-scoped 與 global 兩種 scope 下，`hybrid_matches_vector_only_order` **全部為 `True`**——沒有任何一題因為 boost 誤觸發而改變排序，Sub-step 5 的結論在樣本數擴大後依然成立。

### 被排除題目與原因

共 14 題被排除（`retrieval_eval_eligible=false`），全部列在 `retrieval_benchmark_report.json` 的 `excluded_questions`：
- doc2 未 ingest：q01、q07、q08、q09（4 題）
- doc3 已 ingest 但本輪未建立 `expected_content_keywords`：q03、q04（2 題）
- doc4 未 ingest（ground truth 本輪已用真實 PDF/chunker 驗證，但無法查詢）：q15、q16、q27、q28（4 題）
- 無機械化 ground truth（capability-boundary/insufficient-evidence 題型，依設計本就不可評分）：q10、q12、q14、q17（4 題）

### pytest、API calls、token usage

`python -m pytest spike/tests -v` → **69 passed**（原 52 個 + 本輪新增 17 個：`test_retrieval_metrics.py` 13 個、`test_run_retrieval_benchmark.py` 4 個）。真實 DB 執行：document-scoped 與 global 各 15 次 embedding API 呼叫、635 tokens，**合計 30 次呼叫、1,270 tokens**，成本可忽略（未重新 ingest 文件、未重新 embedding 既有 124 個 chunk）。

### 新發現的限制

1. **q20 的 cross-chunk 檢索失敗是真實限制**：語意向量檢索無法把「同一份文件裡相距 27 頁的兩個相關數字」都拉進同一個小候選集，這比 Sub-step 5 的「同表不同日期」問題更難解決，因為兩個 chunk 在語意上幾乎不相關（硬體規格 vs 投資報表），純向量方法目前沒有機制能把它們關聯起來。
2. **Global scope 證實了跨文件干擾是真實存在的**（16.4% 的 top-5 候選來自錯誤文件），只是目前的小語料庫（僅 2 份文件）還不足以讓它真正拖垮 hit@5；文件數量增加後這個問題預期會惡化，值得在正式 Step 10 設計時納入考量。
3. `multi_chunk_coverage_threshold` 目前每題預設 1.0（要求全部關鍵字都出現），尚未針對不同難度的 cross-chunk 題目個別調整門檻，是可以進一步細緻化的地方。
4. q03、q04、q05 等既有 `partially_verified` 題目本輪仍未補上 `expected_content_keywords`，continued 是一個待補的技術債，不是本輪範圍。
5. doc4 的 3 題（q27、q28 新增、q15 修正）ground truth 已經很扎實，但只要 doc4 一天不 ingest，就一天無法真正驗證——這是下一個 sub-step candidate 的清楚候選項。

## 15. Sub-step 8 執行結果 — 階段一（doc4 Table Detection，離線，未 ingest）

**狀態：階段一已完成。階段二（真正 ingest doc4）尚未執行，需等待使用者確認。**

### 實際修改檔案
`spike/chunker.py`（新增獨立的 "caption-first" 表格偵測路徑，與既有 doc3 date-anchored 路徑完全分離）、`spike/tests/test_chunker.py`（新增 8 個測試：1 個 doc3 regression 鎖定測試、5 個合成資料機制測試、2 個真實 doc4 PDF 驗收測試；過程中也修正了這個檔案裡一段與本次任務無關的既有殘留重複內容）。未修改 `vector_store.py`、`schema_spike.sql`、`run_embedding_ingestion.py`、`test_questions.json`。未呼叫 embedding API，未寫入資料庫。

### Caption-first state machine 的實際規則
新增一個與既有 `state="table"`（doc3 date-anchored 路徑）完全獨立的 `state="table_captionfirst"`，只從 `state="prose"` 觸發，兩條路徑互不干涉：

- **進入條件**：一行符合 `CAPTION_FIRST_TITLE_RE`（`表N-M` 連字號格式，刻意不同於 doc3 用的 `表N.` 句點格式）且不含 ToC 的連續點號（`_TOC_DOT_LEADER_RE`），才會嘗試往前看（`_forward_table_body_run`）：先容忍最多 2 行空白（doc4 的表3-2、表4-1 標題與表頭之間確實有空行），接著要求緊接著至少 `MIN_CAPTION_FIRST_BODY_LINES=3` 行符合「像表格內容」的行（`_looks_like_table_body_line`：長度 ≤40 字元、結尾不是句子終結標點），且這幾行本身不能是下一個表格標題／圖片標題／章節標題（`_is_captionfirst_exit_line`，見下）。三個條件缺一都不算表格，退回當一般散文處理。
- **收尾條件**（滿足任一即結束，不消耗該行、重新用 prose 規則處理）：下一個表格標題（doc4 或 doc3 格式）、圖片標題（`圖N`）、**帶編號的章節標題**（`^\d+(?:\.\d+)+\s+\S`，例如「3.2.2 電池內部結構量測與失效分析」——這個訊號是本輪除錯過程中新增的，見下方 bug 記錄）、**跨頁**（進入下一個 `page_index` 就結束，不允許 caption-first 表格跨頁）、或該行不再符合「像表格內容」（例如遇到句尾標點的完整散文句子）。
- **Row 分組**：不嘗試判斷「這幾行是表頭、這幾行是資料」的界線（doc4 各表的 row-key 型態不一致：類別名稱、電池編號、無明顯 key），改為**每個物理行各自成一個最小打包單位**，依原始順序組成 `row_groups`，`header_line` 固定留空——完整內容（含表頭與資料）仍會依原始順序完整出現在最終的 chunk text 裡，只是不特別把表頭抽出來在多 chunk 時重複（這 14 個表都很小，實務上全部落在單一 chunk，不需要這個機制）。

### 除錯過程中發現並修正的 3 個真實 bug（誠實記錄，不是一次寫對）
1. **`_PARA_START_RE` 判斷是死碼**：`DocLine.text` 在 `_build_doc_lines` 已經 `.strip()` 過，這個檢查依賴的「行首空白」永遠不存在——這其實也是既有 doc3 路徑的同一段邏輯的既有問題，只是 doc3 剛好不依賴它就能正常運作，沒被發現。改用章節標題偵測 + 內容長度/標點判斷取代。
2. **`_SECTION_HEADING_RE` 正則的 regex backtracking 漏洞**：原本用 `\s*\S`（可以是 0 個空白），結果 `3.381` 這種純數字表格值也會被 regex 回溯（backtracking）誤判成「章節標題」，導致表3-2 的實際數值被提早截斷。改成 `\s+\S`（強制至少 1 個空白）後，`3.381` 因為完全沒有空白字元而不可能匹配，正確排除。
3. **entry lookahead 沒有共用 exit 判斷**：`_forward_table_body_run`（進入時的向前掃描）原本只檢查「像不像表格內容」，沒有檢查「是不是下一個表格標題」，導致表4-12 的向前掃描不小心把緊接著的表4-13 標題也吞進表4-12的內容裡（因為標題本身也符合「短、不以標點結尾」的表格內容特徵）。修正方式是把「是否為表格內容」與「是否為結束訊號」兩個判斷抽成共用函式 `_is_captionfirst_exit_line`，讓進入掃描與延續掃描用同一套規則，不會再互相矛盾。

以上 3 個 bug 都是**先跑真實 doc4 PDF、觀察實際輸出、發現不對、回頭修正**，不是憑空設計後就直接回報成功——過程中曾經歷「9 個表格但部分被截斷」→「15 個表格但部分吞入下一表」→最終「14 個表格、逐一人工核對內容完整」三個版本。

### doc4 四種 strategy 的 prose/table chunk 數量

| strategy | prose | table | total |
|---|---|---|---|
| fixed_baseline_600_100 | 121 | 0 | 121 |
| structured_400_80 | 203 | 14 | 217 |
| structured_600_100 | 143 | 14 | 157 |
| structured_800_120 | 104 | 14 | 118 |

三種 structured 策略偵測到的 table chunk 數量完全一致（14），代表偵測結果對 chunk_size 不敏感，是個好現象。

### 成功辨識的真實表格清單（14 / 18，78%）
`表2-1`、`表3-1`、`表3-2`、`表3-3`、`表3-4`、`表4-1`、`表4-4`、`表4-5`、`表4-6`、`表4-8`、`表4-10`、`表4-11`、`表4-12`、`表4-13`。其中 **4 個原始目標案例（表3-1、3-2、3-3、4-1）全部命中**，且逐一人工核對確認：`chunk_type=table`、`table_title` 完整、表頭存在、至少一筆真實資料、沒有吞入下一個表格或章節內容。另外 10 個是本輪 heuristic 泛化帶來的額外收穫（bonus），不是刻意為它們寫規則。

**已知不完整的案例（誠實記錄，非隱藏）**：`表2-1`（陰極材料比較表）、`表3-4`、`表4-1`、`表4-4`、`表4-6` 這幾個表格的儲存格內容是完整敘述句（不是短數值），在遇到第一個句尾標點（「。」）時就會停止收錄——例如表4-1 只完整收錄了 LFP 這一列，NMC/LTO 兩列被截斷在外。這是 `_looks_like_table_body_line` 拒絕句尾標點行的直接後果，是本輪刻意接受的權衡（詳見「新發現的限制」），不是本輪要解決的問題（不要求 row reconstruction）。

### 未辨識或誤判的表格清單與原因
`表4-2`、`表4-3`、`表4-7`、`表4-9`（4 / 18）**完全沒有被偵測到**——本輪額外確認：這 4 個表格的標題行**後面緊接著就是空白或下一段散文，PyMuPDF 完全沒有抽出任何格線資料文字**（原始頁面文字直接從標題跳到下一段敘述，中間沒有任何短行）。這與 Sub-step 8 規劃階段對 表4-3/4-4 的判斷一致：這些表格極可能是排版成圖片嵌入 PDF，不是真正的文字表格，屬於文字抽取層的問題，不是 chunker heuristic 能解決的範圍，本輪明確不計入成功率、不嘗試用 OCR/Camelot/pdfplumber 解決。**零誤判**：`_TOC_DOT_LEADER_RE` + `MIN_CAPTION_FIRST_BODY_LINES` 雙重防護下，doc4 表目錄頁（page_index=15）沒有產生任何 table chunk（新增專屬測試 `test_doc4_toc_page_produces_no_table_chunks` 鎖定這個行為）。

### doc1–doc3 regression comparison
逐一比對（用真實 PDF，doc1 含真實 OCR）：

| 文件 | 策略 | prose | table | total | 與 Sub-step 3/4 既有基準比對 |
|---|---|---|---|---|---|
| doc1 | structured_600_100 | 2 | 0 | 2 | 完全相同 |
| doc2 | structured_600_100 | 85 | 0 | 85 | 完全相同（doc2 從未有 table 偵測） |
| doc3 | structured_400_80 | 178 | 5 | 183 | 完全相同 |
| doc3 | structured_600_100 | 119 | 3 | 122 | 完全相同 |
| doc3 | structured_800_120 | 91 | 2 | 93 | 完全相同 |

doc3 的三組數字已經鎖進新測試 `test_doc3_regression_unaffected_by_captionfirst_path`，未來任何人改動 `chunker.py` 若不小心影響到 doc3，這個測試會立刻失敗。

### pytest 結果
`python -m pytest spike/tests -v` → **77 passed**（原 69 個 + 本輪新增 8 個）。

### 是否仍建議使用 structured_600_100
**是，維持建議**。加入 doc4 表格偵測後，`structured_600_100` 在 doc4 上的 table chunk 數量（14）與 `structured_400_80`/`structured_800_120` 完全一致，代表這次改動沒有引入新的 chunk_size 敏感性；同時 `structured_600_100` 仍然是 Sub-step 3 就已經確立的、在 chunk 碎片化與過大 table chunk 之間的合理折衷，這輪沒有出現需要重新評估策略選擇的新證據。

### 階段二 doc4 ingestion 的更新成本預估與風險
- **成本**：doc4 目前在 `structured_600_100` 下共 157 個 chunk（143 prose + 14 table），比原本估算的 147 個略高（因為部分 prose 被重新切成獨立的 table chunk，總 chunk 數小幅增加）。依 doc3 的實際費率（每 chunk 約 499 tokens）估算，doc4 ingestion 約 **78,000 tokens**，依 OpenAI 公開費率約 **US$0.0016**，與先前估算量級一致，可忽略不計；實際費用仍需以 ingestion 後的真實 API 回傳值為準。
- **風險**：(1) 4 個表格內容截斷在句尾標點處（表2-1/3-4/4-1/4-4/4-6），ingest 後這幾個 table chunk 的內容不完整，若之後要用它們設計新的 benchmark 題目，必須先讀完整 chunk text 確認截斷位置，不可假設內容完整；(2) doc4 ingestion 沿用 Sub-step 6 的 lifecycle 機制（deterministic chunk_id、idempotent、inactive-first、atomic cutover）完全不需要新程式碼，因為 doc4 是全新文件，走的是「沒有 `supersedes_document_id`、cutover 只需 activate」的既有已測試路徑；(3) ingest 後，`test_questions.json` 的 q15/q27/q28 三題需要重新確認 `retrieval_eval_eligible` 是否可以翻成 `true`——q27（1.4–1.6kWh）與 q28（8–12顆/10kWh）的關鍵字如果剛好落在被截斷的表格內容之外（它們原本落在 4.7 節的**散文段落**，不是本輪新偵測的 table chunk，所以不受截斷問題影響），但仍需 ingest 後實際查詢驗證，不可只憑理論推測。

## 16. Sub-step 8 執行結果 — 階段二（doc4 Ingestion，真實寫入 DB）

沿用 Sub-step 6 既有 blue-green lifecycle 機制，未修改 `schema_spike.sql`、`vector_store.py`、`chunker.py`、未新增 package。

### 實際修改檔案
- `spike/run_embedding_ingestion.py`：`DOCUMENTS` dict 新增 `"doc4": "A 完整版本  鋰電池二次利用之電池管理系統開發研究完成報告.pdf"`。
- `spike/run_retrieval_benchmark.py`：`DOC_ID_TO_FILENAME` 新增 doc4 對應，使正式 benchmark 能解析 doc4 檔名。
- `spike/test_questions.json`：q27、q28 的 `retrieval_eval_eligible` 翻為 `true`（移除 `eligibility_reason`，`verification_note` 補上 DB 內實際 chunk 與排名結果）；q15 保持 `false`，`eligibility_reason` 改為記錄「ground truth 已確認存在於 DB，但向量檢索在 pool_size=30 內完全撈不到」的真實失敗原因。

### ingestion pass 1（真實 OpenAI embedding API）
| 項目 | doc1 | doc3 | doc4 |
|---|---|---|---|
| total_chunks_considered | 2 | 122 | 157 |
| inserted_new | 0（既有） | 0（既有） | **157** |
| embedding_api_calls | 0 | 0 | **2**（batch size 96 → 2 batches） |
| total_tokens | 0 | 0 | **72,049** |
| failed_chunk_ids | [] | [] | [] |
| cutover_action | already_active | already_active | **activated** |

doc4 費用依 OpenAI text-embedding-3-small 公開費率（$0.02 / 1M tokens）約 **US$0.0014**，與 Sub-step 8 階段一預估（US$0.0016）及 `embed-cost-estimate` skill 估算（67,866 tokens，實際略高於估算，因 skill 用近似 tokenizer）同量級。

### ingestion pass 2（同一次執行內，idempotency 驗證）
doc1/doc3/doc4 三份文件皆為 **0 embedding_api_calls、0 inserted_new、100% unchanged_skipped**（doc4：157/157 skipped），`cutover_action` 全部回報 `already_active`。Idempotency 驗證通過。

### DB 驗證（直接查詢 `spike_document_chunks`，document_id=5）
- 總數 157（143 prose + 14 table），與規劃值完全一致。
- `is_active=true` 157、`is_active=false` 0。
- `embedding IS NULL` 0 筆。
- 依 `chunk_id` group by 無重複列。
- `spike_documents.supersedes_document_id` = NULL（doc4 是全新文件，非既有文件的新版本，理論上必須為 NULL，已確認）。

### 4 個目標表格抽查（讀取完整 `text` 欄位，非 preview）
- **表3-1**（電池系統組成之電壓與容量，page 31）：title 完整、header（規模/組成/電壓/容量）與 3 列真實資料（電池組/電池模組/電池系統）皆完整，無被吞入其他內容。
- **表3-2**（M01 模組V9-V16 充/放電最高與最低電壓，page 32）：title 完整、V9-V16 header 完整、最高電壓與最低電壓兩列資料完整（含先前修正過的 backtracking bug 案例「3.381」正確保留在資料列內，未被誤判為章節標題截斷）。
- **表3-3A、B**（電池外觀尺寸量測值，page 36）：title 完整、header 與 A/B 電池兩列資料完整。
- **表4-1**（不同種類電池用於梯次利用比較表，page 52）：title 與 header 完整，但資料在第一個句尾標點處被截斷（「...未來」句子中斷）——這是 Sub-step 8 階段一已記錄的已知限制（`_looks_like_table_body_line` 在句尾標點處停止收集），本輪確認為預期行為、不視為 ingestion 失敗。

### q15 / q27 / q28 retrieval 驗證結果
使用真實 embedding API 對三題各查詢一次（document_scoped 與 global 各一次，共 6 次 API call，731 tokens），檢索池 `pool_size=30`：

| 題號 | ground truth chunk | 是否在 top-30 內 | hit_rank | hit@1 / hit@3 / hit@5（vector-only＝hybrid，兩種 scope 皆同） | eligibility 判定 |
|---|---|---|---|---|---|
| q15 | chunk `aa7b66058d4c`，page 111，含關鍵字「每日1–2 次循環」 | **否**，向量相似度檢索完全撈不到（top-30 全部落在其他頁面/其他段落） | None | False / False / False | **維持 `false`**，理由已寫入 `eligibility_reason`：ground truth 確認存在於 DB，但這是真實的 embedding 相似度檢索失敗，不是 ground truth 或 ingestion 問題，依指示不因失敗而竄改 ground truth 或勉強通過 |
| q27 | chunk `aa7b66058d4c`，page 111，含「1.4–1.6kWh」 | 是，排名第 2 | 2 | False / **True** / **True** | 翻為 `true` |
| q28 | chunk `baab13eca55d`，page 112，含「8–12 顆」與「10kWh」 | 是，排名第 3 | 3 | False / **True** / **True** | 翻為 `true` |

q15 的失敗已直接定位到根因：ground truth chunk 本身完整存在（人工查詢 `text LIKE '%每日1–2 次循環%'` 可在 DB 中找到），但該 query 的向量相似度排序把它排到 pool_size=30 之外，hybrid re-ranking 也無法救回（hybrid 只重排 vector-only 撈到的 30 筆候選，撈不到的本來就不在候選集內）。這是向量檢索本身的真實限制，記錄於 `eligibility_reason`，未修改 ground truth 或放寬判準讓它「看起來通過」。

### 正式 retrieval benchmark（`spike/run_retrieval_benchmark.py`，涵蓋全部 17 個 eligible 題目）
document_scoped 與 global 兩種 scope 各呼叫 embedding API 17 次（731 tokens），與 Sub-step 7 基準比對：
- **doc1/doc3 的 11 個 single_chunk 題目結果與 Sub-step 7 完全相同**：hybrid hit@1 命中 7/11（q06/q11/q19/q21/q22/q23/q25），vector-only 命中 5/11（q06/q11/q19/q21/q25），與 Sub-step 7 報告的「7/11 vs 5/11」數字逐題一致，**零 regression**。
- q20（multi_chunk，跨段落）與 q24（multi_chunk）結果同 Sub-step 7：q20 仍為已知失敗案例（success_at_5=False），q24 仍成功（True）。
- 新增的 q27/q28（doc4）：document_scoped 與 global 兩種 scope 下皆為 hit@3/5=True、hit@1=False，與上表一致。
- `excluded_questions`（12 題）：q01/q03/q04/q07/q08/q09/q10/q12/q14/q15/q16/q17，與預期相符（q15 因上述真實檢索失敗維持排除；其餘為既有未驗證或設計上不適用 retrieval 評分的題目，未變動）。

### pytest 結果
`python -m pytest -q` → **113 passed**（doc1/doc2/doc3/doc4 chunker 測試 + ingestion/lifecycle 測試皆通過，無新增測試檔案，僅沿用既有測試對新資料的間接覆蓋）。

### 新限制與風險（本輪確認）
1. **q15 是真實的向量檢索盲點**：ground truth 內容確實存在於已 ingest 的語料庫中，但目前的 embedding 模型/查詢寫法無法在合理候選池大小內找到它。若未來要修，方向是查詢改寫、擴大 pool_size，或換用支援 reranker 的架構——但這些都在 MVP v1 RAG spike 範圍之外，本輪不處理。
2. **表4-1 等 5 個表格的句尾截斷限制**維持 Sub-step 8 階段一的結論：已知、已記錄、不視為缺陷，未來若要用它們設計新 benchmark 題目需先讀完整 chunk text 確認。
3. `is_active` 保留/清理策略、q03/q04/q05 ground truth 補完、`multi_chunk_coverage_threshold` 細緻化、q20 跨 chunk 失敗案例，皆維持未規劃狀態。

## 17. 下一個最小步驟

`is_active` archival（清理/保留期限策略）、q03/q04/q05 的 ground truth 補完、`multi_chunk_coverage_threshold` 細緻化、q15 向量檢索盲點是否需要查詢改寫或架構調整、被截斷表格內容（表2-1/3-4/4-1/4-4/4-6）是否需要處理等方向皆尚未規劃，需等待另一輪 planning 與使用者確認。
