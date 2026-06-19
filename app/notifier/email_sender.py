"""
이메일 알림 모듈 (SMTP 무료)
============================================================
Gmail, 교내 메일 서버 모두 지원
config.yaml > email 섹션에서 설정
"""

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

logger = logging.getLogger(__name__)


class EmailNotifier:
    """SMTP 기반 이메일 알림 발송"""

    def __init__(self, config: dict):
        ec = config.get("email", {})
        self.enabled         = ec.get("enabled", False)
        self.smtp_server     = ec.get("smtp_server", "smtp.gmail.com")
        self.smtp_port       = ec.get("smtp_port", 587)
        self.use_tls         = ec.get("use_tls", True)
        self.sender_email    = ec.get("sender_email", "")
        self.sender_password = ec.get("sender_password", "")
        self.sender_name     = ec.get("sender_name", "[공모레이더]")

    def send_daily_digest(
        self,
        recipients: List[dict],
        dept_name: str,
        notices: List[dict]
    ) -> bool:
        """일일 공고 요약 메일 발송"""
        if not self.enabled or not notices:
            return False

        emails = [c["email"] for c in recipients if c.get("email")]
        if not emails:
            return False

        subject = (
            f"[공모레이더] {dept_name} | "
            f"신규 공고 {len(notices)}건 | "
            f"{datetime.today().strftime('%m/%d')}"
        )
        body_html = self._build_html(dept_name, notices)
        body_text = self._build_text(dept_name, notices)

        return self._send(emails, subject, body_html, body_text)

    # ── HTML 메일 본문 ─────────────────────────────────────────
    def _build_html(self, dept_name: str, notices: list) -> str:
        rows = ""
        for n in notices:
            score = n.get("대학신청가능성", 0)
            color = "#27ae60" if score >= 80 else "#e67e22" if score >= 60 else "#95a5a6"
            deadline = n.get("접수마감일") or "미상"
            budget   = n.get("예산규모") or "미상"

            points = "".join(
                f"<li>{p}</li>"
                for p in n.get("검토포인트", [])[:3]
            )

            rows += f"""
            <tr style="border-bottom:1px solid #eee;">
              <td style="padding:12px; vertical-align:top;">
                <div style="font-weight:bold; font-size:14px; margin-bottom:4px;">
                  {n.get('공고명', '제목없음')}
                </div>
                <div style="color:#555; font-size:12px; margin-bottom:6px;">
                  주관: {n.get('주관기관', '')} &nbsp;|&nbsp;
                  예산: {budget} &nbsp;|&nbsp;
                  마감: <b>{deadline}</b>
                </div>
                <div style="font-size:12px; color:#333;">
                  {n.get('요약', '')}
                </div>
                {"<ul style='font-size:11px;color:#666;margin-top:4px;'>" + points + "</ul>" if points else ""}
              </td>
              <td style="padding:12px; text-align:center; vertical-align:top; min-width:60px;">
                <span style="
                  background:{color}; color:white;
                  padding:4px 8px; border-radius:12px;
                  font-size:13px; font-weight:bold;
                ">{score}점</span>
              </td>
            </tr>
            """

        return f"""
        <html><body style="font-family:맑은고딕,Arial; margin:0; padding:20px; background:#f5f5f5;">
          <div style="max-width:700px; margin:0 auto; background:white; border-radius:8px; overflow:hidden;">

            <!-- 헤더 -->
            <div style="background:#1F3864; padding:20px 24px; color:white;">
              <div style="font-size:20px; font-weight:bold;">📡 공모레이더</div>
              <div style="font-size:13px; margin-top:4px; opacity:0.8;">
                {dept_name} | {datetime.today().strftime('%Y년 %m월 %d일')} 신규 공고
              </div>
            </div>

            <!-- 요약 배너 -->
            <div style="background:#C9A84C; padding:10px 24px; color:white; font-size:13px;">
              총 <b>{len(notices)}건</b>의 관련 공고가 발견되었습니다.
            </div>

            <!-- 공고 목록 -->
            <table style="width:100%; border-collapse:collapse;">
              <thead>
                <tr style="background:#f8f9fa;">
                  <th style="padding:10px 12px; text-align:left; font-size:12px; color:#666;">공고 정보</th>
                  <th style="padding:10px 12px; text-align:center; font-size:12px; color:#666;">신청가능성</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>

            <!-- 푸터 -->
            <div style="padding:16px 24px; background:#f8f9fa; font-size:11px; color:#999;">
              한서대학교 공모레이더 | 문의: 성과혁신IR센터<br>
              이 메일은 자동 발송됩니다. 설정 변경: config.yaml
            </div>
          </div>
        </body></html>
        """

    # ── 텍스트 본문 (HTML 미지원 클라이언트용) ────────────────
    def _build_text(self, dept_name: str, notices: list) -> str:
        lines = [
            f"[공모레이더] {dept_name} 신규 공고 {len(notices)}건",
            f"{datetime.today().strftime('%Y-%m-%d')}",
            "=" * 50
        ]
        for i, n in enumerate(notices, 1):
            lines += [
                f"\n{i}. {n.get('공고명', '')}",
                f"   주관: {n.get('주관기관', '')}",
                f"   마감: {n.get('접수마감일', '미상')}",
                f"   신청 가능성: {n.get('대학신청가능성', 0)}점",
                f"   {n.get('요약', '')}",
            ]
        return "\n".join(lines)

    # ── SMTP 발송 ──────────────────────────────────────────────
    def _send(
        self,
        to_list: List[str],
        subject: str,
        html: str,
        text: str
    ) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = f"{self.sender_name} <{self.sender_email}>"
            msg["To"]      = ", ".join(to_list)

            msg.attach(MIMEText(text, "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, to_list, msg.as_string())

            logger.info(f"이메일 발송 완료: {to_list}")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("이메일 인증 실패. config.yaml의 sender_email/password 확인")
            return False
        except Exception as e:
            logger.error(f"이메일 발송 실패: {e}")
            return False
