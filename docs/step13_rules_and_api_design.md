# Step 13 Sub-step 13.1 — Rule and API Contract Design (Scheduling / Cost / Green Operations Index)

> Planning document only. No backend/frontend code, schema, or migration has
> been written yet. Scoped strictly to 13.1 per `docs/DEVELOPMENT_WORKFLOW.md`
> Step 13 and `docs/PROJECT_ALIGNMENT_REVIEW.md` §9's 2026-08-05 roadmap
> update. This document resolves every numeric threshold and precedence
> decision that `docs/MVP1_RULES.md` §5–§7 left open, per the user's explicit
> decisions on 2026-08-05 — nothing here is invented without that decision
> trail; every non-obvious number below cites which decision it comes from.

## 1. Overview / Scope

Step 13 補齊 Step 9 當初只交付了 anomaly diagnosis、漏做的三項功能：

1. **Battery Scheduling Suggestion**（`docs/MVP1_RULES.md` §5）
2. **Cost Estimation**（§6）
3. **Green Operations Index**（§7）

三項功能各自獨立實作、獨立 endpoint、獨立 response model，但共用同一套
`analysis_runs` persistence 機制與 idempotency 設計（見第 6 節）。§7 Green
Operations Index 與 §6.3 cost 的 over-contract risk penalty 依賴 5 個尚未
對外實作的 anomaly rule 的判斷條件——這些條件在本 Step 中以 **internal
scoring signal**（非對外 anomaly diagnosis 功能）的形式重用，範圍與限制見
第 2.2 節。

不在本次 Step 13 範圍內：

- 其餘 7 種 anomaly rule 的正式對外 diagnosis 功能（`PROGRESS.md` Known
  Issue 保留，不因為 internal signal 重用了判斷條件就視為「已完成」）
- Step 14 Analysis Report、Step 15 AI Assistant tool 擴充（選配）

---

## 2. Shared Definitions

### 2.1 Price Classification（low / neutral / high）

延伸既有 `backend/app/services/rule_engine.py` 的
`_compute_price_threshold`，該函式目前只定義「high」，本次補上
「low」與「neutral」的完整分類邏輯。分類函式對每個 dataset 各自計算一次
（dataset-relative，不使用絕對電價門檻）。

**Mode 判定順序沿用既有邏輯不變**（`MINIMUM_PRICE_SAMPLES = 5`、
`DISCRETE_TOU_MAX_DISTINCT_VALUES = 3`）：

| Mode | 判定條件 | Low / Neutral / High 定義 |
|---|---|---|
| `insufficient_data` | non-null 樣本數 < 5 | 全部 `neutral`（沿用既有：無法判斷任何 high，同理也無法判斷 low） |
| `no_distinguishable_peak` | distinct 值數 < 2（即只有 1 種價格） | 全部 `neutral` |
| `discrete_tou_max`（2 種價格） | distinct 值數 == 2 | `minimum → low`；`maximum → high`；不會出現 `neutral`（使用者裁示①） |
| `discrete_tou_max`（3 種價格） | distinct 值數 == 3 | `minimum → low`；`middle → neutral`；`maximum → high`（使用者裁示①） |
| `percentile` | distinct 值數 > 3 | 見下方 percentile 規則（使用者裁示②） |

**Percentile 模式的 strict comparison**（使用者裁示②，取代原本的
`>= HIGH_PRICE_PERCENTILE` 單邊判斷）：

```text
low_threshold  = 25th percentile（新增常數 LOW_PRICE_PERCENTILE = 0.25，與既有 HIGH_PRICE_PERCENTILE = 0.75 對稱）
high_threshold = 75th percentile（既有值不變）

price < low_threshold   → low
price > high_threshold  → high
其餘（含 price == low_threshold 或 price == high_threshold） → neutral

若 low_threshold >= high_threshold（極端分布導致兩個 percentile 重疊或反轉）：
    落在該重疊區間的值一律 → neutral，不得優先歸類 low 或 high
```

`discrete_tou_max` 的 2/3 種價格分類**不套用**這組 strict comparison（不
使用 `<`/`>` 對 min/max/middle 做二次判斷，直接用使用者裁示①的
value-to-label mapping）——兩種 mode 是互斥的判定路徑，不會混用。

