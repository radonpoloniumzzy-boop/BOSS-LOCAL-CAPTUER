from __future__ import annotations

import unittest

from core.extension_commands import ExtensionCommandBroker


class ExtensionCommandBrokerTest(unittest.TestCase):
    def test_frontend_command_can_be_claimed_and_completed_by_extension(self) -> None:
        broker = ExtensionCommandBroker()

        queued = broker.enqueue("collect_auto", recruitment_task_id=12)
        claimed = broker.claim_next()

        self.assertEqual(claimed["id"], queued["id"])
        self.assertEqual(claimed["action"], "collect_auto")
        self.assertEqual(claimed["recruitment_task_id"], 12)
        self.assertEqual(broker.status(queued["id"])["status"], "running")

        completed = broker.complete(queued["id"], ok=True, message="采集完成")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["message"], "采集完成")

    def test_only_supported_actions_can_be_queued(self) -> None:
        broker = ExtensionCommandBroker()

        with self.assertRaisesRegex(ValueError, "不支持的插件操作"):
            broker.enqueue("delete_everything", recruitment_task_id=12)

    def test_claim_returns_none_when_queue_is_empty(self) -> None:
        self.assertIsNone(ExtensionCommandBroker().claim_next())

    def test_second_capture_is_rejected_but_pause_can_interrupt_running_capture(self) -> None:
        broker = ExtensionCommandBroker()
        broker.enqueue("collect_auto", recruitment_task_id=12)
        broker.claim_next()

        with self.assertRaisesRegex(ValueError, "已有插件采集指令"):
            broker.enqueue("collect_current", recruitment_task_id=12)

        pause = broker.enqueue("pause_scroll", recruitment_task_id=12)
        self.assertEqual(pause["status"], "queued")


if __name__ == "__main__":
    unittest.main()
