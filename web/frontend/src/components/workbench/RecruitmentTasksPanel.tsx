import { useCallback, useEffect, useRef, useState } from "react";
import { BarChart3, Download, Link2, Search, Upload } from "lucide-react";

import {
  ApiRequestError,
  ExternalRatingImportResult,
  ExternalRatingPreviewResult,
  ExternalRatingPreviewRow,
  KeywordRules,
  KeywordRulesResponse,
  PluginTaskContext,
  RecruitmentTaskProgress,
  RecruitmentTaskRow,
  downloadBatchMarkdown,
  requestJson,
} from "../../api";
import { Drawer } from "./Drawer";
import { formatDate, RatingBadge, RefreshButton, StatusBadge, TableState } from "./common";
import { statusLabel, toneForStatus } from "./JobEditorDrawer";

type RecruitmentTasksPanelProps = {
  tasks: RecruitmentTaskRow[];
  currentContext: PluginTaskContext | null;
  saving: boolean;
  onOpenTaskCandidates: (taskId: number) => void;
  onOpenTaskBatches: (taskId: number) => void;
  onOpenBatch: (batchId: number) => void;
  onStatusChange: (task: RecruitmentTaskRow, status: string) => Promise<void>;
  onAssignContext: (task: RecruitmentTaskRow | null) => Promise<void>;
  onPreviewRatings: (task: RecruitmentTaskRow, text: string) => Promise<ExternalRatingPreviewResult>;
  onImportRatings: (task: RecruitmentTaskRow, text: string, rows: ExternalRatingPreviewRow[]) => Promise<ExternalRatingImportResult>;
  onLoadKeywordRules: (task: RecruitmentTaskRow) => Promise<KeywordRulesResponse>;
  onSaveKeywordRules: (task: RecruitmentTaskRow, rules: KeywordRules, expectedVersion: number) => Promise<KeywordRulesResponse>;
};

