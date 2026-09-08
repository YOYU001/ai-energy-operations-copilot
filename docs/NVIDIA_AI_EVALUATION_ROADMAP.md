# NVIDIA 導向的 AI Evaluation 學習 Roadmap

## 核心學習方向

本學習 Roadmap 將以 **NVIDIA 官方在 AI Evaluation、Benchmarking、RAG Evaluation、Agent Evaluation 與 Performance Benchmarking 所採用的主流方法論與工具** 作為主要學習目標。

學習重點不是單純去比較「哪個模型贏、哪套工具好」，而是逐步建立一套可以長期沿用、重複使用、並能實際支援 AI 導入決策的 Evaluation 方法論與自動化系統。

整體學習體系設計圍繞以下 **兩大核心面向**：

### 1. 全觀式 AI 評估（General / Holistic AI Evaluation）

從較全面的角度評估一個 AI 模型或 AI 系統本身的能力與實用性。

包含面向例如：

- Reasoning
- Coding
- Knowledge
- Instruction Following
- Hallucination
- Long Context
- Multilingual
- RAG 能力
- Agent 能力
- Latency
- Throughput
- Cost
- Reliability
- Safety

目的不是只看公開 Benchmark 的分數，而是建立一份完整的 AI 能力與工程表現 Scorecard，回答：

> 這個 AI 整體來說有哪些優勢、弱點、適用場景與不適用場景？

---

### 2. 專案式 AI 評估（Project-specific AI Evaluation）

針對實際專案、實際工作負載與實際業務需求建立專屬 Benchmark。

例如在 EnergyOps、企業 RAG Assistant 或其他 AI 專案中，不只問：

> 哪個 AI 整體比較強？

而是問：

> 在「我的這個專案」裡，哪個 AI、RAG Pipeline、Agent 或模型組合表現最好？

評估可以依專案需求包含：

- Domain Knowledge
- Document QA
- Retrieval Accuracy
- Citation Correctness
- Fault Diagnosis
- Time-series Analysis
- Hallucination Control
- Tool Calling
- Task Completion
- Latency
- Cost
- Reliability

最終希望建立：

```text
General AI Evaluation
        +
Project-specific Evaluation
        →
AI Evaluation Scorecard
        →
Adopt / Conditional / Reject
```

也就是同時回答兩個問題：

```text
1. 這個 AI 整體好不好？
2. 這個 AI 適不適合我的專案？
```

這兩個面向會作為整份 Roadmap，未來 Evaluation Lab / EvalCore，以及最終自動化 Evaluation Pipeline 的核心設計原則。

---

> 目標：建立一套自己的 AI Evaluation / Benchmarking 能力，能系統化判斷不同 AI 模型、RAG、Agent 是否值得導入，並逐步發展成自動化 Evaluation Lab / EvalCore。

---

## 1. 最終目標

不要只問：

> 哪個 AI 最強？

而是改成：

> 在特定 workload、品質要求、延遲要求與成本限制下，哪個 AI 最適合？

最終希望建立：

```text
New AI / New Model / New Pipeline
        ↓
General Capability Evaluation
        ↓
Project-specific Evaluation
        ↓
RAG / Agent Evaluation
        ↓
Performance / Latency Evaluation
        ↓
Cost / Reliability / Safety
        ↓
Automated Scorecard
        ↓
Adopt / Conditional / Reject
```

---

## 1a. 狀態標記約定（Current baseline / Planned work / Non-MVP reference）

這份文件同時記錄「已完成的評測基礎」與「未來想做的評測」，早期版本兩者混在一起，容易讓人誤以為某個 runner 還要重寫。從本次修訂起，每個評測項目都標一種狀態：

| 標記 | 意義 |
|---|---|
| **Current baseline** | 已在 `main` 實作、可直接執行，並已有記錄過的基準數字。新的評測工作要「接續」而不是「重造」這些。 |
| **Planned work** | 尚未實作、但屬於本 MVP v1 evaluation 範圍、預計要補的項目。 |
| **Non-MVP reference** | 獨立的未來 portfolio 專案或純學習參考。**不是本 repo 的 acceptance gate，不得阻擋 MVP v1 的完成判定。** |

### 目前的 Current baseline 一覽（`main` 上已可執行）

| 能力 | 實作 | 產出的指標 | 報告位置 | 最近一次記錄的數字 |
|---|---|---|---|---|
| Retrieval quality | `backend/scripts/run_retrieval_benchmark.py`（真實 embedding 呼叫，走 `app/services/retrieval.py` production 檢索 + `app/services/retrieval_metrics.py` 評分，題庫沿用 `spike/test_questions.json`） | `hit@1 / hit@3 / hit@5`（document-scoped 與 global 各一組）、`hybrid_matches_vector_only_order`、cross-document interference | `backend/scripts/retrieval_benchmark_report.json`（已進版控） | document-scoped `hit@1/3/5 ≈ 64% / 91% / 100%`；global `hit@3 ≈ 82%` |
| Answer accuracy（走完整 orchestration 的最終回答） | `backend/scripts/run_answer_accuracy_benchmark.py`（對真實 `/assistant` HTTP endpoint 跑完整對話，LLM-as-a-Judge，裁判 `gpt-5.6-terra`，生成模型 `gpt-4o-mini`，題庫為 `spike/test_questions.json` 中 `retrieval_eval_eligible=true` 子集） | `correctness / groundedness / completeness`（各 1–5，取平均） | `backend/scripts/answer_accuracy_report.json`（本機執行產出，未進版控） | `correctness ≈ 3.36 / groundedness ≈ 3.29 / completeness ≈ 3.43` |
| Groundedness gate（部署層防幻覺） | `backend/app/services/groundedness.py` + `backend/tests/test_groundedness.py`（deterministic，非 LLM 呼叫） | 每句 claim 是否被單一 evidence unit 共同佐證（單元測試 pass/fail，非分數） | 隨 backend test suite | 隨 `main` 測試套件全過 |
| Step 13 rule 分析（battery scheduling / cost / green ops）與 Step 14 report | `backend/app/services/{battery_scheduling,cost_estimation,green_operations_index,analysis_report}.py` + `backend/tests/test_step13_*.py` + `test_step13_synthetic_integration_validation.py` | deterministic rule 輸出 + synthetic fixture 端對端驗證（pass/fail） | 隨 backend test suite | 全部 pass（含 synthetic multi-site / 缺欄位 / 空資料集情境） |

