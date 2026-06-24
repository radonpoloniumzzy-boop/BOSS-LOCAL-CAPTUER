from __future__ import annotations

import time
from collections.abc import Callable

from automation.parser import CandidateParser
from automation.scroller import PageScroller
from automation.selectors import BossSelectorConfig
from core.models import AppConfig, CaptureProgress, CaptureRunResult, CollectOptions
from core.utils import now_iso
from storage.repository import CandidateRepository


class BossCardCollector:
    def __init__(self, selector_config: BossSelectorConfig, logger=None) -> None:
        self.selector_config = selector_config
        self.logger = logger

    def wait_for_page_ready(self, page, timeout_ms: int = 5000) -> bool:
        end_time = time.time() + (timeout_ms / 1000)
        while time.time() < end_time:
            card_selector = self._pick_card_selector(page)
            if card_selector:
                return True
            for selector in self.selector_config.get("page_ready"):
                if page.locator(selector).count() > 0:
                    return True
            time.sleep(0.5)
        return False

    def extract_loaded_cards(self, page) -> list[dict[str, object]]:
        card_selector = self._pick_card_selector(page)
        if not card_selector:
            return []
        cards = page.locator(card_selector)
        payloads: list[dict[str, object]] = []
        count = cards.count()
        for index in range(count):
            card = cards.nth(index)
            try:
                raw_text = card.inner_text(timeout=1500)
            except Exception:
                raw_text = card.text_content(timeout=1500) or ""
            payloads.append(
                {
                    "raw_card_text": raw_text,
                    "name": self._first_text(card, "name"),
                    "active_status": self._first_text(card, "active_status"),
                    "expected_salary": self._first_text(card, "expected_salary"),
                    "work_experience_text": self._first_text(card, "work_experience_text"),
                    "education_text": self._first_text(card, "education_text"),
                    "summary_text": self._first_text(card, "summary_text"),
                    "tags_text": self._all_text(card, "tags_text"),
                    "detail_url": self._first_href(card, "detail_url"),
                    "platform_uid": self._platform_uid(card),
                }
            )
        self._log("info", "Extracted %s loaded cards from page", len(payloads))
        return payloads

    def _pick_card_selector(self, page) -> str:
        for selector in self.selector_config.get("card"):
            try:
                if page.locator(selector).count() > 0:
                    return selector
            except Exception:
                continue
        return ""

    def _first_text(self, card, field: str) -> str:
        for selector in self.selector_config.get(field):
            try:
                locator = card.locator(selector).first
                if locator.count() > 0:
                    return (locator.inner_text(timeout=500) or "").strip()
            except Exception:
                continue
        return ""

    def _all_text(self, card, field: str) -> list[str]:
        for selector in self.selector_config.get(field):
            try:
                locator = card.locator(selector)
                if locator.count() > 0:
                    return [item.strip() for item in locator.all_inner_texts() if item.strip()]
            except Exception:
                continue
        return []

    def _first_href(self, card, field: str) -> str:
        for selector in self.selector_config.get(field):
            try:
                locator = card.locator(selector).first
                if locator.count() > 0:
                    href = locator.get_attribute("href", timeout=500)
                    if href:
                        return href.strip()
            except Exception:
                continue
        return ""

    def _platform_uid(self, card) -> str:
        for attribute in self.selector_config.get("platform_uid_attributes"):
            try:
                value = card.get_attribute(attribute, timeout=500)
                if value:
                    return value.strip()
            except Exception:
                continue
        return ""

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)


