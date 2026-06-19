# -*- coding: utf-8 -*-
"""
나라장터(G2B) 공모사업 수집기
============================================================
조달청 운영 - 대학 관련 위탁연구/용역/공모 공고 수집
URL: https://www.g2b.go.kr
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

G2B_BASE = "https://www.g2b.go.kr"


class G2bCollector:
    """나라장터 공모/용역 수집기"""

    # 공고 검색 API / 페이지
    SEARCH_URLS = [
        {
            "name": "일반공모",
            "url":  (
                "https://www.g2b.go.kr:8081/ep/tbid/tbBidList.do"
                "?bidSearchType=1&searchType=1&bidNm=공모"
            ),
        },
        {
            "name": "학술연구용역",
            "url":  (
                "https://www.g2b.go.kr:8081/ep/tbid/tbBidList.do"
                "?bidSearchType=1&searchType=1&bidNm=대학"
            ),
        },
    ]

    # 공공데이터포털 나라장터 API (키 없이 사용 가능한 공개 데이터)
    PUBLIC_DATA_URL = (
        "https://apis.data.go.kr/1230000/BidPublicInfoService04/"
        "getBidPblancListInfoServc01"
    )

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": G2B_BASE,
        })

    def collect(self, days_back: int = 3) -> List[dict]:
        notices = []

        # 방법 1: 공공데이터포털 API (API 키 있을 때)
        if self.api_key:
            try:
                notices = self._collect_via_api(days_back)
                if notices:
                    logger.info(f"나라장터 API 수집 완료: {len(notices)}건")
                    return notices
            except Exception as e:
                logger.warning(f"나라장터 API 실패 → 크롤링 전환: {e}")

        # 방법 2: 웹 크롤링
        for target in self.SEARCH_URLS:
            try:
                result = self._scrape_search(target["url"], target["name"], days_back)
                notices.extend(result)
                time.sleep(1)
            except Exception as e:
                logger.warning(f"나라장터 {target['name']} 크롤링 실패: {e}")

        # 중복 제거
        seen = set()
        unique = []
        for n in notices:
            if n["title"] not in seen:
                seen.add(n["title"])
                unique.append(n)

        logger.info(f"나라장터 수집 완료: {len(unique)}건")
        return unique

    def _collect_via_api(self, days_back: int) -> List[dict]:
        """공공데이터포털 나라장터 오픈API"""
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
        today = datetime.now().strftime("%Y%m%d")

        params = {
            "serviceKey": self.api_key,
            "numOfRows": 100,
            "pageNo": 1,
            "inqryBgnDt": cutoff,
            "inqryEndDt": today,
            "type": "json",
        }
        resp = self.session.get(self.PUBLIC_DATA_URL, params=params, timeout=15)
        data = resp.json()

        items = []
        body = data.get("response", {}).get("body", {})
        for item in body.get("items", []):
            items.append({
                "source":    "나라장터",
                "title":     item.get("bidNtceNm", ""),
                "url":       item.get("bidNtceUrl", G2B_BASE),
                "agency":    item.get("ntceInsttNm", ""),
                "end_date":  item.get("bidClseDt", ""),
                "post_date": item.get("bidNtceDt", "")[:10] if item.get("bidNtceDt") else "",
                "raw_text":  f"{item.get('bidNtceNm', '')} {item.get('ntceInsttNm', '')}",
            })
        return items

    def _scrape_search(self, url: str, source_name: str, days_back: int) -> List[dict]:
        """나라장터 검색 결과 크롤링"""
        notices = []
        cutoff = datetime.now() - timedelta(days=days_back)

        try:
            resp = self.session.get(url, timeout=20, verify=False)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")

            # 테이블 행 추출
            rows = soup.select("table tbody tr, .bid_list tbody tr")
            for row in rows:
                cols = row.select("td")
                if len(cols) < 3:
                    continue
                a = row.select_one("a")
                if not a:
                    continue

                title = a.get_text(strip=True)
                if not title or len(title) < 3:
                    continue

                href = a.get("href", "")
                full_url = f"{G2B_BASE}{href}" if href.startswith("/") else href or G2B_BASE

                # 날짜/기관 추출
                agency = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                end_date = cols[-1].get_text(strip=True) if cols else ""
                post_date = ""

                # 날짜 컬럼 찾기
                for col in cols:
                    text = col.get_text(strip=True)
                    if len(text) >= 10 and (text[4] == "-" or text[4] == "."):
                        post_date = text[:10].replace(".", "-")
                        break

                if post_date:
                    try:
                        pd = datetime.strptime(post_date[:10], "%Y-%m-%d")
                        if pd < cutoff:
                            break
                    except ValueError:
                        pass

                notices.append({
                    "source":    f"나라장터-{source_name}",
                    "title":     title,
                    "url":       full_url,
                    "agency":    agency,
                    "end_date":  end_date,
                    "post_date": post_date,
                    "raw_text":  f"{title} {agency} 공모 용역",
                })

        except Exception as e:
            logger.warning(f"나라장터 크롤링 오류 ({source_name}): {e}")

        return notices
