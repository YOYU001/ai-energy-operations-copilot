# MVP1_RULES.md

## 1. Purpose

本文件定義 **AI Energy Operations Copilot MVP v1** 的 rule-based logic。

MVP v1 不實作最佳化演算法、不做即時 EMS 控制、不宣稱能取代正式調度系統。本版本只提供：

- anomaly diagnosis
- battery scheduling suggestion
- cost estimation
- Green Operations Index
- battery health risk assessment
- second-life battery bonus

所有規則都應該以可解釋、可追蹤、可展示為優先。

---

## 2. Core Principles

### 2.1 Internal Knowledge Only

系統回答與判斷必須優先來自：

- uploaded research documents
- approved internal docs
- imported CSV data
- predefined MVP rules

MVP v1 不使用 live web search 作為回答依據。

### 2.2 Rule-based First

MVP v1 使用 rule-based rules，不使用 machine learning optimization、reinforcement learning 或 real-time control。

### 2.3 Human-in-the-loop

所有排程結果都只能是 suggestion，不可以直接控制設備。

系統回答必須避免使用：

- 已自動執行
- 已控制 EMS
- 已下達調度命令

應使用：

- suggest
- recommend
- flag
- explain
- estimate

---

## 3. Required Input Columns

MVP v1 的主要 CSV 欄位應包含：

```csv
timestamp
site_id
pv_forecast_kw
pv_actual_kw
load_kw
load_forecast_kw
battery_soc
battery_power_kw
battery_temperature
electricity_price
contract_capacity_kw
grid_import_kw
grid_export_kw
weather_condition
ghi
temperature
humidity
ems_mode
equipment_status
battery_soh
battery_cycle_count
battery_equivalent_cycle
battery_health_status
battery_is_second_life
battery_rated_capacity_kwh
battery_available_capacity_kwh
```

### 3.1 Field Conventions

- `battery_power_kw > 0` means battery is discharging.
- `battery_power_kw < 0` means battery is charging.
- `battery_power_kw = 0` means battery is idle.
- `battery_soc` uses percentage, range 0–100.
- `battery_soh` uses percentage, range 0–100.
- `battery_is_second_life` should be boolean: `true` or `false`.
- `battery_health_status` should use fixed values: `normal`, `warning`, `critical`, `unknown`.
- `ems_mode` must use: `auto`, `manual`, `schedule`, `tou_arbitrage`, `peak_shaving`, `self_consumption`, `idle`, `fallback`, `error`, `unknown`.
- `equipment_status` must use: `normal`, `warning`, `fault`, `error`, `offline`, `maintenance`, `unknown`.

---

## 4. Anomaly Diagnosis Rules

### 4.1 PV Forecast Deviation

Flag `PV_FORECAST_DEVIATION` if:

```text
abs(pv_actual_kw - pv_forecast_kw) / max(pv_forecast_kw, 1) >= 0.20
```

Severity:

- `warning`: deviation >= 20%
- `critical`: deviation >= 40%

Explanation should mention possible causes:

- cloud change
- weather forecast error
- sensor abnormality
- PV output instability

---

### 4.2 Over Contract Risk

Flag `OVER_CONTRACT_RISK` if:

```text
grid_import_kw >= 0.90 * contract_capacity_kw
```

Severity:

- `warning`: grid_import_kw >= 90% of contract_capacity_kw
- `critical`: grid_import_kw >= 100% of contract_capacity_kw

Suggested action:

- reduce flexible load
- discharge battery if SOC is sufficient
- avoid charging during high-load periods

---

### 4.3 Battery Low SOC Risk

Flag `LOW_SOC_RISK` if:

```text
battery_soc < 20
```

Severity:

- `warning`: battery_soc < 30
- `critical`: battery_soc < 20

Suggested action:

- avoid unnecessary discharge
- reserve battery for peak or emergency period
- charge during low-price or PV surplus period

---

### 4.4 Battery Health Risk

Flag `BATTERY_HEALTH_RISK` if any condition is true:

```text
battery_temperature >= 40
battery_soh < 80
battery_health_status == "warning"
battery_health_status == "critical"
```

Severity:

- `warning`: battery_temperature >= 35 or battery_soh < 85
- `critical`: battery_temperature >= 40 or battery_soh < 80

Suggested action:

- reduce charge/discharge frequency
- avoid high C-rate operation
- avoid aggressive cycling
- prioritize safety over cost savings

Second-life battery note:

If `battery_is_second_life == true`, the assistant should explain that second-life batteries may require more conservative operation due to cell inconsistency, degradation, and thermal aging risk.

---

