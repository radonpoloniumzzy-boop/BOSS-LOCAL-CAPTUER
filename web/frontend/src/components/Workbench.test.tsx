import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Workbench } from "./Workbench";

type ResolveResponse = (value: Response | PromiseLike<Response>) => void;

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
    expect(screen.getAllByText("boss").length).toBeGreaterThan(0);
  });

  it("updates candidate filters and protects against stale responses", async () => {
    const pending = { current: null as ResolveResponse | null };
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.endsWith("/api/candidates?page=1&page_size=100")) {
        return response({
          rows: [
            {
              id: 1,
              name: "Seed",
              source_platform: "boss",
              latest_source_platform: "boss",
              latest_source_job_title: "种子岗位",
              latest_batch_id: 8,
              latest_capture_time: "2026-08-10T09:00:00",
              latest_ingest_status: "new",
              latest_batch_role_id: null,
            },
          ],
          total: 1,
          page: 1,
          page_size: 100,
        });
      }
      if (url.includes("source_platform=boss") && !url.includes("unbound_only=true")) {
        return new Promise<Response>((resolve) => {
          pending.current = resolve;
        });
      }
      if (url.includes("source_platform=boss") && url.includes("unbound_only=true")) {
        return response({
          rows: [
            {
              id: 2,
              name: "Bob",
              source_platform: "boss",
              latest_source_platform: "boss",
              latest_source_job_title: "",
              latest_batch_id: 10,
              latest_capture_time: "2026-08-10T10:30:00",
              latest_ingest_status: "updated",
              latest_batch_role_id: 3,
            },
          ],
          total: 1,
          page: 1,
          page_size: 100,
        });
      }
      return response({
        rows: [],
        total: 0,
        page: 1,
        page_size: 100,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    await user.selectOptions(await screen.findByRole("combobox"), "boss");
    await user.click(screen.getByRole("checkbox", { name: "只看未绑定岗位" }));

    if (pending.current) {
      pending.current({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            rows: [
              {
                id: 1,
                name: "Old Boss Candidate",
                source_platform: "boss",
                latest_source_platform: "boss",
                latest_source_job_title: "旧岗位",
                latest_batch_id: 9,
                latest_capture_time: "2026-08-09T10:00:00",
                latest_ingest_status: "new",
                latest_batch_role_id: null,
              },
            ],
            total: 1,
            page: 1,
            page_size: 100,
          }),
      } as Response);
    }

    expect(await screen.findByText("Bob")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("Old Boss Candidate")).not.toBeInTheDocument();
    });
  });
});
