import { useState } from "react";
import { Link2 } from "lucide-react";

import { PluginTaskContext, RecruitmentTaskRow } from "../../api";
import { Drawer } from "./Drawer";
import { StatusBadge } from "./common";
import { statusLabel, toneForStatus } from "./JobEditorDrawer";

type RecruitmentTasksPanelProps = {
  tasks: RecruitmentTaskRow[];
  currentContext: PluginTaskContext | null;
  saving: boolean;
  onStatusChange: (task: RecruitmentTaskRow, status: string) => Promise<void>;
  onAssignContext: (task: RecruitmentTaskRow | null) => Promise<void>;
};

export function RecruitmentTasksPanel({
  tasks,
  currentContext,
  saving,
  onStatusChange,
  onAssignContext,
}: RecruitmentTasksPanelProps) {
  const [cancelTarget, setCancelTarget] = useState<RecruitmentTaskRow | null>(null);
  const [confirmError, setConfirmError] = useState("");
  const [panelError, setPanelError] = useState("");

  const changeStatus = async (task: RecruitmentTaskRow, status: string) => {
    setPanelError("");
    try {
      await onStatusChange(task, status);
    } catch (err) {
      setPanelError(err instanceof Error ? err.message : "任务状态更新失败。");
    }
  };

  const confirmCancel = async () => {
    if (!cancelTarget) return;
    setConfirmError("");
    try {
      await onStatusChange(cancelTarget, "cancelled");
      setCancelTarget(null);
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : "招聘任务取消失败。");
    }
  };

  return (
    <section className="work-panel">
      <div className="section-title">
        <h2>招聘任务</h2>
        <span>{tasks.length} 个任务</span>
      </div>
      <div className="current-context-card">
        <strong>插件当前任务</strong>
        {currentContext ? (
          <>
            <p>
              {currentContext.job_title} · 任务 #{currentContext.recruitment_task_id} · v{currentContext.job_profile_version}
            </p>
            <button className="secondary-button compact" disabled={saving} onClick={() => void onAssignContext(null)}>
              清除插件当前任务
            </button>
          </>
        ) : (
          <p>当前未选择招聘任务；插件仍可进行无岗位采集。</p>
        )}
      </div>
      {tasks.length === 0 ? (
        <div className="table-state">还没有招聘任务。先打开一个招聘中的岗位创建任务。</div>
      ) : (
        <div className="recruitment-list">
          {panelError && <div className="form-error" role="alert">{panelError}</div>}
          {tasks.map((task) => {
            const isCurrent = currentContext?.recruitment_task_id === task.id;
            return (
              <article key={task.id} className={isCurrent ? "recruitment-card is-current" : "recruitment-card"}>
                <div>
                  <strong>{task.name}</strong>
                  <p>{task.role_title} · v{task.profile_version} · {task.platform}</p>
                </div>
                <div className="status-row">
                  <StatusBadge tone={toneForStatus(task.status)}>{statusLabel(task.status)}</StatusBadge>
                  {isCurrent && <StatusBadge tone="success">插件当前任务</StatusBadge>}
                </div>
                <dl>
                  <div><dt>批次</dt><dd>{task.batch_count}</dd></div>
                  <div><dt>候选人</dt><dd>{task.candidate_count}</dd></div>
                  <div><dt>阶段</dt><dd>{task.current_step || "待启动"}</dd></div>
                </dl>
                <div className="button-row">
                  {task.status === "ready" && <button className="secondary-button compact" disabled={saving} onClick={() => void changeStatus(task, "running")}>启动</button>}
                  {task.status === "running" && <button className="secondary-button compact" disabled={saving} onClick={() => void changeStatus(task, "paused")}>暂停</button>}
                  {task.status === "paused" && <button className="secondary-button compact" disabled={saving} onClick={() => void changeStatus(task, "running")}>继续</button>}
                  {task.status === "running" && (
                    <button className="primary-button compact" disabled={saving || isCurrent} onClick={() => void onAssignContext(task)}>
                      <Link2 size={14} />设为插件当前任务
                    </button>
                  )}
                  {["ready", "running", "waiting_user", "paused"].includes(task.status) && (
                    <button className="secondary-button compact danger" disabled={saving} onClick={() => { setConfirmError(""); setCancelTarget(task); }}>取消</button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
      {cancelTarget && (
        <Drawer label="确认取消招聘任务" className="drawer-panel confirm-drawer" onClose={() => setCancelTarget(null)}>
          <div className="drawer-header">
            <div>
              <p className="eyebrow">危险操作</p>
              <h2>取消任务：{cancelTarget.name}</h2>
            </div>
            <button className="icon-button" onClick={() => setCancelTarget(null)} aria-label="关闭确认">×</button>
          </div>
          <p>取消后该招聘任务不能继续作为插件当前采集任务；已有批次和候选人快照不会被删除。</p>
          {confirmError && <div className="form-error" role="alert">{confirmError}</div>}
          <div className="button-row">
            <button className="secondary-button" onClick={() => { setConfirmError(""); setCancelTarget(null); }}>先不取消</button>
            <button
              className="primary-button danger"
              disabled={saving}
              onClick={() => void confirmCancel()}
            >
              确认取消任务
            </button>
          </div>
        </Drawer>
      )}
    </section>
  );
}
