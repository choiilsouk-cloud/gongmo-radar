# -*- coding: utf-8 -*-
"""
collection.py — 공고 수집 엔진 (단일 책임: 수집 + 수집 이상 알림)
scheduler.py 에서 import 하여 사용.
"""
import logging
from datetime import date

from app.analyzers.matcher import DepartmentMatcher
from app.collectors.iris_collector import BizinfoCollector, BojocollectorWrapper, IrisCollector, RegionalCollector
from app.collectors.nrf_collector import NrfCollector
from app.collectors.g2b_collector import G2bCollector
from app.collectors.ministry_collector import MinistryCollector
from app.collectors.custom_collector import CustomCollector, CUSTOM_SOURCES_FILE
from app.collectors.ntis_collector import NtisCollector
from app.collectors.kstartup_collector import KstartupCollector
from app.git_sync import git_push
from app.health_checker import HealthChecker
from app.notifier.telegram import TelegramNotifier
from app.notifier.email_notifier import EmailNotifier

logger = logging.getLogger(__name__)

def _send_collection_alert(config, failed_sources, zero_sources, total):
    """수집 이상 감지 시 관리자 이메일 발송 (C8: 모니터링 알림)

    config.yaml에 admin_alert_email 설정 시 이상 발생 때 자동 발송.
    미설정 시 로그만 기록.
    """
    try:
        from app.notifier.email_sender import EmailNotifier
        admin_email = (
            config.get("admin_alert_email")
            or config.get("email", {}).get("sender_email", "")
        )
        if not admin_email or not config.get("email", {}).get("enabled"):
            logger.warning("관리자 이메일 미설정 또는 이메일 비활성 — 수집 이상 알림 로그만 기록")
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        text_lines = [
            f"[공모레이더] 수집 이상 감지 — {now_str}",
            f"총 수집 건수: {total}건",
        ]
        if failed_sources:
            text_lines.append(f"수집 실패 소스: {', '.join(failed_sources)}")
        if zero_sources:
            text_lines.append(f"0건 수집 소스: {', '.join(zero_sources)}")
        text_lines.append("data/gongmo.log 파일을 확인하세요.")

        body_text = "\n".join(text_lines)
        body_html = "<br>".join(text_lines)

        notifier = EmailNotifier(config)
        notifier._send(
            to_list=[admin_email],
            subject=f"[공모레이더 경고] 수집 이상 감지 {now_str}",
            html=body_html,
            text=body_text,
        )
        logger.info("수집 이상 관리자 알림 발송: %s", admin_email)
    except Exception as e:
        logger.warning("관리자 알림 발송 실패: %s", e)


def _check_and_alert_zeros(config, db, collect_stats: dict, today: str):
    """D안 Layer 2: 연속 0건/실패 감지 후 알림 (3일=경고, 7일=긴급)."""
    problem_sources = []
    for source, stat in collect_stats.items():
        zeros = db.get_consecutive_zeros(source)
        level = None
        if zeros >= 7:
            level = "긴급"
        elif zeros >= 3:
            level = "경고"
        if level:
            problem_sources.append((source, zeros, level, stat))
            logger.warning(
                "[D안] %s 연속 %d일 0건/실패 (%s)",
                source, zeros, level
            )

    if not problem_sources:
        return

    try:
        admin_email = (
            config.get("admin_alert_email")
            or config.get("email", {}).get("sender_email", "")
        )
        if not admin_email or not config.get("email", {}).get("enabled"):
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows_html = ""
        for src, zeros, level, stat in problem_sources:
            badge = "🔴" if level == "긴급" else "🟡"
            rows_html += (
                f"<tr><td>{badge} {src}</td>"
                f"<td style='color:red;font-weight:bold'>{level}</td>"
                f"<td>{zeros}일</td>"
                f"<td>{'실패' if stat['failed'] else '0건'}</td></tr>"
            )

        html = f"""
<html><body style="font-family:맑은고딕,sans-serif;">
<h2 style="color:#C00000;">⚠️ 공모레이더 수집기 이상 감지 — {now_str}</h2>
<p>아래 수집기가 연속으로 0건 또는 실패 중입니다. 사이트 개편·차단 여부를 확인하세요.</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse">
  <tr style="background:#1F3864;color:white;">
    <th>수집기</th><th>상태</th><th>연속</th><th>오늘결과</th>
  </tr>
  {rows_html}
</table>
<p>👉 data/gongmo.log 파일 또는 GUI 수집기 상태 탭을 확인하세요.</p>
<p style="color:#666;font-size:11px">공모레이더 | 한서대학교 성과혁신IR센터</p>
</body></html>"""

        from app.notifier.email_notifier import EmailNotifier as _EN
        notifier = _EN(config)
        notifier.send(
            to=admin_email,
            subject=f"[공모레이더 D안] 수집기 연속 이상 감지 {now_str}",
            html=html,
        )
        logger.info("[D안] 연속 0건 경보 발송 -> %s", admin_email)
    except Exception as e:
        logger.warning("[D안] 연속 0건 알림 발송 실패: %s", e)