`PriceClassification` 回傳結構（供 3 個功能共用）：

```python
class PriceThresholdInfo(BaseModel):
    mode: str  # "insufficient_data" | "no_distinguishable_peak" | "discrete_tou_max" | "percentile"
    low_threshold: Optional[float] = None
    high_threshold: Optional[float] = None
    non_null_sample_count: int
    distinct_price_count: int
    reason: Optional[str] = None

def classify_price(value: Optional[float], threshold: PriceThresholdInfo) -> str:
    """Returns "low" | "neutral" | "high". None input -> "neutral" with a
    per-row insufficient-data note (row cannot be evaluated for this signal)."""
```

### 2.2 Internal Scoring Signals（不對外暴露的 anomaly-equivalent 判斷）

依使用者裁示⑥，確認完整清單為 **5 個 internal scoring signal**（本 Step
新增）+ **1 個既有正式 signal**（`BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`，
Step 9 已實作，直接重用其既有邏輯，不重寫）：

| Signal（internal，本 Step 新增） | 對應 `docs/MVP1_RULES.md` | 判斷條件（門檻已在文件中明確定義，無缺口） |
|---|---|---|
| `over_contract_risk` | §4.2 | `grid_import_kw >= 0.90 * contract_capacity_kw`（`critical`: `>= 1.00`） |
| `battery_health_risk` | §4.4 | `battery_temperature >= 40 OR battery_soh < 80 OR battery_health_status in ("warning","critical")`（`warning` 子門檻：溫度 >= 35 或 SOH < 85） |
| `low_soc_risk` | §4.3 | `battery_soc < 20`（`warning`: `< 30`） |
| `green_energy_waste` | §4.7 | `grid_export_kw > 0 AND battery_soc < 90 AND battery_power_kw >= 0` |
| `peak_period_abnormal_charging` | §4.5 | `price_classification == "high" AND battery_power_kw < 0`（重用 2.1 節的 price classification，不是另一組獨立門檻） |
| `battery_should_discharge_but_did_not`（既有,重用） | §4.6 | 直接呼叫既有 `evaluate_battery_should_discharge_but_did_not` 的逐列判斷邏輯 |

**限制（依使用者裁示,原樣保留）**：

- 這 5 個 internal signal **不新增對外 anomaly diagnosis endpoint**，不
  出現在 `GET /datasets/{id}/analysis` 既有 response 裡
- 不宣稱其餘 7 種 anomaly rule 已正式完成；`PROGRESS.md` 的對應 Known
  Issue 維持不動
- 對外欄位一律使用 `penalty_reasons` / `internal_scoring_signals` 命名，
  不使用 `anomaly_type` 或任何暗示「這是正式 anomaly diagnosis 結果」的
  命名

```python
class ScoringSignalFlag(BaseModel):
    signal: str  # "over_contract_risk" | "battery_health_risk" | ... (6 個值之一)
    interval_start: datetime
    interval_end: datetime  # 該 signal 判定為 True 的區間（用於 §5 的時間占比計分）
```

---

## 3. Battery Scheduling Suggestion

### 3.1 Inputs / Outputs

**Inputs**（每一列 `energy_timeseries`）：`timestamp`、`battery_temperature`、
`battery_health_status`、`battery_soc`、`battery_soh`、`electricity_price`、
`pv_actual_kw`、`load_kw`、`grid_import_kw`、`contract_capacity_kw`、
`battery_power_kw`。

**Output**（逐列一個建議，結構比照既有 `AnomalyResult` 風格）：

```python
class ScheduleRecommendation(BaseModel):
    timestamp: Optional[datetime]
    action: str  # "charge" | "discharge" | "idle" | "hold"
    reason: str  # 對應觸發該 action 的規則描述（人類可讀）
    price_classification: str  # "low" | "neutral" | "high"
    warnings: list[str] = []  # 例如 "conflicting_energy_flow_signals"

class ScheduleAnalysisResult(BaseModel):
    rule: str = "battery_scheduling"
    rule_version: str
    price_threshold: PriceThresholdInfo
    input_row_count: int
    evaluated_row_count: int
    recommendations: list[ScheduleRecommendation]
```

