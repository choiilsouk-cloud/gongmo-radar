"""
SQLite 데이터베이스 관리
"""

import hashlib
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "./data/gongmo.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_tables()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        # WAL 모드: 동시 읽기/쓰기 충돌 방지 (여러 수집기 병렬 실행 시 필수)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")    # WAL 환경에서 안전 + 빠름
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-8000")      # 8MB 캐시
        conn.execute("PRAGMA busy_timeout=5000")     # 5초 대기 후 OperationalError (잠금 충돌 방지)
        conn.execute("PRAGMA temp_store=MEMORY")     # 임시 데이터 메모리 처리 (디스크 흔적 최소화)
        return conn

    def _init_tables(self):
        with self._conn() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS notices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                source          TEXT,
                title           TEXT,
                url             TEXT,
                agency          TEXT,
                end_date        TEXT,
                post_date       TEXT,
                budget          TEXT,
                eligibility     INTEGER DEFAULT 0,
                importance      INTEGER DEFAULT 0,
                summary         TEXT,
                raw_text        TEXT,
                ai_result       TEXT,
                duplicate_key   TEXT UNIQUE,
                ai_error        INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS dept_matches (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id       INTEGER,
                department      TEXT,
                score           INTEGER,
                action_level    TEXT,
                reason          TEXT,
                notified        INTEGER DEFAULT 0,
                feedback        TEXT,
                created_at      TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (notice_id) REFERENCES notices(id)
            );

            CREATE TABLE IF NOT EXISTS notify_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                notice_id       INTEGER,
                department      TEXT,
                channel         TEXT,
                recipient       TEXT,
                sent_at         TEXT DEFAULT (datetime('now','localtime')),
                success         INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_notices_dup ON notices(duplicate_key);
            CREATE INDEX IF NOT EXISTS idx_matches_notice ON dept_matches(notice_id);

            CREATE TABLE IF NOT EXISTS collector_stats (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                date              TEXT NOT NULL,
                source            TEXT NOT NULL,
                count             INTEGER DEFAULT 0,
                status            TEXT DEFAULT 'ok',
                avg_30d           REAL DEFAULT 0,
                consecutive_zeros INTEGER DEFAULT 0,
                health_status     TEXT DEFAULT 'UNKNOWN',
                created_at        TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(date, source)
            );

            CREATE INDEX IF NOT EXISTS idx_cstats_date   ON collector_stats(date);
            CREATE INDEX IF NOT EXISTS idx_cstats_source ON collector_stats(source);
            """)

    # ── 공고 저장 ──────────────────────────────────────────────
    def save_notice(self, notice: dict, analysis: dict, matches: list) -> Optional[int]:
        dup_key = self._make_dup_key(notice)
        with self._conn() as conn:
            try:
                cur = conn.execute("""
                    INSERT INTO notices
                    (source, title, url, agency, end_date, post_date,
                     budget, eligibility, importance, summary,
                     raw_text, ai_result, duplicate_key, ai_error)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    notice.get("source"),
                    analysis.get("공고명") or notice.get("title"),
                    notice.get("url"),
                    analysis.get("주관기관") or notice.get("agency"),
                    analysis.get("접수마감일") or notice.get("end_date"),
                    notice.get("post_date"),
                    analysis.get("예산규모"),
                    analysis.get("대학신청가능성", 0),
                    analysis.get("대학신청가능성", 0),
                    analysis.get("요약"),
                    notice.get("raw_text", ""),
                    json.dumps(analysis, ensure_ascii=False),
                    dup_key,
                    1 if analysis.get("_ai_error") else 0
                ))
                notice_id = cur.lastrowid

                for m in matches:
                    conn.execute("""
                        INSERT INTO dept_matches
                        (notice_id, department, score, action_level, reason)
                        VALUES (?,?,?,?,?)
                    """, (
                        notice_id,
                        m["department"],
                        m["score"],
                        m["action_level"],
                        m["reason"]
                    ))
                return notice_id

            except sqlite3.IntegrityError:
                return None  # 중복 공고

    def _make_dup_key(self, notice: dict) -> str:
        """
        중복 판별 키 생성 — 3단계 폴백 전략:
        1순위: URL (공고번호 포함, 가장 정확)
        2순위: 제목(전체) + 기관 + 마감일
        3순위: 제목 앞 80자 + 기관 (최후 수단)
        """
        import re as _re

        url = (notice.get("url") or "").strip()
        title = _re.sub(r"\s+", "", (notice.get("title") or "")).lower()
        agency = (notice.get("agency") or "").strip()
        end_date = (notice.get("end_date") or "").strip()
        source = (notice.get("source") or "").strip()

        if url:
            # URL에서 쿼리스트링 파라미터 순서 무관하도록 정렬
            base = url.split("?")[0]
            params = sorted(url.split("?")[1].split("&")) if "?" in url else []
            canonical = base + ("?" + "&".join(params) if params else "")
            raw = f"url:{canonical}"
        elif title and agency:
            raw = f"ta:{title}|{agency}|{end_date}"
        else:
            raw = f"fb:{source}:{title[:80]}|{agency}"

        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    # ── 알림 대상 조회 ─────────────────────────────────────────
    def get_pending_notices_for_dept(
        self,
        dept: str,
        min_dept_score: int = 45,    # 검토필요 이상 (action_level 기준)
        min_eligibility: int = 60,   # 대학 신청 가능성 AI 판단 점수
    ) -> List[dict]:
        """
        미알림 공고 조회.
        - min_dept_score: 부서 매칭 점수 (기본 45 = '검토필요' 이상)
        - min_eligibility: AI가 판단한 대학 신청 가능성 (기본 60)
        """
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT n.*, dm.score, dm.action_level, dm.reason
                FROM notices n
                JOIN dept_matches dm ON n.id = dm.notice_id
                WHERE dm.department = ?
                  AND dm.score >= ?
                  AND dm.notified = 0
                  AND n.eligibility >= ?
                ORDER BY dm.score DESC
            """, (dept, min_dept_score, min_eligibility)).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def mark_notified(self, notice_id: int, dept: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE dept_matches SET notified=1 WHERE notice_id=? AND department=?",
                (notice_id, dept)
            )

    def log_notification(
        self, notice_id: int, dept: str, channel: str,
        recipient: str, success: bool
    ):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO notify_log
                (notice_id, department, channel, recipient, success)
                VALUES (?,?,?,?,?)
            """, (notice_id, dept, channel, recipient, 1 if success else 0))

    # ── 대시보드용 조회 ────────────────────────────────────────
    def get_today_notices(self) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM notices
                WHERE date(created_at) = date('now','localtime')
                ORDER BY eligibility DESC
            """).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_high_priority(self, limit: int = 20) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM notices
                WHERE eligibility >= 70
                ORDER BY eligibility DESC, created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def save_feedback(self, notice_id: int, dept: str, feedback: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE dept_matches SET feedback=? WHERE notice_id=? AND department=?",
                (feedback, notice_id, dept)
            )

    # ── 수집기 통계 (D안 모니터링) ────────────────────────────────
    def save_collector_stat(
        self,
        date: str,
        source: str,
        count: int,
        status: str = "ok",
        avg_30d: float = 0.0,
        consecutive_zeros: int = 0,
        health_status: str = "UNKNOWN",
    ):
        """날짜×수집기 통계 저장 (UPSERT)."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO collector_stats
                    (date, source, count, status, avg_30d, consecutive_zeros, health_status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, source) DO UPDATE SET
                    count             = excluded.count,
                    status            = excluded.status,
                    avg_30d           = excluded.avg_30d,
                    consecutive_zeros = excluded.consecutive_zeros,
                    health_status     = excluded.health_status
            """, (date, source, count, status, avg_30d, consecutive_zeros, health_status))

    def get_avg_30d(self, source: str) -> float:
        """최근 30일 평균 수집 건수 (0건 제외 평균)."""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT AVG(count) FROM collector_stats
                WHERE source = ?
                  AND date >= date('now', '-30 days', 'localtime')
                  AND status != 'failed'
            """, (source,)).fetchone()
            val = row[0] if row else None
            return round(float(val), 1) if val is not None else 0.0

    def get_consecutive_zeros(self, source: str) -> int:
        """연속 0건(또는 실패) 일수 계산."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT date, count, status FROM collector_stats
                WHERE source = ?
                ORDER BY date DESC
                LIMIT 14
            """, (source,)).fetchall()
        streak = 0
        for row in rows:
            if row["count"] == 0 or row["status"] in ("failed", "down"):
                streak += 1
            else:
                break
        return streak

    def get_collector_stats(self, source: str, days: int = 30) -> List[dict]:
        """최근 N일 수집기 통계 목록."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM collector_stats
                WHERE source = ?
                  AND date >= date('now', ?, 'localtime')
                ORDER BY date DESC
            """, (source, f"-{days} days")).fetchall()
            return [dict(r) for r in rows]

    def get_all_collector_summary(self) -> List[dict]:
        """모든 수집기의 최신 통계 요약 (GUI 상태 패널용)."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT cs.*
                FROM collector_stats cs
                INNER JOIN (
                    SELECT source, MAX(date) AS max_date
                    FROM collector_stats
                    GROUP BY source
                ) latest ON cs.source = latest.source AND cs.date = latest.max_date
                ORDER BY cs.source
            """).fetchall()
            return [dict(r) for r in rows]

    def get_weekly_stats(self) -> List[dict]:
        """주간 보고서용: 지난 7일간 수집기별 통계."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    source,
                    SUM(count)              AS total_7d,
                    ROUND(AVG(count), 1)    AS avg_7d,
                    SUM(CASE WHEN count = 0 OR status IN ('failed','down') THEN 1 ELSE 0 END) AS zero_days,
                    MAX(consecutive_zeros)  AS max_streak,
                    MIN(health_status)      AS worst_health
                FROM collector_stats
                WHERE date >= date('now', '-7 days', 'localtime')
                GROUP BY source
                ORDER BY source
            """).fetchall()
            return [dict(r) for r in rows]

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        if d.get("ai_result"):
            try:
                d["ai_result"] = json.loads(d["ai_result"])
            except Exception:
                pass
        return d
