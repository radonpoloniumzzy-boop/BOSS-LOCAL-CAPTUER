from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_multiline_text(value: str | None) -> str:
    if not value:
        return ""
    lines = [normalize_text(line) for line in value.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sanitize_filename(value: str, fallback: str = "export") -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"[\\\\/:*?\"<>|]+", "_", normalized)
    normalized = normalized.strip(" ._")
    return normalized or fallback


def coalesce(*values: str | None) -> str:
    for value in values:
        normalized = normalize_text(value)
        if normalized:
            return normalized
    return ""


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)

