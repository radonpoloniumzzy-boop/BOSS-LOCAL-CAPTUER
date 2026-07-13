from __future__ import annotations

import json
import re
from pathlib import Path

from ai.schemas import PromptTemplate
from core.utils import normalize_multiline_text, normalize_text
from core.models import ScreeningProfile


OUTPUT_PROTOCOL = """
## 输出协议
只输出一个 JSON 对象，不要输出 Markdown 或解释：
{
  "rating": "UR/SSR/SR/R/N 之一",
  "persona": "一句客观人物画像，说明背景、最关键的岗位相关证据和仍需验证的核心缺口",
  "confidence": "high/medium/low 之一；信息不足或证据冲突时用 low",
  "evidence": [
    {"item": "岗位要求或能力点", "evidence": "候选人资料中的具体证据"}
  ],
  "gaps": ["仍缺失或需要面试验证的信息"],
  "risks": ["可复核的岗位相关风险；没有则返回空数组"],
  "recommended_action": "priority_outreach/normal_review/manual_check/hold 之一"
}

人物画像要求：
- 只写一到两句话，最多 180 个中文字符。
- 不使用“优秀、很强、不错、扎实、有潜力、综合素质好、值得期待、学习能力强、沟通能力好”。
- 所有判断落到简历中出现的具体工具、项目、客户、金额、结果、负责范围或交付物。
- 区分已有证据与尚未验证；证据不足时明确写“证据不足，不能高评”。
- 不做最终录用决定；评级仅用于人工复核排序。
""".strip()


DEFAULT_JD_PROTOCOL = """
# 候选人深度测评与分级协议（{job_title}）

## 角色与目标
你是招聘负责人。依据岗位真实需求进行冷静、严格、穿透式评估，不复述简历，不被名校、Title、大厂或包装性项目迷惑。
目标是识别候选人与岗位的证据匹配程度，为人工复核提供优先级，不替代人工招聘决定。

## 原始岗位 JD
{jd_text}

## 判断规则
1. 先从 JD 提取岗位职责、硬性门槛、核心能力、优先项和必须面试验证的缺口。
2. 硬性门槛只能使用 JD 中明确、合法且与工作直接相关的要求；不得自行增加条件。
3. 区分“参与/协助”和“独立负责/推进/闭环/交付”，没有动作、范围和结果证据时不得高评。
4. 项目、平台、学历和头衔只能作为背景证据，不能代替岗位核心能力。
5. 课程项目、模板项目、包装项目不能直接视为真实工作能力。
6. 信息不足时禁止脑补，必须降档并写明“证据不足，不能高评”。
7. 不得使用或推断年龄、性别、婚育、民族、宗教、健康/残疾、照片、外貌、形象气质等个人敏感特征进行评级。

## 五级评级
- UR：极稀缺。核心能力、独立闭环和高含金量结果均有明确证据，已呈现准 owner 能力。
- SSR：强推档。岗位背景、核心能力、业务理解和独立推进证据明显高于普通合格样本。
- SR：合格偏强。基础与相关经历匹配，有可验证的项目或结果证据，但关键深度仍需面试确认。
- R：低位通过。基础条件或可迁移经历存在，但缺少岗位核心能力、独立闭环或高含金量证据。
- N：不匹配。明确不满足合法硬门槛、岗位严重错位，或只有包装/辅助执行而无关键能力证据。

{output_protocol}
""".strip()


SENSITIVE_CRITERIA_PATTERNS = [
    (re.compile(r"年龄.{0,18}(要求|不得|不能|不超过|低于|高于|优先|淘汰|推进|评级|门槛)"), "年龄筛选"),
    (re.compile(r"(28|29|30|35|40)\s*岁.{0,12}(以下|以上|以内|不得|优先|淘汰|推进)"), "年龄筛选"),
    (re.compile(r"(形象气质|外貌|颜值|照片).{0,16}(优先|要求|淘汰|降档|推进|适合)"), "外貌或形象筛选"),
    (re.compile(r"(男性|女性|男生|女生|性别).{0,16}(优先|要求|仅限|淘汰|推进)"), "性别筛选"),
    (re.compile(r"(婚育|已婚|未婚|生育).{0,16}(优先|要求|淘汰|推进)"), "婚育筛选"),
]


