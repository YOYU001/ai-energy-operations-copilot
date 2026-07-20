# backend

FastAPI application，未來將包含 API endpoints、CSV ingestion、RAG ingestion、analysis services、database access 與 role-based response orchestration。

## 目前狀態（Step 4: Dataset Ingestion 完成）

包含 `GET /health`、`GET /version`、`GET /db-check`、`POST /datasets/upload` 四個 endpoint。尚未有 RAG、frontend、dashboard 或 rule-based analysis。

`POST /datasets/upload` 接受 CSV（`multipart/form-data`），驗證與型別轉換規則見 `docs/DATA_SCHEMA.md` 第 7 章，實作於 `app/ingestion.py`：
- 缺少 `timestamp`／`site_id`，或完全沒有 PV/Load/Battery/Price 任一基本欄位 → 整批拒絕（`status: failed`）
- `timestamp` 無法解析 → 該列跳過，記入 `warnings`
- 數值欄位轉換失敗 → 該值存 `NULL`，記入 `warnings`，不影響整列
- CSV 中缺少的欄位 → 整欄存 `NULL`，記入 `warnings`
- 成功寫入 `datasets` 與 `energy_timeseries` 兩張表

## 如何啟動

1. 先啟動 database（見 `database/README.md`），並確認專案根目錄有 `.env`（複製自 `.env.example` 並填入實際密碼）。
2. 於 conda environment `AI_Copilot` 中，於專案根目錄執行：

```text
uvicorn app.main:app --reload --app-dir backend
```

啟動後可測試：

```text
GET  http://127.0.0.1:8000/health
GET  http://127.0.0.1:8000/version
GET  http://127.0.0.1:8000/db-check
POST http://127.0.0.1:8000/datasets/upload
```

範例：

```text
curl -F "file=@sample.csv" -F "name=demo dataset" http://127.0.0.1:8000/datasets/upload
```
