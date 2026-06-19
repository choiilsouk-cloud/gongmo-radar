# -*- coding: utf-8 -*-
"""
중앙행정기관 공모 수집기
============================================================
정부조직법 기준 전체 부처/처/청/위원회 공모사업 수집
config.yaml의 sources.ministries 목록을 읽어 동적 확장 가능

포함 기관 (기본값):
  부: 교육부, 과학기술정보통신부, 중소벤처기업부, 보건복지부, 문화체육관광부,
      고용노동부, 농림축산식품부, 환경부, 산업통상자원부, 국토교통부, 해양수산부
  처/청: 식품의약품안전처, 특허청, 농촌진흥청, 산림청
  위원회: 공정거래위원회, 금융위원회
  산하기관: 한국장학재단, 한국교육학술정보원, 한국교육개발원
  대학협력: 한국대학교육협의회
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
# 중앙행정기관 기본 수집 목록
# (name, url, css_selector, base_url)
# css_selector: None이면 자동 감지
# ────────────────────────────────────────────────────────────────
DEFAULT_MINISTRIES = [
    # ── 부 (Ministries) ────────────────────────────────────────
    {
        "name": "교육부",
        "url":  "https://www.moe.go.kr/boardCnts/list.do?boardID=316&m=030101",
        "base": "https://www.moe.go.kr",
        "sel":  "table tbody tr, .board_list tbody tr",
    },
    {
        "name": "과학기술정보통신부",
        "url":  "https://www.msit.go.kr/bbs/list.do?sCode=user&mId=100&mPid=99&bbsSeqNo=94",
        "base": "https://www.msit.go.kr",
        "sel":  "table tbody tr",
    },
    {
        "name": "중소벤처기업부",
        "url":  "https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=1221",
        "base": "https://www.mss.go.kr",
        "sel":  "tbody tr, .board_list tr",
    },
    {
        "name": "보건복지부",
        "url":  "https://www.mohw.go.kr/menu.es?mid=a10501020000",
        "base": "https://www.mohw.go.kr",
        "sel":  "table tbody tr",
    },
    {
        "name": "문화체육관광부",
        "url":  "https://www.mcst.go.kr/kor/s_notice/notice/noticeList.jsp",
        "base": "https://www.mcst.go.kr",
        "sel":  "tbody tr, table tbody tr",
    },
    {
        "name": "고용노동부",
        "url":  "https://www.moel.go.kr/info/publict/publictList.do",
        "base": "https://www.moel.go.kr",
        "sel":  "table tbody tr",
    },
    {
        "name": "농림축산식품부",
        "url":  "https://www.mafra.go.kr/sites/mafra/sub.do?menuId=mafra0100180000",
        "base": "https://www.mafra.go.kr",
        "sel":  "tbody tr",
    },
    {
        "name": "환경부",
        "url":  "https://www.me.go.kr/home/web/policy_data/read.do?menuId=10261&seq=",
        "base": "https://www.me.go.kr",
        "sel":  "table tbody tr, .board_list tbody tr",
    },
    {
        "name": "산업통상자원부",
        "url":  "https://www.motie.go.kr/motie/ne/presse/press2/bbs/bbsList.do?bbs_seq_n=161",
        "base": "https://www.motie.go.kr",
        "sel":  "tbody tr",
    },
    {
        "name": "국토교통부",
        "url":  "https://www.molit.go.kr/USR/NEWS/m_71/lst.jsp?id=2&searchKey=&searchWord=공모",
        "base": "https://www.molit.go.kr",
        "sel":  "tbody tr, ul.brd_list li",
    },
    {
        "name": "해양수산부",
        "url":  "https://www.mof.go.kr/synap/skin/doc.html?fn=boardfile",
        "base": "https://www.mof.go.kr",
        "sel":  "tbody tr",
    },
    # ── 처/청/위원회 ────────────────────────────────────────────
    {
        "name": "식품의약품안전처",
        "url":  "https://www.mfds.go.kr/bbs/index.do?q_bbsSeq=1&q_cmd=L",
        "base": "https://www.mfds.go.kr",
        "sel":  "tbody tr, table tbody tr",
    },
    {
        "name": "특허청",
        "url":  "https://www.kipo.go.kr/ko/kpoContentView.do?menuCd=SCD0200184",
        "base": "https://www.kipo.go.kr",
        "sel":  "tbody tr",
    },
    {
        "name": "농촌진흥청",
        "url":  "https://www.rda.go.kr/main/selectBbsNttList.do?bbsNo=1044&key=1050",
        "base": "https://www.rda.go.kr",
        "sel":  "tbody tr",
    },
    {
        "name": "공정거래위원회",
        "url":  "https://www.ftc.go.kr/www/selectBbsList.do?key=215",
        "base": "https://www.ftc.go.kr",
        "sel":  "tbody tr",
    },
    # ── 산하 주요기관 ────────────────────────────────────────────
    {
        "name": "한국장학재단",
        "url":  "https://www.kosaf.go.kr/ko/support.do?pg=support01_01_01",
        "base": "https://www.kosaf.go.kr",
        "sel":  "table tbody tr, .bbs_list tbody tr",
    },
    {
        "name": "한국교육학술정보원(KERIS)",
        "url":  "https://www.keris.or.kr/main/na/ntt/selectNttList.do?mi=1050&bbsId=1037",
        "base": "https://www.keris.or.kr",
        "sel":  "tbody tr",
    },
    {
        "name": "한국교육개발원(KEDI)",
        "url":  "https://www.kedi.re.kr/khome/main/research/selectPublicationList.do",
        "base": "https://www.kedi.re.kr",
        "sel":  "tbody tr, .board_list tr",
    },
    {
        "name": "한국대학교육협의회(대교협)",
        "url":  "https://www.kcue.or.kr/contents/?contPage=1&menuId=MN00001018",
        "base": "https://www.kcue.or.kr",
        "sel":  "tbody tr, .bbs_list li",
    },
    {
        "name": "국가평생교육진흥원",
        "url":  "https://www.nile.or.kr/contents/contents.jsp?menuId=MN20011&contId=CO20011",
        "base": "https://www.nile.or.kr",
        "sel":  "tbody tr",
    },
    {
        "name": "한국직업능력연구원(KRIVET)",
        "url":  "https://www.krivet.re.kr/ku/da/prKUDAGs.jsp",
        "base": "https://www.krivet.re.kr",
        "sel":  "tbody tr",
    },
]


class MinistryCollector:
    """중앙행정기관 공모 수집기 (설정 기반 확장형)"""

    def __init__(self, custom_ministries: Optional[List[dict]] = None):
        """
        custom_ministries: config.yaml의 sources.ministries 목록
          형식: [{"name": "기관명", "url": "...", "enabled": true}, ...]
        """
        self.targets = list(DEFAULT_MINISTRIES)

        # config의 추가 기관 병합
        if custom_ministries:
            existing_names = {t["name"] for t in self.targets}
            for m in custom_ministries:
                if not m.get("enabled", True):
                    continue
                if m.get("name") not in existing_names:
                    self.targets.append({
                        "name": m["name"],
                        "url":  m["url"],
                        "base": m.get("base", ""),
                        "sel":  m.get("sel", "tbody tr"),
                    })
                else:
                    # 기존 항목 활성화 여부 처리
                    pass

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9",
        })

    def collect(self, days_back: int = 7) -> List[dict]:
        all_notices = []
        cutoff = datetime.now() - timedelta(days=days_back)

        for target in self.targets:
            try:
                items = self._collect_one(target, cutoff)
                if items:
                    logger.info(f"{target['name']} 수집: {len(items)}건")
                    all_notices.extend(items)
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"{target['name']} 수집 실패: {e}")

        logger.info(f"중앙행정기관 전체 수집 완료: {len(all_notices)}건")
        return all_notices

    def _collect_one(self, target: dict, cutoff: datetime) -> List[dict]:
        try:
            resp = self.session.get(target["url"], timeout=15)
            resp.raise_for_status()
            resp.encoding = "utf-8"
        except Exception as e:
            logger.debug(f"{target['name']} 요청 실패: {e}")
            return []

        return self._parse(resp.text, target, cutoff)

    def _parse(self, html: str, target: dict, cutoff: datetime) -> List[dict]:
        soup = BeautifulSoup(html, "html.parser")
        notices = []

        # 셀렉터로 행 추출
        rows = soup.select(target.get("sel", "tbody tr"))

        # 셀렉터 실패시 자동 감지
        if not rows:
            rows = (
                soup.select("table tbody tr")
                or soup.select(".board_list li, .bbs_list li")
                or soup.select("ul.list_type li")
            )

        for row in rows:
            # 링크 있는 행만 처리
            a = row.select_one("a[href]")
            if not a:
                continue

            title = a.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            # 불필요한 행 스킵 (헤더 등)
            if title in ("제목", "번호", "첨부파일", "순번"):
                continue

            href = a.get("href", "")
            full_url = self._resolve_url(href, target.get("base", ""))

            # 날짜 추출
            post_date = ""
            end_date = ""
            cols = row.select("td, dd, span")
            for col in cols:
                text = col.get_text(strip=True)
                # YYYY-MM-DD 또는 YYYY.MM.DD 패턴
                if len(text) >= 10 and (
                    (text[4] == "-" and text[7] == "-") or
                    (text[4] == "." and text[7] == ".")
                ):
                    normalized = text[:10].replace(".", "-")
                    if not post_date:
                        post_date = normalized
                    elif not end_date:
                        end_date = normalized

            # 컷오프 확인 (날짜 있을 때만)
            if post_date:
                try:
                    pd = datetime.strptime(post_date[:10], "%Y-%m-%d")
                    if pd < cutoff:
                        continue  # 오래된 공고 스킵 (stop 아닌 continue: 순서 보장 안됨)
                except ValueError:
                    pass

            # 기관명
            agency = target["name"]

            notices.append({
                "source":    f"중앙부처-{target['name']}",
                "title":     title,
                "url":       full_url,
                "agency":    agency,
                "end_date":  end_date,
                "post_date": post_date,
                "raw_text":  f"{title} {agency} 공모 지원사업 대학",
            })

        return notices[:20]  # 기관당 최대 20건

    def _resolve_url(self, href: str, base: str) -> str:
        if not href:
            return base
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return f"{base}{href}"
        if href.startswith("..") or href.startswith("."):
            return f"{base}/{href}"
        return f"{base}/{href}"
