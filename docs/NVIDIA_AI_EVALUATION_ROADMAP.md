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

**狀態**：Planned work（題庫尚未建）。範圍宣稱限縮為：**涵蓋每一項「可由 backend 自動驗證」的 MVP 能力**。完整的 MVP validation = **automated backend suite（EnergyOps-Bench + `run_*_benchmark.py`）＋ frontend manual checklist**；只有前者是 EnergyOps-Bench 的責任範圍。

### 題型分佈

| 題型 | 題數 | 對應 `main` 能力 | 驗證層 |
|---|---:|---|---|
| Document QA | 15 | `/assistant` + RAG（`search_documents`） | backend automated |
| CSV Ingestion | 10 | `POST /datasets/upload`（enum / 型別驗證、warning report、寫入 `datasets` / `energy_timeseries`） | backend automated |
| Fault Diagnosis | 15 | `GET/POST /datasets/{id}/analysis`（`BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`） | backend automated |
| Time-series QA | 10 | `/assistant` + dataset tools | backend automated |
| RAG Retrieval | 15 | `run_retrieval_benchmark.py` 題庫 | backend automated |
| Battery Scheduling | 10 | `GET/POST /datasets/{id}/schedule`（`battery_scheduling_v1`） | backend automated |
| Cost Estimation | 5 | `GET/POST /datasets/{id}/cost`（`cost_estimation_v1`） | backend automated |
| Green Operations Index | 5 | `GET/POST /datasets/{id}/green-operations-index`（`green_operations_index_v1`） | backend automated |
| Case Similarity | 10 | `GET /cases/{case_id}/similar`、`POST /cases/search` | backend automated |
| Role / Persona Behavior | 5 | conversation `role_mode` | backend automated（live model；斷言只查不變量，見下） |
| Safety / Hallucination | 5 | groundedness gate、rule safety veto | backend automated |
| Management Summary | 5 | `GET/POST /datasets/{id}/report`（Step 14，`analysis_report_v1`） | backend automated |

**明確不在 EnergyOps-Bench（backend automated）範圍內**：固定圖表 Dashboard（Step 8）的實際 render 與互動 —— 專案目前沒有 frontend 自動化測試框架（已記錄的範圍決策），因此 Dashboard 列為 **frontend manual smoke test**，由 frontend manual checklist 涵蓋，不宣稱由 backend EnergyOps-Bench 自動驗證。

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

---

### Acceptance metrics

**設計原則**（避免 roadmap 與 `main` 漂移）：

- roadmap 只寫**穩定、可讀的 acceptance invariant**（「這個能力對這個 fixture 應該成立什麼」）。
- 容易變動的 **enum、threshold、欄位名、內部函式細節**不在 roadmap 複述，改指向 `main` 最新的具體 code / test symbol 當 single source of truth。建 benchmark 時直接沿用該 test 的斷言。
- roadmap 自己定義的 **engineering policy**（數值 tolerance、score normalization、weights、decision thresholds、missing-baseline policy）才寫完整，且必須可重現。
- Step 13 三類與 Analysis Report 是 **deterministic 純函式**，對固定 fixture「正確輸出」唯一；Role/Persona 走 live model，斷言只查不變量、不要求逐字相同。

**共用數值 tolerance**（roadmap engineering policy，非既有程式 contract）：所有「數值對手算值」的比對用

```text
pass  ⟺  abs(actual − expected) <= max(abs_tol, rel_tol × abs(expected))
        abs_tol = 1e-6 ,  rel_tol = 1e-9
```

`expected == 0` 時由 `abs_tol` 決定，不做除以 0 的相對誤差。

**每個 fixture 宣告一個 `expected_terminal_outcome`**：`answerable` 的 case 期望正常回答（`finish_reason` 既不是 `"ungrounded_retry_exhausted"` 也不是 `"insufficient_data"`）；`insufficient_evidence` 的 case 期望 `finish_reason == "insufficient_data"`。切換 `role_mode` 不得改變同一 fixture 的 `expected_terminal_outcome`。

