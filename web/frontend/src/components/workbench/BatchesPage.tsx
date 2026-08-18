import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Download, X } from "lucide-react";
import { ApiRequestError, BatchCandidateRow, CaptureBatchRow, downloadBatchMarkdown, PagedResponse, requestJson } from "../../api";
import { Drawer } from "./Drawer";
import { formatDate, Loadable, Pager, RefreshButton, StatusBadge, TableState } from "./common";
import { SnapshotTextBlock } from "./SnapshotTextBlock";

const emptyBatches: Loadable<CaptureBatchRow> = { rows: [], total: 0, page: 1, page_size: 20, loading: false, error: "" };
const emptyCandidates: Loadable<BatchCandidateRow> = { rows: [], total: 0, page: 1, page_size: 50, loading: false, error: "" };
type BatchPageResponse = PagedResponse<CaptureBatchRow> & { today_summary?: { received: number; added: number } };

type BatchStatusFilter = "" | "completed" | "partial" | "failed";

export function BatchesPage({
  active = true,
  initialBatchId = null,
  initialReturnView = null,
  onInitialBatchConsumed,
  onReturnFromInitialBatch,
}: {
  active?: boolean;
  initialBatchId?: number | null;
  initialReturnView?: "home" | "candidates" | "batches" | "settings" | null;
  onInitialBatchConsumed?: () => void;
  onReturnFromInitialBatch?: () => void;
}) {
  const [page, setPage] = useState(1);
  const [platform, setPlatform] = useState("");
  const [statusFilter, setStatusFilter] = useState<BatchStatusFilter>("");
  const [failedOnly, setFailedOnly] = useState(false);
  const [todayOnly, setTodayOnly] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState(emptyBatches);
  const [selected, setSelected] = useState<CaptureBatchRow | null>(null);
  const [batchLookup, setBatchLookup] = useState("");
  const [lookupLoading, setLookupLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [todaySummary, setTodaySummary] = useState({ received: 0, added: 0 });
  const [exportingBatchId, setExportingBatchId] = useState<number | null>(null);
  const [openedFromInitialBatch, setOpenedFromInitialBatch] = useState(false);
  const latest = useRef(0);
  const directRequest = useRef(0);
  const knownLatest = useRef(0);
  const noticeTimer = useRef<number | null>(null);

  const load = useCallback(() => setRefresh((value) => value + 1), []);

  const showNotice = useCallback((message: string) => {
    if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current);
    setNotice(message);
    noticeTimer.current = window.setTimeout(() => {
      noticeTimer.current = null;
      setNotice("");
    }, 4000);
  }, []);

  const openBatchById = useCallback((batchId: number, fromInitialBatch = false) => {
    if (!Number.isInteger(batchId) || batchId <= 0) {
      showNotice("请输入有效的批次 ID。");
      return;
    }
    const requestId = ++directRequest.current;
    setLookupLoading(true);
    void requestJson<CaptureBatchRow>(`/api/capture-batches/${batchId}`)
      .then((batch) => {
        if (directRequest.current === requestId) {
          setOpenedFromInitialBatch(fromInitialBatch);
          setSelected(batch);
        }
      })
      .catch(() => {
        if (directRequest.current === requestId) showNotice(`批次 #${batchId} 不存在或已不可用。`);
      })
      .finally(() => {
        if (directRequest.current === requestId) setLookupLoading(false);
      });
  }, [showNotice]);

  const exportBatchMarkdown = useCallback(async (batchId: number) => {
    if (exportingBatchId !== null) return;
    setExportingBatchId(batchId);
    try {
      await downloadBatchMarkdown(batchId);
    } catch (error: unknown) {
      const message = error instanceof ApiRequestError ? error.message : "Markdown 导出失败，请稍后重试。";
      showNotice(message);
    } finally {
      setExportingBatchId((current) => (current === batchId ? null : current));
    }
  }, [exportingBatchId, showNotice]);

  useEffect(() => () => {
    if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current);
  }, []);

  useEffect(() => setPage(1), [platform, statusFilter, failedOnly, todayOnly]);

  useEffect(() => {
    if (!active) return;
    const requestId = ++latest.current;
    setData((current) => ({ ...current, loading: current.rows.length === 0, error: "" }));
    const params = new URLSearchParams({ page: String(page), page_size: "20" });
    if (platform) params.set("source_platform", platform);
    if (statusFilter) params.set("status", statusFilter);
    if (failedOnly) params.set("failed_only", "true");
    if (todayOnly) params.set("today_only", "true");
    void requestJson<BatchPageResponse>(`/api/capture-batches?${params}`)
      .then((payload) => {
        if (latest.current !== requestId) return;
        const newest = Number(payload.rows[0]?.id || 0);
        if (knownLatest.current && newest > knownLatest.current) {
          showNotice(`已接收新批次 #${newest}`);
        }
        knownLatest.current = Math.max(knownLatest.current, newest);
        setData({ ...payload, loading: false, error: "" });
        setTodaySummary(payload.today_summary || { received: 0, added: 0 });
      })
      .catch((error: unknown) => {
        if (latest.current === requestId) {
          setData((current) => ({
            ...current,
            loading: false,
            error: error instanceof ApiRequestError ? error.message : "采集批次加载失败。",
          }));
        }
      });
  }, [active, page, platform, statusFilter, failedOnly, todayOnly, refresh, showNotice]);

  useEffect(() => {
    if (!active || !initialBatchId) return;
    openBatchById(initialBatchId, Boolean(initialReturnView));
    onInitialBatchConsumed?.();
  }, [active, initialBatchId, initialReturnView, onInitialBatchConsumed, openBatchById]);

  useEffect(() => {
    if (!active || selected) return;
    const timer = window.setInterval(load, 10000);
    const onFocus = () => load();
    const onVisibility = () => {
      if (document.visibilityState === "visible") load();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [active, load, selected]);

  const closeSelected = () => {
    if (openedFromInitialBatch && onReturnFromInitialBatch) {
      setOpenedFromInitialBatch(false);
      setSelected(null);
      onReturnFromInitialBatch();
      return;
    }
    setOpenedFromInitialBatch(false);
    setSelected(null);
  };

  if (selected) {
    return (
      <>
        {notice && <div className="toast" role="status">{notice}</div>}
        <BatchDetail
          batch={selected}
          onBack={closeSelected}
          onExportError={showNotice}
        />
      </>
    );
  }

  const hasFilters = Boolean(platform || statusFilter || failedOnly || todayOnly);

  return (
    <div className="page-content page-enter">
      {notice && <div className="toast" role="status">{notice}</div>}
      <div className="page-heading">
        <div>
          <p className="eyebrow">采集流水</p>
          <h1>最近批次</h1>
          <p className="page-description">保留当前筛选、分页和直达定位，批次导出继续使用不可变快照。</p>
        </div>
        <div className="toolbar workbench-toolbar-stack">
          <form className="search-form" onSubmit={(event) => { event.preventDefault(); openBatchById(Number(batchLookup)); }}>
            <label className="search-input">
              <span>#</span>
              <input
                aria-label="批次 ID 搜索"
                inputMode="numeric"
                placeholder="输入批次 ID 直接打开"
                value={batchLookup}
                onChange={(event) => setBatchLookup(event.target.value.replace(/[^\d]/g, ""))}
              />
            </label>
            <button className="secondary-button" type="submit" disabled={lookupLoading}>
              {lookupLoading ? "打开中…" : "打开批次"}
            </button>
          </form>
          <div className="toolbar">
            <select aria-label="批次来源平台" value={platform} onChange={(event) => setPlatform(event.target.value)}>
              <option value="">全部平台</option>
              <option value="boss">Boss</option>
              <option value="liepin">猎聘</option>
            </select>
            <select aria-label="批次状态" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as BatchStatusFilter)}>
              <option value="">全部状态</option>
              <option value="completed">已完成</option>
              <option value="partial">部分成功</option>
              <option value="failed">失败</option>
            </select>
            <label className="compact-check">
              <input type="checkbox" checked={failedOnly} onChange={(event) => setFailedOnly(event.target.checked)} />
              只看失败批次
            </label>
            <label className="compact-check">
              <input type="checkbox" checked={todayOnly} onChange={(event) => setTodayOnly(event.target.checked)} />
              只看今天
            </label>
            <RefreshButton onClick={load} />
          </div>
        </div>
      </div>
      <section className="summary-strip">
        <div><span>总批次数</span><strong>{data.total}</strong></div>
        <div><span>今日接收</span><strong>{todaySummary.received}</strong></div>
        <div><span>今日新增</span><strong>{todaySummary.added}</strong></div>
      </section>
      <section className="data-panel">
        <TableState
          loading={data.loading}
          error={data.error}
          empty={!data.rows.length}
          emptyText={hasFilters ? "当前筛选条件下还没有采集批次。" : "还没有采集批次。"}
        />
        {!data.loading && !data.error && data.rows.length > 0 && (
          <div className="table-scroll">
            <table className="workbench-table batch-table batch-table-readability">
              <thead>
                <tr>
                  <th>批次</th>
                  <th>时间</th>
                  <th>平台</th>
                  <th>状态</th>
                  <th>接收</th>
                  <th>新增</th>
                  <th>更新</th>
                  <th>跳过</th>
                  <th>失败</th>
                  <th className="actions-column">操作</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id} className={row.id === knownLatest.current ? "latest-row" : ""}>
                    <td className="numeric"><strong>#{row.id}</strong></td>
                    <td className="numeric">{formatDate(row.start_time)}</td>
                    <td><StatusBadge>{row.source_platform || "unknown"}</StatusBadge></td>
                    <td><StatusBadge tone={row.status === "completed" ? "success" : row.status === "partial" ? "warning" : "muted"}>{renderBatchStatus(row.status)}</StatusBadge></td>
                    <td>{row.total_collected}</td>
                    <td>{row.total_new}</td>
                    <td>{row.total_updated}</td>
                    <td>{row.total_skipped}</td>
                    <td>{row.total_failed}</td>
                    <td>
                      <div className="row-actions">
                        <button className="secondary-button" onClick={() => { setOpenedFromInitialBatch(false); setSelected(row); }}>查看候选人</button>
                        <button
                          className="secondary-button"
                          onClick={() => void exportBatchMarkdown(row.id)}
                          disabled={exportingBatchId === row.id}
                        >
                          <Download size={14} />
                          {exportingBatchId === row.id ? "导出中…" : "导出 Markdown"}
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
      <Pager
        page={page}
        pageSize={data.page_size}
        total={data.total}
        onPrevious={() => setPage((value) => Math.max(1, value - 1))}
        onNext={() => setPage((value) => value + 1)}
      />
    </div>
  );
}

