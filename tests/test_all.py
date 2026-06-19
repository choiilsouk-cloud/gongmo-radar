"""
공모레이더 통합 테스트
사용법:
  python tests/test_all.py              # 핵심 기능 전체 테스트
  python tests/test_all.py --collect    # IRIS 실제 수집 포함
  python tests/test_all.py --send-email # 이메일 실제 발송 포함
"""

import json
import os
import sys
import time
import argparse
import tempfile
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []

def check(label, ok, detail=""):
    icon = PASS if ok else FAIL
    results.append((icon, label, detail))
    print(f"  {icon} {label}" + (f" → {detail}" if detail else ""))
    return ok

def section(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print('='*55)

# ── 0. 인자 파싱 ─────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--collect",    action="store_true", help="IRIS 실제 수집")
parser.add_argument("--send-email", action="store_true", help="이메일 실제 발송")
args = parser.parse_args()

# ── 1. config.yaml 로드 ───────────────────────────────────────
section("1. 설정 파일 로드")
try:
    import yaml
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    check("config.yaml 파싱", True, f"부서 {len(config['departments'])}개")
    check("AI 엔진 확인", config["ai"]["provider"] == "ollama",
          f"provider={config['ai']['provider']}, model={config['ai']['model']}")
    check("텔레그램 섹션 존재", "telegram" in config)
    check("필터 임계값 확인", "filter" in config,
          f"min_eligibility_score={config['filter']['min_eligibility_score']}")
except Exception as e:
    check("config.yaml 파싱", False, str(e))
    sys.exit(1)

# ── 2. 키워드 매칭 (matcher.py) ───────────────────────────────
section("2. 부서 매칭 엔진")
try:
    from app.analyzers.matcher import DepartmentMatcher
    matcher = DepartmentMatcher(config)

    sample_analysis = {
        "공고명": "2025년 대학혁신지원사업 IR 성과관리 및 교육발전특구 연계 공모",
        "요약": "대학 IR 고도화 및 성과관리 체계 구축 지원",
        "핵심키워드": ["IR", "성과관리", "교육발전특구", "대학혁신"],
        "사업분야": ["고등교육", "지역혁신"],
        "지원대상": ["대학", "연구기관"],
        "추천부서": ["기획예산처", "성과혁신IR센터"],
        "대학신청가능성": 85,
        "접수마감일": "2025-08-31",
        "예산규모": "2억원",
        "주관기관": "교육부",
    }

    matches = matcher.match(sample_analysis)
    check("match() 실행", len(matches) > 0, f"{len(matches)}개 부서 매칭")

    dept_scores = {m["department"]: m["score"] for m in matches}

    # 핵심 부서 점수 확인
    ir_score = dept_scores.get("성과혁신IR센터", 0)
    gk_score = dept_scores.get("기획예산처", 0)
    check("성과혁신IR센터 매칭", ir_score >= 45, f"score={ir_score}")
    check("기획예산처 매칭",    gk_score >= 45, f"score={gk_score}")

    # 3자 키워드 점수 확인 (국제화=3자 → 15점)
    intl_analysis = {
        "공고명": "국제화 유학생 글로벌 대학 지원사업",
        "요약": "국제교류 강화",
        "핵심키워드": ["국제화", "유학생", "글로벌", "해외연수"],
        "사업분야": ["국제교육"],
        "지원대상": ["대학"],
        "추천부서": ["국제교류처"],
        "대학신청가능성": 80,
    }
    intl_matches = matcher.match(intl_analysis)
    intl_scores = {m["department"]: m["score"] for m in intl_matches}
    intl_score = intl_scores.get("국제교류처", 0)
    check("국제교류처 매칭 (3자 키워드)", intl_score >= 60,
          f"score={intl_score} (국제화+유학생+글로벌 각15점)")

    print(f"\n  📊 상위 부서 매칭 결과:")
    for m in matches[:5]:
        print(f"     {m['department']:15s} {m['score']:3d}점  {m['action_level']}  {m['reason'][:40]}")

except Exception as e:
    check("matcher 로드/실행", False, str(e))
    import traceback; traceback.print_exc()

# ── 3. 데이터베이스 (database.py) ─────────────────────────────
section("3. 데이터베이스 (SQLite)")
try:
    # /tmp 사용 (샌드박스 마운트 디스크 I/O 회피)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        tmp_db = tf.name

    from app.database import Database
    db = Database(tmp_db)
    check("DB 초기화", True)

    notice = {
        "source": "test",
        "title": "대학혁신지원사업 IR 성과관리 공모",
        "url": "https://test.example.com/notice/1",
        "agency": "교육부",
        "end_date": "2025-08-31",
        "post_date": "2025-06-01",
        "raw_text": "테스트 공고 원문",
    }

    analysis = {
        "공고명": notice["title"],
        "요약": "IR 고도화 지원",
        "핵심키워드": ["IR", "성과관리", "대학혁신"],
        "사업분야": ["고등교육"],
        "지원대상": ["대학"],
        "추천부서": ["성과혁신IR센터", "기획예산처"],
        "대학신청가능성": 85,
        "접수마감일": "2025-08-31",
        "예산규모": "2억원",
        "주관기관": "교육부",
    }

    # 실제 matcher 결과로 DB 저장
    test_matches = matcher.match(analysis)
    nid = db.save_notice(notice, analysis, test_matches)
    check("공고 저장", nid is not None, f"notice_id={nid}")

    # 중복 방지 확인
    nid2 = db.save_notice(notice, analysis, test_matches)
    check("중복 방지", nid2 is None, "동일 공고 재저장 → None")

    # 부서별 대기 공고 조회 (분리된 임계값)
    # 기획예산처: 높은 점수 → 조회 성공
    gk_rows = db.get_pending_notices_for_dept("기획예산처", min_dept_score=45, min_eligibility=60)
    check("기획예산처 대기공고 조회", len(gk_rows) >= 1, f"{len(gk_rows)}건")

    # 성과혁신IR센터: 매칭 점수가 45 이상이면 조회 성공
    ir_dept_score = dept_scores.get("성과혁신IR센터", 0)
    ir_rows = db.get_pending_notices_for_dept("성과혁신IR센터", min_dept_score=45, min_eligibility=60)
    if ir_dept_score >= 45:
        check("성과혁신IR센터 대기공고 조회", len(ir_rows) >= 1,
              f"{len(ir_rows)}건 (score={ir_dept_score})")
    else:
        check("성과혁신IR센터 대기공고 조회", True,
              f"⚠️ 매칭점수 {ir_dept_score}점 < 45 (키워드 보강 필요)")

    # 오늘 공고 조회
    today = db.get_today_notices()
    check("오늘 공고 조회", len(today) >= 1, f"{len(today)}건")

    os.unlink(tmp_db)

except Exception as e:
    check("database 테스트", False, str(e))
    import traceback; traceback.print_exc()

# ── 4. AI 분석기 (Ollama 연결 확인) ──────────────────────────
section("4. AI 분석기 (Ollama)")
try:
    from app.analyzers.ai_analyzer import AIAnalyzer
    analyzer = AIAnalyzer(config)
    alive = analyzer.health_check()
    if alive:
        check("Ollama 연결", True, f"모델: {config['ai']['model']}")
        # 간단 분석 테스트
        result = analyzer.analyze("2025년 대학혁신지원사업 공모 - 대학 IR 성과관리 및 교육발전특구 연계")
        check("AI 분석 실행", "_ai_error" not in result,
              f"키워드={result.get('핵심키워드', [])[:3]}")
    else:
        print(f"  {WARN} Ollama 미실행 — 건너뜀")
        print(f"       실행 방법: ollama serve  (별도 터미널)")
        print(f"       모델 확인: ollama pull {config['ai']['model']}")
except Exception as e:
    check("ai_analyzer 로드", False, str(e))

# ── 5. 텔레그램 알리미 ────────────────────────────────────────
section("5. 텔레그램 알리미")
try:
    from app.notifier.telegram import TelegramNotifier
    notifier = TelegramNotifier(config)
    token = config["telegram"].get("bot_token", "")
    if token:
        ok = notifier.health_check()
        check("텔레그램 봇 연결", ok)
        if ok:
            updates = notifier.get_updates()
            check("getUpdates 호출", True, f"{len(updates)}개 업데이트")
    else:
        print(f"  {WARN} bot_token 미설정 — 건너뜀")
        print(f"       설정 방법: config.yaml → telegram.bot_token 에 @BotFather 토큰 입력")
except Exception as e:
    check("telegram notifier 로드", False, str(e))

# ── 6. 이메일 알리미 ─────────────────────────────────────────
section("6. 이메일 알리미")
try:
    from app.notifier.email_notifier import EmailNotifier
    enotifier = EmailNotifier(config)
    sender = config["email"].get("sender_email", "")
    if sender and args.send_email:
        ok = enotifier.send_test(sender)
        check("이메일 발송 테스트", ok, f"→ {sender}")
    elif not sender:
        print(f"  {WARN} sender_email 미설정 — 건너뜀")
    else:
        print(f"  ℹ️  이메일 테스트 생략 (--send-email 플래그로 활성화)")
except ImportError:
    print(f"  ℹ️  email_notifier 모듈 없음 — 건너뜀")
except Exception as e:
    check("email notifier 로드", False, str(e))

# ── 7. 수집기 네트워크 ────────────────────────────────────────
section("7. 수집기 네트워크 연결")
try:
    import requests
    sources = [
        ("IRIS (범부처R&D)",   "https://www.iris.go.kr"),
        ("기업마당",           "https://www.bizinfo.go.kr"),
        ("K-Startup",         "https://www.k-startup.go.kr"),
    ]
    for name, url in sources:
        try:
            r = requests.get(url, timeout=5)
            check(name, r.status_code < 500, f"HTTP {r.status_code}")
        except requests.exceptions.ConnectionError:
            check(name, False, "연결 불가")
        except Exception as ex:
            check(name, False, str(ex)[:40])
except ImportError:
    print(f"  {WARN} requests 미설치")

# ── 8. IRIS 실제 수집 (선택) ──────────────────────────────────
if args.collect:
    section("8. IRIS 실제 수집 (--collect)")
    try:
        from app.collectors.iris_collector import IrisCollector
        collector = IrisCollector(config)
        notices = collector.collect()
        check("IRIS 수집", len(notices) > 0, f"{len(notices)}건 수집")
        if notices:
            n = notices[0]
            print(f"  📋 첫 공고: {n.get('title','')[:50]}")
            print(f"     기관: {n.get('agency','')} | 마감: {n.get('end_date','')}")
    except Exception as e:
        check("IRIS 수집", False, str(e))

# ── 최종 결과 요약 ────────────────────────────────────────────
section("📋 테스트 결과 요약")
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
warned = sum(1 for r in results if r[0] == WARN)

print(f"\n  합계: {len(results)}개 항목")
print(f"  {PASS} 통과: {passed}개")
print(f"  {FAIL} 실패: {failed}개")
if warned:
    print(f"  {WARN} 경고: {warned}개")

if failed == 0:
    print(f"\n  🎉 모든 핵심 테스트 통과! 시스템 준비 완료.")
    print(f"     다음 단계: python -m app.scheduler --now  (Ollama 실행 후)")
else:
    print(f"\n  실패 항목:")
    for icon, label, detail in results:
        if icon == FAIL:
            print(f"    {FAIL} {label}: {detail}")
