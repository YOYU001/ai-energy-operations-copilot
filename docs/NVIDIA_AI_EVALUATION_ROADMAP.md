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

正式加入：

```text
Answer Accuracy
Context Relevancy
Groundedness
Recall@K
Citation Correctness
```

官方 NVIDIA：

https://docs.nvidia.com/rag/latest/evaluate.html

### Phase 5 產出

```text
RAG Scorecard
```

例如：

| Metric | Score |
|---|---:|
| Answer Accuracy | 92 |
| Context Relevancy | 88 |
| Groundedness | 95 |
| Recall@1 | 76 |
| Recall@3 | 91 |
| Recall@5 | 97 |

---

# Phase 6 — 建立自己的 Project Benchmark

例如：

```text
EnergyOps-Bench
```

可以先設計 100 題：

| 題型 | 題數 |
|---|---:|
| Document QA | 20 |
| Fault Diagnosis | 20 |
| Time-series | 20 |
| RAG Retrieval | 20 |
| Safety / Hallucination | 10 |
| Management Summary | 10 |

每個 Test Case 建議至少有：

```json
{
  "id": "energy_001",
  "category": "fault_diagnosis",
  "question": "...",
  "ground_truth": "...",
  "expected_sources": [],
  "difficulty": "medium"
}
```

這會逐漸演變成真正有價值的 Domain Dataset。

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

---

# Phase 10 — AI Evaluation Lab / EvalCore

最終架構：

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

最後不是單純算平均。

而是依 Project Requirement 加權，例如：

```text
EnergyOps:

RAG Accuracy       30%
Groundedness       20%
Domain Accuracy    20%
Latency            10%
Cost               10%
Reliability        10%
```

最後產出：

```text
Recommendation

ADOPT
CONDITIONAL
REJECT
```

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

# 16. 建議長期專案名稱

暫定：

```text
EvalCore
```

或：

```text
AI Evaluation Lab
```

未來可以逐步包含：

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

最終它可以成為一個獨立的 Portfolio Project，也可以作為其他 AI 專案共用的 Evaluation Infrastructure。

---

## 補充（Claude Code 審閱建議，2026-07-27）

以下是套用在 `AI Energy Operations Copilot (MVP_V1)` 時的具體修正建議：

1. **`EnergyOps-Bench` 不用從零寫 100 題**：先重用 `spike/test_questions.json`（29 題，已有真實 retrieval baseline 數字）、`chunking_comparison_report.json`、`retrieval_benchmark_report.json` 當作 Phase 2/6 的第一批測試集，站在既有驗證基礎上，而不是重工。
2. **成本控制**：Phase 2 的 AI Battle 與 LLM-as-a-Judge 都會真的呼叫付費 API，建議每次跑評測前先用專案既有的 `embed-cost-estimate` skill 估算花費。
3. **定位**：此文件是長期參考地圖，實際教學仍照 Phase 1 → 2 → 3 逐步走，不要被 Phase 4-10 的規模嚇到或想跳著做。
