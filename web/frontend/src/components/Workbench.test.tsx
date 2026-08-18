import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Workbench } from "./Workbench";

type Deferred = {
  resolve: (response: Response) => void;
};

const status = {
  status: "ready" as const,
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
        return response({
          pairing_code: "ABC123-DEF456",
          pairing_uri: "boss-local://web-pair?apiBase=http%3A%2F%2F127.0.0.1%3A19064&pairingCode=ABC123-DEF456",
          expires_at: "2026-08-11T12:05:00",
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    const view = render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "设置" }));
    await screen.findByText("等待插件配对");
    await user.click(screen.getByRole("button", { name: "生成插件连接码" }));
    expect(await screen.findByText("ABC123-DEF456")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("api_token");
    await user.click(screen.getByRole("button", { name: "复制连接码" }));
    expect(writeText).toHaveBeenCalledWith(
      "boss-local://web-pair?apiBase=http%3A%2F%2F127.0.0.1%3A19064&pairingCode=ABC123-DEF456",
    );
    expect(writeText.mock.calls.flat().join("|")).not.toContain("apiToken");
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
    const clearTimeoutSpy = vi.spyOn(window, "clearTimeout");
    const view = render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    expect(await screen.findByText("#159")).toBeInTheDocument();
    window.dispatchEvent(new Event("focus"));
    expect(await screen.findByText("#161")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("已接收新批次 #161");
    expect(screen.getByRole("button", { name: "导出 Markdown" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    view.unmount();
    expect(clearTimeoutSpy).toHaveBeenCalled();
  });

  it("pauses batch list polling while viewing detail and resumes after returning", async () => {
    let listRequests = 0;
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/capture-batches?")) {
        listRequests += 1;
        return response({
          rows: [{
            id: 9,
            start_time: "2026-08-11T11:35:20",
            source_platform: "boss",
            total_collected: 1,
            total_new: 1,
            total_updated: 0,
            total_skipped: 0,
            total_failed: 0,
            status: "completed",
            role_id: null,
          }],
          total: 1,
          page: 1,
          page_size: 20,
        });
      }
      if (url.includes("/api/capture-batches/9/candidates")) {
        return response({ rows: [], total: 0, page: 1, page_size: 50 });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const view = render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    await user.click(await screen.findByRole("button", { name: "查看候选人" }));
    expect(await screen.findByRole("heading", { name: "批次 #9" })).toBeInTheDocument();
    const beforeDetailFocus = listRequests;
    window.dispatchEvent(new Event("focus"));
    await Promise.resolve();
    expect(listRequests).toBe(beforeDetailFocus);

    await user.click(screen.getByRole("button", { name: "返回批次列表" }));
    window.dispatchEvent(new Event("focus"));
    await waitFor(() => expect(listRequests).toBeGreaterThan(beforeDetailFocus));
  });

  it("opens an older candidate batch directly without requiring it on the first page", async () => {
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/candidates?")) {
        return response({
          rows: [{
            id: 42,
            name: "Older Candidate",
            source_platform: "boss",
            latest_source_platform: "boss",
            latest_source_job_title: "证券交易员",
            latest_batch_id: 7,
            latest_capture_time: "2026-07-01T09:00:00",
            latest_ingest_status: "new",
            latest_batch_role_id: null,
            has_role_binding: 0,
          }],
          total: 1,
          page: 1,
          page_size: 100,
        });
      }
      if (url === "/api/capture-batches/7") {
        return response({
          id: 7,
          start_time: "2026-07-01T09:00:00",
          source_platform: "boss",
          total_collected: 1,
          total_new: 1,
          total_updated: 0,
          total_skipped: 0,
          total_failed: 0,
          status: "completed",
          role_id: null,
        });
      }
      if (url.includes("/api/capture-batches/7/candidates")) {
        return response({ rows: [], total: 0, page: 1, page_size: 50 });
      }
      if (url.includes("/api/capture-batches?")) {
        return response({ rows: [], total: 30, page: 1, page_size: 20 });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const view = render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    await user.click(await screen.findByRole("button", { name: "#7" }));
    expect(await screen.findByRole("heading", { name: "批次 #7" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/capture-batches/7", undefined);
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
    const view = render(<Workbench status={status} />);

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
    await screen.findByText("当前还没有候选人。");
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

  it("searches candidates, opens read-only detail, and jumps to the latest batch", async () => {
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/candidates?page=1&page_size=100&sort=latest_capture_desc")) {
        if (url.includes("keyword=%E5%8E%9F%E5%A7%8B%E5%8D%A1%E7%89%87")) {
          return response({
            rows: [{
              id: 7,
              name: "Bob Li",
              source_platform: "liepin",
              latest_source_platform: "liepin",
              latest_source_job_title: "量化研究员",
              latest_batch_id: 11,
              latest_capture_time: "2026-08-11T10:30:00",
              latest_ingest_status: "updated",
              latest_batch_role_id: null,
              has_role_binding: 0,
            }],
            total: 1,
            page: 1,
            page_size: 100,
          });
        }
        return response({ rows: [], total: 0, page: 1, page_size: 100 });
      }
      if (url === "/api/candidates/7") {
        return response({
          id: 7,
          name: "Bob Li",
          source_platform: "liepin",
          latest_source_platform: "liepin",
          latest_source_job_title: "量化研究员",
          latest_batch_id: 11,
          latest_capture_time: "2026-08-11T10:30:00",
          latest_ingest_status: "updated",
          latest_batch_role_id: null,
          has_role_binding: 0,
          job_title: "量化研究员",
          source_url: "https://example.test/source",
          capture_time: "2026-08-11T10:30:00",
          raw_card_text: "current card snapshot",
          active_status: "在职",
          expected_salary: "40k",
          work_experience_text: "5年",
          education_text: "硕士",
          tags_text: "量化 | 因子",
          summary_text: "擅长因子研究",
          detail_url: "https://example.test/detail",
          latest_raw_card_text: "原始卡片关键词与快照",
          latest_source_url: "https://example.test/source",
          latest_detail_url: "https://example.test/detail",
          city: "上海",
          years_experience: 5,
          job_family: "研究",
          job_track: "量化",
          batch_count: 2,
        });
      }
      if (url === "/api/candidates/7/appearances") {
        return response({
          rows: [{
            batch_id: 11,
            source_platform: "liepin",
            source_job_title: "量化研究员",
            capture_time: "2026-08-11T10:30:00",
            ingest_status: "updated",
          }],
        });
      }
      if (url === "/api/capture-batches/11") {
        return response({
          id: 11,
          start_time: "2026-08-11T10:30:00",
          source_platform: "liepin",
          total_collected: 1,
          total_new: 0,
          total_updated: 1,
          total_skipped: 0,
          total_failed: 0,
          status: "completed",
          role_id: null,
        });
      }
      if (url.includes("/api/capture-batches/11/candidates")) {
        return response({ rows: [], total: 0, page: 1, page_size: 50 });
      }
      if (url.includes("/api/capture-batches?")) {
        return response({ rows: [], total: 0, page: 1, page_size: 20 });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    await user.type(screen.getByLabelText("候选人搜索"), "原始卡片");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    expect(await screen.findByText("Bob Li")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看详情" }));
    const detailDrawer = await screen.findByRole("complementary", { name: "候选人详情" });
    expect(within(detailDrawer).getAllByText("量化研究员").length).toBeGreaterThan(0);
    expect(screen.getByText("原始卡片关键词与快照")).toBeInTheDocument();

    await user.click(within(detailDrawer).getByRole("button", { name: "#11" }));
    expect(await screen.findByRole("heading", { name: "批次 #11" })).toBeInTheDocument();
  });

  it("opens a batch by ID from the batch page even when it is not on the first page", async () => {
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/capture-batches?")) {
        return response({ rows: [], total: 30, page: 1, page_size: 20 });
      }
      if (url === "/api/capture-batches/24") {
        return response({
          id: 24,
          start_time: "2026-08-12T09:20:00",
          source_platform: "boss",
          total_collected: 2,
          total_new: 1,
          total_updated: 1,
          total_skipped: 0,
          total_failed: 0,
          status: "completed",
          role_id: null,
        });
      }
      if (url.includes("/api/capture-batches/24/candidates")) {
        return response({
          rows: [{
            id: 1,
            batch_id: 24,
            candidate_id: 66,
            name: "Archived Batch Candidate",
            source_platform: "boss",
            platform_uid: "boss:66",
            job_title: "证券交易员",
            capture_time: "2026-08-12T09:20:00",
            raw_card_text: "snapshot 24",
            ingest_status: "new",
            has_role_binding: 0,
          }],
          total: 1,
          page: 1,
          page_size: 50,
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    await user.type(screen.getByLabelText("批次 ID 搜索"), "24");
    await user.click(screen.getByRole("button", { name: "打开批次" }));
    expect(await screen.findByRole("heading", { name: "批次 #24" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导出 Markdown" })).toBeInTheDocument();
    expect(screen.getByText("Archived Batch Candidate")).toBeInTheDocument();
  });

  it("shows candidate appearance history, handles retries, and ignores stale appearance responses", async () => {
    const appearanceQueue: Record<number, Deferred> = {};
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/candidates?")) {
        return response({
          rows: [
            {
              id: 1,
              name: "Alice",
              source_platform: "boss",
              latest_source_platform: "boss",
              latest_source_job_title: "证券交易员",
              latest_batch_id: 41,
              latest_capture_time: "2026-08-12T09:00:00",
              latest_ingest_status: "new",
              latest_batch_role_id: null,
              has_role_binding: 0,
              batch_count: 2,
            },
            {
              id: 2,
              name: "Bob",
              source_platform: "liepin",
              latest_source_platform: "liepin",
              latest_source_job_title: "量化研究员",
              latest_batch_id: 42,
              latest_capture_time: "2026-08-12T10:00:00",
              latest_ingest_status: "updated",
              latest_batch_role_id: null,
              has_role_binding: 0,
              batch_count: 1,
            },
          ],
          total: 2,
          page: 1,
          page_size: 100,
        });
      }
      if (url === "/api/candidates/1") {
        return response({
          id: 1,
          name: "Alice",
          source_platform: "boss",
          latest_source_platform: "boss",
          latest_source_job_title: "证券交易员",
          latest_batch_id: 41,
          latest_capture_time: "2026-08-12T09:00:00",
          latest_ingest_status: "new",
          latest_batch_role_id: null,
          has_role_binding: 0,
          batch_count: 2,
          job_title: "证券交易员",
          source_url: "",
          capture_time: "2026-08-12T09:00:00",
          raw_card_text: "alice snapshot",
          active_status: "",
          expected_salary: "",
          work_experience_text: "",
          education_text: "",
          tags_text: "",
          summary_text: "",
          detail_url: "",
          latest_raw_card_text: "alice snapshot",
          latest_source_url: "",
          latest_detail_url: "",
          city: "",
          years_experience: null,
          job_family: "",
          job_track: "",
        });
      }
      if (url === "/api/candidates/2") {
        return response({
          id: 2,
          name: "Bob",
          source_platform: "liepin",
          latest_source_platform: "liepin",
          latest_source_job_title: "量化研究员",
          latest_batch_id: 42,
          latest_capture_time: "2026-08-12T10:00:00",
          latest_ingest_status: "updated",
          latest_batch_role_id: null,
          has_role_binding: 0,
          batch_count: 1,
          job_title: "量化研究员",
          source_url: "",
          capture_time: "2026-08-12T10:00:00",
          raw_card_text: "bob snapshot",
          active_status: "",
          expected_salary: "",
          work_experience_text: "",
          education_text: "",
          tags_text: "",
          summary_text: "",
          detail_url: "",
          latest_raw_card_text: "bob snapshot",
          latest_source_url: "",
          latest_detail_url: "",
          city: "",
          years_experience: null,
          job_family: "",
          job_track: "",
        });
      }
      if (url === "/api/candidates/1/appearances") {
        return new Promise<Response>((resolve) => {
          appearanceQueue[1] = { resolve };
        });
      }
      if (url === "/api/candidates/2/appearances") {
        return response({ rows: [] });
      }
      if (url === "/api/capture-batches/41") {
        return response({
          id: 41,
          start_time: "2026-08-12T09:00:00",
          source_platform: "boss",
          total_collected: 1,
          total_new: 1,
          total_updated: 0,
          total_skipped: 0,
          total_failed: 0,
          status: "completed",
          role_id: null,
        });
      }
      if (url.includes("/api/capture-batches/41/candidates")) {
        return response({ rows: [], total: 0, page: 1, page_size: 50 });
      }
      if (url.includes("/api/capture-batches?")) {
        return response({ rows: [], total: 0, page: 1, page_size: 20, today_summary: { received: 0, added: 0 } });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const view = render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    const detailButtons = await screen.findAllByRole("button", { name: "查看详情" });
    await user.click(detailButtons[0]);
    const aliceDrawer = await screen.findByRole("complementary", { name: "候选人详情" });
    expect(within(aliceDrawer).getByText("正在读取来源出现历史…")).toBeInTheDocument();

    await user.click(detailButtons[1]);
    const bobDrawer = await screen.findByRole("complementary", { name: "候选人详情" });
    expect(within(bobDrawer).getByText("还没有来源出现历史。")).toBeInTheDocument();

    appearanceQueue[1].resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        rows: [{
          batch_id: 41,
          source_platform: "boss",
          source_job_title: "证券交易员",
          capture_time: "2026-08-12T09:00:00",
          ingest_status: "new",
        }],
      }),
    } as Response);

    await waitFor(() => {
      expect(within(bobDrawer).queryByText("查看批次")).not.toBeInTheDocument();
      expect(within(bobDrawer).getByText("还没有来源出现历史。")).toBeInTheDocument();
    });

    const retryMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/candidates?")) {
        return response({
          rows: [{
            id: 3,
            name: "Retry Candidate",
            source_platform: "boss",
            latest_source_platform: "boss",
            latest_source_job_title: "重试岗位",
            latest_batch_id: 50,
            latest_capture_time: "2026-08-12T11:00:00",
            latest_ingest_status: "new",
            latest_batch_role_id: null,
            has_role_binding: 0,
            batch_count: 1,
          }],
          total: 1,
          page: 1,
          page_size: 100,
        });
      }
      if (url === "/api/candidates/3") {
        return response({
          id: 3,
          name: "Retry Candidate",
          source_platform: "boss",
          latest_source_platform: "boss",
          latest_source_job_title: "重试岗位",
          latest_batch_id: 50,
          latest_capture_time: "2026-08-12T11:00:00",
          latest_ingest_status: "new",
          latest_batch_role_id: null,
          has_role_binding: 0,
          batch_count: 1,
          job_title: "重试岗位",
          source_url: "",
          capture_time: "2026-08-12T11:00:00",
          raw_card_text: "retry snapshot",
          active_status: "",
          expected_salary: "",
          work_experience_text: "",
          education_text: "",
          tags_text: "",
          summary_text: "",
          detail_url: "",
          latest_raw_card_text: "retry snapshot",
          latest_source_url: "",
          latest_detail_url: "",
          city: "",
          years_experience: null,
          job_family: "",
          job_track: "",
        });
      }
      if (url === "/api/candidates/3/appearances") {
        const count = retryMock.mock.calls.filter(([request]) => String(request) === "/api/candidates/3/appearances").length;
        if (count === 1) {
          return Promise.resolve({
            ok: false,
            status: 500,
            json: () => Promise.resolve({ error: { code: "request_failed", message: "来源出现历史加载失败。" } }),
          } as Response);
        }
        return response({ rows: [] });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    view.unmount();
    vi.stubGlobal("fetch", retryMock);
    render(<Workbench status={status} />);
    await user.click(screen.getByRole("button", { name: "候选人" }));
    await user.click(await screen.findByRole("button", { name: "查看详情" }));
    const retryDrawer = await screen.findByRole("complementary", { name: "候选人详情" });
    expect(await within(retryDrawer).findByText("来源出现历史加载失败。")).toBeInTheDocument();
    await user.click(within(retryDrawer).getByRole("button", { name: "重试" }));
    expect(await within(retryDrawer).findByText("还没有来源出现历史。")).toBeInTheDocument();
  });

  it("applies batch filters on the server and keeps them during refresh", async () => {
    const batchUrls: string[] = [];
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/capture-batches?")) {
        batchUrls.push(url);
        return response({
          rows: [{
            id: 88,
            start_time: "2026-08-18T09:20:00",
            source_platform: "boss",
            total_collected: 2,
            total_new: 1,
            total_updated: 1,
            total_skipped: 0,
            total_failed: 1,
            status: "failed",
            role_id: null,
            job_title: "失败批次",
          }],
          total: 25,
          page: url.includes("page=2") ? 2 : 1,
          page_size: 20,
          today_summary: { received: 2, added: 1 },
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    await screen.findByText("#88");
    await user.selectOptions(screen.getByLabelText("批次来源平台"), "boss");
    await user.selectOptions(screen.getByLabelText("批次状态"), "failed");
    await user.click(screen.getByLabelText("只看失败批次"));
    await user.click(screen.getByLabelText("只看今天"));
    await waitFor(() => {
      const last = batchUrls.at(-1) || "";
      expect(last).toContain("source_platform=boss");
      expect(last).toContain("status=failed");
      expect(last).toContain("failed_only=true");
      expect(last).toContain("today_only=true");
      expect(last).toContain("page=1");
    });

    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(batchUrls.at(-1)).toContain("page=2"));

    const callsBeforeRefresh = batchUrls.length;
    await user.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(batchUrls.length).toBeGreaterThan(callsBeforeRefresh));
    expect(batchUrls.at(-1)).toContain("page=2");
    expect(batchUrls.at(-1)).toContain("status=failed");

    const callsBeforeFocus = batchUrls.length;
    window.dispatchEvent(new Event("focus"));
    await waitFor(() => expect(batchUrls.length).toBeGreaterThan(callsBeforeFocus));
    expect(batchUrls.at(-1)).toContain("page=2");
    expect(batchUrls.at(-1)).toContain("today_only=true");
  });

  it("downloads markdown once per click, blocks duplicate export, and reports failures", async () => {
    let resolveExport: ((value: Response) => void) | null = null;
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const createObjectURL = vi.fn(() => "blob:markdown");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/capture-batches?")) {
        return response({
          rows: [{
            id: 90,
            start_time: "2026-08-18T09:20:00",
            source_platform: "boss",
            total_collected: 1,
            total_new: 1,
            total_updated: 0,
            total_skipped: 0,
            total_failed: 0,
            status: "completed",
            role_id: null,
          }],
          total: 1,
          page: 1,
          page_size: 20,
          today_summary: { received: 1, added: 1 },
        });
      }
      if (url === "/api/capture-batches/90/export.md") {
        return new Promise<Response>((resolve) => {
          resolveExport = resolve;
        });
      }
      if (url === "/api/capture-batches/91") {
        return response({
          id: 91,
          start_time: "2026-08-18T09:30:00",
          source_platform: "boss",
          total_collected: 1,
          total_new: 1,
          total_updated: 0,
          total_skipped: 0,
          total_failed: 0,
          status: "completed",
          role_id: null,
        });
      }
      if (url.includes("/api/capture-batches/91/candidates")) {
        return response({ rows: [], total: 0, page: 1, page_size: 50 });
      }
      if (url === "/api/capture-batches/91/export.md") {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve({ error: { code: "batch_not_found", message: "采集批次不存在。" } }),
        } as Response);
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    const exportButton = await screen.findByRole("button", { name: "导出 Markdown" });
    await user.click(exportButton);
    await user.click(exportButton);
    expect(fetchMock.mock.calls.filter(([url]) => String(url) === "/api/capture-batches/90/export.md")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "导出中…" })).toBeDisabled();

    expect(resolveExport).not.toBeNull();
    resolveExport!({
      ok: true,
      status: 200,
      blob: () => Promise.resolve(new Blob(["# markdown"])),
      headers: new Headers({ "Content-Disposition": "attachment; filename*=UTF-8''batch-90.md" }),
    } as Response);

    await waitFor(() => expect(clickSpy).toHaveBeenCalled());
    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalled();

    await user.type(screen.getByLabelText("批次 ID 搜索"), "91");
    await user.click(screen.getByRole("button", { name: "打开批次" }));
    expect(await screen.findByRole("heading", { name: "批次 #91" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "导出 Markdown" }));
    expect(await screen.findByRole("status")).toHaveTextContent("采集批次不存在。");
  });
});
