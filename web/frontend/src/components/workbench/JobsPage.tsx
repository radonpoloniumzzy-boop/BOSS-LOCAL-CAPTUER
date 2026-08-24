import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";

import {
  ApiRequestError,
  ExternalRatingImportResult,
  ExternalRatingPreviewResult,
  ExternalRatingPreviewRow,
  JobProfileDetail,
  JobProfileRow,
  JobProfileVersionRow,
  KeywordRules,
  KeywordRulesResponse,
  PluginTaskContext,
  RecruitmentTaskRow,
  requestJson,
} from "../../api";
import { JobEditorDrawer, JobFormPayload, statusLabel, toneForStatus } from "./JobEditorDrawer";
import { RecruitmentTasksPanel } from "./RecruitmentTasksPanel";
import { formatDate, RefreshButton, StatusBadge, TableState } from "./common";

export function JobsPage({
  active,
  onOpenTaskCandidates,
  onOpenTaskBatches,
  onOpenBatch,
}: {
  active: boolean;
  onOpenTaskCandidates: (taskId: number, taskName: string) => void;
  onOpenTaskBatches: (taskId: number, taskName: string) => void;
  onOpenBatch: (batchId: number) => void;
}) {
  const [jobs, setJobs] = useState<JobProfileRow[]>([]);
  const [tasks, setTasks] = useState<RecruitmentTaskRow[]>([]);
  const [versions, setVersions] = useState<JobProfileVersionRow[]>([]);
  const [currentContext, setCurrentContext] = useState<PluginTaskContext | null>(null);
  const [selected, setSelected] = useState<JobProfileDetail | null>(null);
  const [jobDrawerOpen, setJobDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!active) return;
    setLoading(true);
    setError("");
    try {
      const [jobPayload, taskPayload, contextPayload] = await Promise.all([
        requestJson<{ rows: JobProfileRow[] }>("/api/job-profiles"),
        requestJson<{ rows: RecruitmentTaskRow[] }>("/api/recruitment-tasks"),
        requestJson<{ context: PluginTaskContext | null }>("/api/plugin-context"),
      ]);
      setJobs(jobPayload.rows);
      setTasks(taskPayload.rows);
      setCurrentContext(contextPayload.context);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "岗位数据读取失败，请稍后重试。");
    } finally {
      setLoading(false);
    }
  }, [active]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(""), 2400);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const refreshSelected = async (jobId: number) => {
    const [detail, versionPayload] = await Promise.all([
      requestJson<JobProfileDetail>(`/api/job-profiles/${jobId}`),
      requestJson<{ rows: JobProfileVersionRow[] }>(`/api/job-profiles/${jobId}/versions`),
    ]);
    setSelected(detail);
    setVersions(versionPayload.rows);
    return detail;
  };

  const openJob = async (jobId: number) => {
    setError("");
    try {
      await refreshSelected(jobId);
      setJobDrawerOpen(true);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "岗位详情读取失败，请稍后重试。");
    }
  };

  const openCreate = () => {
    setSelected(null);
    setVersions([]);
    setJobDrawerOpen(true);
  };

  const saveJob = async (payload: JobFormPayload, expectedVersion: number | null) => {
    setSaving(true);
    setError("");
    try {
      const saved = expectedVersion
        ? await requestJson<JobProfileDetail & { changed: boolean }>(`/api/job-profiles/${selected?.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...payload, expected_version: expectedVersion }),
          })
        : await requestJson<JobProfileDetail>("/api/job-profiles", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
      setSelected(saved);
      setNotice("岗位档案已保存。");
      await load();
      await refreshSelected(saved.id);
      return saved;
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : "岗位档案保存失败，请稍后重试。";
      setError(message);
      throw new Error(message);
    } finally {
      setSaving(false);
    }
  };

  const changeJobStatus = async (job: JobProfileDetail, status: string) => {
    setSaving(true);
    setError("");
    try {
      const updated = await requestJson<JobProfileDetail>(`/api/job-profiles/${job.id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, expected_version: job.version }),
      });
      setNotice("岗位状态已更新。");
      await load();
      await refreshSelected(updated.id);
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : "岗位状态更新失败。";
      setError(message);
      throw new Error(message);
    } finally {
      setSaving(false);
    }
  };

  const createTask = async (payload: {
    name: string;
    role_id: number;
    profile_version: number;
    platform: string;
    source_url: string;
    target_candidates: number;
  }) => {
    setSaving(true);
    setError("");
    try {
      const task = await requestJson<RecruitmentTaskRow>("/api/recruitment-tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setNotice("招聘任务已创建。");
      await load();
      return task;
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "招聘任务创建失败。");
      throw err;
    } finally {
      setSaving(false);
    }
  };

  const setTaskStatus = async (task: RecruitmentTaskRow, status: string) => {
    setSaving(true);
    setError("");
    try {
      await requestJson<RecruitmentTaskRow>(`/api/recruitment-tasks/${task.id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      setNotice("任务状态已更新。");
      await load();
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : "任务状态更新失败。";
      setError(message);
      throw new Error(message);
    } finally {
      setSaving(false);
    }
  };

  const assignPluginContext = async (task: RecruitmentTaskRow | null) => {
    setSaving(true);
    setError("");
    try {
      const payload = await requestJson<{ context: PluginTaskContext | null }>("/api/plugin-context", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recruitment_task_id: task?.id ?? null }),
      });
      setCurrentContext(payload.context);
      setNotice(task ? `已设为插件当前任务：${task.name}` : "已清除插件当前任务。");
      await load();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "插件当前任务更新失败。");
    } finally {
      setSaving(false);
    }
  };

  const previewExternalRatings = async (task: RecruitmentTaskRow, text: string): Promise<ExternalRatingPreviewResult> => {
    return requestJson<ExternalRatingPreviewResult>(`/api/recruitment-tasks/${task.id}/external-ratings/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, source_note: "web_paste" }),
    });
  };

  const importExternalRatings = async (
    task: RecruitmentTaskRow,
    text: string,
    rows: ExternalRatingPreviewRow[],
  ): Promise<ExternalRatingImportResult> => {
    setSaving(true);
    setError("");
    try {
      const result = await requestJson<ExternalRatingImportResult>(`/api/recruitment-tasks/${task.id}/external-ratings/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, rows, source_note: "web_paste" }),
      });
      setNotice(`外部评级导入完成：成功 ${result.imported}，未匹配 ${result.unmatched}，歧义 ${result.ambiguous}，无效 ${result.invalid}。`);
      await load();
      return result;
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : "外部评级导入失败，请检查名单后重试。";
      setError(message);
      throw new Error(message);
    } finally {
      setSaving(false);
    }
  };

  const loadKeywordRules = async (task: RecruitmentTaskRow): Promise<KeywordRulesResponse> => {
    return requestJson<KeywordRulesResponse>(`/api/recruitment-tasks/${task.id}/keyword-rules`);
  };

  const saveKeywordRules = async (
    task: RecruitmentTaskRow,
    rules: KeywordRules,
    expectedVersion: number,
  ): Promise<KeywordRulesResponse> => {
    setSaving(true);
    setError("");
    try {
      const result = await requestJson<KeywordRulesResponse>(`/api/recruitment-tasks/${task.id}/keyword-rules`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: expectedVersion, keyword_rules: rules }),
      });
      setNotice("关键词筛选规则已保存。");
      await load();
      return result;
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : "关键词筛选规则保存失败，请稍后重试。";
      setError(message);
      throw new Error(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-content page-enter">
      <div className="page-heading">
        <div>
          <p className="eyebrow">岗位档案</p>
          <h1>岗位、版本与招聘任务</h1>
          <p className="page-description">维护正式岗位档案，固定版本后创建招聘任务，并把执行中的任务同步给浏览器插件。</p>
        </div>
        <div className="toolbar-row">
          <RefreshButton onClick={load} />
          <button className="primary-button" onClick={openCreate}>
            <Plus size={15} />新建岗位
          </button>
        </div>
      </div>
      {notice && <div className="toast" role="status">{notice}</div>}
      <div className="split-workbench">
        <section className="work-panel">
          <div className="section-title">
            <h2>岗位列表</h2>
            <span>{jobs.length} 个岗位</span>
          </div>
          <TableState loading={loading} error={error} empty={!jobs.length} emptyText="还没有岗位档案。" />
          {jobs.length > 0 && (
            <div className="table-wrap">
              <table className="data-table job-table">
                <thead>
                  <tr>
                    <th>岗位</th>
                    <th>部门</th>
                    <th>地点</th>
                    <th>人数</th>
                    <th>优先级</th>
                    <th>状态</th>
                    <th>版本</th>
                    <th>更新</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id}>
                      <td>
                        <button className="link-button strong-link" onClick={() => void openJob(job.id)}>
                          {job.job_title || "未命名岗位"}
                        </button>
                        <small className="muted-id">#{job.id}</small>
                      </td>
                      <td>{job.department || "未提供"}</td>
                      <td>{job.location || "未提供"}</td>
                      <td className="tabular">{job.target_hires}</td>
                      <td>{job.priority || "normal"}</td>
                      <td><StatusBadge tone={toneForStatus(job.status)}>{statusLabel(job.status)}</StatusBadge></td>
                      <td className="tabular">v{job.version}</td>
                      <td className="tabular">{formatDate(job.updated_at)}</td>
                      <td>
                        <button className="secondary-button compact" onClick={() => void openJob(job.id)}>
                          查看
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <RecruitmentTasksPanel
          tasks={tasks}
          currentContext={currentContext}
          saving={saving}
          onOpenTaskCandidates={onOpenTaskCandidates}
          onOpenTaskBatches={onOpenTaskBatches}
          onOpenBatch={onOpenBatch}
          onStatusChange={setTaskStatus}
          onAssignContext={assignPluginContext}
          onPreviewRatings={previewExternalRatings}
          onImportRatings={importExternalRatings}
          onLoadKeywordRules={loadKeywordRules}
          onSaveKeywordRules={saveKeywordRules}
        />
      </div>

      {jobDrawerOpen && (
        <JobEditorDrawer
          selected={selected}
          versions={versions}
          saving={saving}
          onClose={() => setJobDrawerOpen(false)}
          onSave={saveJob}
          onStatusChange={changeJobStatus}
          onCreateTask={createTask}
        />
      )}
    </div>
  );
}
