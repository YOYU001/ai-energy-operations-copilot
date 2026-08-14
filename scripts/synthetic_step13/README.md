# Step 13 Synthetic Test/Demo Fixtures

**這些是 100% 人工合成（synthetic）的 CSV fixtures，供 Step 13（battery
scheduling／cost estimation／Green Operations Index）的 ingestion、
rule/API、dashboard 與 edge-case 測試使用。它們不代表任何真實場域、不含任何
真實 EMS／BMS 資料，也不是 Step 13.7 real-world validation 的證據。
Step 13.7 目前仍為 `pending`，需要真實、已授權、去識別化的 time-series 資料
才能開始執行，詳見 Step 13.7 validation plan。**

## 產生方式

```bash
python scripts/synthetic_step13/generate_synthetic_step13_fixtures.py
```

- Deterministic：固定 `SEED = 13`（`numpy.random.default_rng`），重跑會產生
  byte-identical 的 CSV。
- 純本機檔案產生，**不呼叫任何 API、不寫入資料庫**。
- 資料集基準時間：`2026-03-01 00:00:00` 起，15 分鐘一筆。

## Schema mapping（依 `backend/app/ingestion.py` 實際 contract）

- Structural required：`timestamp`、`site_id`（缺任一則整份 upload 被拒絕，
  `IngestionError`）。
- 至少要有以下四組欄位各一個：`[pv_forecast_kw, pv_actual_kw]`、
  `[load_kw, load_forecast_kw]`、`[battery_soc, battery_power_kw]`、
  `[electricity_price]`。
- 其餘欄位若整份 CSV 缺席，會被 ingestion 補 `NULL`、產生 warning，upload
  仍會成功（不拒絕）。
- Sign convention（`docs/MVP1_RULES.md`）：`battery_power_kw > 0` = 放電，
  `< 0` = 充電，`0` = 待機。

## 各 fixture 說明與（已用純函式實測驗證的）預期結果

驗證方式：直接呼叫 `backend/app/ingestion.parse_and_validate_csv`、
`app.services.battery_scheduling.evaluate_battery_scheduling`、
`app.services.cost_estimation.evaluate_cost_estimation`、
`app.services.green_operations_index.evaluate_green_operations_index`
這幾個**純函式**（無 DB session、無 FastAPI app、無 HTTP），確認以下結果為
實測數字，不是預測。

### 1. `happy_path_multisite.csv`

- 2 sites（`site_001` 契約容量 100kW、`site_002` 契約容量 150kW）× 96 rows
  = 192 rows total，全欄位齊全。
- **實測**：0 個 upload warning；192 列全部 persisted；scheduling
  `{'charge': 20, 'hold': 172}`；Cost `site_count=2`，兩個 site 各 95 個
  interval，`total_energy_cost≈4064.79`；Green Ops 兩個 site 的 4 個
  component 全部 `computed`，`dataset_aggregate.total_score≈89.21`，
  `second_life_bonus=[0.0, 0.0]`（未標記 second-life）。

### 2. `battery_second_life.csv`

- 1 site（`site_sl01`）× 96 rows，`battery_is_second_life=true`，
  `battery_health_status="normal"` 全程，`battery_temperature` 已限制在
  20–34°C（低於 `BATTERY_HEALTH_TEMP_THRESHOLD=40`），對應
  `_compute_second_life_bonus` 的 confirmed-safe path。
- **實測**：0 個 warning；96 列全部 persisted；scheduling
  `{'hold': 95, 'charge': 1}`；Cost 95 個 interval，
  `total_energy_cost≈2704.98`；Green Ops 4 個 component 全部 `computed`，
  `total_score=100.0`，**`second_life_bonus=10.0`**（confirmed-safe 判定
  正確觸發）。

### 3. `missing_optional_fields.csv`

- 1 site（`site_partial01`）× 96 rows，header 只有 6 欄：`timestamp`、
  `site_id`、`pv_actual_kw`、`load_kw`、`battery_power_kw`、
  `electricity_price`——滿足四組 required column group（PV／load／
  battery／price 各一），但 `battery_soc`、`battery_temperature`、
  `battery_health_status`、`battery_soh`、`contract_capacity_kw`、
  `grid_export_kw`、`grid_import_kw` 等**完全不在 header 裡**（structural
  missing，不是單列 null）。
- **實測**：upload 成功，20 筆「column missing in CSV」warning；96 列全部
  persisted；scheduling 因 `battery_soc`／`grid_import_kw`／
  `contract_capacity_kw` 缺席，`soc_ok`／`grid_ok` 恆 False，全部 96 列
  結果都是 `hold`（不 crash，符合預期降級行為）；Cost 因 `grid_import_kw`
  結構性缺席，`total_energy_cost=0.0`（已知限制：整欄缺失與單列 null
  在目前實作中回傳相同結果，見 Step 13.7 plan §4.2）；Green Ops：
  `pv_utilization`／`grid_dependency`／`battery_health` 三個 component
  皆為 `insufficient_data`（依 §4.3 對應的欄位缺失規則），
  `battery_operation` 仍為 `computed`（BSD signal 需要的欄位齊全），
  `dataset_aggregate.total_score=None`，`second_life_bonus=None`。

