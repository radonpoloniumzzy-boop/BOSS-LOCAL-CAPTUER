from __future__ import annotations

import subprocess
import sys
from datetime import datetime
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
    venv_pythonw: Path
    requirements_file: Path


def build_context(project_root: Path) -> SetupContext:
    root = project_root.resolve()
    return SetupContext(
        project_root=root,
        venv_dir=root / ".venv",
        venv_python=root / ".venv" / "Scripts" / "python.exe",
        venv_pythonw=root / ".venv" / "Scripts" / "pythonw.exe",
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


def default_runner(
    command: Sequence[str],
    *,
    cwd: Path,
    capture_output: bool,
) -> subprocess.CompletedProcess[str]:
    stdout = subprocess.PIPE if capture_output else None
    stderr = subprocess.PIPE if capture_output else None
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        stdout=stdout,
        stderr=stderr,
        text=capture_output,
        check=False,
    )


def run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    runner: Callable[[Sequence[str], Path, bool], subprocess.CompletedProcess[str]] | None = None,
    code: str,
    message: str,
    capture_output: bool,
) -> subprocess.CompletedProcess[str]:
    invoke = runner or default_runner
    try:
        completed = invoke(
            command,
            cwd=cwd,
            capture_output=capture_output,
        )
    except OSError as exc:
        raise SetupFailure(code, message) from exc
    if completed.returncode != 0:
        raise SetupFailure(code, message)
    return completed


def _existing_venv_recovery_message(reason: str) -> str:
    return (
        f"当前项目内的 .venv 无法继续使用：{reason}。"
        "请先关闭相关程序，仅将当前项目目录里的 .venv 重命名为备份目录后，再重新运行 setup_web_workbench.cmd。"
    )


def _created_venv_failure_message(base_message: str, backup_dir: Path | None = None) -> str:
    if backup_dir is not None:
        return (
            f"{base_message} 已保留本次失败残留目录：{backup_dir.name}。"
            "下次可直接重新运行 setup_web_workbench.cmd。"
        )
    if backup_dir is None:
        return (
            f"{base_message} 如果当前项目目录里已经出现残留 .venv，"
            "请先关闭相关程序，手工将当前项目目录里的 .venv 重命名为备份目录后，再重新运行 setup_web_workbench.cmd。"
        )


def _incomplete_backup_path(context: SetupContext) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = context.project_root / f".venv.incomplete-{timestamp}"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = context.project_root / f".venv.incomplete-{timestamp}-{suffix}"
    return candidate


def _preserve_incomplete_venv(context: SetupContext) -> Path | None:
    if not context.venv_dir.exists():
        return None
    backup_dir = _incomplete_backup_path(context)
    try:
        context.venv_dir.rename(backup_dir)
    except OSError:
        return None
    return backup_dir


def _verify_cpython_312(
    context: SetupContext,
    *,
    runner: Callable[[Sequence[str], Path, bool], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    completed = run_checked(
        [
            str(context.venv_python),
            "-c",
            "import sys; print(f'{sys.implementation.name}|{sys.version_info.major}|{sys.version_info.minor}')",
        ],
        cwd=context.project_root,
        runner=runner,
        code="venv_invalid",
        message=_existing_venv_recovery_message("它不是可用的官方 CPython 3.12 运行环境"),
        capture_output=True,
    )
    version_text = (completed.stdout or completed.stderr or "").strip()
    if version_text != "cpython|3|12":
        raise SetupFailure(
            "venv_invalid",
            _existing_venv_recovery_message("它不是可用的官方 CPython 3.12 运行环境"),
        )


def _verify_pythonw_312(
    context: SetupContext,
    *,
    runner: Callable[[Sequence[str], Path, bool], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    run_checked(
        [
            str(context.venv_pythonw),
            "-c",
            (
                "import sys; "
                "raise SystemExit(0 if sys.implementation.name == 'cpython' and "
                "sys.version_info[:2] == (3, 12) else 1)"
            ),
        ],
        cwd=context.project_root,
        runner=runner,
        code="venv_invalid",
        message=_existing_venv_recovery_message("pythonw.exe 无法作为官方 CPython 3.12 运行"),
        capture_output=False,
    )


def validate_existing_venv(
    context: SetupContext,
    *,
    runner: Callable[[Sequence[str], Path, bool], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    if not context.venv_python.is_file():
        raise SetupFailure(
            "venv_incomplete",
            _existing_venv_recovery_message("缺少 python.exe"),
        )
    if not context.venv_pythonw.is_file():
        raise SetupFailure(
            "venv_incomplete",
            _existing_venv_recovery_message("缺少 pythonw.exe"),
        )
    _verify_cpython_312(context, runner=runner)
    _verify_pythonw_312(context, runner=runner)


def ensure_venv(
    context: SetupContext,
    *,
    runner: Callable[[Sequence[str], Path, bool], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    venv_preexisting = context.venv_dir.exists()
    if venv_preexisting:
        validate_existing_venv(context, runner=runner)
        return
    try:
        run_checked(
            ["py", "-3.12", "-m", "venv", str(context.venv_dir)],
            cwd=context.project_root,
            runner=runner,
            code="venv_create_failed",
            message="无法创建网页工作台运行环境，请确认官方 CPython 3.12 可用后重试。",
            capture_output=False,
        )
        validate_existing_venv(context, runner=runner)
    except SetupFailure as exc:
        backup_dir = _preserve_incomplete_venv(context)
        raise SetupFailure(
            "venv_create_failed",
            _created_venv_failure_message(str(exc), backup_dir),
        ) from exc


def install_requirements(
    context: SetupContext,
    *,
    runner: Callable[[Sequence[str], Path, bool], subprocess.CompletedProcess[str]] | None = None,
) -> None:
    if not context.requirements_file.is_file():
        raise SetupFailure("requirements_missing", "项目缺少 requirements.txt，无法完成初始化。")
    run_checked(
        [str(context.venv_python), "-m", "pip", "install", "-r", str(context.requirements_file)],
        cwd=context.project_root,
        runner=runner,
        code="dependency_install_failed",
        message="网页工作台依赖安装失败，请检查网络或 Python 环境后重试。",
        capture_output=False,
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
    runner: Callable[[Sequence[str], Path, bool], subprocess.CompletedProcess[str]] | None = None,
) -> str:
    if not is_supported_python_version(version_info or sys.version_info):
        raise SetupFailure(
            "python_312_required",
            "需要使用官方 CPython 3.12 运行 setup_web_workbench.py。",
        )
    context = build_context(project_root)
    print("正在检查 CPython 3.12")
    print("正在检查或创建项目运行环境")
    ensure_venv(context, runner=runner)
    print("正在安装项目依赖")
    install_requirements(context, runner=runner)
    print("正在检查网页资源和插件文件")
    validate_project_files(context)
    return "初始化完成，请双击 launch_web_workbench.cmd 启动网页工作台。"


def main() -> int:
    try:
        message = run_setup(Path(__file__).resolve().parent)
    except SetupFailure as exc:
        print(f"初始化失败 [{exc.code}]", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
