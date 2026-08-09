export type SetupStatus = {
  setup_required: boolean;
  suggested_data_dir: string;
  configured_data_dir: string | null;
  existing_database_detected: boolean;
};

export type AppStatus = {
  version: string;
  database_ready: boolean;
  data_dir: string;
  candidate_count: number;
  batch_count: number;
  latest_batch_id: number;
  latest_batch_status: string;
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
      payload.error?.message || "本地服务请求失败。请稍后重试。",
    );
  }
  return payload;
}