export function RecruitmentTasksPanel({
  tasks,
  currentContext,
  saving,
  onOpenTaskCandidates,
  onOpenTaskBatches,
  onOpenBatch,
  onStatusChange,
  onAssignContext,
  onPreviewRatings,
  onImportRatings,
  onLoadKeywordRules,
  onSaveKeywordRules,
}: RecruitmentTasksPanelProps) {
  const [cancelTarget, setCancelTarget] = useState<RecruitmentTaskRow | null>(null);
  const [importTarget, setImportTarget] = useState<RecruitmentTaskRow | null>(null);
  const [confirmError, setConfirmError] = useState("");
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState("");
  const [previewRows, setPreviewRows] = useState<ExternalRatingPreviewRow[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [selectedRatings, setSelectedRatings] = useState<Record<number, string>>({});
  const [importResult, setImportResult] = useState<ExternalRatingImportResult | null>(null);
  const [keywordTarget, setKeywordTarget] = useState<RecruitmentTaskRow | null>(null);
  const [keywordVersion, setKeywordVersion] = useState(0);
  const [keywordForm, setKeywordForm] = useState<KeywordRulesText>(() => emptyKeywordRulesText());
  const [keywordLoading, setKeywordLoading] = useState(false);
  const [keywordError, setKeywordError] = useState("");
  const [keywordSaved, setKeywordSaved] = useState("");
  const [progressTarget, setProgressTarget] = useState<RecruitmentTaskRow | null>(null);
  const [progress, setProgress] = useState<RecruitmentTaskProgress | null>(null);
  const [progressLoading, setProgressLoading] = useState(false);
  const [progressError, setProgressError] = useState("");
  const [progressRefresh, setProgressRefresh] = useState(0);
  const [exportingBatchId, setExportingBatchId] = useState<number | null>(null);
  const [panelError, setPanelError] = useState("");
  const latestProgressRequest = useRef(0);

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
      if (progressTarget?.id === cancelTarget.id) setProgressRefresh((value) => value + 1);
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : "招聘任务取消失败。");
    }
  };

  const loadProgress = useCallback((task: RecruitmentTaskRow) => {
    const requestId = ++latestProgressRequest.current;
    setProgressLoading(true);
    setProgressError("");
    void requestJson<RecruitmentTaskProgress>(`/api/recruitment-tasks/${task.id}/progress`)
      .then((payload) => {
        if (latestProgressRequest.current !== requestId) return;
        setProgress(payload);
        setProgressError("");
      })
      .catch((err: unknown) => {
        if (latestProgressRequest.current !== requestId) return;
        setProgress(null);
        setProgressError(err instanceof ApiRequestError ? err.message : "任务进度读取失败，请稍后重试。");
      })
      .finally(() => {
        if (latestProgressRequest.current === requestId) setProgressLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!progressTarget) {
      setProgress(null);
      setProgressError("");
      return;
    }
    loadProgress(progressTarget);
  }, [loadProgress, progressRefresh, progressTarget]);

  useEffect(() => {
    if (!progressTarget || progress?.task_status !== "running") return undefined;
    const timer = window.setInterval(() => setProgressRefresh((value) => value + 1), 10000);
    const onFocus = () => setProgressRefresh((value) => value + 1);
    const onVisibility = () => {
      if (document.visibilityState === "visible") setProgressRefresh((value) => value + 1);
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [progress?.task_status, progressTarget]);

  const changeProgressStatus = async (status: string) => {
    if (!progressTarget) return;
    await changeStatus(progressTarget, status);
    setProgressRefresh((value) => value + 1);
  };

  const exportProgressBatch = async (batchId: number) => {
    if (exportingBatchId !== null) return;
    setExportingBatchId(batchId);
    setProgressError("");
    try {
      await downloadBatchMarkdown(batchId);
    } catch (err) {
      setProgressError(err instanceof ApiRequestError ? err.message : "Markdown 导出失败，请稍后重试。");
    } finally {
      setExportingBatchId((current) => (current === batchId ? null : current));
    }
  };

  useEffect(() => {
    if (!importTarget || !importText.trim()) {
      setPreviewRows([]);
      setPreviewLoading(false);
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setPreviewLoading(true);
      void onPreviewRatings(importTarget, importText)
        .then((payload) => {
          if (cancelled) return;
          setPreviewRows(payload.rows);
          setImportError("");
        })
        .catch((err) => {
          if (cancelled) return;
          setPreviewRows([]);
          setImportError(err instanceof Error ? err.message : "外部评级预览失败，请检查名单格式。");
        })
        .finally(() => {
          if (!cancelled) setPreviewLoading(false);
        });
    }, 120);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [importTarget, importText, onPreviewRatings]);

  const resolvedPreviewRows = previewRows.map((row) => ({
    ...row,
    rating: selectedRatings[row.line] || row.rating,
  }));
  const unresolvedRows = resolvedPreviewRows.filter(
    (row) => ["needs_confirmation", "invalid"].includes(row.rating_status) && !isValidRating(row.rating),
  );
  const previewCounts = resolvedPreviewRows.reduce(
    (acc, row) => {
      acc.total += 1;
      if (isValidRating(row.rating)) acc.valid += 1;
      else acc.invalid += 1;
      return acc;
    },
    { total: 0, valid: 0, invalid: 0 },
  );

  const confirmImport = async () => {
    if (!importTarget || saving || unresolvedRows.length > 0 || previewCounts.valid === 0) return;
    setImportError("");
    setImportResult(null);
    try {
      const result = await onImportRatings(importTarget, importText, resolvedPreviewRows);
      setImportResult(result);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "外部评级导入失败，请检查名单后重试。");
    }
  };

  const openKeywordRules = async (task: RecruitmentTaskRow) => {
    setKeywordTarget(task);
    setKeywordVersion(task.profile_version);
    setKeywordForm(emptyKeywordRulesText());
    setKeywordError("");
    setKeywordSaved("");
    setKeywordLoading(true);
    try {
      const payload = await onLoadKeywordRules(task);
      setKeywordVersion(payload.job_profile_version);
      setKeywordForm(keywordRulesToText(payload.keyword_rules));
    } catch (err) {
      setKeywordError(err instanceof Error ? err.message : "关键词筛选规则读取失败，请稍后重试。");
    } finally {
      setKeywordLoading(false);
    }
  };

  const keywordRules = keywordTextToRules(keywordForm);
  const keywordCounts = Object.values(keywordRules).reduce((total, values) => total + values.length, 0);

  const confirmKeywordSave = async () => {
    if (!keywordTarget || saving) return;
    setKeywordError("");
    setKeywordSaved("");
    try {
      const result = await onSaveKeywordRules(keywordTarget, keywordRules, keywordVersion);
      setKeywordVersion(result.job_profile_version);
      setKeywordForm(keywordRulesToText(result.keyword_rules));
      setKeywordSaved(`已保存 ${Object.values(result.keyword_rules).reduce((total, values) => total + values.length, 0)} 个关键词。`);
    } catch (err) {
      setKeywordError(err instanceof Error ? err.message : "关键词筛选规则保存失败，请稍后重试。");
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
                  <button
                    className="secondary-button compact"
                    aria-label={`查看 ${task.name} 进度`}
                    onClick={() => { setProgressTarget(task); setProgress(null); setProgressError(""); }}
                  >
                    <BarChart3 size={14} />查看进度
                  </button>
                  {task.status === "ready" && <button className="secondary-button compact" disabled={saving} onClick={() => void changeStatus(task, "running")}>启动</button>}
                  {task.status === "running" && <button className="secondary-button compact" disabled={saving} onClick={() => void changeStatus(task, "paused")}>暂停</button>}
                  {task.status === "paused" && <button className="secondary-button compact" disabled={saving} onClick={() => void changeStatus(task, "running")}>继续</button>}
                  {task.status === "running" && (
                    <button className="primary-button compact" disabled={saving || isCurrent} onClick={() => void onAssignContext(task)}>
                      <Link2 size={14} />设为插件当前任务
                    </button>
                  )}
                  {task.status === "running" && (
                    <button className="secondary-button compact" disabled={saving} onClick={() => void openKeywordRules(task)}>
                      <Search size={14} />关键词筛选规则
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
                        setPreviewRows([]);
                        setSelectedRatings({});
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
      {progressTarget && (
        <Drawer label="招聘任务进度" className="drawer-panel detail-drawer-panel task-progress-drawer" onClose={() => setProgressTarget(null)}>
          <div className="drawer-header">
            <div>
              <p className="eyebrow">任务进度</p>
              <h2>{progressTarget.name}</h2>
              <p>采集规模、外部评级覆盖和安全操作汇总；不包含 AI、沟通或附件能力。</p>
            </div>
            <button className="icon-button" onClick={() => setProgressTarget(null)} aria-label="关闭任务进度">×</button>
          </div>
          <TableState loading={progressLoading} error={progressError} empty={!progress && !progressLoading && !progressError} emptyText="还没有任务进度数据。" />
          {progress && (
            <div className="task-progress-layout">
              <section className="detail-section-card">
                <div className="detail-section-headline">
                  <span className="eyebrow">任务摘要</span>
                  <h3>{progress.task_name}</h3>
                </div>
                <div className="detail-chip-row">
                  <StatusBadge tone={toneForStatus(progress.task_status)}>{statusLabel(progress.task_status)}</StatusBadge>
                  {progress.is_plugin_context ? <StatusBadge tone="success">插件正在使用</StatusBadge> : <StatusBadge tone="muted">不是插件当前任务</StatusBadge>}
                  <StatusBadge>{progress.job_title || "未提供岗位"}</StatusBadge>
                </div>
                <dl className="detail-summary-grid">
                  <div><dt>岗位版本</dt><dd className="numeric">v{progress.job_profile_version}</dd></div>
                  <div><dt>目标候选人</dt><dd className="numeric">{progress.target_count}</dd></div>
                  <div><dt>首次采集</dt><dd className="numeric">{formatDate(progress.first_capture_time)}</dd></div>
                  <div><dt>最近采集</dt><dd className="numeric">{formatDate(progress.latest_capture_time)}</dd></div>
                </dl>
              </section>
              <section className="summary-strip five">
                <div><span>批次数</span><strong>{progress.batch_count}</strong></div>
                <div><span>批次记录</span><strong>{progress.batch_item_count}</strong></div>
                <div><span>唯一候选人</span><strong>{progress.unique_candidate_count}</strong></div>
                <div><span>新增</span><strong>{progress.total_added}</strong></div>
                <div><span>失败</span><strong>{progress.total_failed}</strong></div>
              </section>
              <section className="summary-strip five">
                <div><span>更新</span><strong>{progress.total_updated}</strong></div>
                <div><span>跳过</span><strong>{progress.total_skipped}</strong></div>
                <div><span>接收记录</span><strong>{progress.total_received}</strong></div>
                <div><span>已评级</span><strong>{progress.rated_candidate_count}</strong></div>
                <div><span>未评级</span><strong>{progress.unrated_candidate_count}</strong></div>
              </section>
              <section className="detail-section-card">
                <div className="detail-section-headline">
                  <span className="eyebrow">外部评级覆盖</span>
                  <h3>UR / SSR / SR / R / N</h3>
                </div>
                <div className="rating-distribution">
                  {(["UR", "SSR", "SR", "R", "N"] as const).map((rating) => (
                    <div key={rating}>
                      <RatingBadge rating={rating} />
                      <strong className="numeric">{progress.rating_counts[rating]}</strong>
                    </div>
                  ))}
                </div>
              </section>
              <section className="detail-section-card">
                <div className="detail-section-headline detail-section-headline-row">
                  <div>
                    <span className="eyebrow">最近批次</span>
                    <h3>不可变采集快照</h3>
                  </div>
                  <RefreshButton onClick={() => setProgressRefresh((value) => value + 1)} label="刷新任务进度" />
                </div>
                {progress.recent_batches.length === 0 ? (
                  <div className="table-state compact-empty-state">这个任务还没有采集批次。</div>
                ) : (
                  <div className="table-scroll">
                    <table className="workbench-table compact-table">
                      <thead>
                        <tr><th>批次</th><th>时间</th><th>平台</th><th>状态</th><th>接收</th><th>新增</th><th>更新</th><th>跳过</th><th>失败</th><th>操作</th></tr>
                      </thead>
                      <tbody>
                        {progress.recent_batches.map((batch) => (
                          <tr key={batch.batch_id}>
                            <td className="numeric">#{batch.batch_id}</td>
                            <td className="numeric">{formatDate(batch.start_time)}</td>
                            <td><StatusBadge>{batch.source_platform || "unknown"}</StatusBadge></td>
                            <td><StatusBadge tone={batch.status === "completed" ? "success" : batch.status === "partial" ? "warning" : "muted"}>{batch.status}</StatusBadge></td>
                            <td>{batch.received}</td>
                            <td>{batch.added}</td>
                            <td>{batch.updated}</td>
                            <td>{batch.skipped}</td>
                            <td>{batch.failed}</td>
                            <td>
                              <div className="row-actions">
                                <button className="secondary-button compact" onClick={() => { setProgressTarget(null); onOpenBatch(batch.batch_id); }}>打开批次</button>
                                <button className="secondary-button compact" disabled={exportingBatchId === batch.batch_id} onClick={() => void exportProgressBatch(batch.batch_id)}>
                                  <Download size={14} />{exportingBatchId === batch.batch_id ? "导出中…" : "导出 Markdown"}
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
              <section className="detail-section-card">
                <div className="detail-section-headline">
                  <span className="eyebrow">安全操作</span>
                  <h3>当前可执行</h3>
                </div>
                <div className="button-row">
                  {progress.task_status === "ready" && <button className="secondary-button" disabled={saving} onClick={() => void changeProgressStatus("running")}>启动任务</button>}
                  {progress.task_status === "running" && <button className="secondary-button" disabled={saving} onClick={() => void changeProgressStatus("paused")}>暂停任务</button>}
                  {progress.task_status === "paused" && <button className="secondary-button" disabled={saving} onClick={() => void changeProgressStatus("running")}>继续任务</button>}
                  {["running", "paused"].includes(progress.task_status) && <button className="secondary-button" disabled={saving} onClick={() => void changeProgressStatus("completed")}>完成任务</button>}
                  {progress.task_status === "running" && (
                    <button
                      className="primary-button"
                      disabled={saving || progress.is_plugin_context}
                      onClick={() => void onAssignContext(progressTarget).then(() => setProgressRefresh((value) => value + 1))}
                    >
                      设为插件当前任务
                    </button>
                  )}
                  {["ready", "running", "waiting_user", "paused"].includes(progress.task_status) && (
                    <button className="secondary-button danger" disabled={saving} onClick={() => { setConfirmError(""); setCancelTarget(progressTarget); }}>取消任务</button>
                  )}
                  <button className="secondary-button" onClick={() => { setProgressTarget(null); onOpenTaskCandidates(progress.task_id); }}>查看本任务候选人</button>
                  <button className="secondary-button" onClick={() => { setProgressTarget(null); onOpenTaskBatches(progress.task_id); }}>查看本任务批次</button>
                </div>
                <p className="muted">AI 初筛、自动沟通、联系方式和附件归档仍属于后续阶段，本页不提供可点击入口。</p>
              </section>
            </div>
          )}
        </Drawer>
      )}
      {keywordTarget && (
        <Drawer label="关键词筛选规则" className="drawer-panel detail-drawer-panel" onClose={() => setKeywordTarget(null)}>
          <div className="drawer-header">
            <div>
              <p className="eyebrow">关键词筛选</p>
              <h2>任务：{keywordTarget.name}</h2>
              <p>这些规则只用于页面标记和辅助筛选，不调用 AI，也不会自动操作候选人。</p>
            </div>
            <button className="icon-button" onClick={() => setKeywordTarget(null)} aria-label="关闭关键词筛选规则">×</button>
          </div>
          {keywordLoading ? (
            <div className="table-state">正在读取关键词筛选规则...</div>
          ) : (
            <>
              <div className="keyword-rule-grid">
                <label>必须关键词<textarea rows={5} value={keywordForm.must} onChange={(event) => setKeywordForm({ ...keywordForm, must: event.target.value })} placeholder="Python&#10;量化&#10;风控" /></label>
                <label>加分关键词<textarea rows={5} value={keywordForm.plus} onChange={(event) => setKeywordForm({ ...keywordForm, plus: event.target.value })} placeholder="React&#10;数据分析" /></label>
                <label>风险关键词<textarea rows={5} value={keywordForm.risk} onChange={(event) => setKeywordForm({ ...keywordForm, risk: event.target.value })} placeholder="外包&#10;频繁跳槽" /></label>
                <label>关注关键词<textarea rows={5} value={keywordForm.note} onChange={(event) => setKeywordForm({ ...keywordForm, note: event.target.value })} placeholder="可迁移&#10;英文沟通" /></label>
              </div>
              <div className="rating-import-summary">
                <span>必须 {keywordRules.must.length}</span>
                <span>加分 {keywordRules.plus.length}</span>
                <span>风险 {keywordRules.risk.length}</span>
                <span>关注 {keywordRules.note.length}</span>
                <span>合计 {keywordCounts}</span>
              </div>
              {keywordCounts > 0 && (
                <div className="keyword-preview-list">
                  {(["must", "plus", "risk", "note"] as const).map((group) => (
                    <div key={group}>
                      <strong>{keywordGroupLabel(group)}</strong>
                      <p>{keywordRules[group].join("、") || "未设置"}</p>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
          {keywordError && <div className="form-error" role="alert">{keywordError}</div>}
          {keywordSaved && <div className="rating-import-result" role="status">{keywordSaved}</div>}
          <div className="button-row">
            <button className="secondary-button" onClick={() => setKeywordTarget(null)}>关闭</button>
            <button className="primary-button" disabled={saving || keywordLoading} onClick={() => void confirmKeywordSave()}>
              保存关键词筛选规则
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
              <p>支持 Markdown 表格、CSV、TSV 或 name,rating；不会调用 AI。</p>
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
                setSelectedRatings({});
                setImportResult(null);
              }}
              placeholder={"| 姓名 | 评级 | 方向 | 理由 |\n| --- | --- | --- | --- |\n| 测试甲 | 强SR | Alpha | 外部评级理由 |"}
            />
          </label>
          <div className="rating-import-summary">
            <span>{previewLoading ? "正在解析..." : `解析 ${previewCounts.total} 行`}</span>
            <span>可导入 {previewCounts.valid} 行</span>
            <span>格式待修正 {previewCounts.invalid} 行</span>
          </div>
          {unresolvedRows.length > 0 && (
            <div className="form-error" role="alert">还有 {unresolvedRows.length} 行需要人工选择标准评级。</div>
          )}
          {resolvedPreviewRows.length > 0 && (
            <div className="table-scroll">
              <table className="workbench-table compact-table">
                <thead><tr><th>行号</th><th>候选人</th><th>原始评级</th><th>标准评级</th><th>解析状态</th><th>方向</th><th>理由</th></tr></thead>
                <tbody>
                  {resolvedPreviewRows.slice(0, 20).map((row) => (
                    <tr key={`${row.line}-${row.name}-${row.original_rating}`}>
                      <td className="mono">#{row.line}</td>
                      <td>{row.name || "未提供"}</td>
                      <td>{row.original_rating || "未提供"}</td>
                      <td>
                        <select
                          aria-label={`第 ${row.line} 行标准评级`}
                          value={row.rating}
                          onChange={(event) => setSelectedRatings({ ...selectedRatings, [row.line]: event.target.value })}
                        >
                          <option value="">请选择</option>
                          {["UR", "SSR", "SR", "R", "N"].map((rating) => (
                            <option key={rating} value={rating}>{rating}</option>
                          ))}
                        </select>
                        {isValidRating(row.rating) && <RatingBadge rating={row.rating} />}
                      </td>
                      <td>{ratingPreviewStatusLabel(row.rating_status)}</td>
                      <td>{row.track || "未提供"}</td>
                      <td>{row.reason || "未提供"}</td>
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
            <button className="primary-button" disabled={saving || previewLoading || previewCounts.valid === 0 || unresolvedRows.length > 0} onClick={() => void confirmImport()}>
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

type KeywordRulesText = Record<"must" | "plus" | "risk" | "note", string>;

function emptyKeywordRulesText(): KeywordRulesText {
  return { must: "", plus: "", risk: "", note: "" };
}

function normalizeKeywordLines(text: string) {
  const seen = new Set<string>();
  const values: string[] = [];
  for (const item of text.replace(/,/g, "\n").split(/\r?\n/)) {
    const keyword = item.trim();
    if (!keyword) continue;
    const key = keyword.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    values.push(keyword);
  }
  return values;
}

function keywordTextToRules(text: KeywordRulesText): KeywordRules {
  return {
    must: normalizeKeywordLines(text.must),
    plus: normalizeKeywordLines(text.plus),
    risk: normalizeKeywordLines(text.risk),
    note: normalizeKeywordLines(text.note),
  };
}

function keywordRulesToText(rules: KeywordRules): KeywordRulesText {
  return {
    must: (rules.must || []).join("\n"),
    plus: (rules.plus || []).join("\n"),
    risk: (rules.risk || []).join("\n"),
    note: (rules.note || []).join("\n"),
  };
}

function keywordGroupLabel(group: "must" | "plus" | "risk" | "note") {
  return {
    must: "必须",
    plus: "加分",
    risk: "风险",
    note: "关注",
  }[group];
}

function ratingStatusLabel(status: string) {
  if (status === "imported") return "已导入";
  if (status === "unmatched") return "未匹配";
  if (status === "ambiguous") return "同名歧义";
  if (status === "invalid") return "无效";
  return status;
}

function ratingPreviewStatusLabel(status: string) {
  if (status === "exact") return "已识别";
  if (status === "normalized") return "已自动归一";
  if (status === "needs_confirmation") return "需要确认";
  if (status === "invalid") return "无法识别";
  return "待处理";
}
