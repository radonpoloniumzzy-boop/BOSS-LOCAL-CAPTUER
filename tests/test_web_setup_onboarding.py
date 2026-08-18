from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from setup_web_workbench import SetupFailure, build_context, is_supported_python_version, run_setup


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

    def _runner(self, *, fail_command: tuple[str, ...] | None = None, create_venv: bool = True):
        calls: list[list[str]] = []
        context = build_context(self.root)

        def run(command):
            command = list(command)
            calls.append(command)
            if fail_command and tuple(command[: len(fail_command)]) == fail_command:
                class Result:
                    returncode = 1
                    stdout = ""
                    stderr = "failed"

                return Result()
            if command[:4] == ["py", "-3.12", "-m", "venv"] and create_venv:
                context.venv_python.parent.mkdir(parents=True, exist_ok=True)
                context.venv_python.write_text("", encoding="utf-8")
            class Result:
                returncode = 0
                stdout = "Python 3.12.9" if command[-1] == "-V" or command[1:] == ["-V"] else ""
                stderr = ""

            return Result()

        return calls, run

    def test_detects_supported_python_version(self) -> None:
        self.assertTrue(is_supported_python_version((3, 12, 5)))
        self.assertFalse(is_supported_python_version((3, 11, 9)))

    def test_run_setup_rejects_non_python_312_runtime(self) -> None:
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 11, 9), runner=lambda _command: None)
        self.assertEqual(caught.exception.code, "python_312_required")

    def test_creates_missing_venv_with_py312_command(self) -> None:
        calls, runner = self._runner()
        message = run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(message, "初始化完成，请双击 launch_web_workbench.cmd 启动网页工作台。")
        create_call = next(command for command in calls if command[:4] == ["py", "-3.12", "-m", "venv"])
        self.assertEqual(Path(create_call[4]), (self.root / ".venv").resolve())
        self.assertFalse((self.root / "bootstrap.json").exists())
        self.assertFalse((self.root / "data" / "boss_local_tool.db").exists())

    def test_existing_venv_is_reused_without_recreation(self) -> None:
        context = build_context(self.root)
        context.venv_python.parent.mkdir(parents=True, exist_ok=True)
        context.venv_python.write_text("", encoding="utf-8")
        calls, runner = self._runner(create_venv=False)
        run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertFalse(any(command[:4] == ["py", "-3.12", "-m", "venv"] for command in calls))

    def test_dependency_install_failure_returns_stable_error(self) -> None:
        calls, runner = self._runner(
            fail_command=(str((self.root / ".venv" / "Scripts" / "python.exe").resolve()), "-m", "pip")
        )
        with self.assertRaises(SetupFailure) as caught:
            run_setup(self.root, version_info=(3, 12, 0), runner=runner)
        self.assertEqual(caught.exception.code, "dependency_install_failed")
        self.assertIn("依赖安装失败", str(caught.exception))
        self.assertTrue(calls)

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

    def test_readme_and_guides_do_not_keep_outdated_web_phase_language(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        readme = (repo / "README.md").read_text(encoding="utf-8")
        self.assertTrue((repo / "docs" / "guides" / "web-workbench-quick-start.md").is_file())
        self.assertTrue((repo / "docs" / "guides" / "backup-and-recovery.md").is_file())
        self.assertTrue((repo / "docs" / "releases" / "current-preview.md").is_file())
        self.assertIn("launch_web_workbench.cmd", readme)
        self.assertIn("setup_web_workbench.cmd", readme)
        self.assertNotIn("网页只是 Phase 1 壳层", readme)
        self.assertNotIn("插件必须连接 17863 桌面端", readme)
        self.assertNotIn("网页端没有候选人和批次业务页面", readme)


if __name__ == "__main__":
    unittest.main()
