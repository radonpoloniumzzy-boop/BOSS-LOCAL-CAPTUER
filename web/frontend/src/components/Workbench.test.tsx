/// <reference types="node" />
import { useState } from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as apiModule from "../api";
import { Workbench } from "./Workbench";
import { Drawer } from "./workbench/Drawer";

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

const errorResponse = (message: string, statusCode = 409) =>
  Promise.resolve({
    ok: false,
    status: statusCode,
    json: () => Promise.resolve({ error: { code: "request_failed", message } }),
  } as Response);

afterEach(() => vi.restoreAllMocks());

function DrawerHarness({
  tick = 0,
}: {
  tick?: number;
}) {
  const [primaryOpen, setPrimaryOpen] = useState(false);
  const [secondaryOpen, setSecondaryOpen] = useState(false);

  return (
    <div>
      <button type="button" onClick={() => setPrimaryOpen(true)}>触发按钮</button>
      <button type="button">底层导航</button>
      {primaryOpen && (
        <Drawer label="主抽屉" className="drawer-panel detail-drawer-panel" onClose={() => setPrimaryOpen(false)}>
          <div data-testid={`tick-${tick}`} />
          <button type="button">第一个操作</button>
          <button type="button" onClick={() => setSecondaryOpen(true)}>第二个操作</button>
          {secondaryOpen && (
            <Drawer label="次级抽屉" className="drawer-panel snapshot-reader-drawer" onClose={() => setSecondaryOpen(false)}>
              <button type="button">次级操作</button>
            </Drawer>
          )}
        </Drawer>
      )}
    </div>
  );
}

