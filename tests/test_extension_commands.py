from __future__ import annotations

import unittest

from core.extension_commands import ExtensionCommandBroker


class ExtensionCommandBrokerTest(unittest.TestCase):
    def test_frontend_command_can_be_claimed_and_completed_by_extension(self) -> None:
        broker = ExtensionCommandBroker()

        queued = broker.enqueue(
            "collect_auto",
            recruitment_task_id=12,
            platform="boss",
            source_url="https://www.zhipin.com/web/geek/recommend",
        )
        claimed = broker.claim_next()

        self.assertEqual(claimed["id"], queued["id"])
        self.assertEqual(claimed["action"], "collect_auto")
        self.assertEqual(claimed["recruitment_task_id"], 12)
        self.assertEqual(broker.status(queued["id"])["status"], "running")

        completed = broker.complete(
            queued["id"], claim_token=claimed["claim_token"], ok=True, message="采集完成"
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["message"], "采集完成")

    def test_only_supported_actions_can_be_queued(self) -> None:
        broker = ExtensionCommandBroker()

        with self.assertRaisesRegex(ValueError, "不支持的插件操作"):
            broker.enqueue(
                "delete_everything",
                recruitment_task_id=12,
                platform="boss",
                source_url="https://www.zhipin.com/web/geek/recommend",
            )

    def test_claim_returns_none_when_queue_is_empty(self) -> None:
        self.assertIsNone(ExtensionCommandBroker().claim_next())

    def test_second_capture_is_rejected_but_pause_can_interrupt_running_capture(self) -> None:
        broker = ExtensionCommandBroker()
        broker.enqueue(
            "collect_auto", recruitment_task_id=12, platform="boss", source_url="https://www.zhipin.com"
        )
        broker.claim_next()

        with self.assertRaisesRegex(ValueError, "已有插件采集指令"):
            broker.enqueue(
                "collect_current", recruitment_task_id=12, platform="boss", source_url="https://www.zhipin.com"
            )

        pause = broker.enqueue(
            "pause_scroll", recruitment_task_id=12, platform="boss", source_url="https://www.zhipin.com"
        )
        self.assertEqual(pause["status"], "queued")

    def test_expired_claim_is_recovered_and_heartbeat_extends_lease(self) -> None:
        now = [100.0]
        broker = ExtensionCommandBroker(clock=lambda: now[0], lease_seconds=30)
        command = broker.enqueue(
            "collect_auto", recruitment_task_id=12, platform="boss", source_url="https://www.zhipin.com"
        )
        claimed = broker.claim_next()

        now[0] = 120.0
        broker.heartbeat(command["id"], claimed["claim_token"])
        now[0] = 140.0
        self.assertIsNone(broker.claim_next())

        now[0] = 151.0
        recovered = broker.claim_next()
        self.assertEqual(recovered["id"], command["id"])
        self.assertEqual(recovered["attempt"], 2)


if __name__ == "__main__":
    unittest.main()
