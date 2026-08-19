import { FormEvent, useCallback, useEffect, useState } from "react";
import { BriefcaseBusiness, History, Link2, Plus, RefreshCw } from "lucide-react";

import {
  ApiRequestError,
  JobProfileDetail,
  JobProfileRow,
  JobProfileVersionRow,
  RecruitmentTaskRow,
  requestJson,
} from "../../api";
import { Drawer } from "./Drawer";
import { formatDate, RefreshButton, StatusBadge, TableState } from "./common";

type JobFormState = {
  job_title: string;
  department: string;
  hiring_manager: string;
  location: string;
  employment_type: string;
  target_hires: number;
  priority: string;
  status: string;
  experience_requirement: string;
  education_requirement: string;
  recruitment_deadline: string;
  jd_text: string;
  must_have: string;
  nice_to_have: string;
  risk_flags: string;
  exclusions: string;
  interview_checks: string;
};

type TaskFormState = {
  name: string;
  role_id: number;
  profile_version: number;
  platform: string;
  source_url: string;
  target_candidates: number;
};

const emptyJobForm: JobFormState = {
  job_title: "",
  department: "",
  hiring_manager: "",
  location: "",
  employment_type: "全职",
  target_hires: 1,
  priority: "normal",
  status: "draft",
  experience_requirement: "",
  education_requirement: "",
  recruitment_deadline: "",
  jd_text: "",
  must_have: "",
  nice_to_have: "",
  risk_flags: "",
  exclusions: "",
  interview_checks: "",
};