describe("drawer accessibility behavior", () => {
  it("uses dialog semantics and traps focus in both directions", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);
    await user.click(screen.getByRole("button", { name: "触发按钮" }));

    const dialog = screen.getByRole("dialog", { name: "主抽屉" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(screen.getByRole("button", { name: "第一个操作" })).toHaveFocus());

    await user.tab();
    expect(screen.getByRole("button", { name: "第二个操作" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "第一个操作" })).toHaveFocus();

    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "第二个操作" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "底层导航" })).not.toHaveFocus();
  });

  it("keeps scroll lock and return-focus stable across parent rerenders", async () => {
    const user = userEvent.setup();
    let bumpTick: (() => void) | null = null;
    function RerenderHarness() {
      const [open, setOpen] = useState(false);
      const [tick, setTick] = useState(0);
      bumpTick = () => setTick((current) => current + 1);

      return (
        <div>
          <button type="button" onClick={() => setOpen(true)}>触发按钮</button>
          <span data-testid={`tick-${tick}`}>{tick}</span>
          {open && (
            <Drawer label="主抽屉" className="drawer-panel detail-drawer-panel" onClose={() => setOpen(false)}>
              <button type="button">第一个操作</button>
              <button type="button">第二个操作</button>
            </Drawer>
          )}
        </div>
      );
    }

    render(<RerenderHarness />);
    const trigger = screen.getByRole("button", { name: "触发按钮" });
    await user.click(trigger);
    const secondButton = await screen.findByRole("button", { name: "第二个操作" });
    secondButton.focus();

    expect(document.body.style.overflow).toBe("hidden");
    expect(secondButton).toHaveFocus();

    act(() => bumpTick?.());
    expect(screen.getByTestId("tick-1")).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");
    expect(screen.getByRole("button", { name: "第二个操作" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "触发按钮" })).not.toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "主抽屉" })).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(trigger).toHaveFocus();
    });
  });

  it("closes only the top drawer on Escape and preserves the lower drawer lock", async () => {
    const user = userEvent.setup();
    function StackHarness() {
      const [primaryOpen, setPrimaryOpen] = useState(true);
      const [secondaryOpen, setSecondaryOpen] = useState(true);

      return (
        <div>
          {primaryOpen && (
            <Drawer label="主抽屉" className="drawer-panel detail-drawer-panel" onClose={() => setPrimaryOpen(false)}>
              <button type="button">主抽屉按钮</button>
            </Drawer>
          )}
          {secondaryOpen && (
            <Drawer label="次级抽屉" className="drawer-panel snapshot-reader-drawer" onClose={() => setSecondaryOpen(false)}>
              <button type="button">次级抽屉按钮</button>
            </Drawer>
          )}
        </div>
      );
    }

    const stackView = render(<StackHarness />);
    expect(await screen.findByRole("dialog", { name: "次级抽屉" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "次级抽屉" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("dialog", { name: "主抽屉" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "主抽屉" })).not.toBeInTheDocument();
    });
    expect(document.body.style.overflow).toBe("");
    stackView.unmount();
  });

  it("returns focus to the lower drawer when a nested top drawer closes", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);

    await user.click(screen.getByRole("button", { name: "触发按钮" }));
    const lowerTrigger = await screen.findByRole("button", { name: "第二个操作" });
    await user.click(lowerTrigger);
    expect(await screen.findByRole("dialog", { name: "次级抽屉" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "次级抽屉" })).not.toBeInTheDocument();
    });

    const lowerDialog = screen.getByRole("dialog", { name: "主抽屉" });
    expect(document.body.style.overflow).toBe("hidden");
    await waitFor(() => {
      expect(lowerDialog.contains(document.activeElement)).toBe(true);
    });
    expect(lowerTrigger).toHaveFocus();

    await user.tab();
    expect(screen.getByRole("button", { name: "第一个操作" })).toHaveFocus();
  });

  it("keeps focus inside the top drawer when background code calls focus", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);

    await user.click(screen.getByRole("button", { name: "触发按钮" }));
    await user.click(await screen.findByRole("button", { name: "第二个操作" }));
    const topDialog = await screen.findByRole("dialog", { name: "次级抽屉" });
    const backgroundButton = screen.getByRole("button", { name: "底层导航" });

    act(() => {
      backgroundButton.focus();
    });

    await waitFor(() => {
      expect(topDialog.contains(document.activeElement)).toBe(true);
    });
    expect(backgroundButton).not.toHaveFocus();
  });

  it("does not let a closed drawer steal focus back from a newly opened drawer", async () => {
    const user = userEvent.setup();
    render(<DrawerHarness />);

    const rootTrigger = screen.getByRole("button", { name: "触发按钮" });
    await user.click(rootTrigger);
    const nestedTrigger = await screen.findByRole("button", { name: "第二个操作" });
    await user.click(nestedTrigger);

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "次级抽屉" })).not.toBeInTheDocument();
    });

    await user.click(nestedTrigger);
    const reopenedTopDialog = await screen.findByRole("dialog", { name: "次级抽屉" });
    await waitFor(() => {
      expect(reopenedTopDialog.contains(document.activeElement)).toBe(true);
    });
    expect(rootTrigger).not.toHaveFocus();
  });

  it("does not restore focus to a background trigger when a lower drawer is still open", async () => {
    const user = userEvent.setup();
    function BackgroundTriggerHarness() {
      const [primaryOpen, setPrimaryOpen] = useState(false);
      const [secondaryOpen, setSecondaryOpen] = useState(false);

      return (
        <div>
          <button type="button" onClick={() => setPrimaryOpen(true)}>打开主抽屉</button>
          <button type="button" onClick={() => setSecondaryOpen(true)}>从背景打开次级抽屉</button>
          {primaryOpen && (
            <Drawer label="主抽屉" className="drawer-panel detail-drawer-panel" onClose={() => setPrimaryOpen(false)}>
              <button type="button">主抽屉按钮</button>
            </Drawer>
          )}
          {secondaryOpen && (
            <Drawer label="次级抽屉" className="drawer-panel snapshot-reader-drawer" onClose={() => setSecondaryOpen(false)}>
              <button type="button">次级抽屉按钮</button>
            </Drawer>
          )}
        </div>
      );
    }

    render(<BackgroundTriggerHarness />);
    await user.click(screen.getByRole("button", { name: "打开主抽屉" }));
    const backgroundTrigger = screen.getByRole("button", { name: "从背景打开次级抽屉" });
    await user.click(backgroundTrigger);
    await screen.findByRole("dialog", { name: "次级抽屉" });

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "次级抽屉" })).not.toBeInTheDocument();
    });

    const lowerDialog = screen.getByRole("dialog", { name: "主抽屉" });
    await waitFor(() => {
      expect(lowerDialog.contains(document.activeElement)).toBe(true);
    });
    expect(backgroundTrigger).not.toHaveFocus();
  });

  it("registers global listeners once and keeps them stable across rerenders", async () => {
    const user = userEvent.setup();
    const addListenerSpy = vi.spyOn(document, "addEventListener");
    const removeListenerSpy = vi.spyOn(document, "removeEventListener");

    let bumpTick: (() => void) | null = null;
    function StableHarness() {
      const [open, setOpen] = useState(false);
      const [tick, setTick] = useState(0);
      bumpTick = () => setTick((current) => current + 1);

      return (
        <div>
          <button type="button" onClick={() => setOpen(true)}>触发按钮</button>
          <span data-testid={`stable-tick-${tick}`}>{tick}</span>
          {open && (
            <Drawer label="稳定抽屉" className="drawer-panel detail-drawer-panel" onClose={() => setOpen(false)}>
              <button type="button">抽屉按钮</button>
            </Drawer>
          )}
        </div>
      );
    }

    render(<StableHarness />);
    await user.click(screen.getByRole("button", { name: "触发按钮" }));
    await screen.findByRole("dialog", { name: "稳定抽屉" });
    const keydownAddsAfterMount = addListenerSpy.mock.calls.filter(([type]) => type === "keydown").length;
    const focusinAddsAfterMount = addListenerSpy.mock.calls.filter(([type]) => type === "focusin").length;

    act(() => bumpTick?.());
    act(() => bumpTick?.());
    expect(screen.getByTestId("stable-tick-2")).toBeInTheDocument();
    expect(addListenerSpy.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(keydownAddsAfterMount);
    expect(addListenerSpy.mock.calls.filter(([type]) => type === "focusin")).toHaveLength(focusinAddsAfterMount);

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "稳定抽屉" })).not.toBeInTheDocument();
    });
    expect(removeListenerSpy.mock.calls.some(([type]) => type === "keydown")).toBe(true);
    expect(removeListenerSpy.mock.calls.some(([type]) => type === "focusin")).toBe(true);
  });
});

