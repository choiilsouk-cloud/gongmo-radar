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

    # 모델 폴백 순서: config 우선, 없으면 EXAONE → Qwen 순
    _FALLBACK_MODELS = ["exaone3.5:7.8b", "qwen2.5:7b", "llama3.2:3b"]

    def __init__(self, config: dict):
        self.base_url    = config["ai"]["base_url"]
        self.model       = config["ai"]["model"]
        self.timeout     = config["ai"].get("timeout", 120)
        self._retry_max  = config["ai"].get("retry", 2)   # 재시도 횟수 (기본 2)

    # 핵심 분석: 공고 텍스트 → 구조화된 분석 결과 반환 ─────────────────────────────
    def analyze(self, notice_text: str) -> dict:
        """
        공고 텍스트를 받아 JSON 분석 결과 반환
        """
        prompt = self._build_prompt(notice_text)

        for attempt in range(1, self._retry_max + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,    # 일관성 중요 → 낮게 유지
                            "num_predict": 2048,   # 복잡한 공고 JSON 잘림 방지
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
            except requests.exceptions.Timeout:
                logger.warning(
                    "Ollama 응답 초과 (%ds, 시도 %d/%d) — timeout 설정: ai.timeout",
                    self.timeout, attempt, self._retry_max,
                )
                if attempt < self._retry_max:
                    import time
                    time.sleep(3)
                    continue
                return self._fallback_result()
            except Exception as e:
                logger.error("AI 분석 오류 (시도 %d/%d): %s", attempt, self._retry_max, e)
                if attempt < self._retry_max:
                    import time
                    time.sleep(2)
                    continue
                return self._fallback_result()
        return self._fallback_result()

    # 분석 프롬프트 구성 ────────────────────────────────────────────────────────────
    def _build_prompt(self, text: str) -> str:
        # 너무 긴 텍스트는 앞 3000자만 사용 (토큰 절약)
        truncated = text[:3000] if len(text) > 3000 else text

        return f"""당신은 한서대학교 기획예산처 성과혁신IR센터 전문 연구원입니다.
아래 공모사업 공고를 분석하여 반드시 JSON만 출력하세요. 다른 설명이나 마크다운 없이 JSON만 출력하세요.

[한서대학교 핵심 강점 분야 — 이 분야와 연관성이 높으면 점수를 높게 부여]
- 항공·드론·무인기·UAM·모빌리티
- AI·SW·인공지능·빅데이터·디지털전환
- 지역혁신·서산·충남·교육발전특구
- 산학협력·R&D·기술개발·공동연구
- 교육혁신·비교과·평생교육·재직자교육
- 입학·고교연계·학생지원

[공고 내용]
{truncated}

[출력 형식 — 이 JSON만 출력]
{{
  "공고명": "정확한 공고명",
  "주관기관": "주관기관명",
  "신청가능유형": ["대학", "연구기관", "기업"],
  "응모신청가능성": 85,
  "지원금액": "10억원 (정보 없으면 null)",
  "공고시작일": "YYYY-MM-DD (모르면 null)",
  "공고마감일": "YYYY-MM-DD (모르면 null)",
  "지원분야": ["R&D", "교육", "창업"],
  "신청자격": "대학기관이면 구체적으로 명시, 해당없으면 null",
  "규모구분": "대형/중형/소형",
  "한서대연관도": 75,
  "추천부서": ["기획예산처", "산학협력단"],
  "체크포인트": [
    "신청자격 세부 확인 필요",
    "자부담 여부 확인"
  ],
  "위험요인": ["지자체 컨소시엄 필수", "자부담 20% 필요"],
  "요약": "2~3문장 요약"
}}

판단 기준:
- 응모신청가능성: 대학·학교법인·비영리·연구기관 신청 가능 시 80 이상 / 기업·영리단체 전용 시 10 이하
- 한서대연관도: 위 핵심 강점 분야와 연관성 0~100 (항공·AI·지역혁신 분야 시 80 이상)
- 추천부서: 항공·드론→항공학부, R&D·산학→산학협력단, 창업→창업지원단, 지역혁신·교육특구→기획예산처
- 금액·날짜 모르면 null로 표시
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
        result.setdefault("위험요인", [])
        result.setdefault("지원분야", [])
        result.setdefault("규모구분", "중간")
        result.setdefault("공고명", "")
        result.setdefault("주관기관", "")
        result.setdefault("추천부서", [])
        result.setdefault("한서대연관도", 50)

        # 한서대연관도 0~100 정수 강제
        hd = result.get("한서대연관도", 50)
        if not isinstance(hd, (int, float)):
            try:
                hd = int(str(hd).strip().replace("%", ""))
            except Exception:
                hd = 50
        result["한서대연관도"] = max(0, min(100, int(hd)))

        # 리스트 필드 타입 강제
        for lf in ("지원분야", "신청가능유형", "체크포인트", "위험요인", "추천부서"):
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
            "한서대연관도": 0,
            "추천부서": [],
            "체크포인트": [],
            "위험요인": [],
            "요약": "AI 분석 실패 - 수동 확인 필요",
            "_ai_error": True
        }

    # 로컬 Ollama 서비스 상태 확인 ──────────────────────────────────────────────────
    def health_check(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            model_base = self.model.split(":")[0]
            if any(model_base in m for m in models):
                return True
            # 폴백: 설치된 다른 모델 자동 선택
            for fb in self._FALLBACK_MODELS:
                fb_base = fb.split(":")[0]
                if any(fb_base in m for m in models):
                    logger.warning(
                        "모델 '%s' 미설치. 설치된 '%s'(으)로 폴백합니다. "
                        "ollama pull %s 로 원래 모델 설치 권장",
                        self.model, fb, self.model,
                    )
                    self.model = fb
                    return True
            logger.warning(
                "모델 '%s' 미설치. 실행: ollama pull %s", self.model, self.model
            )
            return False
        except Exception:
            logger.error("Ollama 미실행. 터미널에서 'ollama serve' 실행 필요")
            return False


# ── 필드명 정규화 유틸 (한글/영문/구버전 키 모두 허용) ──────────────────────────────
def normalize_analysis(a: dict) -> dict:
    """
    AI 분석 결과의 한글/영문/구버전 필드를 현행 표준 필드로 통일한다.
    DB·알림·매칭 코드는 이 함수를 통해 받은 dict 만 사용해야 한다.

    지원 변환 예시:
      응모신청가능성 / daehak_score / eligibility_score   → eligibility_score
      한서대연관도 / importance_score / priority_score    → importance_score
      공고마감일 / 접수마감일 / deadline                  → deadline
      지원금액 / 예산규모 / budget                        → budget
      요약 / summary                                     → summary
      추천부서 / recommended_departments                  → recommended_departments
      체크포인트 / evidence                              → evidence
      위험요인 / risk_factors                            → risk_factors
    """
    def _first(*keys, default=None):
        for k in keys:
            v = a.get(k)
            if v is not None and v != "" and v != []:
                return v
        return default

    return {
        # ── 점수 ────────────────────────────────────────────────
        "eligibility_score": int(_first(
            "eligibility_score", "응모신청가능성", "대학신청가능성", "daehak_score", default=0
        ) or 0),
        "importance_score": int(_first(
            "importance_score", "한서대연관도", "중요도", "priority_score", default=50
        ) or 50),

        # ── 날짜·금액 ────────────────────────────────────────────
        "deadline": _first("deadline", "공고마감일", "접수마감일", "마감일"),
        "start_date": _first("start_date", "공고시작일", "접수시작일"),
        "budget": _first("budget", "지원금액", "예산규모", "지원규모"),

        # ── 메타 ─────────────────────────────────────────────────
        "title":   _first("title",   "공고명",   default=""),
        "agency":  _first("agency",  "주관기관", default=""),
        "summary": _first("summary", "요약",     default=""),
        "scale":   _first("scale",   "규모구분", default="중간"),

        # ── 리스트 필드 ──────────────────────────────────────────
        "target_types": _first(
            "target_types", "신청가능유형", "지원대상", default=[]
        ),
        "fields": _first(
            "fields", "지원분야", default=[]
        ),
        "recommended_departments": _first(
            "recommended_departments", "추천부서", default=[]
        ),
        "evidence": _first(
            "evidence", "체크포인트", "추천근거", default=[]
        ),
        "risk_factors": _first(
            "risk_factors", "위험요인", default=[]
        ),

        # ── 원본 보존 ────────────────────────────────────────────
        "_raw": a,
        "_ai_error": a.get("_ai_error", False),
    }
