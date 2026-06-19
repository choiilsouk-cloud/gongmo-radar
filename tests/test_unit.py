"""
pytest 단위 테스트 — Ollama/외부 API 호출 없음 (CI safe)
실행: pytest tests/test_unit.py -v
"""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────
# Database 테스트
# ─────────────────────────────────────────────
@pytest.fixture
def tmp_db(tmp_path):
    from app.database import Database
    db = Database(str(tmp_path / "test.db"))
    # __init__ 에서 _init_tables() 자동 호출
    return db


class TestDatabase:
    def test_wal_mode(self, tmp_db):
        """WAL 저널 모드 활성화 확인."""
        with tmp_db._conn() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal", f"journal_mode={mode}"

    def test_insert_and_count(self, tmp_db):
        """공고 삽입 후 DB 건수 확인."""
        notice = {
            "title": "테스트 공고",
            "agency": "한서대학교",
            "source": "test",
            "url": "https://example.com/notice/1",
            "post_date": "2024-01-01",
            "end_date": "2024-06-30",
            "raw_text": "테스트",
        }
        analysis = {"응모신청가능성": 80, "요약": "좋음", "_ai_error": 0}
        tmp_db.save_notice(notice, analysis, [])

        with tmp_db._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
        assert count == 1

    def test_duplicate_ignored(self, tmp_db):
        """동일 공고 재삽입 시 무시 — 건수 유지."""
        notice = {
            "title": "중복 공고", "agency": "기관",
            "source": "dup", "url": "https://example.com/dup",
            "post_date": "2024-01-01", "end_date": "2024-12-31", "raw_text": "",
        }
        analysis = {"응모신청가능성": 50, "요약": ""}
        tmp_db.save_notice(notice, analysis, [])
        tmp_db.save_notice(notice, analysis, [])

        with tmp_db._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
        assert count == 1

    def test_dup_key_url_normalized(self, tmp_db):
        """URL 파라미터 순서 달라도 동일 dup_key."""
        n1 = {"url": "https://a.com/p?b=2&a=1", "title": "T", "agency": "A",
              "source": "x", "post_date": "", "end_date": ""}
        n2 = {"url": "https://a.com/p?a=1&b=2", "title": "T2", "agency": "A2",
              "source": "x", "post_date": "", "end_date": ""}
        assert tmp_db._make_dup_key(n1) == tmp_db._make_dup_key(n2)

    def test_dup_key_title_agency_fallback(self, tmp_db):
        """URL 없을 때 title+agency 기반 키 = 32자 md5."""
        n = {"url": "", "title": "공모 사업", "agency": "한서대",
             "source": "x", "post_date": "", "end_date": "2024-12-31"}
        k = tmp_db._make_dup_key(n)
        assert len(k) == 32

    def test_dup_key_whitespace_normalized(self, tmp_db):
        """공백 차이 무시."""
        n1 = {"url": "", "title": "공모  사업", "agency": "기관",
              "source": "x", "post_date": "", "end_date": "2024-01-01"}
        n2 = {"url": "", "title": "공모 사업", "agency": "기관",
              "source": "x", "post_date": "", "end_date": "2024-01-01"}
        assert tmp_db._make_dup_key(n1) == tmp_db._make_dup_key(n2)


# ─────────────────────────────────────────────
# AI Analyzer — Ollama 미호출 파싱 테스트
# ─────────────────────────────────────────────
@pytest.fixture
def analyzer():
    from app.analyzers.ai_analyzer import AIAnalyzer
    return AIAnalyzer.__new__(AIAnalyzer)


