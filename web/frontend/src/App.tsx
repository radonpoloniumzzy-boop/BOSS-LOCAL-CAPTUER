import { useCallback, useEffect, useState } from "react";
import { Database, RefreshCw } from "lucide-react";

import { ApiRequestError, AppStatus, requestJson, SetupStatus } from "./api";
import { SetupWizard } from "./components/SetupWizard";
import { Workbench } from "./components/Workbench";

type StartupFault = { code: string; message: string };

const databaseRecoveryTitles: Record<string, string> = {
  configured_database_missing: "找不到已配置的人才库",
  database_corrupt: "人才库文件无法读取",
  unsupported_schema: "人才库版本暂不支持",
  database_upgrade_failed: "人才库升级未完成",
  database_in_use: "人才库正在使用中",
  database_not_ready: "数据库尚未就绪",
};

function Loading() {
  return <main className="center-state" aria-live="polite"><span className="loader" aria-hidden="true" /><p>正在连接本地工作台…</p></main>;
}

function ServiceError({ retry }: { retry: () => void }) {
  return (
    <main className="center-state error-state">
      <Database size={30} aria-hidden="true" />
      <h1>本地服务暂时不可用</h1>
      <p>请确认网页程序仍在运行，然后重新连接。</p>
      <button className="primary-button" onClick={retry}><RefreshCw size={17} aria-hidden="true" />重新连接</button>
    </main>
  );
}

function DatabaseRecovery({ fault, retry }: { fault: StartupFault; retry: () => void }) {
  return (
    <main className="center-state error-state">
      <Database size={30} aria-hidden="true" />
      <h1>{databaseRecoveryTitles[fault.code] || "人才库需要恢复"}</h1>
      <p>{fault.message}</p>
      <button className="primary-button" onClick={retry}><RefreshCw size={17} aria-hidden="true" />重新检查</button>
    </main>
  );
}

export default function App() {
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [serviceError, setServiceError] = useState(false);
  const [databaseFault, setDatabaseFault] = useState<StartupFault | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setServiceError(false);
    setDatabaseFault(null);
    try {
      const setupStatus = await requestJson<SetupStatus>("/api/setup/status");
      setSetup(setupStatus);
      if (!setupStatus.setup_required) {
        setStatus(await requestJson<AppStatus>("/api/app/status"));
      }
    } catch (caught) {
      if (caught instanceof ApiRequestError && databaseRecoveryTitles[caught.code]) {
        setDatabaseFault({ code: caught.code, message: caught.message });
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
  if (databaseFault) return <DatabaseRecovery fault={databaseFault} retry={() => void load()} />;
  if (setup?.setup_required) return <SetupWizard status={setup} onComplete={finishSetup} />;
  if (status) return <Workbench status={status} />;
  return <ServiceError retry={() => void load()} />;
}