function BatchDetail({
  batch,
  onBack,
  onExportError,
}: {
  batch: CaptureBatchRow;
  onBack: () => void;
  onExportError: (message: string) => void;
}) {
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState(emptyCandidates);
  const [snapshotIndex, setSnapshotIndex] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const latest = useRef(0);

  useEffect(() => {
    setSnapshotIndex(null);
  }, [batch.id, page]);

  useEffect(() => {
    const id = ++latest.current;
    setData((current) => ({ ...current, loading: true, error: "" }));
    void requestJson<PagedResponse<BatchCandidateRow>>(`/api/capture-batches/${batch.id}/candidates?page=${page}&page_size=50`)
      .then((payload) => {
        if (latest.current === id) setData({ ...payload, loading: false, error: "" });
      })
      .catch((error: unknown) => {
        if (latest.current === id) {
          setData((current) => ({
            ...current,
            loading: false,
            error: error instanceof ApiRequestError ? error.message : "批次详情加载失败。",
          }));
        }
      });
  }, [batch.id, page, refresh]);

  const exportBatch = useCallback(async () => {
    if (exporting) return;
    setExporting(true);
    try {
      await downloadBatchMarkdown(batch.id);
    } catch (error: unknown) {
      onExportError(error instanceof ApiRequestError ? error.message : "Markdown 导出失败，请稍后重试。");
    } finally {
      setExporting(false);
    }
  }, [batch.id, exporting, onExportError]);

  const snapshot = snapshotIndex !== null ? data.rows[snapshotIndex] ?? null : null;

  return (
    <div className="page-content page-enter">
      <div className="detail-header">
        <button className="icon-button" onClick={onBack} aria-label="返回批次列表"><ArrowLeft size={17} /></button>
        <div>
          <p className="eyebrow">批次快照</p>
          <h1>批次 #{batch.id}</h1>
          <p>{batch.source_platform || "unknown"} · {formatDate(batch.start_time)}</p>
        </div>
        <div className="detail-actions">
          <RefreshButton onClick={() => setRefresh((value) => value + 1)} label="刷新批次候选人" />
          <button className="primary-button" onClick={() => void exportBatch()} disabled={exporting}>
            <Download size={15} />
            {exporting ? "导出中…" : "导出 Markdown"}
          </button>
        </div>
      </div>
      <section className="summary-strip five">
        <div><span>接收</span><strong>{batch.total_collected}</strong></div>
        <div><span>新增</span><strong>{batch.total_new}</strong></div>
        <div><span>更新</span><strong>{batch.total_updated}</strong></div>
        <div><span>跳过</span><strong>{batch.total_skipped}</strong></div>
        <div><span>失败</span><strong>{batch.total_failed}</strong></div>
      </section>
      <section className="data-panel">
        <TableState loading={data.loading} error={data.error} empty={!data.rows.length} />
        {!data.loading && !data.error && data.rows.length > 0 && (
          <div className="table-scroll">
            <table className="workbench-table batch-candidate-table">
              <thead>
                <tr>
                  <th>候选人</th>
                  <th>来源岗位</th>
                  <th>本次结果</th>
                  <th>本次正式岗位</th>
                  <th>采集时间</th>
                  <th>快照</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, index) => (
                  <tr key={row.id}>
                    <td>
                      <strong className="primary-cell">{row.name || `候选人 #${row.candidate_id}`}</strong>
                    </td>
                    <td className="text-cell">
                      <span className="line-clamp-2" title={row.job_title || "未提供"}>
                        {row.job_title || "未提供"}
                      </span>
                    </td>
                    <td><StatusBadge tone={row.ingest_status === "updated" ? "info" : "success"}>{row.ingest_status === "updated" ? "更新" : "新增"}</StatusBadge></td>
                    <td><StatusBadge tone={batch.role_id !== null ? "success" : "muted"}>{batch.role_id !== null ? `岗位档案 #${batch.role_id}` : "未提供正式岗位"}</StatusBadge></td>
                    <td className="numeric">{formatDate(row.capture_time)}</td>
                    <td><button className="secondary-button" onClick={() => setSnapshotIndex(index)}>查看原始快照</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Pager
        page={page}
        pageSize={data.page_size}
        total={data.total}
        onPrevious={() => setPage((value) => Math.max(1, value - 1))}
        onNext={() => setPage((value) => value + 1)}
      />
      {snapshot && (
        <Drawer label="原始快照" className="drawer-panel snapshot-reader-drawer" onClose={() => setSnapshotIndex(null)}>
          <header className="drawer-header">
            <div>
              <p className="eyebrow">不可变批次快照</p>
              <h2>{snapshot.name || `候选人 #${snapshot.candidate_id}`}</h2>
              <p>
                <span className="numeric">{snapshotIndex! + 1} / {data.rows.length}</span>
                {" · "}
                {snapshot.job_title || "未提供"}
                {" · "}
                {formatDate(snapshot.capture_time)}
              </p>
            </div>
            <button className="icon-button" onClick={() => setSnapshotIndex(null)} aria-label="关闭原始快照"><X size={17} /></button>
          </header>
          <div className="detail-chip-row">
            <StatusBadge tone={snapshot.ingest_status === "updated" ? "info" : "success"}>{snapshot.ingest_status === "updated" ? "更新" : "新增"}</StatusBadge>
          </div>
          <SnapshotTextBlock text={snapshot.raw_card_text || ""} />
          <div className="snapshot-pagination">
            <button className="secondary-button" onClick={() => setSnapshotIndex((value) => value === null ? value : Math.max(0, value - 1))} disabled={snapshotIndex === 0}>
              上一个
            </button>
            <button className="secondary-button" onClick={() => setSnapshotIndex((value) => value === null ? value : Math.min(data.rows.length - 1, value + 1))} disabled={snapshotIndex === data.rows.length - 1}>
              下一个
            </button>
          </div>
        </Drawer>
      )}
    </div>
  );
}

function renderBatchStatus(status: string) {
  if (status === "completed") return "已完成";
  if (status === "partial") return "部分成功";
  if (status === "failed") return "失败";
  return status || "unknown";
}
