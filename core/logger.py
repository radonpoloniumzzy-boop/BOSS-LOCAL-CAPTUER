from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from core.utils import ensure_directory


class _CallbackHandler(logging.Handler):
    def __init__(self, callbacks: list[Callable[[str], None]]) -> None:
        super().__init__()
        self._callbacks = callbacks

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        for callback in list(self._callbacks):
            try:
                callback(message)
            except Exception:
                continue


class LoggingService:
    def __init__(self, log_dir: Path, level: str = "INFO") -> None:
        self._log_dir = ensure_directory(log_dir)
        self._callbacks: list[Callable[[str], None]] = []
        self._logger = logging.getLogger("boss_local_tool")
        self._logger.propagate = False
        self.configure(level)

    @property
    def log_file_path(self) -> Path:
        return self._log_dir / "app.log"

    def subscribe(self, callback: Callable[[str], None]) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[str], None]) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def configure(self, level: str) -> None:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self._close_handlers()
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))

        file_handler = RotatingFileHandler(
            self.log_file_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)

        callback_handler = _CallbackHandler(self._callbacks)
        callback_handler.setFormatter(formatter)

        self._logger.addHandler(file_handler)
        self._logger.addHandler(callback_handler)

    def close(self) -> None:
        self._close_handlers()

    def _close_handlers(self) -> None:
        for handler in list(self._logger.handlers):
            self._logger.removeHandler(handler)
            handler.close()

    def get_logger(self, name: str | None = None) -> logging.Logger:
        return self._logger if not name else self._logger.getChild(name)