class PromptManager:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_templates(self) -> list[PromptTemplate]:
        return [
            PromptTemplate(
                template_name="JD 高压筛选模板",
                template_text=DEFAULT_JD_PROTOCOL,
                job_type="通用",
                version="v2",
            )
        ]

    def build_from_jd(self, job_title: str, jd_text: str) -> str:
        title = normalize_text(job_title) or "目标岗位"
        jd = normalize_multiline_text(jd_text)
        if not jd:
            raise ValueError("请先上传或粘贴 JD。")
        return DEFAULT_JD_PROTOCOL.format(job_title=title, jd_text=jd, output_protocol=OUTPUT_PROTOCOL)

    def build_structured(self, profile: ScreeningProfile) -> str:
        def section(title: str, values: list[str]) -> str:
            normalized = [normalize_text(value) for value in values if normalize_text(value)]
            lines = [f"- {value}" for value in normalized] or ["- 无"]
            return f"## {title}\n" + "\n".join(lines)

        evidence_policy = json.dumps(
            profile.evidence_policy or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "\n\n".join(
            [
                f"# {normalize_text(profile.job_title) or '目标岗位'}结构化筛选方案",
                "## 原始岗位 JD\n" + (normalize_multiline_text(profile.jd_text) or "无"),
                section("必须项", profile.must_have),
                section("加分项", profile.nice_to_have),
                section("风险项", profile.risk_flags),
                section("排除项", profile.exclusions),
                section("面试核验项", profile.interview_checks),
                "## 证据策略\n" + evidence_policy,
                "所有判断必须引用候选人资料中的明确证据；信息不足时进入人工确认，不得脑补。",
                OUTPUT_PROTOCOL,
            ]
        )

    def finalize_custom_prompt(self, prompt_text: str, job_title: str, jd_text: str) -> str:
        prompt = normalize_multiline_text(prompt_text)
        if not prompt:
            return self.build_from_jd(job_title, jd_text)
        errors = self.validate_screening_criteria(prompt)
        if errors:
            raise ValueError("自定义 Prompt 包含不能用于自动招聘评级的条件：" + "、".join(errors))
        return "\n\n".join(
            [
                prompt,
                "## 岗位原始 JD\n" + normalize_multiline_text(jd_text),
                "## 合规约束\n不得使用或推断年龄、性别、婚育、民族、宗教、健康/残疾、照片、外貌或形象气质进行评级。",
                OUTPUT_PROTOCOL,
            ]
        )

    def finalize_prompt(self, prompt_text: str, prompt_source: str, job_title: str, jd_text: str) -> str:
        prompt = normalize_multiline_text(prompt_text)
        if not prompt or prompt_source == "generated":
            generated = prompt or self.build_from_jd(job_title, jd_text)
            errors = self.validate_screening_criteria(generated)
            if errors:
                raise ValueError("筛选条件包含不能用于自动招聘评级的条件：" + "、".join(errors))
            return generated
        return self.finalize_custom_prompt(prompt, job_title, jd_text)

    def validate_screening_criteria(self, text: str) -> list[str]:
        value = normalize_multiline_text(text)
        found: list[str] = []
        for pattern, label in SENSITIVE_CRITERIA_PATTERNS:
            if pattern.search(value) and label not in found:
                found.append(label)
        return found

    def read_uploaded_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".markdown", ".json", ".csv"}:
            return normalize_multiline_text(path.read_text(encoding="utf-8-sig"))
        if suffix == ".docx":
            try:
                from docx import Document
            except ImportError as exc:
                raise RuntimeError("读取 DOCX 需要安装 python-docx。") from exc
            document = Document(str(path))
            return normalize_multiline_text("\n".join(paragraph.text for paragraph in document.paragraphs))
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as exc:
                raise RuntimeError("读取 PDF 需要安装 pypdf。") from exc
            reader = PdfReader(str(path))
            return normalize_multiline_text("\n".join(page.extract_text() or "" for page in reader.pages))
        raise ValueError("仅支持 TXT、Markdown、DOCX 和 PDF 文件。")