def run_collection(config, db, analyzer):
    sources = config.get("sources", {})
    days_back = sources.get("days_back", 7)
    all_notices = []
    today_str = date.today().isoformat()

    # ── D안 Layer 3: 수집 전 헬스체크 ─────────────────────────
    health_results = {}
    try:
        from app.health_checker import HealthChecker
        hc_results = HealthChecker().run_active_from_config(sources)
        for r in hc_results:
            health_results[r["source"]] = r["status"]
            if r["status"] == "DOWN":
                logger.warning("[D안 헬스체크] %s DOWN: %s", r["source"], r["detail"])
            elif r["status"] == "DEGRADED":
                logger.warning("[D안 헬스체크] %s DEGRADED: %s", r["source"], r["detail"])
    except Exception as hc_err:
        logger.warning("[D안 헬스체크] 실패: %s", hc_err)

    # 수집 실패·0건 추적 (C8: 모니터링 강화)
    collect_stats = {}  # name -> {"count": int, "failed": bool}

    def safe_collect(name, fn):
        try:
            items = fn()
            all_notices.extend(items)
            collect_stats[name] = {"count": len(items), "failed": False}
            if len(items) == 0:
                logger.warning("%s: 수집 0건 (사이트 응답 또는 필터 확인 필요)", name)
            else:
                logger.info("%s: %d건", name, len(items))
        except Exception as exc:
            collect_stats[name] = {"count": 0, "failed": True}
            logger.warning("%s 수집 실패: %s", name, exc)

    if sources.get("iris", True):
        safe_collect("IRIS", lambda: IrisCollector().collect(days_back))
    if sources.get("nrf", True):
        safe_collect("NRF", lambda: NrfCollector().collect(days_back))
    # data_go_kr_api_key: 공공데이터포털 통합키 (G2B + e나라도움 동시 활성화)
    data_go_kr_key = config.get("data_go_kr_api_key", "")
    if sources.get("g2b", True):
        safe_collect("G2B", lambda: G2bCollector(api_key=data_go_kr_key).collect(days_back))
    if sources.get("ministry", True):
        safe_collect("Ministry", lambda: MinistryCollector(custom_ministries=sources.get("ministries", [])).collect(days_back))
    if sources.get("bojo", True):
        safe_collect("Bojo", lambda: BojocollectorWrapper(api_key=data_go_kr_key).collect(days_back))
    if sources.get("bizinfo", True):
        safe_collect("Bizinfo", lambda: BizinfoCollector().collect(days_back))
    if sources.get("extra_agencies", True):
        safe_collect("Regional", lambda: RegionalCollector().collect())
    # Custom: exe 환경에서 CUSTOM_SOURCES_FILE은 frozen 감지 후 계산된 경로 사용
    safe_collect("Custom", lambda: CustomCollector(CUSTOM_SOURCES_FILE).collect(days_back))
    # NTIS: 웹 크롤링 방식 (API 키 불필요)
    if sources.get("ntis", True):
        safe_collect("NTIS", lambda: NtisCollector().collect(days_back))
    # K-Startup: api_key 없으면 k-skill-proxy 경유, 있으면 공공데이터포털 직접 호출
    if sources.get("kstartup", True):
        safe_collect("KStartup", lambda: KstartupCollector(api_key=config.get("kstartup_api_key", "")).collect(days_back))

    # ── 수집 결과 요약 및 이상 감지 (C8) ──────────────────────────
    total = len(all_notices)
    failed_sources  = [n for n, s in collect_stats.items() if s["failed"]]
    zero_sources    = [n for n, s in collect_stats.items() if not s["failed"] and s["count"] == 0]

    logger.info("total_collected=%d | failed=%s | zero=%s",
                len(all_notices), failed_sources or "none", zero_sources or "none")

    active_count = len(collect_stats)
    fail_ratio = len(failed_sources) / active_count if active_count else 0
    if len(all_notices) == 0 or fail_ratio >= 0.5:
        _send_collection_alert(config, failed_sources, zero_sources, len(all_notices))

    # ── D안 Layer 1: DB에 수집 통계 저장 ─────────────────────────
    try:
        for source, stat in collect_stats.items():
            cnt = stat["count"]
            failed = stat["failed"]

            if failed:
                st = "failed"
            elif cnt == 0:
                st = "zero"
            else:
                st = "ok"

            avg = db.get_avg_30d(source)
            consec = db.get_consecutive_zeros(source)
            hstatus = health_results.get(source, "UNKNOWN")

            db.save_collector_stat(
                date=today_str,
                source=source,
                count=cnt,
                status=st,
                avg_30d=avg,
                consecutive_zeros=consec,
                health_status=hstatus,
            )
    except Exception as db_err:
        logger.warning("[D안] 수집 통계 DB 저장 실패: %s", db_err)

    # ── D안 Layer 2: 연속 0건/실패 경보 ─────────────────────────
    try:
        _check_and_alert_zeros(config, db, collect_stats, today_str)
    except Exception as alert_err:
        logger.warning("[D안] 연속 0건 경보 처리 실패: %s", alert_err)

    saved = skipped = 0
    for notice in all_notices:
        raw_text = notice.get("raw_text", notice.get("title", ""))
        analysis = analyzer.analyze(raw_text)
        score = analysis.get("daehak_score", 0)
        if score < config.get("filter", {}).get("min_eligibility_score", 60):
            skipped += 1
            continue
        matches = DepartmentMatcher(config).match(analysis)
        if db.save_notice(notice, analysis, matches):
            saved += 1
        else:
            skipped += 1

    logger.info("Saved: %d | Skipped: %d", saved, skipped)

    # ── GitHub 자동 Push (수집 완료 후) ──────────────────────────
    if config.get("github", {}).get("auto_push_after_collect", True):
        try:
            msg = f"[자동] 수집 완료 {today_str} saved={saved}"
            git_push(message=msg)
        except Exception as gp_err:
            logger.warning("[git] 수집 후 push 실패: %s", gp_err)
