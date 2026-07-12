from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ai.role_requirements import RoleRequirementExtractor
from core.utils import normalize_multiline_text, normalize_text
from talent.role_taxonomy import EvidencePolicy


PASS_TO_AI = "pass_to_ai"
MANUAL_CHECK = "manual_check"
HOLD = "hold"

ROUTES = {PASS_TO_AI, MANUAL_CHECK, HOLD}


@dataclass(slots=True)
class PrescreenDecision:
    route: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RulePrescreener:
    """Conservative pre-screening that routes sparse records without rejecting candidates."""

    signal_fields = (
        "work_experience_text",
        "education_text",
        "tags_text",
        "summary_text",
        "raw_card_text",
    )
    def __init__(self, requirement_extractor: RoleRequirementExtractor | None = None) -> None:
        self.requirement_extractor = requirement_extractor or RoleRequirementExtractor()

    def evaluate(self, candidate: dict[str, object], profile: dict[str, object]) -> PrescreenDecision:
        text = self._candidate_text(candidate)
        signal_count = self._signal_count(candidate)
        has_name = bool(normalize_text(str(candidate.get("name") or "")))
        requirements = self.requirement_extractor.from_profile(profile)
        candidate_cities = self.requirement_extractor.extract_cities(text)
        candidate_years = self.requirement_extractor.extract_years(text)
        candidate_terms = self.requirement_extractor.extract_role_terms(text)
        missing_required_terms = [
            term for term in requirements.required_terms if term not in candidate_terms
        ]
        role_track = self.requirement_extractor.role_taxonomy.get_track(
            requirements.job_family,
            requirements.job_track,
        )
        evidence_details = self._evaluate_evidence_policy(
            role_track.evidence_policy if role_track else None,
            text,
        )
        keyword_signal = (
            bool(evidence_details["keyword_signal"])
            if evidence_details
            else bool(set(requirements.required_terms).intersection(candidate_terms))
        )

        details = {
            "text_length": len(text),
            "signal_count": signal_count,
            "has_name": has_name,
            "role_requirements": requirements.to_dict(),
            "candidate_cities": candidate_cities,
            "candidate_years": candidate_years,
            "candidate_terms": candidate_terms,
            "missing_required_terms": missing_required_terms,
            "keyword_signal": keyword_signal,
        }
        details.update(evidence_details)
        if len(text) < 8:
            return PrescreenDecision(
                route=HOLD,
                reason="no_meaningful_candidate_text",
                details=details,
            )
        if not has_name and (signal_count < 2 or len(text) < 80):
            return PrescreenDecision(
                route=MANUAL_CHECK,
                reason="insufficient_candidate_evidence",
                details=details,
            )
        if requirements.city_terms and not candidate_cities:
            return PrescreenDecision(
                route=MANUAL_CHECK,
                reason="missing_role_city",
                details=details,
            )
        if requirements.city_terms and candidate_cities:
            if not set(requirements.city_terms).intersection(candidate_cities):
                return PrescreenDecision(
                    route=HOLD,
                    reason="role_city_mismatch",
                    details=details,
                )
        if requirements.min_years is not None and candidate_years is None:
            return PrescreenDecision(
                route=MANUAL_CHECK,
                reason="missing_role_years",
                details=details,
            )
        if (
            requirements.min_years is not None
            and candidate_years is not None
            and candidate_years < requirements.min_years
        ):
            return PrescreenDecision(
                route=HOLD,
                reason="role_years_below_minimum",
                details=details,
            )
        if requirements.required_terms and not keyword_signal:
            return PrescreenDecision(
                route=MANUAL_CHECK,
                reason=str(
                    evidence_details.get("route_reason") or "missing_role_keywords"
                ),
                details=details,
            )
        return PrescreenDecision(
            route=PASS_TO_AI,
            reason=str(
                evidence_details.get("route_reason") or "sufficient_candidate_evidence"
            ),
            details=details,
        )

    def _candidate_text(self, candidate: dict[str, object]) -> str:
        values = [str(candidate.get(field) or "") for field in self.signal_fields]
        return normalize_multiline_text("\n".join(values))

    def _signal_count(self, candidate: dict[str, object]) -> int:
        count = 0
        for field in self.signal_fields:
            value = normalize_text(str(candidate.get(field) or ""))
            if len(value) >= 8:
                count += 1
        return count

    @staticmethod
    def _evaluate_evidence_policy(
        policy: EvidencePolicy | None,
        candidate_text: str,
    ) -> dict[str, object]:
        if policy is None:
            return {}

        text = normalize_text(candidate_text).lower()

        def matched(terms: tuple[str, ...]) -> list[str]:
            return [term for term in terms if term.lower() in text]

        direct = matched(policy.direct_evidence)
        market = matched(policy.market_terms)
        action = matched(policy.action_terms)
        exclusions = matched(policy.exclusion_terms)
        keyword_signal = bool(direct or (market and action and not exclusions))
        route_reason = policy.matched_reason if keyword_signal else policy.unmatched_reason
        return {
            "evidence_policy": policy.name,
            "matched_direct_evidence": direct,
            "matched_market_terms": market,
            "matched_action_terms": action,
            "matched_exclusion_terms": exclusions,
            "keyword_signal": keyword_signal,
            "route_reason": route_reason,
        }
