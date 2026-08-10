from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import (
    main as desktop_main,
    resolve_desktop_data_dir,
    resolve_desktop_startup,
)
from core.bootstrap import BootstrapConfigurationError, BootstrapSettings, BootstrapStore
from core.config import ConfigService
from storage.db import DatabaseManager, DatabaseMissingError
from ui.main_window import initialize_database_for_startup


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

            startup = resolve_desktop_startup(project, store)
            self.assertEqual(startup.data_dir, chosen.resolve())
            self.assertTrue(startup.require_existing_database)

    def test_configured_mode_uses_existing_only_database_initialization(self) -> None:
        database = DatabaseManager(Path("configured.db"))
        with (
            patch.object(database, "initialize") as initialize,
            patch.object(database, "initialize_existing") as initialize_existing,
        ):
            initialize_database_for_startup(database, require_existing=True)

        initialize_existing.assert_called_once_with()
        initialize.assert_not_called()

    def test_configured_existing_database_opens_without_creating_legacy_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            chosen = root / "configured-data"
            database_path = chosen / "boss_local_tool.db"
            DatabaseManager(database_path).initialize()
            store = BootstrapStore(root / "local" / "bootstrap.json")
            store.save(BootstrapSettings(data_dir=str(chosen.resolve())))

            startup = resolve_desktop_startup(project, store)
            database = DatabaseManager(startup.data_dir / "boss_local_tool.db")
            initialize_database_for_startup(
                database,
                require_existing=startup.require_existing_database,
            )

            self.assertEqual(startup.data_dir, chosen.resolve())
            self.assertTrue(database_path.is_file())
            self.assertFalse((project / "data" / "boss_local_tool.db").exists())

    def test_existing_only_connection_strategy_survives_after_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "configured-data" / "boss_local_tool.db"
            moved = root / "moved-data" / "boss_local_tool.db"
            original.parent.mkdir(parents=True)
            moved.parent.mkdir(parents=True)
            DatabaseManager(original).initialize()

            configured = DatabaseManager(original)
            configured.initialize_existing()
            original.replace(moved)

            with self.assertRaises(DatabaseMissingError):
                configured.get_connection()

            self.assertFalse(original.exists())
            self.assertTrue(moved.exists())

    def test_desktop_keeps_legacy_project_data_before_web_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = BootstrapStore(root / "local" / "bootstrap.json")

            self.assertEqual(resolve_desktop_data_dir(project, store), project / "data")
            startup = resolve_desktop_startup(project, store)
            self.assertEqual(startup.data_dir, project / "data")
            self.assertFalse(startup.require_existing_database)

    def test_legacy_mode_keeps_database_initialization_compatibility(self) -> None:
        database = DatabaseManager(Path("legacy.db"))
        with (
            patch.object(database, "initialize") as initialize,
            patch.object(database, "initialize_existing") as initialize_existing,
        ):
            initialize_database_for_startup(database, require_existing=False)

        initialize.assert_called_once_with()
        initialize_existing.assert_not_called()

    def test_legacy_mode_can_create_the_project_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            store = BootstrapStore(root / "local" / "bootstrap.json")
            startup = resolve_desktop_startup(project, store)
            database_path = startup.data_dir / "boss_local_tool.db"

            initialize_database_for_startup(
                DatabaseManager(database_path),
                require_existing=startup.require_existing_database,
            )

            self.assertTrue(database_path.is_file())

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
            self.assertFalse((project / "data" / "boss_local_tool.db").exists())

    def test_missing_configured_database_stops_desktop_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            data_dir = root / "configured-data"
            data_dir.mkdir()
            store = BootstrapStore(root / "local" / "bootstrap.json")
            store.save(BootstrapSettings(data_dir=str(data_dir.resolve())))
            bootstrap_before = store.path.read_bytes()
            startup = resolve_desktop_startup(project, store)
            lock = SimpleNamespace(acquire=unittest.mock.Mock(), release=unittest.mock.Mock())

            def open_window(*, data_dir, require_existing_database):
                self.assertTrue(require_existing_database)
                database = DatabaseManager(data_dir / "boss_local_tool.db")
                initialize_database_for_startup(database, require_existing=True)
                self.fail("configured database initialization should have failed")

            with (
                patch("app.QApplication"),
                patch("app.apply_application_theme"),
                patch("app.resolve_desktop_startup", return_value=startup),
                patch("app.DatabaseApplicationLock", return_value=lock),
                patch("app.MainWindow", side_effect=open_window) as main_window,
                patch("app.QMessageBox.critical") as critical,
            ):
                self.assertEqual(desktop_main(), 1)

            main_window.assert_called_once()
            lock.acquire.assert_called_once_with()
            lock.release.assert_called_once_with()
            self.assertIn("不会自动创建空数据库", critical.call_args.args[2])
            self.assertIn("移动盘", critical.call_args.args[2])
            self.assertFalse((data_dir / "boss_local_tool.db").exists())
            self.assertEqual(store.path.read_bytes(), bootstrap_before)

    def test_permission_denied_configured_directory_shows_recovery_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            data_dir = root / "configured-data"
            data_dir.mkdir()
            store = BootstrapStore(root / "local" / "bootstrap.json")
            store.save(BootstrapSettings(data_dir=str(data_dir.resolve())))
            bootstrap_before = store.path.read_bytes()
            startup = resolve_desktop_startup(project, store)
            lock = SimpleNamespace(acquire=unittest.mock.Mock(), release=unittest.mock.Mock())

            with (
                patch("app.QApplication"),
                patch("app.apply_application_theme"),
                patch("app.resolve_desktop_startup", return_value=startup),
                patch("app.DatabaseApplicationLock", return_value=lock),
                patch("app.MainWindow", side_effect=PermissionError("denied")),
                patch("app.QMessageBox.critical") as critical,
            ):
                self.assertEqual(desktop_main(), 1)

            lock.acquire.assert_called_once_with()
            lock.release.assert_called_once_with()
            self.assertIn("目录权限", critical.call_args.args[2])
            self.assertIn("不会创建或切换到空人才库", critical.call_args.args[2])
            self.assertEqual(store.path.read_bytes(), bootstrap_before)

    def test_os_error_configured_directory_shows_recovery_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            project.mkdir()
            data_dir = root / "configured-data"
            data_dir.mkdir()
            store = BootstrapStore(root / "local" / "bootstrap.json")
            store.save(BootstrapSettings(data_dir=str(data_dir.resolve())))
            startup = resolve_desktop_startup(project, store)
            lock = SimpleNamespace(acquire=unittest.mock.Mock(), release=unittest.mock.Mock())

            with (
                patch("app.QApplication"),
                patch("app.apply_application_theme"),
                patch("app.resolve_desktop_startup", return_value=startup),
                patch("app.DatabaseApplicationLock", return_value=lock),
                patch("app.MainWindow", side_effect=OSError("drive unavailable")),
                patch("app.QMessageBox.critical") as critical,
            ):
                self.assertEqual(desktop_main(), 1)

            lock.release.assert_called_once_with()
            self.assertIn("D 盘", critical.call_args.args[2])
            self.assertIn("不会创建或切换到空人才库", critical.call_args.args[2])

    def test_desktop_entrypoint_shows_bootstrap_recovery_message(self) -> None:
        error = BootstrapConfigurationError("配置文件：C:\\broken\\bootstrap.json")
        with (
            unittest.mock.patch("app.QApplication"),
            unittest.mock.patch("app.apply_application_theme"),
            unittest.mock.patch("app.resolve_desktop_startup", side_effect=error),
            unittest.mock.patch("app.QMessageBox.critical") as critical,
        ):
            self.assertEqual(desktop_main(), 1)

        self.assertIn("bootstrap.json", critical.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