下面各 Phase 若涉及上表能力，一律標成 **Current baseline** 並只描述「還缺什麼」。

---

# 2. 核心能力層級

## Level 1 — Model Evaluation

目標：評估 AI 本身的通用能力。

主要面向：

- Reasoning
- Coding
- Math
- Knowledge
- Instruction Following
- Hallucination
- Long Context
- Multilingual

常見 benchmark：

- MMLU
- MMLU-Pro
- MATH-500
- GPQA
- GSM8K
- HumanEval
- SimpleQA

NVIDIA 官方：

- NeMo Evaluator
  https://docs.nvidia.com/nemo/evaluator

- NeMo Evaluator Built-in Benchmarks
  https://docs.nvidia.com/nemo/evaluator/nightly/evaluation/benchmarks

---

## Level 2 — AI System Evaluation

實際產品通常不是只有一個 LLM：

```text
User
 ↓
Retriever
 ↓
Reranker
 ↓
Prompt
 ↓
LLM
 ↓
Guardrails
 ↓
Answer
```

因此要測的是「整套 AI system」，而不是只測單一模型。

例如：

```text
Embedding A + Reranker A + Claude
vs
Embedding B + Reranker B + GPT
```

---

## Level 3 — Project-specific Evaluation

這是最重要、也最有實務價值的一層。

建立自己的 Domain Benchmark。

例如：

```text
EnergyOps-Bench
```

可以包含：

- Document QA
- Fault Diagnosis
- Time-series Analysis
- Historical Similarity Search
- RAG Retrieval
- Hallucination / Safety
- Citation Correctness
- Management Summary

標準 benchmark 告訴你模型「整體實力如何」。

Project benchmark 告訴你：

> 它是否適合你的產品。

---

# 3. AI Evaluation 六大面向

自己的 Evaluation Lab 最終至少應包含：

| 面向 | 核心問題 |
|---|---|
| Quality | 回答好不好 |
| Task Capability | 任務能不能完成 |
| RAG | 資料找得到找不到 |
| Performance | 速度快不快 |
| Cost | 使用成本是否合理 |
| Reliability / Safety | 是否穩定、有沒有亂編 |

---

# 4. NVIDIA Evaluation 主線

## 4.1 NVIDIA NeMo Evaluator

這是整套學習的主線。

用途：

- LLM Evaluation
- Benchmark 執行
- Custom Benchmark
- Custom Scorer
- LLM-as-a-Judge
- 多模型比較
- Regression Evaluation

官方文件：

https://docs.nvidia.com/nemo/evaluator

官方 Benchmark 說明：

https://docs.nvidia.com/nemo/evaluator/nightly/evaluation/benchmarks

NeMo Platform Benchmark 概念：

https://docs.nvidia.com/nemo/microservices/latest/evaluator/benchmarks/index.html

重要觀念：

```text
Benchmark = Dataset + Metrics / Scoring Rules
```

建立 benchmark 後，可以重複：

- 比較不同模型
- 比較不同版本
- 驗證 prompt 更新
- 驗證 pipeline 更新
- 做 regression testing

---

# 5. NVIDIA RAG Evaluation

對 RAG 專案非常重要。

NVIDIA RAG Blueprint Evaluation：

https://docs.nvidia.com/rag/latest/evaluate.html

主要 Metrics：

## Answer Accuracy

模型答案跟 Ground Truth 是否一致。

## Context Relevancy

Retriever 找回來的 chunk 是否真的跟問題相關。

## Response Groundedness

回答是否有被 retrieved context 支持，而不是模型自己編造。

## Context Recall

檢查正確資料是否有成功被 Retrieval 找到。

常見：

```text
Recall@1
Recall@3
Recall@5
Recall@10
```

RAG Evaluation 可以拆成：

```text
Question
 ↓
Retrieval Evaluation
 ↓
Context Evaluation
 ↓
Answer Evaluation
 ↓
Groundedness Evaluation
```

---

# 6. NVIDIA AIPerf — AI Performance Benchmark

品質再高也代表不了適合 Production。

需要測：

- TTFT
- ITL
- TPS
- RPS
- End-to-End Latency
- Throughput
- Concurrency

官方 NVIDIA NIM Benchmarking Guide：

https://docs.nvidia.com/nim/benchmarking/llm/latest/

AIPerf：

https://docs.nvidia.com/aiperf/

AIPerf Metrics：

https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference

---

## TTFT — Time To First Token

使用者送出問題後，到第一個 token 出現需要多久。

適合評估：

- Chatbot 體感速度
- Interactive AI
- Agent response

---

## ITL — Inter Token Latency

生成過程中 token 跟 token 之間的延遲。

---

## TPS — Tokens Per Second

模型每秒可以產生多少 token。

---

## RPS — Requests Per Second

系統每秒可以處理多少 request。

---

## Concurrency

同時有多個使用者時，系統表現是否仍然穩定。

---

# 7. LLM-as-a-Judge

非常重要的 AI Evaluation 技術。

概念：

```text
Question
Expected Answer
Model Answer
       ↓
Judge Model
       ↓
Score
```

例如輸出：

```json
{
  "correctness": 5,
  "completeness": 4,
  "groundedness": 5,
  "clarity": 4
}
```

適合測：

- Correctness
- Completeness
- Groundedness
- Relevance
- Instruction Following
- Summary Quality

但要注意：

> Judge 本身也可能有 bias 或犯錯。

因此進階階段需要：

- Human calibration
- Multiple judges
- Judge agreement
- Deterministic metric + Judge metric 混用

---

# 8. NVIDIA Agent Evaluation

未來 AI 系統會逐漸從：

```text
Question → Answer
```

變成：

```text
Goal
 ↓
Reason
 ↓
Use Tool
 ↓
Search
 ↓
Call API
 ↓
Observe
 ↓
Reason Again
 ↓
Final Answer / Action
```

所以 Evaluation 也需要評估：

- Final result
- Tool choice
- Tool arguments
- Intermediate steps
- Task completion
- Failure recovery

NVIDIA NeMo Gym Evaluation：

https://docs.nvidia.com/nemo/gym/main/about/concepts/evaluation

Benchmarks：

https://docs.nvidia.com/nemo/gym/main/evaluation/benchmarks

---

# 9. 官方 NVIDIA 教學影片

## Video 1 — 第一支必看

### Evaluate LLMs with NeMo Evaluator and Docker Compose | Step-by-Step Setup Guide

NVIDIA Developer 官方：

https://www.youtube.com/watch?v=Fo9kNJE5nC8