### 3.2 Precedence 決策樹（使用者裁示③ + tie-break 裁示,完整定案）

逐列依序判斷,**第一個成立的分支決定 action,不再往下判斷**：

```text
1. battery_temperature >= 40
   → action = "idle"

2. battery_health_status == "critical"
   → action = "idle"

3. battery_soc <= 20
   → if price_classification == "low" AND (pv_actual_kw > load_kw AND battery_soc < 90):
         action = "charge"
     else:
         action = "idle"
   （絕對不進入 discharge 分支）

4. battery_soh < 80
   → if charge 條件成立（見下方 charge 條件定義）:
         action = "charge"
     else:
         action = "hold"
   （絕對不進入 discharge 分支——soh 過低只否決 discharge,不否決 charge）

5. 一般判斷（通過 1–4 後才會執行到這裡）：
   discharge 條件 = price_classification == "high"
                     AND battery_soc > 30
                     AND grid_import_kw >= 0.80 * contract_capacity_kw
   charge 條件     = (price_classification == "low" AND battery_soc < 80)
                     OR (pv_actual_kw > load_kw AND battery_soc < 90)

   → if discharge 條件成立:
         action = "discharge"
         if charge 條件同時也成立（PV surplus 與 high-price grid-dependency 同時出現）:
             warnings.append("conflicting_energy_flow_signals")
     elif charge 條件成立:
         action = "charge"
     else:
         action = "hold"
```

**決策表（各安全條件 × charge/discharge 的最終結果一覽）**：

| 條件組合 | Action | 依據 |
|---|---|---|
| `temp >= 40` | `idle` | 裁示③ 步驟 1，blanket override |
| `health == "critical"` | `idle` | 裁示③ 步驟 2，blanket override |
| `soc <= 20` 且低價可充電 | `charge` | 裁示③ 步驟 3 |
| `soc <= 20` 且無法充電 | `idle` | 裁示③ 步驟 3 |
| `soh < 80` 且 charge 條件成立 | `charge` | 裁示③ 步驟 4（soh 只否決 discharge） |
| `soh < 80` 且 charge 條件不成立 | `hold` | 裁示③ 步驟 4 |
| 通過安全判斷，discharge 與 charge 同時成立 | `discharge` + `conflicting_energy_flow_signals` warning | tie-break 裁示 (a) |
| 通過安全判斷，只有 discharge 成立 | `discharge` | §5.2 |
| 通過安全判斷，只有 charge 成立 | `charge` | §5.1 |
| 通過安全判斷，兩者皆不成立 | `hold` | §5 缺口①的 fallback |

`conflicting_energy_flow_signals` warning **僅供資料品質提示，不改變
`discharge` 的最終 action**，也不在本次新增任何物理一致性 validation
rule（依裁示原樣保留）。

### 3.3 逐列獨立評估

與既有 `evaluate_battery_should_discharge_but_did_not` 一致：每一列獨立
判斷，不依賴前後列狀態（scheduling 建議不是時序決策，是「當下這個時間
點該怎麼做」的建議）。缺少必要欄位的列（例如 `battery_temperature` 為
null）視同該列的安全判斷條件為 False，繼續往下一步驟判斷；若連
charge/discharge 條件所需欄位也缺失，該列 action 直接為 `hold` 並標記
`insufficient_row_data` warning（沿用既有 `_to_optional_float` 對
null 的處理慣例）。

---

## 4. Cost Estimation

### 4.1 Inputs / Outputs

**Inputs**：`site_id`（**新增**，既有 `GET_TIMESERIES_FOR_ANALYSIS_SQL`
目前未 SELECT 這欄，13.2 需要擴充 SQL）、`timestamp`、`grid_import_kw`、
`electricity_price`、`battery_power_kw`、`contract_capacity_kw`。

**Output**（依使用者裁示④，per-site + dataset aggregate 雙層結構）：

