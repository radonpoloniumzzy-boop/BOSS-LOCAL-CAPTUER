from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from core.bootstrap import BootstrapService, BootstrapStore
from core.config import ConfigService
from core.models import ScreeningProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository
from web.backend.app import create_web_app


class WebJobTaskFoundationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = BootstrapStore(self.root / "local" / "bootstrap.json")
        self.bootstrap = BootstrapService(
            project_root=self.project,
            store=self.store,
            d_drive=self.root / "missing-drive",
            documents_dir=self.root / "Documents",
        )
        self.data_dir = self.root / "data"
        self.bootstrap.setup(self.data_dir)
        self.token = ConfigService(data_dir=self.data_dir).load().local_api_token
        self.app = create_web_app(self.bootstrap, lock_root=self.root / "locks")
        self.client = TestClient(self.app, base_url="http://127.0.0.1:17864")
        self.client.__enter__()
        self.origin = {"Origin": "http://127.0.0.1:17864"}
        self.extension = {
            "Origin": "chrome-extension://unit-test",
            "X-Boss-Local-Token": self.token,
        }

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def _job_payload(self, title: str = "量化研究员") -> dict[str, object]:
        return {
            "job_title": title,
            "department": "投研",
            "hiring_manager": "招聘经理",
            "location": "上海",
            "employment_type": "全职",
            "target_hires": 2,
            "priority": "high",
            "status": "draft",
            "experience_requirement": "3 年以上",
            "education_requirement": "本科",
            "recruitment_deadline": "2026-10-01",
            "jd_text": "负责量化策略研究。",
            "must_have": ["Python"],
            "nice_to_have": ["期货"],
            "risk_flags": ["频繁跳槽"],
            "exclusions": ["无金融经验"],
            "interview_checks": ["策略复盘"],
            "evidence_policy": {"required": ["项目"]},
        }

    def _create_active_job(self) -> dict[str, object]:
        created = self.client.post("/api/job-profiles", json=self._job_payload(), headers=self.origin)
        self.assertEqual(created.status_code, 200, created.text)
        active = self.client.post(
            f"/api/job-profiles/{created.json()['id']}/status",
            json={"status": "active", "expected_version": created.json()["version"]},
            headers=self.origin,
        )
        self.assertEqual(active.status_code, 200, active.text)
        return active.json()

    def _create_task(self, job: dict[str, object]) -> dict[str, object]:
        created = self.client.post(
            "/api/recruitment-tasks",
            json={
                "name": "Boss 推荐流",
                "role_id": job["id"],
                "profile_version": job["version"],
                "platform": "boss",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "target_candidates": 20,
            },
            headers=self.origin,
        )
        self.assertEqual(created.status_code, 200, created.text)
        return created.json()

    def test_job_profile_web_api_versions_and_hides_prompt_fields(self) -> None:
        created = self.client.post("/api/job-profiles", json=self._job_payload(), headers=self.origin)
        self.assertEqual(created.status_code, 200, created.text)
        payload = created.json()
        self.assertEqual(payload["version"], 1)
        self.assertNotIn("prompt_text", created.text)
        self.assertNotIn("prompt_source", created.text)

        listed = self.client.get("/api/job-profiles")
        self.assertEqual(list(listed.json()["rows"][0].keys()), [
            "id",
            "job_title",
            "department",
            "location",
            "employment_type",
            "target_hires",
            "priority",
            "status",
            "version",
            "updated_at",
        ])
        self.assertNotIn("prompt_text", listed.text)

        detail = self.client.get(f"/api/job-profiles/{payload['id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertNotIn("prompt_text", detail.text)
        self.assertNotIn("prompt_source", detail.text)

        no_op = self.client.put(
            f"/api/job-profiles/{payload['id']}",
            json={**self._job_payload(), "expected_version": payload["version"]},
            headers=self.origin,
        )
        self.assertEqual(no_op.status_code, 200, no_op.text)
        self.assertFalse(no_op.json()["changed"])
        self.assertEqual(no_op.json()["version"], 1)
        self.assertEqual(no_op.json()["updated_at"], payload["updated_at"])

        changed = self.client.put(
            f"/api/job-profiles/{payload['id']}",
            json={**self._job_payload(), "target_hires": 3, "expected_version": payload["version"]},
            headers=self.origin,
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertTrue(changed.json()["changed"])
        self.assertEqual(changed.json()["version"], 2)

        conflict = self.client.put(
            f"/api/job-profiles/{payload['id']}",
            json={**self._job_payload(), "expected_version": 1},
            headers=self.origin,
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "job_profile_version_conflict")

        versions = self.client.get(f"/api/job-profiles/{payload['id']}/versions")
        self.assertEqual([row["version"] for row in versions.json()["rows"]], [2, 1])
        self.assertNotIn("prompt_text", versions.text)

    def test_job_profile_status_machine_and_closed_is_terminal(self) -> None:
        created = self.client.post("/api/job-profiles", json=self._job_payload("风控经理"), headers=self.origin)
        profile_id = created.json()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/job-profiles/{profile_id}/status",
                json={"status": "active", "expected_version": created.json()["version"]},
                headers=self.origin,
            ).status_code,
            200,
        )
        active = self.client.get(f"/api/job-profiles/{profile_id}").json()
        self.assertEqual(
            self.client.post(
                f"/api/job-profiles/{profile_id}/status",
                json={"status": "paused", "expected_version": active["version"]},
                headers=self.origin,
            ).status_code,
            200,
        )
        paused = self.client.get(f"/api/job-profiles/{profile_id}").json()
        self.assertEqual(
            self.client.post(
                f"/api/job-profiles/{profile_id}/status",
                json={"status": "closed", "expected_version": paused["version"]},
                headers=self.origin,
            ).status_code,
            200,
        )
        closed = self.client.get(f"/api/job-profiles/{profile_id}").json()
        reopened = self.client.post(
            f"/api/job-profiles/{profile_id}/status",
            json={"status": "active", "expected_version": closed["version"]},
            headers=self.origin,
        )
        self.assertEqual(reopened.status_code, 409)
        self.assertEqual(reopened.json()["error"]["code"], "invalid_job_profile_status_transition")

    def test_job_profile_update_conflict_is_atomic_and_preserves_winner(self) -> None:
        db_path = self.data_dir / "boss_local_tool.db"
        base_db = DatabaseManager(db_path)
        base_db.initialize_existing()
        base_repo = CandidateRepository(base_db)
        profile = base_repo.save_web_job_profile(
            ScreeningProfile(
                job_title="并发岗位",
                department="投研",
                hiring_manager="招聘经理",
                location="上海",
                employment_type="全职",
                target_hires=2,
                priority="high",
                status="draft",
                experience_requirement="3 年以上",
                education_requirement="本科",
                recruitment_deadline="2026-10-01",
                jd_text="负责量化策略研究。",
                prompt_text="",
                must_have=["Python"],
                nice_to_have=["期货"],
                risk_flags=["频繁跳槽"],
                exclusions=["无金融经验"],
                interview_checks=["策略复盘"],
                evidence_policy={"required": ["项目"]},
            )
        )[0]
        profile_id = int(profile.id)
        version = int(profile.version)

        barrier = threading.Barrier(2)
        results: list[tuple[str, int | str]] = []
        result_lock = threading.Lock()

        def update(target_hires: int) -> None:
            db = DatabaseManager(db_path)
            db.initialize_existing()
            repo = CandidateRepository(db)
            try:
                barrier.wait(timeout=5)
                updated, _changed = repo.save_web_job_profile(
                    ScreeningProfile(
                        id=profile_id,
                        job_title="并发岗位",
                        department="投研",
                        hiring_manager="招聘经理",
                        location="上海",
                        employment_type="全职",
                        target_hires=target_hires,
                        priority="high",
                        status="draft",
                        experience_requirement="3 年以上",
                        education_requirement="本科",
                        recruitment_deadline="2026-10-01",
                        jd_text="负责量化策略研究。",
                        prompt_text="",
                        must_have=["Python"],
                        nice_to_have=["期货"],
                        risk_flags=["频繁跳槽"],
                        exclusions=["无金融经验"],
                        interview_checks=["策略复盘"],
                        evidence_policy={"required": ["项目"]},
                    ),
                    expected_version=version,
                )
                outcome: tuple[str, int | str] = ("ok", int(updated.target_hires))
            except Exception as exc:  # noqa: BLE001 - test records stable public exception type/message.
                outcome = ("error", exc.__class__.__name__)
            finally:
                db.close_thread_connection()
                with result_lock:
                    results.append(outcome)

        threads = [threading.Thread(target=update, args=(3,)), threading.Thread(target=update, args=(4,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual([kind for kind, _value in results].count("ok"), 1)
        self.assertEqual([value for kind, value in results if kind == "error"], ["JobProfileVersionConflictError"])
        winner_hires = next(value for kind, value in results if kind == "ok")
        detail = self.client.get(f"/api/job-profiles/{profile_id}").json()
        self.assertEqual(detail["target_hires"], winner_hires)
        self.assertEqual(detail["version"], 2)
        versions = self.client.get(f"/api/job-profiles/{profile_id}/versions").json()["rows"]
        self.assertEqual([row["version"] for row in versions], [2, 1])
        base_db.close_all_connections()

    def test_recruitment_task_uses_fixed_active_job_version_and_safe_fields(self) -> None:
        job = self._create_active_job()
        task = self._create_task(job)
        self.assertEqual(task["profile_version"], job["version"])
        self.assertEqual(task["role_title"], job["job_title"])
        self.assertEqual(task["target_candidates"], 20)
        self.assertEqual(task["current_step"], "待启动")
        self.assertEqual(task["latest_message"], "")
        self.assertNotIn("evidence_json", str(task))
        self.assertNotIn("raw_card_text", str(task))

        missing_version = self.client.post(
            "/api/recruitment-tasks",
            json={
                "name": "坏版本",
                "role_id": job["id"],
                "profile_version": 999,
                "platform": "boss",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
            },
            headers=self.origin,
        )
        self.assertEqual(missing_version.status_code, 400)

    def test_job_profile_evidence_policy_is_preserved_modified_and_validated(self) -> None:
        created = self.client.post("/api/job-profiles", json=self._job_payload("证据岗位"), headers=self.origin)
        self.assertEqual(created.status_code, 200, created.text)
        profile_id = created.json()["id"]

        changed_hires = self.client.put(
            f"/api/job-profiles/{profile_id}",
            json={**self._job_payload("证据岗位"), "target_hires": 5, "expected_version": created.json()["version"]},
            headers=self.origin,
        )
        self.assertEqual(changed_hires.status_code, 200, changed_hires.text)
        self.assertEqual(changed_hires.json()["evidence_policy"], {"required": ["项目"]})

        changed_policy = self.client.put(
            f"/api/job-profiles/{profile_id}",
            json={
                **self._job_payload("证据岗位"),
                "target_hires": 5,
                "evidence_policy": {"required": ["项目", "作品"], "forbid": ["空泛评价"]},
                "expected_version": changed_hires.json()["version"],
            },
            headers=self.origin,
        )
        self.assertEqual(changed_policy.status_code, 200, changed_policy.text)
        self.assertEqual(changed_policy.json()["version"], 3)
        self.assertEqual(changed_policy.json()["evidence_policy"]["forbid"], ["空泛评价"])
        versions = self.client.get(f"/api/job-profiles/{profile_id}/versions").json()["rows"]
        self.assertEqual(versions[0]["snapshot"]["evidence_policy"]["forbid"], ["空泛评价"])

    def test_web_write_dtos_reject_extra_ai_prompt_fields(self) -> None:
        rejected = self.client.post(
            "/api/job-profiles",
            json={**self._job_payload("非法字段"), "prompt_text": "不要进 Web DTO"},
            headers=self.origin,
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(rejected.json()["error"]["code"], "invalid_request")

        job = self._create_active_job()
        task_rejected = self.client.post(
            "/api/recruitment-tasks",
            json={
                "name": "坏任务",
                "role_id": job["id"],
                "profile_version": job["version"],
                "platform": "boss",
                "source_url": "https://www.zhipin.com/web/geek/recommend",
                "ai_config": {"model": "x"},
            },
            headers=self.origin,
        )
        self.assertEqual(task_rejected.status_code, 422, task_rejected.text)
        self.assertEqual(task_rejected.json()["error"]["code"], "invalid_request")

    def test_plugin_context_persists_and_becomes_unavailable_for_terminal_task(self) -> None:
        job = self._create_active_job()
        task = self._create_task(job)

        selected = self.client.put(
            "/api/plugin-context",
            json={"recruitment_task_id": task["id"]},
            headers=self.origin,
        )
        self.assertEqual(selected.status_code, 409)
        self.assertEqual(selected.json()["error"]["code"], "plugin_context_unavailable")

        running = self.client.post(
            f"/api/recruitment-tasks/{task['id']}/status",
            json={"status": "running"},
            headers=self.origin,
        )
        self.assertEqual(running.status_code, 200, running.text)
        selected = self.client.put(
            "/api/plugin-context",
            json={"recruitment_task_id": task["id"]},
            headers=self.origin,
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        context = self.client.get("/api/plugin/context", headers=self.extension)
        self.assertEqual(context.status_code, 200, context.text)
        self.assertEqual(context.json()["recruitment_task_id"], task["id"])
        self.assertEqual(context.json()["job_profile_id"], job["id"])
        self.assertEqual(context.json()["job_profile_version"], job["version"])
        self.assertNotIn(self.token, context.text)

        self.client.__exit__(None, None, None)
        self.app = create_web_app(self.bootstrap, lock_root=self.root / "locks")
        self.client = TestClient(self.app, base_url="http://127.0.0.1:17864")
        self.client.__enter__()
        restored = self.client.get("/api/plugin/context", headers=self.extension)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["recruitment_task_id"], task["id"])

        completed = self.client.post(
            f"/api/recruitment-tasks/{task['id']}/status",
            json={"status": "completed"},
            headers=self.origin,
        )
        self.assertEqual(completed.status_code, 200, completed.text)
        unavailable = self.client.get("/api/plugin/context", headers=self.extension)
        self.assertEqual(unavailable.status_code, 409)
        self.assertEqual(unavailable.json()["error"]["code"], "context_unavailable")

    def test_plugin_context_becomes_unavailable_when_job_closes(self) -> None:
        job = self._create_active_job()
        task = self._create_task(job)
        running = self.client.post(
            f"/api/recruitment-tasks/{task['id']}/status",
            json={"status": "running"},
            headers=self.origin,
        )
        self.assertEqual(running.status_code, 200, running.text)
        selected = self.client.put(
            "/api/plugin-context",
            json={"recruitment_task_id": task["id"]},
            headers=self.origin,
        )
        self.assertEqual(selected.status_code, 200, selected.text)

        closed = self.client.post(
            f"/api/job-profiles/{job['id']}/status",
            json={"status": "closed", "expected_version": job["version"]},
            headers=self.origin,
        )
        self.assertEqual(closed.status_code, 200, closed.text)
        task_after_close = self.client.get(f"/api/recruitment-tasks/{task['id']}").json()
        self.assertEqual(task_after_close["status"], "cancelled")
        unavailable = self.client.get("/api/plugin/context", headers=self.extension)
        self.assertEqual(unavailable.status_code, 409)
        self.assertEqual(unavailable.json()["error"]["code"], "context_unavailable")

    def test_web_current_plugin_context_can_be_read_and_cleared(self) -> None:
        job = self._create_active_job()
        task = self._create_task(job)
        self.assertEqual(self.client.get("/api/plugin-context", headers=self.origin).json()["context"], None)
        self.client.post(f"/api/recruitment-tasks/{task['id']}/status", json={"status": "running"}, headers=self.origin)
        selected = self.client.put("/api/plugin-context", json={"recruitment_task_id": task["id"]}, headers=self.origin)
        self.assertEqual(selected.status_code, 200, selected.text)

        current = self.client.get("/api/plugin-context", headers=self.origin)
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["context"]["recruitment_task_id"], task["id"])
        self.assertNotIn(self.token, current.text)

        cleared = self.client.put("/api/plugin-context", json={"recruitment_task_id": None}, headers=self.origin)
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(self.client.get("/api/plugin-context", headers=self.origin).json()["context"])


if __name__ == "__main__":
    unittest.main()