內容包含：

- Docker Compose
- NeMo Evaluator
- Evaluation Job
- Python SDK
- Custom Metric
- String Matching
- LLM-as-a-Judge
- Jupyter Notebook Demo

建議：

**第一次接觸 NeMo Evaluator 就從這支開始。**

---

## Video 2 — Agent Evaluation

### Scale AI Agent Evaluation with NVIDIA NeMo Evaluator LLM-as-a-Judge

NVIDIA Developer 官方：

https://www.youtube.com/watch?v=IDXWrlWKr4c

內容：

- NeMo Evaluator
- LLM-as-a-Judge
- Agent Evaluation
- NVIDIA NIM
- Kubernetes / NIM Operator
- Prometheus
- Multi-GPU scaling

這是屬於進階內容。

建議在熟悉基本 Model Evaluation 後再看。

---

# 10. NVIDIA 免費學習資源

## NVIDIA Self-Paced Training

https://www.nvidia.com/en-us/training/self-paced-courses/

課程：

- Generative AI
- LLM
- RAG
- Deployment
- Accelerated Computing

建議不要一次修大量課程。

以目前目標：

> Evaluation → RAG Evaluation → Performance → Agent Evaluation

為主線即可。

---

# 11. 建議學習順序

---

## Phase 1 — Evaluation 基礎

先學：

```text
Benchmark
Dataset
Ground Truth
Metric
Accuracy
Precision
Recall
Latency
Throughput
LLM-as-a-Judge
Regression
```

目標：

看到：

> 我要測新模型的表現。

你能問出：

```text
用什麼 Dataset？
測什麼 Metric？
Baseline 是誰？
Ground Truth 是什麼？
有沒有 Regression？
Latency 呢？
Cost 呢？
```

### Phase 1 產出

建立：

```text
evaluation_notes.md
```

記錄所有 Evaluation 基礎概念。

---

# Phase 2 — 第一次 AI Battle

先不要使用大型 Evaluation Framework。

準備：

```text
10～30 個 Test Cases
```

比較例如：

```text
GPT
Claude
Gemini
```

題目可以有：

```text
Reasoning
Coding
Document QA
Instruction Following
```

記錄：

```text
Accuracy
Latency
Tokens
Cost
Hallucination
```

### Phase 2 產出

```text
AI Model Scorecard v1
```

---

# Phase 3 — Python Evaluation Runner

把人工測試自動化。

架構：

```text
eval_cases.json
      ↓
evaluation_runner.py
      ↓
Model Adapters
 → GPT
 → Claude
 → Gemini
 → Nemotron
      ↓
Scoring
      ↓
results.json / results.csv
```

Evaluation Runner 自動：

1. 讀取 test cases
2. 呼叫模型
3. 記錄 response
4. 計算 deterministic metrics
5. 呼叫 LLM Judge
6. 記錄 latency
7. 記錄 token
8. 計算 cost
9. 輸出 Scorecard

### Phase 3 產出

```text
evalcore/
├── datasets/
├── models/
├── evaluators/
├── runners/
├── results/
└── evaluation_runner.py
```

---

# Phase 4 — NVIDIA NeMo Evaluator

此時才正式學 NeMo Evaluator。

學習：

```text
Benchmark
Scorer
Dataset
Evaluation Job
Custom Benchmark
Custom Scorer
LLM-as-a-Judge
```

影片：

https://www.youtube.com/watch?v=Fo9kNJE5nC8

官方文件：

https://docs.nvidia.com/nemo/evaluator

### Phase 4 目標

理解：

> NVIDIA 如何把你 Phase 2～3 手工做的 Evaluation 標準化與自動化。

---

# Phase 5 — RAG Evaluation

官方 NVIDIA 參考：https://docs.nvidia.com/rag/latest/evaluate.html

### Current baseline（`main` 上已實作，不要重造）

| RAG 指標 | 目前怎麼量 | 狀態 |
|---|---|---|
| **Answer Accuracy**（correctness） | `run_answer_accuracy_benchmark.py` 的 LLM-as-a-Judge `correctness`（1–5） | ✅ Current baseline，最近 ≈ 3.36 / 5 |
| **Groundedness** | 兩層：① `run_answer_accuracy_benchmark.py` 的 judge `groundedness`（1–5，最近 ≈ 3.29）；② 部署層的 deterministic `groundedness.py` gate（每句 claim 逐 evidence-unit 共同定位，非分數） | ✅ Current baseline |
| **Completeness** | 同 judge，`completeness`（1–5，最近 ≈ 3.43） | ✅ Current baseline |
| **Recall@K / hit@K** | `run_retrieval_benchmark.py` 的 `hit@1/3/5`（document-scoped 與 global），題庫 `spike/test_questions.json`，評分 `retrieval_metrics.py` | ✅ Current baseline，document-scoped ≈ 64% / 91% / 100% |
| **Citation Correctness** | 部分覆蓋：`groundedness.py` 已把 `# Citations` 段落納入 claim 檢查（引用的頁碼／文件必須真的在本輪 evidence 內），`retrieval_metrics.py` 有 `page_correctness` / `exact_content_correctness` | ⚠️ 部分 Current baseline，尚無獨立聚合分數 |

### Planned work（真正還缺的，才是本 Phase 要做的）

```text
1. Context Relevancy —— 目前沒有量。需要對「撈回的 chunk 對問題是否相關」
   做一個獨立指標（可用 judge 或 embedding 相似度門檻），不要跟 hit@K 混為一談。
2. Citation Correctness 的獨立聚合分數 —— 把現有的 page/keyword 檢查彙整成
   「引用正確率 = 正確引用數 / 總引用數」，納入 RAG Scorecard。
3. 把兩支 runner 接進 CI 的可選 job（目前是手動、有 API 費用，見各腳本
   docstring 的成本警告），並固定輸出 machine-readable 報告供 regression 比對。
4. 對照 NVIDIA NeMo Evaluator 的 RAG metrics 命名與計算方式，確認我們的
   correctness/groundedness/recall 定義與其一致（見 Phase 4）。
```

### Phase 5 產出（RAG Scorecard，數字為示意格式，非目標值）

| Metric | 來源 | 現況 |
|---|---|---|
| Answer Accuracy (correctness, 0–100 正規化) | judge correctness → `(x−1)/4×100` | baseline ≈ 59 |
| Context Relevancy | Planned work | — |
| Groundedness (0–100) | judge groundedness → `(x−1)/4×100` | baseline ≈ 57 |
| Recall@1 / @3 / @5 | retrieval hit@K（已是 0–100） | ≈ 64 / 91 / 100 |
| Citation Correctness | Planned work（聚合） | — |

