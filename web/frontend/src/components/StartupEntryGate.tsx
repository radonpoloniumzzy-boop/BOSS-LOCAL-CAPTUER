import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  CircleDashed,
  Database,
  Link2,
  LoaderCircle,
  Plug2,
  RefreshCw,
  Server,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { ApiRequestError, AppStatus, HealthStatus, PluginConnectionStatus, requestJson } from "../api";

type StartupFault = { code: string; message: string };
type CheckState = "waiting" | "checking" | "ready" | "needs_action" | "failed";

type StartupEntryGateProps = {
  onEnter: (status: AppStatus) => void;
};

type CheckItem = {
  id: string;
  label: string;
  state: CheckState;
  detail: string;
};

const REQUIRED_CAPABILITIES = ["phase2c_pairing", "batch_markdown_export"];

const recoveryMessages: Record<string, string> = {
  configured_database_missing: "已配置的人才库文件不存在，请检查 D 盘、移动盘和数据库备份后重新检查。",
  database_corrupt: "人才库文件无法读取，请停止操作并从可用备份恢复。",
  unsupported_schema: "人才库版本高于当前程序支持版本，请升级网页工作台后再试。",
  database_upgrade_failed: "人才库升级未完成，请查看本机日志并确认恢复方案。",
  database_in_use: "桌面端正在使用人才库。请先关闭桌面端，再点击重新检查。",
  database_not_ready: "人才库尚未完成准备，请先完成首次设置后再进入工作台。",
};

const hiddenSensitivePatterns = /(token|pairing[\s_-]*code|credential)/i;

function safeMessage(message: string, fallback: string) {
  return hiddenSensitivePatterns.test(message) ? fallback : message;
}

function stateLabel(state: CheckState) {
  switch (state) {
    case "checking":
      return "检查中";
    case "ready":
      return "已就绪";
    case "needs_action":
      return "需要处理";
    case "failed":
      return "检查失败";
    default:
      return "等待检查";
  }
}

function iconForState(state: CheckState) {
  switch (state) {
    case "checking":
      return <LoaderCircle size={16} className="spin-inline" aria-hidden="true" />;
    case "ready":
      return <CheckCircle2 size={16} aria-hidden="true" />;
    case "needs_action":
    case "failed":
      return <TriangleAlert size={16} aria-hidden="true" />;
    default:
      return <CircleDashed size={16} aria-hidden="true" />;
  }
}

