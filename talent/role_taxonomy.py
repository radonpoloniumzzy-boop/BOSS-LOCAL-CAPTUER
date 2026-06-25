from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from core.utils import normalize_multiline_text


@dataclass(frozen=True, slots=True)
class RoleTrackDefinition:
    family: str
    track: str
    aliases: tuple[str, ...]
    must_have: tuple[str, ...] = field(default_factory=tuple)
    nice_to_have: tuple[str, ...] = field(default_factory=tuple)
    risk_flags: tuple[str, ...] = field(default_factory=tuple)
    interview_checks: tuple[str, ...] = field(default_factory=tuple)
    exclusion_terms: tuple[str, ...] = field(default_factory=tuple)

    def all_terms(self) -> tuple[str, ...]:
        return self.aliases + self.must_have + self.nice_to_have

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "track": self.track,
            "aliases": list(self.aliases),
            "must_have": list(self.must_have),
            "nice_to_have": list(self.nice_to_have),
            "risk_flags": list(self.risk_flags),
            "interview_checks": list(self.interview_checks),
            "exclusion_terms": list(self.exclusion_terms),
        }


DEFAULT_ROLE_TRACKS = (
    RoleTrackDefinition(
        family="销售",
        track="SaaS销售",
        aliases=("SaaS销售", "SaaS Sales", "软件销售", "企业软件销售", "CRM销售"),
        must_have=("SaaS", "CRM", "企业服务", "B2B", "解决方案"),
        nice_to_have=("KA", "大客户", "续费", "客单价", "ARR"),
        risk_flags=("纯电销", "无企业客户经验"),
        interview_checks=("独立签约金额", "销售周期", "客户行业", "客单价"),
    ),
    RoleTrackDefinition(
        family="销售",
        track="渠道销售",
        aliases=("渠道销售", "渠道经理", "渠道拓展", "代理商拓展", "Channel Sales"),
        must_have=("渠道", "代理商", "分销", "伙伴"),
        nice_to_have=("平台招商", "区域渠道", "渠道政策"),
        risk_flags=("只做直销",),
        interview_checks=("渠道数量", "渠道产出", "渠道激励方式"),
    ),
    RoleTrackDefinition(
        family="销售",
        track="KA销售",
        aliases=("KA销售", "大客户销售", "大客户经理", "Key Account", "重点客户"),
        must_have=("KA", "大客户", "重点客户", "企业客户"),
        nice_to_have=("招投标", "解决方案", "客情维护"),
        risk_flags=("只做中小客户",),
        interview_checks=("客户层级", "项目金额", "决策链路"),
    ),
    RoleTrackDefinition(
        family="销售",
        track="招商主管",
        aliases=("招商主管", "招商经理", "平台招商", "商户拓展", "加盟拓展"),
        must_have=("招商", "商户", "加盟", "门店拓展"),
        nice_to_have=("平台招商", "线下门店", "区域拓展"),
        risk_flags=("无商户谈判经验",),
        interview_checks=("招商转化率", "商户质量", "区域资源"),
    ),
    RoleTrackDefinition(
        family="销售",
        track="B2B销售",
        aliases=("B2B销售", "企业销售", "ToB销售", "商务拓展", "客户经理", "Account Executive"),
        must_have=("B2B", "企业客户", "商务", "销售"),
        nice_to_have=("行业客户", "客户开发", "回款"),
        risk_flags=("只有C端零售经验",),
        interview_checks=("获客方式", "成交周期", "回款金额"),
    ),
    RoleTrackDefinition(
        family="销售",
        track="电话销售",
        aliases=("电话销售", "电销", "Inside Sales", "Telesales", "外呼销售"),
        must_have=("电话", "电销", "外呼", "邀约"),
        nice_to_have=("线索转化", "话术优化"),
        risk_flags=("无陌拜或外呼经验",),
        interview_checks=("日均外呼", "线索转化率", "有效通话率"),
    ),
    RoleTrackDefinition(
        family="运营",
        track="用户运营",
        aliases=("用户运营", "社群运营", "会员运营", "User Operations"),
        must_have=("用户运营", "社群", "留存", "活跃"),
        nice_to_have=("私域", "用户增长", "生命周期"),
        risk_flags=("只有客服经验",),
        interview_checks=("留存指标", "活跃指标", "用户分层"),
    ),
    RoleTrackDefinition(
        family="运营",
        track="内容运营",
        aliases=("内容运营", "新媒体运营", "社区运营", "Content Operations"),
        must_have=("内容运营", "内容", "新媒体", "社区"),
        nice_to_have=("选题", "转化", "增长"),
        risk_flags=("只做执行排版",),
        interview_checks=("内容转化", "爆款案例", "渠道策略"),
    ),
    RoleTrackDefinition(
        family="运营",
        track="电商运营",
        aliases=("电商运营", "店铺运营", "平台运营", "Ecommerce Operations"),
        must_have=("电商", "店铺", "平台运营", "转化率"),
        nice_to_have=("投放", "活动运营", "GMV"),
        risk_flags=("无平台后台经验",),
        interview_checks=("GMV", "转化率", "活动ROI"),
    ),
    RoleTrackDefinition(
        family="技术",
        track="后端开发",
        aliases=("后端开发", "Java工程师", "Python工程师", "Backend Engineer"),
        must_have=("Java", "Python", "后端", "API", "SQL"),
        nice_to_have=("Spring Cloud", "微服务", "高并发"),
        risk_flags=("只有脚本经验",),
        interview_checks=("系统设计", "接口性能", "数据库优化"),
    ),
    RoleTrackDefinition(
        family="技术",
        track="前端开发",
        aliases=("前端开发", "前端工程师", "Frontend Engineer", "Web前端"),
        must_have=("前端", "React", "Vue", "TypeScript", "JavaScript"),
        nice_to_have=("组件库", "性能优化", "工程化"),
        risk_flags=("只会静态页面",),
        interview_checks=("组件设计", "状态管理", "性能优化"),
    ),
    RoleTrackDefinition(
        family="技术",
        track="数据分析",
        aliases=("数据分析", "数据分析师", "BI", "Data Analyst"),
        must_have=("SQL", "数据分析", "BI", "报表"),
        nice_to_have=("Python", "指标体系", "A/B测试"),
        risk_flags=("只做数据录入",),
        interview_checks=("指标拆解", "SQL能力", "业务分析案例"),
    ),
)