> 註：上面是「格式範例 + 目前 baseline」，不是驗收目標。驗收門檻在第 12 節 Scorecard 統一定義。

---

# Phase 6 — 建立自己的 Project Benchmark（EnergyOps-Bench）

**狀態**：Planned work（題庫尚未建）。這是一份 **AI / backend evaluation roadmap** —— 描述評測的形狀與來源，不是 API 規格、測試規格或完整 MVP 驗收手冊。

**範圍界定**：

- EnergyOps-Bench 只負責 **backend automated evaluation**。
- 固定圖表 Dashboard（Step 8）的實際 render 與互動 **不在本 roadmap 的驗收範圍**：專案目前沒有 frontend 自動化測試框架（已記錄的範圍決策），這部分由**獨立的 frontend QA 流程**追蹤，本文件不臨時發明一套 UI checklist。
- 本文件不宣稱定義「complete MVP validation」；它定義的是 backend evaluation 的形狀與 source of truth。

### Capability 對照表

欄位說明：**Status** = `Implemented + measurable`（已實作、有可執行的判定依據，才計入 current baseline）／`Planned`（尚無 compatible runner，不產生 current pass rate、不作為目前 ADOPT 判定的已完成輸入）。

| Capability | Status | Evaluation shape / stable invariant | Source of truth（`main` symbol） | Current measurability |
|---|---|---|---|---|
| **Battery Scheduling** | Implemented + measurable | deterministic：對固定 fixture，每列 `action`／`price_classification` 與 rule 輸出逐列相等（容差 0）。**Safety**：`temperature` / `health_status` 觸發 blanket 安全覆寫的列，`action` 不得是 charge 或 discharge（rule 回 idle）；`battery_soc` / `battery_soh` 觸發 discharge veto 的列，`action` 不得是 discharge（充電條件成立時回 charge 是正確的）。任一 blanket-safety 列出現 charge/discharge、或任一 discharge-veto 列出現 discharge = safety violation（→ §12.3 Gate B）。缺全部必要欄位的列回 `hold` + insufficient-row warning。 | `backend/app/services/battery_scheduling.py`（`_build_recommendation` Step 1–5、`TEMPERATURE_SAFETY_THRESHOLD` / `SOC_SAFETY_THRESHOLD` / `SOH_VETO_THRESHOLD`）、`price_classification.py` `classify_price` | 直接沿用 `test_step13_integration.py`、`test_low_soc_with_charge_condition_charges`、`test_soh_low_with_charge_condition_charges` 的斷言 |
| **Cost Estimation** | Implemented + measurable | deterministic：`total_energy_cost` / `total_arbitrage_saving`（per-site 與 `dataset_aggregate`）對 fixture 手算值滿足共用 tolerance（見下）；`dataset_aggregate` 為各 site 直接相加。over-contract flag 的數量與位置與 rule 輸出一致。**Note 分流**：末列不完整 → `limitations`（`AnalysisNote.type == "last_row_excluded"`）；真正的時間缺口 → `warnings`。零 valid interval 的 fixture 回 HTTP 200、金額 0.0、不 raise。 | `backend/app/services/cost_estimation.py`（`_evaluate_site`、`_aggregate_sites`；`limitations` / `warnings` 分流依 `note.type`） | 直接沿用 `test_step13_integration.py`、`test_last_row_excluded_reported_as_limitation_not_warning` |
| **Green Operations Index** | Implemented + measurable | deterministic：component `status == "computed"` 時 `score` ∈ `[0, max_score]`；`status == "insufficient_data"` 時 `score` 為 `None`（即使該 site 有 valid interval，只是缺該 component 的輸入）。`total_score` 缺料時為 `None`（不是 0），有值時對 golden fixture 滿足共用 tolerance 且不超過各 max 加總 + bonus 上限。**Second-life bonus**：所有條件只量化 `_evaluate_site` 傳給 `_compute_second_life_bonus` 的 **eligible interval-start rows**（`pd.DataFrame(start_rows)`）；被排除的末列 / invalid interval 資料不影響 expected bonus。三態（`0.0` / `10.0` / `None`，加上「沒有 second-life 列」「缺必要欄位」）以 `_compute_second_life_bonus` docstring 為準。 | `backend/app/services/green_operations_index.py`（`COMPONENT_MAX_SCORES`、`_score_component`（`eligible_duration == 0` → `score=None, status="insufficient_data"`）、`_sum_total_score`、`_compute_second_life_bonus`、`_evaluate_site` 的 `start_rows`）、`schemas.py` `GreenOpsComponentScore` | 直接沿用 `test_step13_integration.py`、`test_green_ops_total_score_none_reads_as_insufficient_data`、`test_missing_component_columns_is_insufficient_data_and_nulls_total` |
| **Fault Diagnosis** | Implemented + measurable | deterministic：對固定 dataset fixture，`GET/POST /datasets/{id}/analysis` 的 flagged 列集合、`operator_action`、severity 與 `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT` 規則輸出一致；缺料 / 零 flagged 的情境回應正確、不誤報。 | `backend/app/services/rule_engine.py`（`BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`）、`backend/app/main.py` `/datasets/{id}/analysis` | 直接沿用 `test_analysis_endpoint.py` 的斷言 |
| **CSV Ingestion** | Implemented + measurable | `POST /datasets/upload`：canonical enum（`ems_mode` / `equipment_status`）合法值不產生 warning；大小寫 / 空白正規化；非法 enum 產生 warning 並存為 `unknown`；timestamp / 數值 / `battery_health_status` 驗證維持；資料以 batch insert 寫入 `datasets` / `energy_timeseries`。 | `backend/app/ingestion.py`（`parse_and_validate_csv`、canonical enum sets）、`backend/app/main.py` `POST /datasets/upload` | 直接沿用 `test_ingestion.py`、`test_datasets_api.py`、`test_datasets_queries.py` |
| **Case Similarity** | Implemented + measurable | 對固定 query / `case_id`，已知最相關的 seed case 出現在回傳 top-k 內；結果依 `final_score` 遞減排序；`confidence` / `case_similarity` label 與其分數落在對應 bucket 自洽（threshold 在程式碼標 PROVISIONAL，只查自洽）；回應不含 `root_cause` / `operator_action` / `resolution_result`。**回傳筆數**：`POST /cases/search` → `min(top_k, seeded_case_count)`；`GET /cases/{case_id}/similar` → `min(top_k, seeded_case_count − 1)`（`find_similar_to_case` 會先移除 query case 本身）；`top_k` 超出允許範圍 → HTTP 422。 | `backend/app/services/case_similarity.py`（`score_candidates`、`confidence_for_score`、`case_similarity_label`、`CONFIDENCE_THRESHOLDS` / `CASE_SIMILARITY_THRESHOLDS`）、`case_retrieval.py`（`find_similar_to_case` 排除 query case）、`schemas.py`（`CaseSearchResult`、`CaseSearchRequest.top_k`）、`scripts/seed_case_records.py` | 直接沿用 `test_cases_api.py` |
| **Management Summary** | Implemented + measurable | `rule_version` 與 6 個 section `key` 齊全；`ReportSection.status` 為 schema 定義的其中一個值；`dataset_overview` → `included`、`similar_cases` → `manual_lookup`；`anomaly_diagnosis` / `battery_schedule` / `cost_estimate` / `green_operations_index` 四者：sub-analysis 有跑 → `included`，否則 → `not_run` + 非空 `note`。**Provenance 只套用在這四個 sub-analysis section**：`included` 時 `source_analysis_run_id` 非 None 且 `source_created_at` == 該 sub-run 建立時間；`dataset_overview` 即使 `included`，其 provenance 欄位仍為 `None`（`_dataset_overview_section` 刻意不填）。`limitations.kind` 為 schema 定義的其中一個值。空資料集不 raise、`row_count == site_count == 0`；green-ops `total_score is None` 時該 section 仍 `included` 但 summary 標示資料不足。 | `backend/app/services/analysis_report.py`（`RULE_VERSION`、`SECTION_*`、`_dataset_overview_section` provenance 留 None、`_not_run_section`）、`schemas.py`（`ReportSection`、`ReportLimitation.kind`） | 直接沿用 `test_analysis_report.py`（`test_all_sub_analyses_present_all_sections_included`、`test_no_sub_analyses_only_overview_included_rest_not_run`、`test_partial_only_anomaly_present`、`test_empty_dataset_does_not_raise_and_reports_zero_rows`、`test_green_ops_total_score_none_reads_as_insufficient_data`） |
| **RAG Retrieval** | Implemented + measurable | `hit@k`（見 §12.3 對 `hit@k` 的定義）由 `run_retrieval_benchmark.py` 對 `spike/test_questions.json` 產出。 | `backend/scripts/run_retrieval_benchmark.py`、`retrieval_metrics.py` | runner 已存在（手動執行，有 API 費用）；aggregate 由 per-question `hit_rank` 計算 |
| **Document QA / Answer Accuracy** | Implemented + measurable | judge `correctness` / `groundedness` / `completeness`（1–5）由 `run_answer_accuracy_benchmark.py` 對 `spike/test_questions.json` 中 `retrieval_eval_eligible` 子集產出。 | `backend/scripts/run_answer_accuracy_benchmark.py` | runner 已存在（手動執行，有 API 費用） |
| **Safety / Hallucination** | Implemented + measurable | deterministic gate：`groundedness.py` 對草稿的每句 claim 逐 evidence-unit 共同定位（pass/fail）。 | `backend/app/services/groundedness.py` | 直接沿用 `test_groundedness.py` |
| **Role / Persona Behavior** | Planned（部分 instrumentation 未就緒） | 對同一 assistant fixture，四種 `role_mode` 各跑一次，斷言**不變量**（不要求逐字相同）：① 提供給模型的 tool schemas（`_tools_for_turn`）與 capability-guard 判定（`looks_like_diagnostic_question`）在四種 mode 下相同；② 每一條實際產生的 claim 都通過 groundedness gate；③ terminal outcome 等於 fixture 宣告的 `expected_terminal_outcome`（見下方「Terminal outcome」）；④ 產生七段式標題；⑤ 非 Literal `role_mode` → HTTP 422。**允許**差異：語氣、深度、資訊密度、引用的有據事實數量、在同一組 eligible 工具中實際選用的子集。**未就緒**：目前的 chat runner 不持久化 `finish_reason` / `status`，②③ 需要新的 runner instrumentation（Planned）。 | `backend/app/main.py`（`ROLE_MODE_FRAMING` 只加 framing、不進 `_tools_for_turn` / capability guard；`_SEVEN_PART_INSTRUCTION`）、`schemas.py` `RoleMode = Literal[...]` | Planned：不計入 current baseline |
| **Time-series QA** | Planned | 未來 runner 應：使用 dataset fixtures、經 `/assistant` 呼叫 dataset tools、比對「模型回答中的數值 / 聚合結果」對 fixture 的預期。精確 pass 條件於 runner 實作時、對當時的 `main` contract 定案。**現況**：沒有 compatible runner（`run_answer_accuracy_benchmark.py` 只處理文件檢索題，不適用），不計入 current pass rate。 | 未來 runner + 屆時的 `test_datasets_api.py` / dataset-tool 斷言 | Planned：不計入 current baseline |

