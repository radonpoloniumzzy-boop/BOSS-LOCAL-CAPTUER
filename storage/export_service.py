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
    ) -> ExportResult:
        rows = self.repository.get_export_rows(
            mode=mode,
            batch_id=batch_id,
            keyword=keyword,
            job_title=job_title,
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
            lines.extend(
                [
                    f"## {index}. {name}",
                    "",
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
