import { FormEvent, useEffect, useState } from "react";
import { BriefcaseBusiness, History, Plus } from "lucide-react";

import { JobProfileDetail, JobProfileVersionRow, RecruitmentTaskRow } from "../../api";
import { Drawer } from "./Drawer";
import { formatDate, StatusBadge } from "./common";

export type JobFormPayload = {
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
  must_have: string[];
  nice_to_have: string[];
  risk_flags: string[];
  exclusions: string[];
  interview_checks: string[];
  evidence_policy: Record<string, unknown>;
};

type JobFormState = Omit<
  JobFormPayload,
  "must_have" | "nice_to_have" | "risk_flags" | "exclusions" | "interview_checks" | "evidence_policy"
> & {
  must_have: string;
  nice_to_have: string;
  risk_flags: string;
  exclusions: string;
  interview_checks: string;
  evidence_policy_text: string;
};

type TaskFormState = {
  name: string;
  role_id: number;
  profile_version: number;
  platform: string;
  source_url: string;
  target_candidates: number;
};

type JobEditorDrawerProps = {
  selected: JobProfileDetail | null;
  versions: JobProfileVersionRow[];
  saving: boolean;
  onClose: () => void;
  onSave: (payload: JobFormPayload, expectedVersion: number | null) => Promise<JobProfileDetail>;
  onStatusChange: (job: JobProfileDetail, status: string) => Promise<void>;
  onCreateTask: (payload: TaskFormState) => Promise<RecruitmentTaskRow>;
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
  evidence_policy_text: "{}",
};

function splitLines(value: string) {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function missing(value: unknown) {
  if (Array.isArray(value)) return value.length ? value.join("、") : "未提供";
  if (value && typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value || "").trim() || "未提供";
}

function formatEvidencePolicy(value: Record<string, unknown> | null | undefined) {
  return JSON.stringify(value && typeof value === "object" ? value : {}, null, 2);
}

function jobToForm(job: JobProfileDetail | null): JobFormState {
  if (!job) return { ...emptyJobForm };
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
    evidence_policy_text: formatEvidencePolicy(job.evidence_policy),
  };
}

function parseEvidencePolicy(value: string): Record<string, unknown> {
  if (!value.trim()) return {};
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("证据要求必须是 JSON object。");
  }
  return parsed as Record<string, unknown>;
}

function toPayload(form: JobFormState): JobFormPayload {
  return {
    job_title: form.job_title,
    department: form.department,
    hiring_manager: form.hiring_manager,
    location: form.location,
    employment_type: form.employment_type,
    target_hires: form.target_hires,
    priority: form.priority,
    status: form.status,
    experience_requirement: form.experience_requirement,
    education_requirement: form.education_requirement,
    recruitment_deadline: form.recruitment_deadline,
    jd_text: form.jd_text,
    must_have: splitLines(form.must_have),
    nice_to_have: splitLines(form.nice_to_have),
    risk_flags: splitLines(form.risk_flags),
    exclusions: splitLines(form.exclusions),
    interview_checks: splitLines(form.interview_checks),
    evidence_policy: parseEvidencePolicy(form.evidence_policy_text),
  };
}