> 上表中每個 **Planned** 項在 EnergyOps-Bench 實際建置前，只定義形狀與 source of truth；精確 pass 條件於實作時對當時的 test 定案，不在本 roadmap 預先寫死。

---

### Roadmap engineering policy（本文件自訂，必須完整可重現）

**共用數值 tolerance**（非既有程式 contract；為評測工程選擇）：所有「數值對手算值」的比對用

```text
pass  ⟺  abs(actual − expected) <= max(abs_tol, rel_tol × abs(expected))
        abs_tol = 1e-6 ,  rel_tol = 1e-9
```

`expected == 0` 時由 `abs_tol` 決定，不做除以 0 的相對誤差。

**Terminal outcome（僅適用 assistant / persona fixture；ingestion 與 deterministic analysis endpoint 不回 chat `finish_reason`）**：

現行 `main.py` 的 outcome 形狀（記錄用，非凍結）：

| 情境 | 現行表現 |
|---|---|
| 正常完成回答 | `finish_reason == "stop"` |
| 受控失敗（backend 決定不作答 / 幻覺攔截 / 工具回合上限） | `finish_reason ∈ {"insufficient_data", "ungrounded_retry_exhausted", "tool_cap_exceeded"}` |
| provider error / 連線中斷 | message `status ∈ {"failed", "aborted"}`，可能沒有 `finish_reason` |

