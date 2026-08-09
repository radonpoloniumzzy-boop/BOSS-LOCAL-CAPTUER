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
  version: "0.1.0-web-phase-1",
  database_ready: true,
  data_dir: "D:\\HR-Workbench-Data",
  candidate_count: 1284,
  batch_count: 17,
  latest_batch_id: 17,
  latest_batch_status: "completed",
};

afterEach(() => vi.restoreAllMocks());

describe("local workbench shell", () => {
  it("renders the first-run recommendation and existing database notice", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(setupRequired)));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "选择数据目录" })).toBeInTheDocument();
    expect(screen.getByDisplayValue(setupRequired.suggested_data_dir)).toBeInTheDocument();
    expect(screen.getByText(/检测到现有数据库/)).toBeInTheDocument();
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

  it("explains when the local service stops during setup", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(() => response(setupRequired))
        .mockImplementationOnce(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "确认并开始使用" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "无法连接本地服务，请确认网页程序仍在运行。",
    );
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });

  it("enters the home page immediately after setup succeeds", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => response(setupRequired))
      .mockImplementationOnce(() => response({ setup_completed: true }))
      .mockImplementationOnce(() => response(readyStatus));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "确认并开始使用" }));

    expect(await screen.findByRole("heading", { name: "招聘人才 Mapping 工作台" })).toBeInTheDocument();
    expect(screen.getByText("1,284")).toBeInTheDocument();
    expect(screen.getByText("17 个批次")).toBeInTheDocument();
  });

  it("renders existing database statistics and disables future navigation", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(() => response({ ...setupRequired, setup_required: false }))
        .mockImplementationOnce(() => response(readyStatus)),
    );
    render(<App />);

    expect(await screen.findByText("数据库已就绪")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /候选人.*待开发/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Mapping 与报告.*待开发/ })).toBeDisabled();
  });

  it("shows a recoverable service failure", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "本地服务暂时不可用" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新连接" })).toBeInTheDocument();
  });

  it("distinguishes a database-not-ready response from a service failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(() => response({ ...setupRequired, setup_required: false }))
        .mockImplementationOnce(() =>
          response(
            { error: { code: "database_not_ready", message: "数据库尚未就绪。" } },
            false,
            503,
          ),
        ),
    );
    render(<App />);

    expect(await screen.findByRole("heading", { name: "数据库尚未就绪" })).toBeInTheDocument();
    expect(screen.queryByText("本地服务暂时不可用")).not.toBeInTheDocument();
  });

  it("labels an initialized database with no batches as empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(() => response({ ...setupRequired, setup_required: false }))
        .mockImplementationOnce(() =>
          response({ ...readyStatus, candidate_count: 0, batch_count: 0, latest_batch_id: 0, latest_batch_status: "idle" }),
        ),
    );
    render(<App />);

    expect(await screen.findByText("空数据库")).toBeInTheDocument();
    expect(screen.queryByText("idle")).not.toBeInTheDocument();
  });
});
