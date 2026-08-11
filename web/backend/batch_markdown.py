from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from storage.repository import CandidateRepository


@dataclass(frozen=True)
class MarkdownDownload:
    filename: str
    content: str


class BatchMarkdownExporter:
    def __init__(self, repository: CandidateRepository) -> None:
        self.repository = repository

    def build(self, batch_id: int) -> MarkdownDownload | None:
        batch = self.repository.get_capture_batch(batch_id)
        if batch is None:
            return None
        rows: list[dict[str, object]] = []
        page = 1
        while True:
            result = self.repository.page_capture_batch_candidates(batch_id, page=page, page_size=500)
            rows.extend(result["rows"])
            if len(rows) >= int(result["total"]):
                break
            page += 1
        created = str(batch.get("start_time") or batch.get("created_at") or "")
        sections = [
            "# 招聘候选人采集批次",
            "",
            "## 批次信息",
            f"- 批次 ID：{batch_id}",
            f"- 采集时间：{created or '未记录'}",
            f"- 来源平台：{batch.get('source_platform') or 'unknown'}",
            f"- 来源岗位文字：{batch.get('job_title') or '未提供'}",
            f"- 接收数：{int(batch.get('total_collected') or 0)}",
            f"- 新增数：{int(batch.get('total_new') or 0)}",
            f"- 更新数：{int(batch.get('total_updated') or 0)}",
            f"- 跳过数：{int(batch.get('total_skipped') or 0)}",
            f"- 失败数：{int(batch.get('total_failed') or 0)}",
        ]
        formally_bound = batch.get("role_id") is not None
        for index, row in enumerate(rows, start=1):
            name = str(row.get("name") or f"候选人 {index}").strip()
            sections.extend(
                [
                    "",
                    f"## 候选人 {index}：{name}",
                    f"- 来源平台：{row.get('source_platform') or row.get('candidate_source_platform') or 'unknown'}",
                    f"- 来源岗位：{row.get('job_title') or '未提供'}",
                    f"- 本次结果：{'更新' if row.get('ingest_status') == 'updated' else '新增'}",
                    f"- 正式岗位绑定状态：{'已绑定岗位' if formally_bound else '未绑定岗位'}",
                    f"- 采集时间：{row.get('capture_time') or '未记录'}",
                    "",
                    "### 原始信息快照",
                    str(row.get("raw_card_text") or "未保存原始快照"),
                    "",
                    "---",
                ]
            )
        timestamp = self._filename_timestamp(created)
        return MarkdownDownload(
            filename=f"boss-批次-{batch_id}-{timestamp}.md",
            content="\n".join(sections).rstrip() + "\n",
        )

    @staticmethod
    def _filename_timestamp(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.strftime("%Y%m%d-%H%M%S")
        except ValueError:
            cleaned = re.sub(r"[^0-9]", "", value)[:14]
            return cleaned or datetime.now().strftime("%Y%m%d-%H%M%S")
