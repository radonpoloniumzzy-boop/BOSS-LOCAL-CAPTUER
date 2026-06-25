from __future__ import annotations

import re
from typing import Any

from core.utils import normalize_multiline_text, normalize_text
from talent.role_taxonomy import RoleTaxonomy


class StandardProfileBuilder:
    parser_version = "rule:v2"

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
        "青岛",
        "宁波",
        "厦门",
        "合肥",
        "佛山",
        "东莞",
    ]

    industry_terms = [
        "企业服务",
        "SaaS",
        "CRM",
        "电商",
        "教育",
        "金融",
        "物流",
        "医疗",
        "餐饮",
        "房产",
        "制造",
        "AI",
        "人工智能",
        "互联网",
    ]

    skill_terms = [
        "SaaS",
        "CRM",
        "B2B",
        "KA",
        "BD",
        "渠道",
        "招商",
        "大客户",
        "解决方案",
        "Java",
        "Python",
        "Spring Cloud",
        "React",
        "Vue",
        "SQL",
        "数据分析",
        "用户运营",
        "内容运营",
        "项目管理",
    ]

    def __init__(self, role_taxonomy: RoleTaxonomy | None = None) -> None:
        self.role_taxonomy = role_taxonomy or RoleTaxonomy()

    def build(self, candidate: dict[str, object]) -> dict[str, Any]:
        text = self._candidate_text(candidate)
        city = self._extract_city(text)
        years_experience = self._extract_years(text)
        skill_tags = self._extract_terms(text, self._skill_terms())
        industry_tags = self._extract_terms(text, self.industry_terms)
        job_family, job_track = self._classify_job(candidate, text, skill_tags)
        management_experience = self._has_management_experience(text)
        profile = {
            "candidate_id": int(candidate["id"]),
            "name_or_alias": normalize_text(str(candidate.get("name") or "")),
            "city": city,
            "current_title": normalize_text(str(candidate.get("job_title") or "")),
            "job_family": job_family,
            "job_track": job_track,
            "years_experience": years_experience,
            "industry_tags": industry_tags,
            "skill_tags": skill_tags,
            "management_experience": management_experience,
            "salary_range": normalize_text(str(candidate.get("expected_salary") or "")),
            "education": normalize_text(str(candidate.get("education_text") or "")),
            "last_active_at": normalize_text(
                str(candidate.get("capture_time") or candidate.get("updated_at") or "")
            ),
            "parser_version": self.parser_version,
        }
        profile["profile_completeness"] = self._profile_completeness(profile, candidate)
        return profile

    def _candidate_text(self, candidate: dict[str, object]) -> str:
        values = [
            candidate.get("name"),
            candidate.get("job_title"),
            candidate.get("active_status"),
            candidate.get("expected_salary"),
            candidate.get("work_experience_text"),
            candidate.get("education_text"),
            candidate.get("tags_text"),
            candidate.get("summary_text"),
            candidate.get("raw_card_text"),
        ]
        return normalize_multiline_text("\n".join(str(value or "") for value in values))

    def _extract_city(self, text: str) -> str:
        for city in self.city_terms:
            if city in text:
                return city
        return ""

    def _extract_years(self, text: str) -> int | None:
        candidates: list[int] = []
        for pattern in [
            r"(\d{1,2})\s*年",
            r"(\d{1,2})\s*(?:years?|yrs?)",
            r"经验\s*(\d{1,2})",
        ]:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
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

    def _classify_job(
        self,
        candidate: dict[str, object],
        text: str,
        skill_tags: list[str],
    ) -> tuple[str, str]:
        title = normalize_text(str(candidate.get("job_title") or ""))
        combined = f"{title}\n{text}"
        return self.role_taxonomy.classify(combined, skill_tags)
        if any(term in combined for term in ["销售", "BD", "商务", "客户经理", "大客户", "渠道", "招商"]):
            if "SaaS" in skill_tags or "CRM" in skill_tags:
                return "销售", "SaaS销售"
            if "渠道" in combined:
                return "销售", "渠道销售"
            if "招商" in combined:
                return "销售", "招商主管"
            if "大客户" in combined or "KA" in skill_tags:
                return "销售", "KA销售"
            return "销售", "B2B销售"
        if any(term in combined for term in ["运营", "用户运营", "内容运营", "增长"]):
            return "运营", "运营"
        if any(term in combined for term in ["Java", "Python", "前端", "后端", "开发", "工程师"]):
            return "技术", "软件开发"
        return "", ""

    def _skill_terms(self) -> list[str]:
        terms: list[str] = []
        for term in [*self.skill_terms, *self.role_taxonomy.vocabulary()]:
            if term not in terms:
                terms.append(term)
        return terms

    def _has_management_experience(self, text: str) -> bool:
        return any(term in text for term in ["管理", "负责人", "主管", "经理", "带队", "团队"])

    def _profile_completeness(
        self,
        profile: dict[str, Any],
        candidate: dict[str, object],
    ) -> int:
        checks = [
            bool(profile["name_or_alias"]),
            bool(profile["city"]),
            bool(profile["current_title"]),
            profile["years_experience"] is not None,
            bool(profile["industry_tags"]),
            bool(profile["skill_tags"]),
            bool(profile["salary_range"]),
            bool(profile["education"]),
            bool(normalize_text(str(candidate.get("work_experience_text") or ""))),
            bool(normalize_text(str(candidate.get("raw_card_text") or ""))),
        ]
        return round(sum(1 for item in checks if item) / len(checks) * 100)