| Capability | Stable acceptance invariant | Source of truth（`main` symbol） | Test layer |
|---|---|---|---|
| **Battery Scheduling** | 對 fixture，每列 `action` 與 `price_classification` 與 deterministic rule 的輸出逐列相等（容差 0）。**Safety**：`temperature` 或 `health_status` 觸發 blanket 安全覆寫的列，`action` 不得是 charge 或 discharge（rule 回 idle）；`battery_soc` / `battery_soh` 觸發 discharge veto 的列，`action` 不得是 discharge（在充電條件成立時回 charge 是正確的）。任一 blanket-safety 列出現 charge/discharge、或任一 discharge-veto 列出現 discharge，視為 safety violation（→ §12.3 categorical hard gate）。缺全部必要欄位的列回 `hold` 並帶 insufficient-row warning。 | `backend/app/services/battery_scheduling.py`（`_build_recommendation` 的 Step 1–5、`TEMPERATURE_SAFETY_THRESHOLD` / `SOC_SAFETY_THRESHOLD` / `SOH_VETO_THRESHOLD`）、`price_classification.py` `classify_price` | `test_step13_integration.py`、`test_low_soc_with_charge_condition_charges`、`test_soh_low_with_charge_condition_charges` |
| **Cost Estimation** | `total_energy_cost` / `total_arbitrage_saving`（per-site 與 `dataset_aggregate`）對 fixture 手算值滿足共用 tolerance；`dataset_aggregate` 為各 site 直接相加。over-contract flag 的數量與位置與 rule 輸出一致。**Note 分流**：末列不完整 → 反映在 `limitations`（`AnalysisNote.type == "last_row_excluded"`）；真正的時間缺口 → 反映在 `warnings`。零 valid interval 的 fixture 回 HTTP 200、金額 0.0、不 raise。 | `backend/app/services/cost_estimation.py`（`_evaluate_site`、`_aggregate_sites`；`limitations` / `warnings` 分流依 `note.type`） | `test_step13_integration.py`、`test_last_row_excluded_reported_as_limitation_not_warning` |
| **Green Operations Index** | 每個 component `score` 落在 `[0, max_score]`、`status` 為 rule 定義的其中一個值；`total_score`（缺料時為 `None`，不是 0）對 golden fixture 滿足共用 tolerance 且不超過各 max 加總 + bonus 上限。**Second-life bonus**：所有條件只量化 `compute_valid_intervals` 產生的 **eligible interval-start rows**（`_evaluate_site` 傳給 `_compute_second_life_bonus` 的正是 `pd.DataFrame(start_rows)`）；被排除的末列 / invalid interval 的資料不影響 expected bonus。bonus 的三態（disqualified `0.0` / confirmed-safe `10.0` / unknown `None`，加上「沒有 second-life 列」與「缺必要欄位」）以 `_compute_second_life_bonus` 的 docstring 為準。 | `backend/app/services/green_operations_index.py`（`COMPONENT_MAX_SCORES`、`_score_component`、`_sum_total_score`、`_compute_second_life_bonus`、`_evaluate_site` 的 `start_rows`）、`schemas.py` `GreenOpsComponentScore` | `test_step13_integration.py`、`test_green_ops_total_score_none_reads_as_insufficient_data` |
| **Case Similarity** | 對固定 query / `case_id`，已知最相關的 seed case 出現在回傳 top-k 內；結果依 `final_score` 遞減排序；每筆的 `confidence` / `case_similarity` label 與其分數落在對應 bucket **自洽**（threshold 在程式碼標為 PROVISIONAL，只查自洽、非絕對品質門檻）；`top_k` 超出允許範圍回 HTTP 422，回傳筆數為 `min(top_k, seed 案例數)`（無低分 cutoff）；回應不含 `root_cause` / `operator_action` / `resolution_result`。 | `backend/app/services/case_similarity.py`（`score_candidates`、`confidence_for_score`、`case_similarity_label`、`CONFIDENCE_THRESHOLDS` / `CASE_SIMILARITY_THRESHOLDS`）、`schemas.py`（`CaseSearchResult`、`CaseSearchRequest.top_k`）、`scripts/seed_case_records.py` | `test_cases_api.py` |
| **Role / Persona Behavior** | 對同一問題，四種 `role_mode` 各跑一次，斷言下列**不變量**（不要求逐字相同）：<br>① 提供給模型的 tool schemas（`_tools_for_turn` 結果）與 capability-guard 判定（`looks_like_diagnostic_question`）在四種 mode 下相同；<br>② 每一條實際產生的 claim 都通過 groundedness gate（`finish_reason` 不是 `"ungrounded_retry_exhausted"`）；<br>③ terminal outcome 等於該 fixture 宣告的 `expected_terminal_outcome`；<br>④ 都產生七段式標題；<br>⑤ 建立 / 更新 conversation 帶非 Literal `role_mode` → HTTP 422。<br>**允許**差異：語氣、深度、資訊密度、引用的有據事實數量、以及在**同一組 eligible 工具**中實際選用的子集。 | `backend/app/main.py`（`ROLE_MODE_FRAMING` 只加 framing、不進 `_tools_for_turn` / capability guard；`_SEVEN_PART_INSTRUCTION`；`finish_reason = "ungrounded_retry_exhausted"`）、`schemas.py` `RoleMode = Literal[...]` | `test_conversations_api.py`、`test_chat_streaming_tool_orchestration.py` |
| **CSV Ingestion** | canonical enum（`ems_mode` / `equipment_status`）合法值不產生 warning；大小寫 / 空白正規化；非法 enum 值產生 warning 並存為 `unknown`；timestamp / 數值 / `battery_health_status` 驗證維持；資料寫入 `datasets` / `energy_timeseries`（batch insert）。 | `backend/app/ingestion.py`（`parse_and_validate_csv`、canonical enum sets）、`backend/app/main.py` `POST /datasets/upload` | `test_ingestion.py`、`test_datasets_api.py`、`test_datasets_queries.py` |
| **Management Summary** | `rule_version` 與 6 個 section `key` 齊全；每個 `ReportSection.status` 為 rule 定義的其中一個值；`dataset_overview` 恆 `included`、`similar_cases` 恆 `manual_lookup`；`anomaly_diagnosis` / `battery_schedule` / `cost_estimate` / `green_operations_index` 四者：sub-analysis 有跑 → `included`，沒跑 → `not_run` 且 `note` 非空。**Provenance 只套用在這四個 sub-analysis section**：`included` 時 `source_analysis_run_id` 非 None 且 `source_created_at` == 該 sub-run 的建立時間；`dataset_overview` 即使 `included`，其 `source_analysis_run_id` / `source_created_at` 仍為 `None`（`_dataset_overview_section` 刻意不填）。`limitations` 的 `kind` 為 schema 定義的其中一個值，not-run section → 至少一筆 `section_not_run`，快照過舊 → 一筆 `snapshot_staleness`。有 sub-analysis 時 `key_findings` 非空；異常存在時 `suggested_actions` 反映之。空資料集不 raise、`row_count == site_count == 0`、overview 仍 `included`；green-ops `total_score is None` 時該 section 仍 `included` 但 summary 標示資料不足。 | `backend/app/services/analysis_report.py`（`RULE_VERSION`、`SECTION_*`、`_dataset_overview_section`（provenance 留 None）、`_similar_cases_section`、`_not_run_section`）、`schemas.py`（`ReportSection`、`ReportLimitation.kind`） | `test_analysis_report.py`（`test_all_sub_analyses_present_all_sections_included`、`test_no_sub_analyses_only_overview_included_rest_not_run`、`test_partial_only_anomaly_present`、`test_empty_dataset_does_not_raise_and_reports_zero_rows`、`test_green_ops_total_score_none_reads_as_insufficient_data`） |
| **Document QA / Time-series QA / RAG Retrieval / Safety-Hallucination** | 沿用 `run_answer_accuracy_benchmark.py`（judge 分數 + `expected_terminal_outcome`）與 `run_retrieval_benchmark.py`（`hit@K`）的既有斷言；Safety-Hallucination case 的 `expected_terminal_outcome` 為 `insufficient_data` 或「回答但每條 claim grounded」。 | `backend/scripts/run_answer_accuracy_benchmark.py`、`run_retrieval_benchmark.py`、`retrieval_metrics.py`、`groundedness.py` | `test_groundedness.py` + 兩支 runner（手動，有 API 費用） |

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

