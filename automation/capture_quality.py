from __future__ import annotations

from storage.repository import CandidateRepository


class CaptureQualityService:
    def __init__(self, repository: CandidateRepository) -> None:
        self.repository = repository

    def check_task(self, task_id: int) -> dict[str, object]:
        task = self.repository.get_recruitment_task(task_id)
        if task is None:
            raise ValueError("招聘任务不存在")
        batch = self.repository.get_latest_capture_batch_for_task(task_id)
        if batch is None:
            target_candidates = max(0, int(task.get("target_candidates") or 0))
            return {
                "task_id": task_id,
                "batch_id": None,
                "decision": "needs_collection",
                "decision_label": "尚未采集",
                "total_collected": 0,
                "unique_candidates": 0,
                "new_candidates": 0,
                "duplicate_count": 0,
                "duplicate_rate": 0,
                "core_completeness": 0,
                "source_consistency": 0,
                "task_candidate_count": 0,
                "target_candidates": target_candidates,
                "target_gap": target_candidates,
                "issues": ["还没有采集批次"],
            }
        metrics = self.repository.get_capture_batch_quality_metrics(int(batch["id"]))
        summary = self.repository.get_recruitment_task_summary(task_id)
        unique_candidates = int(metrics["unique_candidates"] or 0)
        total_collected = max(int(metrics.get("total_collected") or 0), unique_candidates)
        total_new = max(0, int(metrics.get("new_candidates") or 0))
        duplicate_count = max(0, total_collected - total_new)
        duplicate_rate = self._percentage(duplicate_count, total_collected)
        core_completeness = self._percentage(int(metrics["core_complete"] or 0), unique_candidates)
        source_consistency = self._percentage(int(metrics["source_consistent"] or 0), unique_candidates)
        target_candidates = max(0, int(task.get("target_candidates") or 0))
        task_candidate_count = int(summary.get("candidate_count") or 0)
        target_gap = max(0, target_candidates - task_candidate_count)
        batch_status = str(metrics.get("status") or "")
        issues: list[str] = []
        if unique_candidates == 0:
            issues.append("本批次没有可用候选人")
        core_below_80 = int(metrics["core_complete"] or 0) * 100 < 80 * unique_candidates
        core_below_60 = int(metrics["core_complete"] or 0) * 100 < 60 * unique_candidates
        source_mismatch = int(metrics["source_consistent"] or 0) < unique_candidates
        high_duplicate_rate = (
            total_collected > 0 and duplicate_count * 100 >= 50 * total_collected
        )
        if core_below_80:
            issues.append(f"核心字段完整度仅 {core_completeness}%")
        if source_mismatch:
            issues.append(f"来源一致率仅 {source_consistency}%")
        if high_duplicate_rate:
            issues.append(f"重复率达到 {duplicate_rate}%")
        if target_gap > 0:
            issues.append(f"距离任务目标还差 {target_gap} 人")

        if batch_status == "running":
            decision, decision_label = "collecting", "采集中，完成后检查"
        elif (
            batch_status != "completed"
            or unique_candidates == 0
            or core_below_60
            or source_mismatch
        ):
            decision, decision_label = "needs_review", "需要人工检查"
        elif core_below_80 or high_duplicate_rate or target_gap > 0:
            decision, decision_label = "needs_supplement", "建议补充采集"
        else:
            decision, decision_label = "ready", "可进入 AI 初筛"
        return {
            "task_id": task_id,
            "batch_id": int(batch["id"]),
            "batch_status": batch_status,
            "decision": decision,
            "decision_label": decision_label,
            "total_collected": total_collected,
            "unique_candidates": unique_candidates,
            "new_candidates": total_new,
            "duplicate_count": duplicate_count,
            "duplicate_rate": duplicate_rate,
            "core_completeness": core_completeness,
            "source_consistency": source_consistency,
            "task_candidate_count": task_candidate_count,
            "target_candidates": target_candidates,
            "target_gap": target_gap,
            "issues": issues,
        }

    @staticmethod
    def _percentage(numerator: int, denominator: int) -> int | float:
        if denominator <= 0:
            return 0
        value = round(max(0, numerator) * 100 / denominator, 1)
        return int(value) if value.is_integer() else value
