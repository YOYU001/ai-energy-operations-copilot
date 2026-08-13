# Step 13.7 Synthetic Validation Report

**結論：`synthetic validation complete`。這不是 `real-world validation`。**

Real-world EMS/BMS validation is out of scope for MVP1.

## Scope

| Sub-step | 結論 |
|---|---|
| Battery Scheduling | `API-level synthetic validation`；前端無 dashboard UI（`frontend/` 內找不到任何呼叫 `/schedule` 的 client 函式或頁面），僅完成 API 層驗證 |
| Cost Estimation | `API + dashboard synthetic validation` |
| Green Operations Index | `API + dashboard synthetic validation` |

## Track A — Automated integration test

- 檔案：`backend/tests/test_step13_synthetic_dashboard_validation.py`
- 走真實 CSV bytes → `POST /datasets/upload` → `parse_and_validate_csv` → `/schedule`／`/cost`／`/green-operations-index`
- 結果：**7/7 passed**
- 全專案回歸：**566 passed**（含既有 559 個測試，無 regression）
- Cleanup evidence：測試內建 `real_pg_upload` fixture 於每次測試結束後刪除自己建立的 dataset，並斷言 `datasets`／`energy_timeseries`／`analysis_runs` 殘留列數為 0；另有 module-level fixture 比對測試前後所有既有 dataset（id, row_count）完全未變動

## Track B — Dashboard rendering verification

以 `curl` 上傳 fixture CSV（前端目前無 CSV upload UI，`/datasets/upload` 只能經 API 呼叫），再於實際啟動的本機 dev server 上瀏覽 `/datasets/{id}` 頁面並點擊「執行成本分析」／「執行綠能營運指數分析」按鈕，確認渲染結果。

| dataset_id | fixture | Cost 畫面渲染結果 | Green Ops 畫面渲染結果 |
|---|---|---|---|
| 271 | `happy_path_multisite.csv` | 總成本 **4,064.79**、電池套利淨額 **230.83**、站點數 2 | site_001 89.47／site_002 88.95，資料集彙總 **89.21/100**，4 個 component 全部 `computed` |
| 272 | `missing_optional_fields.csv` | 總成本 0（`grid_import_kw` 結構性缺席之已知限制）、電池套利淨額 164.72（`battery_power_kw` 仍存在故可算） | `site_partial01：資料不足`；PV 利用率／電網依賴度／電池健康度顯示「資料不足以計算此分項」；電池操作 `20/20 computed`，不 crash |

Cleanup evidence：`DELETE FROM analysis_runs`（4 筆）／`energy_timeseries`（**288** 筆）／`datasets`（2 筆）皆針對 dataset_id 271、272 精確刪除；刪除後以獨立 SQL 查詢核對三張表殘留皆為 **0**。本次啟動的 backend／frontend dev server 已用明確 PID 停止，docker DB container 已 `docker compose stop`。

## Fixture 範圍

全部來自 `scripts/synthetic_step13/fixtures/`（固定 seed=13，見同目錄 `README.md`）：

- `happy_path_multisite.csv` — 2 site，全欄位齊全
- `battery_second_life.csv` — second-life 電池，confirmed-safe path
- `missing_optional_fields.csv` — 僅保留 4 個 required column group，其餘 structural missing
- `timestamp_edge_cases_partial.csv` — 部分 timestamp 無法解析
- `timestamp_edge_cases_all_invalid.csv` — 全部 timestamp 無法解析
- `invalid_enum_and_sign_cases.csv` — 無效 enum／boolean 值 + sign convention 文件化樣本

## 已知限制

- Battery Scheduling 完全沒有前端 UI／dashboard，只能做到 API-level synthetic validation。
- 前端沒有 CSV upload UI，Track B 的資料上傳一律經由 API／curl，不是透過畫面操作上傳。
- 三份 Taipower 內部研究報告（`scripts/2415-1304...`／`2415-1305...`／`A 完整版本...`）僅作為 domain evidence／scenario design 參考，未被用於本次驗證的任何 fixture 內容，也不構成 real-world validation 的依據。

## 結論用語規範

本報告與任何後續引用，一律使用 `synthetic validation complete`；不得使用 `real-world validation` 字樣。
