# -*- coding: utf-8 -*-
"""
AI 분석 모듈 - Ollama + EXAONE 3.5 (완전 무료 LLM)
============================================================
- 외부 API 없음 (Claude API, OpenAI 등 유료 서비스 제외)
- 로컬 Ollama 설치 후 실행 필요
- 설치: https://ollama.com 에서 다운로드
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

    # 핵심 분석: 공고 텍스트 → 구조화된 분석 결과 반환 ─────────────────────────────
    def analyze(self, notice_text: str) -> dict:
        """
        공고 텍스트를 받아 JSON 분석 결과 반환
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
                        "temperature": 0.1,    # 일관성 중요 → 낮게 유지
                        "num_predict": 2048,   # 복잡한 공고 JSON 잘림 방지 (이전: 1024)
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

    # 분석 프롬프트 구성 ────────────────────────────────────────────────────────────
    def _build_prompt(self, text: str) -> str:
        # 너무 긴 텍스트는 앞 3000자만 사용 (토큰 절약)
        truncated = text[:3000] if len(text) > 3000 else text

        return f"""당신은 대학교 기획처 연구원입니다.
아래 공고 텍스트를 읽고, 반드시 JSON 형식으로만 답하세요.
다른 설명이나 마크다운 없이 JSON만 출력하세요.

[공고 내용]
{truncated}

[출력 형식 - 이 JSON만 출력]
{{
  "공고명": "정확한 공고명",
  "주관기관": "주관기관명",
  "신청가능유형": ["대학", "연구기관", "기업"],
  "응모신청가능성": 85,
  "지원금액": "10억원 (정보 없으면 null)",
  "공고시작일": "YYYY-MM-DD (모르면 null)",
  "공고마감일": "YYYY-MM-DD (모르면 null)",
  "지원분야": ["R&D", "교육", "창업"],
  "신청자격": "대학기관이면 명시, 해당없으면 null",
  "규모구분": "대형/중형/소형",
  "체크포인트": [
    "신청자격 세부 확인 필요",
    "예산 단독 신청 여부 확인"
  ],
  "요약": "2~3문장 요약"
}}

중요 판단 기준:
- 응모신청가능성: 대학교/학교법인/비영리/연구기관에 해당 시 80 이상
- 기업/영리단체만 가능 시 10 이하
- 금액/날짜 모르면 null로 표시
"""

    # 응답 JSON 파싱 ──────────────────────────────────────────────────────────────
    def _parse_response(self, raw: str) -> dict:
        """
        LLM 출력에서 JSON을 안전하게 추출.
        전략:
          1) 마크다운 코드블록 제거
          2) JSONDecoder.raw_decode() — 첫 완성 JSON만 추출 (탐욕 패턴 오류 방지)
          3) 실패 시 첫 { ~ 마지막 } 폴백
          4) 필수 필드 타입 검증 + 정규화
        """
        # 마크다운 코드블록 제거
        clean = re.sub(r"```(?:json)?\s*", "", raw)
        clean = re.sub(r"```", "", clean).strip()

        result = None

        # 전략 1: raw_decode — 중첩 JSON에 안전, 첫 { 부터만 파싱
        brace_pos = clean.find("{")
        if brace_pos != -1:
            try:
                decoder = json.JSONDecoder()
                result, _ = decoder.raw_decode(clean, brace_pos)
            except json.JSONDecodeError:
                result = None

        # 전략 2: 폴백 — 첫 { ~ 마지막 } 구간
        if result is None:
            first = clean.find("{")
            last  = clean.rfind("}")
            if first != -1 and last > first:
                try:
                    result = json.loads(clean[first:last + 1])
                except json.JSONDecodeError:
                    result = None

        if result is None or not isinstance(result, dict):
            logger.warning("JSON 파싱 실패 (raw 앞 200자): %s", raw[:200])
            return self._fallback_result()

        # 응모신청가능성: 반드시 정수 0~100
        score = result.get("응모신청가능성", 50)
        if not isinstance(score, (int, float)):
            try:
                score = int(str(score).strip().replace("%", ""))
            except Exception:
                score = 50
        result["응모신청가능성"] = max(0, min(100, int(score)))

        # 기본값 설정
        result.setdefault("요약", "")
        result.setdefault("체크포인트", [])
        result.setdefault("지원분야", [])
        result.setdefault("규모구분", "중간")
        result.setdefault("공고명", "")
        result.setdefault("주관기관", "")

        # 리스트 필드 타입 강제
        for lf in ("지원분야", "신청가능유형", "체크포인트"):
            if lf in result and not isinstance(result[lf], list):
                result[lf] = [str(result[lf])] if result[lf] else []

        return result

    # 분석 실패 시 기본값 ──────────────────────────────────────────────────────────
    def _fallback_result(self) -> dict:
        return {
            "공고명": "",
            "주관기관": "",
            "신청가능유형": [],
            "응모신청가능성": 0,
            "지원금액": None,
            "공고시작일": None,
            "공고마감일": None,
            "지원분야": [],
            "신청자격": None,
            "규모구분": "미확인",
            "체크포인트": [],
            "요약": "AI 분석 실패 - 수동 확인 필요",
            "_ai_error": True
        }

    # 로컬 Ollama 서비스 상태 확인 ──────────────────────────────────────────────────
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
                "Ollama 미실행. 터미널에서 'ollama serve' 실행 필요"
            )
            return False
