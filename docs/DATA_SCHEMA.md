# Data Schema

## 1. 資料層設計

MVP v1 資料分成三大類：

1. Knowledge Base  
   PDF / TXT / MD 文件、研究報告、SOP、EMS 說明

2. Energy Time-Series Data  
   太陽光電、負載、儲能、電價、天氣、EMS 狀態等 CSV 資料

3. Case Library  
   歷史異常案件、症狀、原因、處理方式、結果

主要資料庫使用 PostgreSQL。  
向量搜尋優先使用 pgvector。  
若 pgvector 開發卡住，Chroma 可作為 fallback。

---

## 2. Energy Time-Series CSV Columns

MVP v1 建議 CSV 欄位如下：

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

## 3. Energy Time-Series 欄位說明

### timestamp

資料時間點。  
格式建議使用 ISO datetime。

Example:

```text
2026-07-09 13:00:00
```

### site_id

場域代號或案場 ID。

### pv_forecast_kw

太陽光電預測發電量，單位 kW。

### pv_actual_kw

太陽光電實際發電量，單位 kW。

### load_kw

實際負載，單位 kW。

### load_forecast_kw

預測負載，單位 kW。

### battery_soc

Battery State of Charge，單位百分比。

Example:

```text
65.5
```

### battery_power_kw

電池充放電功率，單位 kW。

建議定義：
- positive value = discharge
- negative value = charge
- zero = idle

### battery_temperature

電池溫度。

### electricity_price

該時間點電價。  
MVP v1 可先用簡化 TOU price。

### contract_capacity_kw

契約容量或用電容量門檻。

### grid_import_kw

從電網取電功率。

### grid_export_kw

送回電網或未被自用的功率。

### weather_condition

天氣狀態，例如：

```text
sunny
cloudy
rainy
unknown
```

### ghi

Global Horizontal Irradiance。

### temperature

環境溫度。

### humidity

環境濕度。

### ems_mode

EMS 操作模式。Canonical allowed values：

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

### equipment_status

設備狀態。Canonical allowed values：

```text
normal
warning
fault
error
offline
maintenance
unknown
```

### battery_soh

Battery State of Health，單位百分比。

MVP v1 可用於判斷 Battery Health Risk。

Example:

```text
82.5
```

### battery_cycle_count

電池累積循環次數。

MVP v1 可用於輔助判斷電池使用程度與 aging risk。

### battery_equivalent_cycle

電池等效循環次數。

MVP v1 可用於支撐 second-life battery 與容量衰退分析。

### battery_health_status

電池健康狀態。

建議固定值：

```text
normal
warning
critical
unknown
```

### battery_is_second_life

是否為二次利用電池。

建議使用 boolean：

```text
true
false
```

### battery_rated_capacity_kwh

電池額定容量，單位 kWh。

### battery_available_capacity_kwh

電池目前可用容量，單位 kWh。

MVP v1 可用於估算容量衰退與 second-life battery bonus。

---

## 4. Case Record Columns

Case Record 可以用 CSV 或 JSON 匯入。

建議欄位：

```csv
case_id
site_id
event_time
event_type
symptoms
root_cause
operator_action
resolution_result
severity
tags
related_dataset_id
related_time_range
```

## 5. Case Record 欄位說明

### case_id

案件唯一識別碼。**Required and unique**（`TEXT NOT NULL UNIQUE`，Step 11 Sub-step 2B 新增）：穩定的業務識別碼，query layer 的 upsert 以此欄位做 `ON CONFLICT` 判斷，因此不可為 null、不可重複。

### site_id

案件所屬場域。

### event_time

案件發生時間。

### event_type

異常類型。

建議值：

```text
PV_FORECAST_DEVIATION
ABNORMAL_LOAD_INCREASE
OVER_CONTRACT_RISK
BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT
PEAK_PERIOD_ABNORMAL_CHARGING
GREEN_ENERGY_WASTE
LOW_SOC_RISK
BATTERY_HEALTH_RISK
OTHER
```

### symptoms

現場觀察到的症狀。

### root_cause

已知或推測原因。

### operator_action

前人或操作人員採取的處置方式。

### resolution_result

處置後結果。

### severity

嚴重程度。

建議值：

```text
low
medium
high
critical
```

### tags

關鍵字。  
可用 comma-separated string。

Example:

```text
PV,cloudy,SOC,peak_shaving
```

### related_dataset_id

對應的 dataset ID。

### related_time_range

案件對應的資料時間區間。

Example:

