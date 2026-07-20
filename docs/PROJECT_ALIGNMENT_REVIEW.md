# Project Alignment Review

> 用途：保存 2026-07-13〜07-14 進行的完整 Project Alignment Review 最終決策，避免對話關閉後遺失。
> 原則：這是完整記錄；`docs/DECISIONS.md` 只收錄其中真正屬於長期架構決策的 ADR（ADR-002〜ADR-007），並回連到本文件；日常開發請讀 `PROGRESS.md`、`docs/RAG_SPIKE_PLAN.md`，不需要每次重讀本文件全文。

---

## 1. Project Alignment Review 摘要

在 Step 5 完成、正式進入原本規劃的 Step 6 之前，因為最終願景（企業級 AI 資料助手）比當時 MVP 的能源垂直範圍更廣，暫停原本的 Step 規劃，進行了一次五階段對齊審查：

1. **Phase 1 教學**：建立企業級 AI 資料助手的完整概念圖（資料來源、RAG、Embedding、權限、Audit Log 等），並標出已知/未知/不知道自己不知道的部分。
2. **Phase 2 專案掃描**：確認 Step 1–5 實際完成的內容；確認現有架構（資料庫、驗證、API 設計）是可重用的通用工程基礎，沒有過早設計或明顯技術債，但原本的 Step 6–12 是為單一垂直領域設計。
3. **Phase 3 Blind Spot Scan**：掃描 20 個面向（使用者需求、資料類型、OCR、Hallucination、Citation、權限、資料生命週期、機密資料與外部 API 衝突、法規責任邊界等）。
4. **Phase 4 反向訪談**：8 輪訪談，逐步鎖定使用者、場景、資料策略、信心與引用規則、部署階段等所有會影響架構的關鍵決策。
5. **Phase 5 方案比較**：確認不轉型為通用企業文件助手，維持能源垂直方向；比較三個 MVP 開發順序方案，選定 RAG Feasibility Spike 優先；比較 tool-calling 與 Text-to-SQL，確認 MVP 用受控 tool-calling。

**結論**：現有架構（Step 1–5）沒有被推翻，也沒有發現需要大改的技術債；真正需要調整的是開發順序——把「產品最大的不確定性（RAG/OCR/Citation）」的驗證時間點，從原本規劃的第 9 步提前到新 Step 6，用一個範圍受控的 spike 先驗證。

---

## 2. Confirmed Product Definition

> **Energy Operations Dashboard + AI Assistant**——一個服務 EMS 工程師的能源營運決策支援系統，結合結構化時間序列資料、rule-based 異常診斷、與 RAG 驅動的文件/案例證據檢索，用保守、可追溯、附引用來源的方式，協助工程師縮小異常排查範圍——不是通用企業文件助手，也不是設備控制系統。

- **MVP 核心使用者**：EMS 工程師（能源調度人員、營運主管明確列為後續擴充對象）。
- **第一個完整端到端場景**：`BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`（電池應該放電卻沒放電）。
- **AI Assistant 角色**：分析與決策支援工具，協助縮小排查範圍，不取代工程師最終判斷，不直接控制設備。
- **長期方向（非本輪範圍）**：未來可能延伸到產品檢核、設備異常、噪音、良率與品質分析，但這是能源垂直站穩之後才考慮的擴充，不影響本輪 MVP 設計。

---

## 3. Decision Log（完整 16 項）