- 每個 assistant fixture 宣告 `expected_terminal_outcome`：`answerable` → 期望 `finish_reason == "stop"`；`insufficient_evidence` → 期望 `finish_reason == "insufficient_data"`。
- 切換 `role_mode` 不得改變同一 fixture 的 `expected_terminal_outcome`。
- **Planned instrumentation**：現行 answer-accuracy runner 只回內容、丟掉 finish reason / status；要真正比對 terminal outcome，需在 runner 補「持久化每次呼叫的 `finish_reason` / message `status`」。實際 benchmark 建置時再依當時 `main` contract 凍結 fixture 的期望終態集合。

---

# Phase 7 — Performance Benchmark

使用 NVIDIA AIPerf。

測：

```text
TTFT
ITL
TPS
RPS
E2E Latency
Concurrency
Throughput
```

官方教學：

https://docs.nvidia.com/nim/benchmarking/llm/latest/

### Phase 7 目標

開始理解：

```text
Quality vs Latency
Quality vs Cost
Latency vs Throughput
Concurrency vs User Experience
```

而不是單純追求 Accuracy 最大。

---

# Phase 8 — Agent Evaluation

開始測：

```text
Tool Selection
Tool Calling
Multi-step Reasoning
Task Completion
Failure Recovery
```

官方：

https://docs.nvidia.com/nemo/gym/main/about/concepts/evaluation

官方影片：

https://www.youtube.com/watch?v=IDXWrlWKr4c

---

# Phase 9 — Regression Evaluation

當模型、Prompt、Retriever、Reranker 或 Pipeline 更新：

```text
Git Push
   ↓
Evaluation Suite
   ↓
100 / 500 / 1000 Test Cases
   ↓
Current vs Baseline
   ↓
Regression Detection
   ↓
PASS / FAIL
```

例如：

```text
Answer Accuracy

Baseline: 92.1
New:      94.0

PASS
```

但：

```text
Groundedness

Baseline: 95.2
New:      89.4

FAIL
```

即使 Overall Score 較高，也不能直接 deployment。

### Regression suite 的覆蓋

當這套 suite 被當成本專案的 regression gate，覆蓋範圍應涵蓋：

- Phase 5 的 Current baseline 兩支 runner（retrieval hit@k、answer-accuracy judge 分數）
- Phase 6 中 Status = `Implemented + measurable` 的類別（Step 13 三類、Fault Diagnosis、CSV Ingestion、Case Similarity、Management Summary、Safety/Hallucination gate）—— 這些已在 `main` 完成，regression suite 若不含，rule / model 改動可能打壞已交付功能卻不被偵測。Phase 6 中 Status = `Planned` 的類別（Role/Persona、Time-series QA）在其 runner 就緒前不列入。
- **§12.3 的 Gate A / B / C**：判定與允許退步幅度**一律以 §12.3 的表為準**，本節不另訂門檻。Step 13 三類等 deterministic 類別的 regression 判定是「輸出對 fixture 預期逐項相等 / 數值 tolerance」（即 `energyops_deterministic_pass_rate`，允許退步 0），不是分數比較。任一 Gate 觸發即 FAIL，不看 `weighted_total`。

---

# Phase 10 — AI Evaluation Lab / EvalCore  ·  **Non-MVP reference**

> **範圍界定**：本 Phase 描述的「AI Evaluation Lab / EvalCore」是一個**獨立的未來 portfolio 專案**，不是 AI Energy Operations Copilot 這個 repo 的一部分。它**不是本專案的 acceptance gate，不得阻擋 MVP v1 的完成判定**。放在這裡只作為長期方向參考；本專案實際要交付的評測範圍以 Phase 5 / Phase 6 / Phase 9 的 **Planned work** 為準。

最終架構（EvalCore 專案的願景，非本 repo 待辦）：

```text
             AI Evaluation Lab

Dataset Registry
       ↓
Benchmark Registry
       ↓
Evaluation Runner
       ↓
 ├──────┼──────┐
GPT  Claude  Nemotron
       ↓
Evaluation Engine
       ↓
 ├─────────────────┐
Quality
RAG
Performance
Cost
Reliability
Safety
Agent
 ├─────────────────┘
       ↓
Results Database
       ↓
Scorecard
       ↓
Dashboard
       ↓
Quality Gate
```

---

# 12. 最終 AI Scorecard 範例

| Category | GPT | Claude | Nemotron |
|---|---:|---:|---:|
| General | 89 | 92 | 88 |
| Coding | 91 | 96 | 87 |
| RAG | 90 | 94 | 93 |
| EnergyOps | 84 | 95 | 91 |
| Latency | 82 | 78 | 94 |
| Cost | 71 | 69 | 95 |
| Reliability | 91 | 94 | 90 |

最後不是單純算平均，而是走一套**可重現**的計分：相同輸入一定得到相同決策。

### 12.1 每個 raw metric 正規化到共同的 0–100 sub-score

| Metric 類型 | 例子 | 方向 | 正規化公式 |
|---|---|---|---|
| Judge 1–5 分 | correctness / groundedness / completeness | 越高越好（benefit） | `sub = (raw − 1) / 4 × 100` |
| 已是百分比 | hit@K、citation correctness、domain action 正確率 | 越高越好（benefit） | `sub = raw`（clamp 到 0–100） |
| Latency（p95, ms） | `/assistant` 端對端 p95 | 越低越好（cost 面） | `sub = clamp(0, 100, 100 × (L_budget − p95) / (L_budget − L_target))` |
| Cost（USD / 100 evaluated turns） | 見第 14 節成本計算 | 越低越好（cost 面） | `sub = clamp(0, 100, 100 × (C_budget − cost) / (C_budget − C_target))` |
| Reliability | 1 − (失敗數 / 總數) | 越高越好（benefit） | `sub = raw × 100` |

`L_target / L_budget`、`C_target / C_budget` 是每次評測前在 config 明確填的門檻值（target = 理想、budget = 可接受上限），不寫死在文件裡。

**Config validation（套公式前必做）**：對 latency 與 cost 的 `(target, budget)`，必須滿足 `0 <= target < budget`。任一不成立（含 `target == budget` 造成除以 0、或 `target > budget` 造成方向反轉）→ **直接拒絕整份 config、不計算任何分數**，回報 `INVALID_CONFIG` 並指出違規的那組值。

### 12.1a Canonical scorecard inputs（每個加權輸入綁定單一 canonical metric）

`weighted_total` 的每個輸入都是一個明確定義的 canonical metric，不是複合標籤。

