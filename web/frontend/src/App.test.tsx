import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const response = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) } as Response);

const setupRequired = {
  setup_required: true,
  suggested_data_dir: "D:\\codex\\BOSS-LOCAL-CAPTURE-review\\data",
  configured_data_dir: null,
  existing_database_detected: true,
};

const readyStatus = {
  status: "ready" as const,
  version: "0.2.0-phase2c",
  database_ready: true,
  data_dir: "D:\\HR-Workbench-Data",
  candidate_count: 1284,
  batch_count: 17,
  latest_batch_id: 17,
  latest_batch_status: "completed",
};

const readyHealth = {
  status: "ok",
  service: "recruiting-talent-workbench",
  version: "0.2.0-phase2c",
  capabilities: ["phase2c_pairing", "batch_markdown_export"],
};

const pluginDisconnected = {
  service_ok: true,
  api_base: "http://127.0.0.1:17864",
  connected: false,
  last_verified_at: "",
  data_dir: readyStatus.data_dir,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

afterEach(() => vi.restoreAllMocks());

describe("local workbench shell", () => {
  it("renders the first-run recommendation and existing database notice", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(setupRequired)));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "选择数据目录" })).toBeInTheDocument();
    expect(screen.getByDisplayValue(setupRequired.suggested_data_dir)).toBeInTheDocument();
    expect(screen.getByText("检测到现有数据库，将继续读取原有人才数据。")).toBeInTheDocument();
  });

  it("shows a backend path validation error", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => response(setupRequired))
      .mockImplementationOnce(() =>
        response(
          { error: { code: "invalid_data_directory", message: "不能把磁盘根目录作为数据目录。" } },
          false,
          400,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await user.clear(await screen.findByLabelText("数据目录"));
    await user.type(screen.getByLabelText("数据目录"), "D:\\");
    await user.click(screen.getByRole("button", { name: "确认并开始使用" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("不能把磁盘根目录作为数据目录");
  });

  it("shows the startup confirmation gate after setup succeeds", async () => {
    const fetchMock = vi.fn((input: string | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/setup/status") return response(setupRequired);
      if (url === "/api/setup" && init?.method === "POST") return response({ setup_completed: true });
      if (url === "/api/health") return response(readyHealth);
      if (url === "/api/app/status") return response(readyStatus);
      if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "确认并开始使用" }));

    expect(await screen.findByRole("heading", { name: "准备进入招聘人才工作台" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "进入工作台" })).toBeEnabled();
    expect(screen.getAllByText("工作台可使用，采集前请在设置中连接浏览器插件。").length).toBeGreaterThan(0);
  });

  it("allows entering the workbench when the plugin is not connected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") return response(readyHealth);
        if (url === "/api/app/status") return response(readyStatus);
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "准备进入招聘人才工作台" })).toBeInTheDocument();
    expect(screen.getAllByText("工作台可使用，采集前请在设置中连接浏览器插件。").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "进入工作台" }));

    expect(await screen.findByRole("heading", { name: "招聘人才 Mapping 工作台" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "准备进入招聘人才工作台" })).not.toBeInTheDocument();
  });

  it("blocks entry and shows recovery guidance for database faults", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") return response(readyHealth);
        if (url === "/api/app/status") {
          return response(
            { error: { code: "database_in_use", message: "desktop busy" } },
            false,
            503,
          );
        }
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    render(<App />);

    expect((await screen.findAllByText("桌面端正在使用人才库。请先关闭桌面端，再点击重新检查。")).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "进入工作台" })).toBeDisabled();
  });

  it("can recover from a failed startup check by rechecking", async () => {
    let run = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") {
          run += 1;
          return run === 1 ? Promise.reject(new TypeError("Failed to fetch token=secret")) : response(readyHealth);
        }
        if (url === "/api/app/status") return response(readyStatus);
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    render(<App />);

    expect((await screen.findAllByText("无法连接本地服务，请确认网页程序仍在运行。")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/secret/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重新检查" }));
    expect(await screen.findByRole("button", { name: "进入工作台" })).toBeEnabled();
  });

  it("does not reopen the confirmation gate during the same page session", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") return response(readyHealth);
        if (url === "/api/app/status") return response(readyStatus);
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        if (url.includes("/api/candidates")) return response({ rows: [], total: 0, page: 1, page_size: 100 });
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "进入工作台" }));
    await user.click(screen.getByRole("button", { name: "候选人" }));
    await screen.findByText("当前筛选条件下还没有候选人。");
    expect(screen.queryByRole("heading", { name: "准备进入招聘人才工作台" })).not.toBeInTheDocument();
  });

  it("rechecks startup state when a new tab mounts the app again", async () => {
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
      if (url === "/api/health") return response(readyHealth);
      if (url === "/api/app/status") return response(readyStatus);
      if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const first = render(<App />);
    await screen.findByRole("heading", { name: "准备进入招聘人才工作台" });
    first.unmount();

    render(<App />);
    await waitFor(() => {
      const healthCalls = fetchMock.mock.calls.filter(([url]) => String(url) === "/api/health");
      expect(healthCalls).toHaveLength(2);
    });
  });

  it("shows a recoverable service failure before setup status is available", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "本地服务暂时不可用" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新连接" })).toBeInTheDocument();
  });

  it("does not mark the service check complete before health returns", async () => {
    const healthRequest = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") return healthRequest.promise;
        if (url === "/api/app/status") return response(readyStatus);
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    render(<App />);

    expect(await screen.findByRole("heading", { name: "准备进入招聘人才工作台" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "进入工作台" })).toBeDisabled();

    healthRequest.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(readyHealth),
    } as Response);

    expect(await screen.findByRole("button", { name: "进入工作台" })).toBeEnabled();
  });

  it("does not mark the database check complete before app status returns", async () => {
    const statusRequest = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") return response(readyHealth);
        if (url === "/api/app/status") return statusRequest.promise;
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    render(<App />);

    expect(await screen.findByRole("heading", { name: "准备进入招聘人才工作台" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "进入工作台" })).toBeDisabled();

    statusRequest.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(readyStatus),
    } as Response);

    expect(await screen.findByRole("button", { name: "进入工作台" })).toBeEnabled();
  });

  it("keeps entry disabled when the service name is wrong", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") return response({ ...readyHealth, service: "another-service" });
        if (url === "/api/app/status") return response(readyStatus);
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    render(<App />);

    expect(await screen.findByRole("button", { name: "进入工作台" })).toBeDisabled();
  });

  it("keeps entry disabled when health status is not ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") return response({ ...readyHealth, status: "degraded" });
        if (url === "/api/app/status") return response(readyStatus);
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    render(<App />);

    expect(await screen.findByRole("button", { name: "进入工作台" })).toBeDisabled();
  });

  it("keeps entry disabled when required capabilities are missing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") return response({ ...readyHealth, capabilities: ["phase2c_pairing"] });
        if (url === "/api/app/status") return response(readyStatus);
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    render(<App />);

    expect(await screen.findByRole("button", { name: "进入工作台" })).toBeDisabled();
  });

  it("keeps entry disabled when database_ready is false", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url === "/api/setup/status") return response({ ...setupRequired, setup_required: false });
        if (url === "/api/health") return response(readyHealth);
        if (url === "/api/app/status") return response({ ...readyStatus, database_ready: false });
        if (url === "/api/plugin-connection/status") return response(pluginDisconnected);
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    render(<App />);

    expect(await screen.findByRole("button", { name: "进入工作台" })).toBeDisabled();
  });
});
