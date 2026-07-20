# SAMPLE_DATA_PLAN.md

## 1. Purpose

本文件定義 AI Energy Operations Copilot MVP1 所需的 synthetic demo datasets。

MVP1 的 sample data 目的不是模擬完整真實電力系統，而是提供一組可重現、可展示、可測試的資料，讓 Dashboard、rule-based analysis、RAG response、case similarity 與 report generation 可以順利展示。

> Important: Demo data must be synthetic. Do not claim it is real Taipower operational data.

---

## 2. Data Source Policy

MVP1 sample data 允許參考以下來源的概念：

- Simulated CSV data
- Taiwan Power research report concepts
- Public energy dataset structure
- Taiwan-relevant energy operation scenarios

但資料本身必須標示為 synthetic data，不可宣稱為真實案場資料或真實台電營運紀錄。

---

## 3. Required Dataset Types

MVP1 至少需要下列 7 種 demo dataset，每一種 dataset 都應該能觸發或支撐一個核心展示情境。

### 3.1 Normal Operation Day

用途：展示正常運轉狀態。

特徵：

- PV forecast 與 PV actual 接近
- Load 未接近 contract capacity
- Battery SOC 維持合理區間
- Battery temperature 正常
- Grid import / export 合理

預期結果：

- 無重大 anomaly
- Dashboard 顯示 healthy operation
- Copilot 回答目前系統穩定

---

### 3.2 PV Forecast Deviation Day

用途：展示 PV 預測偏差診斷。

特徵：

- `pv_forecast_kw` 明顯高於或低於 `pv_actual_kw`
- 偏差率超過 MVP1_RULES.md 定義的 threshold
- 可搭配 cloudy / rainy weather condition

預期結果：

- 觸發 `PV_FORECAST_DEVIATION`
- Copilot 說明可能與天氣變化、雲量或預測誤差有關

---

### 3.3 Over-Contract Risk Day

用途：展示契約容量風險。

特徵：

- `grid_import_kw` 接近或超過 `contract_capacity_kw`
- 尖峰時段負載偏高
- Battery SOC 若足夠，理論上應該輔助放電

預期結果：

- 觸發 `OVER_CONTRACT_RISK`
- Dashboard 顯示 contract capacity warning
- Copilot 建議降低負載或使用 battery discharge 支援削峰

---

### 3.4 Battery Should-Discharge-But-Did-Not Day

用途：展示 EMS 控制異常或排程錯誤。

特徵：

- 尖峰或高電價時段
- Load 接近 contract capacity
- Battery SOC 足夠
- 但 `battery_power_kw` 沒有放電，或反而維持 0

預期結果：

- 觸發 `BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`
- Copilot 說明可能是 EMS mode、equipment status、schedule logic 或 communication issue

---

### 3.5 Peak-Period Abnormal Charging Day

用途：展示尖峰時段異常充電。

特徵：

- 高電價時段
- `battery_power_kw` 為負值，代表 battery charging
- Grid import 同時上升

預期結果：

- 觸發 `PEAK_PERIOD_ABNORMAL_CHARGING`
- Copilot 說明這可能增加電費或提高超約風險

---

### 3.6 Green Energy Waste Day

用途：展示綠電浪費與自發自用不足。

特徵：

- `pv_actual_kw` 高
- `grid_export_kw` 高
- Battery SOC 尚未滿
- Battery 沒有有效充電

預期結果：

- 觸發 `GREEN_ENERGY_WASTE`
- Dashboard 顯示 potential wasted renewable energy
- Copilot 建議優先提高 self-consumption 或調整 battery charging schedule

---

### 3.7 Battery Health Risk Day

用途：展示 Battery Health Risk 與 Second-life battery analysis。

特徵：

- `battery_temperature` 偏高
- `battery_soh` 偏低，或 `battery_equivalent_cycle` 偏高
- `battery_is_second_life` 為 true
- 可搭配 high cycling day

預期結果：

- 觸發 `BATTERY_HEALTH_RISK`
- Copilot 說明高溫與頻繁循環可能增加 battery aging risk
- 若為 second-life battery，回答應更保守，建議降低 cycling frequency

