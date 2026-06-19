# -*- coding: utf-8 -*-
"""
중소벤처기업부(mss.go.kr) 사업공고 수집기
============================================================
중소기업·스타트업·대학 창업 지원 관련 공고 수집
URL: https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=310

대학이 신청 가능한 산학협력·창업·R&D 지원사업 포함.
"""

import logging
from typing import List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MSS_BASE = "https://www.mss.go.kr"
MSS_LIST = f"{MSS_BASE}/site/smba/ex/bbs/List.do"


class MssCollector:
    """중소벤처기업부 사업공고 수집기"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9",
        })

    def collect(self) -> List[dict]:
        """중소벤처기업부 공모 목록 수집"""
        notices = []
        # cbIdx=310: 사업공고 게시판
        for cb_idx in [310, 311]:
            try:
                items = self._fetch_board(cb_idx, page=1)
                items += self._fetch_board(cb_idx, page=2)
                notices.extend(items)
            except Exception as e:
                logger.error("[MssCollector] 게시판 %d 수집 오류: %s", cb_idx, e)
        logger.info("[MssCollector] 수집 완료: %d건", len(notices))
        return notices

    def _fetch_board(self, cb_idx: int, page: int) -> List[dict]:
        params = {
            "cbIdx": cb_idx,
            "pageIndex": page,
        }
        try:
            resp = self.session.get(MSS_LIST, params=params, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            return self._parse(soup)
        except Exception as e:
            logger.warning("[MssCollector] cbIdx=%d page=%d 실패: %s", cb_idx, page, e)
            return []

    def _parse(self, soup: BeautifulSoup) -> List[dict]:
        results = []
        for row in soup.select("table.board_list tbody tr, ul.board_list li"):
            try:
                a_tag = row.select_one("a")
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                href  = a_tag.get("href", "")
                url   = href if href.startswith("http") else MSS_BASE + href

                cols = row.find_all("td")
                end_date  = ""
                post_date = ""
                if len(cols) >= 4:
                    end_date  = cols[-2].get_text(strip=True)
                    post_date = cols[-1].get_text(strip=True)

                if not title or title in ("번호", "제목", "등록일"):
                    continue

                results.append({
                    "source":   "중소벤처기업부",
                    "title":    title,
                    "url":      url,
                    "agency":   "중소벤처기업부",
                    "end_date": end_date,
                    "post_date": post_date,
                    "raw_text": f"{title} 중소벤처기업부 {end_date}",
                })
            except Exception as e:
                logger.debug("[MssCollector] 행 파싱 오류: %s", e)
        return results