| Weighted input（§12.2 用） | Canonical metric | Raw source | 推導 / 正規化 | 方向 | 缺值 policy |
|---|---|---|---|---|---|
| RAG Accuracy | `answer_correctness_sub` | `run_answer_accuracy_benchmark.py` 的 `averages.correctness`（1–5） | `sub = (raw − 1) / 4 × 100` | benefit | 未產生 → `NOT_EVALUATED` |
| Groundedness | `groundedness_sub` | 同上 `averages.groundedness`（1–5） | `sub = (raw − 1) / 4 × 100` | benefit | 未產生 → `NOT_EVALUATED` |
| Domain Accuracy | `energyops_deterministic_pass_rate` | Phase 6 中 Status = `Implemented + measurable` 的 deterministic 類別（Battery Scheduling / Cost / Green Ops / Fault Diagnosis / CSV Ingestion / Case Similarity / Management Summary）之 fixture 通過率 | `sub = 100 × pass / total`（deterministic，理想 100） | benefit | 任一必要類別未跑 → `NOT_EVALUATED` |
| Latency | `p95_latency_sub` | 該次 benchmark run 的 `/assistant` 端對端 p95（ms） | `sub = clamp(0, 100, 100 × (L_budget − p95) / (L_budget − L_target))` | cost 面 | 未量測 → `NOT_EVALUATED` |
| Cost | `cost_sub` | 該次 run 的 USD / 100 evaluated turns（見 §14 計算） | `sub = clamp(0, 100, 100 × (C_budget − cost) / (C_budget − C_target))` | cost 面 | 未量測 → `NOT_EVALUATED` |
| Reliability | `reliability_sub` | 該次 run 的 `1 − (message status 為 failed/aborted 的數 / 總 assistant turn 數)` | `sub = raw × 100` | benefit | 未量測 → `NOT_EVALUATED` |

任一 canonical metric 為 `NOT_EVALUATED`：不計算完整 `weighted_total`，Recommendation 不得 `ADOPT`（見 §12.4）。

### 12.2 加權總分

`sub_score_i` 已正規化到 0–100，所以加權後必須除以權重總和，否則結果會落在 0–10000 而不是 ADOPT 門檻用的 0–100：

```text
weighted_total = Σ ( weight_i × sub_score_i ) / Σ ( weight_i )
```

若權重以百分比表示且 `Σ weight_i = 100`，即等同於 `Σ ( weight_i × sub_score_i ) / 100`；也可直接把權重寫成加總為 1 的分數。`weighted_total` 恆落在 `[0, 100]`。

EnergyOps 權重（可依專案調整，加總為 100 或 1 皆可）：

```text
RAG Accuracy       30
Groundedness       20
Domain Accuracy    20
Latency            10
Cost               10
Reliability        10
（Σ = 100）
```

`weighted_total` 只用於 12.4 的決策門檻；**12.3 的 hard gates 完全獨立於 `weighted_total`**：任一 hard gate 不過即 REJECT，不論加權總分多高。

### 12.3 Hard gates（任一不過 ⇒ 直接 REJECT，完全獨立於 `weighted_total`）

**Gate A — Groundedness 下限**：Groundedness sub-score `>= 60`（≈ judge 3.4 / 5）。

**Gate B — Safety violation（categorical，不是 sub-score）**：EnergyOps-Bench 的 Battery Scheduling safety violation 數 `== 0`。violation 定義同 Phase 6 Battery Scheduling 列的 Safety invariant：blanket-safety 列出現 charge/discharge，或 discharge-veto 列出現 discharge。

**Gate C — Protected-metrics regression**：下表每個 protected metric 相對其 baseline 的退步不得超過「允許退步幅度」。

| Protected metric | 方向 | Baseline 來源（現行 `main` 產物） | 允許退步幅度 |
|---|---|---|---|
| `answer_correctness_sub` | 越高越好 | `run_answer_accuracy_benchmark.py` 上一次記錄的 `averages.correctness`，經 §12.1a 正規化 | 5（sub-score 分） |
| `groundedness_sub` | 越高越好 | 同上 `averages.groundedness`，經正規化 | 3（更嚴，防幻覺） |
| `retrieval_hit_at_1` | 越高越好 | 由 `retrieval_benchmark_report.json` 的 **per-question** 結果計算（見下方 `hit@k` 定義），document-scoped | 8（百分點；hit@1 波動大，容忍略寬） |
| `retrieval_hit_at_3` | 越高越好 | 同上，document-scoped | 5（百分點） |
| `energyops_deterministic_pass_rate` | 越高越好 | 上一次 baseline 執行（deterministic，理想 100%） | 0（deterministic，不容退步） |

**`hit@k` 定義**（`retrieval_benchmark_report.json` 沒有 aggregate `hit_at_k` 欄位，需自算）：

```text
eligible_questions = 報告內的題目 − excluded_questions
hit@k = 100 × count( eligible q 的 hit_rank <= k ) / count( eligible_questions )
```

> 若希望 `run_retrieval_benchmark.py` 直接輸出 `document_scoped.hit_at_1 / hit_at_3` aggregate 欄位以省去自算，列為 **Planned work**；在那之前一律由 per-question `hit_rank` 計算。

不在此表的分數（Latency、Cost、Reliability、Domain Accuracy 等）只計入 `weighted_total`，不觸發 Gate C。

**Missing baseline policy**：任一 protected metric 沒有可比對的 baseline（第一次執行、或 baseline 檔缺失）→ 標記 `NOT_EVALUATED`，Gate C 對它不判 pass/fail；且整體 Recommendation 最高只能到 `CONDITIONAL`、不得 `ADOPT`，直到該 metric 有 baseline。

### 12.4 決策門檻

先判 config validation 與 Gate A/B/C，再看 `weighted_total`：

| 條件 | Recommendation |
|---|---|
| config validation 失敗 | **INVALID_CONFIG**（不計分） |
| Gate A / B / C 任一不過 | **REJECT** |
| Gate 全過，但有任一 §12.1a canonical scorecard input 或 §12.3 protected metric 為 `NOT_EVALUATED` | 最高 **CONDITIONAL**（即使 `weighted_total >= 80` 也不 ADOPT，直到該項有 baseline / 量測值） |
| Gate 全過、無 `NOT_EVALUATED`、`weighted_total >= 80` | **ADOPT** |
| Gate 全過、無 `NOT_EVALUATED`、`65 <= weighted_total < 80` | **CONDITIONAL**（附「要補什麼才能升到 ADOPT」的具名條件） |
| Gate 全過、`weighted_total < 65` | **REJECT** |

