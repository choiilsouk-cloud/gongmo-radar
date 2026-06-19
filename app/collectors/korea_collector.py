# -*- coding: utf-8 -*-
"""
정부공모사업알리미(korea.kr) 공모사업 수집기
============================================================
문화체육관광부 대한민국 정부 공식 포털 공모사업 알리미
URL: https://www.korea.kr/special/govGongmoList.do

각 부처·지자체·공공기관 공모사업을 한곳에서 수집.
대학이 주관·참여기관으로 신청 가능한 공고 다수 포함.
"""

import logging
import re
from typing import List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

KOREA_BASE = "https://www.korea.kr"
KOREA_LIST = f"{KOREA_BASE}/special/govGongmoList.do"


class KoreaGovCollector:
    """정부공모사업알리미 수집기"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": KOREA_BASE,
        })

    def collect(self) -> List[dict]:
        """정부공모사업알리미 공모 목록 수집"""
        notices = []
        for page in range(1, 4):   # 최근 3페이지 (약 60건)
            try:
                items = self._fetch_page(page)
                if not items:
                    break
                notices.extend(items)
            except Exception as e:
                logger.error("[KoreaGov] 페이지 %d 수집 오류: %s", page, e)
                break
        logger.info("[KoreaGov] 수집 완료: %d건", len(notices))
        return notices

    def _fetch_page(self, page: int) -> List[dict]:
        params = {
            "pageIndex": page,
            "srchStatus": "",     # 전체 상태
            "srchField":  "",
            "srchText":   "",
        }
        try:
            resp = self.session.get(KOREA_LIST, params=params, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            return self._parse(soup)
        except Exception as e:
            logger.warning("[KoreaGov] 페이지 %d 실패: %s", page, e)
            return []

    def _parse(self, soup: BeautifulSoup) -> List[dict]:
        results = []
        # korea.kr 공모 목록: 카드형 또는 테이블형
        items = soup.select(
            "ul.board_list li, "
            "div.gongmo_list .item, "
            "table tbody tr"
        )
        for item in items:
            try:
                a_tag = item.select_one("a")
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                href = a_tag.get("href", "")
                url  = href if href.startswith("http") else KOREA_BASE + href

                # 기관명, 기간 추출
                agency   = ""
                end_date = ""
                for span in item.select("span, td"):
                    text = span.get_text(strip=True)
                    if re.search(r"부$|처$|청$|원$|공단$|재단$", text) and len(text) < 30:
                        agency = text
                    if re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", text):
                        dates = re.findall(r"\d{4}[-./]\d{2}[-./]\d{2}", text)
                        end_date = dates[-1].replace(".", "-").replace("/", "-")

                results.append({
                    "source":    "정부공모알리미",
                    "title":     title,
                    "url":       url,
                    "agency":    agency,
                    "end_date":  end_date,
                    "post_date": "",
                    "raw_text":  f"{title} {agency} {end_date}",
                })
            except Exception as e:
                logger.debug("[KoreaGov] 항목 파싱 오류: %s", e)
        return results
