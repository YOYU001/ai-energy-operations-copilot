# MVP V1 Specification

## 1. 產品目標

**AI Energy Operations Copilot MVP v1** 是一個內部使用的能源營運 AI Copilot。

它不是真正的 EMS 控制系統，而是 decision support system。

主要協助使用者：
- 查詢能源研究文件與 EMS 知識
- 分析太陽光電、負載、儲能、電價與天氣資料
- 判斷目前資料是否異常
- 搜尋過去相似案件
- 提供儲能排程建議
- 估算成本影響
- 計算 Green Operations Index
- 產生不同角色可讀的分析報告

## 2. 三個設計視角

本專案設計需同時符合三個角度：

### 台電能源管理 / 太陽光電資深工程師角度

重點：
- EMS 營運邏輯合理
- PV forecast vs actual 可比較
- 儲能充放電建議可解釋
- 異常診斷需貼近現場情境
- 不做真實 EMS control

### AI Applied Engineer 角度

重點：
- 架構需可展示 RAG + structured data analytics
- 使用 PostgreSQL + pgvector 作為主要資料層
- AI 回答需可追溯來源
- 不允許預設 web search
- MVP v1 保持可落地、可測試、可擴充

### 淨零碳排 / 永續能源規劃師角度

重點：
- Green Operations Index 是營運層級永續指標
- 不是正式 carbon accounting
- 不做完整 ESG report
- 可估算 PV 自用、綠電浪費、二次利用電池價值與簡化減碳效益

## 3. 目標使用者

> MVP 第一階段（Step 6 之後）核心使用者為 **EMS Engineer**，第一個完整端到端場景為 `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`（見 `docs/PROJECT_ALIGNMENT_REVIEW.md`）。以下四種角色皆為專案完整願景的一部分，其餘三種角色列為 MVP 第一階段之後的擴充對象，不在本輪實作範圍。

### Energy Dispatch Operator

最需要：
- 現在是否異常？
- 哪個時段有超約風險？
- 電池現在該充電還是放電？
- 需要採取什麼操作建議？

### EMS Engineer

最需要：
- EMS 控制邏輯是否異常？
- 是否有 should-discharge-but-did-not？
- 是否有 peak-period abnormal charging？
- 是否與過去案件相似？

### Non-Engineering Manager

最需要：
- 發生什麼事？
- 影響多少成本？
- 風險高不高？
- 綠能表現好不好？

### New Employee / Trainee

最需要：
- 這個問題代表什麼？
- 相關文件在哪裡？
- 前人過去怎麼處理？
- 有哪些相似案例？

## 4. Core MVP Functions

### 4.1 Knowledge Base Q&A

支援 PDF / TXT / MD 文件 ingestion。

使用者可以問：
- 太陽能發電預測過去用過哪些模型？
- EMS 控制策略有哪些限制？
- 儲能排程為什麼需要負載與電價資料？

回答需引用內部文件來源。

### 4.2 CSV Energy Data Analysis

支援能源時間序列 CSV 匯入。

系統需分析：
- PV forecast vs actual
- Load vs contract capacity
- Battery SOC
- Battery power
- TOU price
- Weather / GHI
- EMS mode
- Equipment status

### 4.3 Fixed Dashboard

Dashboard 使用固定圖表模板，不讓 AI 自由生成任意圖表。

至少包含：
- PV forecast vs actual
- Load vs contract capacity
- Battery SOC
- Battery charge/discharge power
- Electricity price
- Cost comparison
- Green Operations Index
- Anomaly timeline

### 4.4 Anomaly Diagnosis

MVP v1 支援 8 種異常：

1. PV forecast deviation
2. Abnormal load increase
3. Over-contract risk
4. Battery should-discharge-but-did-not
5. Peak-period abnormal charging
6. Green energy waste
7. Low SOC risk
8. Battery health risk

診斷邏輯使用 rule-based rules，不使用 machine learning anomaly model。

### 4.5 Case Similarity Search

MVP v1 做簡化版相似案件搜尋。

依據：
- event_type
- symptoms
- tags
- root_cause
- operator_action
- text embedding similarity

