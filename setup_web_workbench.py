from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from web.backend.workbench_launcher import _frontend_assets_ready


EXPECTED_PYTHON_MAJOR = 3
EXPECTED_PYTHON_MINOR = 12


class SetupFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SetupContext:
    project_root: Path
    venv_dir: Path
    venv_python: Path
    requirements_file: Path


def build_context(project_root: Path) -> SetupContext:
    root = project_root.resolve()
    return SetupContext(
        project_root=root,
        venv_dir=root / ".venv",
        venv_python=root / ".venv" / "Scripts" / "python.exe",
        requirements_file=root / "requirements.txt",
    )


def is_supported_python_version(version_info: Sequence[int] | object) -> bool:
    major = getattr(version_info, "major", None)
    minor = getattr(version_info, "minor", None)
    if major is None or minor is None:
        try:
            major = int(version_info[0])  # type: ignore[index]
            minor = int(version_info[1])  # type: ignore[index]
        except (TypeError, ValueError, IndexError):
            return False
    return int(major) == EXPECTED_PYTHON_MAJOR and int(minor) == EXPECTED_PYTHON_MINOR


def default_runner(command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] | None = None,
    code: str,
    message: str,
) -> subprocess.CompletedProcess[str]:
    invoke = runner or (lambda current: default_runner(current, cwd=cwd))
    try:
        completed = invoke(command)
    except OSError as exc:
        raise SetupFailure(code, message) from exc
    if completed.returncode != 0:
        raise SetupFailure(code, message)
    return completed


def validate_existing_venv(
    context: SetupContext,
    *,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    if not context.venv_python.is_file():
        raise SetupFailure(
            "venv_missing_python",
            "现有 .venv 缺少 python.exe，请重新运行 setup_web_workbench.cmd 完成初始化。",
        )
    completed = run_checked(
        [str(context.venv_python), "-V"],
        cwd=context.project_root,
        runner=runner,
        code="venv_invalid",
        message="现有 .venv 不是可用的官方 CPython 3.12 运行环境，请修复后重新初始化。",
    )
    version_text = (completed.stdout or completed.stderr or "").strip()
    if not version_text.startswith("Python 3.12"):
        raise SetupFailure(
            "venv_invalid",
            "现有 .venv 不是可用的官方 CPython 3.12 运行环境，请修复后重新初始化。",
        )


def ensure_venv(
    context: SetupContext,
    *,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    if not context.venv_dir.exists():
        run_checked(
            ["py", "-3.12", "-m", "venv", str(context.venv_dir)],
            cwd=context.project_root,
            runner=runner,
            code="venv_create_failed",
            message="无法创建网页工作台运行环境，请确认官方 CPython 3.12 可用后重试。",
        )
    validate_existing_venv(context, runner=runner)


def install_requirements(
    context: SetupContext,
    *,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    if not context.requirements_file.is_file():
        raise SetupFailure("requirements_missing", "项目缺少 requirements.txt，无法完成初始化。")
    run_checked(
        [str(context.venv_python), "-m", "pip", "install", "-r", str(context.requirements_file)],
        cwd=context.project_root,
        runner=runner,
        code="dependency_install_failed",
        message="网页工作台依赖安装失败，请检查网络或 Python 环境后重试。",
    )


def validate_project_files(context: SetupContext) -> None:
    required_files = [
        context.project_root / "web_app.py",
        context.project_root / "extension" / "manifest.json",
        context.project_root / "launch_web_workbench.cmd",
    ]
    for path in required_files:
        if not path.is_file():
            raise SetupFailure("project_file_missing", f"项目文件不完整，缺少 {path.relative_to(context.project_root)}。")
    if not _frontend_assets_ready(context.project_root):
        raise SetupFailure(
            "frontend_missing",
            "网页工作台前端资源不完整，请确认 web/frontend/dist 已包含 index.html 和对应 assets。",
        )


def run_setup(
    project_root: Path,
    *,
    version_info: Sequence[int] | object | None = None,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] | None = None,
) -> str:
    if not is_supported_python_version(version_info or sys.version_info):
        raise SetupFailure(
            "python_312_required",
            "需要使用官方 CPython 3.12 运行 setup_web_workbench.py。",
        )
    context = build_context(project_root)
    ensure_venv(context, runner=runner)
    install_requirements(context, runner=runner)
    validate_project_files(context)
    return "初始化完成，请双击 launch_web_workbench.cmd 启动网页工作台。"


def main() -> int:
    try:
        message = run_setup(Path(__file__).resolve().parent)
    except SetupFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