export function statusLabel(status: string) {
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

export function toneForStatus(status: string) {
  if (["active", "running"].includes(status)) return "success";
  if (["ready", "paused", "waiting_user"].includes(status)) return "warning";
  if (["closed", "completed", "cancelled", "failed"].includes(status)) return "muted";
  return "neutral";
}

function defaultTaskForm(job: JobProfileDetail): TaskFormState {
  return {
    name: `${job.job_title} 推荐流`,
    role_id: job.id,
    profile_version: job.version,
    platform: "boss",
    source_url: "https://www.zhipin.com/web/geek/recommend",
    target_candidates: 0,
  };
}

function VersionSnapshot({ version }: { version: JobProfileVersionRow }) {
  const snapshot = version.snapshot;
  return (
    <details className="version-card">
      <summary>
        <strong>v{version.version}</strong>
        <span>{formatDate(version.created_at)}</span>
      </summary>
      <dl className="snapshot-grid">
        <div><dt>岗位名称</dt><dd>{missing(snapshot.job_title)}</dd></div>
        <div><dt>部门</dt><dd>{missing(snapshot.department)}</dd></div>
        <div><dt>负责人</dt><dd>{missing(snapshot.hiring_manager)}</dd></div>
        <div><dt>地点</dt><dd>{missing(snapshot.location)}</dd></div>
        <div><dt>雇佣类型</dt><dd>{missing(snapshot.employment_type)}</dd></div>
        <div><dt>目标人数</dt><dd>{missing(snapshot.target_hires)}</dd></div>
        <div><dt>优先级</dt><dd>{missing(snapshot.priority)}</dd></div>
        <div><dt>状态</dt><dd>{statusLabel(snapshot.status)}</dd></div>
        <div><dt>经验</dt><dd>{missing(snapshot.experience_requirement)}</dd></div>
        <div><dt>学历</dt><dd>{missing(snapshot.education_requirement)}</dd></div>
        <div><dt>截止日期</dt><dd>{missing(snapshot.recruitment_deadline)}</dd></div>
        <div className="wide"><dt>JD</dt><dd>{missing(snapshot.jd_text)}</dd></div>
        <div className="wide"><dt>必须条件</dt><dd>{missing(snapshot.must_have)}</dd></div>
        <div className="wide"><dt>加分条件</dt><dd>{missing(snapshot.nice_to_have)}</dd></div>
        <div className="wide"><dt>风险</dt><dd>{missing(snapshot.risk_flags)}</dd></div>
        <div className="wide"><dt>排除条件</dt><dd>{missing(snapshot.exclusions)}</dd></div>
        <div className="wide"><dt>面试核验点</dt><dd>{missing(snapshot.interview_checks)}</dd></div>
        <div className="wide"><dt>证据要求</dt><dd><pre>{formatEvidencePolicy(snapshot.evidence_policy)}</pre></dd></div>
      </dl>
    </details>
  );
}

export function JobEditorDrawer({
  selected,
  versions,
  saving,
  onClose,
  onSave,
  onStatusChange,
  onCreateTask,
}: JobEditorDrawerProps) {
  const [form, setForm] = useState<JobFormState>(() => jobToForm(selected));
  const [formError, setFormError] = useState("");
  const [taskForm, setTaskForm] = useState<TaskFormState | null>(selected ? defaultTaskForm(selected) : null);
  const [confirmClose, setConfirmClose] = useState(false);

  useEffect(() => {
    setForm(jobToForm(selected));
    setTaskForm(selected ? defaultTaskForm(selected) : null);
    setFormError("");
    setConfirmClose(false);
  }, [selected]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setFormError("");
    try {
      const saved = await onSave(toPayload(form), selected?.version ?? null);
      setForm(jobToForm(saved));
    } catch (err) {
      if (err instanceof SyntaxError || (err instanceof Error && err.message.includes("JSON object"))) {
        setFormError("证据要求必须填写合法 JSON object。");
        return;
      }
      setFormError(err instanceof Error ? err.message : "岗位档案保存失败，请稍后重试。");
    }
  };

  const createTask = async (event: FormEvent) => {
    event.preventDefault();
    if (!taskForm) return;
    setFormError("");
    try {
      await onCreateTask(taskForm);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "招聘任务创建失败。");
    }
  };

  return (
    <>
      <Drawer label={selected ? "岗位档案详情" : "新建岗位档案"} className="drawer-panel detail-drawer-panel job-drawer" onClose={onClose}>
        <div className="drawer-header">
          <div>
            <p className="eyebrow">{selected ? `岗位 #${selected.id}` : "新岗位"}</p>
            <h2>{selected?.job_title || "新建岗位档案"}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭岗位详情">×</button>
        </div>
        <form className="job-form" onSubmit={save}>
          <label>岗位名称<input value={form.job_title} onChange={(event) => setForm({ ...form, job_title: event.target.value })} required /></label>
          <div className="form-grid">
            <label>部门<input value={form.department} onChange={(event) => setForm({ ...form, department: event.target.value })} /></label>
            <label>负责人<input value={form.hiring_manager} onChange={(event) => setForm({ ...form, hiring_manager: event.target.value })} /></label>
            <label>地点<input value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} /></label>
            <label>雇佣类型<input value={form.employment_type} onChange={(event) => setForm({ ...form, employment_type: event.target.value })} /></label>
            <label>目标人数<input type="number" min={1} value={form.target_hires} onChange={(event) => setForm({ ...form, target_hires: Number(event.target.value || 1) })} /></label>
            <label>优先级<select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value })}><option value="normal">normal</option><option value="high">high</option><option value="urgent">urgent</option></select></label>
            <label>经验要求<input value={form.experience_requirement} onChange={(event) => setForm({ ...form, experience_requirement: event.target.value })} /></label>
            <label>学历要求<input value={form.education_requirement} onChange={(event) => setForm({ ...form, education_requirement: event.target.value })} /></label>
          </div>
          <label>招聘截止日期<input value={form.recruitment_deadline} onChange={(event) => setForm({ ...form, recruitment_deadline: event.target.value })} /></label>
          <label>JD<textarea value={form.jd_text} onChange={(event) => setForm({ ...form, jd_text: event.target.value })} /></label>
          <div className="form-grid">
            <label>必须条件<textarea value={form.must_have} onChange={(event) => setForm({ ...form, must_have: event.target.value })} /></label>
            <label>加分条件<textarea value={form.nice_to_have} onChange={(event) => setForm({ ...form, nice_to_have: event.target.value })} /></label>
            <label>风险提醒<textarea value={form.risk_flags} onChange={(event) => setForm({ ...form, risk_flags: event.target.value })} /></label>
            <label>排除条件<textarea value={form.exclusions} onChange={(event) => setForm({ ...form, exclusions: event.target.value })} /></label>
          </div>
          <label>面试核验点<textarea value={form.interview_checks} onChange={(event) => setForm({ ...form, interview_checks: event.target.value })} /></label>
          <label>证据要求 JSON<textarea value={form.evidence_policy_text} onChange={(event) => setForm({ ...form, evidence_policy_text: event.target.value })} /></label>
          {formError && <div className="form-error" role="alert">{formError}</div>}
          <div className="button-row">
            <button className="primary-button" disabled={saving} type="submit"><BriefcaseBusiness size={15} />保存岗位</button>
            {selected?.status === "draft" && <button type="button" className="secondary-button" disabled={saving} onClick={() => void onStatusChange(selected, "active")}>开启招聘</button>}
            {selected?.status === "active" && <button type="button" className="secondary-button" disabled={saving} onClick={() => void onStatusChange(selected, "paused")}>暂停岗位</button>}
            {selected?.status === "paused" && <button type="button" className="secondary-button" disabled={saving} onClick={() => void onStatusChange(selected, "active")}>恢复岗位</button>}
            {selected && selected.status !== "closed" && <button type="button" className="secondary-button danger" disabled={saving} onClick={() => setConfirmClose(true)}>关闭岗位</button>}
          </div>
        </form>

        {selected && (
          <>
            <section className="detail-section">
              <h3><History size={16} />版本历史</h3>
              <div className="version-list">
                {versions.map((version) => <VersionSnapshot key={version.version} version={version} />)}
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
      {confirmClose && selected && (
        <Drawer label="确认关闭岗位" className="drawer-panel confirm-drawer" onClose={() => setConfirmClose(false)}>
          <div className="drawer-header">
            <div>
              <p className="eyebrow">危险操作</p>
              <h2>关闭岗位：{selected.job_title}</h2>
            </div>
            <button className="icon-button" onClick={() => setConfirmClose(false)} aria-label="关闭确认">×</button>
          </div>
          <p>关闭岗位后，该岗位下未终结的招聘任务会统一取消，插件当前任务也会失效。这个操作不可直接撤销。</p>
          <div className="button-row">
            <button className="secondary-button" onClick={() => setConfirmClose(false)}>先不关闭</button>
            <button
              className="primary-button danger"
              disabled={saving}
              onClick={() => void onStatusChange(selected, "closed").then(() => setConfirmClose(false)).catch((err: unknown) => {
                setFormError(err instanceof Error ? err.message : "岗位关闭失败。");
              })}
            >
              确认关闭岗位
            </button>
          </div>
        </Drawer>
      )}
    </>
  );
}
