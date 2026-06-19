"""
부서 매칭 엔진 - 키워드 + 임베딩 하이브리드
============================================================
1차: 키워드 점수 (빠름, 명확한 매칭)
2차: 문장 유사도 (표현이 달라도 같은 의미 포착)
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


class DepartmentMatcher:
    """공고 ↔ 부서 자동 매칭"""

    def __init__(self, config: dict):
        self.departments = config.get("departments", [])
        self.embedder = None
        self._try_load_embedder()

    # ── 임베딩 모델 로드 (선택, 없으면 키워드만 사용) ──────────
    def _try_load_embedder(self):
        try:
            from sentence_transformers import SentenceTransformer, util
            self.embedder = SentenceTransformer("jhgan/ko-sroberta-multitask")
            self.sim_util = util
            logger.info("임베딩 모델 로드 완료 (하이브리드 매칭 활성화)")
        except ImportError:
            logger.info("sentence-transformers 미설치 → 키워드 매칭만 사용")

    # ── 메인 매칭 함수 ──────────────────────────────────────────
    def match(self, analysis: dict) -> List[dict]:
        """
        AI 분석 결과 → 추천 부서 리스트 반환
        Returns: [{"department": ..., "score": ..., "action_level": ..., "reason": ...}]
        """
        parts = [
            analysis.get("공고명", ""),
            analysis.get("요약", ""),
            " ".join(analysis.get("핵심키워드", [])),
            " ".join(analysis.get("사업분야", [])),
            " ".join(analysis.get("지원대상", [])),
        ]
        notice_text = " ".join(p for p in parts if p)

        matches = []
        for dept in self.departments:
            score, reasons = self._score_department(dept, notice_text, analysis)
            if score < 20:
                continue

            if score >= 70:
                action = "신청권고"
            elif score >= 45:
                action = "검토필요"
            else:
                action = "참고"

            matches.append({
                "department":   dept["name"],
                "score":        min(score, 100),
                "action_level": action,
                "reason":       " | ".join(reasons[:3]),
            })

        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:5]

    # ── 키워드 + 임베딩 점수 계산 ──────────────────────────────
    def _score_department(self, dept: dict, notice_text: str, analysis: dict):
        score = 0
        reasons = []
        dept_keywords = dept.get("keywords", [])

        # ① 키워드 매칭
        # 한국어 3자 이상 = 의미 있는 복합어 → 15점, 2자 이하(약어 등) → 8점
        for kw in dept_keywords:
            if kw in notice_text:
                pts = 15 if len(kw) >= 3 else 8
                score += pts
                reasons.append(f"키워드: {kw}")

        # ② 대학 신청 가능 대상 보너스
        targets = analysis.get("지원대상", [])
        if {"대학", "연구기관", "산학협력단", "비영리", "컨소시엄"} & set(targets):
            score += 10
            reasons.append("대학 신청 가능")

        # ③ AI 추천 부서 일치 보너스
        if dept["name"] in analysis.get("추천부서", []):
            score += 20
            reasons.append("AI 추천 일치")

        # ④ 임베딩 유사도 (sentence-transformers 설치 시)
        if self.embedder and dept_keywords and notice_text:
            try:
                dept_desc = " ".join(dept_keywords)
                emb_n = self.embedder.encode(notice_text[:500], convert_to_tensor=True)
                emb_d = self.embedder.encode(dept_desc, convert_to_tensor=True)
                sim = float(self.sim_util.cos_sim(emb_n, emb_d)[0][0])
                emb_score = int(sim * 30)
                if emb_score > 5:
                    score += emb_score
                    reasons.append(f"문맥유사도: {sim:.2f}")
            except Exception:
                pass

        return score, reasons
