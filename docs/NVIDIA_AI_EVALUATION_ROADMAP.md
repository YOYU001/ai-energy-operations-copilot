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

**狀態**：Planned work（題庫尚未建），但**必須涵蓋 `main` 上已完成的所有 MVP 能力**，否則 model / rule / prompt 改動可能打壞已交付的功能卻不影響任何 EnergyOps-Bench 數字。

### 題型分佈（含 Step 13 的三項 rule 分析）

| 題型 | 題數 | 對應 `main` 能力 |
|---|---:|---|
| Document QA | 20 | `/assistant` + RAG（`search_documents`） |
| Fault Diagnosis | 15 | `/datasets/{id}/analysis`（`BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`） |
| Time-series QA | 15 | `/assistant` + dataset tools |
| RAG Retrieval | 15 | `run_retrieval_benchmark.py` 題庫 |
| **Battery Scheduling** | 10 | `/datasets/{id}/schedule`（`battery_scheduling_v1`） |
| **Cost Estimation** | 5 | `/datasets/{id}/cost`（`cost_estimation_v1`） |
| **Green Operations Index** | 5 | `/datasets/{id}/green-operations-index`（`green_operations_index_v1`） |
| Safety / Hallucination | 5 | groundedness gate、rule safety veto |
| Management Summary | 5 | `/datasets/{id}/report`（Step 14） |

Test Case schema（沿用，非新增）：

```json
{
  "id": "energy_001",
  "category": "battery_scheduling",
  "dataset_fixture": "scripts/synthetic_step13/…",
  "question": "...",
  "expected": { "...": "見下方各類別的 acceptance metric" },
  "difficulty": "medium"
}
```

### Step 13 三類的 acceptance metrics（依現有 API contract、deterministic rule 與既有測試設計，不可憑空編造）

這三類的規則是 **deterministic**（`evaluate_battery_scheduling` / `evaluate_cost_estimation` / `evaluate_green_operations_index` 皆為純函式），所以對固定的 synthetic fixture，「正確輸出」是唯一且可精確比對的。已有的 `backend/tests/test_step13_*.py` 與 `test_step13_synthetic_integration_validation.py` 就是這些 metric 的參考實作。

**Battery Scheduling**（`POST /datasets/{id}/schedule` → `ScheduleRunResponse`，每列 `ScheduleRecommendation`）

| 檢查 | 通過條件 |
|---|---|
| Correct action | 每列 `action ∈ {"charge","discharge","idle","hold"}` 與 fixture 的預期值**逐列完全相等**（deterministic rule，action label 容差 = 0） |
| Correct price class | 每列 `price_classification ∈ {"low","normal","high"}` 與預期相等 |
| **Safety-rule violation（hard fail）** | 任一列若 `battery_temperature ≥ 40` 或 `battery_health_status == "critical"` 或 `battery_soc ≤ 20`（`SOC_SAFETY_THRESHOLD`）或 `battery_soh < 80`（`SOH_VETO_THRESHOLD`），其 `action` 必須是 `hold` 或 `idle`，**絕不可**是 `charge` / `discharge`。出現任一違反 = 整個 case FAIL，且觸發第 12 節的 safety hard gate |
| insufficient-data 行為 | 對「所有 `_REQUIRED_COLUMNS` 皆缺」的 fixture，`evaluated_row_count == 0`，回應仍為 HTTP 200 且不誤觸任何 charge/discharge |

**Cost Estimation**（`POST /datasets/{id}/cost` → `CostRunResponse`，`per_site` + `dataset_aggregate`）

| 檢查 | 通過條件 |
|---|---|
| Energy cost 數值 tolerance | `total_energy_cost` 與 fixture 手算值（`Σ grid_import_kw × duration_hours × electricity_price`）的相對誤差 ≤ `1e-6` |
| Arbitrage 數值 tolerance | `total_arbitrage_saving` 與手算值（放電 `+power×dur×price`、充電 `−|power|×dur×price`）相對誤差 ≤ `1e-6` |
| Over-contract flags | `over_contract_penalty_flags` 的數量與被標記的 interval 與預期**完全一致** |
| Multi-site 一致性 | `dataset_aggregate` 的金額 == `Σ per_site`（同 tolerance） |
| Warning 行為 | 對「有時間缺口 / 末列不完整」的 fixture，`warnings: list[AnalysisNote]` 至少含對應 `type` 的一筆 |
| insufficient-data 行為 | 對「零個 valid interval」的 fixture，回應 HTTP 200、金額為 0、不 crash |

