---
name: db-bootstrap
description: 一鍵啟動本機 Docker PostgreSQL + pgvector、套用 database/schema.sql、並驗證 extension 與 7 張表是否真的建立成功。對應 CLAUDE.md Gotchas「SQL DDL 拆分陷阱」——套用 schema 後務必實際驗證，不能只看指令沒報錯就假設成功。用法："/db-bootstrap"。
---

執行 `python .claude/skills/db-bootstrap/scripts/bootstrap.py`（從 repo 根目錄執行）。

這支 script 會：
1. 執行 `docker compose up -d` 啟動資料庫容器，並輪詢 `pg_isready` 直到就緒（最多等待 30 秒）。
2. 透過 `docker compose exec db psql` 套用 `database/schema.sql`。
3. 連線資料庫，實際查詢 `pg_extension` 確認 `vector` extension 存在，並查詢 `information_schema.tables` 確認 7 張表（`documents`、`document_chunks`、`datasets`、`energy_timeseries`、`case_records`、`analysis_runs`、`chat_messages`）都存在。
4. 印出結構化結果：容器狀態、schema 套用是否成功、每張表是否存在。

若容器啟動逾時、schema 套用出錯、或有任何一張表缺失，script 會回傳非 0 exit code 並列出具體缺什麼，不要把「指令沒有丟出例外」當成「一定成功」。

需要根目錄 `.env`（可從 `.env.example` 複製）。若 `.env` 不存在，script 會直接停止並提示使用者先建立。
