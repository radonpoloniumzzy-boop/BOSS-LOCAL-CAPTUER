from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import main as desktop_main, resolve_desktop_data_dir
from core.bootstrap import BootstrapConfigurationError, BootstrapSettings, BootstrapStore
from core.config import ConfigService


class DesktopWebTransitionTest(unittest.TestCase):
    def test_desktop_uses_bootstrap_data_directory_after_web_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            chosen = root / "shared-data"
            store = BootstrapStore(root / "local" / "bootstrap.json")
            store.save(BootstrapSettings(data_dir=str(chosen.resolve())))

            resolved = resolve_desktop_data_dir(project, store)
            config = ConfigService(app_root=project, data_dir=resolved)

            self.assertEqual(resolved, chosen.resolve())
            self.assertEqual(config.database_path, chosen.resolve() / "boss_local_tool.db")
            self.assertEqual(config.config_path, chosen.resolve() / "config.json")

    def test_desktop_keeps_legacy_project_data_before_web_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = BootstrapStore(root / "local" / "bootstrap.json")

            self.assertEqual(resolve_desktop_data_dir(project, store), project / "data")

    def test_desktop_does_not_fall_back_when_bootstrap_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = BootstrapStore(root / "local" / "bootstrap.json")
            store.path.parent.mkdir(parents=True)
            store.path.write_text("{broken", encoding="utf-8")

            with self.assertRaises(BootstrapConfigurationError):
                resolve_desktop_data_dir(project, store)

    def test_desktop_entrypoint_shows_bootstrap_recovery_message(self) -> None:
        error = BootstrapConfigurationError("配置文件：C:\\broken\\bootstrap.json")
        with (
            unittest.mock.patch("app.QApplication"),
            unittest.mock.patch("app.apply_application_theme"),
            unittest.mock.patch("app.resolve_desktop_data_dir", side_effect=error),
            unittest.mock.patch("app.QMessageBox.critical") as critical,
        ):
            self.assertEqual(desktop_main(), 1)

        self.assertIn("bootstrap.json", critical.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