```python
class CostInterval(BaseModel):
    site_id: str
    interval_start: datetime
    interval_end: datetime
    duration_hours: float
    energy_kwh: float  # grid_import_kw * duration_hours
    estimated_cost: float  # energy_kwh * electricity_price（用區間起點的 price）
    battery_arbitrage: Optional[float] = None  # 見 4.2 公式，可為正（discharge saving）或負（charge cost）

class CostSiteResult(BaseModel):
    site_id: str
    row_count: int
    interval_count: int  # 實際納入計算的區間數（不含最後一筆、不含被排除的異常區間）
    total_energy_cost: float
    total_arbitrage_saving: float  # 正值為 saving，負值為 charging cost 淨額
    over_contract_penalty_flags: list[ScoringSignalFlag]  # 重用 2.2 節 over_contract_risk signal
    warnings: list[str]
    limitations: list[str]

class CostAnalysisResult(BaseModel):
    rule: str = "cost_estimation"
    rule_version: str
    site_count: int
    per_site: list[CostSiteResult]
    dataset_aggregate: CostSiteResult  # site_id = "__all__"，其餘欄位為跨 site 加總
```

### 4.2 Duration 計算規則（使用者裁示,原樣落地）

```text
energy_kwh      = grid_import_kw（該區間起點列的值） × duration_hours
estimated_cost  = energy_kwh × electricity_price（該區間起點列的值）
duration_hours  = (下一列 timestamp - 本列 timestamp) 的實際小時數

battery arbitrage（§6.2，同樣以區間起點列的值計算，duration 邏輯相同）：
  若 battery_power_kw > 0（discharging）: saving = battery_power_kw × duration_hours × electricity_price
  若 battery_power_kw < 0（charging）:    cost   = abs(battery_power_kw) × duration_hours × electricity_price
```

**逐項規則（依使用者裁示,含明確定義的邊界情況）**：

1. **timestamps 必須依時間排序**——若輸入未排序，函式內部依
   `(site_id, timestamp)` 重新排序後才計算，不假設呼叫端已排序。
2. **最後一筆不計入區間成本**——每個 `site_id` 分組內最後一筆列沒有
   「下一筆」可比較，`duration_hours` 無法計算，該列不產生
   `CostInterval`，並在該 site 的 `limitations` 加入一條說明（例如
   `"last row at {timestamp} excluded from interval cost: no next timestamp"`）。
3. **Duplicate timestamp（duration == 0）**——同一 `site_id` 出現兩筆
   相同 `timestamp`：該區間**不計算**（duration 為 0 會導致
   `energy_kwh` 恆為 0，掩蓋真實用電），在 `warnings` 加入
   `"duplicate_timestamp"` 並列出實際 timestamp，該筆列被跳過但不中止
   整個請求（non-fatal）。
4. **Non-positive interval（duration < 0，即資料未真正遞增，可能是
   重複匯入或 clock skew）**——同 3，該區間不計算，`warnings` 加入
   `"non_positive_interval"`，non-fatal，不回傳 422。
5. **異常大時間缺口（gap）warning**——依使用者指示「若文件仍未定義，
   請在設計文件中提出一個可設定的 contract，不要先硬編數值」：新增
   可設定常數 `MAX_EXPECTED_INTERVAL_HOURS`（13.2 實作時作為
   module-level 常數，非 `docs/MVP1_RULES.md` 規定的業務門檻，只是
   一個資料品質偵測用的技術參數，預設值待 13.2 實際跑過至少一份真實
   dataset 的時間間隔分布後再決定，本文件不先假設具體數字）。任何
   `duration_hours > MAX_EXPECTED_INTERVAL_HOURS` 的區間**仍然照常計算
   成本**（不排除，因為缺口本身不代表數字錯誤，只是需要提醒），但在
   `warnings` 加入 `"large_time_gap"` 並附上該區間的實際 `duration_hours`。

### 4.3 Multi-site 處理（使用者裁示④,方案 b）

- `GET_TIMESERIES_FOR_ANALYSIS_SQL`（`backend/app/datasets_queries.py`）
  需要擴充 `SELECT` 清單加入 `site_id`（13.2 範圍，本文件只記錄需求）