| # | 決策主題 | 確認內容 |
|---|---|---|
| 1 | 產品方向 | Energy Operations Dashboard + AI Assistant，能源垂直優先，不轉型為通用企業文件助手 |
| 2 | MVP 核心使用者 | EMS 工程師（單一角色優先，其他角色後續擴充） |
| 3 | 第一個完整場景 | `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT` |
| 4 | Structured data 查詢方式 | 受控 tool-calling（意圖判斷 → 呼叫已定義 API/tool → 固定 SQL → AI 解釋），複用 Step 5 既有查詢函式；unrestricted Text-to-SQL 留到 MVP 後（見 ADR-002） |
| 5 | RAG spike 定位 | 在正式 Step 6（原順序）之前，範圍極小、只驗證技術可行性，不取代正式 RAG Step、不建立正式產品功能 |
| 6 | OCR | MVP 必須具備能力（非可選），已有 必須做/可簡化/後續再做 三層分類（見 ADR-003） |
| 7 | 資料策略 | Structured data 用 synthetic CSV；Unstructured data 用真實但非機密文件（含掃描 PDF）；真實機密資料 MVP 不使用 |
| 8 | Embedding/LLM Provider | Spike 與 MVP 先用 OpenAI Embeddings + LLM；provider 不寫死、集中管理設定、metadata 記錄 model/version、保留未來重新 embedding 的能力；地端方案留到需要處理機密資料時評估（見 ADR-004） |
| 9 | NAS | 已揭露未來基礎設施（Synology DS925+，個人使用設備），本輪不使用、不提前介入，MVP 核心驗證完成後才評估搬遷哪些服務；不因 NAS 是本地設備就假設可存放真實機密資料 |
| 10 | 資料規模與使用人數 | MVP：案例 20–100、文件 10–50、掃描 PDF 5–20、使用者 1–5 人（同時≤3）；未來：案例數百至數千、文件數百至上千、使用者擴充到單一部門 10–30 人 |
| 11 | 權限 | MVP 簡化（不做完整權限系統），但不堵死未來 role/department/audit；測試者只能碰 API，不直接連 PostgreSQL，即使內部測試也要有基本登入/密碼保護 |
| 12 | AI 回答的信心與保守度 | 證據不足不可下結論，需明確說「證據不足」；可能原因需標示為假設並附證據；相似案例需標示相似度/相似條件/不同條件；核心原則「寧可誠實說證據不足，也不要給沒根據的答案」 |
| 13 | 一般知識 vs 案場證據邊界 | LLM 可用通用工程知識輔助解釋（僅限概念/方向/建議），不可寫成已確認原因；回答需區分：已確認事實/可能原因/一般背景知識/下一步建議；citation 需區分內部來源與一般背景知識（見 ADR-006、`docs/MVP1_RULES.md` 第 8 節） |
| 14 | 資料生命週期（Archive/Version/Delete） | MVP 不實作完整機制；已確認現有 schema 可低成本擴充（`status`/`version`/`effective_from`/`effective_until`/`archived_at`/`deleted_at`/`superseded_by`/`retention_until`），未來優先 Archive 而非 Delete，一般查詢預設用 Active 資料（見 ADR-005） |
| 15 | 部署階段 | 開發電腦本機開發 → MVP 完成後開放 1–3 位內部測試者（安全內網、基本存取控制）→ 之後評估 NAS → 有遠端展示需求才評估雲端；機密資料未來不直接上公開雲端 |
| 16 | MVP 開發順序 | 選定 RAG Feasibility Spike 優先（在原 Step 6 之前執行，見 ADR-007） |

---

## 4. MVP Scope

**RAG Feasibility Spike**（新 Step 6，本次審查的直接產出，詳見 `docs/RAG_SPIKE_PLAN.md`）

**Dashboard + Rule Engine**（新 Step 8–9，聚焦單一場景）
- 前端骨架 + 針對 `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT` 場景相關的圖表（時間序列、異常標示）
- Rule Engine 先只實作這一條規則（`docs/MVP1_RULES.md` 4.6 節），其餘 7 種異常類型延後

**AI Assistant**（新 Step 10–12，基於 spike 結論展開）
- 完整 RAG（文件 ingestion、chunking、embedding、citation）
- Case Similarity（歷史案例檢索，含相似度/信心標示）
- Tool-calling 整合層：結合 Rule Engine 結果 + RAG 證據 + 歷史案例，產出七部分結構化回答（`docs/MVP1_RULES.md` 第 8 節）

**資料**：Synthetic CSV（結構化）+ 真實非機密文件（10–50 份，含 5–20 份掃描 PDF）

**部署**：本機開發 → 內部測試者（API-only 存取 + 基本登入）

---

## 5. Non-goals（MVP 明確不做）

- Unrestricted Text-to-SQL
- 完整文件管理、完整 ingestion pipeline、大量文件壓力測試
- 完整權限系統、多部門/多租戶
- 完整資料生命週期管理（自動封存、自動清除、retention 執行、完整 Audit Log）
- NAS 部署、地端 LLM/embedding
- 雲端正式部署（除非有遠端展示需求）
- 其餘 7 種異常類型的 Rule Engine（`OVER_CONTRACT_RISK`、`PV_FORECAST_DEVIATION` 等）
- 表格結構辨識、手寫文字辨識、工程圖理解、多語言 OCR（僅先支援中英文）
- 設備控制、自動化調度執行
- 通用企業文件助手（跨部門、跨領域）
- 真實機密資料的處理（本輪完全不碰）

---

## 6. Risks and Blind Spots（仍待驗證或尚未決定）

