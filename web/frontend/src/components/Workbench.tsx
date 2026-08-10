import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  BriefcaseBusiness,
  Database,
  Home,
  Layers3,
  RefreshCw,
  Settings,
  Users,
} from "lucide-react";

import {
  ApiRequestError,
  AppStatus,
  BatchCandidateRow,
  CandidateRow,
  CaptureBatchRow,
  PagedResponse,
  requestJson,
} from "../api";
import { CountUp } from "./CountUp";

type View = "home" | "candidates" | "batches" | "settings";

type Loadable<T> = {
  rows: T[];
  total: number;
  page: number;
  page_size: number;
  loading: boolean;
  error: string;
};

const emptyCandidates: Loadable<CandidateRow> = {
  rows: [],
  total: 0,
  page: 1,
  page_size: 100,
  loading: false,
  error: "",
};

const emptyBatches: Loadable<CaptureBatchRow> = {
  rows: [],
  total: 0,
  page: 1,
  page_size: 20,
  loading: false,
  error: "",
};

const emptyBatchCandidates: Loadable<BatchCandidateRow> = {
  rows: [],
  total: 0,
  page: 1,
  page_size: 50,
  loading: false,
  error: "",
};

export function Workbench({ status }: { status: AppStatus }) {
  const [view, setView] = useState<View>("home");
  const [platformFilter, setPlatformFilter] = useState("");
  const [unboundOnly, setUnboundOnly] = useState(false);
  const [candidatePage, setCandidatePage] = useState(1);
  const [batchPage, setBatchPage] = useState(1);
  const [batchCandidatePage, setBatchCandidatePage] = useState(1);
  const [candidateRefreshTick, setCandidateRefreshTick] = useState(0);
  const [batchRefreshTick, setBatchRefreshTick] = useState(0);
  const [batchCandidateRefreshTick, setBatchCandidateRefreshTick] = useState(0);
  const [selectedBatch, setSelectedBatch] = useState<CaptureBatchRow | null>(null);
  const [candidates, setCandidates] = useState<Loadable<CandidateRow>>(emptyCandidates);
  const [batches, setBatches] = useState<Loadable<CaptureBatchRow>>(emptyBatches);
  const [batchCandidates, setBatchCandidates] = useState<Loadable<BatchCandidateRow>>(emptyBatchCandidates);
  const latestCandidateRequest = useRef(0);
  const latestBatchRequest = useRef(0);
  const latestBatchCandidateRequest = useRef(0);

  useEffect(() => {
    setCandidatePage(1);
  }, [platformFilter, unboundOnly]);

  useEffect(() => {
    setBatchPage(1);
  }, [platformFilter]);

  useEffect(() => {
    if (view !== "candidates") return;
    const requestId = latestCandidateRequest.current + 1;
    latestCandidateRequest.current = requestId;
    setCandidates((current) => ({ ...current, loading: true, error: "" }));
    const params = new URLSearchParams({
      page: String(candidatePage),
      page_size: "100",
    });
    if (platformFilter) params.set("source_platform", platformFilter);
    if (unboundOnly) params.set("unbound_only", "true");
    void requestJson<PagedResponse<CandidateRow>>(`/api/candidates?${params.toString()}`)
      .then((payload) => {
        if (latestCandidateRequest.current !== requestId) return;
        setCandidates({ ...payload, loading: false, error: "" });
      })
      .catch((error: unknown) => {
        if (latestCandidateRequest.current !== requestId) return;
        const message = error instanceof ApiRequestError ? error.message : "候选人列表加载失败。";
        setCandidates((current) => ({ ...current, loading: false, error: message, rows: [] }));
      });
  }, [candidatePage, candidateRefreshTick, platformFilter, unboundOnly, view]);

  useEffect(() => {
    if (view !== "batches" || selectedBatch !== null) return;
    const requestId = latestBatchRequest.current + 1;
    latestBatchRequest.current = requestId;
    setBatches((current) => ({ ...current, loading: true, error: "" }));
    const params = new URLSearchParams({
      page: String(batchPage),
      page_size: "20",
    });
    if (platformFilter) params.set("source_platform", platformFilter);
    void requestJson<PagedResponse<CaptureBatchRow>>(`/api/capture-batches?${params.toString()}`)
      .then((payload) => {
        if (latestBatchRequest.current !== requestId) return;
        setBatches({ ...payload, loading: false, error: "" });
      })
      .catch((error: unknown) => {
        if (latestBatchRequest.current !== requestId) return;
        const message = error instanceof ApiRequestError ? error.message : "采集批次加载失败。";
        setBatches((current) => ({ ...current, loading: false, error: message, rows: [] }));
      });
  }, [batchPage, batchRefreshTick, platformFilter, selectedBatch, view]);

  useEffect(() => {
    if (view !== "batches" || selectedBatch === null) return;
    const requestId = latestBatchCandidateRequest.current + 1;
    latestBatchCandidateRequest.current = requestId;
    setBatchCandidates((current) => ({ ...current, loading: true, error: "" }));
    const params = new URLSearchParams({
      page: String(batchCandidatePage),
      page_size: "50",
    });
    void requestJson<PagedResponse<BatchCandidateRow>>(
      `/api/capture-batches/${selectedBatch.id}/candidates?${params.toString()}`,
    )
      .then((payload) => {
        if (latestBatchCandidateRequest.current !== requestId) return;
        setBatchCandidates({ ...payload, loading: false, error: "" });
      })
      .catch((error: unknown) => {
        if (latestBatchCandidateRequest.current !== requestId) return;
        const message = error instanceof ApiRequestError ? error.message : "批次候选人加载失败。";
        setBatchCandidates((current) => ({ ...current, loading: false, error: message, rows: [] }));
      });
  }, [batchCandidatePage, batchCandidateRefreshTick, selectedBatch, view]);

  const latestLabel = status.latest_batch_id ? `#${status.latest_batch_id}` : "暂无批次";
  const statusLabel = !status.latest_batch_id
    ? "空数据库"
    : status.latest_batch_status === "completed"
      ? "已完成"
      : status.latest_batch_status;
  const platformOptions = useMemo(() => {
    const values = new Set<string>();
    for (const row of candidates.rows) values.add(row.latest_source_platform || row.source_platform);
    for (const row of batches.rows) values.add(row.source_platform);
    return Array.from(values).filter(Boolean).sort();
  }, [batches.rows, candidates.rows]);

  return (
    <div className="app-shell">
      <header className="shell-chrome">
        <div className="shell-header">
          <div className="brand">
            <div className="product-mark"><Users size={19} aria-hidden="true" /></div>
            <div><strong>人才工作台</strong><span>本地招聘工作空间</span></div>
          </div>
          <div className="shell-meta">
            <div className="service-health"><span className="status-dot" />本地服务正常</div>
            <span className="version">{status.version}</span>
          </div>
        </div>
        <nav className="workflow-nav" aria-label="主导航">
          <div className="workflow-scroll">
            <button className={view === "home" ? "nav-item active" : "nav-item"} onClick={() => setView("home")}>
              <Home size={16} aria-hidden="true" /><span>概览</span>
            </button>
            <button className={view === "candidates" ? "nav-item active" : "nav-item"} onClick={() => setView("candidates")}>
              <Users size={16} aria-hidden="true" /><span>候选人</span>
            </button>
            <button className={view === "batches" ? "nav-item active" : "nav-item"} onClick={() => setView("batches")}>
              <Layers3 size={16} aria-hidden="true" /><span>最近批次</span>
            </button>
            <button className="nav-item" disabled aria-label="岗位，待开发">
              <BriefcaseBusiness size={16} aria-hidden="true" /><span>岗位</span><small>待开发</small>
            </button>
            <button className={view === "settings" ? "nav-item active" : "nav-item"} onClick={() => setView("settings")}>
              <Settings size={16} aria-hidden="true" /><span>设置</span>
            </button>
          </div>
        </nav>
      </header>
      <main className="workspace">
        {view === "home" && (
          <div className="page-content">
            <div className="page-heading">
              <div><p className="eyebrow">工作空间概览</p><h1>招聘人才 Mapping 工作台</h1></div>
              <div className="database-badge"><Database size={17} aria-hidden="true" />数据库已就绪</div>
            </div>
            <section className="metrics" aria-label="工作台统计">
              <article><span>候选人总数</span><strong><CountUp to={status.candidate_count} /></strong><small>当前人才库</small></article>
              <article><span>采集批次</span><strong><CountUp to={status.batch_count} /></strong><small>{status.batch_count} 个批次</small></article>
              <article><span>最新批次</span><strong>{status.latest_batch_id ? <CountUp to={status.latest_batch_id} prefix="#" /> : latestLabel}</strong><small>{statusLabel}</small></article>
            </section>
            <section className="status-band">
              <div><Database size={21} aria-hidden="true" /><div><strong>阶段 2A 已接入候选人主档入口</strong><p>当前可以查看候选人列表、正式岗位绑定状态和最近采集批次，也能回看单批次快照。</p></div></div>
            </section>
            <section className="data-location">
              <div><h2>数据位置</h2><p>工作台正在读取的本地目录</p></div>
              <code>{status.data_dir}</code>
            </section>
          </div>
        )}
        {view === "candidates" && (
          <div className="page-content">
            <div className="page-heading">
              <div><p className="eyebrow">候选人主档</p><h1>候选人</h1></div>
              <Toolbar
                platformFilter={platformFilter}
                setPlatformFilter={setPlatformFilter}
                unboundOnly={unboundOnly}
                setUnboundOnly={setUnboundOnly}
                platformOptions={platformOptions}
                onRefresh={() => setCandidateRefreshTick((value) => value + 1)}
              />
            </div>
            <CandidateTable data={candidates} />
            <Pager
              page={candidatePage}
              pageSize={candidates.page_size}
              total={candidates.total}
              onPrevious={() => setCandidatePage((value) => Math.max(1, value - 1))}
              onNext={() => setCandidatePage((value) => value + 1)}
            />
          </div>
        )}
        {view === "batches" && (
          <div className="page-content">
            <div className="page-heading">
              <div><p className="eyebrow">最近采集批次</p><h1>采集批次</h1></div>
              <Toolbar
                platformFilter={platformFilter}
                setPlatformFilter={setPlatformFilter}
                unboundOnly={false}
                setUnboundOnly={() => undefined}
                platformOptions={platformOptions}
                onRefresh={() => setBatchRefreshTick((value) => value + 1)}
                hideUnboundToggle
              />
            </div>
            <BatchTable data={batches} onOpenBatch={(batch) => {
              setSelectedBatch(batch);
              setBatchCandidatePage(1);
              setBatchCandidateRefreshTick((value) => value + 1);
            }} />
            <Pager
              page={batchPage}
              pageSize={batches.page_size}
              total={batches.total}
              onPrevious={() => setBatchPage((value) => Math.max(1, value - 1))}
              onNext={() => setBatchPage((value) => value + 1)}
            />
            {selectedBatch !== null && (
              <>
                <div className="page-heading">
                  <div><p className="eyebrow">批次候选人快照</p><h1>批次 #{selectedBatch.id}</h1></div>
                  <div className="shell-meta">
                    <button className="icon-button" onClick={() => setSelectedBatch(null)} aria-label="返回批次列表" title="返回批次列表">
                      <ArrowLeft size={16} aria-hidden="true" />
                    </button>
                    <button className="icon-button" onClick={() => setBatchCandidateRefreshTick((value) => value + 1)} aria-label="刷新批次候选人" title="刷新批次候选人">
                      <RefreshCw size={16} aria-hidden="true" />
                    </button>
                  </div>
                </div>
                <BatchCandidateTable batchId={selectedBatch.id} data={batchCandidates} />
                <Pager
                  page={batchCandidatePage}
                  pageSize={batchCandidates.page_size}
                  total={batchCandidates.total}
                  onPrevious={() => setBatchCandidatePage((value) => Math.max(1, value - 1))}
                  onNext={() => setBatchCandidatePage((value) => value + 1)}
                />
              </>
            )}
          </div>
        )}
        {view === "settings" && (
          <div className="page-content settings-page">
            <div className="page-heading"><div><p className="eyebrow">只读设置</p><h1>本地配置</h1></div></div>
            <dl>
              <div><dt>数据目录</dt><dd>{status.data_dir}</dd></div>
              <div><dt>版本</dt><dd>{status.version}</dd></div>
              <div><dt>运行方式</dt><dd>仅限 127.0.0.1 本机访问</dd></div>
            </dl>
          </div>
        )}
      </main>
    </div>
  );
}

