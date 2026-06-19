"""
이메일 알림 발송 (SMTP)
Gmail 앱 비밀번호 또는 교내 SMTP 지원
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, config: dict):
        self.cfg = config.get("email", {})
        self.sender = self.cfg.get("sender_email", "")
        self.password = self.cfg.get("sender_password", "")
        self.smtp_server = self.cfg.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = self.cfg.get("smtp_port", 587)
        self.use_tls = self.cfg.get("use_tls", True)
        self.sender_name = self.cfg.get("sender_name", "[공모레이더] 한서대학교")

    def _smtp(self):
        s = smtplib.SMTP(self.smtp_server, self.smtp_port)
        if self.use_tls:
            s.starttls()
        s.login(self.sender, self.password)
        return s

    def send(self, to: str, subject: str, html: str) -> bool:
        if not (self.sender and self.password):
            logger.warning("이메일 설정 미완료 (sender_email / sender_password)")
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.sender_name} <{self.sender}>"
            msg["To"] = to
            msg.attach(MIMEText(html, "html", "utf-8"))
            with self._smtp() as s:
                s.sendmail(self.sender, [to], msg.as_string())
            logger.info(f"이메일 발송 완료 → {to}")
            return True
        except Exception as e:
            logger.error(f"이메일 발송 실패: {e}")
            return False

    def notify_department(self, dept_name: str, contacts: list, notices: list) -> bool:
        if not notices:
            return True
        html = self._build_html(dept_name, notices)
        subject = f"[공모레이더] {dept_name} 신규 공모사업 {len(notices)}건"
        ok = True
        for c in contacts:
            email = c.get("email", "")
            if email:
                ok &= self.send(email, subject, html)
        return ok

    def send_test(self, to: str) -> bool:
        """연결 테스트용 이메일"""
        return self.send(
            to,
            "[공모레이더] 이메일 연결 테스트",
            "<h2>✅ 공모레이더 이메일 발송 테스트 성공</h2>"
            "<p>이 메일이 수신되면 이메일 알림 설정이 완료된 것입니다.</p>"
        )

    def _build_html(self, dept_name: str, notices: list) -> str:
        rows = ""
        for n in notices:
            score = n.get("score", 0)
            badge = "🟢" if score >= 70 else "🟡"
            rows += f"""
            <tr>
              <td>{badge} {n.get('title','')}</td>
              <td>{n.get('agency','')}</td>
              <td>{n.get('end_date','')}</td>
              <td>{score}점</td>
              <td>{n.get('action_level','')}</td>
            </tr>"""

        return f"""
        <html><body style="font-family:맑은고딕,sans-serif;">
        <h2 style="color:#1F3864;">📢 {dept_name} 공모사업 알림</h2>
        <p>아래 {len(notices)}건의 공모사업을 검토하시기 바랍니다.</p>
        <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%">
          <tr style="background:#1F3864;color:white;">
            <th>공고명</th><th>주관기관</th><th>마감일</th><th>매칭점수</th><th>권고</th>
          </tr>
          {rows}
        </table>
        <p style="color:#666;font-size:12px;">공모레이더 | 한서대학교 성과혁신IR센터</p>
        </body></html>"""
