import { FormEvent, useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { ApiRequestError, CandidateDetail, CandidateRow, PagedResponse, requestJson } from "../../api";
import { formatDate, Loadable, Pager, RefreshButton, StatusBadge, TableState } from "./common";

const empty: Loadable<CandidateRow> = { rows: [], total: 0, page: 1, page_size: 100, loading: false, error: "" };

export function CandidatesPage({ onOpenBatch }: { onOpenBatch: (batchId: number) => void }) {
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [platform, setPlatform] = useState("");
  const [unbound, setUnbound] = useState(false);
  const [sort, setSort] = useState("latest_capture_desc");
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState(empty);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CandidateDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const latest = useRef(0);
  const latestDetail = useRef(0);

  useEffect(() => setPage(1), [keyword, platform, sort, unbound]);

  useEffect(() => {
    const requestId = ++latest.current;
    setData((current) => ({ ...current, loading: true, error: "" }));
    const params = new URLSearchParams({ page: String(page), page_size: "100", sort });
    if (keyword) params.set("keyword", keyword);
    if (platform) params.set("source_platform", platform);
    if (unbound) params.set("unbound_only", "true");
    void requestJson<PagedResponse<CandidateRow>>(`/api/candidates?${params}`).then((payload) => {
      if (latest.current === requestId) setData({ ...payload, loading: false, error: "" });
    }).catch((error: unknown) => {
      if (latest.current === requestId) {
        setData((current) => ({
          ...current,
          rows: [],
          loading: false,
          error: error instanceof ApiRequestError ? error.message : "候选人列表加载失败。",
        }));
      }
    });
  }, [keyword, page, platform, refresh, sort, unbound]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      setDetailError("");
      setDetailLoading(false);
      return;
    }
    const requestId = ++latestDetail.current;
    setDetail(null);
    setDetailLoading(true);
    setDetailError("");
    void requestJson<CandidateDetail>(`/api/candidates/${selectedId}`).then((payload) => {
      if (latestDetail.current === requestId) {
        setDetail(payload);
        setDetailLoading(false);
      }
    }).catch((error: unknown) => {
      if (latestDetail.current === requestId) {
        setDetail(null);
        setDetailLoading(false);
        setDetailError(error instanceof ApiRequestError ? error.message : "候选人详情加载失败。");
      }
    });
  }, [selectedId]);

  const openDetail = (candidateId: number) => setSelectedId(candidateId);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setKeyword(keywordInput.trim());
  };

  return (
    <div className="page-content page-enter">
      <div className="page-heading">
        <div>
          <p className="eyebrow">候选人主档</p>
          <h1>候选人</h1>
          <p className="page-description">按来源、关键词和最近采集批次快速定位候选人，详情保持只读。</p>
        </div>
        <div className="toolbar workbench-toolbar-stack">
          <form className="search-form" onSubmit={submitSearch}>
            <label className="search-input">
              <Search size={15} />
              <input
                aria-label="候选人搜索"
                placeholder="搜索姓名、来源岗位、原始卡片关键词"
                value={keywordInput}
                onChange={(event) => setKeywordInput(event.target.value)}
              />
            </label>
            <button className="secondary-button" type="submit">搜索</button>
          </form>
          <div className="toolbar">
            <select aria-label="来源平台" value={platform} onChange={(event) => setPlatform(event.target.value)}>
              <option value="">全部平台</option>
              <option value="boss">Boss</option>
              <option value="liepin">猎聘</option>
            </select>
            <select aria-label="候选人排序" value={sort} onChange={(event) => setSort(event.target.value)}>
              <option value="latest_capture_desc">最近采集优先</option>
              <option value="latest_capture_asc">最早采集优先</option>
            </select>
            <label className="compact-check">
              <input type="checkbox" checked={unbound} onChange={(event) => setUnbound(event.target.checked)} />
              只看未绑定岗位
            </label>
            <RefreshButton onClick={() => setRefresh((value) => value + 1)} />
          </div>
        </div>
      </div>
      <section className="data-panel">
        <TableState
          loading={data.loading}
          error={data.error}
          empty={!data.rows.length}
          emptyText={keyword || platform || unbound ? "没有符合当前筛选条件的候选人。" : "当前还没有候选人。"}
        />
        {!data.loading && !data.error && data.rows.length > 0 && (
          <div className="table-scroll">
            <table className="workbench-table candidate-table candidate-table-detailed">
              <thead>
                <tr>
                  <th>候选人</th>
                  <th>来源</th>
                  <th>来源岗位</th>
                  <th>岗位状态</th>
                  <th>最近采集</th>
                  <th>批次</th>
                  <th>本次结果</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <button className="table-link-button" onClick={() => openDetail(row.id)}>
                        <strong className="primary-cell">{row.name || `候选人 #${row.id}`}</strong>
                      </button>
                      <small>内部 ID {row.id}</small>
                    </td>
                    <td><StatusBadge>{row.latest_source_platform || row.source_platform || "unknown"}</StatusBadge></td>
                    <td className="text-cell">{row.latest_source_job_title || "未提供"}</td>
                    <td><StatusBadge tone={row.has_role_binding ? "success" : "muted"}>{row.has_role_binding ? "已绑定岗位" : "未绑定岗位"}</StatusBadge></td>
                    <td className="numeric">{formatDate(row.latest_capture_time)}</td>
                    <td>{row.latest_batch_id ? <button className="text-button" onClick={() => onOpenBatch(row.latest_batch_id)}>#{row.latest_batch_id}</button> : "—"}</td>
                    <td><StatusBadge tone={row.latest_ingest_status === "updated" ? "info" : "success"}>{row.latest_ingest_status === "updated" ? "更新" : "新增"}</StatusBadge></td>
                    <td><button className="secondary-button" onClick={() => openDetail(row.id)}>查看详情</button></td>
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
      {selectedId !== null && (
        <CandidateDetailDrawer
          detail={detail}
          loading={detailLoading}
          error={detailError}
          onClose={() => setSelectedId(null)}
          onOpenBatch={(batchId) => {
            setSelectedId(null);
            onOpenBatch(batchId);
          }}
        />
      )}
    </div>
  );
}

function CandidateDetailDrawer({
  detail,
  loading,
  error,
  onClose,
  onOpenBatch,
}: {
  detail: CandidateDetail | null;
  loading: boolean;
  error: string;
  onClose: () => void;
  onOpenBatch: (batchId: number) => void;
}) {
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="snapshot-drawer detail-drawer" aria-label="候选人详情" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <p className="eyebrow">候选人详情</p>
            <h2>{detail?.name || "候选人详情"}</h2>
            {detail && <p>{detail.latest_source_platform || detail.source_platform || "unknown"} · 最近采集 {formatDate(detail.latest_capture_time)}</p>}
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭候选人详情"><X size={17} /></button>
        </header>
        {loading && <div className="table-state skeleton-state"><span />正在读取候选人详情…</div>}
        {!loading && error && <div className="table-state error-table-state">{error}</div>}
        {!loading && !error && detail && (
          <>
            <div className="detail-chip-row">
              <StatusBadge>{detail.latest_source_platform || detail.source_platform || "unknown"}</StatusBadge>
              <StatusBadge tone={detail.has_role_binding ? "success" : "muted"}>{detail.has_role_binding ? "已绑定岗位" : "未绑定岗位"}</StatusBadge>
              <StatusBadge tone={detail.latest_ingest_status === "updated" ? "info" : "success"}>{detail.latest_ingest_status === "updated" ? "最近为更新" : "最近为新增"}</StatusBadge>
            </div>
            <dl className="detail-grid">
              <div><dt>来源岗位</dt><dd>{detail.latest_source_job_title || detail.job_title || "未提供"}</dd></div>
              <div><dt>最近批次</dt><dd>{detail.latest_batch_id ? <button className="text-button" onClick={() => onOpenBatch(detail.latest_batch_id)}>#{detail.latest_batch_id}</button> : "—"}</dd></div>
              <div><dt>最近采集</dt><dd>{formatDate(detail.latest_capture_time)}</dd></div>
              <div><dt>来源链接</dt><dd className="break-all">{detail.latest_source_url || detail.source_url || "未保存"}</dd></div>
              <div><dt>详情链接</dt><dd className="break-all">{detail.latest_detail_url || detail.detail_url || "未保存"}</dd></div>
              <div><dt>基础状态</dt><dd>{detail.active_status || "未提供"}</dd></div>
              <div><dt>期望薪资</dt><dd>{detail.expected_salary || "未提供"}</dd></div>
              <div><dt>工作经验</dt><dd>{detail.work_experience_text || "未提供"}</dd></div>
              <div><dt>学历</dt><dd>{detail.education_text || "未提供"}</dd></div>
              <div><dt>标签</dt><dd>{detail.tags_text || "未提供"}</dd></div>
              <div><dt>城市</dt><dd>{detail.city || "未提供"}</dd></div>
              <div><dt>批次数</dt><dd>{detail.batch_count || 0}</dd></div>
            </dl>
            <section className="detail-section">
              <h3>摘要</h3>
              <p>{detail.summary_text || "未提供摘要。"}</p>
            </section>
            <section className="detail-section">
              <h3>原始卡片快照</h3>
              <pre>{detail.latest_raw_card_text || detail.raw_card_text || "未保存原始快照"}</pre>
            </section>
          </>
        )}
      </aside>
    </div>
  );
}