function Toolbar({
  platformFilter,
  setPlatformFilter,
  unboundOnly,
  setUnboundOnly,
  platformOptions,
  onRefresh,
  hideUnboundToggle = false,
}: {
  platformFilter: string;
  setPlatformFilter: (value: string) => void;
  unboundOnly: boolean;
  setUnboundOnly: (value: boolean) => void;
  platformOptions: string[];
  onRefresh: () => void;
  hideUnboundToggle?: boolean;
}) {
  return (
    <div className="shell-meta">
      <label>
        <span className="eyebrow">来源平台</span>
        <select value={platformFilter} onChange={(event) => setPlatformFilter(event.target.value)}>
          <option value="">全部</option>
          {platformOptions.map((platform) => <option key={platform} value={platform}>{platform}</option>)}
        </select>
      </label>
      {!hideUnboundToggle && (
        <label>
          <input
            type="checkbox"
            checked={unboundOnly}
            onChange={(event) => setUnboundOnly(event.target.checked)}
          />
          <span>只看未绑定岗位</span>
        </label>
      )}
      <button className="icon-button" onClick={onRefresh} aria-label="刷新" title="刷新">
        <RefreshCw size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

function CandidateTable({ data }: { data: Loadable<CandidateRow> }) {
  if (data.loading) return <section className="status-band"><div><strong>正在加载候选人…</strong></div></section>;
  if (data.error) return <section className="status-band"><div><strong>{data.error}</strong></div></section>;
  if (!data.rows.length) return <section className="status-band"><div><strong>当前筛选条件下还没有候选人。</strong></div></section>;
  return (
    <table>
      <thead>
        <tr>
          <th>候选人</th>
          <th>来源平台</th>
          <th>来源岗位文字</th>
          <th>岗位绑定</th>
          <th>最近采集时间</th>
          <th>最近批次</th>
          <th>本次结果</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map((row) => (
          <tr key={row.id}>
            <td>{row.name || `候选人 #${row.id}`}</td>
            <td>{row.latest_source_platform || row.source_platform || "unknown"}</td>
            <td>{row.latest_source_job_title || "未提供"}</td>
            <td>{Boolean(row.has_role_binding) ? "已绑定岗位" : "未绑定岗位"}</td>
            <td>{row.latest_capture_time || "—"}</td>
            <td>{row.latest_batch_id ? `#${row.latest_batch_id}` : "—"}</td>
            <td>{row.latest_ingest_status === "updated" ? "更新" : "新增"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BatchTable({
  data,
  onOpenBatch,
}: {
  data: Loadable<CaptureBatchRow>;
  onOpenBatch: (batch: CaptureBatchRow) => void;
}) {
  if (data.loading) return <section className="status-band"><div><strong>正在加载批次…</strong></div></section>;
  if (data.error) return <section className="status-band"><div><strong>{data.error}</strong></div></section>;
  if (!data.rows.length) return <section className="status-band"><div><strong>还没有采集批次。</strong></div></section>;
  return (
    <table>
      <thead>
        <tr>
          <th>批次 ID</th>
          <th>时间</th>
          <th>来源平台</th>
          <th>接收</th>
          <th>新增</th>
          <th>更新</th>
          <th>跳过</th>
          <th>失败</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map((row) => (
          <tr key={row.id}>
            <td>#{row.id}</td>
            <td>{row.start_time}</td>
            <td>{row.source_platform || "unknown"}</td>
            <td>{row.total_collected}</td>
            <td>{row.total_new}</td>
            <td>{row.total_updated}</td>
            <td>{row.total_skipped}</td>
            <td>{row.total_failed}</td>
            <td>
              <button className="icon-button" onClick={() => onOpenBatch(row)}>
                查看候选人
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BatchCandidateTable({
  batchId,
  data,
}: {
  batchId: number;
  data: Loadable<BatchCandidateRow>;
}) {
  if (data.loading) return <section className="status-band"><div><strong>正在加载批次 #{batchId} 的候选人…</strong></div></section>;
  if (data.error) return <section className="status-band"><div><strong>{data.error}</strong></div></section>;
  if (!data.rows.length) return <section className="status-band"><div><strong>批次 #{batchId} 暂无候选人快照。</strong></div></section>;
  return (
    <table>
      <thead>
        <tr>
          <th>候选人</th>
          <th>来源岗位文字</th>
          <th>采集时间</th>
          <th>本次结果</th>
          <th>正式岗位绑定</th>
          <th>原始快照</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map((row) => (
          <tr key={row.id}>
            <td>{row.name || `候选人 #${row.candidate_id}`}</td>
            <td>{row.job_title || "未提供"}</td>
            <td>{row.capture_time || "—"}</td>
            <td>{row.ingest_status === "updated" ? "更新" : "新增"}</td>
            <td>{Boolean(row.has_role_binding) ? "已绑定岗位" : "未绑定岗位"}</td>
            <td>{row.raw_card_text}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Pager({
  page,
  pageSize,
  total,
  onPrevious,
  onNext,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const maxPage = Math.max(1, Math.ceil(total / Math.max(pageSize, 1)));
  return (
    <div className="shell-meta">
      <button className="icon-button" onClick={onPrevious} disabled={page <= 1}>上一页</button>
      <span>第 {page} / {maxPage} 页，共 {total} 条</span>
      <button className="icon-button" onClick={onNext} disabled={page >= maxPage}>下一页</button>
    </div>
  );
}