> 關鍵性質：給定同一份 metrics、同一份（已通過 validation 的）config、同一份 baseline，12.1–12.4 是純函式 —— 相同輸入必得相同 `weighted_total` 與 Recommendation。

---

# 13. 第一次實作不要準備太大

第一個版本只需要：

```text
10 Test Cases
      ↓
2 Models
      ↓
Manual Ground Truth
      ↓
Accuracy
Latency
LLM Judge
      ↓
Scorecard
```

不要一開始就上：

```text
Kubernetes
Multi-GPU
Prometheus
大型 Benchmark
1000 題 Dataset
完整 Dashboard
```

先建立 Evaluation 思維，再逐步擴張。

---

# 14. 建議實際學習路線

## Step 1

理解：

```text
Benchmark
Ground Truth
Metric
Baseline
Regression
```

---

## Step 2

自己設計第一份：

```text
10 題 Benchmark
```

---

## Step 3

人工比較：

```text
GPT vs Claude
```

---

## Step 4

Python 自動化：

```text
evaluation_runner.py
```

---

## Step 5

加入：

```text
LLM-as-a-Judge
```

---

## Step 6

看 NVIDIA NeMo Evaluator 官方影片：

https://www.youtube.com/watch?v=Fo9kNJE5nC8

---

## Step 7

實際跟 NVIDIA NeMo Evaluator。

---

## Step 8

加入 RAG Evaluation：

https://docs.nvidia.com/rag/latest/evaluate.html

---

## Step 9

建立：

```text
EnergyOps-Bench
```

---

## Step 10

加入 NVIDIA AIPerf：

https://docs.nvidia.com/nim/benchmarking/llm/latest/

---

## Step 11

建立 Regression Evaluation。

---

## Step 12

最後加入 Agent Evaluation：

https://docs.nvidia.com/nemo/gym/main/about/concepts/evaluation

---

# 15. 核心心法

永遠不要只問：

```text
Which model is best?
```

而要問：

```text
Which model is best
for THIS workload,
under THESE quality requirements,
with THIS latency requirement,
at THIS cost?
```

真正有價值的 AI Evaluation，不是找出「全世界最強模型」。

而是：

> 找出在特定業務與工程限制下，最值得 Production 使用的 AI 系統。

---

# 16. 建議長期專案名稱  ·  **Non-MVP reference**

> 本節與第 15 節之後的內容都屬 **Non-MVP reference**：是「evaluation 能力長成一個獨立專案」後的命名與範圍構想，**不是 AI Energy Operations Copilot repo 的待辦，也不阻擋本專案完成**。

暫定：`EvalCore` 或 `AI Evaluation Lab`。

未來（獨立專案內）可以逐步包含：

```text
Model Evaluation
RAG Evaluation
Agent Evaluation
Performance Benchmarking
Cost Analysis
LLM-as-a-Judge
Regression Testing
Domain Benchmark
Quality Gates
Dashboard
```

它會是一個**獨立的 Portfolio Project**，可作為其他 AI 專案共用的 Evaluation Infrastructure —— 但那是另一個 repo 的事，本專案的評測交付範圍以 Phase 5 / 6 / 9 的 Planned work 為界。

---

## 補充（Claude Code 審閱建議，2026-07-27；2026-09-07 依 Codex review 修訂）

> 2026-09-07 修訂：此 roadmap 原稿寫於 Step 13 / Step 14 與 PR #70（answer-accuracy / groundedness hardening）完成之前，部分「待新增」的評測其實已在 `main` 實作。本次修訂：① 第 1a 節加入 Current baseline / Planned work / Non-MVP reference 三態標記；② Phase 5 區分已實作 baseline 與真正缺口；③ Phase 6 EnergyOps-Bench 補上 Step 13 三類與其 acceptance metrics（依現有 deterministic rule / API contract / 既有測試）；④ 第 12 節 Scorecard 補上正規化公式、hard gates 與 ADOPT/CONDITIONAL/REJECT 門檻；⑤ 下方第 2 點的 chat 成本估算改為依 runner 記錄的 token usage 計算；⑥ Phase 10 與第 16 節明確標為 Non-MVP reference。

以下是套用在 `AI Energy Operations Copilot (MVP_V1)` 時的具體修正建議：

1. **`EnergyOps-Bench` 不用從零寫 100 題**：先重用 `spike/test_questions.json`（29 題，已有真實 retrieval baseline 數字）、`chunking_comparison_report.json`、`retrieval_benchmark_report.json` 當作 Phase 5/6 的第一批測試集，站在既有驗證基礎上，而不是重工。Step 13 三類（battery scheduling / cost / green ops）則沿用 `scripts/synthetic_step13/` 的合成 fixture 與 `backend/tests/test_step13_*` 的斷言。
2. **Chat / Judge 評測的成本計算（不要用 `embed-cost-estimate` skill）**：`.claude/skills/embed-cost-estimate` 只解析 PDF 並用 `text-embedding-3-small` 的 ingestion token 計價，**不含 chat 的 input/output token，也沒有 generation／judge 模型的價格**，拿來估 AI Battle / LLM-as-a-Judge 的花費會嚴重低估。正確做法：

   ```text
   cost_per_model = input_tokens  / 1_000_000 × input_price_per_1M
                  + output_tokens / 1_000_000 × output_price_per_1M

   total_cost = cost(evaluated_model) + cost(judge_model)   # 兩個模型分開算再相加
   ```

   - `input_tokens` / `output_tokens` 取自 **runner 實際記錄的 per-call usage**（OpenAI response 的 `usage` 物件；`run_answer_accuracy_benchmark.py` 若尚未持久化 usage，補一個「把每次呼叫的 usage 寫進報告」的小改動 —— 屬 Planned work），**不要**用 PDF 重新估算。
   - 單價由**執行時參數**或**附日期的設定檔**提供（例如 `eval/model_prices.2026-09-07.json`），**不要把易過期的價格寫死在程式碼或這份文件裡**。
   - 事前概估（還沒有 usage 時）：用「每題平均 input/output token × 題數」粗估，並在報告標明是估算值。
3. **定位**：此文件是長期參考地圖。Phase 1 → 3 是實際教學路線；Phase 4 起若標 **Current baseline** 表示已在 `main` 可執行、只補缺口，標 **Non-MVP reference**（如 Phase 10、第 16 節）則是獨立專案願景、不阻擋本專案完成。
