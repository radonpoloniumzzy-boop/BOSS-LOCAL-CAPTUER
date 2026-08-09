from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.app_lock import ApplicationLockError, DatabaseApplicationLock
from core.bootstrap import (
    BootstrapConfigurationError,
    BootstrapService,
    BootstrapSettings,
    BootstrapStore,
    DataDirectoryError,
)
from storage.db import DatabaseManager
from web.backend.app import create_web_app
from web.backend.launcher import PortUnavailableError, ensure_port_available, uvicorn_options
from web_app import main as web_main


class BootstrapServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.bootstrap_path = self.root / "local" / "bootstrap.json"
        self.store = BootstrapStore(self.bootstrap_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def service(self, *, d_drive: Path | None = None) -> BootstrapService:
        return BootstrapService(
            project_root=self.project,
            store=self.store,
            d_drive=d_drive or self.root / "missing-d-drive",
            documents_dir=self.root / "Documents",
        )

    def test_missing_bootstrap_is_the_only_unconfigured_state(self) -> None:
        self.assertIsNone(self.store.load())

    def test_corrupt_bootstrap_is_reported_and_never_overwritten(self) -> None:
        self.bootstrap_path.parent.mkdir(parents=True)
        original = "{broken json"
        self.bootstrap_path.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(BootstrapConfigurationError, "bootstrap.json"):
            self.store.load()

        self.assertEqual(self.bootstrap_path.read_text(encoding="utf-8"), original)

    def test_unreadable_bootstrap_is_reported(self) -> None:
        self.bootstrap_path.parent.mkdir(parents=True)
        self.bootstrap_path.write_text("{}", encoding="utf-8")

        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(BootstrapConfigurationError, "无法读取"):
                self.store.load()

    def test_bootstrap_requires_all_safety_fields(self) -> None:
        valid = {
            "data_dir": str((self.root / "data").resolve()),
            "web_port": 17864,
            "setup_completed": True,
        }
        invalid_payloads = [
            {key: value for key, value in valid.items() if key != "data_dir"},
            {key: value for key, value in valid.items() if key != "web_port"},
            {key: value for key, value in valid.items() if key != "setup_completed"},
            {**valid, "setup_completed": False},
            {**valid, "web_port": 1023},
            {**valid, "web_port": 65536},
            {**valid, "web_port": "17864"},
            {**valid, "data_dir": "relative/data"},
            {**valid, "data_dir": ""},
        ]
        self.bootstrap_path.parent.mkdir(parents=True)

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.bootstrap_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(BootstrapConfigurationError):
                    self.store.load()

    def test_status_prefers_existing_project_database_without_reading_secrets(self) -> None:
        data_dir = self.project / "data"
        data_dir.mkdir()
        (data_dir / "boss_local_tool.db").write_bytes(b"existing-database")
        (data_dir / "config.json").write_text('{"local_api_token":"secret"}', encoding="utf-8")

        status = self.service().status()

        self.assertTrue(status["setup_required"])
        self.assertEqual(status["suggested_data_dir"], str(data_dir.resolve()))
        self.assertTrue(status["existing_database_detected"])
        self.assertNotIn("secret", json.dumps(status))

    def test_status_falls_back_to_documents_when_d_drive_is_missing(self) -> None:
        status = self.service().status()

        self.assertEqual(
            status["suggested_data_dir"],
            str((self.root / "Documents" / "RecruitingTalentWorkbench").resolve()),
        )

    def test_rejects_root_system_source_and_unrecognized_nonempty_directories(self) -> None:
        service = self.service()
        invalid_nonempty = self.root / "unknown"
        invalid_nonempty.mkdir()
        (invalid_nonempty / "notes.txt").write_text("not app data", encoding="utf-8")

        rejected = [Path(Path.cwd().anchor), self.project, invalid_nonempty]
        system_root = Path(os.environ.get("SystemRoot", "C:/Windows"))
        rejected.append(system_root)
        for path in rejected:
            with self.subTest(path=path):
                with self.assertRaises(DataDirectoryError):
                    service.validate_data_dir(path)

    def test_rejects_an_unwritable_directory(self) -> None:
        data_dir = self.root / "unwritable"
        data_dir.mkdir()
        with patch("core.bootstrap.os.access", return_value=False):
            with self.assertRaisesRegex(DataDirectoryError, "不可写"):
                self.service().validate_data_dir(data_dir)

    def test_rejects_empty_project_data_and_an_incompatible_database(self) -> None:
        empty_project_data = self.project / "data"
        empty_project_data.mkdir()
        incompatible = self.root / "incompatible"
        incompatible.mkdir()
        sqlite3.connect(incompatible / "boss_local_tool.db").close()

        with self.assertRaises(DataDirectoryError):
            self.service().validate_data_dir(empty_project_data)
        with self.assertRaisesRegex(DataDirectoryError, "结构"):
            self.service().validate_data_dir(incompatible)

        incomplete = self.root / "incomplete"
        incomplete.mkdir()
        connection = sqlite3.connect(incomplete / "boss_local_tool.db")
        connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_version(version) VALUES (16)")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(DataDirectoryError, "结构"):
            self.service().validate_data_dir(incomplete)

    def test_setup_reuses_existing_database_and_never_overwrites_config(self) -> None:
        data_dir = self.root / "existing-data"
        data_dir.mkdir()
        database = DatabaseManager(data_dir / "boss_local_tool.db")
        database.initialize()
        connection = sqlite3.connect(data_dir / "boss_local_tool.db")
        connection.execute("CREATE TABLE existing_marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO existing_marker(value) VALUES ('preserved')")
        connection.commit()
        connection.close()
        config = data_dir / "config.json"
        config.write_text('{"keep":"this"}', encoding="utf-8")

        result = self.service().setup(data_dir)

        self.assertTrue(result["setup_completed"])
        self.assertEqual(config.read_text(encoding="utf-8"), '{"keep":"this"}')
        connection = sqlite3.connect(data_dir / "boss_local_tool.db")
        marker = connection.execute("SELECT value FROM existing_marker").fetchone()[0]
        connection.close()
        self.assertEqual(marker, "preserved")
        with self.assertRaises(DataDirectoryError):
            self.service().setup(self.root / "another")


class DatabaseApplicationLockTest(unittest.TestCase):
    def test_windows_diagnostic_write_failure_releases_mutex_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "data" / "boss_local_tool.db"
            lock_root = root / "locks"
            first = DatabaseApplicationLock(db_path, lock_root=lock_root)

            def fake_acquire(lock):
                from core.app_lock import _HELD_IDENTITIES, _HELD_IDENTITIES_LOCK

                lock._mutex_handle = 41
                with _HELD_IDENTITIES_LOCK:
                    _HELD_IDENTITIES.add(lock.identity)

            with (
                patch("core.app_lock.os.name", "nt"),
                patch.object(DatabaseApplicationLock, "_acquire_windows_mutex", fake_acquire),
                patch.object(DatabaseApplicationLock, "_close_windows_handle") as close_handle,
                patch.object(Path, "write_text", side_effect=OSError("disk denied")),
            ):
                with self.assertRaisesRegex(ApplicationLockError, "诊断文件"):
                    first.acquire()
                close_handle.assert_called_once_with(41)

            recovered = DatabaseApplicationLock(db_path, lock_root=lock_root)
            recovered.acquire()
            recovered.release()
    def test_lock_is_cross_process_and_recovers_after_process_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "data" / "boss_local_tool.db"
            lock_root = root / "locks"
            helper = Path(__file__).parent / "helpers" / "app_lock_holder.py"
            process = subprocess.Popen(
                [sys.executable, str(helper), str(db_path), str(lock_root)],
                cwd=Path(__file__).parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(process.stdout.readline().strip(), "locked")
                with self.assertRaises(ApplicationLockError) as caught:
                    DatabaseApplicationLock(db_path, lock_root=lock_root).acquire()
                self.assertIn(str(db_path.resolve()), str(caught.exception))
            finally:
                process.kill()
                process.wait(timeout=5)

            recovered = DatabaseApplicationLock(db_path, lock_root=lock_root)
            recovered.acquire()
            recovered.release()


class DatabaseBackupTest(unittest.TestCase):
    def test_current_schema_does_not_create_repeated_upgrade_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "boss_local_tool.db"
            database = DatabaseManager(db_path)
            database.initialize()
            database.initialize()

            self.assertEqual(list(Path(temp).glob("*.bak")), [])

    def test_backup_failure_stops_upgrade_and_preserves_original_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "boss_local_tool.db"
            connection = sqlite3.connect(db_path)
            connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY)")
            connection.execute("INSERT INTO schema_version(version) VALUES (14)")
            connection.commit()
            connection.close()
            real_connect = sqlite3.connect

            def fail_backup(path, *args, **kwargs):
                if ".bak.tmp-" in str(path):
                    raise OSError("backup disk unavailable")
                return real_connect(path, *args, **kwargs)

            with patch("storage.db.sqlite3.connect", side_effect=fail_backup):
                with self.assertRaisesRegex(RuntimeError, "备份"):
                    DatabaseManager(db_path).initialize()

            check = sqlite3.connect(db_path)
            version = check.execute("SELECT version FROM schema_version").fetchone()[0]
            check.close()
            self.assertEqual(version, 14)

    def test_copy_failure_after_target_open_leaves_no_backup_or_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "boss_local_tool.db"
            connection = sqlite3.connect(db_path)
            connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY)")
            connection.execute("INSERT INTO schema_version(version) VALUES (14)")
            connection.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
            connection.execute("INSERT INTO sentinel(value) VALUES ('preserved')")
            connection.commit()
            connection.close()

            real_connect = sqlite3.connect

            class FailingSource:
                def __init__(self, wrapped):
                    self.wrapped = wrapped

                def __getattr__(self, name):
                    return getattr(self.wrapped, name)

                def backup(self, target):
                    target.execute("CREATE TABLE partial(value TEXT)")
                    target.commit()
                    raise OSError("copy interrupted")

            calls = 0

            def connect(path, *args, **kwargs):
                nonlocal calls
                result = real_connect(path, *args, **kwargs)
                calls += 1
                return FailingSource(result) if calls == 1 else result

            with patch("storage.db.sqlite3.connect", side_effect=connect):
                with self.assertRaisesRegex(RuntimeError, "copy interrupted"):
                    DatabaseManager(db_path).initialize()

            self.assertEqual(list(root.glob("*.bak")), [])
            self.assertEqual(list(root.glob("*.tmp-*")), [])
            check = sqlite3.connect(db_path)
            try:
                self.assertEqual(check.execute("SELECT version FROM schema_version").fetchone()[0], 14)
                self.assertEqual(check.execute("SELECT value FROM sentinel").fetchone()[0], "preserved")
            finally:
                check.close()

    def test_schema_inspection_failure_always_closes_the_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "boss_local_tool.db"
            with patch.object(DatabaseManager, "_schema_version", side_effect=RuntimeError("broken")):
                with self.assertRaisesRegex(RuntimeError, "broken"):
                    DatabaseManager(db_path).initialize()

            db_path.unlink()
            self.assertFalse(db_path.exists())


class WebApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = BootstrapStore(self.root / "local" / "bootstrap.json")
        self.service = BootstrapService(
            project_root=self.project,
            store=self.store,
            d_drive=self.root / "missing-d-drive",
            documents_dir=self.root / "Documents",
        )
        self.app = create_web_app(self.service, lock_root=self.root / "locks")
        self.client = TestClient(self.app, base_url="http://127.0.0.1:17864")
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_health_and_setup_status_are_available_before_database(self) -> None:
        health = self.client.get("/api/health").json()
        setup = self.client.get("/api/setup/status").json()

        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["service"], "recruiting-talent-workbench")
        self.assertNotIn("token", json.dumps(health).lower())
        self.assertTrue(setup["setup_required"])
        wrong_port = self.client.get("/api/health", headers={"Host": "127.0.0.1:9999"})
        self.assertEqual(wrong_port.status_code, 400)

    def test_setup_requires_same_origin_and_status_reuses_repository_statistics(self) -> None:
        data_dir = self.root / "chosen-data"
        blocked = self.client.post("/api/setup", json={"data_dir": str(data_dir)})
        self.assertEqual(blocked.status_code, 403)

        response = self.client.post(
            "/api/setup",
            json={"data_dir": str(data_dir)},
            headers={"Origin": "http://127.0.0.1:17864"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        database = sqlite3.connect(data_dir / "boss_local_tool.db")
        database.execute(
            "INSERT INTO capture_batches(job_title, source_url, start_time, status, created_at, updated_at) "
            "VALUES ('交易员', 'https://example.test', '2026-08-09T10:00:00', 'completed', "
            "'2026-08-09T10:00:00', '2026-08-09T10:00:00')"
        )
        database.commit()
        database.close()

        status = self.client.get("/api/app/status").json()

        self.assertTrue(status["database_ready"])
        self.assertEqual(status["batch_count"], 1)
        self.assertEqual(status["latest_batch_id"], 1)
        self.assertEqual(status["latest_batch_status"], "completed")
        repeated = self.client.post(
            "/api/setup",
            json={"data_dir": str(self.root / "other")},
            headers={"Origin": "http://127.0.0.1:17864"},
        )
        self.assertEqual(repeated.status_code, 409)

    def test_errors_have_stable_json_shape(self) -> None:
        response = self.client.get("/api/app/status")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(set(response.json()), {"error"})
        self.assertEqual(set(response.json()["error"]), {"code", "message"})
        self.assertEqual(response.json()["error"]["code"], "database_not_ready")

    def test_existing_project_database_is_locked_before_setup_page_starts(self) -> None:
        data_dir = self.project / "data"
        DatabaseManager(data_dir / "boss_local_tool.db").initialize()
        first_app = create_web_app(self.service, lock_root=self.root / "early-locks")
        try:
            with self.assertRaises(ApplicationLockError):
                create_web_app(self.service, lock_root=self.root / "early-locks")
        finally:
            first_app.state.runtime.close()

    def test_health_starts_even_when_a_configured_database_cannot_initialize(self) -> None:
        broken_data = self.root / "broken-data"
        broken_data.mkdir()
        (broken_data / "boss_local_tool.db").write_text("not sqlite", encoding="utf-8")
        self.store.save(BootstrapSettings(data_dir=str(broken_data)))
        database_before = (broken_data / "boss_local_tool.db").read_bytes()
        bootstrap_before = self.store.path.read_bytes()

        app = create_web_app(self.service, lock_root=self.root / "broken-locks")
        with TestClient(app, base_url="http://127.0.0.1:17864") as client:
            self.assertEqual(client.get("/api/health").status_code, 200)
            response = client.get("/api/app/status")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "database_corrupt")
        self.assertEqual((broken_data / "boss_local_tool.db").read_bytes(), database_before)
        self.assertEqual(self.store.path.read_bytes(), bootstrap_before)

    def test_configured_missing_database_never_creates_an_empty_file(self) -> None:
        data_dir = self.root / "missing-database"
        data_dir.mkdir()
        self.store.save(BootstrapSettings(data_dir=str(data_dir.resolve())))
        bootstrap_before = self.store.path.read_bytes()

        app = create_web_app(self.service, lock_root=self.root / "missing-locks")
        try:
            with TestClient(app, base_url="http://127.0.0.1:17864") as client:
                self.assertEqual(client.get("/api/health").status_code, 200)
                response = client.get("/api/app/status")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json()["error"]["code"], "configured_database_missing"
                )
                self.assertIn("从备份恢复", response.json()["error"]["message"])
        finally:
            app.state.runtime.close()

        self.assertFalse((data_dir / "boss_local_tool.db").exists())
        self.assertEqual(self.store.path.read_bytes(), bootstrap_before)

    def test_newer_database_schema_is_not_modified(self) -> None:
        data_dir = self.root / "newer-schema"
        db_path = data_dir / "boss_local_tool.db"
        DatabaseManager(db_path).initialize()
        connection = sqlite3.connect(db_path)
        connection.execute("UPDATE schema_version SET version = 999")
        connection.commit()
        connection.close()
        self.store.save(BootstrapSettings(data_dir=str(data_dir.resolve())))
        database_before = db_path.read_bytes()
        bootstrap_before = self.store.path.read_bytes()

        app = create_web_app(self.service, lock_root=self.root / "newer-locks")
        try:
            with TestClient(app, base_url="http://127.0.0.1:17864") as client:
                response = client.get("/api/app/status")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "unsupported_schema")
        finally:
            app.state.runtime.close()

        self.assertEqual(db_path.read_bytes(), database_before)
        self.assertEqual(self.store.path.read_bytes(), bootstrap_before)

    def test_upgrade_failure_has_a_safe_stable_error(self) -> None:
        data_dir = self.root / "upgrade-failure"
        db_path = data_dir / "boss_local_tool.db"
        data_dir.mkdir()
        connection = sqlite3.connect(db_path)
        connection.execute("CREATE TABLE schema_version(version INTEGER NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO schema_version(version) VALUES (14)")
        connection.commit()
        connection.close()
        self.store.save(BootstrapSettings(data_dir=str(data_dir.resolve())))
        bootstrap_before = self.store.path.read_bytes()

        with patch.object(
            DatabaseManager,
            "_create_upgrade_backup",
            side_effect=RuntimeError("secret raw failure"),
        ):
            app = create_web_app(self.service, lock_root=self.root / "upgrade-locks")
        try:
            with TestClient(app, base_url="http://127.0.0.1:17864") as client:
                response = client.get("/api/app/status")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "database_upgrade_failed")
                self.assertNotIn("secret raw failure", response.text)
        finally:
            app.state.runtime.close()
        check = sqlite3.connect(db_path)
        try:
            self.assertEqual(check.execute("SELECT version FROM schema_version").fetchone()[0], 14)
        finally:
            check.close()
        self.assertEqual(self.store.path.read_bytes(), bootstrap_before)
        self.assertIn(
            "secret raw failure",
            (self.store.path.parent / "logs" / "web-runtime.log").read_text(encoding="utf-8"),
        )

    def test_configured_database_in_use_keeps_health_available(self) -> None:
        data_dir = self.root / "locked-data"
        db_path = data_dir / "boss_local_tool.db"
        DatabaseManager(db_path).initialize()
        self.store.save(BootstrapSettings(data_dir=str(data_dir.resolve())))
        held = DatabaseApplicationLock(db_path, lock_root=self.root / "configured-locks")
        held.acquire()
        try:
            app = create_web_app(self.service, lock_root=self.root / "configured-locks")
            try:
                with TestClient(app, base_url="http://127.0.0.1:17864") as client:
                    self.assertEqual(client.get("/api/health").status_code, 200)
                    response = client.get("/api/app/status")
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()["error"]["code"], "database_in_use")
            finally:
                app.state.runtime.close()
        finally:
            held.release()

    def test_concurrent_setup_is_serialized_and_keeps_the_winning_lock(self) -> None:
        class SlowBootstrapService(BootstrapService):
            active = 0
            max_active = 0
            counter_lock = threading.Lock()

            def setup(self, data_dir):
                with self.counter_lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                try:
                    time.sleep(0.1)
                    return super().setup(data_dir)
                finally:
                    with self.counter_lock:
                        self.active -= 1

        store = BootstrapStore(self.root / "concurrent" / "bootstrap.json")
        service = SlowBootstrapService(
            project_root=self.project,
            store=store,
            d_drive=self.root / "missing-d-drive",
            documents_dir=self.root / "Documents",
        )
        app = create_web_app(service, lock_root=self.root / "concurrent-locks")
        selected = self.root / "concurrent-data"

        def attempt_setup():
            try:
                app.state.runtime.setup(str(selected))
                return "success"
            except DataDirectoryError:
                return "rejected"

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _value: attempt_setup(), range(2)))
            self.assertEqual(sorted(outcomes), ["rejected", "success"])
            self.assertEqual(service.max_active, 1)
            self.assertIsNotNone(app.state.runtime.repository)
            with self.assertRaises(ApplicationLockError):
                DatabaseApplicationLock(
                    selected / "boss_local_tool.db",
                    lock_root=self.root / "concurrent-locks",
                ).acquire()
        finally:
            app.state.runtime.close()


class WebLauncherTest(unittest.TestCase):
    def test_entrypoint_reports_bootstrap_recovery_message(self) -> None:
        error = BootstrapConfigurationError("配置文件：C:\\broken\\bootstrap.json")
        with (
            patch("web_app.run_web_app", side_effect=error),
            patch("builtins.print") as output,
        ):
            self.assertEqual(web_main(), 1)

        self.assertIn("bootstrap.json", output.call_args.args[0])

    def test_uvicorn_is_loopback_only_and_port_conflict_is_clear(self) -> None:
        options = uvicorn_options(17864)
        self.assertEqual(options["host"], "127.0.0.1")
        self.assertEqual(options["port"], 17864)

        occupied = socket.socket()
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        try:
            with self.assertRaisesRegex(PortUnavailableError, "端口"):
                ensure_port_available(port)
        finally:
            occupied.close()


if __name__ == "__main__":
    unittest.main()
