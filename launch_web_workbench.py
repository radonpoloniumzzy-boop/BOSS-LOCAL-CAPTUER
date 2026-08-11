from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from core.bootstrap import BootstrapStore
from web.backend.workbench_launcher import (
    LaunchFailure,
    STEP_CHECK_FRONTEND,
    STEP_CHECK_PORT,
    STEP_CHECK_RUNTIME,
    STEP_CONFIRM_DATABASE,
    STEP_CONNECT_DATABASE,
    STEP_OPEN_BROWSER,
    STEP_READ_CONFIG,
    create_default_launcher,
)

WINDOW_TITLE = "启动网页工作台"
WINDOW_SIZE = "560x420"
STEP_LABELS = [
    STEP_READ_CONFIG,
    STEP_CHECK_RUNTIME,
    STEP_CHECK_FRONTEND,
    STEP_CHECK_PORT,
    STEP_CONNECT_DATABASE,
    STEP_CONFIRM_DATABASE,
    STEP_OPEN_BROWSER,
]
STEP_WAITING = "等待检查"
STEP_WORKING = "检查中"
STEP_DONE = "已完成"
STEP_FAILED = "需要处理"
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
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.resizable(False, False)
        self.root.configure(bg="#f6f7f9")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.logger = LauncherLog(project_root)
        self.running = False
        self.failure: LaunchFailure | None = None
        self.message = tk.StringVar(value="正在准备启动检查…")
        self.hint = tk.StringVar(value="网页端与桌面端不能同时使用同一人才库。")
        self.step_status: dict[str, tk.StringVar] = {
            step: tk.StringVar(value=STEP_WAITING) for step in STEP_LABELS
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
        for step in STEP_LABELS:
            row = tk.Frame(self.steps_frame, bg="#ffffff")
            row.pack(fill="x", padx=14, pady=8)
            tk.Label(
                row,
                text=step,
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
        self.close_button = tk.Button(buttons, text="关闭", command=self.root.destroy)
        self.close_button.pack(side="right")

    def append_detail(self, line: str) -> None:
        self.detail.configure(state="normal")
        self.detail.insert("end", line.rstrip() + "\n")
        self.detail.see("end")
        self.detail.configure(state="disabled")
        self.logger.write(line)

    def progress(self, message: str) -> None:
        self.events.put(("progress", message))

    def show_help(self) -> None:
        if self.failure is None:
            return
        messagebox.showinfo("恢复说明", self.failure.recovery, parent=self.root)

    def start_check(self) -> None:
        if self.running:
            return
        self.running = True
        self.failure = None
        self.retry_button.configure(state="disabled")
        self.help_button.configure(state="disabled")
        self.message.set("正在执行启动检查…")
        self.hint.set("会按真实检查结果逐步推进，不会伪造进度。")
        for variable in self.step_status.values():
            variable.set(STEP_WAITING)
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.configure(state="disabled")
        self.append_detail("开始新的网页工作台启动检查。")

        def run() -> None:
            try:
                create_default_launcher(self.project_root, self.progress).launch()
                self.events.put(("done", None))
            except LaunchFailure as exc:
                self.events.put(("error", exc))
            except Exception:
                self.events.put(("error", LaunchFailure("service_start_failed")))

        threading.Thread(target=run, daemon=True).start()

    def _mark_progress(self, message: str) -> None:
        if message in self.step_status:
            for step in STEP_LABELS:
                current = self.step_status[step].get()
                if step == message:
                    self.step_status[step].set(STEP_WORKING)
                    break
                if current in {STEP_WAITING, STEP_WORKING}:
                    self.step_status[step].set(STEP_DONE)
        elif message == "网页工作台已经运行":
            self.step_status[STEP_CHECK_PORT].set(STEP_DONE)
        elif message == "正在启动本地服务":
            self.step_status[STEP_CONFIRM_DATABASE].set(STEP_WORKING)
        elif message == "正在等待网页工作台响应":
            self.step_status[STEP_CONFIRM_DATABASE].set(STEP_WORKING)
        self.message.set(message)
        self.append_detail(message)

    def _handle_failure(self, failure: LaunchFailure) -> None:
        self.failure = failure
        self.running = False
        active = next((step for step in STEP_LABELS if self.step_status[step].get() == STEP_WORKING), None)
        if active:
            self.step_status[active].set(STEP_FAILED)
        self.message.set(str(failure))
        self.hint.set("你可以先看恢复说明，再点击“重新检查”。")
        self.append_detail(f"启动失败：{failure}")
        self.retry_button.configure(state="normal")
        self.help_button.configure(state="normal")

    def _poll(self) -> None:
        try:
            kind, payload = self.events.get_nowait()
        except queue.Empty:
            self.root.after(80, self._poll)
            return
        if kind == "progress":
            self._mark_progress(str(payload))
        elif kind == "done":
            for step in STEP_LABELS:
                if self.step_status[step].get() == STEP_WORKING:
                    self.step_status[step].set(STEP_DONE)
            self.running = False
            self.message.set("网页工作台已准备完成。")
            self.hint.set("浏览器正在打开正确端口的工作台。")
            self.append_detail("启动完成。")
            self.root.after(900, self.root.destroy)
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
