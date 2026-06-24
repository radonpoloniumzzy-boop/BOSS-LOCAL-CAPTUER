from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai.prompt_manager import PromptManager
from ai.schemas import ScreeningDecision
from ai.screening_service import ScreeningService
from automation.importer import CardImportService
from automation.parser import CandidateParser
from core.models import ScreeningProfile
from storage.db import DatabaseManager
from storage.repository import CandidateRepository


class RatingProvider:
    def screen(self, _system_prompt: str, candidate_text: str) -> ScreeningDecision:
        rating = "UR" if "Alice" in candidate_text else "R"
        return ScreeningDecision(
            rating=rating,
            persona=f"{rating} 自动化测试画像",
            raw_response=f'{{"rating":"{rating}","persona":"test"}}',
        )


class AutomationPipelineTest(unittest.TestCase):
    def test_imported_batch_is_screened_and_ranked_as_automation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db = DatabaseManager(Path(tmp_dir) / "automation.db")
            db.initialize()
            repository = CandidateRepository(db)
            importer = CardImportService(repository, CandidateParser())
            import_result = importer.import_cards(
                {
                    "job_title": "Java工程师",
                    "source_url": "https://www.zhipin.com/web/geek/recommend",
                    "cards": [
                        {
                            "raw_card_text": "Bob Java 本科",
                            "name": "Bob",
                            "detail_url": "https://www.zhipin.com/geek/bob",
                        },
                        {
                            "raw_card_text": "Alice Java Spring Cloud 本科",
                            "name": "Alice",
                            "detail_url": "https://www.zhipin.com/geek/alice",
                        },
                    ],
                }
            )
            prompt_manager = PromptManager(Path(tmp_dir) / "prompts")
            prompt = prompt_manager.build_from_jd("Java工程师", "熟悉 Java 和 Spring Cloud")
            profile = repository.save_screening_profile(
                ScreeningProfile(
                    job_title="Java工程师",
                    jd_text="熟悉 Java 和 Spring Cloud",
                    prompt_text=prompt,
                    prompt_source="generated",
                )
            )
            candidates = repository.list_screening_candidates(
                batch_id=int(import_result["batch_id"])
            )
            service = ScreeningService(
                repository=repository,
                prompt_manager=prompt_manager,
                provider=RatingProvider(),
            )

            screening_result = service.run(
                profile=profile.to_dict(),
                candidates=candidates,
                source_job_title="Java工程师",
                batch_id=int(import_result["batch_id"]),
                provider_name="fake",
                model="fake-model",
                origin="automation",
            )

            rows = repository.list_screening_results(int(screening_result["run_id"]))
            runs = repository.list_screening_runs(origin="automation")
            self.assertEqual([row["rating"] for row in rows], ["UR", "R"])
            self.assertEqual(runs[0]["batch_id"], import_result["batch_id"])
            db.close_thread_connection()


if __name__ == "__main__":
    unittest.main()
