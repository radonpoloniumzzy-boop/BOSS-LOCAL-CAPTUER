from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from web.backend.workbench_launcher import LaunchFailure, create_default_launcher


def main() -> int:
    root = tk.Tk()
    root.title("启动网页工作台")
    root.geometry("440x210")
    root.resizable(False, False)
    root.configure(bg="#f6f7f9")
    status = tk.StringVar(value="正在准备启动…")
    tk.Label(root, text="招聘人才工作台", font=("Microsoft YaHei UI", 16, "bold"), bg="#f6f7f9", fg="#172033").pack(pady=(34, 12))
    tk.Label(root, textvariable=status, font=("Microsoft YaHei UI", 10), bg="#f6f7f9", fg="#3b4658").pack(pady=8)
    events: queue.Queue[tuple[str, str]] = queue.Queue()

    def progress(message: str) -> None:
        events.put(("progress", message))

    def run() -> None:
        try:
            create_default_launcher(Path(__file__).resolve().parent, progress).launch()
            events.put(("done", ""))
        except LaunchFailure as exc:
            events.put(("error", str(exc)))
        except Exception:
            events.put(("error", "网页工作台启动失败。请检查运行环境和本地日志后重试。"))

    def poll() -> None:
        try:
            kind, message = events.get_nowait()
        except queue.Empty:
            root.after(80, poll)
            return
        if kind == "progress":
            status.set(message)
            root.after(80, poll)
        elif kind == "done":
            root.after(500, root.destroy)
        else:
            status.set("启动未完成")
            messagebox.showerror("无法启动网页工作台", message, parent=root)

    threading.Thread(target=run, daemon=True).start()
    root.after(80, poll)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
