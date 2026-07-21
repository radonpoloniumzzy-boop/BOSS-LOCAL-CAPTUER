from __future__ import annotations

import threading
import json
import unittest
from types import SimpleNamespace

from core.models import AutomationFlowConfig
from ui.main_window import MainWindow


class _ProviderPage:
    def provider_payload(self) -> dict[str, object]:
        return {"provider": "openai", "api_key": ""}

    def set_status(self, _message: str) -> None:
        pass

    def update_pipeline_status(self, _payload: dict[str, object]) -> None:
        pass


class _Repository:
    def __init__(self) -> None:
        self.limit = None

    def list_screening_candidates(self, *, batch_id: int, limit: int):
        self.limit = limit
        return [{"id": 1, "batch_id": batch_id}]


class _TextInput:
    def __init__(self) -> None:
        self.value = ""

    def setText(self, value: str) -> None:
        self.value = value


class _StatusBar:
    def showMessage(self, _message: str) -> None:
        pass


class AutomationLaunchSnapshotTest(unittest.TestCase):
    def test_resuming_automation_run_preserves_origin_and_concurrency_snapshot(self) -> None:
        launched = []
        run = {
            "id": 31,
            "profile_id": 7,
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "source_job_title": "Role A",
            "batch_id": 12,
            "origin": "automation",
            "automation_snapshot_json": json.dumps({"screening_concurrency": 6}),
        }
        target = SimpleNamespace(
            _ai_screening_thread=None,
            repository=SimpleNamespace(
                get_screening_run=lambda _run_id: run,
                get_screening_profile=lambda _profile_id: {"id": 7, "job_title": "Role A"},
                list_screening_run_candidates=lambda _run_id: [{"id": 1}],
                recover_interrupted_screening_tasks=lambda: 0,
                get_screening_task_counts=lambda _run_id: {
                    "pending": 1,
                    "running": 0,
                    "retrying": 0,
                    "failed": 0,
                },
            ),
            ai_page=SimpleNamespace(
                provider_payload=lambda: {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "api_base": "https://api.deepseek.com",
                    "api_key": "",
                    "api_key_env": "DEEPSEEK_API_KEY",
                },
                set_status=lambda _message: None,
            ),
            _launch_ai_screening=lambda payload, origin: launched.append((payload, origin)),
        )

        MainWindow._resume_ai_screening_run(target, 31)

        self.assertEqual(launched[0][1], "automation")
        self.assertEqual(launched[0][0]["origin"], "automation")
        self.assertEqual(launched[0][0]["screening_concurrency"], 6)
        self.assertEqual(
            launched[0][0]["automation_snapshot"]["screening_concurrency"],
            6,
        )

    def test_launch_snapshot_is_detached_from_later_config_and_profile_edits(self) -> None:
        flow = AutomationFlowConfig(
            enabled=True,
            profile_id=7,
            job_title="Role A",
            source_url="https://www.zhipin.com/web/geek/recommend",
            max_candidates=10,
            provider="openai",
            model="model-a",
            post_screen_action="screen_and_favorite",
            screening_concurrency=6,
            favorite_interval_seconds=5,
            favorite_max_candidates=20,
        )
        profile = {"id": 7, "version": 3, "favorite_eligible_ratings": ["SSR"]}
        snapshot = MainWindow._build_automation_launch_snapshot(flow, profile)

        flow.model = "model-b"
        profile["favorite_eligible_ratings"].append("R")

        self.assertEqual(snapshot["flow"]["model"], "model-a")
        self.assertEqual(snapshot["flow"]["screening_concurrency"], 6)
        self.assertEqual(snapshot["profile"]["favorite_eligible_ratings"], ["SSR"])

    def test_unarmed_import_cannot_enter_automation_screening_queue(self) -> None:
        started = []
        target = SimpleNamespace(
            _automation_armed=False,
            _armed_automation_snapshot={"flow": {}, "profile": {}},
            _start_automation_screening=started.append,
        )

        MainWindow._queue_automation_screening(
            target,
            {"batch_id": 1, "total_batch_items": 1},
        )

        self.assertEqual(started, [])

    def test_duplicate_collection_cannot_enter_automation_screening_queue(self) -> None:
        started = []
        statuses = []
        target = SimpleNamespace(
            _automation_armed=True,
            _armed_automation_snapshot={"flow": {}, "profile": {}},
            _start_automation_screening=started.append,
            automation_flow_page=SimpleNamespace(set_status=statuses.append),
        )

        MainWindow._queue_automation_screening(
            target,
            {
                "batch_id": 12,
                "total_batch_items": 20,
                "automation_requested": True,
                "automation_allowed": False,
                "duplicate_content": True,
            },
        )

        self.assertEqual(started, [])
        self.assertIn("完全相同", statuses[-1])

    def test_screening_does_not_start_when_imported_count_differs_from_batch(self) -> None:
        launched = []
        statuses = []
        target = SimpleNamespace(
            repository=SimpleNamespace(count_batch_items=lambda _batch_id: 19),
            automation_flow_page=SimpleNamespace(set_status=statuses.append),
            _launch_ai_screening=lambda payload, origin: launched.append((payload, origin)),
        )

        MainWindow._start_automation_screening(
            target,
            {
                "batch_id": 12,
                "expected_total_items": 20,
                "launch_snapshot": {
                    "profile": {"id": 7},
                    "flow": {"post_screen_action": "screen_only"},
                },
            },
        )

        self.assertEqual(launched, [])
        self.assertIn("20", statuses[-1])
        self.assertIn("19", statuses[-1])

    def test_screening_does_not_start_when_batch_has_fewer_screenable_candidates(self) -> None:
        launched = []
        statuses = []
        target = SimpleNamespace(
            repository=SimpleNamespace(
                count_batch_items=lambda _batch_id: 20,
                list_screening_candidates=lambda **_kwargs: [{"id": value} for value in range(19)],
            ),
            automation_flow_page=SimpleNamespace(set_status=statuses.append),
            _launch_ai_screening=lambda payload, origin: launched.append((payload, origin)),
        )

        MainWindow._start_automation_screening(
            target,
            {
                "batch_id": 12,
                "expected_total_items": 20,
                "launch_snapshot": {
                    "profile": {"id": 7},
                    "flow": {"post_screen_action": "screen_only", "max_candidates": 10},
                },
            },
        )

        self.assertEqual(launched, [])
        self.assertIn("可筛选", statuses[-1])

    def test_desktop_arm_entry_persists_the_locked_launch_snapshot(self) -> None:
        flow = AutomationFlowConfig(
            enabled=True,
            profile_id=7,
            job_title="Role A",
            source_url="https://www.zhipin.com/web/geek/recommend",
            provider="openai",
            model="model-a",
            post_screen_action="screen_and_favorite",
        )
        saved = []
        waiting = []
        target = SimpleNamespace(
            _save_automation_flow=lambda _payload: True,
            config=SimpleNamespace(automation_flow=flow),
            repository=SimpleNamespace(
                get_screening_profile=lambda _profile_id: {
                    "id": 7,
                    "version": 3,
                    "favorite_eligible_ratings": ["SSR"],
                }
            ),
            _build_automation_launch_snapshot=MainWindow._build_automation_launch_snapshot,
            config_service=SimpleNamespace(save=saved.append),
            automation_flow_page=SimpleNamespace(set_waiting=waiting.append),
            dashboard_page=SimpleNamespace(
                job_title_input=_TextInput(),
                source_url_input=_TextInput(),
            ),
            statusBar=lambda: _StatusBar(),
        )

        MainWindow._arm_automation_flow(target, {})

        self.assertTrue(target._automation_armed)
        self.assertEqual(
            target.config.automation_flow.armed_launch_snapshot["profile"]["version"],
            3,
        )
        self.assertEqual(waiting, [True])
        self.assertEqual(len(saved), 1)

    def test_saving_disabled_clears_the_persisted_and_in_memory_arm(self) -> None:
        old_snapshot = {"flow": {"model": "model-a"}, "profile": {"id": 7}}
        flow = AutomationFlowConfig(
            enabled=True,
            profile_id=7,
            armed_launch_snapshot=old_snapshot,
        )
        target = SimpleNamespace(
            repository=SimpleNamespace(
                get_screening_profile=lambda _profile_id: {
                    "id": 7,
                    "favorite_eligible_ratings": ["SSR"],
                }
            ),
            automation_flow_page=SimpleNamespace(set_status=lambda _message: None),
            config=SimpleNamespace(automation_flow=flow),
            config_service=SimpleNamespace(save=lambda _config: None),
            statusBar=lambda: _StatusBar(),
            _automation_armed=True,
            _armed_automation_snapshot=old_snapshot,
        )

        saved = MainWindow._save_automation_flow(
            target,
            {
                "enabled": False,
                "profile_id": 7,
                "provider": {"provider": "openai", "model": "model-a"},
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "post_screen_action": "screen_only",
            },
        )

        self.assertTrue(saved)
        self.assertFalse(target._automation_armed)
        self.assertIsNone(target._armed_automation_snapshot)
        self.assertEqual(target.config.automation_flow.armed_launch_snapshot, {})

    def test_extension_status_uses_the_armed_snapshot_not_later_edits(self) -> None:
        current_flow = AutomationFlowConfig(
            enabled=True,
            profile_id=7,
            model="new-model",
            post_screen_action="screen_only",
        )
        target = SimpleNamespace(
            _automation_config_lock=threading.RLock(),
            _automation_armed=True,
            _armed_automation_snapshot={
                "flow": {
                    "profile_id": 7,
                    "job_title": "Locked Role",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "max_candidates": 0,
                    "provider": "openai",
                    "model": "locked-model",
                    "post_screen_action": "screen_and_favorite",
                    "screening_concurrency": 6,
                    "favorite_interval_seconds": 5,
                    "favorite_max_candidates": 20,
                },
                "profile": {
                    "id": 7,
                    "version": 3,
                    "job_title": "Locked Role",
                    "favorite_eligible_ratings": ["SSR"],
                },
            },
            config_service=SimpleNamespace(load=lambda: SimpleNamespace(automation_flow=current_flow)),
            repository=SimpleNamespace(
                get_screening_profile=lambda _profile_id: {
                    "id": 7,
                    "version": 4,
                    "job_title": "Changed Role",
                    "favorite_eligible_ratings": ["R"],
                }
            ),
        )

        status = MainWindow._automation_status_payload(target)

        self.assertEqual(status["model"], "locked-model")
        self.assertEqual(status["profile_version"], 3)
        self.assertEqual(status["favorite_eligible_ratings"], ["SSR"])
        self.assertEqual(status["post_screen_action"], "screen_and_favorite")
        self.assertEqual(status["screening_concurrency"], 6)

    def test_favorite_mode_screens_the_complete_capture_batch_from_locked_snapshot(self) -> None:
        repository = _Repository()
        launched = []
        target = SimpleNamespace(
            repository=repository,
            automation_flow_page=_ProviderPage(),
            ai_page=_ProviderPage(),
            _launch_ai_screening=lambda payload, origin: launched.append((payload, origin)),
        )
        launch_snapshot = {
            "profile": {
                "id": 7,
                "version": 3,
                "job_title": "Role A",
                "favorite_eligible_ratings": ["SSR"],
            },
            "flow": {
                "profile_id": 7,
                "job_title": "Role A",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "max_candidates": 10,
                "provider": "openai",
                "model": "model-a",
                "api_base": "",
                "api_key_env": "OPENAI_API_KEY",
                "post_screen_action": "screen_and_favorite",
                "screening_concurrency": 6,
                "favorite_interval_seconds": 5,
                "favorite_max_candidates": 20,
            },
        }

        MainWindow._start_automation_screening(
            target,
            {
                "batch_id": 12,
                "job_title": "Role A",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "source_page_context": {"platform": "boss", "tab_id": 91},
                "launch_snapshot": launch_snapshot,
            },
        )

        self.assertEqual(repository.limit, 0)
        self.assertEqual(launched[0][0]["limit"], 0)
        self.assertEqual(launched[0][0]["profile"]["version"], 3)
        self.assertEqual(launched[0][0]["screening_concurrency"], 6)
        self.assertEqual(
            launched[0][0]["automation_snapshot"]["screening_profile_snapshot"]["version"],
            3,
        )
        self.assertEqual(launched[0][1], "automation")


if __name__ == "__main__":
    unittest.main()