---

## 4. CSV Time Resolution

MVP1 預設使用 hourly data。

建議格式：

```text
timestamp interval: 1 hour
rows per day: 24
minimum demo days: 7
minimum rows: 168
```

後續版本可以擴充到 15-minute interval，但 MVP1 不需要。

---

## 5. Required Demo Sites

MVP1 建議至少建立 3 個 demo site：

```text
site_demo_pv_001
site_demo_container_001
site_demo_second_life_battery_001
```

### 5.1 site_demo_pv_001

用途：展示 PV forecast、PV actual、load、grid import/export。

### 5.2 site_demo_container_001

用途：展示 smart container / low-carbon container energy operation。

### 5.3 site_demo_second_life_battery_001

用途：展示 second-life battery health risk、SOH、equivalent cycle、temperature risk。

---

## 6. Required CSV Columns

Sample CSV 應符合 `docs/DATA_SCHEMA.md` 的 Energy Time-Series CSV schema。

建議欄位如下：

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

---

## 7. Value Conventions

### 7.1 battery_power_kw

```text
positive value = battery discharging
negative value = battery charging
zero = idle
```

### 7.2 battery_health_status

Allowed values:

```text
normal
warning
critical
unknown
```

### 7.3 battery_is_second_life

Allowed values:

```text
true
false
```

### 7.4 ems_mode

Canonical allowed values：

```text
auto
manual
schedule
tou_arbitrage
peak_shaving
self_consumption
idle
fallback
error
unknown
```

### 7.5 equipment_status

Canonical allowed values：

```text
normal
warning
fault
error
offline
maintenance
unknown
```

### 7.6 weather_condition

Recommended values:

```text
sunny
cloudy
rainy
overcast
storm
unknown
```

---

## 8. Demo Data Design Requirements

每一組 sample data 應符合以下要求：

1. 可被 Dashboard 正確顯示。
2. 可觸發 MVP1_RULES.md 中至少一種 rule。
3. 可讓 Copilot 用 Internal Knowledge Only 模式解釋。
4. 不需要精準反映真實電力系統，但數值應維持合理範圍。
5. 不應使用真實未公開案場資料。
6. 不應宣稱 synthetic data 是台電真實營運資料。

---

## 9. Suggested File Names

建議將 sample data 放在：

```text
data/sample/
```

建議檔名：

```text
normal_operation_day.csv
pv_forecast_deviation_day.csv
over_contract_risk_day.csv
battery_should_discharge_but_did_not_day.csv
peak_period_abnormal_charging_day.csv
green_energy_waste_day.csv
battery_health_risk_day.csv
combined_demo_timeseries.csv
```

其中 `combined_demo_timeseries.csv` 可作為 MVP1 預設載入資料。

---

## 10. MVP1 Acceptance Criteria

完成 sample data 後，至少要能驗證：

- Dashboard 可以讀取 CSV 並顯示 PV、load、battery、grid metrics。
- Anomaly engine 可以偵測 PV forecast deviation。
- Anomaly engine 可以偵測 over-contract risk。
- Anomaly engine 可以偵測 battery should-discharge-but-did-not。
- Anomaly engine 可以偵測 peak-period abnormal charging。
- Anomaly engine 可以偵測 green energy waste。
- Anomaly engine 可以偵測 battery health risk。
- Copilot 可以根據 dataset 與 internal docs 回答原因、風險與建議。

---

## 11. Non-Goals

MVP1 sample data 不需要做到以下項目：

- Real-time streaming data
- Real Taipower confidential data
- High-resolution SCADA data
- Full EMS control simulation
- Optimization algorithm training data
- Real weather API integration
- Real tariff billing engine

---

## 12. Notes for Claude Code

When generating sample data:

1. Create data in small steps.
2. Explain assumptions before generating CSV files.
3. Keep values realistic enough for demo use.
4. Ensure each anomaly case is easy to inspect manually.
5. Do not over-engineer the generator in MVP1.
6. Prefer a simple Python script only if needed.
7. Update `PROGRESS.md` after completing sample data generation.