### 4.5 Peak Period Abnormal Charging

Flag `PEAK_PERIOD_ABNORMAL_CHARGING` if:

```text
electricity_price is high
AND battery_power_kw < 0
```

Suggested action:

- avoid charging during high-price period
- shift charging to low-price or PV surplus period

---

### 4.6 Battery Should Discharge But Did Not

Flag `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT` if all conditions are true:

```text
electricity_price is high
grid_import_kw >= 0.90 * contract_capacity_kw
battery_soc > 30
battery_power_kw <= 0
```

Suggested action:

- recommend battery discharge
- check EMS mode
- check equipment status
- check whether battery protection mode is active

---

### 4.7 Green Energy Waste

Flag `GREEN_ENERGY_WASTE` if:

```text
grid_export_kw > 0
AND battery_soc < 90
AND battery_power_kw >= 0
```

Explanation:

PV energy may be exported or curtailed while the battery still has available capacity.

Suggested action:

- charge battery during PV surplus period
- increase self-consumption
- check EMS charging strategy

---

### 4.8 Equipment or EMS Abnormal Status

Flag `EMS_OR_EQUIPMENT_STATUS_WARNING` if:

```text
ems_mode in ["manual", "fallback", "error", "unknown"]
OR equipment_status in ["warning", "fault", "error", "offline", "maintenance", "unknown"]
```

Suggested action:

- check EMS mode
- check sensor status
- check inverter and battery communication
- confirm whether manual override is active

---

## 5. Battery Scheduling Suggestion Rules

### 5.1 Charge Recommendation

Recommend charging if any condition is true:

```text
electricity_price is low
AND battery_soc < 80
```

or

```text
pv_actual_kw > load_kw
AND battery_soc < 90
```

Do not recommend charging if:

```text
battery_temperature >= 40
OR battery_health_status == "critical"
```

---

### 5.2 Discharge Recommendation

Recommend discharging if all conditions are true:

```text
electricity_price is high
battery_soc > 30
grid_import_kw >= 0.80 * contract_capacity_kw
```

Do not recommend aggressive discharge if:

```text
battery_temperature >= 40
OR battery_soh < 80
OR battery_health_status == "critical"
```

---

### 5.3 Idle Recommendation

Recommend idle if:

```text
battery_soc <= 20
```

or

```text
battery_temperature >= 40
```

or

```text
battery_health_status == "critical"
```

Explanation should prioritize safety and battery lifetime.

---

## 6. Cost Estimation Rules

MVP v1 cost estimation should be simple and explainable.

### 6.1 Energy Cost

```text
estimated_cost = grid_import_kw * electricity_price
```

### 6.2 Battery Arbitrage Benefit

If battery discharges during high-price period:

```text
estimated_saving = battery_power_kw * electricity_price
```

If battery charges during low-price period, store the cost as:

```text
charging_cost = abs(battery_power_kw) * electricity_price
```

### 6.3 Over-contract Risk Penalty

MVP v1 does not need to calculate official penalty exactly.

Instead, mark over-contract risk as:

```text
risk_level = warning or critical
```

The assistant may explain that actual penalty calculation depends on contract terms and official tariff rules.

---

## 7. Green Operations Index

Green Operations Index is a 0–100 score for dashboard display only.

### 7.1 Suggested Components

```text
Green Operations Index =
  PV Utilization Score
+ Battery Operation Score
+ Grid Dependency Score
+ Battery Health Score
+ Second-life Battery Bonus
```

### 7.2 Component Weights

```text
PV Utilization Score: 25 points
Battery Operation Score: 25 points
Grid Dependency Score: 20 points
Battery Health Score: 20 points
Second-life Battery Bonus: 10 points
Total: 100 points
```

### 7.3 PV Utilization Score

Higher score if PV generation is consumed or stored instead of wasted.

Penalty if `GREEN_ENERGY_WASTE` is flagged.

### 7.4 Battery Operation Score

Higher score if battery charges during low-price or PV surplus periods and discharges during high-price or high-load periods.

Penalty if:

- `PEAK_PERIOD_ABNORMAL_CHARGING`
- `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`

### 7.5 Grid Dependency Score

Higher score if grid import is low relative to load.

Penalty if:

- `OVER_CONTRACT_RISK`
- high grid import during peak period

### 7.6 Battery Health Score

Higher score if:

- battery temperature is within safe range
- battery SOH is acceptable
- battery health status is normal

Penalty if:

- `BATTERY_HEALTH_RISK`
- `LOW_SOC_RISK`

### 7.7 Second-life Battery Bonus

Add bonus if:

