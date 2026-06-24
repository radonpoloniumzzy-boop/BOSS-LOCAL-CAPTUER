from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from core.models import AIProviderConfig, AppConfig, AutomationFlowConfig
from core.utils import deep_merge, ensure_directory, get_app_root, json_dumps


class ConfigService:
    def __init__(self, app_root: Path | None = None, logger=None) -> None:
        self.app_root = app_root or get_app_root()
        self.logger = logger
        self.data_dir = ensure_directory(self.app_root / "data")
        self.logs_dir = ensure_directory(self.app_root / "logs")
        self.dist_dir = ensure_directory(self.app_root / "dist")
        self.config_path = self.data_dir / "config.json"
        self.database_path = self.data_dir / "boss_local_tool.db"
        self.default_export_dir = ensure_directory(self.data_dir / "exports")
        self.default_user_data_dir = ensure_directory(self.data_dir / "browser_profile")
        self.default_selectors_path = self.data_dir / "boss_selectors.json"

    def default_config(self) -> AppConfig:
        return AppConfig(
            user_data_dir=str(self.default_user_data_dir),
            default_export_dir=str(self.default_export_dir),
            selectors_path=str(self.default_selectors_path),
        )

    def ensure_runtime_paths(self, config: AppConfig | None = None) -> AppConfig:
        config = config or self.default_config()
        ensure_directory(Path(config.user_data_dir))
        ensure_directory(Path(config.default_export_dir))
        ensure_directory(self.logs_dir)
        ensure_directory(self.data_dir)
        return config

    def load(self) -> AppConfig:
        defaults = self.default_config()
        if not self.config_path.exists():
            self.save(defaults)
            self._log("info", "Config file not found. Created default config at %s", self.config_path)
            return defaults

        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            merged = deep_merge(defaults.to_dict(), raw)
            config = self._build_config(merged)
            self.ensure_runtime_paths(config)
            return config
        except Exception as exc:
            self._log("exception", "Failed to load config from %s: %s", self.config_path, exc)
            self.save(defaults)
            return defaults

    def save(self, config: AppConfig) -> None:
        self.ensure_runtime_paths(config)
        self.config_path.write_text(json_dumps(config.to_dict()), encoding="utf-8")
        self._log("info", "Saved config to %s", self.config_path)

    def export_example(self, target_path: Path) -> None:
        target_path.write_text(json_dumps(self.default_config().to_dict()), encoding="utf-8")

    def _build_config(self, data: dict[str, Any]) -> AppConfig:
        defaults = self.default_config()
        valid_keys = {field.name for field in fields(AppConfig)}
        clean: dict[str, Any] = {key: value for key, value in data.items() if key in valid_keys}
        ai_provider = clean.get("ai_provider", {})
        if not isinstance(ai_provider, dict):
            ai_provider = defaults.ai_provider.to_dict()
        automation_flow = clean.get("automation_flow", {})
        if not isinstance(automation_flow, dict):
            automation_flow = defaults.automation_flow.to_dict()
        csv_columns = clean.get("csv_columns", defaults.csv_columns)
        if not isinstance(csv_columns, list) or not all(isinstance(value, str) for value in csv_columns):
            csv_columns = list(defaults.csv_columns)
        clean["csv_columns"] = csv_columns
        clean["scroll_step"] = int(clean.get("scroll_step", defaults.scroll_step))
        clean["scroll_wait_seconds"] = float(clean.get("scroll_wait_seconds", defaults.scroll_wait_seconds))
        clean["max_scroll_count"] = int(clean.get("max_scroll_count", defaults.max_scroll_count))
        clean["no_new_stop_rounds"] = int(clean.get("no_new_stop_rounds", defaults.no_new_stop_rounds))
        clean["local_api_port"] = int(clean.get("local_api_port", defaults.local_api_port))
        clean["ai_provider"] = AIProviderConfig(**ai_provider)
        automation_keys = {field.name for field in fields(AutomationFlowConfig)}
        automation_clean = {
            key: value for key, value in automation_flow.items() if key in automation_keys
        }
        automation_clean["enabled"] = bool(
            automation_clean.get("enabled", defaults.automation_flow.enabled)
        )
        profile_id = automation_clean.get("profile_id")
        automation_clean["profile_id"] = int(profile_id) if profile_id is not None else None
        automation_clean["max_candidates"] = int(
            automation_clean.get("max_candidates", defaults.automation_flow.max_candidates)
        )
        clean["automation_flow"] = AutomationFlowConfig(**automation_clean)
        return AppConfig(**clean)

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        logger = self.logger.getChild("config")
        getattr(logger, level, logger.info)(message, *args)
