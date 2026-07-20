-- AI Energy Operations Copilot MVP v1 - Initial Schema
-- See docs/DATA_SCHEMA.md section 6 for field definitions.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    title TEXT,
    file_name TEXT,
    file_type TEXT,
    source_type TEXT,
    uploaded_at TIMESTAMP,
    status TEXT
);

-- embedding dimension (1536) is a placeholder pending final embedding model choice (see Step 9: Knowledge Base / RAG)
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    chunk_index INTEGER,
    content TEXT,
    page_number INTEGER,
    embedding vector(1536)
);

CREATE TABLE IF NOT EXISTS datasets (
    id SERIAL PRIMARY KEY,
    name TEXT,
    file_name TEXT,
    description TEXT,
    row_count INTEGER,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS energy_timeseries (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(id),
    timestamp TIMESTAMP,
    site_id TEXT,
    pv_forecast_kw NUMERIC,
    pv_actual_kw NUMERIC,
    load_kw NUMERIC,
    load_forecast_kw NUMERIC,
    battery_soc NUMERIC,
    battery_power_kw NUMERIC,
    battery_temperature NUMERIC,
    electricity_price NUMERIC,
    contract_capacity_kw NUMERIC,
    grid_import_kw NUMERIC,
    grid_export_kw NUMERIC,
    weather_condition TEXT,
    ghi NUMERIC,
    temperature NUMERIC,
    humidity NUMERIC,
    ems_mode TEXT,
    equipment_status TEXT,
    battery_soh NUMERIC,
    battery_cycle_count INTEGER,
    battery_equivalent_cycle NUMERIC,
    battery_health_status TEXT,
    battery_is_second_life BOOLEAN,
    battery_rated_capacity_kwh NUMERIC,
    battery_available_capacity_kwh NUMERIC
);

-- embedding dimension (1536) is a placeholder pending final embedding model choice (see Step 9: Knowledge Base / RAG)
CREATE TABLE IF NOT EXISTS case_records (
    id SERIAL PRIMARY KEY,
    case_id TEXT,
    site_id TEXT,
    event_time TIMESTAMP,
    event_type TEXT,
    symptoms TEXT,
    root_cause TEXT,
    operator_action TEXT,
    resolution_result TEXT,
    severity TEXT,
    tags TEXT,
    related_dataset_id INTEGER REFERENCES datasets(id),
    related_time_range TEXT,
    embedding vector(1536)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(id),
    analysis_type TEXT,
    result_json JSONB,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    role TEXT,
    content TEXT,
    created_at TIMESTAMP
);