**Green Operations Index**（`POST /datasets/{id}/green-operations-index` → `GreenOpsRunResponse`）

| 檢查 | 通過條件 |
|---|---|
| Component 分數界限 | 4 個 component 分數各自 ∈ `[0, max_score]`（max 分別為 `pv_utilization 25 / battery_operation 20 / grid_dependency 20 / battery_health 25`） |
| Total 上限 | `total_score`（含 `second_life_bonus`）≤ 100 |
| Golden fixture 數值 tolerance | 對 golden fixture，`total_score` 與手算值誤差 ≤ `0.01` |
| insufficient-data 行為 | 對「缺 `compute_valid_intervals` 所需欄位」的 fixture，每個 component `status == "insufficient_data"` 且 `total_score is None`（不是 0） |
| Second-life bonus 條件 | `second_life_bonus` 只有在重用的 `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT` 規則判定 eligible 且無 safety veto 時才 > 0 |

> 這三類的 fixture 直接沿用 `scripts/synthetic_step13/` 既有合成資料 + `backend/tests/test_step13_*` 的斷言，EnergyOps-Bench 只是把它們包成統一 case 格式並納入 regression 報告，不是重寫規則測試。

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

### Regression suite 的最低覆蓋（對齊 `main` 現況）

當這套 suite 被當成本專案的 regression gate，它**必須**包含：

- Phase 5 的 Current baseline 兩支 runner（retrieval hit@K、answer-accuracy judge 分數）
- Phase 6 EnergyOps-Bench 的**全部**題型，特別是 Step 13 三類（Battery Scheduling / Cost Estimation / Green Operations Index）—— 這三項的 API 與 dashboard 已在 `main` 完成，若 regression suite 不含它們，rule / model 改動可能打壞已交付功能卻不被偵測
- 第 12.3 的三條 hard gate（groundedness 下限、EnergyOps-Bench safety-rule violations == 0、hard-gated metric 退步 > 5 分）；任一觸發即 FAIL，不看總分

Step 13 三類因為是 deterministic rule，regression 判定用「輸出與 fixture 預期逐項相等 / 數值 tolerance」，不是分數比較（見 Phase 6 的 acceptance metrics）。

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

- **Benefit metrics**（sub 越高越好）：RAG Accuracy、Groundedness、Domain Accuracy、Reliability、hit@K、Citation Correctness。
- **Cost/latency metrics**（raw 越低 → sub 越高）：p95 latency、USD / 100 turns。

### 12.2 加權總分

```text
weighted_total = Σ ( weight_i × sub_score_i ) ，其中 Σ weight_i = 100
```

EnergyOps 權重（可依專案調整，但必須加總為 100）：

```text
RAG Accuracy       30
Groundedness       20
Domain Accuracy    20
Latency            10
Cost               10
Reliability        10
```

### 12.3 Hard gates（任一不過 ⇒ 直接 REJECT，不看 weighted_total）

```text
1. Groundedness sub-score ≥ 60           （≈ judge 3.4 / 5；低於此代表防幻覺不合格）
2. EnergyOps-Bench safety-rule violations == 0
   （Battery Scheduling 在 temp≥40 / health=critical / SOC≤20 / SOH<80 時
    出現 charge/discharge 即為 violation）
3. 相對 baseline，任一 hard-gated metric 的 sub-score 退步 > 5 分
```

### 12.4 決策門檻（hard gates 全過之後，看 weighted_total）

| weighted_total | Recommendation |
|---|---|
| ≥ 80 | **ADOPT** |
| 65 – 79 | **CONDITIONAL**（必須附「要補什麼才能升到 ADOPT」的具名條件） |
| < 65，或任一 hard gate 不過 | **REJECT** |

> 關鍵性質：給定同一份 metrics 與同一份 config（權重、target/budget），12.1–12.4 是純函式 —— 兩個人算出的 `weighted_total` 與 Recommendation 必定相同。

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