### 4. `timestamp_edge_cases_partial.csv`

- 1 site（`site_tsedge01`）× 30 rows，全欄位齊全，其中第 4、9、15、20、
  24、28 列（0-indexed 3, 8, 14, 19, 23, 27）的 `timestamp` 值故意設為
  `"not-a-date"`、空字串、`"32/13/2026"`、`"2026-99-99"`、`"N/A"`、
  `"2026-03-01 25:70:00"` 六種不同的無法解析格式。
- **實測**：upload 成功，6 筆「could not parse timestamp value」warning；
  persisted rows = 24（30 − 6）；scheduling 全部 `hold`（剩餘列的
  battery_soc 走勢在這組合成資料下未觸發 charge/discharge 條件，但確認
  不 crash）；Cost `interval_count=23`；Green Ops 4 個 component 全部
  `computed`，`total_score≈89.31`——證明部分列失敗不影響其餘列的分析。

### 5. `timestamp_edge_cases_all_invalid.csv`

- 1 site（`site_tsedge02`）× 10 rows，header 與其餘欄位皆合法，**僅
  `timestamp` 全部 10 列都設為無法解析的字串**（`"invalid-timestamp-0"`
  … `"invalid-timestamp-9"`）。
- **實測**：upload 成功（不是 `IngestionError`——只有 `timestamp`／
  `site_id` header 缺席才會整份拒絕），但 10 筆「could not parse
  timestamp value」warning，**persisted rows = 0**。因為 0 筆資料進入
  分析，本次驗證腳本略過了 rule 評估；依 Step 13.7 plan §4，這代表
  Battery scheduling／Cost／Green Ops 三個 dimension 在這份資料上
  Validation status 皆為 `pending`（無資料可評估，不是「有資料但算出
  insufficient_data」）。

### 6. `invalid_enum_and_sign_cases.csv`

- 1 site（`site_enumsign01`）× 20 rows，全欄位齊全。
- **Sign convention 文件化用途**（第 0–3 列，人為覆寫，**非真實 sign
  convention 驗證證據**，僅供 UI／規則展示用）：
  - Row 0：`battery_soc=70.0`, `battery_power_kw=10.0`（放電，>0）
  - Row 1：`battery_soc=60.0`, `battery_power_kw=10.0`（SOC 相對 row 0
    下降 10，與放電方向一致）
  - Row 2：`battery_soc=60.0`, `battery_power_kw=-10.0`（充電，<0）
  - Row 3：`battery_soc=70.0`, `battery_power_kw=-10.0`（SOC 相對 row 2
    上升 10，與充電方向一致）
- **Invalid enum／boolean 案例**（第 5、6、7、8 列）：
  - Row 5：`battery_health_status="totally_bogus"`
  - Row 6：`ems_mode="not_a_real_mode"`
  - Row 7：`equipment_status="???"`
  - Row 8：`battery_is_second_life="maybe"`
- **實測**：upload 成功，4 筆 warning——3 筆「invalid value」（對應
  row 5/6/7 的三個 enum 欄位，皆被 ingestion 正規化並 coerce 成
  `"unknown"`）+ 1 筆「invalid boolean value, expected true or false」
  （row 8 的 `battery_is_second_life`，被存成 `NULL`）；20 列全部
  persisted（enum/boolean 錯誤不會丟列，只會 coerce 該欄位）；scheduling
  `{'charge': 1, 'hold': 19}`；Cost `interval_count=19`；Green Ops 4 個
  component 全部 `computed`，`total_score≈88.95`——證明 invalid enum／
  boolean 值不會讓 upload 被拒絕、不會讓其他欄位的分析失敗，符合
  `ingestion.py` 的 coerce-to-unknown 設計。

## 已知限制 / 不涵蓋範圍

- 這些 fixture 的充放電決策、PV 曲線、負載曲線都是簡化的規則式模擬
  （見 `generate_synthetic_step13_fixtures.py` 的 `_simulate_site`），
  不是任何真實場域的物理模型，數值本身沒有 domain 意義。
- 不包含任何來自三份 Taipower 內部研究報告的片段資料。
- `invalid_enum_and_sign_cases.csv` 的 sign-convention 文件化列，只是把
  `docs/MVP1_RULES.md` 已定義的假設具象化成 4 筆範例資料，用來讓
  ingestion／dashboard 測試時有東西可看；**不能**當作 Step 13.7 plan §5.2
  要求的「獨立 sign convention evidence」，那必須來自真實 EMS event log
  或真實 SOC 走勢。
