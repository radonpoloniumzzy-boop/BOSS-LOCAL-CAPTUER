from __future__ import annotations

import csv
import json
from pathlib import Path

from core.models import ExportResult
from core.utils import ensure_directory, now_iso, sanitize_filename
from storage.repository import CandidateRepository


EXPORT_SUFFIXES = {
    "csv": ("候选人列表", "csv"),
    "jsonl": ("候选人列表", "jsonl"),
    "markdown": ("候选人摘要", "md"),
}


class ExportService:
    def __init__(self, repository: CandidateRepository, logger=None) -> None:
        self.repository = repository
        self.logger = logger

    def export(
        self,
        export_format: str,
        mode: str,
        export_dir: Path,
        columns: list[str],
        batch_id: int | None = None,
        keyword: str = "",
        job_title: str = "",
        city: str = "",
        years_min: int | str | None = None,
        years_max: int | str | None = None,
        profile_tag: str = "",
        last_active_days: int | str | None = None,
        match_role_id: int | str | None = None,
        minimum_rating: str = "",
        match_status: str = "",
        recruitment_status: str = "",
        latest_reason_code: str = "",
    ) -> ExportResult:
        rows = self.repository.get_export_rows(
            mode=mode,
            batch_id=batch_id,
            keyword=keyword,
            job_title=job_title,
            city=city,
            years_min=years_min,
            years_max=years_max,
            profile_tag=profile_tag,
            last_active_days=last_active_days,
            match_role_id=match_role_id,
            minimum_rating=minimum_rating,
            match_status=match_status,
            recruitment_status=recruitment_status,
            latest_reason_code=latest_reason_code,
        )
        export_format = export_format.lower().strip()
        if export_format not in EXPORT_SUFFIXES:
            raise ValueError(f"Unsupported export format: {export_format}")

        ensure_directory(export_dir)
        resolved_job_title = job_title or self._infer_job_title(rows)
        filename = self._build_filename(resolved_job_title, batch_id, export_format)
        target_path = export_dir / filename

        if export_format == "csv":
            self._export_csv(target_path, rows, columns)
        elif export_format == "jsonl":
            self._export_jsonl(target_path, rows, batch_id)
        else:
            self._export_markdown(target_path, rows, mode, resolved_job_title, batch_id)

        if self.logger:
            self.logger.info(
                "Exported %s rows to %s using mode=%s format=%s",
                len(rows),
                target_path,
                mode,
                export_format,
            )
        return ExportResult(
            file_path=str(target_path),
            row_count=len(rows),
            mode=mode,
            export_format=export_format,
        )

    def _export_csv(self, target_path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
        with target_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({column: self._stringify_value(row.get(column)) for column in columns})

    def _export_jsonl(self, target_path: Path, rows: list[dict[str, object]], batch_id: int | None) -> None:
        with target_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                record = {key: self._stringify_value(value) for key, value in row.items()}
                if batch_id is not None and "batch_id" not in record:
                    record["batch_id"] = batch_id
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")

    def _export_markdown(
        self,
        target_path: Path,
        rows: list[dict[str, object]],
        mode: str,
        job_title: str,
        batch_id: int | None,
    ) -> None:
        exported_at = now_iso()
        lines = [
            "# 候选人导出摘要",
            "",
            f"- 导出时间：{exported_at}",
            f"- 导出模式：{mode}",
            f"- 岗位名称：{job_title or 'Boss 候选人'}",
            f"- 候选人数：{len(rows)}",
        ]
        if batch_id is not None:
            lines.append(f"- 批次 ID：{batch_id}")
        lines.append("")

        if not rows:
            lines.append("当前没有可导出的候选人数据。")
            target_path.write_text("\n".join(lines), encoding="utf-8")
            return

        for index, row in enumerate(rows, start=1):
            name = self._stringify_value(row.get("name")) or f"候选人 {index}"
            role_direction = self._stringify_value(row.get("job_track") or row.get("job_family"))
            lines.extend(
                [
                    f"## {index}. {name}",
                    "",
                    f"- 城市：{self._stringify_value(row.get('city')) or '-'}",
                    f"- 年限：{self._stringify_value(row.get('years_experience')) or '-'}",
                    f"- 岗位方向：{role_direction or '-'}",
                    f"- AI匹配岗位：{self._stringify_value(row.get('role_title')) or '-'}",
                    f"- AI评级：{self._stringify_value(row.get('latest_rating')) or '-'}",
                    f"- AI置信度：{self._stringify_value(row.get('latest_confidence')) or '-'}",
                    f"- AI建议：{self._stringify_value(row.get('recommended_action')) or '-'}",
                    f"- AI证据：{self._json_summary(self._stringify_value(row.get('evidence_json')))}",
                    f"- AI缺口：{self._json_summary(self._stringify_value(row.get('gap_json')))}",
                    f"- AI风险：{self._json_summary(self._stringify_value(row.get('risk_json')))}",
                    f"- 匹配状态：{self._stringify_value(row.get('match_status')) or '-'}",
                    f"- 招聘阶段：{self._stringify_value(row.get('recruitment_status')) or '-'}",
                    f"- 人工复核：{self._stringify_value(row.get('human_decision')) or '-'}",
                    f"- 最近阶段变化：{self._stringify_value(row.get('latest_status_changed_at')) or '-'}",
                    f"- 最近原因：{self._stringify_value(row.get('latest_reason_code')) or '-'}",
                    f"- 最近备注：{self._stringify_value(row.get('latest_status_note')) or '-'}",
                    f"- 最近活跃：{self._stringify_value(row.get('last_active_at')) or '-'}",
                    f"- 画像完整度：{self._stringify_value(row.get('profile_completeness')) or '-'}",
                    f"- 活跃状态：{self._stringify_value(row.get('active_status')) or '-'}",
                    f"- 期望薪资：{self._stringify_value(row.get('expected_salary')) or '-'}",
                    f"- 工作经历：{self._stringify_value(row.get('work_experience_text')) or '-'}",
                    f"- 教育经历：{self._stringify_value(row.get('education_text')) or '-'}",
                    f"- 标签：{self._stringify_value(row.get('tags_text')) or '-'}",
                    f"- 摘要：{self._stringify_value(row.get('summary_text')) or '-'}",
                    f"- 来源岗位：{self._stringify_value(row.get('job_title')) or '-'}",
                    f"- 来源页面：{self._stringify_value(row.get('source_url')) or '-'}",
                    f"- 抓取时间：{self._stringify_value(row.get('capture_time')) or '-'}",
                    f"- 详情链接：{self._stringify_value(row.get('detail_url')) or '-'}",
                    f"- 候选人键：{self._stringify_value(row.get('candidate_key')) or '-'}",
                    "",
                    "### 原始卡片文本",
                    "",
                    "```text",
                    self._stringify_value(row.get("raw_card_text")) or "-",
                    "```",
                    "",
                ]
            )

        target_path.write_text("\n".join(lines), encoding="utf-8")

    def _build_filename(self, job_title: str, batch_id: int | None, export_format: str) -> str:
        label, extension = EXPORT_SUFFIXES[export_format]
        title = sanitize_filename(job_title or "Boss 候选人", fallback="Boss 候选人")
        suffix = f"_batch{batch_id}" if batch_id is not None else ""
        timestamp = now_iso().replace(":", "").replace("-", "").replace("T", "_")
        return f"{title}_{timestamp}{suffix}_{label}.{extension}"

    @staticmethod
    def _infer_job_title(rows: list[dict[str, object]]) -> str:
        if not rows:
            return "Boss 候选人"
        return str(rows[0].get("job_title") or "Boss 候选人")

    @staticmethod
    def _stringify_value(value: object) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _json_summary(value: str) -> str:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            return value or "-"
        if not parsed:
            return "-"
        if isinstance(parsed, list):
            parts: list[str] = []
            for item in parsed[:5]:
                if isinstance(item, dict):
                    text = "；".join(
                        f"{key}:{val}" for key, val in item.items() if val not in (None, "")
                    )
                    if text:
                        parts.append(text)
                else:
                    parts.append(str(item))
            return " / ".join(parts) or "-"
        if isinstance(parsed, dict):
            return "；".join(
                f"{key}:{val}" for key, val in parsed.items() if val not in (None, "")
            ) or "-"
        return str(parsed)
