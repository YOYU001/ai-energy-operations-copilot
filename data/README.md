# data

此資料夾放置 sample CSV、sample Case Records 與 demo documents。

## `representative_synthetic_energy_operations_timeseries.csv`

**Representative synthetic demo data — not real-world data.**

Step 13 Sub-step 13.5 建立的示範用能源時間序列資料,人工合成,用於驗證
Cost Comparison（13.5）與 Green Operations Index（13.6）的 UI／圖表,
以及未來 portfolio demo。**不代表任何真實場域,不能作為 Sub-step 13.7
real-world dataset validation 的依據。**

- 2 個站點（`site_001`、`site_002`),各 49 筆整點資料(2026-03-01 00:00
  起,每小時一筆),共 98 列
- 涵蓋欄位：`docs/DATA_SCHEMA.md` §2 定義的全部 26 個 `energy_timeseries`
  欄位
- `electricity_price` 依小時交替於 3.0（低價）／8.0（高價）之間
- `site_001`：`contract_capacity_kw=100`,`battery_is_second_life=false`
- `site_002`：`contract_capacity_kw=150`,`battery_is_second_life=true`,
  第 20–22 小時刻意安排 `battery_temperature=42`／
  `battery_health_status="warning"` 的短暫異常區段（供 13.6 使用,不影響
  Cost 計算)
- `pv_actual_kw`／`load_kw`／`battery_soc` 等欄位依日夜週期與合理範圍變化,
  其餘欄位（`weather_condition`／`ghi`／`temperature`／`humidity`／
  `ems_mode`／`equipment_status`／`battery_soh`／`battery_cycle_count`／
  `battery_equivalent_cycle`／`battery_rated_capacity_kwh`／
  `battery_available_capacity_kwh`)填入合理示範值