- 依 `site_id` 分組後各自排序、各自計算 duration／cost／limitations
- **相鄰 timestamp 只能在同一個 `site_id` 內比較**——不同 site 之間的
  列即使 timestamp 相鄰也不得配對成一個 `CostInterval`
- `dataset_aggregate`：對所有 site 的 `CostInterval` 直接加總
  （`total_energy_cost`、`total_arbitrage_saving` 為各 site 加總），
  `over_contract_penalty_flags` 為各 site flag 的聯集，`warnings`／
  `limitations` 為各 site 訊息的聯集（保留 site_id 前綴以利追蹤來源）
- `site_count` 欄位直接暴露在 top-level response，前端／Step 14
  report 可以據此判斷是否為多場域 dataset

### 4.4 Over-contract Risk Penalty（§6.3）

不重新定義門檻，直接重用第 2.2 節的 `over_contract_risk` internal
signal（`grid_import_kw >= 0.90 * contract_capacity_kw` /
`critical: >= 1.00`）。`CostSiteResult.over_contract_penalty_flags`
只記錄「哪些區間被標記」，不產生額外金額計算（§6.3 原文本來就只要求
`risk_level` 標記，不要求精確違約金額，MVP v1 不做官方罰則計算）。

---

## 5. Green Operations Index

### 5.1 Inputs / Outputs

**Inputs**：`site_id`、`timestamp`（用於計算 flagged interval 的時間長度）
+ 第 2.2 節六個 signal 各自需要的欄位（`battery_temperature`、
`battery_soh`、`battery_health_status`、`battery_soc`、`grid_export_kw`、
`battery_power_kw`、`electricity_price`、`grid_import_kw`、
`contract_capacity_kw`）+ `battery_is_second_life`（second-life bonus 用）。

**Output**：

```python
class GreenOpsComponentScore(BaseModel):
    component: str  # "pv_utilization" | "battery_operation" | "grid_dependency" | "battery_health"
    max_score: float  # 25 | 20 | 20 | 25
    score: Optional[float]  # None 代表 insufficient_data，不得填 0 或滿分
    status: str  # "computed" | "insufficient_data"
    eligible_duration_hours: Optional[float]
    flagged_duration_hours: Optional[float]
    penalty_reasons: list[str]  # 例如 ["over_contract_risk", "peak_period_abnormal_charging"]

class GreenOpsSiteResult(BaseModel):
    site_id: str
    components: list[GreenOpsComponentScore]  # 固定 4 筆，順序固定
    second_life_bonus: Optional[float]  # 0 / 10 / None（欄位缺失時）
    total_score: Optional[float]  # None 代表任一 base component 為 None
    warnings: list[str]

class GreenOpsAnalysisResult(BaseModel):
    rule: str = "green_operations_index"
    rule_version: str
    site_count: int
    per_site: list[GreenOpsSiteResult]
    dataset_aggregate: GreenOpsSiteResult  # site_id = "__all__"
```

### 5.2 五個子分數計分公式（使用者裁示⑤,完整落地）

**權重定案**：PV Utilization `0–25`／Battery Operation `0–20`／
Grid Dependency `0–20`／Battery Health `0–25`／Second-life Bonus `0 或 10`／
Total `0–100`。

**前四項統一公式**：

```text
penalty_ratio   = flagged_duration_hours / eligible_duration_hours
component_score = component_max_score × (1 - penalty_ratio)
score = clamp(component_score, 0, component_max_score)，四捨五入至小數點後 2 位
```

- `eligible_duration_hours`：該 component 所需欄位皆非 null 的區間時長
  總和（操作化定義，比照既有 `evaluated_row_count` 的「可評估才算」精神
  ——這是本文件依現有慣例做的具體化，不是新業務門檻，若你認為需要另外
  裁示請指出）。
- `flagged_duration_hours`：該 component 對應的 signal（可能不只一個，
  見下方對應表）在 `eligible` 區間內判定為 True 的時間長度，**同一區間
  若被多個 signal 同時命中,只計一次**（interval union，不重複扣分）。
