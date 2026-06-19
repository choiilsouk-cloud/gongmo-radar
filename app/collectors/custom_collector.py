# -*- coding: utf-8 -*-
"""
custom_collector.py - 사용자 정의 수집기
============================================================
custom_sources.json 파일에서 사용자가 추가한 수집처를 동적 로드
GUI에서 수집처 추가/삭제/활성화 관리
"""

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from typing import List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# PyInstaller --onefile 환경에서는 __file__이 임시 추출 디렉터리를 가리키므로
# sys.executable(실행 파일 위치) 기준으로 경로를 계산한다.
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

CUSTOM_SOURCES_FILE = os.path.join(_BASE_DIR, "custom_sources.json")


class CustomCollector:
    """사용자 정의 URL 수집기"""

    def __init__(self, sources_file: str = CUSTOM_SOURCES_FILE):
        self.sources_file = sources_file
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9",
        })

    def load_sources(self) -> List[dict]:
        if not os.path.exists(self.sources_file):
            return []
        try:
            with open(self.sources_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("사용자 정의 수집처 로드 실패: %s", e)
            return []

    def save_sources(self, sources: List[dict]) -> bool:
        try:
            with open(self.sources_file, "w", encoding="utf-8") as f:
                json.dump(sources, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("사용자 정의 수집처 저장 실패: %s", e)
            return False

    def add_source(self, name: str, url: str,
                   base_url: str = "", selector: str = "tbody tr, li") -> dict:
        sources = self.load_sources()
        new_source = {
            "id":       str(uuid.uuid4())[:8],
            "name":     name,
            "url":      url,
            "base_url": base_url or self._extract_base(url),
            "selector": selector,
            "enabled":  True,
            "added_at": datetime.now().strftime("%Y-%m-%d"),
        }
        sources.append(new_source)
        self.save_sources(sources)
        return new_source

    def remove_source(self, source_id: str) -> bool:
        sources = self.load_sources()
        sources = [s for s in sources if s.get("id") != source_id]
        return self.save_sources(sources)

    def toggle_source(self, source_id: str) -> bool:
        sources = self.load_sources()
        for s in sources:
            if s.get("id") == source_id:
                s["enabled"] = not s.get("enabled", True)
                break
        return self.save_sources(sources)

    def collect(self, days_back: int = 7) -> List[dict]:
        sources = self.load_sources()
        enabled = [s for s in sources if s.get("enabled", True)]
        if not enabled:
            return []
        all_notices = []
        cutoff = datetime.now() - timedelta(days=days_back)
        for source in enabled:
            try:
                items = self._collect_one(source, cutoff)
                logger.info("[CustomCollector] %s: %d건", source["name"], len(items))
                all_notices.extend(items)
                time.sleep(0.8)
            except Exception as e:
                logger.warning("[CustomCollector] %s 실패: %s", source["name"], e)
        return all_notices

    def _collect_one(self, source: dict, cutoff: datetime) -> List[dict]:
        url = source["url"]
        base = source.get("base_url", "") or self._extract_base(url)
        selector = source.get("selector", "tbody tr, li")
        name = source["name"]
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            resp.encoding = "utf-8"
        except Exception as e:
            logger.warning("%s 접근 실패: %s", name, e)
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select(selector)
        if not rows:
            rows = (
                soup.select("table tbody tr")
                or soup.select(".board_list li, .bbs_list li, ul.list li")
                or []
            )
        notices = []
        for row in rows[:30]:
            a = row.select_one("a[href]")
            if not a:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 3:
                continue
            href = a.get("href", "")
            full_url = self._resolve_url(href, base)
            post_date = ""
            for el in row.select("td, dd, span, p"):
                text = el.get_text(strip=True)
                if len(text) >= 10 and (
                    (text[4] == "-" and text[7] == "-") or
                    (text[4] == "." and text[7] == ".")
                ):
                    post_date = text[:10].replace(".", "-")
                    break
            notices.append({
                "source":    "Custom-" + name,
                "title":     title,
                "url":       full_url,
                "agency":    name,
                "end_date":  "",
                "post_date": post_date,
                "raw_text":  title + " " + name,
            })
        return notices

    def _extract_base(self, url: str) -> str:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.scheme + "://" + parsed.netloc
        except Exception:
            return ""

    def _resolve_url(self, href: str, base: str) -> str:
        if not href:
            return base
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return base + href
        return base + "/" + href
