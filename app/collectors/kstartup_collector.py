# -*- coding: utf-8 -*-
"""
kstartup_collector.py - K-Startup 창업지원 공고 수집기
============================================================
k-skill-proxy (https://k-skill-proxy.nomadamas.org) 경유로
공공데이터포털 K-Startup API를 API 키 없이 조회한다.

API 키가 config에 설정된 경우 공공데이터포털 직접 호출도 지원.

출처: https://github.com/NomaDamas/k-skill (MIT License)
데이터셋: 공공데이터포털 15125364
  - endpoint: getAnnouncementInformation01
  - proxy: https://k-skill-proxy.nomadamas.org/v1/kstartup/announcements
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

# k-skill 커뮤니티 프록시 - API 키를 서버측에서 주입 (사용자 키 불필요)
_PROXY_BASE = "https://k-skill-proxy.nomadamas.org/v1/kstartup"
# 직접 호출 시 공공데이터포털 endpoint (API 키 필요)
_DIRECT_BASE = "https://apis.data.go.kr/B552735/kisedKstartupService01"

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "gongmo-radar/2.0 (Hanseo University IR)",
}


class KstartupCollector:
    """
    K-Startup 창업지원 공고 수집기.

    api_key 미설정 -> k-skill-proxy 경유 (API 키 불필요, 커뮤니티 무료 프록시)
    api_key 설정   -> 공공데이터포털 직접 호출 (안정적, 일 10,000건 한도)
    """

    def __init__(self, api_key: str = ""):
        self.api_key = api_key.strip()

    def collect(self, days_back: int = 7) -> List[dict]:
        """모집 중인 창업지원 공고를 수집해 표준 notice dict 리스트로 반환."""
        mode = "직접" if self.api_key else "프록시(키불필요)"
        logger.info("K-Startup 수집 시작 [%s] days_back=%d", mode, days_back)
        try:
            return self._collect(days_back)
        except Exception as exc:
            logger.error("K-Startup 수집 실패: %s", exc)
            return []

    def _collect(self, days_back: int) -> List[dict]:
        # rcrt_prgs_yn=Y 로 "현재 모집 중" 필터링이 이미 적용됨
        # post_date cutoff는 사용하지 않음 (오래 전 공고된 장기 모집 공고 포함 필요)
        all_notices = []
        page = 1

        while True:
            payload = self._fetch_page(page, per_page=100)
            if not payload:
                break

            items = payload.get("data") or []
            if not items:
                break

            for item in items:
                notice = self._parse(item)
                if notice:
                    all_notices.append(notice)

            total = int(payload.get("totalCount") or payload.get("matchCount") or 0)
            current_count = int(payload.get("currentCount") or len(items))
            if total == 0 or page * 100 >= total or current_count < 100:
                break
            page += 1

        logger.info("K-Startup 수집 완료: %d건 (days_back=%d)", len(all_notices), days_back)
        return all_notices

    def _fetch_page(self, page: int, per_page: int = 100) -> Optional[dict]:
        params = {
            "page": page,
            "perPage": per_page,
            "returnType": "json",
            "rcrt_prgs_yn": "Y",
        }

        if self.api_key:
            params["ServiceKey"] = self.api_key
            qs = urllib.parse.urlencode(params)
            url = "{}/getAnnouncementInformation01?{}".format(_DIRECT_BASE, qs)
        else:
            qs = urllib.parse.urlencode(params)
            url = "{}/announcements?{}".format(_PROXY_BASE, qs)

        req = urllib.request.Request(url, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            logger.warning("K-Startup HTTP %s: %s", e.code, url[:80])
            return None
        except Exception as e:
            logger.warning("K-Startup 요청 실패: %s", e)
            return None

    def _parse(self, item: dict) -> Optional[dict]:
        title = (
            item.get("biz_pbanc_nm") or item.get("intg_pbanc_biz_nm") or ""
        ).strip()
        if not title:
            return None

        raw_end = item.get("pbanc_rcpt_end_dt") or ""
        raw_start = item.get("pbanc_rcpt_bgng_dt") or ""
        end_date = self._fmt_date(raw_end)
        post_date = self._fmt_date(raw_start)

        detail_url = (
            item.get("detl_pg_url") or item.get("biz_aply_url")
            or "https://www.k-startup.go.kr"
        )
        agency = (
            item.get("sprv_inst") or item.get("pbanc_ntrp_nm") or "창업진흥원"
        ).strip()
        region = item.get("supt_regin", "").strip()
        target = item.get("aply_trgt", "").strip()

        raw_text = " ".join(filter(None, [
            title, agency, region, target,
            item.get("supt_biz_clsfc", ""),
            (item.get("pbanc_ctnt") or "")[:200],
        ]))

        return {
            "source":    "K-Startup",
            "title":     title,
            "url":       detail_url,
            "agency":    agency,
            "end_date":  end_date,
            "post_date": post_date,
            "region":    region,
            "raw_text":  raw_text,
        }

    @staticmethod
    def _fmt_date(raw: str) -> str:
        digits = "".join(c for c in (raw or "") if c.isdigit())
        if len(digits) == 8:
            return "{}-{}-{}".format(digits[:4], digits[4:6], digits[6:])
        return raw
