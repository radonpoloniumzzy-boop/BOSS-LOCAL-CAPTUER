import { useState } from "react";
import {
  BrainCircuit,
  BriefcaseBusiness,
  ChartNoAxesCombined,
  CheckCircle2,
  Database,
  Home,
  Layers3,
  Settings,
  UserCheck,
  Users,
} from "lucide-react";

import { AppStatus } from "../api";
import { CountUp } from "./CountUp";

const futureNavigation = [
  { label: "采集批次", icon: Layers3 },
  { label: "候选人", icon: Users },
  { label: "岗位", icon: BriefcaseBusiness },
  { label: "AI 分析", icon: BrainCircuit },
  { label: "人工复核", icon: UserCheck },
  { label: "Mapping 与报告", icon: ChartNoAxesCombined },
];

export function Workbench({ status }: { status: AppStatus }) {
  const [view, setView] = useState<"home" | "settings">("home");
  const latestLabel = status.latest_batch_id ? `#${status.latest_batch_id}` : "暂无批次";
  const statusLabel = !status.latest_batch_id
    ? "空数据库"
    : status.latest_batch_status === "completed"
      ? "已完成"
      : status.latest_batch_status;

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
            <button
              className={view === "settings" ? "icon-button active" : "icon-button"}
              onClick={() => setView("settings")}
              aria-label="设置"
              title="设置"
            >
              <Settings size={17} aria-hidden="true" />
            </button>
          </div>
        </div>
        <nav className="workflow-nav" aria-label="主导航">
          <div className="workflow-scroll">
            <button className={view === "home" ? "nav-item active" : "nav-item"} onClick={() => setView("home")}>
              <Home size={16} aria-hidden="true" /><span>概览</span>
            </button>
            {futureNavigation.map(({ label, icon: Icon }) => (
              <button className="nav-item" disabled key={label} aria-label={`${label}，待开发`}>
                <Icon size={16} aria-hidden="true" /><span>{label}</span><small>待开发</small>
              </button>
            ))}
          </div>
        </nav>
      </header>
      <main className="workspace">
        {view === "home" ? (
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