class TestAiAnalyzer:
    def test_parse_clean_json(self, analyzer):
        raw = '{"응모신청가능성": 85, "요약": "우수", "체크포인트": ["A"], "지원분야": [], "규모구분": "대형"}'
        r = analyzer._parse_response(raw)
        assert r["응모신청가능성"] == 85

    def test_parse_markdown_fence(self, analyzer):
        raw = '```json\n{"응모신청가능성": 70, "요약": "보통"}\n```'
        r = analyzer._parse_response(raw)
        assert r["응모신청가능성"] == 70

    def test_parse_prefix_text(self, analyzer):
        raw = '분석 결과:\n{"응모신청가능성": 60, "요약": "낮음"}\n이상.'
        r = analyzer._parse_response(raw)
        assert r["응모신청가능성"] == 60

    def test_score_clamp_high(self, analyzer):
        r = analyzer._parse_response('{"응모신청가능성": 150, "요약": ""}')
        assert r["응모신청가능성"] == 100

    def test_score_clamp_low(self, analyzer):
        r = analyzer._parse_response('{"응모신청가능성": -10, "요약": ""}')
        assert r["응모신청가능성"] == 0

    def test_score_string_percent(self, analyzer):
        r = analyzer._parse_response('{"응모신청가능성": "75%", "요약": "양호"}')
        assert r["응모신청가능성"] == 75

    def test_invalid_json_fallback(self, analyzer):
        r = analyzer._parse_response("JSON 아님")
        assert "응모신청가능성" in r
        assert r.get("_ai_error") is not None

    def test_list_fields_coerced(self, analyzer):
        r = analyzer._parse_response('{"응모신청가능성": 50, "체크포인트": "마감임박", "지원분야": "ICT"}')
        assert isinstance(r["체크포인트"], list)
        assert isinstance(r["지원분야"], list)

    def test_fallback_required_keys(self, analyzer):
        fb = analyzer._fallback_result()
        for k in ["응모신청가능성", "요약", "체크포인트", "지원분야", "_ai_error"]:
            assert k in fb


# ─────────────────────────────────────────────
# Auto Updater — 버전 비교 (module-level 함수)
# ─────────────────────────────────────────────
class TestAutoUpdater:
    def test_newer(self):
        from app.auto_updater import _is_newer
        assert _is_newer("1.1.0", "1.0.0") is True

    def test_same(self):
        from app.auto_updater import _is_newer
        assert _is_newer("1.0.0", "1.0.0") is False

    def test_older(self):
        from app.auto_updater import _is_newer
        assert _is_newer("0.9.9", "1.0.0") is False

    def test_patch_bump(self):
        from app.auto_updater import _is_newer
        assert _is_newer("1.0.1", "1.0.0") is True

    def test_major_bump(self):
        from app.auto_updater import _is_newer
        assert _is_newer("2.0.0", "1.9.9") is True


# ─────────────────────────────────────────────
# Health Checker — 임포트 + 기본 구조
# ─────────────────────────────────────────────
class TestHealthChecker:
    def test_import(self):
        from app.health_checker import HealthChecker
        assert HealthChecker is not None

    def test_instantiate(self):
        from app.health_checker import HealthChecker
        hc = HealthChecker()
        assert hasattr(hc, "check")
        assert callable(hc.check)

    def test_unknown_source_returns_skip(self):
        from app.health_checker import HealthChecker
        hc = HealthChecker()
        result = hc.check("__nonexistent_source_xyz__")
        assert "status" in result
        # SKIP 또는 error 형태 dict 반환
        assert isinstance(result, dict)


# ─────────────────────────────────────────────
# Custom Collector — 소스 파일 로드
# ─────────────────────────────────────────────
class TestCustomCollector:
    def test_load_sources_empty(self, tmp_path):
        from app.collectors.custom_collector import CustomCollector
        cc = CustomCollector.__new__(CustomCollector)
        cc.sources_file = str(tmp_path / "nonexistent.json")
        result = cc.load_sources()
        assert result == []

    def test_load_sources_valid(self, tmp_path):
        src_file = tmp_path / "custom_sources.json"
        data = [{"name": "테스트", "url": "https://example.com",
                 "selector": "div.title", "enabled": True}]
        src_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        from app.collectors.custom_collector import CustomCollector
        cc = CustomCollector.__new__(CustomCollector)
        cc.sources_file = str(src_file)
        result = cc.load_sources()
        assert len(result) == 1
        assert result[0]["name"] == "테스트"

    def test_load_sources_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ not valid json", encoding="utf-8")

        from app.collectors.custom_collector import CustomCollector
        cc = CustomCollector.__new__(CustomCollector)
        cc.sources_file = str(bad_file)
        result = cc.load_sources()
        assert result == []