- 最後一筆列沒有 duration（呼應第 4.2 節同一原則），不進入
  `eligible_duration_hours` 或 `flagged_duration_hours` 的分子分母。
- `eligible_duration_hours == 0`（例如整份 dataset 都缺該 component
  必要欄位）：`score = None`、`status = "insufficient_data"`，
  **不得回傳 0 分或滿分**。

**Signal 對應表**（使用者裁示⑤）：

| Component | Max | 對應 signal(s) |
|---|---|---|
| PV Utilization Score | 25 | `green_energy_waste` |
| Battery Operation Score | 20 | `peak_period_abnormal_charging`、`battery_should_discharge_but_did_not`（既有正式 signal，重用） |
| Grid Dependency Score | 20 | `over_contract_risk` |
| Battery Health Score | 25 | `battery_health_risk`、`low_soc_risk` |

**Total score**：

```text
若 4 個 component 皆非 None:
    total_score = sum(4 個 component.score) + (second_life_bonus or 0)
否則:
    total_score = None
    （回傳可計算的 component scores 與 coverage metadata，不包裝成假的 0-100 總分）
```

**Second-life Bonus（§7.7，布林，非時間加權)**：

```text
若 battery_is_second_life / battery_health_status / battery_temperature 任一必要欄位整份 dataset 皆缺失:
    second_life_bonus = None（unavailable，不猜測）
否則若 battery_is_second_life == true AND battery_health_status in ("normal","warning") AND battery_temperature < 40:
    second_life_bonus = 10
否則:
    second_life_bonus = 0
```

### 5.3 Multi-site 聚合

- 每個 `site_id` 先各自算出 4 個 component + bonus + total（結構同
  `GreenOpsSiteResult`）
- `dataset_aggregate` 的每個 component：
  - 只對「該 component 非 None」的 site 取值，依各自
    `eligible_duration_hours` 做加權平均：
    `aggregate_score = Σ(site.score × site.eligible_hours) / Σ(site.eligible_hours)`
  - 若所有 site 對該 component 皆為 None → aggregate 該 component 也是
    `None`
- `dataset_aggregate.total_score`：比照 5.2 節同一條規則（4 個 aggregate
  component 皆非 None 才加總，否則 None）

---

## 6. API Contract

三個新 endpoint，**不修改**既有 `GET`/`POST /datasets/{id}/analysis`
的 request/response 形狀。

### 6.1 `GET /datasets/{dataset_id}/schedule`
### 6.2 `POST /datasets/{dataset_id}/schedule`

```text
GET  → 200 ScheduleRunResponse | 404（dataset 不存在，或存在但尚無 run）
POST → 200 ScheduleRunResponse | 404（dataset 不存在）| 422（超過 MAX_ANALYSIS_ROWS，沿用既有常數）
```

### 6.3 `GET /datasets/{dataset_id}/cost`
### 6.4 `POST /datasets/{dataset_id}/cost`

```text
GET  → 200 CostRunResponse | 404
POST → 200 CostRunResponse | 404 | 422（沿用 MAX_ANALYSIS_ROWS）
```

### 6.5 `GET /datasets/{dataset_id}/green-operations-index`
### 6.6 `POST /datasets/{dataset_id}/green-operations-index`

```text
GET  → 200 GreenOpsRunResponse | 404
POST → 200 GreenOpsRunResponse | 404 | 422（沿用 MAX_ANALYSIS_ROWS）
```

**Response wrapper（三者共用同一個外殼，比照既有 `AnalysisRunResponse`）**：

```python
class ScheduleRunResponse(BaseModel):
    analysis_run_id: int
    dataset_id: int
    analysis_type: str  # "battery_scheduling"
    rule_version: str
    created_at: datetime
    result: ScheduleAnalysisResult

class CostRunResponse(BaseModel):
    analysis_run_id: int
    dataset_id: int
    analysis_type: str  # "cost_estimation"
    rule_version: str
    created_at: datetime
    result: CostAnalysisResult

class GreenOpsRunResponse(BaseModel):
    analysis_run_id: int
    dataset_id: int
    analysis_type: str  # "green_operations_index"
    rule_version: str
    created_at: datetime
    result: GreenOpsAnalysisResult
```

