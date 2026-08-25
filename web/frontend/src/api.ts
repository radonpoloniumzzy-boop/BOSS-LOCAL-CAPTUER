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
  latest_rating: string;
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

export type CandidateAppearanceRow = {
  batch_id: number;
  source_platform: string;
  source_job_title: string;
  capture_time: string;
  ingest_status: string;
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
  latest_rating: string;
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

export type JobProfileRow = {
  id: number;
  job_title: string;
  department: string;
  location: string;
  employment_type: string;
  target_hires: number;
  priority: string;
  status: string;
  version: number;
  updated_at: string;
};

export type JobProfileDetail = JobProfileRow & {
  hiring_manager: string;
  experience_requirement: string;
  education_requirement: string;
  recruitment_deadline: string;
  jd_text: string;
  must_have: string[];
  nice_to_have: string[];
  risk_flags: string[];
  exclusions: string[];
  interview_checks: string[];
  evidence_policy: Record<string, unknown>;
  created_at: string;
};

export type JobProfileVersionRow = {
  version: number;
  created_at: string;
  snapshot: JobProfileDetail;
};

export type RecruitmentTaskRow = {
  id: number;
  name: string;
  role_id: number;
  role_title: string;
  profile_version: number;
  platform: string;
  source_url: string;
  target_candidates: number;
  status: string;
  current_step: string;
  latest_message: string;
  batch_count: number;
  candidate_count: number;
  run_count: number;
  export_count: number;
  created_at: string;
  updated_at: string;
};

export type RecruitmentTaskProgress = {
  task_id: number;
  task_name: string;
  task_status: string;
  job_profile_id: number;
  job_profile_version: number;
  job_title: string;
  target_count: number;
  is_plugin_context: boolean;
  batch_count: number;
  batch_item_count: number;
  unique_candidate_count: number;
  total_received: number;
  total_added: number;
  total_updated: number;
  total_skipped: number;
  total_failed: number;
  rated_candidate_count: number;
  unrated_candidate_count: number;
  rating_counts: Record<"UR" | "SSR" | "SR" | "R" | "N", number>;
  first_capture_time: string;
  latest_capture_time: string;
  recent_batches: Array<{
    batch_id: number;
    source_platform: string;
    status: string;
    start_time: string;
    received: number;
    added: number;
    updated: number;
    skipped: number;
    failed: number;
  }>;
};

export type PluginTaskContext = {
  recruitment_task_id: number;
  job_profile_id: number;
  job_profile_version: number;
  job_title: string;
  platform: string;
  source_url: string;
  task_status: string;
  context_updated_at: string;
};

export type ExternalRatingImportRow = {
  line: number;
  candidate_id: number | null;
  name: string;
  rating: string;
  original_rating?: string;
  track?: string;
  reason?: string;
  status: "imported" | "unmatched" | "ambiguous" | "invalid";
  message: string;
};

export type ExternalRatingPreviewRow = {
  line: number;
  candidate_id: string | number | null;
  name: string;
  rating: string;
  original_rating: string;
  rating_status: "exact" | "normalized" | "needs_confirmation" | "invalid";
  track: string;
  reason: string;
  batch_id: string | number | null;
  source_platform: string;
  source_job_title: string;
};

export type ExternalRatingPreviewResult = {
  task_id: number;
  received: number;
  rows: ExternalRatingPreviewRow[];
};

export type ExternalRatingImportResult = {
  task_id: number;
  run_id: number;
  status: string;
  received: number;
  imported: number;
  unmatched: number;
  ambiguous: number;
  invalid: number;
  rows: ExternalRatingImportRow[];
};

export type KeywordRuleGroup = "must" | "plus" | "risk" | "note";

export type KeywordRules = Record<KeywordRuleGroup, string[]>;

export type KeywordRulesResponse = {
  task_id: number;
  job_profile_id: number;
  job_profile_version: number;
  task_status: string;
  keyword_rules: KeywordRules;
  changed?: boolean;
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

export async function downloadBatchMarkdown(batchId: number): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/capture-batches/${batchId}/export.md`);
  } catch {
    throw new ApiRequestError("network_error", "无法连接本地服务，请确认网页程序仍在运行。");
  }

  if (!response.ok) {
    let payload: ApiError = {};
    try {
      payload = await response.json() as ApiError;
    } catch {
      payload = {};
    }
    throw new ApiRequestError(
      payload.error?.code || "export_failed",
      payload.error?.message || "Markdown 导出失败，请稍后重试。",
    );
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const filename = match ? decodeURIComponent(match[1]) : `batch-${batchId}.md`;
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    try {
      link.click();
    } catch {
      throw new ApiRequestError("export_failed", "Markdown 导出失败，请稍后重试。");
    }
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
