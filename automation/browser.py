from __future__ import annotations

import subprocess
from pathlib import Path

from core.exceptions import BrowserNotReadyError, PlatformBlockedError
from core.utils import ensure_directory


WINDOWS_BROWSER_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Chromium\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Chromium\Application\chrome.exe"),
]


class BrowserService:
    def __init__(self, logger=None) -> None:
        self.logger = logger
        self._playwright = None
        self._context = None
        self._page = None
        self._platform_blocked_reason: str | None = None

    def ensure_page(self, config, target_url: str | None = None):
        if self._context is None and self._platform_blocked_reason:
            raise PlatformBlockedError(self._platform_blocked_reason)
        if self._context is None:
            self.open_browser(config, target_url=target_url)
        if self._page is None or self._page.is_closed():
            self._page = self._pick_or_create_page()
        if target_url:
            self._navigate_page(self._page, target_url)
        return self._page

    def open_browser(self, config, target_url: str | None = None) -> str:
        resolved_url = target_url or config.target_url or "about:blank"
        if self._should_bypass_playwright(resolved_url):
            executable_path = self._resolve_browser_path(config.browser_path)
            self.close()
            self._open_regular_browser(executable_path, resolved_url)
            self._platform_blocked_reason = (
                "当前机器上的 Boss 页面无法在 Playwright 接管浏览器中稳定打开。"
                f"已为你打开普通浏览器窗口：{resolved_url}。"
                "你可以在普通浏览器里手动浏览和登录，但当前 Boss 集成不会继续自动采集。"
            )
            self._log("warning", self._platform_blocked_reason)
            raise PlatformBlockedError(self._platform_blocked_reason)

        if self._context is not None:
            page = self.ensure_page(config, target_url)
            return page.url

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserNotReadyError("未安装 Playwright，请先执行 `pip install -r requirements.txt`。") from exc

        executable_path = self._resolve_browser_path(config.browser_path)
        profile_dir = self._resolve_profile_dir(config.user_data_dir, executable_path)
        self._playwright = sync_playwright().start()
        chromium = self._playwright.chromium
        launch_kwargs = {
            "user_data_dir": str(profile_dir),
            "headless": False,
            "viewport": {"width": 1440, "height": 960},
            "ignore_default_args": ["--enable-automation", "--no-sandbox"],
        }
        if executable_path:
            launch_kwargs["executable_path"] = str(executable_path)

        try:
            self._context = chromium.launch_persistent_context(**launch_kwargs)
            self._page = self._pick_or_create_page()
            if target_url:
                self._navigate_page(self._page, target_url)
            self._platform_blocked_reason = None
            self._log(
                "info",
                "Opened browser with profile=%s executable=%s current_url=%s",
                profile_dir,
                executable_path or "playwright-chromium",
                self._page.url,
            )
            return self._page.url
        except Exception as exc:
            self.close()
            if self._is_boss_block(target_url or config.target_url, exc):
                fallback_url = "https://www.zhipin.com/"
                self._open_regular_browser(executable_path, fallback_url)
                self._platform_blocked_reason = (
                    "Boss 会阻止 Playwright/CDP 接管的页面。"
                    f"已为你打开普通浏览器窗口：{fallback_url}。"
                    "当前流程请改用 Chrome 扩展完成采集。"
                )
                self._log("warning", self._platform_blocked_reason)
                raise PlatformBlockedError(self._platform_blocked_reason) from exc
            raise

    def current_url(self) -> str:
        if not self._page:
            return ""
        return self._page.url

    def detect_manual_intervention(self, page) -> str:
        try:
            text = (page.locator("body").inner_text(timeout=2_000) or "")[:5000]
            url = page.url.lower()
        except Exception:
            return ""

        if any(token in url for token in ["login", "signin", "passport"]):
            return "当前处于登录页，请先手动登录后再继续。"

        text_lower = text.lower()
        if any(token in text for token in ["验证码", "滑块", "请完成验证"]) or any(
            token in text_lower for token in ["captcha", "verify"]
        ):
            return "检测到验证码或滑块验证，请先手动处理后再继续。"

        if any(token in text for token in ["登录", "扫码登录", "手机号登录"]):
            return "检测到登录提示，请先手动登录后再继续。"
        return ""

    def close(self) -> None:
        if self._page is not None:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._log("info", "Closed browser context")

    @staticmethod
    def _resolve_browser_path(configured_path: str) -> Path | None:
        if configured_path:
            path = Path(configured_path)
            if path.exists():
                return path
            for fallback in WINDOWS_BROWSER_CANDIDATES:
                if fallback.exists():
                    return fallback
        return None

    @staticmethod
    def _resolve_profile_dir(user_data_dir: str, executable_path: Path | None) -> Path:
        base_dir = ensure_directory(Path(user_data_dir))
        if executable_path is None:
            return ensure_directory(base_dir / "playwright_chromium")
        return ensure_directory(base_dir / "external_browser")

    def _pick_or_create_page(self):
        if self._context is None:
            raise BrowserNotReadyError("浏览器上下文尚未就绪。")
        pages = [page for page in self._context.pages if not page.is_closed()]
        for page in reversed(pages):
            try:
                url = page.url or ""
            except Exception:
                continue
            if not url.startswith("chrome://"):
                return page
        return self._context.new_page()

    def _navigate_page(self, page, target_url: str) -> None:
        if page.url != target_url:
            page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
        page.bring_to_front()
        self._log("info", "Active page ready at %s", page.url)

    @staticmethod
    def _is_boss_block(target_url: str, exc: Exception) -> bool:
        if "zhipin.com" not in (target_url or ""):
            return False
        message = str(exc).lower()
        return "target page, context or browser has been closed" in message or "about:blank" in message

    @staticmethod
    def _should_bypass_playwright(target_url: str) -> bool:
        return "zhipin.com" in (target_url or "").lower()

    def _open_regular_browser(self, executable_path: Path | None, target_url: str) -> None:
        if executable_path and executable_path.exists():
            subprocess.Popen([str(executable_path), target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        chrome_path = next((path for path in WINDOWS_BROWSER_CANDIDATES if path.exists()), None)
        if chrome_path:
            subprocess.Popen([str(chrome_path), target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        subprocess.Popen(["cmd", "/c", "start", "", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)
