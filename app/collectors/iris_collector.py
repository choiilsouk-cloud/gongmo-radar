"""
IRIS 수집기 - 범부처 통합연구지원시스템
============================================================
전 부처 R&D 공고 통합 수집 (교육부, 과기부, 산업부 등 모두 포함)
API 우선 → 실패 시 크롤링 폴백
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

IRIS_BASE = "https://www.iris.go.kr"


class IrisCollector:
    """IRIS 공고 수집기"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            )
        })

    def collect(self, days_back: int = 3) -> List[dict]:
        """
        최근 N일 공고 수집
        Returns: 공고 dict 리스트
        """
        notices = []
        try:
            notices = self._collect_via_scraping(days_back)
            logger.info(f"IRIS 수집 완료: {len(notices)}건")
        except Exception as e:
            logger.error(f"IRIS 수집 오류: {e}")
        return notices

    def _collect_via_scraping(self, days_back: int) -> List[dict]:
        """IRIS 공고 게시판 크롤링"""
        notices = []
        page = 1
        cutoff = datetime.now() - timedelta(days=days_back)

        while page <= 10:  # 최대 10페이지
            url = (
                f"{IRIS_BASE}/IRIS/CM/10000/selectPbancList.do"
                f"?pageIndex={page}&recordCountPerPage=20"
                f"&pbancSeCd=&srchKwd="
            )
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                items, should_stop = self._parse_list_page(
                    resp.text, cutoff
                )
                notices.extend(items)
                if should_stop or not items:
                    break
                page += 1
                time.sleep(1)  # 서버 부하 방지
            except Exception as e:
                logger.warning(f"IRIS 페이지 {page} 수집 실패: {e}")
                break

        return notices

    def _parse_list_page(
        self, html: str, cutoff: datetime
    ) -> tuple[List[dict], bool]:
        soup = BeautifulSoup(html, "html.parser")
        items = []
        should_stop = False

        rows = soup.select("table tbody tr")
        for row in rows:
            cols = row.select("td")
            if len(cols) < 5:
                continue

            title_el = row.select_one("td a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            href  = title_el.get("href", "")
            agency = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            end_date_str = cols[4].get_text(strip=True) if len(cols) > 4 else ""
            post_date_str = cols[-1].get_text(strip=True)

            # 날짜 파싱
            try:
                post_date = datetime.strptime(post_date_str[:10], "%Y-%m-%d")
                if post_date < cutoff:
                    should_stop = True
                    break
            except ValueError:
                pass

            full_url = (
                f"{IRIS_BASE}{href}"
                if href.startswith("/") else href
            )

            items.append({
                "source":    "IRIS",
                "title":     title,
                "url":       full_url,
                "agency":    agency,
                "end_date":  end_date_str,
                "post_date": post_date_str,
                "raw_text":  f"{title} {agency}",  # 상세 수집 전 기본값
            })

        return items, should_stop


class BojocollectorWrapper:
    """e나라도움 보조금 공모 수집기

    api_key 설정 시: 공공데이터포털 보조사업자 모집공고 API (안정적)
    api_key 미설정: e나라도움 웹 크롤링 폴백
    """

    BASE = "https://www.gosims.go.kr"
    # 공공데이터포털 보조사업자 모집공고 목록 조회 서비스
    API_URL = (
        "https://apis.data.go.kr/1741000/pubBizBidPblancInfo"
        "/getPubBizBidPblancList"
    )

    def __init__(self, api_key: str = ""):
        self.api_key = (api_key or "").strip()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; GongmoRadar/1.0)"
        })

    def collect(self, days_back: int = 3) -> List[dict]:
        notices = []
        try:
            if self.api_key:
                notices = self._try_public_api(days_back)
            if not notices:
                notices = self._scrape_fallback(days_back)
            logger.info(f"e나라도움 수집 완료: {len(notices)}건")
        except Exception as e:
            logger.error(f"e나라도움 수집 오류: {e}")
        return notices

    def _try_public_api(self, days_back: int) -> List[dict]:
        """공공데이터포털 보조사업자 모집공고 API (data_go_kr_api_key 필요)"""
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
        today  = datetime.now().strftime("%Y%m%d")
        params = {
            "serviceKey": self.api_key,
            "numOfRows":  100,
            "pageNo":     1,
            "type":       "json",
            "pbancBgngYmd": cutoff,
            "pbancEndYmd":  today,
        }
        try:
            resp = self.session.get(self.API_URL, params=params, timeout=15)
            data = resp.json()
            items = (
                data.get("response", {}).get("body", {}).get("items", [])
                or data.get("items", [])
                or []
            )
            notices = []
            for item in items:
                title = item.get("pbancNm") or item.get("bizNm") or ""
                if not title:
                    continue
                notices.append({
                    "source":    "e나라도움",
                    "title":     title,
                    "url":       item.get("pbancUrl") or self.BASE,
                    "agency":    item.get("cntrwkInsttNm") or item.get("insttNm") or "",
                    "end_date":  self._fmt_date(item.get("rcptEndYmd") or ""),
                    "post_date": self._fmt_date(item.get("pbancBgngYmd") or ""),
                    "raw_text":  f"{title} {item.get('cntrwkInsttNm', '')} 보조사업 공모",
                })
            logger.info(f"e나라도움 API 수집: {len(notices)}건")
            return notices
        except Exception as e:
            logger.warning(f"e나라도움 API 실패 → 크롤링 전환: {e}")
            return []

    @staticmethod
    def _fmt_date(raw: str) -> str:
        d = "".join(c for c in (raw or "") if c.isdigit())
        if len(d) == 8:
            return f"{d[:4]}-{d[4:6]}-{d[6:]}"
        return raw

    def _scrape_fallback(self, days_back: int) -> List[dict]:
        """e나라도움 공모 게시판 크롤링"""
        notices = []
        try:
            url = f"{self.BASE}/gosims/pg/pblBidPblanc/selectPblBidPblancList.do"
            resp = self.session.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            for row in soup.select("tbody tr")[:20]:
                cols = row.select("td")
                if len(cols) < 4:
                    continue
                title_el = row.select_one("a")
                if not title_el:
                    continue
                notices.append({
                    "source":   "e나라도움",
                    "title":    title_el.get_text(strip=True),
                    "url":      f"{self.BASE}{title_el.get('href', '')}",
                    "agency":   cols[1].get_text(strip=True) if len(cols) > 1 else "",
                    "end_date": cols[3].get_text(strip=True) if len(cols) > 3 else "",
                    "raw_text": title_el.get_text(strip=True),
                })
        except Exception as e:
            logger.warning(f"e나라도움 크롤링 실패: {e}")
        return notices


