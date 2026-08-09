import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  BrainCircuit,
  BriefcaseBusiness,
  ChartNoAxesCombined,
  CheckCircle2,
  Database,
  FolderLock,
  Home,
  Layers3,
  RefreshCw,
  Settings,
  UserCheck,
  Users,
} from "lucide-react";

type SetupStatus = {
  setup_required: boolean;
  suggested_data_dir: string;
  configured_data_dir: string | null;
  existing_database_detected: boolean;
};

type AppStatus = {
  version: string;
  database_ready: boolean;
  data_dir: string;
  candidate_count: number;
  batch_count: number;
  latest_batch_id: number;
  latest_batch_status: string;
};

type ApiError = { error?: { code?: string; message?: string } };

class ApiRequestError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiRequestError(
      "network_error",
      "无法连接本地服务，请确认网页程序仍在运行。",
    );
  }
  const payload = (await response.json()) as T & ApiError;
  if (!response.ok) {
    throw new ApiRequestError(
      payload.error?.code || "request_failed",
      payload.error?.message || "本地服务请求失败。请稍后重试。",
    );
  }
  return payload;
}

const futureNavigation = [
  { label: "采集批次", icon: Layers3 },
  { label: "候选人", icon: Users },
  { label: "岗位", icon: BriefcaseBusiness },
  { label: "AI 分析", icon: BrainCircuit },
  { label: "人工复核", icon: UserCheck },
  { label: "Mapping 与报告", icon: ChartNoAxesCombined },
];

function Loading() {
  return (
    <main className="center-state" aria-live="polite">
      <span className="loader" aria-hidden="true" />
      <p>正在连接本地工作台...</p>
    </main>
  );
}

function ServiceError({ retry }: { retry: () => void }) {
  return (
    <main className="center-state error-state">
      <Database size={30} aria-hidden="true" />
      <h1>本地服务暂时不可用</h1>
      <p>请确认网页程序仍在运行，然后重新连接。</p>
      <button className="primary-button" onClick={retry}>
        <RefreshCw size={17} aria-hidden="true" />
        重新连接
      </button>
    </main>
  );
}

function DatabaseNotReady({ retry }: { retry: () => void }) {
  return (
    <main className="center-state error-state">
      <Database size={30} aria-hidden="true" />
      <h1>数据库尚未就绪</h1>
      <p>本地服务已启动，但数据目录还没有准备完成。</p>
      <button className="primary-button" onClick={retry}>
        <RefreshCw size={17} aria-hidden="true" />
        重新检查
      </button>
    </main>
  );
}

function SetupWizard({ status, onComplete }: { status: SetupStatus; onComplete: () => Promise<void> }) {
  const [dataDir, setDataDir] = useState(status.suggested_data_dir);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await requestJson("/api/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data_dir: dataDir }),
      });
      await onComplete();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "设置失败，请检查数据目录。 ");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="setup-layout">
      <section className="setup-intro">
        <div className="product-mark"><Users size={22} aria-hidden="true" /></div>
        <p className="eyebrow">招聘人才 Mapping 工作台</p>
        <h1>欢迎使用本地工作台</h1>
        <p>数据保留在这台电脑上。先确认唯一的数据目录，后续启动会继续使用同一份人才库。</p>
        <div className="privacy-note">
          <FolderLock size={20} aria-hidden="true" />
          <span>不会移动旧数据，也不会覆盖现有配置。</span>
        </div>
      </section>
      <section className="setup-panel" aria-labelledby="setup-title">
        <h2 id="setup-title">选择数据目录</h2>
        <p className="muted">路径必须是本机可写的独立文件夹。</p>
        {status.existing_database_detected && (
          <div className="notice success-notice">
            <CheckCircle2 size={18} aria-hidden="true" />
            <span>检测到现有数据库，将继续读取原有人才数据。</span>
          </div>
        )}
        <form onSubmit={submit}>
          <label htmlFor="data-dir">数据目录</label>
          <input
            id="data-dir"
            value={dataDir}
            onChange={(event) => setDataDir(event.target.value)}
            spellCheck={false}
            autoComplete="off"
          />
          {error && <div className="notice error-notice" role="alert">{error}</div>}
          <button className="primary-button full-width" disabled={saving || !dataDir.trim()}>
            {saving ? "正在初始化..." : "确认并开始使用"}
          </button>
        </form>
      </section>
    </main>
  );
}

