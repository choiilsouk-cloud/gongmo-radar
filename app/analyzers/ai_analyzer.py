"""
AI 분석 엔진 - Ollama + EXAONE 3.5 (무료 로컬 LLM)
============================================================
- 유료 API 없음 (Claude API, OpenAI 사용 안 함)
- 서버에 Ollama 설치 후 로컬 실행
- 설치: curl -fsSL https://ollama.com/install.sh | sh
- 모델: ollama pull exaone3.5:7.8b
"""

import json
import logging
import re
import requests
from typing import Optional

logger = logging.getLogger(__name__)


class AIAnalyzer:
    """Ollama 기반 공고 분석기 (무료)"""

    def __init__(self, config: dict):
        self.base_url = config["ai"]["base_url"]
        self.model    = config["ai"]["model"]
        self.timeout  = config["ai"].get("timeout", 120)

    # ── 핵심: 공고 원문 → 구조화된 분석 결과 ──────────────────
    def analyze(self, notice_text: str) -> dict:
        """
        공고 원문을 받아 JSON 분석 결과 반환
        """
        prompt = self._build_prompt(notice_text)

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,   # 일관성 중요 → 낮게 설정
                        "num_predict": 1024,
                    }
                },
                timeout=self.timeout
            )
            response.raise_for_status()
            raw = response.json().get("response", "")
            return self._parse_response(raw)

        except requests.exceptions.ConnectionError:
            logger.error("Ollama 연결 실패. 'ollama serve' 실행 여부 확인 필요")
            return self._fallback_result()
        except Exception as e:
            logger.error(f"AI 분석 오류: {e}")
            return self._fallback_result()

    # ── 프롬프트 ───────────────────────────────────────────────
    def _build_prompt(self, text: str) -> str:
        # 너무 긴 공고는 앞 3000자만 사용 (토큰 절약)
        truncated = text[:3000] if len(text) > 3000 else text

        return f"""당신은 대학교 행정 전문가입니다.
아래 정부 공모사업 공고를 읽고, 반드시 JSON 형식으로만 답하세요.
다른 설명이나 마크다운 없이 JSON만 출력하세요.

[공고 원문]
{truncated}

[출력 형식 - 이 JSON만 출력]
{{
  "공고명": "공고 제목",
  "주관기관": "기관명",
  "지원대상": ["대학", "연구기관", "기업"],
  "대학신청가능성": 85,
  "예산규모": "10억원 (추정 불가시 null)",
  "접수시작일": "YYYY-MM-DD (없으면 null)",
  "접수마감일": "YYYY-MM-DD (없으면 null)",
  "사업분야": ["R&D", "교육", "창업"],
  "신청제한": "기업전용이면 기재, 없으면 null",
  "긴급도": "높음/보통/낮음",
  "검토포인트": [
    "공동신청 필요 여부 확인",
    "대학 단독 신청 가능 여부"
  ],
  "요약": "2~3문장 요약"
}}

중요 판단 기준:
- 대학신청가능성: 지원대상에 대학/연구기관/비영리/산학협력단/컨소시엄 포함 시 80점 이상
- 기업전용/개인전용/지자체전용은 10점 이하
- 금액/날짜가 없으면 null로 표기
"""

    # ── JSON 파싱 ──────────────────────────────────────────────
    def _parse_response(self, raw: str) -> dict:
        # LLM이 마크다운 코드블록으로 감쌀 경우 제거
        clean = re.sub(r"```(?:json)?", "", raw).strip()

        # JSON 블록 추출
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if not match:
            logger.warning("JSON 파싱 실패 - 기본값 반환")
            return self._fallback_result()

        try:
            result = json.loads(match.group())
            # 필수 필드 기본값 보장
            result.setdefault("대학신청가능성", 50)
            result.setdefault("요약", "")
            result.setdefault("검토포인트", [])
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 디코드 오류: {e}")
            return self._fallback_result()

    # ── 분석 실패 시 기본값 ────────────────────────────────────
    def _fallback_result(self) -> dict:
        return {
            "공고명": "",
            "주관기관": "",
            "지원대상": [],
            "대학신청가능성": 0,
            "예산규모": None,
            "접수시작일": None,
            "접수마감일": None,
            "사업분야": [],
            "신청제한": None,
            "긴급도": "낮음",
            "검토포인트": [],
            "요약": "AI 분석 실패 - 수동 확인 필요",
            "_ai_error": True
        }

    # ── Ollama 서버 상태 확인 ──────────────────────────────────
    def health_check(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            if not any(self.model.split(":")[0] in m for m in models):
                logger.warning(
                    f"모델 '{self.model}' 미설치. "
                    f"실행: ollama pull {self.model}"
                )
                return False
            return True
        except Exception:
            logger.error(
                "Ollama 미실행. 서버에서 'ollama serve' 실행 필요"
            )
            return False