**Config validation（套公式前必做）**：對 latency 與 cost 的 `(target, budget)`，必須滿足 `0 <= target < budget`。任一不成立（含 `target == budget` 造成除以 0、或 `target > budget` 造成方向反轉）→ **直接拒絕整份 config、不計算任何分數**，回報 `INVALID_CONFIG` 並指出違規的那組值。

- **Benefit metrics**（sub 越高越好）：RAG Accuracy、Groundedness、Domain Accuracy、Reliability、hit@K、Citation Correctness。
- **Cost/latency metrics**（raw 越低 → sub 越高）：p95 latency、USD / 100 turns。

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

| Metric（canonical name） | 方向 | Baseline 來源 | 允許退步幅度 |
|---|---|---|---|
| `answer_correctness_sub`（judge correctness 正規化後） | 越高越好 | `run_answer_accuracy_benchmark.py` 上一次記錄的 `averages.correctness` | 5（sub-score 分） |
| `groundedness_sub`（judge groundedness 正規化後） | 越高越好 | 同上 `averages.groundedness` | 3（更嚴，防幻覺） |
| `retrieval_hit_at_3`（document-scoped） | 越高越好 | `retrieval_benchmark_report.json` 的 `document_scoped.hit_at_3` | 5（百分點） |
| `retrieval_hit_at_1`（document-scoped） | 越高越好 | 同上 `document_scoped.hit_at_1` | 8（百分點；hit@1 波動大，容忍略寬） |
| `energyops_deterministic_pass_rate`（Step 13 三類 + Analysis Report 的 fixture 通過率） | 越高越好 | 上一次 baseline 執行（deterministic，理想恆為 100%） | 0（deterministic，不容任何退步） |
| `p95_latency_sub`（`/assistant` 端對端 p95 正規化後） | 越高越好 | 上一次 baseline run 的 p95 | 5（sub-score 分） |

不在此表的分數（例如 Reliability、Domain Accuracy 的細項）只計入 `weighted_total`，不觸發 hard gate。

**Missing baseline policy**：任一 protected metric 沒有可比對的 baseline（第一次執行、或 baseline 檔缺失）→ 該 metric 標記 `NOT_EVALUATED`，Gate C 對它不判 pass/fail。**只要有任一 protected metric 為 `NOT_EVALUATED`，整體 Recommendation 最高只能到 `CONDITIONAL`，不得 `ADOPT`**，直到所有 protected metric 都有 baseline。

### 12.4 決策門檻

先判 config validation 與 Gate A/B/C，再看 `weighted_total`：

| 條件 | Recommendation |
|---|---|
| config validation 失敗 | **INVALID_CONFIG**（不計分） |
| Gate A / B / C 任一不過 | **REJECT** |
| Gate 全過，但有任一 protected metric 為 `NOT_EVALUATED` | 最高 **CONDITIONAL**（即使 `weighted_total >= 80` 也不 ADOPT，直到 baseline 建立） |
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
