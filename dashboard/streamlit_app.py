"""
공모레이더 관리자 대시보드 (Streamlit)
실행: streamlit run dashboard/streamlit_app.py
"""

import json
import sys
from pathlib import Path

import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.database import Database

# ── 페이지 설정 ────────────────────────────────────────────────
st.set_page_config(
    page_title="공모레이더 | 한서대학교",
    page_icon="📡",
    layout="wide",
)

# ── 스타일 ─────────────────────────────────────────────────────
st.markdown("""
<style>
  .main { background: #f5f6fa; }
  .score-high  { color: #27ae60; font-weight: bold; }
  .score-mid   { color: #e67e22; font-weight: bold; }
  .score-low   { color: #95a5a6; }
  .header-box  {
    background: #1F3864; color: white;
    padding: 16px 24px; border-radius: 8px; margin-bottom: 16px;
  }
  .badge-신청권고 { background:#27ae60; color:white; padding:2px 8px; border-radius:10px; font-size:12px; }
  .badge-검토필요 { background:#e67e22; color:white; padding:2px 8px; border-radius:10px; font-size:12px; }
  .badge-참고     { background:#95a5a6; color:white; padding:2px 8px; border-radius:10px; font-size:12px; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_db():
    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return Database(cfg["database"]["path"]), cfg


db, config = get_db()
dept_names = [d["name"] for d in config.get("departments", [])]

# ── 헤더 ───────────────────────────────────────────────────────
st.markdown(
    '<div class="header-box">'
    '<span style="font-size:22px; font-weight:bold;">📡 공모레이더</span>'
    '<span style="font-size:13px; opacity:0.8; margin-left:16px;">'
    '한서대학교 국가공모사업 자동탐지 시스템</span>'
    '</div>',
    unsafe_allow_html=True
)

# ── 사이드바 ───────────────────────────────────────────────────
st.sidebar.title("🔍 필터")
selected_dept   = st.sidebar.selectbox("부서", ["전체"] + dept_names)
min_score       = st.sidebar.slider("최소 신청가능성", 0, 100, 60)
selected_action = st.sidebar.selectbox(
    "조치 수준", ["전체", "신청권고", "검토필요", "참고"]
)
st.sidebar.markdown("---")
st.sidebar.markdown("**AI 엔진:** EXAONE 3.5 (Ollama)")
st.sidebar.markdown("**업데이트:** 매일 06:00")

# ── 탭 ─────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(
    ["📋 오늘 신규", "⭐ 중요 공고", "🏢 부서별 추천", "📊 수집 현황"]
)


# ── 공고 카드 렌더링 ────────────────────────────────────────────
def render_notice_card(n: dict, show_dept: bool = False):
    score = n.get("eligibility", 0)
    color = "#27ae60" if score >= 80 else "#e67e22" if score >= 60 else "#95a5a6"
    ai    = n.get("ai_result") or {}

    with st.container():
        col1, col2 = st.columns([9, 1])
        with col1:
            title = n.get("title", "제목 없음")
            url   = n.get("url", "#")
            st.markdown(f"**[{title}]({url})**")
            st.caption(
                f"🏛 {n.get('agency', '')}  |  "
                f"📅 마감: {n.get('end_date', '미상')}  |  "
                f"💰 {n.get('budget', '미상')}  |  "
                f"📂 {n.get('source', '')}"
            )
            if n.get("summary"):
                st.markdown(
                    f"<small>{n['summary']}</small>",
                    unsafe_allow_html=True
                )
            if isinstance(ai, dict) and ai.get("검토포인트"):
                points = ai["검토포인트"][:2]
                st.markdown(
                    "<small>💡 " + " / ".join(points) + "</small>",
                    unsafe_allow_html=True
                )
        with col2:
            st.markdown(
                f"<div style='text-align:center; padding:8px; "
                f"background:{color}; color:white; border-radius:8px; "
                f"font-weight:bold; font-size:18px;'>"
                f"{score}<br><small style='font-size:10px;'>점</small></div>",
                unsafe_allow_html=True
            )
        st.divider()


# ── 탭1: 오늘 신규 ─────────────────────────────────────────────
with tab1:
    today_notices = db.get_today_notices()
    filtered = [n for n in today_notices if n.get("eligibility", 0) >= min_score]

    col1, col2, col3 = st.columns(3)
    col1.metric("오늘 수집", f"{len(today_notices)}건")
    col2.metric("가능성 60+ 건", f"{len([n for n in today_notices if n.get('eligibility',0)>=60])}건")
    col3.metric("가능성 80+ 건", f"{len([n for n in today_notices if n.get('eligibility',0)>=80])}건")

    st.markdown(f"### 신규 공고 ({len(filtered)}건)")
    if not filtered:
        st.info("오늘 수집된 공고가 없습니다. 스케줄러가 실행 중인지 확인하세요.")
    for n in filtered:
        render_notice_card(n)


# ── 탭2: 중요 공고 ─────────────────────────────────────────────
with tab2:
    high = db.get_high_priority(limit=30)
    filtered_high = [n for n in high if n.get("eligibility", 0) >= min_score]

    st.markdown(f"### 신청 가능성 높은 공고 ({len(filtered_high)}건)")
    for n in filtered_high:
        render_notice_card(n)


# ── 탭3: 부서별 추천 ───────────────────────────────────────────
with tab3:
    if selected_dept == "전체":
        st.info("사이드바에서 부서를 선택하면 해당 부서 추천 공고를 확인할 수 있습니다.")
    else:
        dept_notices = db.get_pending_notices_for_dept(selected_dept, min_score)
        st.markdown(f"### [{selected_dept}] 추천 공고 ({len(dept_notices)}건)")

        if not dept_notices:
            st.success("현재 검토 필요한 공고가 없습니다.")
        else:
            for n in dept_notices:
                action = n.get("action_level", "참고")
                badge  = f'<span class="badge-{action}">{action}</span>'
                st.markdown(badge, unsafe_allow_html=True)
                render_notice_card(n)

                # 피드백 버튼
                cols = st.columns(4)
                fb_options = ["관심있음", "신청검토", "신청완료", "제외"]
                for i, fb in enumerate(fb_options):
                    if cols[i].button(fb, key=f"fb_{n['id']}_{fb}"):
                        db.save_feedback(n["id"], selected_dept, fb)
                        st.success(f"'{fb}'로 저장되었습니다.")
                        st.rerun()


# ── 탭4: 수집 현황 ─────────────────────────────────────────────
with tab4:
    st.markdown("### 수집 현황")

    import sqlite3
    with sqlite3.connect(config["database"]["path"]) as conn:
        conn.row_factory = sqlite3.Row

        # 소스별 통계
        rows = conn.execute("""
            SELECT source, COUNT(*) as cnt,
                   AVG(eligibility) as avg_score,
                   MAX(created_at) as last_collected
            FROM notices
            GROUP BY source
            ORDER BY cnt DESC
        """).fetchall()

    if rows:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in rows])
        df.columns = ["수집소스", "공고수", "평균가능성", "마지막수집"]
        df["평균가능성"] = df["평균가능성"].round(1)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("아직 수집된 데이터가 없습니다.")

    st.markdown("---")
    st.markdown("**⚙️ 수동 실행 (테스트)**")
    if st.button("🔄 지금 즉시 수집 실행"):
        import subprocess
        subprocess.Popen(
            ["python", "-m", "app.scheduler", "--now"],
            cwd=str(Path(__file__).parent.parent)
        )
        st.success("수집 시작됨. 잠시 후 새로고침하세요.")
