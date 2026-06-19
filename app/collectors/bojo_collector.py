# -*- coding: utf-8 -*-
"""
보조금통합포털(bojo.go.kr) 공모사업 수집기
============================================================
행정안전부 보조금통합포털 공모사업 공고 수집
URL: https://www.bojo.go.kr/hg/hg002/retrieveTaskReqstList.do
Open API: https://www.bojo.go.kr/ga/retrieveOpnApi.do

대학 지원 가능한 비영리 보조금 사업 위주 수집.
"""

import logging
import time
from typing import List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BOJO_BASE = "https://www.bojo.go.kr"
BOJO_LIST = f"{BOJO_BASE}/hg/hg002/retrieveTaskReqstList.do"


class BojoCollector:
    """보조금통합포털 공모사업 수집기"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": BOJO_BASE,
        })

    def collect(self) -> List[dict]:
        """보조금통합포털 공모 목록 수집"""
        notices = []
        try:
            notices.extend(self._fetch_list_page(1))
            notices.extend(self._fetch_list_page(2))
            logger.info("[BojoCollector] 수집 완료: %d건", len(notices))
        except Exception as e:
            logger.error("[BojoCollector] 수집 오류: %s", e)
        return notices

    def _fetch_list_page(self, page: int) -> List[dict]:
        """목록 페이지 파싱"""
        params = {
            "pageIndex": page,
            "searchGbnCd": "",     # 전체
            "searchWrd": "",
        }
        try:
            resp = self.session.get(BOJO_LIST, params=params, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            return self._parse_list(soup)
        except Exception as e:
            logger.warning("[BojoCollector] 페이지 %d 실패: %s", page, e)
            return []

    def _parse_list(self, soup: BeautifulSoup) -> List[dict]:
        """HTML 목록 파싱 → notice dict 리스트"""
        results = []
        # 보조금포털 목록 테이블 행
        rows = soup.select("table tbody tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue
            try:
                # 컬럼 순서: 번호 | 사업명 | 주관기관 | 신청기간 | 상태
                title_tag = row.select_one("td a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                href  = title_tag.get("href", "")
                url   = href if href.startswith("http") else BOJO_BASE + href

                agency   = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                period   = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                end_date = period.split("~")[-1].strip() if "~" in period else ""

                if not title:
                    continue

                results.append({
                    "source":   "보조금포털",
                    "title":    title,
                    "url":      url,
                    "agency":   agency,
                    "end_date": end_date,
                    "post_date": "",
                    "raw_text": f"{title} {agency} {period}",
                })
            except Exception as e:
                logger.debug("[BojoCollector] 행 파싱 오류: %s", e)
        return results
