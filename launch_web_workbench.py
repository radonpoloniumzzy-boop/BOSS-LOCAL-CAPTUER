from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Callable

from core.bootstrap import BootstrapStore
from web.backend.workbench_launcher import (
    LaunchCancelled,
    LaunchFailure,
    STEP_CHECK_FRONTEND,
    STEP_CHECK_PORT,
    STEP_CHECK_RUNTIME,
    STEP_CONFIRM_DATABASE,
    STEP_CONNECT_DATABASE,
    STEP_LABELS,
    STEP_OPEN_BROWSER,
    STEP_READ_CONFIG,
    create_default_launcher,
)

WINDOW_TITLE = "启动网页工作台"
WINDOW_SIZE = "560x420"
STEP_ORDER = [
    STEP_READ_CONFIG,
    STEP_CHECK_RUNTIME,
    STEP_CHECK_FRONTEND,
    STEP_CHECK_PORT,
    STEP_CONNECT_DATABASE,
    STEP_CONFIRM_DATABASE,
    STEP_OPEN_BROWSER,
]
STATE_LABELS = {
    "waiting": "等待检查",
    "running": "检查中",
    "completed": "已完成",
    "failed": "需要处理",
}
LOG_NAME = "web-launcher.log"


class LauncherLog:
    def __init__(self, project_root: Path) -> None:
        self.path = BootstrapStore().path.parent / "logs" / LOG_NAME
        self.project_root = project_root
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, line: str) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line.strip() + "\n")
        except OSError:
            return


