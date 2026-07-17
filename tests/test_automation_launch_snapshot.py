from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.models import AutomationFlowConfig
from ui.main_window import MainWindow


class _ProviderPage:
    def provider_payload(self) -> dict[str, object]:
        return {"provider": "openai", "api_key": ""}

    def set_status(self, _message: str) -> None:
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
            favorite_interval_seconds=5,
            favorite_max_candidates=20,
        )
        profile = {"id": 7, "version": 3, "favorite_eligible_ratings": ["SSR"]}
        snapshot = MainWindow._build_automation_launch_snapshot(flow, profile)

        flow.model = "model-b"
        profile["favorite_eligible_ratings"].append("R")

        self.assertEqual(snapshot["flow"]["model"], "model-a")
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
        self.assertEqual(
            launched[0][0]["automation_snapshot"]["screening_profile_snapshot"]["version"],
            3,
        )
        self.assertEqual(launched[0][1], "automation")


if __name__ == "__main__":
    unittest.main()