不做 advanced time-series similarity modeling。

### 4.6 Battery Scheduling Suggestion

MVP v1 使用 rule-based scheduler，不做 optimization algorithm。

基本規則：
- High PV + low price + SOC not full → charge
- Peak price + high load + enough SOC → discharge
- Load near contract capacity → discharge or suggest load reduction
- Low SOC → preserve backup energy
- High battery temperature → reduce cycling

輸出需包含：
- suggested action
- time window
- reason
- risk
- cost impact
- green impact

### 4.7 Cost Estimation

MVP v1 支援簡化成本估算：
- TOU energy cost estimate
- battery arbitrage saving estimate
- over-contract risk warning
- before/after schedule cost comparison

不做：
- full Taipower bill reconstruction
- ancillary service revenue
- power trading revenue
- carbon fee or carbon credit calculation

### 4.8 Green Operations Index

Green Operations Index 是營運層級永續指標，不是正式碳盤查。

MVP v1 的 implementation source of truth 是 `docs/MVP1_RULES.md`，固定採用以下 100 分權重：

- PV Utilization Score: 25 points
- Battery Operation Score: 25 points
- Grid Dependency Score: 20 points
- Battery Health Score: 20 points
- Second-life Battery Bonus: 10 points

輸出範例：
- Green Operations Index: 78 / 100
- 主要加分原因
- 主要扣分原因
- 改善建議

若未來要調整權重，必須先更新 `docs/MVP1_RULES.md` 與 `docs/DECISIONS.md`，再同步其他文件。

### 4.9 Role-Based Response Style

支援四種回答模式：

- Operator Mode: 操作建議
- Engineer Mode: 技術分析
- Executive Mode: 主管摘要
- Training Mode: 新人教學

### 4.10 Analysis Report

報告需包含：
- key findings
- detected anomalies
- similar cases
- suggested actions
- cost impact
- green operations impact
- limitations

### 4.11 AI Assistant Answer Structure

AI Assistant 的回答（Rule Engine 解釋、RAG 檢索結果、Case Similarity 引用）一律採用 `docs/MVP1_RULES.md` 第 8 節定義的七部分結構：Confirmed facts/Finding、Evidence、Possible causes、General engineering background、Suggested actions/Next checks、Confidence、Citations。

核心規則：
- 案場具體事實只能來自 structured data、Rule Engine 結果、檢索到的文件、歷史案例，不可用一般知識替代。
- LLM 補充的一般工程背景知識只能用於解釋概念、提供可能方向、建議下一步檢查，不可寫成已確認原因。
- Citation 需區分內部來源（附實際來源）與一般背景知識（明確標示，不可偽裝成內部來源）。
- 證據不足時必須明確說明，不可硬下結論。
- AI Assistant 是分析與決策支援工具，不直接控制設備，不取代工程師最終判斷。

具體的相似度門檻與 confidence 分級數值，由 Step 6 RAG Feasibility Spike 的實測結果決定，本節不預先假設。

### 4.12 Structured Data Query Approach

MVP 使用受控 tool-calling：AI 判斷使用者意圖 → 呼叫預先定義的 dataset API/statistics function/analysis tool（複用 `backend/app/datasets_queries.py`）→ 後端執行固定且受控制的 SQL → AI 根據結果產生解釋。**不做 unrestricted Text-to-SQL**，該能力列為 MVP 之後的進階能力（見 `docs/DECISIONS.md` ADR-002）。

## 5. Internal Knowledge Only Rule

MVP v1 預設只允許使用：
- uploaded internal documents
- imported CSV datasets
- case records
- built-in MVP rules

若資料不足，回答：
「目前內部知識庫與資料集不足以回答此問題。」

不要自行上網查資料。  
不要編造不存在的文件、案件或數據。

## 6. Not Included in MVP v1

MVP v1 不做：
- Real EMS control
- Real web search
- Optimization algorithms
- Self-trained PV/load forecasting models
- Multi-agent system
- Full carbon accounting
- ESG report automation
- Power trading platform integration