class LaunchWindow:
    def __init__(
        self,
        project_root: Path,
        *,
        launcher_factory: Callable[..., object] = create_default_launcher,
        root: tk.Tk | None = None,
    ) -> None:
        self.project_root = project_root
        self.launcher_factory = launcher_factory
        self.root = root or tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.resizable(False, False)
        self.root.configure(bg="#f6f7f9")
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.logger = LauncherLog(project_root)
        self.running = False
        self.failure: LaunchFailure | None = None
        self.cancel_event = threading.Event()
        self.message = tk.StringVar(value="正在准备启动检查…")
        self.hint = tk.StringVar(value="网页端与桌面端不能同时使用同一人才库。")
        self.step_status: dict[str, tk.StringVar] = {
            step: tk.StringVar(value=STATE_LABELS["waiting"]) for step in STEP_ORDER
        }
        self._build_ui()
        self.root.after(80, self._poll)

    def _build_ui(self) -> None:
        container = tk.Frame(self.root, bg="#f6f7f9")
        container.pack(fill="both", expand=True, padx=24, pady=22)

        tk.Label(
            container,
            text="网页工作台启动检查",
            font=("Microsoft YaHei UI", 17, "bold"),
            bg="#f6f7f9",
            fg="#172033",
        ).pack(anchor="w")
        tk.Label(
            container,
            textvariable=self.message,
            font=("Microsoft YaHei UI", 10),
            bg="#f6f7f9",
            fg="#334155",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(10, 6))
        tk.Label(
            container,
            textvariable=self.hint,
            font=("Microsoft YaHei UI", 9),
            bg="#f6f7f9",
            fg="#64748b",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(0, 14))

        self.steps_frame = tk.Frame(container, bg="#ffffff", highlightbackground="#d8dee8", highlightthickness=1)
        self.steps_frame.pack(fill="x")
        for step in STEP_ORDER:
            row = tk.Frame(self.steps_frame, bg="#ffffff")
            row.pack(fill="x", padx=14, pady=8)
            tk.Label(
                row,
                text=STEP_LABELS[step],
                bg="#ffffff",
                fg="#172033",
                font=("Microsoft YaHei UI", 10),
                anchor="w",
            ).pack(side="left")
            tk.Label(
                row,
                textvariable=self.step_status[step],
                bg="#ffffff",
                fg="#2563eb",
                font=("Microsoft YaHei UI", 9, "bold"),
                anchor="e",
            ).pack(side="right")

        self.detail = tk.Text(
            container,
            height=7,
            bg="#ffffff",
            fg="#334155",
            relief="solid",
            borderwidth=1,
            wrap="word",
            font=("Microsoft YaHei UI", 9),
        )
        self.detail.pack(fill="both", expand=True, pady=(14, 14))
        self.detail.insert("1.0", "启动器会在这里显示真实检查结果。\n")
        self.detail.configure(state="disabled")

        buttons = tk.Frame(container, bg="#f6f7f9")
        buttons.pack(fill="x")
        self.retry_button = tk.Button(buttons, text="重新检查", command=self.start_check, state="disabled")
        self.retry_button.pack(side="left")
        self.help_button = tk.Button(buttons, text="查看恢复说明", command=self.show_help, state="disabled")
        self.help_button.pack(side="left", padx=(10, 0))
        self.close_button = tk.Button(buttons, text="关闭", command=self.request_close)
        self.close_button.pack(side="right")

    def append_detail(self, line: str) -> None:
        self.detail.configure(state="normal")
        self.detail.insert("end", line.rstrip() + "\n")
        self.detail.see("end")
        self.detail.configure(state="disabled")
        self.logger.write(line)

    def progress(self, event: dict[str, str]) -> None:
        self.events.put(("progress", event))

    def show_help(self) -> None:
        if self.failure is None:
            return
        messagebox.showinfo("恢复说明", self.failure.recovery, parent=self.root)

    def start_check(self) -> None:
        if self.running:
            return
        self.running = True
        self.failure = None
        self.cancel_event.clear()
        self.retry_button.configure(state="disabled")
        self.help_button.configure(state="disabled")
        self.close_button.configure(text="取消启动")
        self.message.set("正在执行启动检查…")
        self.hint.set("会按真实检查结果逐步推进，不会伪造进度。")
        for variable in self.step_status.values():
            variable.set(STATE_LABELS["waiting"])
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.configure(state="disabled")
        self.append_detail("开始新的网页工作台启动检查。")

        def run() -> None:
            try:
                launcher = self.launcher_factory(
                    self.project_root,
                    self.progress,
                    cancel_requested=self.cancel_event.is_set,
                )
                launcher.launch()
                self.events.put(("done", None))
            except LaunchCancelled as exc:
                self.events.put(("cancelled", exc))
            except LaunchFailure as exc:
                self.events.put(("error", exc))
            except Exception:
                self.events.put(("error", LaunchFailure("service_start_failed")))

        threading.Thread(target=run, daemon=True).start()

    def request_close(self) -> None:
        if self.running:
            self.cancel_startup()
            return
        self.root.destroy()

    def cancel_startup(self) -> None:
        if not self.running or self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self.message.set("正在取消启动检查…")
        self.hint.set("如果本轮已经启动了本地服务，会在退出前回收本轮进程。")
        self.close_button.configure(state="disabled")
        self.retry_button.configure(state="disabled")
        self.help_button.configure(state="disabled")
        self.append_detail("收到取消请求，正在停止本轮启动。")

    def _mark_progress(self, event: dict[str, str]) -> None:
        step = event.get("step")
        state = event.get("state")
        detail = event.get("detail") or ""
        if step in self.step_status and state in STATE_LABELS:
            self.step_status[step].set(STATE_LABELS[state])
        if detail:
            self.message.set(detail)
            self.append_detail(detail)

    def _handle_failure(self, failure: LaunchFailure) -> None:
        self.failure = failure
        self.running = False
        if failure.step in self.step_status:
            self.step_status[failure.step].set(STATE_LABELS["failed"])
        self.message.set(str(failure))
        self.hint.set("你可以先看恢复说明，再点击“重新检查”。")
        self.append_detail(f"启动失败：{failure}")
        self.retry_button.configure(state="normal")
        self.help_button.configure(state="normal")
        self.close_button.configure(state="normal", text="关闭")

    def _handle_cancelled(self, cancelled: LaunchCancelled) -> None:
        self.running = False
        if cancelled.step in self.step_status and self.step_status[cancelled.step].get() == STATE_LABELS["running"]:
            self.step_status[cancelled.step].set(STATE_LABELS["waiting"])
        self.message.set("已取消本轮启动检查。")
        self.hint.set("本轮创建的启动进程已停止。你可以重新检查或直接关闭。")
        self.append_detail("本轮启动已取消。")
        self.retry_button.configure(state="normal")
        self.help_button.configure(state="disabled")
        self.close_button.configure(state="normal", text="关闭")

    def _poll(self) -> None:
        try:
            kind, payload = self.events.get_nowait()
        except queue.Empty:
            self.root.after(80, self._poll)
            return
        if kind == "progress":
            self._mark_progress(payload)
        elif kind == "done":
            self.running = False
            self.message.set("网页工作台已准备完成。")
            self.hint.set("浏览器正在打开正确端口的工作台。")
            self.append_detail("启动完成。")
            self.close_button.configure(state="normal", text="关闭")
            self.root.after(900, self.root.destroy)
        elif kind == "cancelled":
            self._handle_cancelled(payload)
        elif kind == "error":
            self._handle_failure(payload)
        self.root.after(80, self._poll)

    def mainloop(self) -> int:
        self.start_check()
        self.root.mainloop()
        return 0


def main() -> int:
    return LaunchWindow(Path(__file__).resolve().parent).mainloop()


if __name__ == "__main__":
    raise SystemExit(main())