class RoleTaxonomy:
    def __init__(self, tracks: Iterable[RoleTrackDefinition] | None = None) -> None:
        self.tracks = tuple(tracks or DEFAULT_ROLE_TRACKS)

    def classify(self, text: str, extra_terms: Iterable[str] | None = None) -> tuple[str, str]:
        combined = normalize_multiline_text(text)
        if extra_terms:
            combined = normalize_multiline_text(
                combined + "\n" + "\n".join(str(term) for term in extra_terms)
            )
        lowered = combined.lower()
        best: tuple[int, int, RoleTrackDefinition] | None = None
        for index, track in enumerate(self.tracks):
            score = self._score_track(lowered, track)
            if score <= 0:
                continue
            candidate = (score, -index, track)
            if best is None or candidate > best:
                best = candidate
        if best is None:
            return "", ""
        return best[2].family, best[2].track

    def match_track(self, text: str) -> RoleTrackDefinition | None:
        family, track = self.classify(text)
        if not family or not track:
            return None
        return self.get_track(family, track)

    def get_track(self, family: str, track: str) -> RoleTrackDefinition | None:
        for definition in self.tracks:
            if definition.family == family and definition.track == track:
                return definition
        return None

    def vocabulary(self) -> list[str]:
        terms: list[str] = []
        for track in self.tracks:
            for term in track.all_terms():
                if term not in terms:
                    terms.append(term)
        return terms

    @staticmethod
    def _score_track(text: str, track: RoleTrackDefinition) -> int:
        score = 0
        for term in track.aliases:
            if term.lower() in text:
                score += 4
        for term in track.must_have:
            if term.lower() in text:
                score += 2
        for term in track.nice_to_have:
            if term.lower() in text:
                score += 1
        return score
