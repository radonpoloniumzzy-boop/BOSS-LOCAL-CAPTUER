import { useEffect, useRef, useState } from "react";
import { Users } from "lucide-react";
import { ApiRequestError, CandidateRow, PagedResponse, requestJson } from "../../api";
import { formatDate, Loadable, Pager, RefreshButton, StatusBadge, TableState } from "./common";

const empty: Loadable<CandidateRow> = { rows: [], total: 0, page: 1, page_size: 100, loading: false, error: "" };

export function CandidatesPage({ onOpenBatch }: { onOpenBatch: (batchId: number) => void }) {
  const [platform, setPlatform] = useState("");
  const [unbound, setUnbound] = useState(false);
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState(empty);
  const latest = useRef(0);
  useEffect(() => setPage(1), [platform, unbound]);
  useEffect(() => {
    const requestId = ++latest.current;
    setData((current) => ({ ...current, loading: true, error: "" }));
    const params = new URLSearchParams({ page: String(page), page_size: "100" });
    if (platform) params.set("source_platform", platform);
    if (unbound) params.set("unbound_only", "true");
    void requestJson<PagedResponse<CandidateRow>>(`/api/candidates?${params}`).then((payload) => {
      if (latest.current === requestId) setData({ ...payload, loading: false, error: "" });
    }).catch((error: unknown) => {
      if (latest.current === requestId) setData((current) => ({ ...current, rows: [], loading: false, error: error instanceof ApiRequestError ? error.message : "候选人列表加载失败。" }));
    });
  }, [page, platform, refresh, unbound]);

  return <div className="page-content page-enter">
    <div className="page-heading"><div><p className="eyebrow">候选人主档</p><h1>候选人</h1><p className="page-description">统一查看来源、采集批次与岗位绑定状态。</p></div><div className="toolbar">
      <select aria-label="来源平台" value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="">全部平台</option><option value="boss">Boss</option><option value="liepin">猎聘</option></select>
      <label className="compact-check"><input type="checkbox" checked={unbound} onChange={(event) => setUnbound(event.target.checked)} />只看未绑定岗位</label>
      <RefreshButton onClick={() => setRefresh((value) => value + 1)} />
    </div></div>
    <section className="data-panel">
      <TableState loading={data.loading} error={data.error} empty={!data.rows.length} emptyText="当前筛选条件下还没有候选人。" />
      {!data.loading && !data.error && data.rows.length > 0 && <div className="table-scroll"><table className="workbench-table candidate-table"><thead><tr><th>候选人</th><th>来源</th><th>来源岗位</th><th>岗位状态</th><th>最近采集</th><th>批次</th><th>本次结果</th></tr></thead><tbody>
        {data.rows.map((row) => <tr key={row.id}><td><strong className="primary-cell">{row.name || `候选人 #${row.id}`}</strong><small>内部 ID {row.id}</small></td><td><StatusBadge>{row.latest_source_platform || row.source_platform || "unknown"}</StatusBadge></td><td className="text-cell">{row.latest_source_job_title || "未提供"}</td><td><StatusBadge tone={row.has_role_binding ? "success" : "muted"}>{row.has_role_binding ? "已绑定岗位" : "未绑定岗位"}</StatusBadge></td><td className="numeric">{formatDate(row.latest_capture_time)}</td><td>{row.latest_batch_id ? <button className="text-button" onClick={() => onOpenBatch(row.latest_batch_id)}>#{row.latest_batch_id}</button> : "—"}</td><td><StatusBadge tone={row.latest_ingest_status === "updated" ? "info" : "success"}>{row.latest_ingest_status === "updated" ? "更新" : "新增"}</StatusBadge></td></tr>)}
      </tbody></table></div>}
    </section>
    <Pager page={page} pageSize={data.page_size} total={data.total} onPrevious={() => setPage((value) => Math.max(1, value - 1))} onNext={() => setPage((value) => value + 1)} />
  </div>;
}
