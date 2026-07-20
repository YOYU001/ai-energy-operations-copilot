# database

PostgreSQL schema 與 pgvector setup。

## 目前狀態（Step 3: Database Foundation 完成）

- `schema.sql`：定義 7 張 initial table（documents、document_chunks、datasets、energy_timeseries、case_records、analysis_runs、chat_messages）並啟用 pgvector extension。
- 純 SQL，不使用 Alembic migration，也未建立任何 ORM model 或 seed data。

## 如何啟動 PostgreSQL（Docker）

於專案根目錄複製 `.env.example` 為 `.env` 並填入實際密碼，然後：

```text
docker compose up -d
```

## 如何套用 schema

```text
docker exec -i <container_name> psql -U ai_copilot -d ai_copilot < database/schema.sql
```

## 如何驗證

```text
docker exec -it <container_name> psql -U ai_copilot -d ai_copilot -c "\dt"
docker exec -it <container_name> psql -U ai_copilot -d ai_copilot -c "SELECT * FROM pg_extension WHERE extname='vector';"
```