function Workbench({ status }: { status: AppStatus }) {
  const [view, setView] = useState<"home" | "settings">("home");
  const latestLabel = status.latest_batch_id ? `#${status.latest_batch_id}` : "暂无批次";
  const statusLabel = !status.latest_batch_id
    ? "空数据库"
    : status.latest_batch_status === "completed"
      ? "已完成"
      : status.latest_batch_status;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="product-mark"><Users size={20} aria-hidden="true" /></div>
          <div><strong>人才工作台</strong><span>本地安全模式</span></div>
        </div>
        <nav aria-label="主导航">
          <button className={view === "home" ? "nav-item active" : "nav-item"} onClick={() => setView("home")}>
            <Home size={18} aria-hidden="true" /><span>首页</span>
          </button>
          {futureNavigation.map(({ label, icon: Icon }) => (
            <button className="nav-item" disabled key={label} aria-label={`${label}，待开发`}>
              <Icon size={18} aria-hidden="true" /><span>{label}</span><small>待开发</small>
            </button>
          ))}
          <button className={view === "settings" ? "nav-item active" : "nav-item"} onClick={() => setView("settings")}>
            <Settings size={18} aria-hidden="true" /><span>设置</span>
          </button>
        </nav>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div className="service-health"><span className="status-dot" />本地服务正常</div>
          <span className="version">版本 {status.version}</span>
        </header>
        {view === "home" ? (
          <div className="page-content">
            <div className="page-heading">
              <div><p className="eyebrow">阶段 1</p><h1>招聘人才 Mapping 工作台</h1></div>
              <div className="database-badge"><Database size={17} aria-hidden="true" />数据库已就绪</div>
            </div>
            <section className="metrics" aria-label="工作台统计">
              <article><span>候选人总数</span><strong>{status.candidate_count.toLocaleString("zh-CN")}</strong><small>当前人才库</small></article>
              <article><span>采集批次</span><strong>{status.batch_count}</strong><small>{status.batch_count} 个批次</small></article>
              <article><span>最新批次</span><strong>{latestLabel}</strong><small>{statusLabel}</small></article>
            </section>
            <section className="status-band">
              <div><CheckCircle2 size={21} aria-hidden="true" /><div><strong>本地网页基础已启用</strong><p>当前阶段提供安全启动、数据读取与运行状态；招聘业务页面将在后续阶段接入。</p></div></div>
            </section>
            <section className="data-location">
              <div><h2>数据位置</h2><p>工作台正在读取的本地目录</p></div>
              <code>{status.data_dir}</code>
            </section>
          </div>
        ) : (
          <div className="page-content settings-page">
            <div className="page-heading"><div><p className="eyebrow">只读设置</p><h1>本地配置</h1></div></div>
            <dl>
              <div><dt>数据目录</dt><dd>{status.data_dir}</dd></div>
              <div><dt>版本</dt><dd>{status.version}</dd></div>
              <div><dt>运行方式</dt><dd>仅限 127.0.0.1 本机访问</dd></div>
            </dl>
            <p className="muted">运行期间不能更换数据目录。</p>
          </div>
        )}
      </main>
    </div>
  );
}

export default function App() {
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [serviceError, setServiceError] = useState(false);
  const [databaseNotReady, setDatabaseNotReady] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setServiceError(false);
    setDatabaseNotReady(false);
    try {
      const setupStatus = await requestJson<SetupStatus>("/api/setup/status");
      setSetup(setupStatus);
      if (!setupStatus.setup_required) {
        setStatus(await requestJson<AppStatus>("/api/app/status"));
      }
    } catch (caught) {
      if (caught instanceof ApiRequestError && caught.code === "database_not_ready") {
        setDatabaseNotReady(true);
      } else {
        setServiceError(true);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const finishSetup = useCallback(async () => {
    setStatus(await requestJson<AppStatus>("/api/app/status"));
    setSetup((current) => current ? { ...current, setup_required: false } : current);
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <Loading />;
  if (serviceError) return <ServiceError retry={() => void load()} />;
  if (databaseNotReady) return <DatabaseNotReady retry={() => void load()} />;
  if (setup?.setup_required) return <SetupWizard status={setup} onComplete={finishSetup} />;
  if (status) return <Workbench status={status} />;
  return <ServiceError retry={() => void load()} />;
}
