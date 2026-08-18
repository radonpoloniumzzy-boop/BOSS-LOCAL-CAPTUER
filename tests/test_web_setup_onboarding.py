from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from setup_web_workbench import (
    SetupFailure,
    build_context,
    default_runner,
    is_supported_python_version,
    run_checked,
    run_setup,
)


class SetupWorkbenchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._write_minimal_project()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_minimal_project(self) -> None:
        (self.root / "web" / "frontend" / "dist" / "assets").mkdir(parents=True, exist_ok=True)
        (self.root / "extension").mkdir(parents=True, exist_ok=True)
        (self.root / "web_app.py").write_text("print('web')\n", encoding="utf-8")
        (self.root / "requirements.txt").write_text("fastapi>=0.116,<1\n", encoding="utf-8")
        (self.root / "launch_web_workbench.cmd").write_text("@echo off\r\n", encoding="utf-8")
        (self.root / "extension" / "manifest.json").write_text(
            json.dumps({"manifest_version": 3, "version": "0.5.1"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.root / "web" / "frontend" / "dist" / "index.html").write_text(
            '<link rel="stylesheet" href="/assets/index.css"><script src="/assets/index.js"></script>',
            encoding="utf-8",
        )
        (self.root / "web" / "frontend" / "dist" / "assets" / "index.js").write_text(
            "console.log('ok');",
            encoding="utf-8",
        )
        (self.root / "web" / "frontend" / "dist" / "assets" / "index.css").write_text(
            "body { color: #111; }",
            encoding="utf-8",
        )

    def _runner(
        self,
        *,
        fail_command: tuple[str, ...] | None = None,
        create_venv: bool = True,
        version_output: str = "cpython|3|12",
        fail_with_partial_venv: bool = False,
        create_pythonw: bool = True,
        pythonw_returncode: int = 0,
    ):
        calls: list[dict[str, object]] = []
        context = build_context(self.root)

        def run(command, *, cwd, capture_output):
            command = list(command)
            calls.append({"command": command, "cwd": cwd, "capture_output": capture_output})
            if fail_command and tuple(command[: len(fail_command)]) == fail_command:
                if fail_with_partial_venv and command[:4] == ["py", "-3.12", "-m", "venv"]:
                    context.venv_python.parent.mkdir(parents=True, exist_ok=True)
                    context.venv_python.write_text("", encoding="utf-8")
                    if create_pythonw:
                        context.venv_pythonw.write_text("", encoding="utf-8")
                class Result:
                    returncode = 1
                    stdout = ""
                    stderr = "failed"

                return Result()
            if command[:4] == ["py", "-3.12", "-m", "venv"] and create_venv:
                context.venv_python.parent.mkdir(parents=True, exist_ok=True)
                context.venv_python.write_text("", encoding="utf-8")
                if create_pythonw:
                    context.venv_pythonw.write_text("", encoding="utf-8")
            class Result:
                returncode = pythonw_returncode if command and command[0] == str(context.venv_pythonw) else 0
                stdout = version_output if command and command[0] == str(context.venv_python) and "-c" in command else ""
                stderr = ""

            return Result()

        return calls, run

    def test_detects_supported_python_version(self) -> None:
        self.assertTrue(is_supported_python_version((3, 12, 5)))
        self.assertFalse(is_supported_python_version((3, 11, 9)))

    def test_run_setup_rejects_non_python_312_runtime(self) -> None:
        with self.assertRaises(SetupFailure) as caught:
            run_setup(
                self.root,
                version_info=(3, 11, 9),
                runner=lambda _command, *, cwd, capture_output: None,
            )
        self.assertEqual(caught.exception.code, "python_312_required")

    def test_default_runner_executes_real_command_with_captured_output(self) -> None:
        completed = default_runner(
            [sys.executable, "-c", "print('runner-ok')"],
            cwd=self.root,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual((completed.stdout or "").strip(), "runner-ok")

    def test_run_checked_uses_real_runner_contract_without_override(self) -> None:
        completed = run_checked(
            [sys.executable, "-c", "print('checked-ok')"],
            cwd=self.root,
            code="unexpected",
            message="should not fail",
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual((completed.stdout or "").strip(), "checked-ok")

    def test_creates_missing_venv_with_py312_command(self) -> None:
        calls, runner = self._runner()
        message = run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(message, "初始化完成，请双击 launch_web_workbench.cmd 启动网页工作台。")
        create_call = next(entry["command"] for entry in calls if entry["command"][:4] == ["py", "-3.12", "-m", "venv"])
        self.assertEqual(Path(create_call[4]), (self.root / ".venv").resolve())
        self.assertFalse((self.root / "bootstrap.json").exists())
        self.assertFalse((self.root / "data" / "boss_local_tool.db").exists())

    def test_existing_venv_is_reused_without_recreation(self) -> None:
        context = build_context(self.root)
        context.venv_python.parent.mkdir(parents=True, exist_ok=True)
        context.venv_python.write_text("", encoding="utf-8")
        context.venv_pythonw.write_text("", encoding="utf-8")
        calls, runner = self._runner(create_venv=False)
        run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertFalse(any(entry["command"][:4] == ["py", "-3.12", "-m", "venv"] for entry in calls))

    def test_existing_venv_missing_pythonw_fails_without_install(self) -> None:
        context = build_context(self.root)
        context.venv_python.parent.mkdir(parents=True, exist_ok=True)
        context.venv_python.write_text("", encoding="utf-8")
        calls, runner = self._runner(create_venv=False)
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "venv_incomplete")
        self.assertIn("仅将当前项目目录里的 .venv 重命名为备份目录", str(caught.exception))
        self.assertFalse(any(entry["command"][0:3] == [str(context.venv_python), "-m", "pip"] for entry in calls))

    def test_existing_venv_wrong_python_version_fails_without_overwrite(self) -> None:
        context = build_context(self.root)
        context.venv_python.parent.mkdir(parents=True, exist_ok=True)
        context.venv_python.write_text("", encoding="utf-8")
        context.venv_pythonw.write_text("", encoding="utf-8")
        calls, runner = self._runner(create_venv=False, version_output="cpython|3|11")
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "venv_invalid")
        self.assertTrue(context.venv_dir.exists())
        self.assertFalse(any(entry["command"][:4] == ["py", "-3.12", "-m", "venv"] for entry in calls))
        self.assertFalse(any(entry["command"][0:3] == [str(context.venv_python), "-m", "pip"] for entry in calls))

    def test_dependency_install_failure_returns_stable_error(self) -> None:
        calls, runner = self._runner(
            fail_command=(str((self.root / ".venv" / "Scripts" / "python.exe").resolve()), "-m", "pip")
        )
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "dependency_install_failed")
        self.assertIn("依赖安装失败", str(caught.exception))
        self.assertTrue(calls)
        pip_call = next(entry for entry in calls if entry["command"][0:3] == [str((self.root / ".venv" / "Scripts" / "python.exe").resolve()), "-m", "pip"])
        self.assertFalse(pip_call["capture_output"])

    def test_new_venv_failure_preserves_half_created_environment_as_backup(self) -> None:
        calls, runner = self._runner(
            fail_command=("py", "-3.12", "-m", "venv"),
            fail_with_partial_venv=True,
        )
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "venv_create_failed")
        self.assertFalse((self.root / ".venv").exists())
        backups = list(self.root.glob(".venv.incomplete-*"))
        self.assertEqual(len(backups), 1)
        self.assertIn(backups[0].name, str(caught.exception))
        self.assertFalse(any(entry["command"][0:3] == [str((self.root / ".venv" / "Scripts" / "python.exe").resolve()), "-m", "pip"] for entry in calls))
        retry_calls, retry_runner = self._runner()
        run_setup(self.root, version_info=(3, 12, 0), runner=retry_runner)
        self.assertTrue((self.root / ".venv").exists())

    def test_new_venv_missing_pythonw_is_preserved_as_backup_and_skips_pip(self) -> None:
        calls, runner = self._runner(create_pythonw=False)
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "venv_create_failed")
        self.assertFalse((self.root / ".venv").exists())
        backups = list(self.root.glob(".venv.incomplete-*"))
        self.assertEqual(len(backups), 1)
        self.assertFalse(any(entry["command"][0:3] == [str((self.root / ".venv" / "Scripts" / "python.exe").resolve()), "-m", "pip"] for entry in calls))

    def test_new_venv_invalid_python_version_is_preserved_as_backup_and_skips_pip(self) -> None:
        calls, runner = self._runner(version_output="cpython|3|11")
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "venv_create_failed")
        self.assertFalse((self.root / ".venv").exists())
        backups = list(self.root.glob(".venv.incomplete-*"))
        self.assertEqual(len(backups), 1)
        self.assertFalse(any(entry["command"][0:3] == [str((self.root / ".venv" / "Scripts" / "python.exe").resolve()), "-m", "pip"] for entry in calls))

    def test_existing_incomplete_venv_is_not_recreated(self) -> None:
        context = build_context(self.root)
        context.venv_dir.mkdir(parents=True, exist_ok=True)
        calls, runner = self._runner(create_venv=False)
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "venv_incomplete")
        self.assertFalse(any(entry["command"][:4] == ["py", "-3.12", "-m", "venv"] for entry in calls))
        self.assertIn("仅将当前项目目录里的 .venv 重命名为备份目录", str(caught.exception))

    def test_pythonw_validation_nonzero_fails_without_install(self) -> None:
        calls, runner = self._runner(create_venv=False, pythonw_returncode=1)
        context = build_context(self.root)
        context.venv_python.parent.mkdir(parents=True, exist_ok=True)
        context.venv_python.write_text("", encoding="utf-8")
        context.venv_pythonw.write_text("", encoding="utf-8")
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "venv_invalid")
        pythonw_calls = [entry for entry in calls if entry["command"] and entry["command"][0] == str(context.venv_pythonw)]
        self.assertEqual(len(pythonw_calls), 1)
        self.assertFalse(pythonw_calls[0]["capture_output"])
        self.assertFalse(any(entry["command"][0:3] == [str(context.venv_python), "-m", "pip"] for entry in calls))

    def test_existing_venv_pythonw_oserror_fails_with_stable_protocol(self) -> None:
        context = build_context(self.root)
        context.venv_python.parent.mkdir(parents=True, exist_ok=True)
        context.venv_python.write_text("", encoding="utf-8")
        context.venv_pythonw.write_text("", encoding="utf-8")
        local_app_data = self.root / "localappdata-pythonw-oserror"
        local_app_data.mkdir()
        calls: list[dict[str, object]] = []

        def runner(command, *, cwd, capture_output):
            command = list(command)
            calls.append({"command": command, "cwd": cwd, "capture_output": capture_output})
            if command and command[0] == str(context.venv_pythonw):
                raise PermissionError("pythonw blocked")

            class Result:
                returncode = 0
                stdout = "cpython|3|12" if command and command[0] == str(context.venv_python) and "-c" in command else ""
                stderr = ""

            return Result()

        with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
            with self.assertRaises(SetupFailure) as caught:
                run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "venv_invalid")
        self.assertTrue(context.venv_dir.exists())
        self.assertTrue(context.venv_python.exists())
        self.assertTrue(context.venv_pythonw.exists())
        self.assertEqual(list(self.root.glob(".venv.incomplete-*")), [])
        self.assertFalse(any(entry["command"][0:3] == [str(context.venv_python), "-m", "pip"] for entry in calls))
        self.assertFalse((local_app_data / "RecruitingTalentWorkbench" / "bootstrap.json").exists())
        self.assertFalse((self.root / "boss_local_tool.db").exists())
        self.assertFalse((self.root / "data" / "boss_local_tool.db").exists())

    def test_new_venv_failed_preserve_rename_keeps_original_directory_and_skips_pip(self) -> None:
        calls, runner = self._runner(create_pythonw=False)
        context = build_context(self.root)
        local_app_data = self.root / "localappdata-rename-failure"
        local_app_data.mkdir()
        original_rename = Path.rename

        def guarded_rename(path_self: Path, target):
            if path_self == context.venv_dir:
                raise OSError("rename denied")
            return original_rename(path_self, target)

        with patch.object(Path, "rename", autospec=True, side_effect=guarded_rename):
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
                with self.assertRaises(SetupFailure) as caught:
                    run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "venv_create_failed")
        self.assertTrue(context.venv_dir.exists())
        self.assertTrue(context.venv_python.exists())
        self.assertEqual(list(self.root.glob(".venv.incomplete-*")), [])
        self.assertIn("手工将当前项目目录里的 .venv 重命名为备份目录后", str(caught.exception))
        self.assertFalse(any(entry["command"][0:3] == [str(context.venv_python), "-m", "pip"] for entry in calls))
        self.assertFalse((local_app_data / "RecruitingTalentWorkbench" / "bootstrap.json").exists())
        self.assertFalse((self.root / "boss_local_tool.db").exists())
        self.assertFalse((self.root / "data" / "boss_local_tool.db").exists())

    def test_run_setup_prints_visible_progress_and_keeps_success_paths_clean(self) -> None:
        calls, runner = self._runner()
        stdout = StringIO()
        with redirect_stdout(stdout):
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        output = stdout.getvalue()
        self.assertIn("正在检查 CPython 3.12", output)
        self.assertIn("正在检查或创建项目运行环境", output)
        self.assertIn("正在安装项目依赖", output)
        self.assertIn("正在检查网页资源和插件文件", output)
        venv_call = next(entry for entry in calls if entry["command"][:4] == ["py", "-3.12", "-m", "venv"])
        self.assertFalse(venv_call["capture_output"])

    def test_requirements_missing_real_run_setup_failure_does_not_create_bootstrap_or_db(self) -> None:
        context = build_context(self.root)
        context.venv_python.parent.mkdir(parents=True, exist_ok=True)
        context.venv_python.write_text("", encoding="utf-8")
        context.venv_pythonw.write_text("", encoding="utf-8")
        (self.root / "requirements.txt").unlink()
        local_app_data = self.root / "localappdata"
        local_app_data.mkdir()
        calls, runner = self._runner(create_venv=False)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
            with self.assertRaises(SetupFailure) as caught:
                run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "requirements_missing")
        self.assertFalse((local_app_data / "RecruitingTalentWorkbench" / "bootstrap.json").exists())
        self.assertFalse((self.root / "boss_local_tool.db").exists())
        self.assertFalse((self.root / "data" / "boss_local_tool.db").exists())
        self.assertFalse(any(entry["command"][0:3] == [str(context.venv_python), "-m", "pip"] for entry in calls))

    def test_main_reports_stable_failure_code_without_creating_database_files(self) -> None:
        import setup_web_workbench

        stderr = StringIO()
        with patch.object(
            setup_web_workbench,
            "run_setup",
            side_effect=SetupFailure("requirements_missing", "项目缺少 requirements.txt，无法完成初始化。"),
        ):
            with redirect_stderr(stderr):
                exit_code = setup_web_workbench.main()
        self.assertEqual(exit_code, 1)
        self.assertIn("requirements_missing", stderr.getvalue())
        self.assertFalse((self.root / "bootstrap.json").exists())
        self.assertFalse((self.root / "data" / "boss_local_tool.db").exists())

    def test_setup_success_does_not_create_bootstrap_or_db_under_temp_localappdata(self) -> None:
        local_app_data = self.root / "localappdata-success"
        local_app_data.mkdir()
        calls, runner = self._runner()
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
            message = run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertIn("初始化完成", message)
        self.assertFalse((local_app_data / "RecruitingTalentWorkbench" / "bootstrap.json").exists())
        self.assertFalse((self.root / "boss_local_tool.db").exists())
        self.assertFalse((self.root / "data" / "boss_local_tool.db").exists())

    def test_frontend_resource_missing_fails(self) -> None:
        (self.root / "web" / "frontend" / "dist" / "assets" / "index.js").unlink()
        calls, runner = self._runner()
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "frontend_missing")

    def test_extension_manifest_missing_fails(self) -> None:
        (self.root / "extension" / "manifest.json").unlink()
        calls, runner = self._runner()
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "project_file_missing")
        self.assertIn("extension", str(caught.exception))
        self.assertIn("manifest.json", str(caught.exception))

    def test_setup_cmd_is_utf8_crlf_and_uses_official_python_entry(self) -> None:
        cmd = (Path(__file__).resolve().parents[1] / "setup_web_workbench.cmd").read_bytes()
        self.assertFalse(cmd.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", cmd)
        text = cmd.decode("utf-8")
        self.assertIn("py -3.12", text)
        self.assertIn("setup_web_workbench.py", text)
        self.assertNotIn("python setup_web_workbench.py", text)

    def test_launcher_missing_venv_points_to_setup_cmd(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "launch_web_workbench.cmd").read_text(encoding="utf-8")
        self.assertIn("setup_web_workbench.cmd", text)
        self.assertIn("缺少网页工作台运行环境", text)

    def test_readme_and_guides_are_portable_and_current_preview_is_not_fixed_to_old_audit_commit(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        readme = (repo / "README.md").read_text(encoding="utf-8")
        quick_start = (repo / "docs" / "guides" / "web-workbench-quick-start.md").read_text(encoding="utf-8")
        backup = (repo / "docs" / "guides" / "backup-and-recovery.md").read_text(encoding="utf-8")
        current_preview = (repo / "docs" / "releases" / "current-preview.md").read_text(encoding="utf-8")
        self.assertTrue((repo / "docs" / "guides" / "web-workbench-quick-start.md").is_file())
        self.assertTrue((repo / "docs" / "guides" / "backup-and-recovery.md").is_file())
        self.assertTrue((repo / "docs" / "releases" / "current-preview.md").is_file())
        self.assertIn("launch_web_workbench.cmd", readme)
        self.assertIn("setup_web_workbench.cmd", readme)
        self.assertIn("[网页工作台快速开始](docs/guides/web-workbench-quick-start.md)", readme)
        self.assertIn("[备份与恢复](docs/guides/backup-and-recovery.md)", readme)
        self.assertIn("[当前预览版本说明](docs/releases/current-preview.md)", readme)
        self.assertIn("<项目目录>", readme)
        for text in (readme, quick_start, backup, current_preview):
            self.assertNotIn(r"D:\codex\BOSS-LOCAL-CAPTURE-review", text)
        self.assertIn("正式下载基准", current_preview)
        self.assertIn("GitHub `main`", current_preview)
        self.assertIn("M0 开始时的审计基线", current_preview)
        self.assertNotIn("当前确认基线提交", current_preview)


if __name__ == "__main__":
    unittest.main()
