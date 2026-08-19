import { useState } from "react";
import { Link2, Upload } from "lucide-react";

import { ExternalRatingImportResult, PluginTaskContext, RecruitmentTaskRow } from "../../api";
import { Drawer } from "./Drawer";
import { RatingBadge, StatusBadge } from "./common";
import { statusLabel, toneForStatus } from "./JobEditorDrawer";

type RecruitmentTasksPanelProps = {
  tasks: RecruitmentTaskRow[];
  currentContext: PluginTaskContext | null;
  saving: boolean;
  onStatusChange: (task: RecruitmentTaskRow, status: string) => Promise<void>;
  onAssignContext: (task: RecruitmentTaskRow | null) => Promise<void>;
  onImportRatings: (task: RecruitmentTaskRow, text: string) => Promise<ExternalRatingImportResult>;
};

export function RecruitmentTasksPanel({
  tasks,
  currentContext,
  saving,
  onStatusChange,
  onAssignContext,
  onImportRatings,
}: RecruitmentTasksPanelProps) {
  const [cancelTarget, setCancelTarget] = useState<RecruitmentTaskRow | null>(null);
  const [importTarget, setImportTarget] = useState<RecruitmentTaskRow | null>(null);
  const [confirmError, setConfirmError] = useState("");
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState("");
  const [importResult, setImportResult] = useState<ExternalRatingImportResult | null>(null);
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

  const previewRows = parseRatingPreview(importText);
  const previewCounts = previewRows.reduce(
    (acc, row) => {
      acc.total += 1;
      if (isValidRating(row.rating)) acc.valid += 1;
      else acc.invalid += 1;
      return acc;
    },
    { total: 0, valid: 0, invalid: 0 },
  );

  const confirmImport = async () => {
    if (!importTarget || saving) return;
    setImportError("");
    setImportResult(null);
    try {
      const result = await onImportRatings(importTarget, importText);
      setImportResult(result);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "外部评级导入失败，请检查名单后重试。");
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
                  {task.status === "running" && (
                    <button
                      className="secondary-button compact"
                      disabled={saving}
                      onClick={() => {
                        setImportTarget(task);
                        setImportText("");
                        setImportError("");
                        setImportResult(null);
                      }}
                    >
                      <Upload size={14} />导入外部评级
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
      {importTarget && (
        <Drawer label="导入外部评级" className="drawer-panel detail-drawer-panel" onClose={() => setImportTarget(null)}>
          <div className="drawer-header">
            <div>
              <p className="eyebrow">外部评级</p>
              <h2>导入到任务：{importTarget.name}</h2>
              <p>支持 CSV / TSV / 粘贴文本，至少包含候选人姓名和评级；不会调用 AI。</p>
            </div>
            <button className="icon-button" onClick={() => setImportTarget(null)} aria-label="关闭外部评级导入">×</button>
          </div>
          <label className="full-width-label">
            粘贴评级名单
            <textarea
              rows={9}
              value={importText}
              onChange={(event) => {
                setImportText(event.target.value);
                setImportError("");
                setImportResult(null);
              }}
              placeholder={"name,rating\n张三,SSR\n李四,SR"}
            />
          </label>
          <div className="rating-import-summary">
            <span>解析 {previewCounts.total} 行</span>
            <span>可导入 {previewCounts.valid} 行</span>
            <span>格式待修正 {previewCounts.invalid} 行</span>
          </div>
          {previewRows.length > 0 && (
            <div className="table-scroll">
              <table className="workbench-table compact-table">
                <thead><tr><th>候选人</th><th>外部评级</th><th>预览状态</th></tr></thead>
                <tbody>
                  {previewRows.slice(0, 8).map((row, index) => (
                    <tr key={`${row.name}-${row.rating}-${index}`}>
                      <td>{row.name || "未提供"}</td>
                      <td><RatingBadge rating={row.rating} /></td>
                      <td>{isValidRating(row.rating) ? "等待导入" : "评级无效"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {importError && <div className="form-error" role="alert">{importError}</div>}
          {importResult && (
            <div className="rating-import-result" role="status">
              <strong>导入完成</strong>
              <span>成功 {importResult.imported}</span>
              <span>未匹配 {importResult.unmatched}</span>
              <span>歧义 {importResult.ambiguous}</span>
              <span>无效 {importResult.invalid}</span>
            </div>
          )}
          {importResult?.rows?.length ? (
            <div className="table-scroll">
              <table className="workbench-table compact-table">
                <thead><tr><th>候选人</th><th>评级</th><th>结果</th><th>说明</th></tr></thead>
                <tbody>
                  {importResult.rows.map((row) => (
                    <tr key={`${row.line}-${row.name}-${row.rating}`}>
                      <td>{row.name || (row.candidate_id ? `#${row.candidate_id}` : "未提供")}</td>
                      <td><RatingBadge rating={row.rating} /></td>
                      <td>{ratingStatusLabel(row.status)}</td>
                      <td>{row.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <div className="button-row">
            <button className="secondary-button" onClick={() => setImportTarget(null)}>关闭</button>
            <button className="primary-button" disabled={saving || previewCounts.valid === 0} onClick={() => void confirmImport()}>
              确认导入外部评级
            </button>
          </div>
        </Drawer>
      )}
    </section>
  );
}

function isValidRating(value: string) {
  return ["UR", "SSR", "SR", "R", "N"].includes(String(value || "").trim().toUpperCase());
}

function parseRatingPreview(text: string) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.split(/\t|,/).map((value) => value.trim());
      if (index === 0 && parts.some((part) => /^(name|candidate_name|rating)$/i.test(part))) {
        return null;
      }
      return { name: parts[0] || "", rating: (parts[1] || "").toUpperCase() };
    })
    .filter((row): row is { name: string; rating: string } => row !== null);
}

function ratingStatusLabel(status: string) {
  if (status === "imported") return "已导入";
  if (status === "unmatched") return "未匹配";
  if (status === "ambiguous") return "同名歧义";
  if (status === "invalid") return "无效";
  return status;
}