| 風險 | 現況 | 如何處理 |
|---|---|---|
| RAG 準確度、OCR 品質、Citation 正確性 | 完全未知 | 由 Step 6 RAG Feasibility Spike 直接驗證 |
| 相似度門檻與 confidence 分級的具體數值規則 | 尚未給出具體數字，合理門檻應由 spike 實際測出的 retrieval 分數分布決定 | 列為 spike 的驗收輸出之一，spike 完成後再回頭定出具體規則 |
| Provider 抽象設計的執行紀律 | 已決定要做，但寫 spike 程式碼時容易為求快而寫死 OpenAI | 需要在 spike 階段就開始養成習慣（設定集中管理、記錄 model/version） |
| OpenAI API 呼叫成本 | 尚未實際估算過 | 建議 spike 完成後，用實際跑過的 10–20 題 + embedding 次數，回推 MVP 規模下的預估月費 |
| 資料生命週期欄位何時真的加進 schema | 已確認不會被堵死，但沒有決定何時加 | 建議在真的需要時（例如文件開始有新舊版本）才加，不需要現在預先加空欄位 |
| Spike 規模是否能代表 MVP 正式規模的行為 | 3–5 份文件、10–20 題測試問題，樣本很小 | 刻意取捨（快速驗證優先於統計顯著性），spike 報告需誠實標註這是小樣本結論 |
| `docs/MVP1_RULES.md` 第 8 節與 `docs/MVP_V1_SPEC.md` 4.11 節的一致性 | 本輪已同步更新兩份文件（見 ADR-006） | 後續任何調整都必須兩份文件一起改 |

---

## 7. Architecture Direction

```text
Frontend（Next.js，未來）
  ↓
Backend API（FastAPI，已有 Step 1–5 基礎）
  ├─ Structured data 查詢：Tool-calling 層，複用 Step 5 query functions 作為「工具」
  ├─ Rule Engine：BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT（單一規則優先）
  └─ RAG 層（基於 spike 結論建置）
        ├─ Document ingestion + Chunking + OCR
        ├─ Embedding（OpenAI，provider 抽象化、設定集中管理）
        ├─ pgvector 檢索 + Case Similarity
        └─ Citation（區分內部來源 vs 一般背景知識）
  ↓
AI Assistant 整合層
  ├─ 意圖判斷 → 選擇 tool 或觸發 RAG 檢索
  ├─ 組裝七部分回答（`docs/MVP1_RULES.md` 第 8 節）
  └─ 附 citation + confidence，證據不足時保守回答
  ↓
資料層（PostgreSQL + pgvector）
  ├─ 現有 7 張表維持不變，不需要現在加欄位
  └─ 未來資料生命週期欄位可低成本擴充（已確認不被堵死）

部署：本機開發 → 內部測試（API-only + 基本登入）→（未來）NAS（個人設備，未來才評估）→（未來，如有需要）雲端
```

**關鍵架構原則**：Provider 可替換（embedding/LLM 不寫死）、SQL 執行受控（tool-calling 而非 Text-to-SQL）、回答保守且可追溯（七部分結構 + citation + confidence）、資料庫對外不直接暴露（測試者只碰 API）。

---

## 8. RAG Feasibility Spike

完整規格見 `docs/RAG_SPIKE_PLAN.md`（範圍、必須驗證的 10 項、spike 不做清單、驗收輸出）。本文件只記錄它在整體 roadmap 裡的定位：**新 Step 6，插入在原本 Step 6 之前，不取代正式 RAG Step（新 Step 10），只驗證技術可行性**。

**狀態：已完成並正式驗收關閉（Go）。** 完整 closeout 記錄見 `docs/RAG_SPIKE_PLAN.md` 第 18 節；Step 10 的 production integration plan（schema 差距分析、整合順序、rollback plan）已規劃完成、尚未執行，見同文件第 17 節。本次 closeout 決策維持第 9 節既有 roadmap 順序，**未提前執行 Step 10、未新增 ADR**。

---

## 9. 重排後的 Step 6–13 Roadmap

```text
Step 6（新增）: RAG Feasibility Spike
Step 7（原 Step 6）: Frontend Foundation
Step 8（原 Step 7）: Dashboard Charts
    聚焦 BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT 場景相關圖表
Step 9（原 Step 8）: Rule-Based Analysis
    先只實作 BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT 這一條規則
Step 10（原 Step 9）: Knowledge Base / RAG（正式版）
    基於 spike 的結論展開
Step 11（原 Step 10）: Case Similarity
Step 12（原 Step 11）: Copilot Chat / AI Assistant 整合
    Tool-calling 架構，複用 Step 5 查詢能力，整合 Rule Engine + RAG + Case Similarity
Step 13（原 Step 12）: Analysis Report
```

完整版本見 `docs/DEVELOPMENT_WORKFLOW.md` 第 6 節（已同步更新）。

---

## 10. 下一個最小步驟

> **Step 6：RAG Feasibility Spike — 子步驟 1：準備測試文件清單與 10–20 題固定測試問題（含預期答案要點）**

資料/規劃性質，不需要寫程式、不需要安裝套件，適合當作正式進入 spike 之前的第一個小步驟。詳見 `docs/RAG_SPIKE_PLAN.md`。
