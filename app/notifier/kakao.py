"""
카카오톡 알림 모듈
============================================================
방법1: 카카오워크 Webhook (무료 - 교내 카카오워크 사용 시)
방법2: 카카오 알림톡 API (건당 약 8원 - 카카오 비즈니스 계정 필요)

config.yaml에서 enabled/방법을 선택하면 자동 적용됩니다.
"""

import logging
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ================================================================
# 방법1: 카카오워크 Webhook (무료)
# ================================================================
class KakaoWorkNotifier:
    """
    카카오워크 채널 Webhook 알림
    - 카카오워크 채널 생성 → Incoming Webhook URL 발급 → config.yaml 입력
    - 완전 무료
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, notices: list) -> bool:
        if not self.webhook_url:
            logger.warning("카카오워크 Webhook URL 미설정")
            return False

        body = self._build_message(title, notices)

        try:
            r = requests.post(
                self.webhook_url,
                json={"text": body},
                timeout=10
            )
            r.raise_for_status()
            logger.info("카카오워크 알림 발송 완료")
            return True
        except Exception as e:
            logger.error(f"카카오워크 발송 실패: {e}")
            return False

    def _build_message(self, title: str, notices: list) -> str:
        lines = [f"📢 *{title}*", ""]
        for i, n in enumerate(notices[:5], 1):  # 최대 5건
            score = n.get("대학신청가능성", 0)
            deadline = n.get("접수마감일", "미상")
            lines.append(
                f"{i}. {n.get('공고명', '제목없음')}\n"
                f"   └ {n.get('주관기관', '')} | 마감: {deadline} | 가능성: {score}점"
            )
        lines += ["", f"총 {len(notices)}건 | 자세한 내용 → 공모레이더 대시보드"]
        return "\n".join(lines)


# ================================================================
# 방법2: 카카오 알림톡 (카카오 비즈니스 계정 필요)
# ================================================================
class KakaoAlimtalkNotifier:
    """
    카카오 알림톡 API 알림
    - 카카오 비즈니스 계정 + 알림톡 채널 심사 통과 필요
    - 건당 약 7~8원 (대량 발송 시 협의 가능)
    - 설정: config.yaml > kakao > alimtalk > api_key, sender_key 입력
    """

    BASE_URL = "https://kakaoapi.aligo.in/akv10/alimtalk/send/"

    def __init__(self, api_key: str, sender_key: str, template_code: str):
        self.api_key = api_key
        self.sender_key = sender_key
        self.template_code = template_code

    def send_to_contact(
        self,
        phone: str,
        contact_name: str,
        notices: list
    ) -> bool:
        if not all([self.api_key, self.sender_key]):
            logger.warning("카카오 알림톡 API 키 미설정")
            return False

        message = self._build_message(contact_name, notices)

        try:
            r = requests.post(
                self.BASE_URL,
                data={
                    "apikey": self.api_key,
                    "userid": "hanseo_gongmo",
                    "senderkey": self.sender_key,
                    "tpl_code": self.template_code,
                    "sender": "15884822",   # 한서대 대표 번호로 변경
                    "receiver_1": phone,
                    "recvname_1": contact_name,
                    "message_1": message,
                },
                timeout=10
            )
            r.raise_for_status()
            result = r.json()
            if result.get("code") == 0:
                logger.info(f"알림톡 발송 성공: {contact_name} ({phone})")
                return True
            else:
                logger.error(f"알림톡 오류: {result.get('message')}")
                return False
        except Exception as e:
            logger.error(f"알림톡 발송 실패: {e}")
            return False

    def _build_message(self, name: str, notices: list) -> str:
        top = notices[0] if notices else {}
        return (
            f"[공모레이더] {name}님\n\n"
            f"오늘 신규 공고 {len(notices)}건이 확인되었습니다.\n\n"
            f"■ 주요 공고\n"
            f"{top.get('공고명', '')}\n"
            f"주관: {top.get('주관기관', '')}\n"
            f"마감: {top.get('접수마감일', '미상')}\n"
            f"가능성: {top.get('대학신청가능성', 0)}점\n\n"
            f"자세한 내용은 공모레이더 대시보드를 확인하세요."
        )


# ================================================================
# 통합 카카오 알림 매니저 (config.yaml 설정 기반 자동 선택)
# ================================================================
class KakaoNotifier:
    """config.yaml 설정에 따라 방법1/방법2 자동 선택"""

    def __init__(self, config: dict):
        self.enabled = config.get("kakao", {}).get("enabled", False)
        self.kakaowork: Optional[KakaoWorkNotifier] = None
        self.alimtalk: Optional[KakaoAlimtalkNotifier] = None

        if not self.enabled:
            return

        kk = config.get("kakao", {})

        # 방법1: 카카오워크
        if kk.get("kakaowork", {}).get("enabled"):
            url = kk["kakaowork"].get("webhook_url", "")
            if url:
                self.kakaowork = KakaoWorkNotifier(url)
                logger.info("카카오워크 Webhook 알림 활성화")

        # 방법2: 알림톡
        if kk.get("alimtalk", {}).get("enabled"):
            at = kk["alimtalk"]
            self.alimtalk = KakaoAlimtalkNotifier(
                api_key=at.get("api_key", ""),
                sender_key=at.get("sender_key", ""),
                template_code=at.get("template_code", "")
            )
            logger.info("카카오 알림톡 활성화")

    def notify_department(
        self,
        dept_name: str,
        contacts: list,
        notices: list,
        title: str
    ) -> None:
        if not self.enabled or not notices:
            return

        # 방법1: 카카오워크 채널 공지 (전체 발송)
        if self.kakaowork:
            self.kakaowork.send(
                title=f"[{dept_name}] {title}",
                notices=notices
            )

        # 방법2: 알림톡 (개인별 발송)
        if self.alimtalk:
            for contact in contacts:
                phone = contact.get("phone", "")
                if phone:
                    self.alimtalk.send_to_contact(
                        phone=phone,
                        contact_name=contact.get("name", ""),
                        notices=notices
                    )