export function StartupEntryGate({ onEnter }: StartupEntryGateProps) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [plugin, setPlugin] = useState<PluginConnectionStatus | null>(null);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [fault, setFault] = useState<StartupFault | null>(null);
  const [checking, setChecking] = useState(true);
  const [runId, setRunId] = useState(0);

  const recheck = useCallback(() => {
    setRunId((value) => value + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      setChecking(true);
      setHealth(null);
      setPlugin(null);
      setStatus(null);
      setFault(null);

      try {
        const nextHealth = await requestJson<HealthStatus>("/api/health");
        if (cancelled) return;
        setHealth(nextHealth);

        const [statusResult, pluginResult] = await Promise.allSettled([
          requestJson<AppStatus>("/api/app/status"),
          requestJson<PluginConnectionStatus>("/api/plugin-connection/status"),
        ]);
        if (cancelled) return;

        if (statusResult.status === "fulfilled") {
          setStatus(statusResult.value);
        } else if (statusResult.reason instanceof ApiRequestError && recoveryMessages[statusResult.reason.code]) {
          setFault({
            code: statusResult.reason.code,
            message: recoveryMessages[statusResult.reason.code],
          });
        } else {
          throw statusResult.reason;
        }

        if (pluginResult.status === "fulfilled") {
          setPlugin(pluginResult.value);
        } else {
          setPlugin(null);
        }
      } catch (error) {
        if (cancelled) return;
        const message =
          error instanceof ApiRequestError
            ? safeMessage(error.message, "无法连接本地服务，请确认网页程序仍在运行。")
            : "无法连接本地服务，请确认网页程序仍在运行。";
        setFault({ code: "service_unavailable", message });
      } finally {
        if (!cancelled) {
          setChecking(false);
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const capabilitiesReady = useMemo(() => {
    if (!health) return false;
    return REQUIRED_CAPABILITIES.every((item) => health.capabilities.includes(item));
  }, [health]);

  const checks = useMemo<CheckItem[]>(() => {
    const serviceOk = Boolean(health && health.status === "ok" && health.service === "recruiting-talent-workbench");
    const dataDir = status?.data_dir || plugin?.data_dir || "等待检查结果";

    return [
      {
        id: "service",
        label: "本地服务是否为正确版本",
        state: checking && !health ? "checking" : serviceOk ? "ready" : fault?.code === "service_unavailable" ? "failed" : "needs_action",
        detail: serviceOk ? `已连接 ${health?.version}` : "需要连接到本地网页工作台服务。",
      },
      {
        id: "capabilities",
        label: "Phase 2C 必要能力是否存在",
        state: checking && !health ? "checking" : capabilitiesReady ? "ready" : serviceOk ? "needs_action" : "waiting",
        detail: capabilitiesReady ? REQUIRED_CAPABILITIES.join(" / ") : "当前服务缺少必要能力，请确认已启动正确版本。",
      },
      {
        id: "database",
        label: "人才库是否可访问",
        state: checking && !status && !fault ? "checking" : status?.status === "ready" ? "ready" : fault ? "needs_action" : "waiting",
        detail: status?.status === "ready" ? "人才库可访问，准备进入工作台。" : fault?.message || "等待检查结果。",
      },
      {
        id: "data-dir",
        label: "当前数据目录",
        state: checking && dataDir === "等待检查结果" ? "checking" : dataDir === "等待检查结果" ? "waiting" : "ready",
        detail: dataDir,
      },
      {
        id: "database-lock",
        label: "数据库是否被其他实例占用",
        state:
          checking && !status && !fault
            ? "checking"
            : fault?.code === "database_in_use"
              ? "needs_action"
              : status?.status === "ready"
                ? "ready"
                : fault
                  ? "waiting"
                  : "waiting",
        detail:
          fault?.code === "database_in_use"
            ? "桌面端正在使用人才库，请先关闭桌面端后重新检查。"
            : status?.status === "ready"
              ? "当前未发现其他实例占用人才库。"
              : "等待检查结果。",
      },
      {
        id: "plugin",
        label: "浏览器插件是否已连接",
        state: checking && !plugin ? "checking" : plugin?.connected ? "ready" : "needs_action",
        detail: plugin?.connected
          ? `插件连接已验证：${plugin.last_verified_at || "刚刚完成"}`
          : "工作台可使用，采集前请在设置中连接浏览器插件。",
      },
    ];
  }, [checking, fault, health, plugin, status, capabilitiesReady]);

  const canEnter = Boolean(health && status?.status === "ready" && capabilitiesReady);

  return (
    <main className="startup-gate-layout">
      <section className="startup-gate-hero page-enter">
        <p className="eyebrow">使用前确认</p>
        <h1>准备进入招聘人才工作台</h1>
        <p className="page-description">
          在进入工作台之前，我们先确认本地服务、人才库、插件连接和数据库占用状态，避免把你带进一个看起来已经打开、实际却不能工作的页面。
        </p>
      </section>

      <section className="startup-gate-panel page-enter" aria-labelledby="startup-gate-title">
        <div className="startup-gate-header">
          <div>
            <h2 id="startup-gate-title">启动确认</h2>
            <p className="muted">只有核心服务与人才库都已就绪时，才能进入工作台。</p>
          </div>
          <button className="secondary-button" onClick={recheck} disabled={checking}>
            <RefreshCw size={15} aria-hidden="true" />重新检查
          </button>
        </div>

        <div className="startup-check-list" role="list">
          {checks.map((item, index) => (
            <article
              key={item.id}
              role="listitem"
              className={`startup-check-item state-${item.state}`}
              style={{ animationDelay: `${index * 36}ms` }}
            >
              <div className="startup-check-icon">{iconForState(item.state)}</div>
              <div className="startup-check-copy">
                <div className="startup-check-topline">
                  <strong>{item.label}</strong>
                  <span
                    className={`status-badge ${
                      item.state === "ready"
                        ? "success"
                        : item.state === "checking"
                          ? "info"
                          : item.state === "failed"
                            ? "warning"
                            : "muted"
                    }`}
                  >
                    {stateLabel(item.state)}
                  </span>
                </div>
                <p>{item.detail}</p>
              </div>
            </article>
          ))}
        </div>

        {!plugin?.connected && !checking && (
          <div className="notice startup-inline-note" role="status">
            <Plug2 size={18} aria-hidden="true" />
            <span>工作台可使用，采集前请在设置中连接浏览器插件。</span>
          </div>
        )}

        {fault && (
          <div className={`notice ${fault.code === "service_unavailable" ? "error-notice" : "error-notice"}`} role="alert">
            <TriangleAlert size={18} aria-hidden="true" />
            <span>{fault.message}</span>
          </div>
        )}

        <div className="startup-gate-actions">
          <button className="primary-button" disabled={!canEnter} onClick={() => status && onEnter(status)}>
            <ShieldCheck size={16} aria-hidden="true" />进入工作台
          </button>
        </div>
      </section>

      <section className="startup-gate-side page-enter" aria-label="检查摘要">
        <div className="summary-card">
          <Server size={18} aria-hidden="true" />
          <div>
            <strong>本地服务</strong>
            <span>{health?.version || "等待检查"}</span>
          </div>
        </div>
        <div className="summary-card">
          <Database size={18} aria-hidden="true" />
          <div>
            <strong>数据目录</strong>
            <span>{status?.data_dir || plugin?.data_dir || "等待检查"}</span>
          </div>
        </div>
        <div className="summary-card">
          <Link2 size={18} aria-hidden="true" />
          <div>
            <strong>插件连接</strong>
            <span>{plugin?.connected ? "已连接" : "未连接"}</span>
          </div>
        </div>
      </section>
    </main>
  );
}