class BizinfoCollector:
    """기업마당 지원사업 수집기"""

    API_BASE = "https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C128/AS/74/list.do"

    def __init__(self):
        self.session = requests.Session()

    def collect(self, days_back: int = 3) -> List[dict]:
        notices = []
        try:
            resp = self.session.get(
                self.API_BASE,
                params={"pageIndex": 1, "recordCountPerPage": 30},
                timeout=15
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.select(".board_list tbody tr")[:20]:
                title_el = row.select_one("td.title a, td a")
                if not title_el:
                    continue
                cols = row.select("td")
                notices.append({
                    "source":   "기업마당",
                    "title":    title_el.get_text(strip=True),
                    "url":      "https://www.bizinfo.go.kr" + title_el.get("href", ""),
                    "agency":   cols[1].get_text(strip=True) if len(cols) > 1 else "",
                    "end_date": cols[-1].get_text(strip=True),
                    "raw_text": title_el.get_text(strip=True),
                })
            logger.info(f"기업마당 수집 완료: {len(notices)}건")
        except Exception as e:
            logger.error(f"기업마당 수집 오류: {e}")
        return notices


class RegionalCollector:
    """지자체 공고 수집기 (충남도청, 서산시, 충남교육청)"""

    TARGETS = [
        {
            "name": "충청남도청",
            "url":  "https://www.chungnam.go.kr/cnnet/bbs/list.do?mId=0401030000",
            "tag":  ".bbs_list tbody tr",
        },
        {
            "name": "서산시청",
            "url":  "https://www.seosan.go.kr/www/bbs/list.do?mId=0301010000",
            "tag":  ".bbs_list tbody tr",
        },
        {
            "name": "충남교육청",
            "url":  "https://www.cne.go.kr/bbs/list.do?mId=0401010000",
            "tag":  "tbody tr",
        },
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; GongmoRadar/1.0)"
        })

    def collect(self) -> List[dict]:
        notices = []
        for target in self.TARGETS:
            try:
                resp = self.session.get(target["url"], timeout=15)
                resp.encoding = "utf-8"
                soup = BeautifulSoup(resp.text, "html.parser")
                for row in soup.select(target["tag"])[:15]:
                    a = row.select_one("a")
                    if not a:
                        continue
                    notices.append({
                        "source":   target["name"],
                        "title":    a.get_text(strip=True),
                        "url":      a.get("href", ""),
                        "agency":   target["name"],
                        "raw_text": a.get_text(strip=True),
                    })
                logger.info(f"{target['name']} 수집: {len(notices)}건")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"{target['name']} 수집 실패: {e}")
        return notices
