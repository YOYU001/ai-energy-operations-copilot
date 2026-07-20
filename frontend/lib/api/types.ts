export interface HealthResponse {
  status: string;
}

export interface VersionResponse {
  version: string;
}

export interface DatasetSummary {
  id: number;
  name: string | null;
  file_name: string | null;
  description: string | null;
  row_count: number | null;
  start_time: string | null;
  end_time: string | null;
  created_at: string | null;
}
