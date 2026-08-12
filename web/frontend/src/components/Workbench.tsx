import { useState } from "react";
import { BriefcaseBusiness, Database, Home, Layers3, Settings, Users } from "lucide-react";

import { AppStatus } from "../api";
import { CountUp } from "./CountUp";
import { BatchesPage } from "./workbench/BatchesPage";
import { CandidatesPage } from "./workbench/CandidatesPage";
import { SettingsPage } from "./workbench/SettingsPage";

type View = "home" | "candidates" | "batches" | "settings";

export function Workbench({ status }: { status: AppStatus }) {
  const [view, setView] = useState<View>("home");
  const [requestedBatch, setRequestedBatch] = useState<number | null>(null);

  const openBatch = (batchId: number) => {
    setRequestedBatch(batchId);
    setView("batches");
  };

  const latestLabel = status.latest_batch_id ? `#${status.latest_batch_id}` : "暂无批次";

  return (
    <div className="app-shell">
      <div className="ambient-grid" aria-hidden="true" />
      <header className="shell-chrome">
        <div className="shell-header">
          <div className="brand">
            <div className="product-mark">
              <Users size={19} />
            </div>
            <div>
              <strong>人才工作台</strong>
              <span>本地招聘情报空间</span>
            </div>
          </div>
          <div className="shell-meta">
            <div className="service-health">
              <span className="status-dot" />本地服务正常
            </div>
            <span className="version">{status.version}</span>
          </div>
        </div>
        <nav className="workflow-nav" aria-label="主导航">
          <div className="workflow-scroll">
            <NavButton active={view === "home"} onClick={() => setView("home")} icon={<Home size={16} />} label="概览" />
            <NavButton active={view === "candidates"} onClick={() => setView("candidates")} icon={<Users size={16} />} label="候选人" />
            <NavButton active={view === "batches"} onClick={() => setView("batches")} icon={<Layers3 size={16} />} label="最近批次" />
            <button className="nav-item" disabled aria-label="岗位，待开发">
              <BriefcaseBusiness size={16} />
              <span>岗位</span>
              <small>待开发</small>
            </button>
            <NavButton active={view === "settings"} onClick={() => setView("settings")} icon={<Settings size={16} />} label="设置" />
          </div>
        </nav>
      </header>
      <main className="workspace">
        {view === "home" && (
          <div className="page-content page-enter">
            <div className="page-heading">
              <div>
                <p className="eyebrow">工作空间概览</p>
                <h1>招聘人才 Mapping 工作台</h1>
                <p className="page-description">候选人主档、采集批次与本地连接状态，一处完成。</p>
              </div>
              <div className="database-badge">
                <Database size={17} />数据库已就绪
              </div>
            </div>
            <section className="metrics">
              <article>
                <span>候选人总数</span>
                <strong>
                  <CountUp to={status.candidate_count} />
                </strong>
                <small>当前人才库</small>
              </article>
              <article>
                <span>采集批次</span>
                <strong>
                  <CountUp to={status.batch_count} />
                </strong>
                <small>{status.batch_count} 个批次</small>
              </article>
              <article>
                <span>最新批次</span>
                <strong>{status.latest_batch_id ? <CountUp to={status.latest_batch_id} prefix="#" /> : latestLabel}</strong>
                <small>
                  {!status.latest_batch_id
                    ? "空数据库"
                    : status.latest_batch_status === "completed"
                      ? "已完成"
                      : status.latest_batch_status}
                </small>
              </article>
            </section>
            <section className="status-band">
              <div>
                <Database size={21} />
                <div>
                  <strong>本地人才库运行正常</strong>
                  <p>网页工作台与浏览器插件使用同一人才库；桌面兼容模式和 Web 模式保持互斥。</p>
                </div>
              </div>
            </section>
            <section className="data-location">
              <div>
                <h2>数据位置</h2>
                <p>当前工作台读取的本地目录</p>
              </div>
              <code>{status.data_dir}</code>
            </section>
          </div>
        )}
        {view === "candidates" && <CandidatesPage onOpenBatch={openBatch} />}
        {view === "batches" && <BatchesPage initialBatchId={requestedBatch} onInitialBatchConsumed={() => setRequestedBatch(null)} />}
        {view === "settings" && <SettingsPage status={status} />}
      </main>
    </div>
  );
}

function NavButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button className={active ? "nav-item active" : "nav-item"} onClick={onClick}>
      {icon}
      <span>{label}</span>
    </button>
  );
}
