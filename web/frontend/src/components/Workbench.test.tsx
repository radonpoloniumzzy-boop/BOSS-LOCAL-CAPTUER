import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Workbench } from "./Workbench";

type Deferred = {
  resolve: (response: Response) => void;
};

const status = {
  version: "0.2.0",
  database_ready: true,
  data_dir: "D:\\HR-Workbench-Data",
  candidate_count: 3,
  batch_count: 2,
  latest_batch_id: 9,
  latest_batch_status: "completed",
};

const response = (body: unknown) =>
  Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response);

afterEach(() => vi.restoreAllMocks());

describe("workbench candidate intake views", () => {
  it("generates and copies a one-time plugin pairing code without exposing a token", async () => {
    const fetchMock = vi.fn((input: string | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/plugin-connection/status")) {
        return response({
          api_base: "http://127.0.0.1:17864",
          service_ready: true,
          connected: false,
          last_verified_at: null,
        });
      }
      if (url.endsWith("/api/plugin-connection/pairing-code") && init?.method === "POST") {
        return response({ pairing_code: "ABC123-DEF456", expires_at: "2026-08-11T12:05:00" });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "设置" }));
    await screen.findByText("等待插件配对");
    await user.click(screen.getByRole("button", { name: "生成插件连接码" }));
    expect(await screen.findByText("ABC123-DEF456")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("api_token");
    await user.click(screen.getByRole("button", { name: "复制连接码" }));
    expect(writeText).toHaveBeenCalledWith("ABC123-DEF456");
  });

  it("refreshes newest batches on focus, announces the new batch, and exposes snapshot export", async () => {
    let batchRequest = 0;
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (!url.includes("/api/capture-batches?")) throw new Error(`unexpected request: ${url}`);
      batchRequest += 1;
      const id = batchRequest === 1 ? 159 : 161;
      return response({
        rows: [{
          id,
          start_time: "2026-08-11T11:35:20",
          source_platform: "boss",
          total_collected: 450,
          total_new: id === 161 ? 0 : 12,
          total_updated: id === 161 ? 450 : 3,
          total_skipped: 0,
          total_failed: 0,
          status: "completed",
          role_id: null,
        }],
        total: id,
        page: 1,
        page_size: 20,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    expect(await screen.findByText("#159")).toBeInTheDocument();
    window.dispatchEvent(new Event("focus"));
    expect(await screen.findByText("#161")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("已接收新批次 #161");
    const exportLink = screen.getByRole("link", { name: "导出 Markdown" });
    expect(exportLink).toHaveAttribute("href", "/api/capture-batches/161/export.md");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("renders job-optional candidates and batches", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url.includes("/api/candidates")) {
          return response({
            rows: [
              {
                id: 1,
                name: "Alice",
                source_platform: "boss",
                latest_source_platform: "boss",
                latest_source_job_title: "证券交易员",
                latest_batch_id: 9,
                latest_capture_time: "2026-08-10T10:00:00",
                latest_ingest_status: "new",
                latest_batch_role_id: null,
                has_role_binding: 0,
              },
            ],
            total: 1,
            page: 1,
            page_size: 100,
          });
        }
        return response({
          rows: [
            {
              id: 9,
              start_time: "2026-08-10T10:00:00",
              source_platform: "boss",
              total_collected: 1,
              total_new: 1,
              total_updated: 0,
              total_skipped: 0,
              total_failed: 0,
              status: "completed",
              role_id: null,
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        });
      }),
    );
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("未绑定岗位")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    expect(await screen.findByText("#9")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看候选人" })).toBeInTheDocument();
  });

  it("uses explicit refresh ticks for candidate and batch lists", async () => {
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/candidates")) {
        return response({ rows: [], total: 0, page: 1, page_size: 100 });
      }
      return response({ rows: [], total: 0, page: 1, page_size: 20 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    await screen.findByText("当前筛选条件下还没有候选人。");
    const candidateCallsBefore = fetchMock.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(candidateCallsBefore));

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    await screen.findByText("还没有采集批次。");
    const batchCallsBefore = fetchMock.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(batchCallsBefore));
  });

  it("opens batch candidates, pages them, and can return to the list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url.includes("/api/capture-batches/9/candidates")) {
          return response({
            rows: [
              {
                id: 1,
                batch_id: 9,
                candidate_id: 88,
                name: "Snapshot Alice",
                source_platform: "boss",
                platform_uid: "boss:88",
                job_title: "证券交易员",
                capture_time: "2026-08-10T10:00:00",
                raw_card_text: "old snapshot text",
                ingest_status: "new",
                has_role_binding: 0,
              },
            ],
            total: 1,
            page: 1,
            page_size: 50,
          });
        }
        return response({
          rows: [
            {
              id: 9,
              start_time: "2026-08-10T10:00:00",
              source_platform: "boss",
              total_collected: 1,
              total_new: 1,
              total_updated: 0,
              total_skipped: 0,
              total_failed: 0,
              status: "completed",
              role_id: null,
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        });
      }),
    );
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    await user.click(await screen.findByRole("button", { name: "查看候选人" }));

    expect(await screen.findByRole("heading", { name: "批次 #9" })).toBeInTheDocument();
    expect(screen.getByText("Snapshot Alice")).toBeInTheDocument();
    expect(screen.queryByText("old snapshot text")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看原始快照" }));
    expect(screen.getByRole("complementary", { name: "原始快照" })).toBeInTheDocument();
    expect(screen.getByText("old snapshot text")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭原始快照" }));

    await user.click(screen.getByRole("button", { name: "返回批次列表" }));
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "批次 #9" })).not.toBeInTheDocument();
    });
  });

  it("protects batch detail from stale responses when switching batches", async () => {
    const pending: Record<number, Deferred> = {};
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url.includes("/api/capture-batches/9/candidates")) {
          return new Promise<Response>((resolve) => {
            pending[9] = { resolve };
          });
        }
        if (url.includes("/api/capture-batches/10/candidates")) {
          return response({
            rows: [
              {
                id: 2,
                batch_id: 10,
                candidate_id: 99,
                name: "Newest Batch Candidate",
                source_platform: "boss",
                platform_uid: "boss:99",
                job_title: "新批次岗位",
                capture_time: "2026-08-10T11:00:00",
                raw_card_text: "new batch snapshot",
                ingest_status: "updated",
                has_role_binding: 1,
              },
            ],
            total: 1,
            page: 1,
            page_size: 50,
          });
        }
        return response({
          rows: [
            {
              id: 9,
              start_time: "2026-08-10T10:00:00",
              source_platform: "boss",
              total_collected: 1,
              total_new: 1,
              total_updated: 0,
              total_skipped: 0,
              total_failed: 0,
              status: "completed",
              role_id: null,
            },
            {
              id: 10,
              start_time: "2026-08-10T11:00:00",
              source_platform: "boss",
              total_collected: 1,
              total_new: 0,
              total_updated: 1,
              total_skipped: 0,
              total_failed: 0,
              status: "completed",
              role_id: 3,
            },
          ],
          total: 2,
          page: 1,
          page_size: 20,
        });
      }),
    );
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    const buttons = await screen.findAllByRole("button", { name: "查看候选人" });
    await user.click(buttons[0]);
    await user.click(screen.getByRole("button", { name: "返回批次列表" }));
    const refreshedButtons = await screen.findAllByRole("button", { name: "查看候选人" });
    await user.click(refreshedButtons[1]);

    pending[9].resolve({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          rows: [
            {
              id: 1,
              batch_id: 9,
              candidate_id: 88,
              name: "Old Batch Candidate",
              source_platform: "boss",
              platform_uid: "boss:88",
              job_title: "旧批次岗位",
              capture_time: "2026-08-10T10:00:00",
              raw_card_text: "old batch snapshot",
              ingest_status: "new",
              has_role_binding: 0,
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        }),
    } as Response);

    expect(await screen.findByText("Newest Batch Candidate")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("Old Batch Candidate")).not.toBeInTheDocument();
    });
  });
});
