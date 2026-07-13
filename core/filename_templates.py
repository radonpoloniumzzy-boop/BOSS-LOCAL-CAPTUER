from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping


DEFAULT_EXPORT_TEMPLATE = "{job_title}_{date}_{time}_batch{batch_id}_{type}"
DEFAULT_RESUME_TEMPLATE = "{candidate_name}_{job_title}_{date}_{original_name}"
_VARIABLE_PATTERN = re.compile(r"\{([a-z_][a-z0-9_]*)\}", re.IGNORECASE)
_ILLEGAL_PATTERN = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def render_filename(template: str, values: Mapping[str, object], fallback: str = "unknown") -> str:
    normalized = {str(key): _normalize_value(str(key), value, fallback) for key, value in values.items()}

    def replace(match: re.Match[str]) -> str:
        return normalized.get(match.group(1), fallback)

    rendered = _VARIABLE_PATTERN.sub(replace, str(template or "").strip())
    rendered = rendered.replace("..", "_")
    rendered = _ILLEGAL_PATTERN.sub("_", rendered)
    rendered = re.sub(r"\s+", " ", rendered).strip(" ._")
    rendered = rendered or fallback
    if rendered.upper() in _RESERVED_NAMES:
        rendered += "_"
    return rendered[:180]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _normalize_value(name: str, value: object, fallback: str) -> str:
    text = str(value or "").strip()
    if name == "original_name" and text:
        text = Path(text.replace("\\", "/")).stem
    text = text.replace("..", "_")
    text = _ILLEGAL_PATTERN.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" ._")
    if not text:
        return fallback
    if text.upper() in _RESERVED_NAMES:
        text += "_"
    return text
