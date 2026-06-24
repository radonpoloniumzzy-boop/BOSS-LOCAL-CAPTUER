from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.utils import normalize_text


DEFAULT_SELECTORS = {
    "page_ready": [
        ".recommend-geek-list",
        ".recommend-list",
        ".candidate-list",
        "[data-testid='candidate-list']",
    ],
    "card": [
        ".candidate-card-wrap",
        ".candidate-card",
        ".card-inner",
        "[data-testid='candidate-card']",
    ],
    "name": [".name", ".geek-name", ".candidate-name"],
    "active_status": [".active-time", ".online", ".active-status"],
    "expected_salary": [".salary", ".expect-salary", ".tag-salary"],
    "work_experience_text": [".experience", ".work-experience", ".resume-desc"],
    "education_text": [".education", ".edu", ".education-status"],
    "tags_text": [".tags span", ".tag-list span", ".labels span", ".tag"],
    "summary_text": [".description", ".summary", ".card-desc", ".self-intro"],
    "detail_url": ["a[href*='geek']", "a[href*='candidate']", "a"],
    "platform_uid_attributes": ["data-geek-id", "data-id", "data-candidate-id", "data-user-id"],
}


@dataclass(slots=True)
class BossSelectorConfig:
    selectors: dict[str, list[str]]

    @classmethod
    def load(cls, path: Path) -> "BossSelectorConfig":
        data = DEFAULT_SELECTORS
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = {**DEFAULT_SELECTORS, **raw}
            except Exception:
                data = DEFAULT_SELECTORS
        return cls(selectors=data)

    def get(self, name: str) -> list[str]:
        value = self.selectors.get(name, [])
        return [normalize_text(item) for item in value if normalize_text(item)]