```text
2026-07-09 12:00:00 ~ 2026-07-09 18:00:00
```

---

## 6. PostgreSQL MVP Tables

### documents

用途：儲存文件 metadata。

Fields:

```text
id
title
file_name
file_type
source_type
uploaded_at
status
```

### document_chunks

用途：儲存文件切片與 embedding。

Fields:

```text
id
document_id
chunk_index
content
page_number
embedding
```

備註：
- `embedding` 優先使用 pgvector。
- 若改用 Chroma，需保留 chunk ID 對應關係。

### datasets

用途：儲存 CSV dataset metadata。

Fields:

```text
id
name
file_name
description
row_count
start_time
end_time
created_at
```

### energy_timeseries

用途：儲存能源時間序列資料。

Fields:

```text
id
dataset_id
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

### case_records

用途：儲存歷史案件與相似案件搜尋資料。

Fields:

```text
id
case_id
site_id
event_time
event_type
symptoms
root_cause
operator_action
resolution_result
severity
tags
related_dataset_id
related_time_range
embedding
embedding_provider
embedding_model
embedding_dimensions
embedding_model_version
embedding_content_hash
embedded_at
created_at
updated_at
```

備註：`embedding_provider`/`embedding_model`/`embedding_dimensions`/`embedding_model_version`/`embedded_at`（Step 11 新增）與 `document_chunks` 的 embedding provenance 欄位設計一致（見 ADR-004：provider 不寫死、記錄 model/version，保留未來重新 embedding 的能力）。`embedding_content_hash` 同樣沿用 `document_chunks.embedding_content_hash` 的欄位命名與計算方式（`app/services/hashing.py` 的 `compute_embedding_content_hash`），讓 `scripts/seed_case_records.py` 能判斷案件搜尋文字是否真的變更，未變更且已有 embedding 時跳過重新呼叫 embedding API。

`case_id` 為 `TEXT NOT NULL UNIQUE`。由於本專案不使用 Alembic，`database/schema.sql` 在 `CREATE TABLE IF NOT EXISTS case_records` 之後另外附了一段可重複執行的 `DO $$ ... $$` 升級區塊：對既有（Step 11 之前建立、`case_id` 當時仍可為 NULL 且無 UNIQUE）的資料庫，會先用 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 補齊本節列出的所有欄位，再檢查現有資料是否已有 NULL 或重複的 `case_id`；只要沒有違規資料就會補上 `NOT NULL` 與 `case_records_case_id_key` UNIQUE constraint，兩者皆用 `IF NOT EXISTS`／`pg_constraint` 檢查過，重複套用 schema.sql 是安全的。若既有資料真的有 NULL 或重複的 `case_id`，這段升級會直接 `RAISE EXCEPTION` 並中止，不會自動刪除或竄改資料，需要先手動修正資料再重新套用。

### analysis_runs

用途：儲存 rule-based analysis 與 AI analysis 結果。

Fields:

```text
id
dataset_id
analysis_type
result_json
created_at
```

analysis_type examples:

```text
anomaly_diagnosis
battery_schedule
cost_estimation
green_operations_index
case_similarity
report_generation
```

### chat_messages

用途：儲存聊天紀錄。

Fields:

```text
id
session_id
role
content
created_at
```

---

## 7. 資料驗證規則

CSV ingestion 時需檢查：

1. `timestamp` 是否存在
2. `site_id` 是否存在
3. 至少需包含 PV、Load、Battery、Price 中的基本欄位
4. 數值欄位需能轉成 numeric
5. 時間欄位需能轉成 datetime
6. 缺失欄位可允許，但需回報 warning
7. 不要默默吞掉錯誤資料
8. `battery_soc` 與 `battery_soh` 建議落在 0–100
9. `battery_health_status` 建議只能使用 `normal`、`warning`、`critical`、`unknown`
10. `battery_is_second_life` 建議只能使用 `true` 或 `false`
11. `ems_mode` 必須使用 canonical allowed values：`auto`、`manual`、`schedule`、`tou_arbitrage`、`peak_shaving`、`self_consumption`、`idle`、`fallback`、`error`、`unknown`
12. `equipment_status` 必須使用 canonical allowed values：`normal`、`warning`、`fault`、`error`、`offline`、`maintenance`、`unknown`

---

## 8. MVP v1 暫不處理

資料層暫不處理：
- real-time streaming data
- direct EMS API ingestion
- Excel advanced parsing
- sensor-level raw data
- official carbon accounting records
- real power trading market data
