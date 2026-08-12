import { useCallback, useEffect, useState } from "react";
import { Database, RefreshCw } from "lucide-react";

import { ApiRequestError, requestJson, SetupStatus, AppStatus } from "./api";
import { SetupWizard } from "./components/SetupWizard";
import { StartupEntryGate } from "./components/StartupEntryGate";
import { Workbench } from "./components/Workbench";

function Loading() {
  return (
    <main className="center-state" aria-live="polite">
      <span className="loader" aria-hidden="true" />
      <p>正在连接本地工作台…</p>
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
        <RefreshCw size={17} aria-hidden="true" />重新连接
      </button>
    </main>
  );
}

export default function App() {
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [enteredWorkbench, setEnteredWorkbench] = useState(false);
  const [loading, setLoading] = useState(true);
  const [serviceError, setServiceError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setServiceError(false);
    try {
      const setupStatus = await requestJson<SetupStatus>("/api/setup/status");
      setSetup(setupStatus);
      if (setupStatus.setup_required) {
        setEnteredWorkbench(false);
        setStatus(null);
      }
    } catch (caught) {
      if (caught instanceof ApiRequestError) {
        setServiceError(true);
      } else {
        setServiceError(true);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const finishSetup = useCallback(async () => {
    setSetup((current) => (current ? { ...current, setup_required: false } : current));
    setEnteredWorkbench(false);
    setStatus(null);
  }, []);

  const enterWorkbench = useCallback((nextStatus: AppStatus) => {
    setStatus(nextStatus);
    setEnteredWorkbench(true);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <Loading />;
  if (serviceError) return <ServiceError retry={() => void load()} />;
  if (setup?.setup_required) return <SetupWizard status={setup} onComplete={finishSetup} />;
  if (!enteredWorkbench) return <StartupEntryGate onEnter={enterWorkbench} />;
  if (status) return <Workbench status={status} />;
  return <ServiceError retry={() => void load()} />;
}
