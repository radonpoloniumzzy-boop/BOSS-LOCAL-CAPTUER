import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Download, X } from "lucide-react";
import { ApiRequestError, BatchCandidateRow, CaptureBatchRow, PagedResponse, requestJson } from "../../api";
import { formatDate, Loadable, Pager, RefreshButton, StatusBadge, TableState } from "./common";

const emptyBatches: Loadable<CaptureBatchRow> = { rows: [], total: 0, page: 1, page_size: 20, loading: false, error: "" };
const emptyCandidates: Loadable<BatchCandidateRow> = { rows: [], total: 0, page: 1, page_size: 50, loading: false, error: "" };
type BatchPageResponse = PagedResponse<CaptureBatchRow> & { today_summary?: { received: number; added: number } };

export function BatchesPage({ initialBatchId = null, onInitialBatchConsumed }: { initialBatchId?: number | null; onInitialBatchConsumed?: () => void }) {
  const [page, setPage] = useState(1);
  const [platform, setPlatform] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState(emptyBatches);
  const [selected, setSelected] = useState<CaptureBatchRow | null>(null);
  const [notice, setNotice] = useState("");
  const [todaySummary, setTodaySummary] = useState({ received: 0, added: 0 });
  const latest = useRef(0);
  const directRequest = useRef(0);
  const knownLatest = useRef(0);
  const load = useCallback(() => setRefresh((value) => value + 1), []);
  useEffect(() => setPage(1), [platform]);
  useEffect(() => {
    const requestId = ++latest.current;
    setData((current) => ({ ...current, loading: current.rows.length === 0, error: "" }));
    const params = new URLSearchParams({ page: String(page), page_size: "20" });
    if (platform) params.set("source_platform", platform);
    void requestJson<BatchPageResponse>(`/api/capture-batches?${params}`).then((payload) => {
      if (latest.current !== requestId) return;
      const newest = Number(payload.rows[0]?.id || 0);
      if (knownLatest.current && newest > knownLatest.current) {
        setNotice(`已接收新批次 #${newest}`);
        window.setTimeout(() => setNotice(""), 4000);
      }
      knownLatest.current = Math.max(knownLatest.current, newest);
      setData({ ...payload, loading: false, error: "" });
      setTodaySummary(payload.today_summary || { received: 0, added: 0 });
    }).catch((error: unknown) => {
      if (latest.current === requestId) setData((current) => ({ ...current, loading: false, error: error instanceof ApiRequestError ? error.message : "采集批次加载失败。" }));
    });
  }, [page, platform, refresh]);
  useEffect(() => {
    if (!initialBatchId) return;
    const requestId = ++directRequest.current;
    void requestJson<CaptureBatchRow>(`/api/capture-batches/${initialBatchId}`)
      .then((batch) => {
        if (directRequest.current === requestId) setSelected(batch);
      })
      .catch(() => {
        if (directRequest.current === requestId) setNotice(`批次 #${initialBatchId} 不存在或已不可用。`);
      })
      .finally(() => {
        if (directRequest.current === requestId) onInitialBatchConsumed?.();
      });
  }, [initialBatchId, onInitialBatchConsumed]);
  useEffect(() => {
    const timer = window.setInterval(load, 10000);
    const onFocus = () => load();
    const onVisibility = () => { if (document.visibilityState === "visible") load(); };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", onFocus); document.removeEventListener("visibilitychange", onVisibility); };
  }, [load]);

  if (selected) return <BatchDetail batch={selected} onBack={() => setSelected(null)} />;
  return <div className="page-content page-enter">
    {notice && <div className="toast" role="status">{notice}</div>}
    <div className="page-heading"><div><p className="eyebrow">采集流水</p><h1>最近批次</h1><p className="page-description">每 10 秒轻量刷新，最新批次始终在顶部。</p></div><div className="toolbar"><select aria-label="批次来源平台" value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="">全部平台</option><option value="boss">Boss</option><option value="liepin">猎聘</option></select><RefreshButton onClick={load} /></div></div>
    <section className="summary-strip"><div><span>总批次数</span><strong>{data.total}</strong></div><div><span>今日接收</span><strong>{todaySummary.received}</strong></div><div><span>今日新增</span><strong>{todaySummary.added}</strong></div></section>
    <section className="data-panel"><TableState loading={data.loading} error={data.error} empty={!data.rows.length} />{!data.loading && !data.error && data.rows.length > 0 && <div className="table-scroll"><table className="workbench-table batch-table"><thead><tr><th>批次</th><th>时间</th><th>平台</th><th>状态</th><th>接收</th><th>新增</th><th>更新</th><th>跳过</th><th>失败</th><th className="actions-column">操作</th></tr></thead><tbody>
      {data.rows.map((row) => <tr key={row.id} className={row.id === knownLatest.current ? "latest-row" : ""}><td><strong>#{row.id}</strong></td><td className="numeric">{formatDate(row.start_time)}</td><td><StatusBadge>{row.source_platform || "unknown"}</StatusBadge></td><td><StatusBadge tone={row.status === "completed" ? "success" : row.status === "partial" ? "warning" : "muted"}>{row.status}</StatusBadge></td><td>{row.total_collected}</td><td>{row.total_new}</td><td>{row.total_updated}</td><td>{row.total_skipped}</td><td>{row.total_failed}</td><td><div className="row-actions"><button className="secondary-button" onClick={() => setSelected(row)}>查看候选人</button><a className="secondary-button" href={`/api/capture-batches/${row.id}/export.md`} download><Download size={14} />导出 Markdown</a></div></td></tr>)}
    </tbody></table></div>}</section>
    <Pager page={page} pageSize={data.page_size} total={data.total} onPrevious={() => setPage((value) => Math.max(1, value - 1))} onNext={() => setPage((value) => value + 1)} />
  </div>;
}

function BatchDetail({ batch, onBack }: { batch: CaptureBatchRow; onBack: () => void }) {
  const [page, setPage] = useState(1); const [refresh, setRefresh] = useState(0); const [data, setData] = useState(emptyCandidates); const [snapshot, setSnapshot] = useState<BatchCandidateRow | null>(null); const latest = useRef(0);
  useEffect(() => { const id = ++latest.current; setData((current) => ({ ...current, loading: true, error: "" })); void requestJson<PagedResponse<BatchCandidateRow>>(`/api/capture-batches/${batch.id}/candidates?page=${page}&page_size=50`).then((payload) => { if (latest.current === id) setData({ ...payload, loading: false, error: "" }); }).catch((error: unknown) => { if (latest.current === id) setData((current) => ({ ...current, loading: false, error: error instanceof ApiRequestError ? error.message : "批次详情加载失败。" })); }); }, [batch.id, page, refresh]);
  return <div className="page-content page-enter"><div className="detail-header"><button className="icon-button" onClick={onBack} aria-label="返回批次列表"><ArrowLeft size={17} /></button><div><p className="eyebrow">批次快照</p><h1>批次 #{batch.id}</h1><p>{batch.source_platform || "unknown"} · {formatDate(batch.start_time)}</p></div><div className="detail-actions"><RefreshButton onClick={() => setRefresh((value) => value + 1)} label="刷新批次候选人" /><a className="primary-button" href={`/api/capture-batches/${batch.id}/export.md`} download><Download size={15} />导出 Markdown</a></div></div>
    <section className="summary-strip five"><div><span>接收</span><strong>{batch.total_collected}</strong></div><div><span>新增</span><strong>{batch.total_new}</strong></div><div><span>更新</span><strong>{batch.total_updated}</strong></div><div><span>跳过</span><strong>{batch.total_skipped}</strong></div><div><span>失败</span><strong>{batch.total_failed}</strong></div></section>
    <section className="data-panel"><TableState loading={data.loading} error={data.error} empty={!data.rows.length} />{!data.loading && !data.error && data.rows.length > 0 && <div className="table-scroll"><table className="workbench-table"><thead><tr><th>候选人</th><th>来源岗位</th><th>本次结果</th><th>本次正式岗位</th><th>采集时间</th><th>快照</th></tr></thead><tbody>{data.rows.map((row) => <tr key={row.id}><td><strong className="primary-cell">{row.name || `候选人 #${row.candidate_id}`}</strong></td><td className="text-cell">{row.job_title || "未提供"}</td><td><StatusBadge tone={row.ingest_status === "updated" ? "info" : "success"}>{row.ingest_status === "updated" ? "更新" : "新增"}</StatusBadge></td><td><StatusBadge tone={batch.role_id !== null ? "success" : "muted"}>{batch.role_id !== null ? `岗位档案 #${batch.role_id}` : "未提供正式岗位"}</StatusBadge></td><td className="numeric">{formatDate(row.capture_time)}</td><td><button className="secondary-button" onClick={() => setSnapshot(row)}>查看原始快照</button></td></tr>)}</tbody></table></div>}</section>
    <Pager page={page} pageSize={data.page_size} total={data.total} onPrevious={() => setPage((value) => Math.max(1, value - 1))} onNext={() => setPage((value) => value + 1)} />
    {snapshot && <div className="drawer-backdrop" onClick={() => setSnapshot(null)}><aside className="snapshot-drawer" aria-label="原始快照" onClick={(event) => event.stopPropagation()}><header><div><p className="eyebrow">不可变批次快照</p><h2>{snapshot.name || `候选人 #${snapshot.candidate_id}`}</h2></div><button className="icon-button" onClick={() => setSnapshot(null)} aria-label="关闭原始快照"><X size={17} /></button></header><pre>{snapshot.raw_card_text || "未保存原始快照"}</pre></aside></div>}
  </div>;
}
