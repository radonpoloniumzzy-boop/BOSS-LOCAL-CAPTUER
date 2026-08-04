from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ui.main_window import MainWindow


class _SignalSpy:
    def __init__(self) -> None:
        self.calls = 0

    def emit(self) -> None:
        self.calls += 1


class MainWindowJobLifecycleTest(unittest.TestCase):
    def test_capture_completion_updates_bound_task_not_current_config_task(self) -> None:
        repository = SimpleNamespace(update_recruitment_task_progress=Mock())
        window = SimpleNamespace(
            repository=repository,
            _active_capture_task_id=7,
            _capture_running=True,
            _active_capture_profile_id=4,
            dashboard_page=SimpleNamespace(set_running=Mock(), update_result=Mock()),
            refresh_candidates=Mock(),
            refresh_dashboard_stats=Mock(),
            refresh_recruitment_tasks=Mock(),
            statusBar=lambda: SimpleNamespace(showMessage=Mock()),
            config=SimpleNamespace(automation_flow=SimpleNamespace(task_id=99)),
        )

        MainWindow._on_capture_finished(
            window, SimpleNamespace(status="failed", message="采集失败")
        )

        repository.update_recruitment_task_progress.assert_called_once_with(
            7, current_step="等待人工处理", message="采集失败"
        )
        window.refresh_recruitment_tasks.assert_called_once_with(7)
        self.assertIsNone(window._active_capture_task_id)

    def test_task_failure_without_execution_context_changes_nothing(self) -> None:
        repository = SimpleNamespace(
            get_recruitment_task=Mock(), set_recruitment_task_status=Mock()
        )
        window = SimpleNamespace(repository=repository, refresh_recruitment_tasks=Mock())

        MainWindow._mark_recruitment_task_failed(window, None, "未知来源错误")

        repository.get_recruitment_task.assert_not_called()
        repository.set_recruitment_task_status.assert_not_called()

    def test_extension_import_failure_updates_payload_task(self) -> None:
        window = SimpleNamespace(
            dashboard_page=SimpleNamespace(set_message=Mock()),
            config=SimpleNamespace(automation_flow=SimpleNamespace(enabled=True)),
            automation_flow_page=SimpleNamespace(set_status=Mock()),
            statusBar=lambda: SimpleNamespace(showMessage=Mock()),
            _mark_recruitment_task_failed=Mock(),
        )

        MainWindow._on_extension_import_error(
            window, {"message": "导入失败", "recruitment_task_id": 42}
        )

        window._mark_recruitment_task_failed.assert_called_once_with(42, "导入失败")

    def test_ai_completion_updates_run_task_not_current_config_task(self) -> None:
        repository = SimpleNamespace(
            get_screening_run=Mock(return_value={"task_id": 7}),
            get_recruitment_task=Mock(return_value={"id": 7, "status": "running"}),
            set_recruitment_task_status=Mock(),
        )
        window = SimpleNamespace(
            repository=repository,
            _ai_screening_origin="automation",
            automation_flow_page=SimpleNamespace(set_running=Mock(), set_status=Mock()),
            ai_page=SimpleNamespace(set_running=Mock(), set_status=Mock()),
            refresh_automation_flow=Mock(),
            refresh_ai_screen=Mock(),
            refresh_recruitment_tasks=Mock(),
            statusBar=lambda: SimpleNamespace(showMessage=Mock()),
            config=SimpleNamespace(automation_flow=SimpleNamespace(task_id=99)),
        )

        MainWindow._on_ai_screening_finished(
            window, {"run_id": 31, "completed": 4, "failed": 0, "message": "完成"}
        )

        repository.set_recruitment_task_status.assert_called_once_with(
            7, "waiting_user", message="完成"
        )
        window.refresh_recruitment_tasks.assert_called_once_with(7)

    def test_pausing_job_stops_and_clears_linked_work(self) -> None:
        worker = Mock()
        stop_capture = _SignalSpy()
        window = SimpleNamespace(
            repository=SimpleNamespace(pause_active_recruitment_tasks_for_role=Mock(return_value=[11])),
            config=SimpleNamespace(automation_flow=SimpleNamespace(profile_id=7, enabled=True)),
            config_service=SimpleNamespace(save=Mock()),
            _automation_armed=True,
            _queued_automation_batches=[{"batch_id": 3}],
            automation_flow_page=SimpleNamespace(set_waiting=Mock(), set_status=Mock()),
            ai_page=SimpleNamespace(set_status=Mock()),
            dashboard_page=SimpleNamespace(set_message=Mock()),
            _ai_screening_thread=(object(), worker),
            _active_screening_profile_id=7,
            _capture_running=True,
            _active_capture_profile_id=7,
            automation_worker=SimpleNamespace(request_stop=Mock()),
            stop_capture_requested=stop_capture,
        )

        MainWindow._stop_work_for_job_profile(window, 7)

        self.assertFalse(window.config.automation_flow.enabled)
        self.assertFalse(window._automation_armed)
        self.assertEqual(window._queued_automation_batches, [])
        worker.request_stop.assert_called_once_with()
        window.automation_worker.request_stop.assert_called_once_with()
        self.assertEqual(stop_capture.calls, 0)
        window.config_service.save.assert_called_once_with(window.config)
        window.repository.pause_active_recruitment_tasks_for_role.assert_called_once_with(
            7, "岗位已暂停或结束，关联招聘任务自动暂停。"
        )

    def test_pausing_unrelated_job_does_not_clear_active_automation_queue(self) -> None:
        window = SimpleNamespace(
            repository=SimpleNamespace(pause_active_recruitment_tasks_for_role=Mock(return_value=[])),
            config=SimpleNamespace(automation_flow=SimpleNamespace(profile_id=8, enabled=True)),
            config_service=SimpleNamespace(save=Mock()),
            _automation_armed=True,
            _queued_automation_batches=[{"batch_id": 4}],
            automation_flow_page=SimpleNamespace(set_waiting=Mock(), set_status=Mock()),
            ai_page=SimpleNamespace(set_status=Mock()),
            dashboard_page=SimpleNamespace(set_message=Mock()),
            _ai_screening_thread=None,
            _active_screening_profile_id=None,
            _capture_running=False,
            _active_capture_profile_id=None,
            automation_worker=SimpleNamespace(request_stop=Mock()),
            stop_capture_requested=_SignalSpy(),
        )

        MainWindow._stop_work_for_job_profile(window, 7)

        self.assertTrue(window.config.automation_flow.enabled)
        self.assertTrue(window._automation_armed)
        self.assertEqual(window._queued_automation_batches, [{"batch_id": 4}])
        window.config_service.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
