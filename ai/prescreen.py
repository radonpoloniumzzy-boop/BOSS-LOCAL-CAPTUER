from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ai.role_requirements import RoleRequirementExtractor
from core.utils import normalize_multiline_text, normalize_text


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
    finance_trading_role_terms = (
        "证券交易员",
        "交易员",
        "股票交易员",
        "期货交易员",
        "操盘手",
        "证券",
        "股票",
        "期货",
        "账户操作",
        "行情",
        "投资",
        "资管",
    )
    finance_market_terms = (
        "金融",
        "证券",
        "股票",
        "期货",
        "基金",
        "私募",
        "资管",
        "投资",
        "A股",
        "港股",
        "美股",
        "债券",
        "可转债",
        "ETF",
        "期权",
        "外汇",
        "量化",
    )
    finance_trading_action_terms = (
        "交易",
        "下单",
        "买卖",
        "操盘",
        "账户操作",
        "行情",
        "盘口",
        "止损",
        "风控",
        "盯盘",
        "交易计划",
        "价格波动",
    )
    finance_trading_specific_terms = (
        "证券交易",
        "股票交易",
        "期货交易",
        "基金交易",
        "A股交易",
        "港股交易",
        "美股交易",
        "交易员",
        "操盘手",
        "账户操作",
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
        keyword_signal = self._has_required_keyword_signal(
            profile,
            requirements.to_dict(),
            candidate_terms,
            text,
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
                reason="missing_role_keywords",
                details=details,
            )
        return PrescreenDecision(
            route=PASS_TO_AI,
            reason="sufficient_candidate_evidence",
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

    def _has_required_keyword_signal(
        self,
        profile: dict[str, object],
        requirements: dict[str, object],
        candidate_terms: list[str],
        candidate_text: str,
    ) -> bool:
        required_terms = [str(term) for term in requirements.get("required_terms") or []]
        if not self._is_finance_trading_role(profile, requirements):
            return bool(set(required_terms).intersection(candidate_terms))
        return self._has_finance_trading_candidate_signal(candidate_text)

    def _is_finance_trading_role(
        self,
        profile: dict[str, object],
        requirements: dict[str, object],
    ) -> bool:
        role_text = normalize_multiline_text(
            "\n".join(
                [
                    str(profile.get("job_title") or ""),
                    str(profile.get("jd_text") or ""),
                    str(requirements.get("job_family") or ""),
                    str(requirements.get("job_track") or ""),
                    " ".join(str(term) for term in requirements.get("required_terms") or []),
                ]
            )
        ).lower()
        return any(term.lower() in role_text for term in self.finance_trading_role_terms)

    def _has_finance_trading_candidate_signal(self, candidate_text: str) -> bool:
        text = normalize_text(candidate_text).lower()
        if any(term.lower() in text for term in self.finance_trading_specific_terms):
            return True
        has_market = any(term.lower() in text for term in self.finance_market_terms)
        has_action = any(term.lower() in text for term in self.finance_trading_action_terms)
        has_trading_context = any(
            term.lower() in text
            for term in ("行情判断", "交易计划", "价格波动", "买卖操作", "风控纪律")
        )
        return has_market or (has_action and has_trading_context)
