from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class IngestWarning(BaseModel):
    row: Optional[int] = None
    column: Optional[str] = None
    issue: str
    action: str


class IngestResult(BaseModel):
    dataset_id: Optional[int] = None
    row_count: int
    inserted_count: int
    warnings: list[IngestWarning]
    status: str


class DatasetSummary(BaseModel):
    id: int
    name: Optional[str] = None
    file_name: Optional[str] = None
    description: Optional[str] = None
    row_count: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ColumnStatistics(BaseModel):
    min: Optional[float] = None
    mean: Optional[float] = None
    max: Optional[float] = None


class DatasetSummaryStatistics(BaseModel):
    dataset_id: int
    row_count: int
    site_count: int
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    columns: dict[str, ColumnStatistics]


class TimeseriesRow(BaseModel):
    id: int
    dataset_id: int
    timestamp: Optional[datetime] = None
    site_id: Optional[str] = None
    pv_forecast_kw: Optional[float] = None
    pv_actual_kw: Optional[float] = None
    load_kw: Optional[float] = None
    load_forecast_kw: Optional[float] = None
    battery_soc: Optional[float] = None
    battery_power_kw: Optional[float] = None
    battery_temperature: Optional[float] = None
    electricity_price: Optional[float] = None
    contract_capacity_kw: Optional[float] = None
    grid_import_kw: Optional[float] = None
    grid_export_kw: Optional[float] = None
    weather_condition: Optional[str] = None
    ghi: Optional[float] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    ems_mode: Optional[str] = None
    equipment_status: Optional[str] = None
    battery_soh: Optional[float] = None
    battery_cycle_count: Optional[int] = None
    battery_equivalent_cycle: Optional[float] = None
    battery_health_status: Optional[str] = None
    battery_is_second_life: Optional[bool] = None
    battery_rated_capacity_kwh: Optional[float] = None
    battery_available_capacity_kwh: Optional[float] = None


class TimeseriesPage(BaseModel):
    dataset_id: int
    total: int
    limit: int
    offset: int
    items: list[TimeseriesRow]


class PriceThresholdInfo(BaseModel):
    mode: str  # "insufficient_data" | "no_distinguishable_peak" | "discrete_tou_max" | "percentile"
    threshold: Optional[float] = None
    non_null_sample_count: int
    distinct_price_count: int
    reason: Optional[str] = None


class BatteryDischargeEvidence(BaseModel):
    electricity_price: Optional[float] = None
    high_price_threshold: Optional[float] = None
    price_threshold_mode: str
    grid_import_kw: Optional[float] = None
    contract_capacity_kw: Optional[float] = None
    contract_capacity_ratio: Optional[float] = None
    battery_soc: Optional[float] = None
    battery_power_kw: Optional[float] = None
    non_null_price_sample_count: int
    distinct_price_count: int


class AnomalyResult(BaseModel):
    anomaly_type: str
    severity: str
    timestamp: Optional[datetime] = None
    evidence: BatteryDischargeEvidence
    suggested_actions: list[str]


class BatteryDischargeAnalysisResult(BaseModel):
    rule: str
    rule_version: str
    price_threshold: PriceThresholdInfo
    input_row_count: int
    evaluated_row_count: int
    flagged_row_count: int
    anomalies: list[AnomalyResult]


class AnalysisRunResponse(BaseModel):
    analysis_run_id: int
    dataset_id: int
    analysis_type: str
    rule_version: str
    created_at: datetime
    result: BatteryDischargeAnalysisResult


class DocumentSummary(BaseModel):
    id: int
    title: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    source_type: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    status: str
    total_pages: Optional[int] = None
    supersedes_document_id: Optional[int] = None


class DocumentUploadResult(BaseModel):
    document_id: int
    file_name: str
    status: str  # "processing" | "already_ingested"


class ChunkSummary(BaseModel):
    chunk_id: str
    strategy_name: str
    chunk_type: str
    content: str
    page_index_start: int
    page_index_end: int
    pdf_page_number_start: int
    pdf_page_number_end: int
    section_title: Optional[str] = None
    table_title: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimensions: Optional[int] = None
    embedding_model_version: Optional[str] = None
    embedded_at: Optional[datetime] = None
    is_active: bool


class CaseSummary(BaseModel):
    """GET /cases list item -- deliberately excludes answer-shaped fields
    (root_cause/operator_action/resolution_result) so browsing the list
    never leaks a case's resolution before the user opens its detail."""

    case_id: str
    event_type: Optional[str] = None
    symptoms: Optional[str] = None
    tags: Optional[str] = None
    severity: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CasesPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CaseSummary]


class CaseDetail(BaseModel):
    """GET /cases/{case_id} -- full record, including answer-shaped fields
    and provenance. Never includes the raw embedding vector."""

    case_id: str
    site_id: Optional[str] = None
    event_time: Optional[datetime] = None
    event_type: Optional[str] = None
    symptoms: Optional[str] = None
    root_cause: Optional[str] = None
    operator_action: Optional[str] = None
    resolution_result: Optional[str] = None
    severity: Optional[str] = None
    tags: Optional[str] = None
    related_dataset_id: Optional[int] = None
    related_time_range: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimensions: Optional[int] = None
    embedding_model_version: Optional[str] = None
    embedded_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CaseSearchRequest(BaseModel):
    query: str
    event_type: Optional[str] = None
    tags: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)


class CaseSearchResult(BaseModel):
    """Shared response item for GET /cases/{case_id}/similar and
    POST /cases/search -- backend returns fully-computed scoring, never a
    raw embedding vector or answer-shaped fields (root_cause/
    operator_action/resolution_result); those are reserved for
    GET /cases/{case_id}."""

    case_id: str
    event_type: Optional[str] = None
    symptoms: Optional[str] = None
    tags: Optional[str] = None
    severity: Optional[str] = None
    semantic_score: float
    event_type_match: bool
    tags_boost: float
    final_score: float
    confidence: str
    # Composite semantic-similarity description (event_type + symptoms + tags
    # + severity combined -- see build_case_search_text in
    # scripts/seed_case_records.py), NOT a symptoms-only comparison. Renamed
    # from symptoms_similarity (PR #37 Codex review, P2) -- the old name
    # implied it isolated symptom text similarity, which it never did.
    case_similarity: str
    matches: list[str]
    differs: list[str]


# Step 12 Sub-step 3A slice 2: Conversation CRUD (no /messages endpoint yet
# -- see docs/step12_substep3a_plan.md). role_mode is Literal, not a bare
# str, so an invalid value is rejected as a 422 by FastAPI/Pydantic itself,
# matching the DB CHECK constraint's 4 allowed values (Sub-step 1 schema).
RoleMode = Literal["operator", "engineer", "executive", "training"]


class ConversationCreateRequest(BaseModel):
    role_mode: Optional[RoleMode] = None


class ConversationSummary(BaseModel):
    id: int
    title: Optional[str] = None
    role_mode: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ConversationsPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ConversationSummary]


class ChatMessageSummary(BaseModel):
    id: int
    role: str
    content: str
    status: str
    parent_user_message_id: Optional[int] = None
    attempt_number: int
    is_active: bool
    provider: Optional[str] = None
    model: Optional[str] = None
    finish_reason: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class ConversationDetail(BaseModel):
    conversation: ConversationSummary
    messages: list[ChatMessageSummary]


class ConversationUpdateRequest(BaseModel):
    title: Optional[str] = None
    role_mode: Optional[RoleMode] = None


class PostMessageRequest(BaseModel):
    content: str
