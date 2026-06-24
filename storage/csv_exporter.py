from __future__ import annotations

from pathlib import Path

from core.models import ExportResult
from storage.export_service import ExportService


class CsvExporter(ExportService):
    def export(
        self,
        mode: str,
        export_dir: Path,
        columns: list[str],
        batch_id: int | None = None,
        keyword: str = "",
        job_title: str = "",
    ) -> ExportResult:
        return super().export(
            export_format="csv",
            mode=mode,
            export_dir=export_dir,
            columns=columns,
            batch_id=batch_id,
            keyword=keyword,
            job_title=job_title,
        )
