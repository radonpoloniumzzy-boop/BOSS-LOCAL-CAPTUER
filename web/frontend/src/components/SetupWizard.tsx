import { FormEvent, useState } from "react";
import { CheckCircle2, FolderLock, Users } from "lucide-react";

import { requestJson, SetupStatus } from "../api";

export function SetupWizard({
  status,
  onComplete,
}: {
  status: SetupStatus;
  onComplete: () => Promise<void>;
}) {
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
      setError(caught instanceof Error ? caught.message : "设置失败，请检查数据目录。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="setup-layout">
      <section className="setup-intro">
        <div className="product-mark">
          <Users size={22} aria-hidden="true" />
        </div>
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
          {error && (
            <div className="notice error-notice" role="alert">
              {error}
            </div>
          )}
          <button className="primary-button full-width" disabled={saving || !dataDir.trim()}>
            {saving ? "正在初始化..." : "确认并开始使用"}
          </button>
        </form>
      </section>
    </main>
  );
}
