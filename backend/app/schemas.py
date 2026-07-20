from datetime import datetime
from typing import Optional

from pydantic import BaseModel


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