class CaptureService:
    def __init__(
        self,
        repository: CandidateRepository,
        parser: CandidateParser,
        scroller: PageScroller,
        logger=None,
    ) -> None:
        self.repository = repository
        self.parser = parser
        self.scroller = scroller
        self.logger = logger
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True
        self._log("warning", "Stop requested by user")

    def reset_stop(self) -> None:
        self._stop_requested = False

    def collect(
        self,
        browser_service,
        selector_config: BossSelectorConfig,
        options: CollectOptions,
        config: AppConfig,
        progress_callback: Callable[[CaptureProgress], None] | None = None,
    ) -> CaptureRunResult:
        self.reset_stop()
        page = browser_service.ensure_page(config, options.source_url)
        intervention = browser_service.detect_manual_intervention(page)
        if intervention:
            return CaptureRunResult(
                batch_id=None,
                status="waiting_user",
                total_unique=0,
                total_inserted_candidates=0,
                total_batch_items=0,
                rounds_completed=0,
                message=intervention,
            )

        collector = BossCardCollector(selector_config=selector_config, logger=self.logger)
        collector.wait_for_page_ready(page)
        batch = self.repository.create_batch(options.job_title, options.source_url, options.note)
        seen_keys: set[str] = set()
        total_inserted_candidates = 0
        total_batch_items = 0
        rounds_without_new = 0
        rounds_completed = 0
        status = "completed"
        message = ""

        try:
            for round_index in range(1, config.max_scroll_count + 1):
                rounds_completed = round_index
                if self._stop_requested:
                    status = "stopped"
                    message = "Collection stopped by user."
                    break

                loaded_cards = collector.extract_loaded_cards(page)
                new_records = []
                for raw_card in loaded_cards:
                    try:
                        record = self.parser.parse_card(raw_card, options.job_title, options.source_url, now_iso())
                    except Exception as exc:
                        self._log("exception", "Failed to parse candidate card: %s", exc)
                        continue
                    if record is None or record.candidate_key in seen_keys:
                        continue
                    seen_keys.add(record.candidate_key)
                    new_records.append(record)

                repo_result = self.repository.upsert_batch_candidates(batch.id, new_records)
                total_inserted_candidates += repo_result["inserted_candidates"]
                total_batch_items += repo_result["inserted_batch_items"]
                last_round_new = len(new_records)

                if last_round_new == 0:
                    rounds_without_new += 1
                else:
                    rounds_without_new = 0

                self._log(
                    "info",
                    "Round %s loaded=%s new=%s total_unique=%s no_new_rounds=%s",
                    round_index,
                    len(loaded_cards),
                    last_round_new,
                    len(seen_keys),
                    rounds_without_new,
                )
                if progress_callback:
                    progress_callback(
                        CaptureProgress(
                            batch_id=batch.id,
                            status="running",
                            round_index=round_index,
                            loaded_cards=len(loaded_cards),
                            total_unique=len(seen_keys),
                            total_inserted_candidates=total_inserted_candidates,
                            total_batch_items=total_batch_items,
                            last_round_new=last_round_new,
                            consecutive_no_new=rounds_without_new,
                            message=f"Round {round_index}: +{last_round_new}",
                        )
                    )

                if rounds_without_new >= config.no_new_stop_rounds:
                    message = f"Stopped after {rounds_without_new} consecutive rounds with no new cards."
                    break

                self.scroller.scroll_once(
                    page,
                    mode=config.scroll_mode,
                    step=config.scroll_step,
                    wait_seconds=config.scroll_wait_seconds,
                )
                intervention = browser_service.detect_manual_intervention(page)
                if intervention:
                    status = "waiting_user"
                    message = intervention
                    break
        except Exception as exc:
            status = "failed"
            message = str(exc)
            self._log("exception", "Collection failed: %s", exc)
        finally:
            self.repository.finalize_batch(
                batch_id=batch.id,
                status=status,
                total_collected=len(seen_keys),
                total_new=total_batch_items,
                note=message or options.note,
            )

        return CaptureRunResult(
            batch_id=batch.id,
            status=status,
            total_unique=len(seen_keys),
            total_inserted_candidates=total_inserted_candidates,
            total_batch_items=total_batch_items,
            rounds_completed=rounds_completed,
            message=message,
        )

    def _log(self, level: str, message: str, *args) -> None:
        if not self.logger:
            return
        getattr(self.logger, level, self.logger.info)(message, *args)

