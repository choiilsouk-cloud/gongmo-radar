"""
텔레그램 알림 모듈 (완전 무료)
============================================================
설정 방법:
  1. 텔레그램에서 @BotFather 대화
  2. /newbot → 봇 이름 입력 → API 토큰 발급
  3. 봇에게 메시지 1회 전송
  4. https://api.telegram.org/bot{토큰}/getUpdates 로 chat_id 확인
  5. config.yaml에 token, chat_id 입력

부서별 알림: 각 담당자가 봇과 대화 후 chat_id를 config.yaml에 등록
그룹 채널: 부서별 텔레그램 그룹 생성 → 봇 초대 → 그룹 chat_id 등록
"""

import logging
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramNotifier:
    """텔레그램 Bot API 알림 (무료)"""

    def __init__(self, config: dict):
        tg = config.get("telegram", {})
        self.enabled = tg.get("enabled", False)
        self.token   = tg.get("bot_token", "")
        self.timeout = 10

    # ── 단일 메시지 발송 ────────────────────────────────────────
    def send(self, chat_id: str, text: str) -> bool:
        if not self.enabled or not self.token:
            return False
        if not chat_id:
            logger.warning("chat_id 미설정 - config.yaml 확인")
            return False

        url = TELEGRAM_API.format(token=self.token, method="sendMessage")
        try:
            r = requests.post(
                url,
                json={
                    "chat_id":    chat_id,
                    "text":       text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            if r.json().get("ok"):
                logger.info(f"텔레그램 발송 완료: {chat_id}")
                return True
            else:
                logger.error(f"텔레그램 오류: {r.json()}")
                return False
        except Exception as e:
            logger.error(f"텔레그램 발송 실패: {e}")
            return False

    # ── 부서 알림 (담당자 개인 or 그룹 채널) ───────────────────
    def notify_department(
        self,
        dept_name: str,
        contacts: list,
        notices: list,
    ) -> None:
        if not self.enabled or not notices:
            return

        text = self._build_message(dept_name, notices)

        sent_chats = set()
        for contact in contacts:
            chat_id = contact.get("telegram_chat_id", "")
            if chat_id and chat_id not in sent_chats:
                self.send(chat_id, text)
                sent_chats.add(chat_id)

    # ── 메시지 본문 (HTML 포맷) ─────────────────────────────────
    def _build_message(self, dept_name: str, notices: list) -> str:
        today = datetime.today().strftime("%m/%d")
        lines = [
            f"📡 <b>[공모레이더] {dept_name}</b>",
            f"<i>{today} 신규 공고 {len(notices)}건</i>",
            "",
        ]

        for i, n in enumerate(notices[:5], 1):
            score    = n.get("eligibility", 0)
            deadline = n.get("end_date") or "미상"
            title    = n.get("title", "제목없음")
            agency   = n.get("agency", "")
            url      = n.get("url", "")

            # 점수 이모지
            emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "⚪"

            lines += [
                f"{emoji} <b>{i}. {title}</b>",
                f"   🏛 {agency}  |  📅 마감: {deadline}  |  {score}점",
            ]
            if url:
                lines.append(f"   🔗 <a href='{url}'>공고 바로가기</a>")
            lines.append("")

        if len(notices) > 5:
            lines.append(f"<i>외 {len(notices)-5}건 → 대시보드에서 확인</i>")

        return "\n".join(lines)

    # ── 봇 상태 확인 ───────────────────────────────────────────
    def health_check(self) -> bool:
        if not self.token:
            logger.warning("텔레그램 봇 토큰 미설정")
            return False
        url = TELEGRAM_API.format(token=self.token, method="getMe")
        try:
            r = requests.get(url, timeout=5)
            if r.json().get("ok"):
                bot_name = r.json()["result"]["username"]
                logger.info(f"텔레그램 봇 정상: @{bot_name}")
                return True
        except Exception as e:
            logger.error(f"텔레그램 봇 확인 실패: {e}")
        return False

    # ── chat_id 자동 조회 헬퍼 (최초 설정 시 사용) ─────────────
    def get_updates(self) -> list:
        """
        봇에게 메시지를 보낸 사용자의 chat_id 조회
        사용법: python -c "from app.notifier.telegram import *; ..."
        """
        url = TELEGRAM_API.format(token=self.token, method="getUpdates")
        try:
            r = requests.get(url, timeout=10)
            updates = r.json().get("result", [])
            chats = []
            for u in updates:
                msg = u.get("message", {})
                chat = msg.get("chat", {})
                chats.append({
                    "chat_id":  chat.get("id"),
                    "name":     chat.get("first_name") or chat.get("title"),
                    "type":     chat.get("type"),
                })
            return chats
        except Exception as e:
            logger.error(f"getUpdates 실패: {e}")
            return []
