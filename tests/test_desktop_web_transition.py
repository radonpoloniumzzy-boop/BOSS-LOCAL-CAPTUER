from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import resolve_desktop_data_dir
from core.bootstrap import BootstrapSettings, BootstrapStore
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


if __name__ == "__main__":
    unittest.main()
