from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.utils import normalize_multiline_text, normalize_text
from talent.role_taxonomy import RoleTaxonomy


@dataclass(slots=True)
class RoleRequirements:
    min_years: int | None = None
    job_family: str = ""
    job_track: str = ""
    city_terms: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)
    preferred_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "min_years": self.min_years,
            "job_family": self.job_family,
            "job_track": self.job_track,
            "city_terms": list(self.city_terms),
            "required_terms": list(self.required_terms),
            "preferred_terms": list(self.preferred_terms),
        }


class RoleRequirementExtractor:
    city_terms = [
        "北京",
        "上海",
        "深圳",
        "广州",
        "杭州",
        "成都",
        "武汉",
        "南京",
        "苏州",
        "西安",
        "重庆",
        "天津",
        "长沙",
        "郑州",
        "Shenzhen",
        "Shanghai",
        "Beijing",
        "Guangzhou",
        "Hangzhou",
        "Chengdu",
    ]
    domain_terms = [
        "B2B",
        "B2C",
        "SaaS",
        "CRM",
        "ERP",
        "KA",
        "BD",
        "AI",
        "Java",
        "Python",
        "React",
        "Vue",
        "SQL",
        "渠道",
        "招商",
        "大客户",
        "解决方案",
        "企业服务",
        "电商",
        "教育",
        "金融",
        "证券",
        "证券交易",
        "交易员",
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
        "物流",
        "医疗",
        "房地产",
        "内容运营",
        "用户运营",
        "数据分析",
    ]
    preferred_markers = (
        "优先",
        "加分",
        "nice to have",
        "preferred",
        "plus",
    )

    def __init__(self, role_taxonomy: RoleTaxonomy | None = None) -> None:
        self.role_taxonomy = role_taxonomy or RoleTaxonomy()

    def from_profile(self, profile: dict[str, object]) -> RoleRequirements:
        text = normalize_multiline_text(
            "\n".join(
                [
                    str(profile.get("job_title") or ""),
                    str(profile.get("jd_text") or ""),
                ]
            )
        )
        job_family, job_track = self.role_taxonomy.classify(text)
        return RoleRequirements(
            min_years=self.extract_years(text),
            job_family=job_family,
            job_track=job_track,
            city_terms=self.extract_cities(text),
            required_terms=self.extract_required_terms(text),
            preferred_terms=self.extract_preferred_terms(text),
        )

    def extract_cities(self, text: str) -> list[str]:
        return self._extract_terms(text, self.city_terms)

    def extract_role_terms(self, text: str) -> list[str]:
        return self._extract_terms(text, self._domain_terms())

    def extract_required_terms(self, text: str) -> list[str]:
        all_terms = self.extract_role_terms(text)
        preferred = set(self.extract_preferred_terms(text))
        return [term for term in all_terms if term not in preferred]

    def extract_preferred_terms(self, text: str) -> list[str]:
        found: list[str] = []
        for line in normalize_multiline_text(text).splitlines():
            lowered = line.lower()
            if not any(marker in lowered for marker in self.preferred_markers):
                continue
            for term in self._extract_terms(line, self._domain_terms()):
                if term not in found:
                    found.append(term)
        return found

    def extract_years(self, text: str) -> int | None:
        normalized = normalize_text(text)
        candidates: list[int] = []
        patterns = [
            r"(?:至少|不少于|不低于|minimum|min\.?|at least)\s*(\d{1,2})\s*(?:年|years?|yrs?)",
            r"(\d{1,2})\s*(?:年|years?|yrs?)\s*(?:以上|\+|及以上|or more|minimum|min\.?)",
            r"(\d{1,2})\s*(?:\+)\s*(?:年|years?|yrs?)?",
            r"(\d{1,2})\s*(?:年|years?|yrs?)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
                value = int(match.group(1))
                if 0 <= value <= 50:
                    candidates.append(value)
        return max(candidates) if candidates else None

    def _extract_terms(self, text: str, terms: list[str]) -> list[str]:
        found: list[str] = []
        lowered = text.lower()
        for term in terms:
            if term.lower() in lowered and term not in found:
                found.append(term)
        return found

    def _domain_terms(self) -> list[str]:
        terms: list[str] = []
        for term in [*self.domain_terms, *self.role_taxonomy.vocabulary()]:
            if term not in terms:
                terms.append(term)
        return terms
