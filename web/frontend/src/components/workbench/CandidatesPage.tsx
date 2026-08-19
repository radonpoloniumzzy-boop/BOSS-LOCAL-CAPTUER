import { FormEvent, useEffect, useRef, useState } from "react";
import { ExternalLink, Search, X } from "lucide-react";
import { ApiRequestError, CandidateAppearanceRow, CandidateDetail, CandidateRow, PagedResponse, requestJson } from "../../api";
import { Drawer } from "./Drawer";
import { formatDate, Loadable, Pager, RefreshButton, StatusBadge, TableState } from "./common";
import { SnapshotTextBlock } from "./SnapshotTextBlock";

const empty: Loadable<CandidateRow> = { rows: [], total: 0, page: 1, page_size: 100, loading: false, error: "" };
const emptyAppearances: AppearanceLoadable = { rows: [], loading: false, error: "" };

type AppearanceLoadable = {
  rows: CandidateAppearanceRow[];
  loading: boolean;
  error: string;
};

function displayValue(value: string | number | null | undefined) {
  if (value === null || value === undefined) return "未提供";
  if (typeof value === "number") return String(value);
  return value.trim() ? value : "未提供";
}

function safeHttpUrl(value: string) {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.toString();
  } catch {
    return null;
  }
}

export function CandidatesPage({
  active = true,
  onOpenBatch,
}: {
  active?: boolean;
  onOpenBatch: (batchId: number) => void;
}) {
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
  const [appearances, setAppearances] = useState<AppearanceLoadable>(emptyAppearances);
  const [appearanceRefresh, setAppearanceRefresh] = useState(0);
  const latest = useRef(0);
  const latestDetail = useRef(0);
  const latestAppearances = useRef(0);

  useEffect(() => setPage(1), [keyword, platform, sort, unbound]);

  useEffect(() => {
    if (active) return;
    setSelectedId(null);
  }, [active]);

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
      setAppearances(emptyAppearances);
      setAppearanceRefresh(0);
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

  useEffect(() => {
    if (selectedId === null) return;
    const requestId = ++latestAppearances.current;
    setAppearances((current) => ({ ...current, loading: true, error: "" }));
    void requestJson<{ rows: CandidateAppearanceRow[] }>(`/api/candidates/${selectedId}/appearances`)
      .then((payload) => {
        if (latestAppearances.current === requestId) {
          setAppearances({ rows: payload.rows, loading: false, error: "" });
        }
      })
      .catch((error: unknown) => {
        if (latestAppearances.current === requestId) {
          setAppearances({
            rows: [],
            loading: false,
            error: error instanceof ApiRequestError ? error.message : "来源出现历史加载失败。",
          });
        }
      });
  }, [selectedId, appearanceRefresh]);

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
            <table className="workbench-table candidate-table candidate-table-readability">
              <thead>
                <tr>
                  <th>候选人</th>
                  <th>来源岗位</th>
                  <th>来源平台</th>
                  <th>岗位绑定</th>
                  <th>最近采集</th>
                  <th>最近批次</th>
                  <th>本次结果</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <div className="candidate-anchor-cell">
                        <button className="table-link-button" onClick={() => openDetail(row.id)}>
                          <strong className="primary-cell">{row.name || `候选人 #${row.id}`}</strong>
                        </button>
                        <small>内部 ID {row.id}</small>
                      </div>
                    </td>
                    <td className="text-cell">
                      <span className="line-clamp-2" title={row.latest_source_job_title || "未提供"}>
                        {row.latest_source_job_title || "未提供"}
                      </span>
                    </td>
                    <td><StatusBadge>{row.latest_source_platform || row.source_platform || "unknown"}</StatusBadge></td>
                    <td><StatusBadge tone={row.has_role_binding ? "success" : "muted"}>{row.has_role_binding ? "已绑定岗位" : "未绑定岗位"}</StatusBadge></td>
                    <td className="numeric">{formatDate(row.latest_capture_time)}</td>
                    <td className="numeric">
                      {row.latest_batch_id ? <button className="text-button" onClick={() => onOpenBatch(row.latest_batch_id)}>#{row.latest_batch_id}</button> : "未提供"}
                    </td>
                    <td><StatusBadge tone={row.latest_ingest_status === "updated" ? "info" : "success"}>{row.latest_ingest_status === "updated" ? "更新" : "新增"}</StatusBadge></td>
                    <td><button className="secondary-button row-hover-action" onClick={() => openDetail(row.id)}>查看详情</button></td>
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
      {active && selectedId !== null && (
        <CandidateDetailDrawer
          detail={detail}
          loading={detailLoading}
          error={detailError}
          appearances={appearances}
          onClose={() => setSelectedId(null)}
          onRetryAppearances={() => setAppearanceRefresh((value) => value + 1)}
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
  appearances,
  onClose,
  onRetryAppearances,
  onOpenBatch,
}: {
  detail: CandidateDetail | null;
  loading: boolean;
  error: string;
  appearances: AppearanceLoadable;
  onClose: () => void;
  onRetryAppearances: () => void;
  onOpenBatch: (batchId: number) => void;
}) {
  const sourceUrl = safeHttpUrl(detail?.latest_source_url || detail?.source_url || "");
  const detailUrl = safeHttpUrl(detail?.latest_detail_url || detail?.detail_url || "");

  return (
    <Drawer label="候选人详情" className="drawer-panel detail-drawer-panel" onClose={onClose}>
      <header className="drawer-header">
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
        <div className="detail-layout">
          <section className="detail-section-card">
            <div className="detail-section-headline">
              <span className="eyebrow">区域 A</span>
              <h3>身份摘要</h3>
            </div>
            <div className="detail-identity">
              <div className="detail-identity-main">
                <strong>{detail.name || `候选人 #${detail.id}`}</strong>
                <div className="detail-chip-row">
                  <StatusBadge>{detail.latest_source_platform || detail.source_platform || "unknown"}</StatusBadge>
                  <StatusBadge tone={detail.has_role_binding ? "success" : "muted"}>{detail.has_role_binding ? "已绑定岗位" : "未绑定岗位"}</StatusBadge>
                  <StatusBadge tone={detail.latest_ingest_status === "updated" ? "info" : "success"}>{detail.latest_ingest_status === "updated" ? "最近为更新" : "最近为新增"}</StatusBadge>
                </div>
              </div>
              <dl className="detail-summary-grid">
                <div><dt>最近采集时间</dt><dd className="numeric">{formatDate(detail.latest_capture_time)}</dd></div>
                <div>
                  <dt>最近批次</dt>
                  <dd>
                    {detail.latest_batch_id ? (
                      <button
                        className="text-button numeric"
                        aria-label={`打开最近批次 #${detail.latest_batch_id}`}
                        onClick={() => onOpenBatch(detail.latest_batch_id)}
                      >
                        #{detail.latest_batch_id}
                      </button>
                    ) : "未提供"}
                  </dd>
                </div>
              </dl>
            </div>
          </section>

          <section className="detail-section-card">
            <div className="detail-section-headline">
              <span className="eyebrow">区域 B</span>
              <h3>基础信息</h3>
            </div>
            <dl className="detail-grid">
              <div><dt>来源岗位</dt><dd>{displayValue(detail.latest_source_job_title || detail.job_title)}</dd></div>
              <div><dt>城市</dt><dd>{displayValue(detail.city)}</dd></div>
              <div><dt>工作经验</dt><dd>{displayValue(detail.work_experience_text)}</dd></div>
              <div><dt>学历</dt><dd>{displayValue(detail.education_text)}</dd></div>
              <div><dt>期望薪资</dt><dd>{displayValue(detail.expected_salary)}</dd></div>
              <div><dt>基础状态</dt><dd>{displayValue(detail.active_status)}</dd></div>
              <div><dt>标签</dt><dd>{displayValue(detail.tags_text)}</dd></div>
              <div><dt>历史批次数</dt><dd className="numeric">{displayValue(detail.batch_count)}</dd></div>
            </dl>
          </section>

          <section className="detail-section-card">
            <div className="detail-section-headline">
              <span className="eyebrow">区域 C</span>
              <h3>摘要与链接</h3>
            </div>
            <div className="detail-prose-block">
              <p>{detail.summary_text || "未提供"}</p>
            </div>
            <div className="button-row detail-link-row">
              {sourceUrl && (
                <a className="secondary-button" href={sourceUrl} target="_blank" rel="noreferrer">
                  <ExternalLink size={14} />
                  打开来源页面
                </a>
              )}
              {detailUrl && (
                <a className="secondary-button" href={detailUrl} target="_blank" rel="noreferrer">
                  <ExternalLink size={14} />
                  打开候选人详情
                </a>
              )}
              {!sourceUrl && !detailUrl && <span className="muted">未提供可打开的来源链接。</span>}
            </div>
            <div className="snapshot-preview-section">
              <h4>原始卡片快照</h4>
              <SnapshotTextBlock text={detail.latest_raw_card_text || detail.raw_card_text || ""} collapsible previewLines={8} />
            </div>
          </section>

          <section className="detail-section-card">
            <div className="detail-section-headline detail-section-headline-row">
              <div>
                <span className="eyebrow">区域 D</span>
                <h3>来源出现历史</h3>
              </div>
              <RefreshButton onClick={onRetryAppearances} label="重新读取来源历史" />
            </div>
            {appearances.loading && <div className="table-state skeleton-state"><span />正在读取来源出现历史…</div>}
            {!appearances.loading && appearances.error && (
              <div className="table-state error-table-state">
                <p>{appearances.error}</p>
                <button className="secondary-button" onClick={onRetryAppearances}>重试</button>
              </div>
            )}
            {!appearances.loading && !appearances.error && appearances.rows.length === 0 && (
              <div className="table-state compact-empty-state">还没有来源出现历史。</div>
            )}
            {!appearances.loading && !appearances.error && appearances.rows.length > 0 && (
              <div className="table-scroll">
                <table className="workbench-table compact-table appearance-table">
                  <thead>
                    <tr>
                      <th>批次</th>
                      <th>平台</th>
                      <th>来源岗位</th>
                      <th>采集时间</th>
                      <th>结果</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {appearances.rows.map((row) => (
                      <tr key={`${row.batch_id}-${row.capture_time}-${row.source_platform}`}>
                        <td className="numeric">
                          <button className="text-button" onClick={() => onOpenBatch(row.batch_id)}>#{row.batch_id}</button>
                        </td>
                        <td><StatusBadge>{row.source_platform || "unknown"}</StatusBadge></td>
                        <td className="text-cell">
                          <span className="line-clamp-2" title={row.source_job_title || "未提供"}>
                            {row.source_job_title || "未提供"}
                          </span>
                        </td>
                        <td className="numeric">{formatDate(row.capture_time)}</td>
                        <td><StatusBadge tone={row.ingest_status === "updated" ? "info" : "success"}>{row.ingest_status === "updated" ? "更新" : "新增"}</StatusBadge></td>
                        <td><button className="secondary-button" onClick={() => onOpenBatch(row.batch_id)}>查看批次</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}
