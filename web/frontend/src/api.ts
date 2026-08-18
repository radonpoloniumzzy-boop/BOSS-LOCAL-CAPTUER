export type SetupStatus = {
  setup_required: boolean;
  suggested_data_dir: string;
  configured_data_dir: string | null;
  existing_database_detected: boolean;
};

export type AppStatus = {
  status: "ready";
  version: string;
  database_ready: boolean;
  data_dir: string;
  candidate_count: number;
  batch_count: number;
  latest_batch_id: number;
  latest_batch_status: string;
};

export type HealthStatus = {
  status: string;
  service: string;
  version: string;
  capabilities: string[];
};

export type CandidateRow = {
  id: number;
  name: string;
  source_platform: string;
  latest_source_platform: string;
  latest_source_job_title: string;
  latest_batch_id: number;
  latest_capture_time: string;
  latest_ingest_status: string;
  latest_batch_role_id: number | null;
  has_role_binding: boolean | number;
  batch_count: number;
};

export type CandidateDetail = CandidateRow & {
  job_title: string;
  source_url: string;
  capture_time: string;
  raw_card_text: string;
  active_status: string;
  expected_salary: string;
  work_experience_text: string;
  education_text: string;
  tags_text: string;
  summary_text: string;
  detail_url: string;
  latest_raw_card_text: string;
  latest_source_url: string;
  latest_detail_url: string;
  city: string;
  years_experience: number | null;
  job_family: string;
  job_track: string;
  batch_count: number;
};

export type CaptureBatchRow = {
  id: number;
  start_time: string;
  source_platform: string;
  total_collected: number;
  total_new: number;
  total_updated: number;
  total_skipped: number;
  total_failed: number;
  status: string;
  role_id: number | null;
};

export type BatchCandidateRow = {
  id: number;
  batch_id: number;
  candidate_id: number;
  name: string;
  source_platform: string;
  platform_uid: string;
  job_title: string;
  capture_time: string;
  raw_card_text: string;
  ingest_status: string;
  has_role_binding: boolean | number;
};

export type PagedResponse<T> = {
  rows: T[];
  total: number;
  page: number;
  page_size: number;
};

export type PluginConnectionStatus = {
  service_ok: boolean;
  api_base: string;
  connected: boolean;
  last_verified_at: string;
  data_dir: string;
};

type ApiError = { error?: { code?: string; message?: string } };

export class ApiRequestError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiRequestError("network_error", "无法连接本地服务，请确认网页程序仍在运行。");
  }

  const payload = (await response.json()) as T & ApiError;
  if (!response.ok) {
    throw new ApiRequestError(
      payload.error?.code || "request_failed",
      payload.error?.message || "本地服务请求失败，请稍后重试。",
    );
  }
  return payload;
}
