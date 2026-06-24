from __future__ import annotations

import time


class PageScroller:
    def __init__(self, logger=None) -> None:
        self.logger = logger

    def scroll_once(self, page, mode: str, step: int, wait_seconds: float) -> int:
        if mode == "page":
            offset = int(
                page.evaluate(
                    "() => Math.max(window.innerHeight || 0, document.documentElement.clientHeight || 0, 800)"
                )
            )
        else:
            offset = step
        current_y = int(page.evaluate("(delta) => { window.scrollBy(0, delta); return window.scrollY; }", offset))
        if self.logger:
            self.logger.info("Scrolled page by %s pixels to Y=%s", offset, current_y)
        time.sleep(wait_seconds)
        return current_y