```text
battery_is_second_life == true
AND battery_health_status in ["normal", "warning"]
AND battery_temperature < 40
```

Do not add bonus if:

```text
battery_health_status == "critical"
OR battery_temperature >= 40
```

Explanation:

Second-life battery bonus represents circular economy value, but only when the system operates within safe and reasonable conditions.

---

## 8. Assistant Response Rules

> Updated by Project Alignment Review (see `docs/DECISIONS.md` ADR-006, `docs/PROJECT_ALIGNMENT_REVIEW.md`). This section is the implementation source of truth for the AI Assistant's answer structure; `docs/MVP_V1_SPEC.md` section 4.11 must stay consistent with it.

When explaining diagnosis results, similar-case matches, or document-based evidence, the assistant must use this seven-part structure:

```text
Confirmed facts / Finding:
Evidence:
Possible causes:
General engineering background:
Suggested actions / Next checks:
Confidence:
Citations:
```

Rules for each field:

- **Confirmed facts / Finding** and **Evidence**: may only be built from structured data, Rule Engine output, retrieved documents, or case records — never from the LLM's own general knowledge.
- **Possible causes**: must be clearly marked as hypotheses, not established facts. Each possible cause should note what evidence supports or is missing for it.
- **General engineering background**: general engineering knowledge (e.g. BMS protection logic, C-rate, SOC limits, inverter constraints, EMS scheduling mechanics) the LLM adds to help explain concepts, suggest possible directions, or propose next checks. It must never be presented as a confirmed cause for this specific case, and must be kept visually/textually separate from Confirmed facts and Possible causes — not blended into the same sentence.
- **Suggested actions / Next checks**: concrete next steps for the EMS engineer; the assistant recommends, it does not execute (see section 2.3 Human-in-the-loop).
- **Confidence**: `high` / `medium` / `low`. If evidence is close to nonexistent, the assistant must say "insufficient data" instead of forcing a low-confidence guess. Concrete thresholds for what counts as high/medium/low, and for how similar a past case must be to count as supporting evidence, are not yet defined here — they are determined empirically by the Step 6 RAG Feasibility Spike's retrieval results (see `docs/RAG_SPIKE_PLAN.md`), not assumed in advance.
- **Citations**: every citation must be typed as either an internal source (document name/page, dataset, or case ID — an actual reference) or general background knowledge (explicitly labeled as such). A citation must never disguise general knowledge as an internal source. Similar-case citations must additionally state the similarity level and which conditions match vs. differ; a 60–70%-similar case may be referenced but must be labeled as reference-only, not proof.

Example:

```text
Confirmed facts / Finding: Battery health risk detected.
Evidence: battery_temperature is 42°C and battery_is_second_life is true (source: energy_timeseries, dataset_id=12, row timestamp 2026-07-10 14:00).
Possible causes: high cycling frequency (supporting evidence: battery_cycle_count trend over past 7 days); thermal accumulation (supporting evidence: temperature trend; missing evidence: no ambient temperature reading available for this period).
General engineering background: second-life batteries typically require more conservative operation due to cell inconsistency, degradation, and thermal aging risk (general knowledge, not specific to this case).
Suggested actions / Next checks: reduce cycling frequency, avoid aggressive discharge, inspect thermal management system.
Confidence: medium.
Citations: [internal] energy_timeseries dataset_id=12; [internal] Case #045 (72% similar — matches: second-life battery, high temperature; differs: different site_id) — reference only; [general knowledge] second-life battery conservative-operation guidance.
```

---

## 9. MVP v1 Limitations

The assistant must clearly avoid overclaiming.

MVP v1 does not provide:

- real EMS control
- real-time dispatch command
- official tariff settlement
- safety certification
- battery warranty judgment
- production-grade optimization
- self-trained forecasting model

MVP v1 provides:

- explainable rule-based analysis
- portfolio demo dashboard
- internal document Q&A
- CSV-based energy operation insights
- scheduling suggestions for human review

---

## 10. Implementation Notes for Claude Code

When implementing these rules:

- keep thresholds configurable
- avoid hardcoding business logic inside UI components
- place rule logic in backend service layer
- return explanation fields with every anomaly
- keep output JSON easy for frontend cards and charts
- write tests for each anomaly rule

Suggested backend module name:

```text
backend/app/services/rule_engine.py
```

Suggested API endpoint:

```text
POST /api/analyze/site-day
```

Suggested response structure:

```json
{
  "site_id": "site_demo_001",
  "date": "2026-01-01",
  "anomalies": [],
  "recommendations": [],
  "cost_summary": {},
  "green_operations_index": 0
}
```