三個 endpoint 的 handler 邏輯與既有 `get_dataset_analysis`/
`post_dataset_analysis` 完全同構（同一個 `_analysis_run_to_response`
模式，只是各自對應不同的 Pydantic model 與 `analysis_type` 常數），
`get_analysis_run`/`insert_analysis_run`（`datasets_queries.py`）
簽名不需要任何修改，直接重用。

---

## 7. `analysis_type` / `rule_version` 命名

依 `docs/DATA_SCHEMA.md` §6 原本就預留的 `analysis_type` 命名慣例：

| 功能 | `analysis_type` | `rule_version`（初版） |
|---|---|---|
| Battery Scheduling | `battery_scheduling` | `battery_scheduling_v1` |
| Cost Estimation | `cost_estimation` | `cost_estimation_v1` |
| Green Operations Index | `green_operations_index` | `green_operations_index_v1` |

沿用既有 `UNIQUE(dataset_id, analysis_type, rule_version)` +
`ON CONFLICT DO NOTHING` idempotency：同一 dataset 重複 `POST` 回傳既有
結果；`rule_version` 变更才产生新 row。與既有
`battery_should_discharge_v1` 的命名風格一致。

---

## 8. Warnings / Limitations / Coverage Metadata 格式

三個功能統一使用 `list[str]` 的 `warnings` 與 `limitations` 欄位（已在
第 3–5 節各自的 response model 中定義），字串內容採用
`snake_case_reason` 前綴 + 人類可讀說明的形式，例如：

```text
"conflicting_energy_flow_signals: pv_actual_kw > load_kw and grid_import_kw high at the same timestamp"
"duplicate_timestamp: site_id=site_a, timestamp=2026-01-01T00:00:00Z appears more than once"
"non_positive_interval: site_id=site_a, timestamp=2026-01-01T01:00:00Z duration_hours=-0.5"
"large_time_gap: site_id=site_a, interval 2026-01-01T00:00:00Z~2026-01-02T06:00:00Z duration_hours=30.0"
"last_row_excluded: site_id=site_a, timestamp=2026-01-05T23:00:00Z has no next timestamp"
"insufficient_row_data: timestamp=2026-01-01T00:00:00Z missing battery_temperature"
```

`coverage` 概念體現在 `eligible_duration_hours`（Green Ops）與
`interval_count`（Cost）等欄位裡，不另外設計一個獨立的 `coverage`
物件——沿用三個 response model 各自已有的欄位即可表達「這份結果实际
覆蓋了多少可信資料」，避免額外抽象層。

---

## 9. 後續 Sub-steps 與各自驗收案例

| Sub-step | 內容 | 驗收案例（草案，13.2/13.3 實作時展開為正式測試） |
|---|---|---|
| 13.2 | Backend rules：`battery_scheduling.py`／`cost_estimation.py`／`green_operations_index.py` + `PriceThresholdInfo`／`ScoringSignalFlag` 共用 helper | 每個 precedence 分支至少一個測試（含 tie-break 案例）；5 個 internal signal 各自的判斷條件測試；price classification 的 discrete 2-tier/3-tier/percentile/重疊 edge case |
| 13.3 | Persistence + API：3 個新 endpoint,擴充 `GET_TIMESERIES_FOR_ANALYSIS_SQL` 加入 `site_id` | 404／422／idempotency（重複 POST 回傳同一 run）；multi-site 分組正確性 |
| 13.4 | Tests：pure-function + API-level（比照 `test_rule_engine.py`／`test_analysis_endpoint.py` 慣例） | duplicate timestamp／non-positive interval／large gap／insufficient_data 各自至少一個測試 |
| 13.5 | Dashboard：Cost comparison 圖表 | 對一個真實 dataset 顯示 per-site 或 aggregate 成本趨勢 |
| 13.6 | Dashboard：Green Operations Index 圖表 | 顯示 4 個 component + total，null component 時明確顯示「資料不足」而非 0 分 |
| 13.7 | Integration verification | 端到端對真實 dataset 跑三個新 endpoint，確認 `analysis_runs` 正確寫入、無 regression |
