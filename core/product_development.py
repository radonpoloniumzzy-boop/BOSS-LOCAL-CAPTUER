from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class ProductDevelopmentRepository:
    """Load the tracked product plan and keep user feedback in local runtime data."""

    REQUIRED_PLAN_KEYS = ("product", "status_options", "roadmap", "modules", "versions")

    def __init__(self, plan_path: Path, feedback_path: Path) -> None:
        self.plan_path = Path(plan_path)
        self.feedback_path = Path(feedback_path)

    def load_snapshot(self) -> dict[str, Any]:
        return {"plan": self._load_plan(), "feedback": self._load_feedback()}

    def submit_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        description = str(payload.get("description") or "").strip()
        if not description:
            raise ValueError("请填写反馈内容。")

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        feedback = {
            "id": f"FB-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
            "type": str(payload.get("type") or "功能建议").strip(),
            "module": str(payload.get("module") or "整体产品").strip(),
            "impact": str(payload.get("impact") or "一般影响").strip(),
            "description": description,
            "expected": str(payload.get("expected") or "").strip(),
            "status": "待处理",
            "created_at": now,
        }
        feedback_items = self._load_feedback()
        feedback_items.insert(0, feedback)
        self._save_feedback(feedback_items)
        return feedback

    def _load_plan(self) -> dict[str, Any]:
        if not self.plan_path.exists():
            raise FileNotFoundError(f"产品方案文件不存在：{self.plan_path}")
        try:
            plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"产品方案文件格式错误：{exc}") from exc
        if not isinstance(plan, dict):
            raise ValueError("产品方案必须是一个对象。")
        missing = [key for key in self.REQUIRED_PLAN_KEYS if key not in plan]
        if missing:
            raise ValueError(f"产品方案缺少字段：{', '.join(missing)}")
        if not isinstance(plan["product"], dict):
            raise ValueError("产品基础信息格式错误。")
        for key in ("status_options", "roadmap", "modules", "versions"):
            if not isinstance(plan[key], list):
                raise ValueError(f"产品方案字段 {key} 必须是列表。")
        if not all(isinstance(status, str) for status in plan["status_options"]):
            raise ValueError("产品方案字段 status_options 的每一项必须是文本。")
        for key in ("roadmap", "modules", "versions"):
            if not all(isinstance(item, dict) for item in plan[key]):
                raise ValueError(f"产品方案字段 {key} 的每一项必须是对象。")
        return plan

    def _load_feedback(self) -> list[dict[str, Any]]:
        if not self.feedback_path.exists():
            return []
        try:
            items = json.loads(self.feedback_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"反馈记录读取失败：{exc}") from exc
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError("反馈记录格式错误。")
        return items

    def _save_feedback(self, feedback_items: list[dict[str, Any]]) -> None:
        self.feedback_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.feedback_path.with_suffix(self.feedback_path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(feedback_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.feedback_path)
