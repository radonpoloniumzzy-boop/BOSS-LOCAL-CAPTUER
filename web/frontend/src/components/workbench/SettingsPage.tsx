import { useEffect, useState } from "react";
import { Check, Copy, Link2, RotateCcw, ShieldCheck, Unplug } from "lucide-react";
import { ApiRequestError, AppStatus, PluginConnectionStatus, requestJson } from "../../api";

export function SettingsPage({ status }: { status: AppStatus }) {
  const [connection, setConnection] = useState<PluginConnectionStatus | null>(null); const [code, setCode] = useState(""); const [expiresAt, setExpiresAt] = useState(""); const [message, setMessage] = useState(""); const [loading, setLoading] = useState(false);
  const load = () => void requestJson<PluginConnectionStatus>("/api/plugin-connection/status").then(setConnection).catch(() => setConnection(null));
  useEffect(load, []);
  const generate = async () => { setLoading(true); setMessage(""); try { const result = await requestJson<{ pairing_code: string; expires_at: string }>("/api/plugin-connection/pairing-code", { method: "POST" }); setCode(result.pairing_code); setExpiresAt(result.expires_at); } catch (error) { setMessage(error instanceof ApiRequestError ? error.message : "连接码生成失败。"); } finally { setLoading(false); } };
  const copy = async () => { if (!code) return; await navigator.clipboard.writeText(code); setMessage("连接码已复制，有效期内粘贴到浏览器插件即可。"); };
  const revoke = async () => { setLoading(true); try { await requestJson("/api/plugin-connection/revoke", { method: "POST" }); setCode(""); setExpiresAt(""); setMessage("现有插件连接已撤销。旧凭证已失效，请重新配对。"); load(); } catch (error) { setMessage(error instanceof ApiRequestError ? error.message : "撤销连接失败。"); } finally { setLoading(false); } };
  return <div className="page-content settings-page page-enter"><div className="page-heading"><div><p className="eyebrow">本机与连接</p><h1>设置</h1><p className="page-description">管理人才库位置、网页服务和浏览器插件连接。</p></div></div>
    <div className="settings-grid"><section className="settings-section"><div className="section-title"><ShieldCheck size={19} /><div><h2>本地服务</h2><p>数据仅保留在这台电脑。</p></div></div><dl><div><dt>服务状态</dt><dd><span className="status-badge success"><Check size={12} />正常</span></dd></div><div><dt>服务地址</dt><dd>{connection?.api_base || "http://127.0.0.1:17864"}</dd></div><div><dt>数据目录</dt><dd className="path-value">{status.data_dir}</dd></div></dl></section>
      <section className="settings-section pairing-section"><div className="section-title"><Link2 size={19} /><div><h2>浏览器插件连接</h2><p>连接信息只用于本机插件，不会上传到外部服务。</p></div></div><div className="connection-state"><span className={`status-dot ${connection?.connected ? "" : "idle"}`} /><div><strong>{connection?.connected ? "插件已验证" : "等待插件配对"}</strong><small>{connection?.last_verified_at ? `最近验证：${connection.last_verified_at}` : "生成一次性连接码后，在 5 分钟内粘贴到插件。"}</small></div></div>
        {code && <div className="pairing-code" aria-label="插件连接码"><strong>{code}</strong><small>有效至 {expiresAt.replace("T", " ")}</small></div>}
        <div className="button-row"><button className="primary-button" disabled={loading} onClick={generate}>{code ? <RotateCcw size={15} /> : <Link2 size={15} />}{code ? "重新生成" : "生成插件连接码"}</button><button className="secondary-button" disabled={!code} onClick={copy}><Copy size={15} />复制连接码</button><button className="secondary-button danger" disabled={loading} onClick={revoke}><Unplug size={15} />撤销现有连接</button></div>{message && <p className="inline-feedback" role="status">{message}</p>}</section>
      <section className="settings-section launcher-note"><div className="section-title"><RotateCcw size={19} /><div><h2>一键启动</h2><p>以后请运行项目根目录的“launch_web_workbench.cmd”。它会检查人才库、启动服务并自动打开浏览器。</p></div></div></section>
    </div>
  </div>;
}