function splitLines(value: string) {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function jobToForm(job: JobProfileDetail | null): JobFormState {
  if (!job) return emptyJobForm;
  return {
    job_title: job.job_title || "",
    department: job.department || "",
    hiring_manager: job.hiring_manager || "",
    location: job.location || "",
    employment_type: job.employment_type || "",
    target_hires: job.target_hires || 1,
    priority: job.priority || "normal",
    status: job.status || "draft",
    experience_requirement: job.experience_requirement || "",
    education_requirement: job.education_requirement || "",
    recruitment_deadline: job.recruitment_deadline || "",
    jd_text: job.jd_text || "",
    must_have: (job.must_have || []).join("\n"),
    nice_to_have: (job.nice_to_have || []).join("\n"),
    risk_flags: (job.risk_flags || []).join("\n"),
    exclusions: (job.exclusions || []).join("\n"),
    interview_checks: (job.interview_checks || []).join("\n"),
  };
}

function jobFormPayload(form: JobFormState) {
  return {
    ...form,
    must_have: splitLines(form.must_have),
    nice_to_have: splitLines(form.nice_to_have),
    risk_flags: splitLines(form.risk_flags),
    exclusions: splitLines(form.exclusions),
    interview_checks: splitLines(form.interview_checks),
    evidence_policy: {},
  };
}

function toneForStatus(status: string) {
  if (["active", "running", "ready"].includes(status)) return "success";
  if (["paused", "waiting_user"].includes(status)) return "warning";
  if (["closed", "completed", "cancelled", "failed"].includes(status)) return "muted";
  return "neutral";
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    draft: "草稿",
    active: "招聘中",
    paused: "暂停",
    closed: "已关闭",
    ready: "待启动",
    running: "执行中",
    waiting_user: "等待处理",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[status] || status || "未提供";
}

export function JobsPage({ active }: { active: boolean }) {
  const [jobs, setJobs] = useState<JobProfileRow[]>([]);
  const [tasks, setTasks] = useState<RecruitmentTaskRow[]>([]);
  const [versions, setVersions] = useState<JobProfileVersionRow[]>([]);
  const [selected, setSelected] = useState<JobProfileDetail | null>(null);
  const [jobDrawerOpen, setJobDrawerOpen] = useState(false);
  const [jobForm, setJobForm] = useState<JobFormState>(emptyJobForm);
  const [taskForm, setTaskForm] = useState<TaskFormState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!active) return;
    setLoading(true);
    setError("");
    try {
      const [jobPayload, taskPayload] = await Promise.all([
        requestJson<{ rows: JobProfileRow[] }>("/api/job-profiles"),
        requestJson<{ rows: RecruitmentTaskRow[] }>("/api/recruitment-tasks"),
      ]);
      setJobs(jobPayload.rows);
      setTasks(taskPayload.rows);
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

  const openJob = async (jobId: number) => {
    setError("");
    try {
      const [detail, versionPayload] = await Promise.all([
        requestJson<JobProfileDetail>(`/api/job-profiles/${jobId}`),
        requestJson<{ rows: JobProfileVersionRow[] }>(`/api/job-profiles/${jobId}/versions`),
      ]);
      setSelected(detail);
      setJobDrawerOpen(true);
      setJobForm(jobToForm(detail));
      setVersions(versionPayload.rows);
      setTaskForm({
        name: `${detail.job_title} 推荐流`,
        role_id: detail.id,
        profile_version: detail.version,
        platform: "boss",
        source_url: "https://www.zhipin.com/web/geek/recommend",
        target_candidates: 0,
      });
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "岗位详情读取失败，请稍后重试。");
    }
  };

  const openCreate = () => {
    setSelected(null);
    setJobForm({ ...emptyJobForm });
    setVersions([]);
    setTaskForm(null);
    setJobDrawerOpen(true);
  };

  const saveJob = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload = jobFormPayload(jobForm);
      const saved = selected
        ? await requestJson<JobProfileDetail & { changed: boolean }>(`/api/job-profiles/${selected.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...payload, expected_version: selected.version }),
          })
        : await requestJson<JobProfileDetail>("/api/job-profiles", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
      setSelected(saved);
      setJobForm(jobToForm(saved));
      setNotice("岗位档案已保存。");
      await load();
      const versionPayload = await requestJson<{ rows: JobProfileVersionRow[] }>(`/api/job-profiles/${saved.id}/versions`);
      setVersions(versionPayload.rows);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "岗位档案保存失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  };

  const changeJobStatus = async (job: JobProfileDetail | JobProfileRow, status: string) => {
    setSaving(true);
    setError("");
    try {
      const updated = await requestJson<JobProfileDetail>(`/api/job-profiles/${job.id}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      setNotice("岗位状态已更新。");
      await load();
      if (selected?.id === updated.id) {
        setSelected(updated);
        setJobForm(jobToForm(updated));
      }
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "岗位状态更新失败。");
    } finally {
      setSaving(false);
    }
  };

  const createTask = async (event: FormEvent) => {
    event.preventDefault();
    if (!taskForm) return;
    setSaving(true);
    setError("");
    try {
      await requestJson<RecruitmentTaskRow>("/api/recruitment-tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(taskForm),
      });
      setNotice("招聘任务已创建。");
      await load();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "招聘任务创建失败。");
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
      setError(err instanceof ApiRequestError ? err.message : "任务状态更新失败。");
    } finally {
      setSaving(false);
    }
  };

  const assignPluginContext = async (task: RecruitmentTaskRow | null) => {
    setSaving(true);
    setError("");
    try {
      await requestJson("/api/plugin-context", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recruitment_task_id: task?.id ?? null }),
      });
      setNotice(task ? `已设为插件当前任务：${task.name}` : "已清除插件当前任务。");
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "插件当前任务更新失败。");
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
          <p className="page-description">维护正式岗位档案，固定版本后创建招聘任务，并把当前任务同步给浏览器插件。</p>
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

        <section className="work-panel">
          <div className="section-title">
            <h2>招聘任务</h2>
            <span>{tasks.length} 个任务</span>
          </div>
          {tasks.length === 0 ? (
            <div className="table-state">还没有招聘任务。先打开一个招聘中的岗位创建任务。</div>
          ) : (
            <div className="recruitment-list">
              {tasks.map((task) => (
                <article key={task.id} className="recruitment-card">
                  <div>
                    <strong>{task.name}</strong>
                    <p>{task.role_title} · v{task.profile_version} · {task.platform}</p>
                  </div>
                  <StatusBadge tone={toneForStatus(task.status)}>{statusLabel(task.status)}</StatusBadge>
                  <dl>
                    <div><dt>批次</dt><dd>{task.batch_count}</dd></div>
                    <div><dt>候选人</dt><dd>{task.candidate_count}</dd></div>
                    <div><dt>阶段</dt><dd>{task.current_step || "待启动"}</dd></div>
                  </dl>
                  <div className="button-row">
                    {task.status === "ready" && <button className="secondary-button compact" disabled={saving} onClick={() => void setTaskStatus(task, "running")}>启动</button>}
                    {task.status === "running" && <button className="secondary-button compact" disabled={saving} onClick={() => void setTaskStatus(task, "paused")}>暂停</button>}
                    {task.status === "paused" && <button className="secondary-button compact" disabled={saving} onClick={() => void setTaskStatus(task, "running")}>继续</button>}
                    {["ready", "running", "waiting_user", "paused"].includes(task.status) && (
                      <button className="primary-button compact" disabled={saving} onClick={() => void assignPluginContext(task)}>
                        <Link2 size={14} />设为插件当前任务
                      </button>
                    )}
                    {["ready", "running", "waiting_user", "paused"].includes(task.status) && (
                      <button className="secondary-button compact danger" disabled={saving} onClick={() => void setTaskStatus(task, "cancelled")}>取消</button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>

      {jobDrawerOpen && (
        <Drawer label={selected ? "岗位档案详情" : "新建岗位档案"} className="drawer-panel detail-drawer-panel job-drawer" onClose={() => setJobDrawerOpen(false)}>
          <div className="drawer-header">
            <div>
              <p className="eyebrow">{selected ? `岗位 #${selected.id}` : "新岗位"}</p>
              <h2>{selected?.job_title || "新建岗位档案"}</h2>
            </div>
            <button className="icon-button" onClick={() => setJobDrawerOpen(false)} aria-label="关闭岗位详情">×</button>
          </div>
          <form className="job-form" onSubmit={saveJob}>
            <label>岗位名称<input value={jobForm.job_title} onChange={(event) => setJobForm({ ...jobForm, job_title: event.target.value })} required /></label>
            <div className="form-grid">
              <label>部门<input value={jobForm.department} onChange={(event) => setJobForm({ ...jobForm, department: event.target.value })} /></label>
              <label>负责人<input value={jobForm.hiring_manager} onChange={(event) => setJobForm({ ...jobForm, hiring_manager: event.target.value })} /></label>
              <label>地点<input value={jobForm.location} onChange={(event) => setJobForm({ ...jobForm, location: event.target.value })} /></label>
              <label>雇佣类型<input value={jobForm.employment_type} onChange={(event) => setJobForm({ ...jobForm, employment_type: event.target.value })} /></label>
              <label>目标人数<input type="number" min={1} value={jobForm.target_hires} onChange={(event) => setJobForm({ ...jobForm, target_hires: Number(event.target.value || 1) })} /></label>
              <label>优先级<select value={jobForm.priority} onChange={(event) => setJobForm({ ...jobForm, priority: event.target.value })}><option value="normal">normal</option><option value="high">high</option><option value="urgent">urgent</option></select></label>
              <label>经验要求<input value={jobForm.experience_requirement} onChange={(event) => setJobForm({ ...jobForm, experience_requirement: event.target.value })} /></label>
              <label>学历要求<input value={jobForm.education_requirement} onChange={(event) => setJobForm({ ...jobForm, education_requirement: event.target.value })} /></label>
            </div>
            <label>招聘截止日期<input value={jobForm.recruitment_deadline} onChange={(event) => setJobForm({ ...jobForm, recruitment_deadline: event.target.value })} /></label>
            <label>JD<textarea value={jobForm.jd_text} onChange={(event) => setJobForm({ ...jobForm, jd_text: event.target.value })} /></label>
            <div className="form-grid">
              <label>必须条件<textarea value={jobForm.must_have} onChange={(event) => setJobForm({ ...jobForm, must_have: event.target.value })} /></label>
              <label>加分条件<textarea value={jobForm.nice_to_have} onChange={(event) => setJobForm({ ...jobForm, nice_to_have: event.target.value })} /></label>
              <label>风险提醒<textarea value={jobForm.risk_flags} onChange={(event) => setJobForm({ ...jobForm, risk_flags: event.target.value })} /></label>
              <label>排除条件<textarea value={jobForm.exclusions} onChange={(event) => setJobForm({ ...jobForm, exclusions: event.target.value })} /></label>
            </div>
            <label>面试核验点<textarea value={jobForm.interview_checks} onChange={(event) => setJobForm({ ...jobForm, interview_checks: event.target.value })} /></label>
            <div className="button-row">
              <button className="primary-button" disabled={saving} type="submit"><BriefcaseBusiness size={15} />保存岗位</button>
              {selected?.status === "draft" && <button type="button" className="secondary-button" disabled={saving} onClick={() => void changeJobStatus(selected, "active")}>开启招聘</button>}
              {selected?.status === "active" && <button type="button" className="secondary-button" disabled={saving} onClick={() => void changeJobStatus(selected, "paused")}>暂停岗位</button>}
              {selected?.status === "paused" && <button type="button" className="secondary-button" disabled={saving} onClick={() => void changeJobStatus(selected, "active")}>恢复岗位</button>}
              {selected && selected.status !== "closed" && <button type="button" className="secondary-button danger" disabled={saving} onClick={() => void changeJobStatus(selected, "closed")}>关闭岗位</button>}
            </div>
          </form>

          {selected && (
            <>
              <section className="detail-section">
                <h3><History size={16} />版本历史</h3>
                <div className="version-list">
                  {versions.map((version) => (
                    <article key={version.version}>
                      <strong>v{version.version}</strong>
                      <span>{formatDate(version.created_at)}</span>
                      <p>{version.snapshot.jd_text || "未提供 JD"}</p>
                    </article>
                  ))}
                </div>
              </section>

              {taskForm && selected.status === "active" && (
                <section className="detail-section">
                  <h3>创建招聘任务</h3>
                  <form className="job-form" onSubmit={createTask}>
                    <label>任务名称<input value={taskForm.name} onChange={(event) => setTaskForm({ ...taskForm, name: event.target.value })} /></label>
                    <div className="form-grid">
                      <label>平台<select value={taskForm.platform} onChange={(event) => setTaskForm({ ...taskForm, platform: event.target.value })}><option value="boss">Boss 直聘</option><option value="liepin">猎聘</option></select></label>
                      <label>目标候选人数<input type="number" min={0} value={taskForm.target_candidates} onChange={(event) => setTaskForm({ ...taskForm, target_candidates: Number(event.target.value || 0) })} /></label>
                    </div>
                    <label>来源页面<input value={taskForm.source_url} onChange={(event) => setTaskForm({ ...taskForm, source_url: event.target.value })} /></label>
                    <p className="inline-help">任务会固定使用岗位 v{taskForm.profile_version}。后续岗位修改不会改变已创建任务的版本。</p>
                    <button className="primary-button" disabled={saving} type="submit"><Plus size={15} />创建任务</button>
                  </form>
                </section>
              )}
            </>
          )}
        </Drawer>
      )}
    </div>
  );
}