describe("workbench candidate intake views", () => {
  it("manages job profiles, fixed versions, tasks, and plugin context", async () => {
    let taskStatus = "ready";
    const fetchMock = vi.fn((input: string | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/job-profiles") && !init?.method) {
        return response({
          rows: [{
            id: 7,
            job_title: "量化研究员",
            department: "投研",
            location: "上海",
            employment_type: "全职",
            target_hires: 2,
            priority: "high",
            status: "active",
            version: 2,
            updated_at: "2026-08-19T10:00:00",
          }],
        });
      }
      if (url.endsWith("/api/recruitment-tasks") && !init?.method) {
        return response({
          rows: [{
            id: 11,
            name: "Boss 推荐流",
            role_id: 7,
            role_title: "量化研究员",
            profile_version: 2,
            platform: "boss",
            source_url: "https://www.zhipin.com/web/geek/recommend",
            target_candidates: 20,
            status: taskStatus,
            current_step: taskStatus === "running" ? "采集与筛选" : "待启动",
            latest_message: "",
            batch_count: 0,
            candidate_count: 0,
            run_count: 0,
            export_count: 0,
            created_at: "2026-08-19T09:00:00",
            updated_at: "2026-08-19T09:00:00",
          }],
        });
      }
      if (url.endsWith("/api/plugin-context") && !init?.method) {
        return response({ context: null });
      }
      if (url.endsWith("/api/job-profiles/7")) {
        return response({
          id: 7,
          job_title: "量化研究员",
          department: "投研",
          hiring_manager: "招聘经理",
          location: "上海",
          employment_type: "全职",
          target_hires: 2,
          priority: "high",
          status: "active",
          version: 2,
          updated_at: "2026-08-19T10:00:00",
          created_at: "2026-08-19T09:00:00",
          experience_requirement: "3 年以上",
          education_requirement: "本科",
          recruitment_deadline: "2026-10-01",
          jd_text: "负责策略研究",
          must_have: ["Python"],
          nice_to_have: ["期货"],
          risk_flags: [],
          exclusions: [],
          interview_checks: ["策略复盘"],
          evidence_policy: { required: ["项目"] },
        });
      }
      if (url.endsWith("/api/job-profiles/7/versions")) {
        return response({
          rows: [
            {
              version: 2,
              created_at: "2026-08-19T10:00:00",
              snapshot: {
                id: 7,
                job_title: "量化研究员",
                department: "投研",
                hiring_manager: "招聘经理",
                location: "上海",
                employment_type: "全职",
                target_hires: 2,
                priority: "high",
                status: "active",
                version: 2,
                updated_at: "2026-08-19T10:00:00",
                created_at: "2026-08-19T09:00:00",
                experience_requirement: "3 年以上",
                education_requirement: "本科",
                recruitment_deadline: "2026-10-01",
                jd_text: "负责策略研究",
                must_have: ["Python"],
                nice_to_have: ["期货"],
                risk_flags: [],
                exclusions: [],
                interview_checks: ["策略复盘"],
                evidence_policy: { required: ["项目"] },
              },
            },
            {
              version: 1,
              created_at: "2026-08-19T09:00:00",
              snapshot: {
                id: 7,
                job_title: "量化研究员",
                department: "投研",
                hiring_manager: "招聘经理",
                location: "上海",
                employment_type: "全职",
                target_hires: 2,
                priority: "high",
                status: "draft",
                version: 1,
                updated_at: "2026-08-18T11:00:00",
                created_at: "2026-08-18T09:00:00",
                experience_requirement: "3 年以上",
                education_requirement: "本科",
                recruitment_deadline: "2026-10-01",
                jd_text: "旧 JD",
                must_have: [],
                nice_to_have: [],
                risk_flags: [],
                exclusions: [],
                interview_checks: [],
                evidence_policy: {},
              },
            },
          ],
        });
      }
      if (url.endsWith("/api/plugin-context") && init?.method === "PUT") {
        return response({
          ok: true,
          context: {
            recruitment_task_id: 11,
            job_profile_id: 7,
            job_profile_version: 2,
            job_title: "量化研究员",
            platform: "boss",
            source_url: "https://www.zhipin.com/web/geek/recommend",
            task_status: "running",
            context_updated_at: "2026-08-19T10:05:00",
          },
          message: "已更新插件当前任务。",
        });
      }
      if (url.endsWith("/api/recruitment-tasks/11/status") && init?.method === "POST") {
        taskStatus = JSON.parse(String(init.body)).status;
        return response({
          id: 11,
          name: "Boss 推荐流",
          role_id: 7,
          role_title: "量化研究员",
          profile_version: 2,
          platform: "boss",
          source_url: "https://www.zhipin.com/web/geek/recommend",
          target_candidates: 20,
          status: taskStatus,
          current_step: taskStatus === "running" ? "采集与筛选" : "待启动",
          latest_message: "",
          batch_count: 0,
          candidate_count: 0,
          run_count: 0,
          export_count: 0,
          created_at: "2026-08-19T09:00:00",
          updated_at: "2026-08-19T10:05:00",
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "岗位" }));
    expect(await screen.findByRole("heading", { name: "岗位、版本与招聘任务" })).toBeInTheDocument();
    expect(screen.getByText("量化研究员")).toBeInTheDocument();
    expect(screen.queryByText("待开发")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看" }));
    expect(await screen.findByRole("dialog", { name: "岗位档案详情" })).toBeInTheDocument();
    expect(screen.getByText("版本历史")).toBeInTheDocument();
    expect(screen.getAllByText("v2").length).toBeGreaterThanOrEqual(1);
    const latestVersionCard = document.querySelector(".version-card") as HTMLElement;
    expect(latestVersionCard).toBeTruthy();
    await user.click(latestVersionCard.querySelector("summary") as HTMLElement);
    expect(within(latestVersionCard).getByText("岗位 ID")).toBeInTheDocument();
    expect(within(latestVersionCard).getByText("#7")).toBeInTheDocument();
    expect(within(latestVersionCard).getByText("岗位版本")).toBeInTheDocument();
    expect(within(latestVersionCard).getByText("岗位创建时间")).toBeInTheDocument();
    expect(within(latestVersionCard).getByText("2026/8/19 09:00:00")).toBeInTheDocument();
    expect(within(latestVersionCard).getByText("岗位更新时间")).toBeInTheDocument();
    expect(within(latestVersionCard).getAllByText("2026/8/19 10:00:00").length).toBeGreaterThanOrEqual(1);
    expect(within(latestVersionCard).getByText("证据要求")).toBeInTheDocument();
    expect(within(latestVersionCard).getByText(/required/)).toBeInTheDocument();
    const firstVersionCard = document.querySelectorAll(".version-card")[1] as HTMLElement;
    await user.click(firstVersionCard.querySelector("summary") as HTMLElement);
    expect(within(firstVersionCard).getByText("2026/8/18 09:00:00")).toBeInTheDocument();
    expect(within(firstVersionCard).getByText("2026/8/18 11:00:00")).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: /设为插件当前任务/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "启动" }));
    await user.click(screen.getByRole("button", { name: "设为插件当前任务" }));
    expect(await screen.findByText("已设为插件当前任务：Boss 推荐流")).toBeInTheDocument();
    const contextCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith("/api/plugin-context") && init?.method === "PUT");
    expect(contextCall?.[1]?.body).toBe(JSON.stringify({ recruitment_task_id: 11 }));
    expect(fetchMock.mock.calls.map(([url]) => String(url)).join("|")).not.toContain("prompt_text");
  });

  it("keeps dangerous confirmation drawers open on failure and retries safely", async () => {
    let closeAttempts = 0;
    let cancelAttempts = 0;
    let taskStatus = "running";
    const fetchMock = vi.fn((input: string | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/job-profiles") && !init?.method) {
        return response({
          rows: [{
            id: 7,
            job_title: "关闭测试岗位",
            department: "投研",
            location: "上海",
            employment_type: "全职",
            target_hires: 2,
            priority: "high",
            status: closeAttempts >= 2 ? "closed" : "active",
            version: closeAttempts >= 2 ? 3 : 2,
            updated_at: "2026-08-19T10:00:00",
          }],
        });
      }
      if (url.endsWith("/api/recruitment-tasks") && !init?.method) {
        return response({
          rows: [{
            id: 11,
            name: "待取消任务",
            role_id: 7,
            role_title: "关闭测试岗位",
            profile_version: 2,
            platform: "boss",
            source_url: "https://www.zhipin.com/web/geek/recommend",
            target_candidates: 20,
            status: taskStatus,
            current_step: taskStatus === "cancelled" ? "已取消" : "采集与筛选",
            latest_message: "",
            batch_count: 0,
            candidate_count: 0,
            run_count: 0,
            export_count: 0,
            created_at: "2026-08-19T09:00:00",
            updated_at: "2026-08-19T09:00:00",
          }],
        });
      }
      if (url.endsWith("/api/plugin-context") && !init?.method) {
        return response({ context: null });
      }
      if (url.endsWith("/api/job-profiles/7") && !url.endsWith("/versions")) {
        return response({
          id: 7,
          job_title: "关闭测试岗位",
          department: "投研",
          hiring_manager: "招聘经理",
          location: "上海",
          employment_type: "全职",
          target_hires: 2,
          priority: "high",
          status: closeAttempts >= 2 ? "closed" : "active",
          version: closeAttempts >= 2 ? 3 : 2,
          updated_at: "2026-08-19T10:00:00",
          created_at: "2026-08-19T09:00:00",
          experience_requirement: "",
          education_requirement: "",
          recruitment_deadline: "",
          jd_text: "JD",
          must_have: [],
          nice_to_have: [],
          risk_flags: [],
          exclusions: [],
          interview_checks: [],
          evidence_policy: {},
        });
      }
      if (url.endsWith("/api/job-profiles/7/versions")) {
        return response({ rows: [] });
      }
      if (url.endsWith("/api/job-profiles/7/status") && init?.method === "POST") {
        closeAttempts += 1;
        if (closeAttempts === 1) {
          return errorResponse("岗位关闭失败，请稍后重试。");
        }
        return response({
          id: 7,
          job_title: "关闭测试岗位",
          department: "投研",
          hiring_manager: "招聘经理",
          location: "上海",
          employment_type: "全职",
          target_hires: 2,
          priority: "high",
          status: "closed",
          version: 3,
          updated_at: "2026-08-19T10:10:00",
          created_at: "2026-08-19T09:00:00",
          experience_requirement: "",
          education_requirement: "",
          recruitment_deadline: "",
          jd_text: "JD",
          must_have: [],
          nice_to_have: [],
          risk_flags: [],
          exclusions: [],
          interview_checks: [],
          evidence_policy: {},
        });
      }
      if (url.endsWith("/api/recruitment-tasks/11/status") && init?.method === "POST") {
        cancelAttempts += 1;
        if (cancelAttempts === 1) {
          return errorResponse("招聘任务取消失败，请稍后重试。");
        }
        taskStatus = "cancelled";
        return response({
          id: 11,
          name: "待取消任务",
          role_id: 7,
          role_title: "关闭测试岗位",
          profile_version: 2,
          platform: "boss",
          source_url: "https://www.zhipin.com/web/geek/recommend",
          target_candidates: 20,
          status: "cancelled",
          current_step: "已取消",
          latest_message: "",
          batch_count: 0,
          candidate_count: 0,
          run_count: 0,
          export_count: 0,
          created_at: "2026-08-19T09:00:00",
          updated_at: "2026-08-19T10:10:00",
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "岗位" }));
    await user.click(await screen.findByRole("button", { name: "查看" }));
    await screen.findByRole("dialog", { name: "岗位档案详情" });
    await user.click(screen.getByRole("button", { name: "关闭岗位" }));
    const closeDialog = await screen.findByRole("dialog", { name: "确认关闭岗位" });
    await user.click(within(closeDialog).getByRole("button", { name: "先不关闭" }));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/job-profiles/7/status"))).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "关闭岗位" }));
    const failingCloseDialog = await screen.findByRole("dialog", { name: "确认关闭岗位" });
    await user.click(within(failingCloseDialog).getByRole("button", { name: "确认关闭岗位" }));
    expect(await within(failingCloseDialog).findByRole("alert")).toHaveTextContent("岗位关闭失败，请稍后重试。");
    expect(screen.queryByText("岗位状态已更新。")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "确认关闭岗位" })).toBeInTheDocument();
    await user.click(within(failingCloseDialog).getByRole("button", { name: "确认关闭岗位" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "确认关闭岗位" })).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/job-profiles/7/status"))).toHaveLength(2);
    expect(await screen.findByText("岗位状态已更新。")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "取消" }));
    const cancelDialog = await screen.findByRole("dialog", { name: "确认取消招聘任务" });
    await user.click(within(cancelDialog).getByRole("button", { name: "先不取消" }));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/recruitment-tasks/11/status"))).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "取消" }));
    const failingCancelDialog = await screen.findByRole("dialog", { name: "确认取消招聘任务" });
    await user.click(within(failingCancelDialog).getByRole("button", { name: "确认取消任务" }));
    expect(await within(failingCancelDialog).findByRole("alert")).toHaveTextContent("招聘任务取消失败，请稍后重试。");
    expect(screen.queryByText("任务状态已更新。")).not.toBeInTheDocument();
    expect(screen.getByText("待取消任务")).toBeInTheDocument();
    await user.click(within(failingCancelDialog).getByRole("button", { name: "确认取消任务" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "确认取消招聘任务" })).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/recruitment-tasks/11/status"))).toHaveLength(2);
    expect(await screen.findByText("任务状态已更新。")).toBeInTheDocument();
  });

  it("previews and imports external ratings for running recruitment tasks", async () => {
    let importAttempts = 0;
    const fetchMock = vi.fn((input: string | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/job-profiles") && !init?.method) {
        return response({ rows: [] });
      }
      if (url.endsWith("/api/recruitment-tasks") && !init?.method) {
        return response({
          rows: [{
            id: 11,
            name: "Boss 推荐流",
            role_id: 7,
            role_title: "量化研究员",
            profile_version: 2,
            platform: "boss",
            source_url: "https://www.zhipin.com/web/geek/recommend",
            target_candidates: 20,
            status: "running",
            current_step: "采集与筛选",
            latest_message: "",
            batch_count: 1,
            candidate_count: 2,
            run_count: 0,
            export_count: 0,
            created_at: "2026-08-19T09:00:00",
            updated_at: "2026-08-19T09:00:00",
          }],
        });
      }
      if (url.endsWith("/api/plugin-context") && !init?.method) {
        return response({ context: null });
      }
      if (url.endsWith("/api/recruitment-tasks/11/external-ratings/import") && init?.method === "POST") {
        importAttempts += 1;
        if (importAttempts === 1) {
          return errorResponse("外部评级导入失败，请稍后重试。");
        }
        return response({
          task_id: 11,
          run_id: 32,
          status: "partial",
          received: 3,
          imported: 1,
          unmatched: 1,
          ambiguous: 0,
          invalid: 1,
          rows: [
            { line: 1, candidate_id: 7, name: "Alice", rating: "SSR", status: "imported", message: "已导入外部评级。" },
            { line: 2, candidate_id: null, name: "Nobody", rating: "SR", status: "unmatched", message: "未在当前招聘任务的岗位关系中找到唯一候选人。" },
            { line: 3, candidate_id: null, name: "Broken", rating: "A+", status: "invalid", message: "评级只能是 UR、SSR、SR、R、N。" },
          ],
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "岗位" }));
    await screen.findByText("Boss 推荐流");
    await user.click(screen.getByRole("button", { name: "导入外部评级" }));
    const dialog = await screen.findByRole("dialog", { name: "导入外部评级" });
    await user.type(within(dialog).getByLabelText("粘贴评级名单"), "candidate_id,name,rating\n7,Alice,SSR\n,Nobody,SR\n,Broken,A+");
    expect(within(dialog).getByText("解析 3 行")).toBeInTheDocument();
    expect(within(dialog).getByText("可导入 2 行")).toBeInTheDocument();
    expect(within(dialog).getByText("格式待修正 1 行")).toBeInTheDocument();
    expect(within(dialog).getByText("1SSR")).toBeInTheDocument();
    expect(within(dialog).getByText("评级无效")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "确认导入外部评级" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("外部评级导入失败，请稍后重试。");
    expect(within(dialog).getByLabelText("粘贴评级名单")).toHaveValue("candidate_id,name,rating\n7,Alice,SSR\n,Nobody,SR\n,Broken,A+");
    await user.click(within(dialog).getByRole("button", { name: "确认导入外部评级" }));
    expect(await within(dialog).findByRole("status")).toHaveTextContent("成功 1");
    expect(within(dialog).getByText("未匹配 1")).toBeInTheDocument();
    expect(within(dialog).getByText("无效 1")).toBeInTheDocument();
    const importCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/recruitment-tasks/11/external-ratings/import"));
    expect(importCall?.[1]?.body).toContain("candidate_id,name,rating");
    expect(importCall?.[1]?.body).toContain("7,Alice,SSR");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/recruitment-tasks/11/external-ratings/import"))).toHaveLength(2);
  });

  it("previews TSV external rating headers without disabling import", async () => {
    const fetchMock = vi.fn((input: string | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/job-profiles") && !init?.method) return response({ rows: [] });
      if (url.endsWith("/api/recruitment-tasks") && !init?.method) {
        return response({
          rows: [{
            id: 11,
            name: "Boss 推荐流",
            role_id: 7,
            role_title: "量化研究员",
            profile_version: 2,
            platform: "boss",
            source_url: "https://www.zhipin.com/web/geek/recommend",
            target_candidates: 20,
            status: "running",
            current_step: "采集与筛选",
            latest_message: "",
            batch_count: 1,
            candidate_count: 2,
            run_count: 0,
            export_count: 0,
            created_at: "2026-08-19T09:00:00",
            updated_at: "2026-08-19T09:00:00",
          }],
        });
      }
      if (url.endsWith("/api/plugin-context") && !init?.method) return response({ context: null });
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "岗位" }));
    await screen.findByText("Boss 推荐流");
    await user.click(screen.getByRole("button", { name: "导入外部评级" }));
    const dialog = await screen.findByRole("dialog", { name: "导入外部评级" });
    await user.click(within(dialog).getByLabelText("粘贴评级名单"));
    await user.paste("id\tcandidate_name\trating\n8\tBob\tSR");

    expect(within(dialog).getByText("解析 1 行")).toBeInTheDocument();
    expect(within(dialog).getByText("可导入 1 行")).toBeInTheDocument();
    expect(within(dialog).getByText("Bob")).toBeInTheDocument();
    expect(within(dialog).getByText("1SR")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "确认导入外部评级" })).toBeEnabled();
  });

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
    expect(await screen.findByRole("button", { name: "查看候选人" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导出 Markdown" })).toBeInTheDocument();
    expect(screen.getAllByText("#9").length).toBeGreaterThan(0);
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
    expect(screen.getByRole("dialog", { name: "原始快照" })).toBeInTheDocument();
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
              latest_rating: "SSR",
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
          latest_rating: "SSR",
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
    expect(screen.getAllByText("1SSR").length).toBeGreaterThanOrEqual(1);
    await user.selectOptions(screen.getByLabelText("外部评级"), "SSR");
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("rating=SSR"))).toBe(true);
    });

    await user.click(screen.getByRole("button", { name: "查看详情" }));
    const detailDrawer = await screen.findByRole("dialog", { name: "候选人详情" });
    expect(within(detailDrawer).getAllByText("量化研究员").length).toBeGreaterThan(0);
    expect(within(detailDrawer).getByText("1SSR")).toBeInTheDocument();
    expect(screen.getByText("原始卡片关键词与快照")).toBeInTheDocument();

    await user.click(within(detailDrawer).getByRole("button", { name: "打开最近批次 #11" }));
    expect(await screen.findByRole("heading", { name: "批次 #11" })).toBeInTheDocument();
  });

  it("renders the candidate detail in four sections with safe links and missing values", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url.includes("/api/candidates?")) {
          return response({
            rows: [{
              id: 18,
              name: "Readable Candidate",
              source_platform: "boss",
              latest_source_platform: "boss",
              latest_source_job_title: "高级交易员岗位职责很长很长需要截断展示",
              latest_batch_id: 33,
              latest_capture_time: "2026-08-12T09:00:00",
              latest_ingest_status: "updated",
              latest_batch_role_id: null,
              has_role_binding: 0,
              batch_count: 3,
            }],
            total: 1,
            page: 1,
            page_size: 100,
          });
        }
        if (url === "/api/candidates/18") {
          return response({
            id: 18,
            name: "Readable Candidate",
            source_platform: "boss",
            latest_source_platform: "boss",
            latest_source_job_title: "高级交易员岗位职责很长很长需要截断展示",
            latest_batch_id: 33,
            latest_capture_time: "2026-08-12T09:00:00",
            latest_ingest_status: "updated",
            latest_batch_role_id: null,
            has_role_binding: 0,
            job_title: "",
            source_url: "https://example.test/source",
            capture_time: "2026-08-12T09:00:00",
            raw_card_text: "",
            active_status: "",
            expected_salary: "",
            work_experience_text: "",
            education_text: "",
            tags_text: "",
            summary_text: "",
            detail_url: "javascript:alert(1)",
            latest_raw_card_text: "",
            latest_source_url: "https://example.test/source",
            latest_detail_url: "file:///secret",
            city: "",
            years_experience: null,
            job_family: "",
            job_track: "",
            batch_count: 3,
          });
        }
        if (url === "/api/candidates/18/appearances") {
          return response({ rows: [] });
        }
        if (url.includes("/api/capture-batches?")) {
          return response({ rows: [], total: 0, page: 1, page_size: 20 });
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    await user.click(await screen.findByRole("button", { name: "查看详情" }));
    const detailDrawer = await screen.findByRole("dialog", { name: "候选人详情" });

    expect(within(detailDrawer).getByRole("heading", { name: "身份摘要" })).toBeInTheDocument();
    expect(within(detailDrawer).getByRole("heading", { name: "基础信息" })).toBeInTheDocument();
    expect(within(detailDrawer).getByRole("heading", { name: "摘要与链接" })).toBeInTheDocument();
    expect(within(detailDrawer).getByRole("heading", { name: "来源出现历史" })).toBeInTheDocument();
    expect(within(detailDrawer).getAllByText("未提供").length).toBeGreaterThan(3);
    expect(within(detailDrawer).getByRole("link", { name: "打开来源页面" })).toHaveAttribute("href", "https://example.test/source");
    expect(within(detailDrawer).getByRole("link", { name: "打开来源页面" })).toHaveAttribute("target", "_blank");
    expect(within(detailDrawer).getByRole("link", { name: "打开来源页面" })).toHaveAttribute("rel", "noreferrer");
    expect(within(detailDrawer).queryByRole("link", { name: "打开候选人详情" })).not.toBeInTheDocument();
  });

  it("expands, collapses, and copies candidate snapshots with success and failure feedback", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url.includes("/api/candidates?")) {
          return response({
            rows: [{
              id: 21,
              name: "Snapshot Candidate",
              source_platform: "boss",
              latest_source_platform: "boss",
              latest_source_job_title: "交易员",
              latest_batch_id: 61,
              latest_capture_time: "2026-08-12T10:00:00",
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
        if (url === "/api/candidates/21") {
          return response({
            id: 21,
            name: "Snapshot Candidate",
            source_platform: "boss",
            latest_source_platform: "boss",
            latest_source_job_title: "交易员",
            latest_batch_id: 61,
            latest_capture_time: "2026-08-12T10:00:00",
            latest_ingest_status: "new",
            latest_batch_role_id: null,
            has_role_binding: 0,
            job_title: "交易员",
            source_url: "",
            capture_time: "2026-08-12T10:00:00",
            raw_card_text: "",
            active_status: "",
            expected_salary: "",
            work_experience_text: "",
            education_text: "",
            tags_text: "",
            summary_text: "",
            detail_url: "",
            latest_raw_card_text: "第一行\n第二行\n第三行\n第四行\n第五行\n第六行\n第七行\n第八行\n第九行",
            latest_source_url: "",
            latest_detail_url: "",
            city: "",
            years_experience: null,
            job_family: "",
            job_track: "",
            batch_count: 1,
          });
        }
        if (url === "/api/candidates/21/appearances") {
          return response({ rows: [] });
        }
        if (url.includes("/api/capture-batches?")) {
          return response({ rows: [], total: 0, page: 1, page_size: 20 });
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const writeText = vi.spyOn(navigator.clipboard, "writeText")
      .mockResolvedValueOnce()
      .mockRejectedValueOnce(new Error("copy failed"));
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    await user.click(await screen.findByRole("button", { name: "查看详情" }));
    const detailDrawer = await screen.findByRole("dialog", { name: "候选人详情" });

    await user.click(within(detailDrawer).getByRole("button", { name: "展开完整快照" }));
    expect(within(detailDrawer).getByRole("button", { name: "收起" })).toBeInTheDocument();
    await user.click(within(detailDrawer).getByRole("button", { name: "复制快照" }));
    expect(writeText).toHaveBeenCalledWith("第一行\n第二行\n第三行\n第四行\n第五行\n第六行\n第七行\n第八行\n第九行");
    expect(await within(detailDrawer).findByRole("status")).toHaveTextContent("已复制快照。");
    await user.click(within(detailDrawer).getByRole("button", { name: "复制快照" }));
    expect(await within(detailDrawer).findByRole("status")).toHaveTextContent("复制失败，请稍后重试。");
  });

  it("navigates batch snapshots in place and closes stale snapshots when pagination changes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url.includes("/api/capture-batches?")) {
          return response({
            rows: [{
              id: 75,
              start_time: "2026-08-12T10:30:00",
              source_platform: "boss",
              total_collected: 3,
              total_new: 2,
              total_updated: 1,
              total_skipped: 0,
              total_failed: 0,
              status: "completed",
              role_id: null,
            }],
            total: 1,
            page: 1,
            page_size: 20,
            today_summary: { received: 3, added: 2 },
          });
        }
        if (url.includes("/api/capture-batches/75/candidates?page=1&page_size=50")) {
          return response({
            rows: [
              {
                id: 1,
                batch_id: 75,
                candidate_id: 501,
                name: "第一页候选人甲",
                source_platform: "boss",
                platform_uid: "boss:501",
                job_title: "来源岗位甲",
                capture_time: "2026-08-12T10:30:00",
                raw_card_text: "第一页快照甲",
                ingest_status: "new",
                has_role_binding: 0,
              },
              {
                id: 2,
                batch_id: 75,
                candidate_id: 502,
                name: "第一页候选人乙",
                source_platform: "boss",
                platform_uid: "boss:502",
                job_title: "来源岗位乙",
                capture_time: "2026-08-12T10:31:00",
                raw_card_text: "第一页快照乙",
                ingest_status: "updated",
                has_role_binding: 0,
              },
            ],
            total: 51,
            page: 1,
            page_size: 50,
          });
        }
        if (url.includes("/api/capture-batches/75/candidates?page=2&page_size=50")) {
          return response({
            rows: [
              {
                id: 3,
                batch_id: 75,
                candidate_id: 503,
                name: "第二页候选人",
                source_platform: "boss",
                platform_uid: "boss:503",
                job_title: "来源岗位丙",
                capture_time: "2026-08-12T10:32:00",
                raw_card_text: "第二页快照",
                ingest_status: "new",
                has_role_binding: 0,
              },
            ],
            total: 51,
            page: 2,
            page_size: 50,
          });
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    await user.click(await screen.findByRole("button", { name: "查看候选人" }));
    const snapshotButtons = await screen.findAllByRole("button", { name: "查看原始快照" });
    await user.click(snapshotButtons[0]);

    const snapshotDrawer = await screen.findByRole("dialog", { name: "原始快照" });
    expect(within(snapshotDrawer).getByText("第一页候选人甲")).toBeInTheDocument();
    expect(within(snapshotDrawer).getByText("1 / 2")).toBeInTheDocument();
    expect(within(snapshotDrawer).getByRole("button", { name: "上一个" })).toBeDisabled();

    await user.click(within(snapshotDrawer).getByRole("button", { name: "下一个" }));
    expect(await within(snapshotDrawer).findByText("第一页候选人乙")).toBeInTheDocument();
    expect(within(snapshotDrawer).getByText("2 / 2")).toBeInTheDocument();
    expect(within(snapshotDrawer).getByRole("button", { name: "下一个" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "原始快照" })).not.toBeInTheDocument();
    });
    expect(await screen.findByText("第二页候选人")).toBeInTheDocument();
  });

  it("closes drawers with Escape, restores focus, and releases background scroll lock", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url.includes("/api/candidates?")) {
          return response({
            rows: [{
              id: 31,
              name: "Focus Candidate",
              source_platform: "boss",
              latest_source_platform: "boss",
              latest_source_job_title: "交易员",
              latest_batch_id: 91,
              latest_capture_time: "2026-08-12T11:30:00",
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
        if (url === "/api/candidates/31") {
          return response({
            id: 31,
            name: "Focus Candidate",
            source_platform: "boss",
            latest_source_platform: "boss",
            latest_source_job_title: "交易员",
            latest_batch_id: 91,
            latest_capture_time: "2026-08-12T11:30:00",
            latest_ingest_status: "new",
            latest_batch_role_id: null,
            has_role_binding: 0,
            job_title: "交易员",
            source_url: "",
            capture_time: "2026-08-12T11:30:00",
            raw_card_text: "",
            active_status: "",
            expected_salary: "",
            work_experience_text: "",
            education_text: "",
            tags_text: "",
            summary_text: "",
            detail_url: "",
            latest_raw_card_text: "快照",
            latest_source_url: "",
            latest_detail_url: "",
            city: "",
            years_experience: null,
            job_family: "",
            job_track: "",
            batch_count: 1,
          });
        }
        if (url === "/api/candidates/31/appearances") {
          return response({ rows: [] });
        }
        if (url.includes("/api/capture-batches?")) {
          return response({ rows: [], total: 0, page: 1, page_size: 20 });
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    const detailButton = await screen.findByRole("button", { name: "查看详情" });
    await user.click(detailButton);
    expect(await screen.findByRole("dialog", { name: "候选人详情" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "候选人详情" })).not.toBeInTheDocument();
    });
    expect(document.body.style.overflow).toBe("");
    expect(detailButton).toHaveFocus();
  });

  it("closes candidate dialogs when switching away from the candidates page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url.includes("/api/candidates?")) {
          return response({
            rows: [{
              id: 32,
              name: "Switch Candidate",
              source_platform: "boss",
              latest_source_platform: "boss",
              latest_source_job_title: "交易员",
              latest_batch_id: 92,
              latest_capture_time: "2026-08-12T11:40:00",
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
        if (url === "/api/candidates/32") {
          return response({
            id: 32,
            name: "Switch Candidate",
            source_platform: "boss",
            latest_source_platform: "boss",
            latest_source_job_title: "交易员",
            latest_batch_id: 92,
            latest_capture_time: "2026-08-12T11:40:00",
            latest_ingest_status: "new",
            latest_batch_role_id: null,
            has_role_binding: 0,
            job_title: "交易员",
            source_url: "",
            capture_time: "2026-08-12T11:40:00",
            raw_card_text: "",
            active_status: "",
            expected_salary: "",
            work_experience_text: "",
            education_text: "",
            tags_text: "",
            summary_text: "",
            detail_url: "",
            latest_raw_card_text: "切页快照",
            latest_source_url: "",
            latest_detail_url: "",
            city: "",
            years_experience: null,
            job_family: "",
            job_track: "",
            batch_count: 1,
          });
        }
        if (url === "/api/candidates/32/appearances") {
          return response({ rows: [] });
        }
        if (url.includes("/api/capture-batches?")) {
          return response({ rows: [], total: 0, page: 1, page_size: 20 });
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "候选人" }));
    await user.click(await screen.findByRole("button", { name: "查看详情" }));
    expect(await screen.findByRole("dialog", { name: "候选人详情" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "候选人详情" })).not.toBeInTheDocument();
    });
    expect(document.body.style.overflow).toBe("");
  });

  it("closes batch snapshot dialogs when switching away from the batch page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const url = String(input);
        if (url.includes("/api/capture-batches?")) {
          return response({
            rows: [{
              id: 93,
              start_time: "2026-08-12T12:10:00",
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
        if (url.includes("/api/capture-batches/93/candidates")) {
          return response({
            rows: [{
              id: 1,
              batch_id: 93,
              candidate_id: 800,
              name: "Snapshot Candidate",
              source_platform: "boss",
              platform_uid: "boss:800",
              job_title: "快照岗位",
              capture_time: "2026-08-12T12:10:00",
              raw_card_text: "批次快照内容",
              ingest_status: "new",
              has_role_binding: 0,
            }],
            total: 1,
            page: 1,
            page_size: 50,
          });
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    render(<Workbench status={status} />);

    await user.click(screen.getByRole("button", { name: "最近批次" }));
    await user.click(await screen.findByRole("button", { name: "查看候选人" }));
    await user.click(await screen.findByRole("button", { name: "查看原始快照" }));
    expect(await screen.findByRole("dialog", { name: "原始快照" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await user.click(screen.getByRole("button", { name: "设置" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "原始快照" })).not.toBeInTheDocument();
    });
    expect(document.body.style.overflow).toBe("");
  });

  it("keeps a reduced-motion drawer rule available for accessibility", async () => {
    const stylesPath = resolve(process.cwd(), "src/styles.css");
    const stylesSource = readFileSync(stylesPath, "utf8");
    expect(stylesSource).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(stylesSource).toMatch(/\.drawer-panel\s*\{[^}]*animation:\s*none\s*!important;[^}]*transform:\s*none\s*!important;/s);
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
    const aliceDrawer = await screen.findByRole("dialog", { name: "候选人详情" });
    expect(within(aliceDrawer).getByText("正在读取来源出现历史…")).toBeInTheDocument();

    await user.click(detailButtons[1]);
    const bobDrawer = await screen.findByRole("dialog", { name: "候选人详情" });
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
    const retryDrawer = await screen.findByRole("dialog", { name: "候选人详情" });
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

  it("uses the shared markdown downloader from both batch list and batch detail", async () => {
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input);
      if (url.includes("/api/capture-batches?")) {
        return response({
          rows: [{
            id: 120,
            start_time: "2026-08-18T10:20:00",
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
      if (url === "/api/capture-batches/121") {
        return response({
          id: 121,
          start_time: "2026-08-18T10:40:00",
          source_platform: "liepin",
          total_collected: 1,
          total_new: 1,
          total_updated: 0,
          total_skipped: 0,
          total_failed: 0,
          status: "completed",
          role_id: null,
        });
      }
      if (url.includes("/api/capture-batches/121/candidates")) {
        return response({ rows: [], total: 0, page: 1, page_size: 50 });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const downloader = vi.spyOn(apiModule, "downloadBatchMarkdown").mockResolvedValue();
    const user = userEvent.setup();

    render(<Workbench status={status} />);
    await user.click(screen.getByRole("button", { name: "最近批次" }));
    await user.click(await screen.findByRole("button", { name: "导出 Markdown" }));
    expect(downloader).toHaveBeenCalledWith(120);

    await user.type(screen.getByLabelText("批次 ID 搜索"), "121");
    await user.click(screen.getByRole("button", { name: "打开批次" }));
    await user.click(await screen.findByRole("button", { name: "导出 Markdown" }));
    expect(downloader).toHaveBeenCalledWith(121);
  });
});
