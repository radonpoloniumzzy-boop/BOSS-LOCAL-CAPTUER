from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from ai.prescreen import HOLD, MANUAL_CHECK, PASS_TO_AI, RulePrescreener
from talent.profile_builder import StandardProfileBuilder


@dataclass(slots=True)
class CalibrationSampler:
    prescreener: RulePrescreener
    profile_builder: StandardProfileBuilder

    def build_sample(
        self,
        *,
        profile: dict[str, object],
        candidates: list[dict[str, object]],
        sample_size: int = 50,
    ) -> dict[str, object]:
        rows = [self._row(profile, candidate) for candidate in candidates]
        sample = self._stratified_sample(rows, sample_size)
        return {
            "summary": self._summary(sample),
            "rows": sample,
            "manual_metrics": self.manual_metrics(sample),
        }

    def manual_metrics(self, rows: list[dict[str, object]]) -> dict[str, object]:
        route_reviewed = [
            row
            for row in rows
            if str(row.get("manual_route_judgment") or "").strip()
        ]
        profile_reviewed = [
            row
            for row in rows
            if str(row.get("manual_profile_judgment") or "").strip()
        ]
        reviewed = [
            row
            for row in rows
            if str(row.get("manual_route_judgment") or "").strip()
            or str(row.get("manual_profile_judgment") or "").strip()
        ]
        route_errors = [
            row
            for row in route_reviewed
            if str(row.get("manual_route_judgment") or "").strip()
            in {"false_hold", "false_manual_check", "false_pass_to_ai"}
        ]
        profile_errors = [
            row
            for row in profile_reviewed
            if str(row.get("manual_profile_judgment") or "").strip()
            in {"wrong_city", "wrong_years", "wrong_track", "wrong_tags"}
        ]
        reviewed_count = len(reviewed)
        return {
            "reviewed_count": reviewed_count,
            "route_reviewed_count": len(route_reviewed),
            "profile_reviewed_count": len(profile_reviewed),
            "route_error_count": len(route_errors),
            "profile_error_count": len(profile_errors),
            "route_error_rate": self._rate(len(route_errors), len(route_reviewed)),
            "profile_error_rate": self._rate(len(profile_errors), len(profile_reviewed)),
        }

    def _row(self, profile: dict[str, object], candidate: dict[str, object]) -> dict[str, object]:
        decision = self.prescreener.evaluate(candidate, profile)
        standard_profile = self.profile_builder.build(candidate)
        flags = self._review_flags(decision.route, standard_profile)
        return {
            "candidate_id": int(candidate["id"]),
            "name": str(candidate.get("name") or ""),
            "raw_card_text": str(candidate.get("raw_card_text") or ""),
            "prescreen_route": decision.route,
            "prescreen_reason": decision.reason,
            "prescreen_details": decision.details,
            "city": standard_profile.get("city") or "",
            "years_experience": standard_profile.get("years_experience"),
            "job_family": standard_profile.get("job_family") or "",
            "job_track": standard_profile.get("job_track") or "",
            "industry_tags": list(standard_profile.get("industry_tags") or []),
            "skill_tags": list(standard_profile.get("skill_tags") or []),
            "profile_completeness": int(standard_profile.get("profile_completeness") or 0),
            "parser_version": str(standard_profile.get("parser_version") or ""),
            "review_flags": flags,
            "review_priority": bool(flags),
            "manual_route_judgment": "",
            "manual_profile_judgment": "",
            "manual_notes": "",
        }

    def _review_flags(
        self,
        route: str,
        standard_profile: dict[str, Any],
    ) -> list[str]:
        flags: list[str] = []
        if route in {HOLD, MANUAL_CHECK}:
            flags.append(f"route:{route}")
        if int(standard_profile.get("profile_completeness") or 0) < 60:
            flags.append("profile:low_completeness")
        if not standard_profile.get("city"):
            flags.append("profile:missing_city")
        if standard_profile.get("years_experience") is None:
            flags.append("profile:missing_years")
        if not standard_profile.get("job_track"):
            flags.append("profile:missing_track")
        return flags

    def _stratified_sample(
        self,
        rows: list[dict[str, object]],
        sample_size: int,
    ) -> list[dict[str, object]]:
        if sample_size <= 0 or len(rows) <= sample_size:
            return rows
        selected: list[dict[str, object]] = []
        buckets = {
            HOLD: [row for row in rows if row["prescreen_route"] == HOLD],
            MANUAL_CHECK: [row for row in rows if row["prescreen_route"] == MANUAL_CHECK],
            PASS_TO_AI: [row for row in rows if row["prescreen_route"] == PASS_TO_AI],
        }
        per_bucket = max(1, sample_size // len(buckets))
        for route in [HOLD, MANUAL_CHECK, PASS_TO_AI]:
            selected.extend(buckets[route][:per_bucket])
        if len(selected) < sample_size:
            selected_ids = {int(row["candidate_id"]) for row in selected}
            for row in rows:
                if int(row["candidate_id"]) in selected_ids:
                    continue
                selected.append(row)
                if len(selected) >= sample_size:
                    break
        return selected[:sample_size]

    def _summary(self, rows: list[dict[str, object]]) -> dict[str, object]:
        route_counts = Counter(str(row["prescreen_route"]) for row in rows)
        reason_counts = Counter(str(row["prescreen_reason"]) for row in rows)
        flag_counts = Counter(
            flag
            for row in rows
            for flag in list(row.get("review_flags") or [])
        )
        completeness_values = [int(row.get("profile_completeness") or 0) for row in rows]
        return {
            "sample_size": len(rows),
            "route_counts": dict(route_counts),
            "reason_counts": dict(reason_counts),
            "review_priority_count": sum(1 for row in rows if row.get("review_priority")),
            "flag_counts": dict(flag_counts),
            "average_profile_completeness": round(
                sum(completeness_values) / len(completeness_values),
                2,
            )
            if completeness_values
            else 0.0,
        }

    @staticmethod
    def _rate(count: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round(count / total, 4)
