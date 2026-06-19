# -*- coding: utf-8 -*-
"""
scheduler.py - v2.0
공모레이더 자동 수집/분석/알림 스케줄러
"""
import logging, os, subprocess, sys, time, urllib.request
from datetime import datetime, date
from logging.handlers import RotatingFileHandler
import schedule, yaml

from app.analyzers.ai_analyzer import AIAnalyzer
from app.database import Database
from app.collection import run_collection
from app.git_sync import git_push
from app.notifier.email_notifier import EmailNotifier
from app.notifier.telegram import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            "./data/gongmo.log",
            maxBytes=5 * 1024 * 1024,   # 5MB
            backupCount=5,               # gongmo.log.1 ~ .5 보존
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_ollama_running():
    try:
        urllib.request.urlopen("http://localhost:11434", timeout=2)
        return True
    except Exception:
        pass
    env = os.environ.copy()
    try:
        os.path.expanduser("~").encode("ascii")
    except UnicodeEncodeError:
        env["OLLAMA_MODELS"] = r"C:\OllamaModels"
    try:
        subprocess.Popen(["ollama", "serve"], env=env,
            creationflags=0x00000008 | 0x08000000,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        logger.error("ollama not found. Run: python setup.py")
        return False
    for _ in range(20):
        time.sleep(1)
        try:
            urllib.request.urlopen("http://localhost:11434", timeout=1)
            return True
        except Exception:
            pass
    return False






def _send_weekly_report(config, db):
    """D안 Layer 4: 매주 월요일 주간 수집 보고서 이메일."""
    try:
        admin_email = (
            config.get("admin_alert_email")
            or config.get("email", {}).get("sender_email", "")
        )
        if not admin_email or not config.get("email", {}).get("enabled"):
            logger.info("[D안] 이메일 미설정 — 주간 보고서 스킵")
            return

        weekly = db.get_weekly_stats()
        if not weekly:
            logger.info("[D안] 주간 통계 없음 — 보고서 스킵")
            return

        now_str = datetime.now().strftime("%Y-%m-%d")
        rows_html = ""
        for row in weekly:
            src = row["source"]
            total = row["total_7d"] or 0
            avg = row["avg_7d"] or 0
            zddays = row["zero_days"] or 0
            streak = row["max_streak"] or 0
            wh = row["worst_health"] or "UNKNOWN"

            if wh == "DOWN" or streak >= 7:
                badge, bg = "❌", "#FFC7CE"
            elif wh == "DEGRADED" or streak >= 3:
                badge, bg = "⚠️", "#FFEB9C"
            else:
                badge, bg = "✅", "#C6EFCE"

            rows_html += (
                f"<tr style='background:{bg}'>"
                f"<td>{badge} {src}</td>"
                f"<td style='text-align:center'>{total}건</td>"
                f"<td style='text-align:center'>{avg}건/일</td>"
                f"<td style='text-align:center'>{zddays}일</td>"
                f"<td style='text-align:center'>{streak}일</td>"
                f"<td style='text-align:center'>{wh}</td>"
                "</tr>"
            )

        html = f"""
<html><body style="font-family:맑은고딕,sans-serif;">
<h2 style="color:#1F3864;">📋 공모레이더 주간 수집 현황 ({now_str})</h2>
<p>지난 7일간 수집기별 실적 요약입니다.</p>
<table border="1" cellpadding="6" cellspacing="0"
       style="border-collapse:collapse;width:100%;min-width:500px">
  <tr style="background:#1F3864;color:white;">
    <th>수집기</th><th>7일합계</th><th>일평균</th><th>0건일수</th><th>최장연속0건</th><th>헬스</th>
  </tr>
  {rows_html}
</table>
<p>✅ 정상 &nbsp;⚠️ 요주의 (3일+) &nbsp;❌ 긴급 (7일+ 또는 DOWN)</p>
<p style="color:#666;font-size:11px">공모레이더 D안 자동 보고 | 한서대학교 성과혁신IR센터</p>
</body></html>"""

        from app.notifier.email_notifier import EmailNotifier as _EN
        _EN(config).send(
            to=admin_email,
            subject=f"[공모레이더] 주간 수집 보고서 {now_str}",
            html=html,
        )
        logger.info("[D안] 주간 보고서 발송 -> %s", admin_email)
    except Exception as e:
        logger.warning("[D안] 주간 보고서 발송 실패: %s", e)




def _git_push_nightly(config):
    """새벽 정기 GitHub Push (코드 변경사항 야간 백업)."""
    if not config.get("github", {}).get("nightly_push", True):
        return
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        git_push(message=f"[새벽백업] {now_str}", add_all=False)
        logger.info("[git] 새벽 push 완료")
    except Exception as e:
        logger.warning("[git] 새벽 push 실패: %s", e)


def run_notification(config, db):
    email_notifier = EmailNotifier(config)
    telegram_notifier = TelegramNotifier(config)
    min_score = config.get("filter", {}).get("min_eligibility_score", 60)

    for dept in config.get("departments", []):
        dept_name = dept["name"]
        contacts = dept.get("contacts", [])
        notices = db.get_pending_notices_for_dept(dept_name, min_dept_score=45, min_eligibility=min_score)
        if not notices:
            continue
        if config.get("email", {}).get("enabled"):
            ok = email_notifier.send_daily_digest(contacts, dept_name, notices)
            for n in notices:
                for c in contacts:
                    db.log_notification(n["id"], dept_name, "email", c.get("email", ""), ok)
        telegram_notifier.notify_department(dept_name=dept_name, contacts=contacts, notices=notices)
        for n in notices:
            db.mark_notified(n["id"], dept_name)


def main():
    config = load_config()
    db = Database(config["database"]["path"])
    analyzer = AIAnalyzer(config)
    ensure_ollama_running()
    if not analyzer.health_check():
        logger.error("Ollama not running or model not installed. Run: python setup.py")
        return

    collect_time = config.get("schedule", {}).get("collect_time", "06:00")
    notify_time  = config.get("schedule", {}).get("notify_time",  "08:30")

    schedule.every().day.at(collect_time).do(run_collection, config=config, db=db, analyzer=analyzer)
    schedule.every().day.at(notify_time).do(run_notification, config=config, db=db)

    # D안 Layer 4: 매주 월요일 09:00 주간 보고서 이메일
    weekly_time = config.get("schedule", {}).get("weekly_report_time", "09:00")
    schedule.every().monday.at(weekly_time).do(_send_weekly_report, config=config, db=db)

    # GitHub 새벽 자동 Push (02:00)
    nightly_time = config.get("schedule", {}).get("git_push_time", "02:00")
    schedule.every().day.at(nightly_time).do(_git_push_nightly, config=config)

    logger.info("Scheduler started | collect=%s | notify=%s | weekly_report=Monday %s | git_push=%s",
                collect_time, notify_time, weekly_time, nightly_time)

    if "--now" in sys.argv:
        run_collection(config, db, analyzer)
        run_notification(config, db)
        return

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
