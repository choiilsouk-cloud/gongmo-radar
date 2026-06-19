# -*- coding: utf-8 -*-
"""
ntis_collector.py - NTIS
=============================
[2024 test] NTIS(www.ntis.go.kr) blocks requests with:
  1. Cloudflare access_check2 bot detection
  2. Pure JS SPA (React) - no static HTML

Solution: Playwright headless browser required.

Install:
  pip install playwright
  playwright install chromium
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List

logger = logging.getLogger(__name__)

NTIS_BASE = "https://www.ntis.go.kr"
_BOARD_URL = f"{NTIS_BASE}/rndgate/etc/menu/program/bizAncm/bizAncmList.do"

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


class NtisCollector:
    """
    NTIS collector.
    - Playwright installed: headless Chromium scraping
    - Playwright missing : graceful empty return (no error)
    api_key param kept for backward compat only (unused).
    """

    def __init__(self, api_key: str = ""):
        pass

    def collect(self, days_back: int = 7) -> List[dict]:
        if not _PLAYWRIGHT_AVAILABLE:
            logger.info(
                "NTIS: Playwright not installed - skipping. "
                "Run: pip install playwright && playwright install chromium"
            )
            return []
        try:
            return self._fetch_with_playwright(days_back)
        except Exception as exc:
            logger.warning("NTIS Playwright error: %s", exc)
            return []

    def _fetch_with_playwright(self, days_back: int) -> List[dict]:
        cutoff = datetime.now() - timedelta(days=days_back)
        notices = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="ko-KR",
            )
            page = ctx.new_page()

            try:
                page.goto(_BOARD_URL, wait_until="networkidle", timeout=30_000)
                time.sleep(2)

                rows = page.query_selector_all(
                    "table tbody tr, .list-item, .board-item, li.item"
                )

                if not rows:
                    logger.warning(
                        "NTIS: no list elements found - site may have changed. URL: %s",
                        _BOARD_URL,
                    )
                    return []

                for row in rows:
                    try:
                        a_tag = row.query_selector("a")
                        if not a_tag:
                            continue
                        title = (a_tag.inner_text() or "").strip()
                        if not title or len(title) < 3:
                            continue
                        href = a_tag.get_attribute("href") or ""
                        url = (
                            f"{NTIS_BASE}{href}" if href.startswith("/")
                            else href or _BOARD_URL
                        )
                        post_date_str = ""
                        date_els = row.query_selector_all("td, span.date, .date")
                        for el in date_els:
                            txt = (el.inner_text() or "").strip()
                            if len(txt) >= 10 and txt[4] in ("-", "."):
                                post_date_str = txt[:10].replace(".", "-")
                                break
                        if post_date_str:
                            try:
                                post_dt = datetime.strptime(post_date_str, "%Y-%m-%d")
                                if post_dt < cutoff:
                                    break
                            except ValueError:
                                pass
                        notices.append({
                            "source":    "NTIS",
                            "title":     title,
                            "url":       url,
                            "agency":    "NTIS",
                            "end_date":  "",
                            "post_date": post_date_str,
                            "raw_text":  f"{title} R&D university national science tech",
                        })
                    except Exception as row_err:
                        logger.debug("NTIS row parse error: %s", row_err)
                        continue

            except PlaywrightTimeout:
                logger.warning("NTIS page load timeout (30s)")
            finally:
                ctx.close()
                browser.close()

        logger.info("NTIS Playwright collected: %d items", len(notices))
        return notices
