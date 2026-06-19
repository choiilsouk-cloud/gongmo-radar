# -*- coding: utf-8 -*-
"""
health_checker.py - D-plan Layer 3: pre-collection health check
================================================================
Checks each collector's base URL before collection:
  HEALTHY  : HTTP 200 + keyword found
  DEGRADED : HTTP 200 but keyword missing (site may have changed)
  DOWN     : connection error / timeout / non-200

Usage (standalone):
    from app.health_checker import HealthChecker
    results = HealthChecker().run_all()
    # [{"source": "IRIS", "status": "HEALTHY", "latency_ms": 312, "detail": "..."}, ...]
"""

import logging
import time
import urllib.request
import urllib.error
from typing import Dict, List

logger = logging.getLogger(__name__)

# ── 각 수집기 헬스체크 정의 ─────────────────────────────────────────
# (URL, [keyword_list], timeout_sec)
SOURCE_CHECKS: Dict[str, tuple] = {
    "IRIS": (
        "https://www.iris.go.kr/contents/retrieveBsnsAncmInfoList.do",
        ["공고", "사업", "IRIS", "bsns"],
        10,
    ),
    "NRF": (
        "https://www.nrf.re.kr/biz/notice/notice01/list",
        ["공고", "연구", "한국연구재단", "nrf"],
        10,
    ),
    "Bojo": (
        "https://www.gosims.go.kr/gw/gwe/main.do",
        ["보조금", "지원사업", "gosims"],
        10,
    ),
    "Bizinfo": (
        "https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C128/AS/74/list.do",
        ["공모", "지원", "bizinfo", "중소기업"],
        10,
    ),
    "G2B": (
        "https://www.g2b.go.kr",
        ["나라장터", "g2b", "입찰"],
        10,
    ),
    "Ministry": (
        "https://www.moe.go.kr",
        ["교육부", "공고", "moe"],
        10,
    ),
    "KStartup": (
        "https://www.k-startup.go.kr",
        ["창업", "k-startup", "지원"],
        10,
    ),
    "NTIS": (
        "https://www.ntis.go.kr",
        ["ntis", "국가과학기술", "R&D"],
        10,
    ),
}

# 상태 상수
HEALTHY  = "HEALTHY"
DEGRADED = "DEGRADED"
DOWN     = "DOWN"
SKIP     = "SKIP"      # 수집 비활성 시


class HealthChecker:
    """수집기 URL 사전 점검 클래스."""

    def __init__(self, timeout_override: int = None):
        self.timeout_override = timeout_override

    def check(self, source: str) -> dict:
        """단일 수집기 헬스체크."""
        if source not in SOURCE_CHECKS:
            return {
                "source": source,
                "status": SKIP,
                "latency_ms": 0,
                "detail": "No health-check definition",
            }

        url, keywords, timeout = SOURCE_CHECKS[source]
        if self.timeout_override:
            timeout = self.timeout_override

        t0 = time.time()
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "ko-KR,ko;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                latency_ms = int((time.time() - t0) * 1000)
                http_status = resp.status

                if http_status != 200:
                    return {
                        "source": source,
                        "status": DOWN,
                        "latency_ms": latency_ms,
                        "detail": f"HTTP {http_status}",
                    }

                # 본문 키워드 확인 (첫 32KB만)
                raw = resp.read(32768)
                try:
                    body = raw.decode("utf-8", errors="ignore")
                except Exception:
                    body = raw.decode("euc-kr", errors="ignore")

                body_lower = body.lower()
                found = any(kw.lower() in body_lower for kw in keywords)

                status = HEALTHY if found else DEGRADED
                detail = (
                    f"OK ({latency_ms}ms)"
                    if found
                    else f"Keywords not found: {keywords[:2]} - site may have changed"
                )

                logger.info("[HealthCheck] %s -> %s (%dms)", source, status, latency_ms)
                return {
                    "source": source,
                    "status": status,
                    "latency_ms": latency_ms,
                    "detail": detail,
                }

        except urllib.error.URLError as e:
            latency_ms = int((time.time() - t0) * 1000)
            detail = f"URLError: {e.reason}"
            logger.warning("[HealthCheck] %s -> DOWN: %s", source, detail)
            return {"source": source, "status": DOWN, "latency_ms": latency_ms, "detail": detail}
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            detail = f"{type(e).__name__}: {e}"
            logger.warning("[HealthCheck] %s -> DOWN: %s", source, detail)
            return {"source": source, "status": DOWN, "latency_ms": latency_ms, "detail": detail}

    def run_all(self, active_sources: List[str] = None) -> List[dict]:
        """
        모든(또는 지정) 수집기 헬스체크.
        active_sources: None -> SOURCE_CHECKS 전부
        """
        targets = active_sources if active_sources else list(SOURCE_CHECKS.keys())
        results = []
        for src in targets:
            r = self.check(src)
            results.append(r)
        return results

    def run_active_from_config(self, sources_cfg: dict) -> List[dict]:
        """
        config.yaml sources 섹션 기반으로 활성 수집기만 체크.
        sources_cfg: {"iris": True, "nrf": False, ...}
        """
        # config key -> source name 매핑
        key_to_name = {
            "iris": "IRIS",
            "nrf": "NRF",
            "bojo": "Bojo",
            "bizinfo": "Bizinfo",
            "g2b": "G2B",
            "ministry": "Ministry",
            "kstartup": "KStartup",
            "ntis": "NTIS",
        }
        active = [
            name
            for key, name in key_to_name.items()
            if sources_cfg.get(key, True)
        ]
        return self.run_all(active)


def status_emoji(status: str) -> str:
    """상태 이모지 반환 (GUI / 이메일 공용)."""
    return {"HEALTHY": "✅", "DEGRADED": "⚠️", "DOWN": "❌", "SKIP": "⏸"}.get(status, "❓")
