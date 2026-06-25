from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.models import CandidateRecord, ScreeningProfile, ScreeningResult
from core.utils import now_iso
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class CandidateRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(db_path)
        self.db.initialize()
        self.repository = CandidateRepository(self.db)

    def tearDown(self) -> None:
        self.db.close_thread_connection()
        self.temp_dir.cleanup()

    def _candidate(self, candidate_key: str, name: str) -> CandidateRecord:
        return CandidateRecord(
            candidate_key=candidate_key,
            raw_text_hash=f"hash-{candidate_key}",
            job_title="招聘实习生",
            source_url="https://example.com",
            capture_time="2026-04-07T10:00:00",
            raw_card_text=f"{name} 原始文本",
            name=name,
            expected_salary="10k-12k",
            work_experience_text="1年招聘",
            education_text="本科",
        )

    def test_upsert_deduplicates_candidates_and_preserves_batch_history(self) -> None:
        batch_one = self.repository.create_batch("招聘实习生", "https://example.com/page1")
        first = self._candidate("platform:1", "张三")
        second = self._candidate("platform:1", "张三")
        result_one = self.repository.upsert_batch_candidates(batch_one.id, [first, second])
        self.assertEqual(result_one["inserted_candidates"], 1)
        self.assertEqual(result_one["inserted_batch_items"], 1)

        batch_two = self.repository.create_batch("招聘实习生", "https://example.com/page2")
        result_two = self.repository.upsert_batch_candidates(batch_two.id, [first])
        self.assertEqual(result_two["inserted_candidates"], 0)
        self.assertEqual(result_two["inserted_batch_items"], 1)

        candidates = self.repository.list_candidates()
        self.assertEqual(len(candidates), 1)
        detail = self.repository.get_candidate_detail(int(candidates[0]["id"]))
        assert detail is not None
        self.assertEqual(len(detail["appearances"]), 2)

    def test_screening_profile_is_upserted_by_job_title(self) -> None:
        first = self.repository.save_screening_profile(
            ScreeningProfile(job_title="招聘实习生", jd_text="本科", prompt_text="第一版")
        )
        second = self.repository.save_screening_profile(
            ScreeningProfile(job_title="招聘实习生", jd_text="本科，招聘经验", prompt_text="第二版")
        )
        rows = self.repository.list_screening_profiles()
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["prompt_text"], "第二版")

    def test_candidate_standard_profiles_are_searchable(self) -> None:
        batch = self.repository.create_batch("SaaS Sales", "https://example.com")
        self.repository.upsert_batch_candidates(
            batch.id,
            [
                CandidateRecord(
                    candidate_key="platform:profiled",
                    raw_text_hash="hash-profiled",
                    job_title="SaaS Sales",
                    source_url="https://example.com",
                    capture_time="2026-04-07T10:00:00",
                    raw_card_text="Profiled 深圳 5年 B2B SaaS CRM 企业服务 KA 销售",
                    name="Profiled",
                    active_status="近期活跃",
                    expected_salary="25k-35k",
                    work_experience_text="深圳 5年 SaaS 大客户销售经验",
                    education_text="本科",
                    tags_text="SaaS | CRM | 企业服务 | KA",
                )
            ],
        )

        rows = self.repository.list_candidates(
            keyword="近期活跃",
            city="深圳",
            years_min=3,
            years_max=6,
            profile_tag="企业服务 SaaS 销售",
        )
        detail = self.repository.get_candidate_detail(int(rows[0]["id"]))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["city"], "深圳")
        self.assertEqual(rows[0]["years_experience"], 5)
        self.assertEqual(rows[0]["job_track"], "SaaS销售")
        assert detail is not None
        self.assertEqual(detail["standard_profile"]["city"], "深圳")
        self.assertEqual(detail["standard_profile"]["years_experience"], 5)

    def test_candidates_include_best_role_match_summary(self) -> None:
        batch = self.repository.create_batch("SaaS Sales", "https://example.com")
        self.repository.upsert_batch_candidates(
            batch.id,
            [self._candidate("platform:best-match-summary", "Blair")],
        )
        candidate = dict(self.repository.list_candidates()[0])
        sales_role = self.repository.save_screening_profile(
            ScreeningProfile(job_title="SaaS Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        ops_role = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Operations", jd_text="Ops", prompt_text="screen ops")
        )
        self.repository.upsert_candidate_role_match(
            candidate_id=int(candidate["id"]),
            role_id=int(ops_role.id),
            latest_rating="R",
            latest_confidence="medium",
            match_status="ai_screened",
            recruitment_status="screened",
            timestamp="2026-01-02T10:00:00",
        )
        self.repository.upsert_candidate_role_match(
            candidate_id=int(candidate["id"]),
            role_id=int(sales_role.id),
            latest_rating="SSR",
            latest_confidence="high",
            match_status="ai_screened",
            recruitment_status="replied",
            timestamp="2026-01-01T10:00:00",
        )
        self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(sales_role.id),
            to_status="contacted",
            operator="tester",
            reason_code="priority_candidate",
            note="Initial outreach",
        )
        self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(sales_role.id),
            to_status="replied",
            operator="tester",
            reason_code="candidate_not_interested",
            note="Prefers remote roles",
        )

        rows = self.repository.list_candidates()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role_title"], "SaaS Sales")
        self.assertEqual(rows[0]["latest_rating"], "SSR")
        self.assertEqual(rows[0]["latest_confidence"], "high")
        self.assertEqual(rows[0]["match_status"], "ai_screened")
        self.assertEqual(rows[0]["recruitment_status"], "replied")
        self.assertTrue(str(rows[0]["match_updated_at"]))
        self.assertEqual(rows[0]["latest_status_from"], "contacted")
        self.assertEqual(rows[0]["latest_status_to"], "replied")
        self.assertEqual(rows[0]["latest_reason_code"], "candidate_not_interested")
        self.assertEqual(rows[0]["latest_status_note"], "Prefers remote roles")
        self.assertEqual(rows[0]["latest_status_operator"], "tester")
        filtered_candidates = self.repository.list_candidates(
            latest_reason_code="candidate_not_interested"
        )
        filtered_matches = self.repository.list_candidate_role_matches(
            role_id=int(sales_role.id),
            latest_reason_code="candidate_not_interested",
        )
        unrelated_candidates = self.repository.list_candidates(latest_reason_code="skill_gap")

        self.assertEqual([row["name"] for row in filtered_candidates], ["Blair"])
        self.assertEqual([row["name"] for row in filtered_matches], ["Blair"])
        self.assertEqual(unrelated_candidates, [])

    def test_role_match_search_filters_recent_active_candidates(self) -> None:
        batch = self.repository.create_batch("SaaS Sales", "https://example.com")
        self.repository.upsert_batch_candidates(
            batch.id,
            [
                CandidateRecord(
                    candidate_key="platform:recent-active",
                    raw_text_hash="hash-recent-active",
                    job_title="SaaS Sales",
                    source_url="https://example.com",
                    capture_time=now_iso(),
                    raw_card_text="Recent 深圳 5年 B2B SaaS CRM 企业服务 KA 销售",
                    name="Recent",
                    active_status="今日活跃",
                    work_experience_text="深圳 5年 SaaS 大客户销售经验",
                    education_text="本科",
                    tags_text="SaaS | CRM | 企业服务 | KA",
                ),
                CandidateRecord(
                    candidate_key="platform:stale-active",
                    raw_text_hash="hash-stale-active",
                    job_title="SaaS Sales",
                    source_url="https://example.com",
                    capture_time="2000-01-01T00:00:00",
                    raw_card_text="Stale 深圳 5年 B2B SaaS CRM 企业服务 KA 销售",
                    name="Stale",
                    active_status="历史采集",
                    work_experience_text="深圳 5年 SaaS 大客户销售经验",
                    education_text="本科",
                    tags_text="SaaS | CRM | 企业服务 | KA",
                ),
            ],
        )
        role = self.repository.save_screening_profile(
            ScreeningProfile(
                job_title="SaaS Sales",
                jd_text="B2B SaaS sales",
                prompt_text="Rate SaaS sales candidates",
            )
        )
        candidates = {row["name"]: row for row in self.repository.list_candidates()}
        for name in ["Recent", "Stale"]:
            self.repository.upsert_candidate_role_match(
                candidate_id=int(candidates[name]["id"]),
                role_id=int(role.id),
                latest_rating="SSR",
                latest_confidence="high",
                match_status="screened",
                recruitment_status="screened",
            )

        rows = self.repository.list_candidate_role_matches(
            role_id=int(role.id),
            recruitment_statuses=["uncontacted"],
            minimum_rating="SSR",
            city="深圳",
            years_min=3,
            years_max=6,
            profile_tag="企业服务 SaaS 销售",
            last_active_days=90,
        )

        self.assertEqual([row["name"] for row in rows], ["Recent"])
        self.assertEqual(rows[0]["last_active_at"][:10], now_iso()[:10])

    def test_outdated_candidate_profiles_can_be_refreshed(self) -> None:
        batch = self.repository.create_batch("SaaS Sales", "https://example.com")
        self.repository.upsert_batch_candidates(
            batch.id,
            [
                CandidateRecord(
                    candidate_key="platform:profile-refresh",
                    raw_text_hash="hash-refresh",
                    job_title="SaaS Sales",
                    source_url="https://example.com",
                    capture_time="2026-04-07T10:00:00",
                    raw_card_text="Refresh Shenzhen 5 years B2B SaaS CRM enterprise sales",
                    name="Refresh",
                    work_experience_text="Shenzhen 5 years B2B SaaS CRM enterprise sales",
                    education_text="Bachelor",
                    tags_text="SaaS | CRM | B2B",
                )
            ],
        )
        candidate_id = int(self.repository.list_candidates(keyword="Refresh")[0]["id"])
        connection = self.db.get_connection()
        connection.execute(
            """
            UPDATE candidate_profiles
            SET parser_version = 'legacy:v0',
                job_family = '',
                job_track = '',
                profile_completeness = 0
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        )
        connection.commit()

        refreshed = self.repository.refresh_outdated_candidate_profiles()
        detail = self.repository.get_candidate_detail(candidate_id)
        assert detail is not None

        self.assertEqual(refreshed, 1)
        self.assertEqual(detail["standard_profile"]["parser_version"], "rule:v2")
        self.assertEqual(detail["standard_profile"]["job_family"], "销售")
        self.assertEqual(detail["standard_profile"]["job_track"], "SaaS销售")
        self.assertGreater(detail["standard_profile"]["profile_completeness"], 0)
        self.assertEqual(self.repository.refresh_outdated_candidate_profiles(), 0)

    def test_screening_runs_can_be_filtered_by_automation_origin(self) -> None:
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Java工程师", jd_text="Java", prompt_text="筛选 Java")
        )
        self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Java工程师",
            batch_id=None,
            provider="fake",
            model="manual-model",
            total_candidates=1,
        )
        automation_run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Java工程师",
            batch_id=None,
            provider="fake",
            model="automation-model",
            total_candidates=1,
            origin="automation",
        )

        automation_runs = self.repository.list_screening_runs(origin="automation")

        self.assertEqual(len(automation_runs), 1)
        self.assertEqual(automation_runs[0]["id"], automation_run_id)
        self.assertEqual(automation_runs[0]["origin"], "automation")
        version = self.db.get_connection().execute("SELECT version FROM schema_version").fetchone()
        self.assertEqual(version["version"], 11)

    def test_interrupted_screening_tasks_are_recovered(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(batch.id, [self._candidate("platform:2", "Alice")])
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Sales",
            batch_id=None,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=[candidate],
            model_name="fake-model",
            prompt_version="v1",
            request_hashes={int(candidate["id"]): "hash"},
        )
        task = self.repository.claim_next_screening_task(run_id)
        self.assertIsNotNone(task)

        recovered = self.repository.recover_interrupted_screening_tasks()

        tasks = self.repository.list_screening_tasks(run_id)
        run = self.repository.list_screening_runs()[0]
        self.assertEqual(recovered, 1)
        self.assertEqual(tasks[0]["status"], "pending")
        self.assertEqual(run["status"], "recoverable")
        matches = self.repository.list_candidate_role_matches(role_id=int(profile.id))
        self.assertEqual(matches[0]["match_status"], "screening_pending")

    def test_failed_screening_tasks_reset_alongside_pending_tasks(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(
            batch.id,
            [
                self._candidate("platform:retry-failed", "Failed"),
                self._candidate("platform:retry-pending", "Pending"),
            ],
        )
        candidates = [dict(row) for row in self.repository.list_candidates()]
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Sales",
            batch_id=batch.id,
            provider="fake",
            model="fake-model",
            total_candidates=2,
        )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=candidates,
            model_name="fake-model",
            prompt_version="v1",
            request_hashes={int(candidate["id"]): f"hash-{candidate['id']}" for candidate in candidates},
            max_retry_count=0,
        )
        task = self.repository.claim_next_screening_task(run_id)
        assert task is not None
        self.repository.mark_screening_task_failure(int(task["task_id"]), "temporary network error")
        before_counts = self.repository.get_screening_task_counts(run_id)

        reset = self.repository.reset_failed_screening_tasks(run_id)

        after_counts = self.repository.get_screening_task_counts(run_id)
        run = self.repository.get_screening_run(run_id)
        matches = self.repository.list_candidate_role_matches(role_id=int(profile.id))
        self.assertEqual(before_counts["failed"], 1)
        self.assertEqual(before_counts["pending"], 1)
        self.assertEqual(reset, 1)
        self.assertEqual(after_counts["failed"], 0)
        self.assertEqual(after_counts["pending"], 2)
        assert run is not None
        self.assertEqual(run["status"], "recoverable")
        self.assertEqual(run["failed_candidates"], 0)
        self.assertEqual({row["match_status"] for row in matches}, {"screening_pending"})

    def test_single_failed_screening_task_can_be_reset_for_retry(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(
            batch.id,
            [
                self._candidate("platform:retry-one", "Retry One"),
                self._candidate("platform:retry-two", "Retry Two"),
            ],
        )
        candidates = [dict(row) for row in self.repository.list_candidates()]
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Sales",
            batch_id=batch.id,
            provider="fake",
            model="fake-model",
            total_candidates=2,
        )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=candidates,
            model_name="fake-model",
            prompt_version="v1",
            request_hashes={int(candidate["id"]): f"hash-{candidate['id']}" for candidate in candidates},
            max_retry_count=0,
        )
        first_task = self.repository.claim_next_screening_task(run_id)
        second_task = self.repository.claim_next_screening_task(run_id)
        assert first_task is not None
        assert second_task is not None
        self.repository.mark_screening_task_failure(int(first_task["task_id"]), "network error one")
        self.repository.mark_screening_task_failure(int(second_task["task_id"]), "network error two")

        reset_run_id = self.repository.reset_failed_screening_task(int(first_task["task_id"]))

        self.assertEqual(reset_run_id, run_id)
        tasks = {int(row["id"]): row for row in self.repository.list_screening_tasks(run_id)}
        counts = self.repository.get_screening_task_counts(run_id)
        run = self.repository.get_screening_run(run_id)
        self.assertEqual(tasks[int(first_task["task_id"])]["status"], "pending")
        self.assertEqual(tasks[int(first_task["task_id"])]["retry_count"], 0)
        self.assertEqual(tasks[int(second_task["task_id"])]["status"], "failed")
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["failed"], 1)
        assert run is not None
        self.assertEqual(run["status"], "recoverable")
        self.assertEqual(run["failed_candidates"], 1)

    def test_screening_task_results_include_pending_candidates(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(batch.id, [self._candidate("platform:3", "Morgan")])
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Sales",
            batch_id=None,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=[candidate],
            model_name="fake-model",
            prompt_version="v1",
            request_hashes={int(candidate["id"]): "hash"},
        )

        rows = self.repository.list_screening_task_results(run_id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_status"], "pending")
        self.assertEqual(rows[0]["route"], "pass_to_ai")
        self.assertEqual(rows[0]["name"], "Morgan")
        self.assertIsNone(rows[0]["rating"])

    def test_manual_check_tasks_are_persisted_but_not_claimed_by_worker(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(batch.id, [self._candidate("platform:4", "Casey")])
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Sales",
            batch_id=None,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )

        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=[candidate],
            model_name="fake-model",
            prompt_version="v1",
            request_hashes={int(candidate["id"]): "hash"},
            prescreen_decisions={
                int(candidate["id"]): {
                    "route": "manual_check",
                    "reason": "insufficient_candidate_evidence",
                    "details": {"text_length": 32},
                }
            },
        )

        task = self.repository.claim_next_screening_task(run_id)
        rows = self.repository.list_screening_task_results(run_id)
        counts = self.repository.get_screening_task_counts(run_id)

        self.assertIsNone(task)
        self.assertEqual(rows[0]["task_status"], "manual_check")
        self.assertEqual(rows[0]["route"], "manual_check")
        self.assertEqual(rows[0]["route_reason"], "insufficient_candidate_evidence")
        self.assertEqual(counts["manual_check"], 1)
        matches = self.repository.list_candidate_role_matches(role_id=int(profile.id))
        self.assertEqual(matches[0]["match_status"], "manual_check")
        review_rows = self.repository.list_manual_review_candidates(role_id=int(profile.id))
        self.assertEqual(len(review_rows), 1)
        self.assertEqual(review_rows[0]["review_reason"], "规则分流：人工确认")
        self.assertEqual(review_rows[0]["route_reason"], "insufficient_candidate_evidence")
        route_details = json.loads(review_rows[0]["route_details_json"])
        self.assertEqual(route_details["text_length"], 32)
        quality_summary = self.repository.get_manual_review_quality_summary(role_id=int(profile.id))
        self.assertEqual(quality_summary["active_total"], 1)
        self.assertEqual(quality_summary["manual_review_total"], 1)
        self.assertEqual(quality_summary["rule_manual_check"], 1)
        self.assertEqual(quality_summary["rule_hold"], 0)

    def test_screening_success_updates_candidate_role_match(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(batch.id, [self._candidate("platform:5", "Taylor")])
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Sales",
            batch_id=None,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=[candidate],
            model_name="fake-model",
            prompt_version="v1",
            request_hashes={int(candidate["id"]): "hash"},
        )
        pending_matches = self.repository.list_candidate_role_matches(role_id=int(profile.id))
        self.assertEqual(pending_matches[0]["match_status"], "screening_pending")

        task = self.repository.claim_next_screening_task(run_id)
        assert task is not None
        running_matches = self.repository.list_candidate_role_matches(role_id=int(profile.id))
        self.assertEqual(running_matches[0]["match_status"], "screening_running")
        result_id = self.repository.save_screening_result(
            ScreeningResult(
                run_id=run_id,
                candidate_id=int(candidate["id"]),
                rating="SSR",
                persona="Strong SaaS sales evidence.",
                raw_response='{"rating":"SSR"}',
                confidence="high",
                evidence_json='[{"item":"SaaS","evidence":"5 years"}]',
                gap_json='["quota not verified"]',
                risk_json='[]',
                recommended_action="priority_outreach",
            )
        )
        self.repository.mark_screening_task_success(int(task["task_id"]), result_id)

        matches = self.repository.list_candidate_role_matches(
            role_id=int(profile.id),
            match_statuses=["ai_screened"],
            recruitment_statuses=["screened"],
            minimum_rating="SSR",
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["candidate_id"], int(candidate["id"]))
        self.assertEqual(matches[0]["latest_rating"], "SSR")
        self.assertEqual(matches[0]["latest_confidence"], "high")
        self.assertEqual(matches[0]["recruitment_status"], "screened")
        self.assertEqual(matches[0]["screening_result_id"], result_id)
        self.assertEqual(matches[0]["recommended_action"], "priority_outreach")
        self.assertIn("SaaS", matches[0]["evidence_json"])
        candidate_row = dict(self.repository.list_candidates()[0])
        self.assertEqual(candidate_row["recommended_action"], "priority_outreach")
        self.assertIn("quota not verified", candidate_row["gap_json"])
        detail = self.repository.get_candidate_detail(int(candidate["id"]))
        assert detail is not None
        self.assertEqual(detail["role_matches"][0]["recommended_action"], "priority_outreach")
        self.assertIn("SaaS", detail["role_matches"][0]["evidence_json"])
        events = self.repository.list_candidate_role_status_events(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
        )
        self.assertEqual([event["to_status"] for event in reversed(events)], ["collected", "screened"])
        uncontacted = self.repository.list_candidate_role_matches(
            role_id=int(profile.id),
            recruitment_statuses=["uncontacted"],
            minimum_rating="SSR",
        )
        self.assertEqual(len(uncontacted), 1)

        self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            to_status="contacted",
            operator="tester",
            reason_code="priority_candidate",
            note="Reached out on WeChat",
        )
        self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            to_status="replied",
            operator="tester",
        )
        funnel = self.repository.get_recruitment_funnel_counts(
            role_id=int(profile.id),
            minimum_rating="SSR",
            screened_since="2000-01-01T00:00:00",
        )
        self.assertEqual(funnel["screened"], 1)
        self.assertEqual(funnel["contacted"], 1)
        self.assertEqual(funnel["replied"], 1)
        replied_candidates = self.repository.list_recruitment_funnel_candidates(
            role_id=int(profile.id),
            status="replied",
            rating="SSR",
            screened_since="2000-01-01T00:00:00",
        )
        self.assertEqual(len(replied_candidates), 1)
        self.assertEqual(replied_candidates[0]["name"], "Taylor")
        self.assertEqual(replied_candidates[0]["funnel_status"], "replied")
        self.assertEqual(replied_candidates[0]["latest_rating"], "SSR")
        contacted_candidates = self.repository.list_recruitment_funnel_candidates(
            role_id=int(profile.id),
            status="contacted",
            minimum_rating="SSR",
            screened_since="2000-01-01T00:00:00",
        )
        self.assertEqual([row["name"] for row in contacted_candidates], ["Taylor"])
        future_replied_candidates = self.repository.list_recruitment_funnel_candidates(
            role_id=int(profile.id),
            status="replied",
            rating="SSR",
            screened_since="9999-01-01T00:00:00",
        )
        self.assertEqual(future_replied_candidates, [])
        reason_counts = [
            dict(row)
            for row in self.repository.get_recruitment_reason_counts(
                role_id=int(profile.id),
                minimum_rating="SSR",
                screened_since="2000-01-01T00:00:00",
            )
        ]
        self.assertEqual(
            [(row["reason_code"], row["count"]) for row in reason_counts],
            [("priority_candidate", 1)],
        )
        future_funnel = self.repository.get_recruitment_funnel_counts(
            role_id=int(profile.id),
            minimum_rating="SSR",
            screened_since="9999-01-01T00:00:00",
        )
        self.assertEqual(future_funnel["screened"], 0)
        self.assertEqual(future_funnel["contacted"], 0)
        self.assertEqual(future_funnel["replied"], 0)
        future_reason_counts = self.repository.get_recruitment_reason_counts(
            role_id=int(profile.id),
            minimum_rating="SSR",
            screened_since="9999-01-01T00:00:00",
        )
        self.assertEqual(future_reason_counts, [])
        uncontacted_after_reply = self.repository.list_candidate_role_matches(
            role_id=int(profile.id),
            recruitment_statuses=["uncontacted"],
            minimum_rating="SSR",
        )
        self.assertEqual(uncontacted_after_reply, [])
        searched = self.repository.list_candidate_role_matches(
            role_id=int(profile.id),
            match_statuses=["ai_screened"],
            recruitment_statuses=["replied"],
            minimum_rating="SSR",
            query="Taylor",
        )
        detail = self.repository.get_candidate_detail(int(candidate["id"]))
        assert detail is not None
        self.assertEqual(len(searched), 1)
        self.assertEqual(searched[0]["id"], int(candidate["id"]))
        self.assertEqual(len(detail["role_matches"]), 1)
        self.assertEqual(detail["role_matches"][0]["latest_rating"], "SSR")
        self.assertEqual(detail["role_matches"][0]["recruitment_status"], "replied")
        self.assertEqual(detail["status_events"][0]["to_status"], "replied")

    def test_ai_rating_conversion_counts_group_recruitment_outcomes(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        candidates = [
            self._candidate("platform:conversion-ssr", "Sasha"),
            self._candidate("platform:conversion-sr", "Morgan"),
            self._candidate("platform:conversion-r", "Jordan"),
        ]
        self.repository.upsert_batch_candidates(batch.id, candidates)
        candidate_rows = {
            str(row["candidate_key"]): dict(row)
            for row in self.repository.list_candidates()
            if str(row["candidate_key"]).startswith("platform:conversion-")
        }
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Sales",
            batch_id=batch.id,
            provider="fake",
            model="fake-model",
            total_candidates=3,
        )
        ordered_candidates = [
            candidate_rows["platform:conversion-ssr"],
            candidate_rows["platform:conversion-sr"],
            candidate_rows["platform:conversion-r"],
        ]
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=ordered_candidates,
            model_name="fake-model",
            prompt_version="v1",
            request_hashes={
                int(candidate["id"]): f"hash-{candidate['candidate_key']}"
                for candidate in ordered_candidates
            },
        )
        ratings = {
            int(candidate_rows["platform:conversion-ssr"]["id"]): "SSR",
            int(candidate_rows["platform:conversion-sr"]["id"]): "SR",
            int(candidate_rows["platform:conversion-r"]["id"]): "R",
        }
        while True:
            task = self.repository.claim_next_screening_task(run_id)
            if task is None:
                break
            candidate_id = int(task["candidate_id"])
            result_id = self.repository.save_screening_result(
                ScreeningResult(
                    run_id=run_id,
                    candidate_id=candidate_id,
                    rating=ratings[candidate_id],
                    persona="conversion test",
                    confidence="high",
                )
            )
            self.repository.mark_screening_task_success(int(task["task_id"]), result_id)

        ssr_id = int(candidate_rows["platform:conversion-ssr"]["id"])
        sr_id = int(candidate_rows["platform:conversion-sr"]["id"])
        self.repository.record_candidate_role_status_change(
            candidate_id=ssr_id,
            role_id=int(profile.id),
            to_status="contacted",
            operator="tester",
            reason_code="priority_candidate",
        )
        for status in ["replied", "interviewing", "offer", "hired"]:
            self.repository.record_candidate_role_status_change(
                candidate_id=ssr_id,
                role_id=int(profile.id),
                to_status=status,
                operator="tester",
            )
        self.repository.record_candidate_role_status_change(
            candidate_id=sr_id,
            role_id=int(profile.id),
            to_status="contacted",
            operator="tester",
        )
        self.repository.record_candidate_role_status_change(
            candidate_id=sr_id,
            role_id=int(profile.id),
            to_status="rejected",
            operator="tester",
            reason_code="skill_gap",
        )

        rows = {
            str(row["rating"]): dict(row)
            for row in self.repository.get_ai_rating_conversion_counts(
                role_id=int(profile.id),
                minimum_rating="N",
                screened_since="2000-01-01T00:00:00",
            )
        }

        self.assertEqual(set(rows), {"SSR", "SR", "R"})
        self.assertEqual(rows["SSR"]["screened_count"], 1)
        self.assertEqual(rows["SSR"]["contacted_count"], 1)
        self.assertEqual(rows["SSR"]["replied_count"], 1)
        self.assertEqual(rows["SSR"]["interviewing_count"], 1)
        self.assertEqual(rows["SSR"]["offer_count"], 1)
        self.assertEqual(rows["SSR"]["hired_count"], 1)
        self.assertEqual(rows["SSR"]["rejected_count"], 0)
        self.assertEqual(rows["SR"]["screened_count"], 1)
        self.assertEqual(rows["SR"]["contacted_count"], 1)
        self.assertEqual(rows["SR"]["rejected_count"], 1)
        self.assertEqual(rows["R"]["screened_count"], 1)
        self.assertEqual(rows["R"]["contacted_count"], 0)

        high_rating_rows = self.repository.get_ai_rating_conversion_counts(
            role_id=int(profile.id),
            minimum_rating="SSR",
            screened_since="2000-01-01T00:00:00",
        )
        self.assertEqual([row["rating"] for row in high_rating_rows], ["SSR"])
        high_rating_summary = self.repository.get_ai_rating_cohort_summary(
            role_id=int(profile.id),
            minimum_rating="SSR",
            screened_since="2000-01-01T00:00:00",
        )
        self.assertEqual(high_rating_summary["screened_count"], 1)
        self.assertEqual(high_rating_summary["contacted_count"], 1)
        self.assertEqual(high_rating_summary["replied_count"], 1)
        self.assertEqual(high_rating_summary["interviewing_count"], 1)
        self.assertEqual(high_rating_summary["offer_count"], 1)
        self.assertEqual(high_rating_summary["hired_count"], 1)
        self.assertEqual(high_rating_summary["rejected_count"], 0)
        broad_summary = self.repository.get_ai_rating_cohort_summary(
            role_id=int(profile.id),
            minimum_rating="N",
            screened_since="2000-01-01T00:00:00",
        )
        self.assertEqual(broad_summary["screened_count"], 3)
        self.assertEqual(broad_summary["contacted_count"], 2)
        self.assertEqual(broad_summary["replied_count"], 1)
        self.assertEqual(broad_summary["rejected_count"], 1)
        future_rows = self.repository.get_ai_rating_conversion_counts(
            role_id=int(profile.id),
            minimum_rating="N",
            screened_since="9999-01-01T00:00:00",
        )
        self.assertEqual(future_rows, [])
        future_summary = self.repository.get_ai_rating_cohort_summary(
            role_id=int(profile.id),
            minimum_rating="N",
            screened_since="9999-01-01T00:00:00",
        )
        self.assertEqual(future_summary["screened_count"], 0)

    def test_low_confidence_or_risky_results_enter_manual_review_queue(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(batch.id, [self._candidate("platform:6", "Riley")])
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Sales",
            batch_id=None,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=[candidate],
            model_name="fake-model",
            prompt_version="v1",
            request_hashes={int(candidate["id"]): "hash"},
        )
        task = self.repository.claim_next_screening_task(run_id)
        assert task is not None
        result_id = self.repository.save_screening_result(
            ScreeningResult(
                run_id=run_id,
                candidate_id=int(candidate["id"]),
                rating="SR",
                persona="Relevant but evidence is thin.",
                confidence="low",
                risk_json='["岗位变动频繁"]',
                recommended_action="manual_check",
            )
        )
        self.repository.mark_screening_task_success(int(task["task_id"]), result_id)

        rows = self.repository.list_manual_review_candidates(role_id=int(profile.id))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Riley")
        self.assertEqual(rows[0]["latest_confidence"], "low")
        self.assertEqual(rows[0]["recommended_action"], "manual_check")
        quality_summary = self.repository.get_manual_review_quality_summary(
            role_id=int(profile.id),
            minimum_rating="SR",
            screened_since="2000-01-01T00:00:00",
        )
        self.assertEqual(quality_summary["active_total"], 1)
        self.assertEqual(quality_summary["manual_review_total"], 1)
        self.assertEqual(quality_summary["low_confidence"], 1)
        self.assertEqual(quality_summary["model_manual_action"], 1)
        self.assertEqual(quality_summary["risky"], 1)
        self.assertIn(rows[0]["review_reason"], {"模型置信度低", "模型建议人工确认"})

        event_id = self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            to_status="priority_outreach",
            operator="tester",
            reason_code="manual_review_passed",
            note="Reviewer approved outreach.",
        )
        remaining_rows = self.repository.list_manual_review_candidates(role_id=int(profile.id))
        matches = self.repository.list_candidate_role_matches(
            role_id=int(profile.id),
            recruitment_statuses=["priority_outreach"],
        )
        events = self.repository.list_candidate_role_status_events(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
        )

        self.assertGreater(event_id, 0)
        self.assertEqual(remaining_rows, [])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["human_decision"], "manual_review_passed")
        self.assertEqual(events[0]["to_status"], "priority_outreach")
        cleared_summary = self.repository.get_manual_review_quality_summary(role_id=int(profile.id))
        self.assertEqual(cleared_summary["active_total"], 0)
        self.assertEqual(cleared_summary["manual_review_total"], 0)

    def test_failed_ai_tasks_enter_manual_review_queue(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(batch.id, [self._candidate("platform:ai-failed", "Blake")])
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        run_id = self.repository.create_screening_run(
            profile_id=int(profile.id),
            source_job_title="Sales",
            batch_id=batch.id,
            provider="fake",
            model="fake-model",
            total_candidates=1,
        )
        self.repository.create_screening_tasks(
            run_id=run_id,
            role_id=int(profile.id),
            candidates=[candidate],
            model_name="fake-model",
            prompt_version="v1",
            request_hashes={int(candidate["id"]): "hash"},
            max_retry_count=0,
        )
        task = self.repository.claim_next_screening_task(run_id)
        assert task is not None
        self.repository.mark_screening_task_failure(int(task["task_id"]), "provider timeout")

        rows = self.repository.list_manual_review_candidates(role_id=int(profile.id))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Blake")
        self.assertEqual(rows[0]["match_status"], "ai_failed")
        self.assertEqual(rows[0]["review_reason"], "AI筛选失败")
        self.assertEqual(rows[0]["task_error"], "provider timeout")
        self.assertEqual(rows[0]["retry_count"], 1)
        self.assertEqual(rows[0]["max_retry_count"], 0)
        self.assertTrue(rows[0]["task_updated_at"])
        quality_summary = self.repository.get_manual_review_quality_summary(role_id=int(profile.id))
        self.assertEqual(quality_summary["active_total"], 1)
        self.assertEqual(quality_summary["manual_review_total"], 1)
        self.assertEqual(quality_summary["ai_failed"], 1)

    def test_recruitment_reason_code_must_be_standardized(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(batch.id, [self._candidate("platform:7", "Jamie")])
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )

        with self.assertRaises(ValueError):
            self.repository.record_candidate_role_status_change(
                candidate_id=int(candidate["id"]),
                role_id=int(profile.id),
                to_status="rejected",
                operator="tester",
                reason_code="random_free_text",
            )

        event_id = self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            to_status="rejected",
            operator="tester",
            reason_code="skill_gap",
        )
        events = self.repository.list_candidate_role_status_events(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
        )

        self.assertGreater(event_id, 0)
        self.assertEqual(events[0]["reason_code"], "skill_gap")

    def test_later_reason_codes_do_not_overwrite_manual_review_decision(self) -> None:
        batch = self.repository.create_batch("Sales", "https://example.com")
        self.repository.upsert_batch_candidates(batch.id, [self._candidate("platform:decision", "Dana")])
        candidate = dict(self.repository.list_candidates()[0])
        profile = self.repository.save_screening_profile(
            ScreeningProfile(job_title="Sales", jd_text="SaaS", prompt_text="screen SaaS")
        )
        self.repository.upsert_candidate_role_match(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            latest_rating="SR",
            latest_confidence="low",
            match_status="ai_screened",
            recruitment_status="screened",
        )

        self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            to_status="priority_outreach",
            operator="reviewer",
            reason_code="manual_review_passed",
        )
        self.repository.record_candidate_role_status_change(
            candidate_id=int(candidate["id"]),
            role_id=int(profile.id),
            to_status="rejected",
            operator="recruiter",
            reason_code="candidate_unresponsive",
        )

        matches = self.repository.list_candidate_role_matches(role_id=int(profile.id))
        reason_counts = {
            str(row["reason_code"]): int(row["count"])
            for row in self.repository.get_recruitment_reason_counts(
                role_id=int(profile.id),
                minimum_rating="N",
                screened_since="2000-01-01T00:00:00",
            )
        }
        self.assertEqual(matches[0]["human_decision"], "manual_review_passed")
        self.assertEqual(matches[0]["recruitment_status"], "rejected")
        self.assertEqual(reason_counts["candidate_unresponsive"], 1)
        self.assertEqual(reason_counts["manual_review_passed"], 1)


if __name__ == "__main__":
    unittest.main()
