# -*- coding: utf-8 -*-
"""
한국연구재단(NRF) 공모 수집기
============================================================
대학 R&D 지원사업 공고 수집 (신진연구, 중견연구, 기초연구 등)
URL: https://www.nrf.re.kr
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

NRF_BASE = "https://www.nrf.re.kr"


class NrfCollector:
    """한국연구재단 공모사업 수집기"""

    # 공모사업 목록 페이지들
    NOTICE_URLS = [
        {
            "name": "공모사업공고",
            "url":  f"{NRF_BASE}/biz/info/notice/list?menu_no=378",
        },
        {
            "name": "이달의공모",
            "url":  f"{NRF_BASE}/cms/page/main?menu_no=navi_10040",
        },
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        })

    def collect(self, days_back: int = 7) -> List[dict]:
        notices = []
        cutoff = datetime.now() - timedelta(days=days_back)

        for target in self.NOTICE_URLS:
            try:
                result = self._collect_from_url(target["url"], target["name"], cutoff)
                notices.extend(result)
                time.sleep(1)
            except Exception as e:
                logger.warning(f"NRF {target['name']} 수집 실패: {e}")

        # 중복 제거 (제목 기준)
        seen = set()
        unique = []
        for n in notices:
            key = n["title"]
            if key not in seen:
                seen.add(key)
                unique.append(n)

        logger.info(f"한국연구재단 수집 완료: {len(unique)}건")
        return unique

    def _collect_from_url(self, url: str, source_name: str, cutoff: datetime) -> List[dict]:
        notices = []

        for page in range(1, 6):  # 최대 5페이지
            try:
                page_url = f"{url}&pageIndex={page}" if "?" in url else f"{url}?pageIndex={page}"
                resp = self.session.get(page_url, timeout=15)
                resp.raise_for_status()
                resp.encoding = "utf-8"

                items, should_stop = self._parse_page(resp.text, source_name, cutoff)
                notices.extend(items)

                if should_stop or not items:
                    break

                time.sleep(0.8)

            except Exception as e:
                logger.warning(f"NRF 페이지 {page} 오류: {e}")
                break

        return notices

    def _parse_page(self, html: str, source_name: str, cutoff: datetime):
        soup = BeautifulSoup(html, "html.parser")
        items = []
        should_stop = False

        # 패턴 1: 표준 게시판 테이블
        rows = soup.select("table tbody tr, .board_list tbody tr")
        for row in rows:
            cols = row.select("td")
            if len(cols) < 3:
                continue

            a = row.select_one("td a[href], a.subject")
            if not a:
                continue

            title = a.get_text(strip=True)
            if not title or title in ("제목", "번호", "첨부"):
                continue

            href = a.get("href", "")
            full_url = self._make_url(href)

            # 날짜 추출 (마지막 컬럼 또는 날짜처럼 보이는 컬럼)
            post_date = ""
            end_date = ""
            for col in reversed(cols):
                text = col.get_text(strip=True)
                if len(text) == 10 and text[4] == "-" and text[7] == "-":
                    if not post_date:
                        post_date = text
                    elif not end_date:
                        end_date = text
                        break

            # 컷오프 날짜 확인
            if post_date:
                try:
                    pd = datetime.strptime(post_date[:10], "%Y-%m-%d")
                    if pd < cutoff:
                        should_stop = True
                        break
                except ValueError:
                    pass

            # 기관명 추출
            agency = ""
            for col in cols[1:3]:
                text = col.get_text(strip=True)
                if text and text != title and len(text) < 30:
                    agency = text
                    break

            items.append({
                "source":    f"연구재단-{source_name}",
                "title":     title,
                "url":       full_url,
                "agency":    agency or "한국연구재단",
                "end_date":  end_date,
                "post_date": post_date,
                "raw_text":  f"{title} 한국연구재단 {agency} 대학 연구 R&D",
            })

        # 패턴 2: 리스트형 (dl/dt/dd)
        if not items:
            for item in soup.select(".notice_list li, .list_type li, dl.list_box"):
                a = item.select_one("a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                if not title:
                    continue
                href = a.get("href", "")
                date_el = item.select_one(".date, .period, span")
                end_date = date_el.get_text(strip=True) if date_el else ""

                items.append({
                    "source":    f"연구재단-{source_name}",
                    "title":     title,
                    "url":       self._make_url(href),
                    "agency":    "한국연구재단",
                    "end_date":  end_date,
                    "post_date": "",
                    "raw_text":  f"{title} 한국연구재단 대학 연구",
                })

        return items, should_stop

    def _make_url(self, href: str) -> str:
        if not href:
            return NRF_BASE
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return f"{NRF_BASE}{href}"
        return f"{NRF_BASE}/{href}"
