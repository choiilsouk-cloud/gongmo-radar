# -*- coding: utf-8 -*-
"""
공모레이더 GUI - 한서대학교 성과혁신IR센터
============================================================
누구나 사용 가능한 단독 실행 프로그램 (Python / .exe 모두 지원)

기능:
  - 수집처 선택 (기본 소스 + 사용자 정의 추가/삭제)
  - 공고 수집 실행 (백그라운드 스레드)
  - AI 분석 (Ollama 있을 때 자동, 없으면 스킵)
  - 결과 테이블 표시
  - Excel 내보내기

실행: python gui_app.py
빌드: pyinstaller --onefile --windowed --icon=icon.ico gui_app.py
"""

import io
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from tkinter import (
    BooleanVar, END, IntVar, StringVar,
    filedialog, messagebox, scrolledtext, simpledialog
)
import tkinter as tk
import tkinter.ttk as ttk

# ── 경로 설정 (exe 패키징 시 __file__ 이슈 처리) ─────────────────
if getattr(sys, "frozen", False):
    # PyInstaller로 패키징된 경우
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, APP_DIR)

# ── Windows UTF-8 출력 ──────────────────────────────────────────
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 로깅 설정 ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

# ── 컬러 팔레트 ──────────────────────────────────────────────────
# ── 전문 디자인 팔레트 (상업용 소프트웨어 기준) ────────────────
NAVY     = "#1F3864"    # 브랜드 프라이머리
NAVY_DK  = "#152A4E"    # 사이드바 배경
NAVY_HL  = "#263D6E"    # 호버/선택
GOLD     = "#C9A84C"    # 브랜드 액센트
GOLD_LT  = "#EDD98A"    # 라이트 골드
WHITE    = "#FFFFFF"
BG       = "#F1F5F9"    # 페이지 배경
SURFACE  = "#FFFFFF"    # 카드 표면
BORDER   = "#E2E8F0"    # 카드 경계선
BORDER_DK= "#CBD5E1"    # 강조 경계선
LIGHT    = "#F8FAFC"    # 미묘한 배경
TEXT     = "#1E293B"    # 주 텍스트
MUTED    = "#64748B"    # 보조 텍스트
# 시맨틱 컬러
GREEN    = "#059669"    # 성공
GREEN_LT = "#D1FAE5"    # 성공 배경
RED      = "#DC2626"    # 위험
RED_LT   = "#FEE2E2"    # 위험 배경
AMBER    = "#D97706"    # 경고
AMBER_LT = "#FEF3C7"    # 경고 배경
BLUE     = "#2563EB"    # 정보
BLUE_LT  = "#DBEAFE"    # 정보 배경
GRAY     = "#64748B"    # 중성

CUSTOM_SOURCES_FILE = os.path.join(APP_DIR, "custom_sources.json")


# ════════════════════════════════════════════════════════════════
# 수집처 정의
# ════════════════════════════════════════════════════════════════
BUILTIN_SOURCES = [
    # (key, display_name, category, default_enabled)
    ("iris",        "IRIS (범부처 R&D 통합)",         "R&D/연구",    True),
    ("nrf",         "한국연구재단(NRF)",               "R&D/연구",    True),
    ("ntis",        "NTIS (국가과학기술정보서비스)",    "R&D/연구",    True),
    ("bojo",        "e나라도움 (정부보조금)",           "보조금",      True),
    ("bizinfo",     "기업마당 (중소기업지원)",           "기업지원",    True),
    ("kstartup",    "K-Startup (창업지원)",             "창업",        True),
    ("g2b",         "나라장터 (G2B 공모/용역)",         "조달/공모",   True),
    ("ministry",    "중앙행정기관 (교육부·과기부 등)",  "정부부처",    True),
    ("regional",    "지자체 (충남도청·서산시·교육청)",  "지자체",      True),
]

SOURCE_CATEGORY_COLORS = {
    "R&D/연구":  "#1F3864",
    "보조금":    "#375623",
    "기업지원":  "#833C00",
    "창업":      "#7030A0",
    "조달/공모": "#006B6B",
    "정부부처":  "#C00000",
    "지자체":    "#00538A",
}


# ════════════════════════════════════════════════════════════════
# 수집 엔진 (GUI와 분리된 worker)
# ════════════════════════════════════════════════════════════════
class CollectionWorker:
    """백그라운드 수집 스레드용 워커"""

    def __init__(self, selected_sources: list, days_back: int,
                 use_ai: bool, progress_queue: queue.Queue):
        self.selected = set(selected_sources)
        self.days_back = days_back
        self.use_ai = use_ai
        self.q = progress_queue
        self.notices = []
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self._collect()
        except Exception as e:
            self.q.put(("error", str(e)))
        finally:
            self.q.put(("done", self.notices))

    def _collect(self):
        all_notices = []

        # ── IRIS ──────────────────────────────────────
        if "iris" in self.selected and not self._stop:
            self.q.put(("progress", "IRIS (범부처 R&D) 수집 중..."))
            try:
                from app.collectors.iris_collector import IrisCollector
                items = IrisCollector().collect(self.days_back)
                all_notices.extend(items)
                self.q.put(("tick", f"IRIS: {len(items)}건"))
            except Exception as e:
                self.q.put(("warn", f"IRIS 오류: {e}"))

        # ── NRF ──────────────────────────────────────
        if "nrf" in self.selected and not self._stop:
            self.q.put(("progress", "한국연구재단 수집 중..."))
            try:
                from app.collectors.nrf_collector import NrfCollector
                items = NrfCollector().collect(self.days_back)
                all_notices.extend(items)
                self.q.put(("tick", f"연구재단: {len(items)}건"))
            except Exception as e:
                self.q.put(("warn", f"연구재단 오류: {e}"))

        # ── NTIS (웹 크롤링 - API 키 불필요) ──────────────────────
        if "ntis" in self.selected and not self._stop:
            self.q.put(("progress", "NTIS 수집 중..."))
            try:
                from app.collectors.ntis_collector import NtisCollector
                items = NtisCollector().collect(self.days_back)
                all_notices.extend(items)
                msg = f"NTIS: {len(items)}건" if items else "NTIS: 수집 결과 없음 (사이트 응답 확인 필요)"
                self.q.put(("tick", msg))
            except Exception as e:
                self.q.put(("warn", f"NTIS 오류: {e}"))

        # ── 보조금 ────────────────────────────────────
        if "bojo" in self.selected and not self._stop:
            self.q.put(("progress", "e나라도움 수집 중..."))
            try:
                from app.collectors.iris_collector import BojocollectorWrapper
                dgk_key = self._load_config_key("data_go_kr_api_key")
                items = BojocollectorWrapper(api_key=dgk_key).collect(self.days_back)
                all_notices.extend(items)
                self.q.put(("tick", f"e나라도움: {len(items)}건"))
            except Exception as e:
                self.q.put(("warn", f"e나라도움 오류: {e}"))

        # ── 기업마당 ──────────────────────────────────
        if "bizinfo" in self.selected and not self._stop:
            self.q.put(("progress", "기업마당 수집 중..."))
            try:
                from app.collectors.iris_collector import BizinfoCollector
                items = BizinfoCollector().collect(self.days_back)
                all_notices.extend(items)
                self.q.put(("tick", f"기업마당: {len(items)}건"))
            except Exception as e:
                self.q.put(("warn", f"기업마당 오류: {e}"))

        # ── K-Startup (k-skill-proxy 경유, API 키 불필요) ───────────
        if "kstartup" in self.selected and not self._stop:
            self.q.put(("progress", "K-Startup 수집 중..."))
            try:
                from app.collectors.kstartup_collector import KstartupCollector
                ks_key = self._load_config_key("kstartup_api_key")
                items = KstartupCollector(api_key=ks_key).collect(self.days_back)
                all_notices.extend(items)
                self.q.put(("tick", f"K-Startup: {len(items)}건"))
            except Exception as e:
                self.q.put(("warn", f"K-Startup 오류: {e}"))

        # ── 나라장터 ──────────────────────────────────
        if "g2b" in self.selected and not self._stop:
            self.q.put(("progress", "나라장터 수집 중..."))
            try:
                from app.collectors.g2b_collector import G2bCollector
                g2b_key = self._load_config_key("data_go_kr_api_key")
                items = G2bCollector(api_key=g2b_key).collect(self.days_back)
                all_notices.extend(items)
                self.q.put(("tick", f"나라장터: {len(items)}건"))
            except Exception as e:
                self.q.put(("warn", f"나라장터 오류: {e}"))

        # ── 중앙부처 ──────────────────────────────────
        if "ministry" in self.selected and not self._stop:
            self.q.put(("progress", "중앙행정기관 수집 중 (시간 소요)..."))
            try:
                from app.collectors.ministry_collector import MinistryCollector
                items = MinistryCollector().collect(self.days_back)
                all_notices.extend(items)
                self.q.put(("tick", f"중앙부처: {len(items)}건"))
            except Exception as e:
                self.q.put(("warn", f"중앙부처 오류: {e}"))

        # ── 지자체 ────────────────────────────────────
        if "regional" in self.selected and not self._stop:
            self.q.put(("progress", "지자체 수집 중..."))
            try:
                from app.collectors.iris_collector import RegionalCollector
                items = RegionalCollector().collect()
                all_notices.extend(items)
                self.q.put(("tick", f"지자체: {len(items)}건"))
            except Exception as e:
                self.q.put(("warn", f"지자체 오류: {e}"))

        # ── 사용자 정의 ───────────────────────────────
        if not self._stop:
            self.q.put(("progress", "사용자 정의 수집처 수집 중..."))
            try:
                from app.collectors.custom_collector import CustomCollector
                cc = CustomCollector(CUSTOM_SOURCES_FILE)
                items = cc.collect(self.days_back)
                if items:
                    all_notices.extend(items)
                    self.q.put(("tick", f"사용자정의: {len(items)}건"))
            except Exception as e:
                self.q.put(("warn", f"사용자정의 오류: {e}"))

        # ── AI 분석 ───────────────────────────────────
        if self.use_ai and all_notices and not self._stop:
            self.q.put(("progress", "AI 분석 중 (Ollama)..."))
            analyzed = self._analyze_with_ai(all_notices)
            all_notices = analyzed

        self.notices = all_notices

    def _load_config_key(self, key: str) -> str:
        """config.yaml에서 API 키 한 개를 읽어 반환. 없으면 빈 문자열."""
        try:
            import yaml
            cfg_path = os.path.join(APP_DIR, "config.yaml")
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            return cfg.get(key, "") or ""
        except Exception:
            return ""

    def _analyze_with_ai(self, notices: list) -> list:
        """Ollama로 AI 분석 (간략 버전 - 배치 처리)"""
        try:
            import requests as req
            req.get("http://localhost:11434", timeout=2)
        except Exception:
            self.q.put(("warn", "Ollama 미실행 → AI 분석 스킵"))
            return notices

        config_path = os.path.join(APP_DIR, "config.yaml")
        model = "exaone3.5:7.8b"
        try:
            import yaml
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            model = cfg.get("ai", {}).get("model", model)
        except Exception:
            pass

        import requests as req
        analyzed = []
        for i, notice in enumerate(notices):
            if self._stop:
                break
            if i % 10 == 0:
                self.q.put(("progress", f"AI 분석 중... ({i}/{len(notices)})"))

            title = notice.get("title", "")[:200]
            agency = notice.get("agency", "")

            prompt = (
                f"아래 공고가 대학(교)이 신청 가능한지 0-100점으로 평가해.\n"
                f"공고: {title}\n발주기관: {agency}\n\n"
                f"JSON으로만 답해: {{\"score\": 점수, \"reason\": \"이유 한줄\"}}"
            )
            try:
                resp = req.post(
                    "http://localhost:11434/api/generate",
                    json={"model": model, "prompt": prompt,
                          "stream": False, "options": {"temperature": 0.1, "num_predict": 100}},
                    timeout=30
                )
                raw = resp.json().get("response", "{}")
                # JSON 추출
                import re
                m = re.search(r'\{.*?\}', raw, re.DOTALL)
                if m:
                    data = json.loads(m.group())
                    notice["ai_score"] = data.get("score", 0)
                    notice["ai_reason"] = data.get("reason", "")
            except Exception:
                pass

            analyzed.append(notice)

        return analyzed


# ════════════════════════════════════════════════════════════════
# GUI 메인 앱
# ════════════════════════════════════════════════════════════════
class GongmoRadarApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("공모레이더 v2.0 - 한서대학교 성과혁신IR센터")
        self.root.geometry("1280x820")
        self.root.minsize(1000, 650)
        self.root.configure(bg=BG)

        # 상태
        self.source_vars = {}       # {key: BooleanVar}
        self.custom_sources = []    # [{id, name, url, ...}]
        self.notices = []           # 수집 결과
        self.worker = None
        self.worker_thread = None
        self.progress_queue = queue.Queue()
        self.is_running = False

        # UI 구성
        self._setup_styles()
        self._build_ui()
        self._load_custom_sources()
        self._check_ollama_status()

        # 주기적 큐 처리
        self.root.after(200, self._process_queue)

    # ────────────────────────────────────────────────────────────
    # 스타일 설정
    # ────────────────────────────────────────────────────────────
    def _setup_styles(self):
        """ttk 전체 테마 — 상업용 소프트웨어 기준"""
        s = ttk.Style()
        s.theme_use("clam")
        # 노트북 탭
        s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=[0, 0, 0, 0])
        s.configure("TNotebook.Tab",
                    font=("맑은 고딕", 10), padding=[18, 9],
                    background=BORDER, foreground=MUTED)
        s.map("TNotebook.Tab",
              background=[("selected", SURFACE), ("active", LIGHT)],
              foreground=[("selected", NAVY), ("active", TEXT)])
        # Treeview
        s.configure("Pro.Treeview",
                    background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, rowheight=28,
                    font=("맑은 고딕", 9), borderwidth=0, relief="flat")
        s.configure("Pro.Treeview.Heading",
                    background=LIGHT, foreground=NAVY,
                    font=("맑은 고딕", 9, "bold"),
                    relief="flat", borderwidth=0, padding=[8, 7])
        s.map("Pro.Treeview",
              background=[("selected", "#DBEAFE")],
              foreground=[("selected", NAVY)])
        s.map("Pro.Treeview.Heading",
              background=[("active", BORDER)])
        # 프로그레스바
        s.configure("Gold.Horizontal.TProgressbar",
                    troughcolor=BORDER, background=GOLD, thickness=5)
        # 체크버튼 (사이드바용 다크)
        s.configure("Dark.TCheckbutton",
                    background=NAVY_DK, foreground="#CBD5E1",
                    font=("맑은 고딕", 9))
        s.map("Dark.TCheckbutton",
              background=[("active", NAVY_HL)],
              foreground=[("active", WHITE)])
        # 스크롤바
        s.configure("TScrollbar", troughcolor=LIGHT, background=BORDER, arrowsize=12)

    # ────────────────────────────────────────────────────────────
    # UI 구성
    # ────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── 헤더 (64px) ──────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=NAVY, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # 로고 배지 (캔버스 원형)
        logo_c = tk.Canvas(hdr, width=40, height=40, bg=NAVY, highlightthickness=0)
        logo_c.pack(side="left", padx=(18, 10), pady=12)
        logo_c.create_oval(3, 3, 37, 37, fill=GOLD, outline=GOLD_LT, width=1)
        logo_c.create_text(20, 21, text="📡", font=("맑은 고딕", 14))

        # 타이틀 영역
        title_col = tk.Frame(hdr, bg=NAVY)
        title_col.pack(side="left", fill="y", pady=10)

        top_row = tk.Frame(title_col, bg=NAVY)
        top_row.pack(anchor="w")
        tk.Label(top_row, text="공모레이더", bg=NAVY, fg=WHITE,
                 font=("맑은 고딕", 15, "bold")).pack(side="left")
        # 버전 배지
        vbadge = tk.Frame(top_row, bg=GOLD_LT)
        vbadge.pack(side="left", padx=(8, 0), pady=6)
        tk.Label(vbadge, text=" v2.0 ", bg=GOLD_LT, fg=NAVY,
                 font=("맑은 고딕", 8, "bold")).pack(pady=1, padx=2)
        tk.Label(title_col, text="한서대학교 성과혁신IR센터  ·  공모사업 자동 수집 시스템",
                 bg=NAVY, fg="#90A8C0", font=("맑은 고딕", 9)).pack(anchor="w")

        # 우측: Ollama + 시각
        right_hdr = tk.Frame(hdr, bg=NAVY)
        right_hdr.pack(side="right", padx=20, fill="y")
        self.time_label = tk.Label(right_hdr, bg=NAVY, fg=GOLD,
                                   font=("맑은 고딕", 10, "bold"))
        self.time_label.pack(anchor="e", pady=(12, 2))
        self._update_clock()
        self.ollama_label = tk.Label(right_hdr, text="● 확인 중...",
                                     bg=NAVY, fg=MUTED, font=("맑은 고딕", 8))
        self.ollama_label.pack(anchor="e")

        # 골드 구분선 (2px)
        tk.Frame(self.root, bg=GOLD, height=2).pack(fill="x")

        # ── 메인 영역 ─────────────────────────────────────────────
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True)

        # 사이드바 (240px 다크)
        sidebar = tk.Frame(main, bg=NAVY_DK, width=240)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # 우측 콘텐츠
        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._build_left(sidebar)
        self._build_right_notebook(right)

        # ── 하단 상태바 (30px) ────────────────────────────────────
        sbar = tk.Frame(self.root, bg="#0F1E35", height=30)
        sbar.pack(fill="x", side="bottom")
        sbar.pack_propagate(False)

        self.status_var = StringVar(value="준비")
        self.status_dot = tk.Label(sbar, text="●", bg="#0F1E35",
                                   fg=GREEN, font=("맑은 고딕", 8))
        self.status_dot.pack(side="left", padx=(12, 3), pady=9)
        tk.Label(sbar, textvariable=self.status_var,
                 bg="#0F1E35", fg=WHITE, font=("맑은 고딕", 9)).pack(side="left")

        # 우측: 버전
        tk.Label(sbar, text="v2.0.0", bg="#0F1E35",
                 fg=MUTED, font=("맑은 고딕", 8)).pack(side="right", padx=14)
        tk.Label(sbar, text="|", bg="#0F1E35", fg="#1E3A5F",
                 font=("맑은 고딕", 9)).pack(side="right", padx=2)
        tk.Label(sbar, text="GitHub Auto-Sync ✓", bg="#0F1E35",
                 fg="#3D6B8A", font=("맑은 고딕", 8)).pack(side="right", padx=8)

    def _build_left(self, parent):
        """다크 사이드바: 수집처 선택 + 설정 + 실행"""

        def _sec_lbl(text):
            tk.Label(parent, text=text, bg=NAVY_DK, fg="#5B7A9A",
                     font=("맑은 고딕", 8, "bold")).pack(
                         anchor="w", padx=16, pady=(12, 3))

        # ── 수집처 전체선택/해제 ──────────────────────────────
        _sec_lbl("수집처 선택")
        ctrl = tk.Frame(parent, bg=NAVY_DK)
        ctrl.pack(fill="x", padx=14, pady=(0, 4))
        for txt, fn, bg_ in [
            ("전체선택", lambda: self._toggle_all(True),  "#1E4080"),
            ("전체해제", lambda: self._toggle_all(False), "#2E2E40"),
        ]:
            tk.Button(ctrl, text=txt, command=fn, bg=bg_, fg="#BDD3E8",
                      font=("맑은 고딕", 8), relief="flat",
                      padx=10, pady=3, cursor="hand2",
                      activebackground=NAVY_HL, activeforeground=WHITE
                      ).pack(side="left", padx=(0, 4))

        # 스크롤 체크박스 영역
        sb_c = tk.Canvas(parent, bg=NAVY_DK, highlightthickness=0, height=240)
        sb_s = ttk.Scrollbar(parent, orient="vertical", command=sb_c.yview)
        sb_f = tk.Frame(sb_c, bg=NAVY_DK)
        sb_f.bind("<Configure>",
                  lambda e: sb_c.configure(scrollregion=sb_c.bbox("all")))
        sb_c.create_window((0, 0), window=sb_f, anchor="nw")
        sb_c.configure(yscrollcommand=sb_s.set)
        sb_c.pack(side="left", fill="both", expand=True, padx=(8, 0))
        sb_s.pack(side="right", fill="y")

        # 카테고리별 체크박스
        current_cat = None
        for key, name, cat, default in BUILTIN_SOURCES:
            var = BooleanVar(value=default)
            self.source_vars[key] = var
            if cat != current_cat:
                current_cat = cat
                color = SOURCE_CATEGORY_COLORS.get(cat, "#1E4080")
                cf = tk.Frame(sb_f, bg=color, height=20)
                cf.pack(fill="x", pady=(5, 0))
                cf.pack_propagate(False)
                tk.Label(cf, text=f"  ▸ {cat}", bg=color, fg=WHITE,
                         font=("맑은 고딕", 8, "bold")).pack(side="left", pady=2)
            ttk.Checkbutton(sb_f, text=f"  {name}", variable=var,
                            style="Dark.TCheckbutton").pack(anchor="w", padx=6, pady=1)
        sb_c.bind_all("<MouseWheel>",
                      lambda e: sb_c.yview_scroll(-1*(e.delta//120), "units"))

        # 구분선
        tk.Frame(parent, bg="#1E3A5F", height=1).pack(fill="x", padx=12, pady=6)

        # ── 수집 설정 ─────────────────────────────────────────
        _sec_lbl("수집 설정")
        days_f = tk.Frame(parent, bg=NAVY_DK)
        days_f.pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(days_f, text="수집 기간", bg=NAVY_DK, fg="#8AAAC8",
                 font=("맑은 고딕", 9)).pack(side="left")
        self.days_var = IntVar(value=7)
        ttk.Spinbox(days_f, from_=1, to=30,
                    textvariable=self.days_var, width=5).pack(side="right", padx=(0,4))
        tk.Label(days_f, text="일", bg=NAVY_DK, fg="#8AAAC8",
                 font=("맑은 고딕", 9)).pack(side="right", padx=2)

        self.ai_var = BooleanVar(value=True)
        ai_f = tk.Frame(parent, bg=NAVY_DK)
        ai_f.pack(fill="x", padx=14, pady=2)
        ttk.Checkbutton(ai_f, text="AI 분석 사용 (Ollama)",
                        variable=self.ai_var,
                        style="Dark.TCheckbutton").pack(anchor="w")
        tk.Label(ai_f, text="※ 3~5분 추가 소요", bg=NAVY_DK, fg="#5B7A9A",
                 font=("맑은 고딕", 8)).pack(anchor="w", padx=20)

        # 구분선
        tk.Frame(parent, bg="#1E3A5F", height=1).pack(fill="x", padx=12, pady=6)

        # ── 사용자 정의 수집처 ────────────────────────────────
        _sec_lbl("사용자 정의 수집처")
        lb_f = tk.Frame(parent, bg=NAVY_DK, padx=12)
        lb_f.pack(fill="x")
        self.custom_listbox = tk.Listbox(
            lb_f, height=4, font=("맑은 고딕", 9),
            selectmode="single", activestyle="none",
            bg="#0C1A2E", fg="#CBD5E1",
            selectbackground=GOLD, selectforeground=NAVY_DK,
            highlightthickness=0, borderwidth=0)
        lb_scr = ttk.Scrollbar(lb_f, command=self.custom_listbox.yview)
        self.custom_listbox.configure(yscrollcommand=lb_scr.set)
        self.custom_listbox.pack(side="left", fill="both", expand=True)
        lb_scr.pack(side="right", fill="y")

        lb_btn = tk.Frame(parent, bg=NAVY_DK)
        lb_btn.pack(fill="x", padx=12, pady=4)
        for txt, fn, bg_, fg_ in [
            ("+ 추가", self._add_custom_source,    GOLD,     NAVY_DK),
            ("삭제",   self._remove_custom_source, "#3D1A1A", "#FCA5A5"),
        ]:
            tk.Button(lb_btn, text=txt, command=fn, bg=bg_, fg=fg_,
                      font=("맑은 고딕", 8, "bold"), relief="flat",
                      padx=10, pady=3, cursor="hand2").pack(side="left", padx=(0, 4))

        # ── 실행/중지 버튼 (사이드바 하단 고정) ─────────────
        btn_f = tk.Frame(parent, bg=NAVY_DK)
        btn_f.pack(fill="x", padx=12, pady=8, side="bottom")

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_label = tk.Label(
            btn_f, text="", bg=NAVY_DK, fg="#8AAAC8",
            font=("맑은 고딕", 8), wraplength=200, justify="left")
        self.progress_label.pack(fill="x", pady=(0, 2))

        self.progress_bar = ttk.Progressbar(
            btn_f, variable=self.progress_var,
            maximum=100, mode="indeterminate",
            style="Gold.Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", pady=(0, 6))

        self.stop_btn = tk.Button(
            btn_f, text="■  수집 중지",
            command=self._stop_collection,
            bg="#7F1D1D", fg="#FCA5A5",
            font=("맑은 고딕", 10), relief="flat", pady=7,
            state="disabled", cursor="hand2",
            activebackground="#991B1B", activeforeground=WHITE)
        self.stop_btn.pack(fill="x", pady=(0, 4))

        self.run_btn = tk.Button(
            btn_f, text="▶  수집 시작",
            command=self._start_collection,
            bg="#065F46", fg=WHITE,
            font=("맑은 고딕", 12, "bold"), relief="flat", pady=11,
            cursor="hand2",
            activebackground="#047857", activeforeground=WHITE)
        self.run_btn.pack(fill="x")

    def _build_right_notebook(self, parent):
        """우측: 탭 노트북 (수집 결과 + 수집기 상태)"""
        notebook = ttk.Notebook(parent)
        notebook.pack(fill="both", expand=True)

        tab_result = tk.Frame(notebook, bg=BG)
        tab_status = tk.Frame(notebook, bg=BG)
        notebook.add(tab_result, text="  📋 수집 결과  ")
        notebook.add(tab_status, text="  🔍 수집기 상태  ")

        self._build_right(tab_result)
        self._build_status_panel(tab_status)

    def _build_status_panel(self, parent):
        """수집기 상태 패널 (D안 Layer 4 GUI)."""

        # ── 상단 버튼 ───────────────────────────────────────────
        btn_frame = tk.Frame(parent, bg=BG)
        btn_frame.pack(fill="x", padx=8, pady=6)

        tk.Button(
            btn_frame, text="🔄 헬스체크 실행",
            command=self._run_health_check,
            bg=NAVY, fg=WHITE, font=("맑은 고딕", 10, "bold"),
            relief="flat", padx=14, pady=6, cursor="hand2",
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_frame, text="📊 수집 이력 새로고침",
            command=self._refresh_status_panel,
            bg=GOLD, fg=WHITE, font=("맑은 고딕", 10),
            relief="flat", padx=10, pady=6, cursor="hand2",
        ).pack(side="left")

        self.hc_status_label = tk.Label(
            btn_frame, text="", bg=BG, fg=GRAY, font=("맑은 고딕", 9)
        )
        self.hc_status_label.pack(side="right", padx=8)

        # ── 상태 테이블 ─────────────────────────────────────────
        table_frame = tk.LabelFrame(
            parent, text="수집기별 현황 (최근 7일)",
            bg=BG, font=("맑은 고딕", 9, "bold"), fg=NAVY, labelanchor="nw"
        )
        table_frame.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        st_cols = ("상태", "수집기", "오늘", "7일평균", "연속0건", "헬스체크", "마지막수집")
        self.status_tree = ttk.Treeview(
            table_frame, columns=st_cols, show="headings", selectmode="browse", height=12
        )
        st_widths = {"상태": 50, "수집기": 130, "오늘": 70, "7일평균": 80,
                     "연속0건": 80, "헬스체크": 110, "마지막수집": 100}
        for col in st_cols:
            self.status_tree.heading(col, text=col)
            self.status_tree.column(col, width=st_widths.get(col, 90), anchor="center")
        self.status_tree.column("수집기", anchor="w")

        st_scroll = ttk.Scrollbar(table_frame, orient="vertical",
                                   command=self.status_tree.yview)
        self.status_tree.configure(yscrollcommand=st_scroll.set)
        self.status_tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        st_scroll.pack(side="right", fill="y")

        # 행 색상 태그
        self.status_tree.tag_configure("ok",       background="#C6EFCE")
        self.status_tree.tag_configure("warning",  background="#FFEB9C")
        self.status_tree.tag_configure("critical", background="#FFC7CE")
        self.status_tree.tag_configure("inactive", background="#F2F2F2")

        # ── 헬스체크 상세 로그 ──────────────────────────────────
        detail_frame = tk.LabelFrame(
            parent, text="헬스체크 상세",
            bg=BG, font=("맑은 고딕", 9, "bold"), fg=NAVY, labelanchor="nw", height=90
        )
        detail_frame.pack(fill="x", padx=8, pady=(0, 4))
        detail_frame.pack_propagate(False)

        self.hc_detail_text = scrolledtext.ScrolledText(
            detail_frame, height=4, font=("Consolas", 8),
            bg="#1E1E1E", fg="#D4D4D4", state="disabled", wrap="word"
        )
        self.hc_detail_text.pack(fill="both", expand=True, padx=4, pady=4)

        # 초기 로드
        self.root.after(500, self._refresh_status_panel)

    def _refresh_status_panel(self):
        """DB에서 최신 수집기 통계를 읽어 상태 테이블 갱신."""
        for item in self.status_tree.get_children():
            self.status_tree.delete(item)

        try:
            from app.database import Database
            import yaml, os
            cfg_path = os.path.join(APP_DIR, "config.yaml")
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            db = Database(cfg["database"]["path"])
            summaries = db.get_all_collector_summary()
            weekly = {r["source"]: r for r in db.get_weekly_stats()}
        except Exception as e:
            self.hc_status_label.config(text=f"DB 조회 오류: {e}")
            return

        if not summaries:
            self.status_tree.insert("", END, values=("—", "데이터 없음 (수집 먼저 실행)", "", "", "", "", ""))
            return

        for row in summaries:
            src = row["source"]
            today_cnt = row["count"]
            streak = row["consecutive_zeros"]
            hstatus = row["health_status"] or "UNKNOWN"
            last_date = row["date"]
            w = weekly.get(src, {})
            avg7 = w.get("avg_7d") or 0

            # 상태 아이콘
            if hstatus == "DOWN" or streak >= 7:
                icon, tag = "❌", "critical"
            elif hstatus == "DEGRADED" or streak >= 3:
                icon, tag = "⚠️", "warning"
            elif today_cnt == 0:
                icon, tag = "⚠️", "warning"
            else:
                icon, tag = "✅", "ok"

            self.status_tree.insert("", END, tags=(tag,), values=(
                icon,
                src,
                f"{today_cnt}건",
                f"{avg7}건",
                f"{streak}일" if streak > 0 else "-",
                hstatus,
                last_date,
            ))

        self.hc_status_label.config(
            text=f"갱신: {datetime.now().strftime('%H:%M:%S')}", fg=GRAY
        )

    def _run_health_check(self):
        """헬스체크 비동기 실행."""
        self.hc_status_label.config(text="헬스체크 실행 중...", fg=GOLD)
        self._hc_log("▶ 헬스체크 시작...")

        def _worker():
            try:
                from app.health_checker import HealthChecker, status_emoji
                results = HealthChecker().run_all()
                lines = []
                for r in results:
                    em = status_emoji(r["status"])
                    lines.append(
                        f"  {em} {r['source']:12s} | {r['status']:8s} | {r['latency_ms']}ms | {r['detail']}"
                    )
                self.root.after(0, lambda: self._hc_log("\n".join(lines)))
                self.root.after(0, self._refresh_status_panel)
                self.root.after(0, lambda: self.hc_status_label.config(
                    text=f"완료: {datetime.now().strftime('%H:%M:%S')}", fg=GREEN))
            except Exception as e:
                self.root.after(0, lambda: self._hc_log(f"오류: {e}"))
                self.root.after(0, lambda: self.hc_status_label.config(
                    text=f"오류: {e}", fg=RED))

        threading.Thread(target=_worker, daemon=True).start()

    def _hc_log(self, msg: str):
        """헬스체크 상세 로그 추가."""
        self.hc_detail_text.config(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.hc_detail_text.insert(END, f"[{ts}]\n{msg}\n\n")
        self.hc_detail_text.see(END)
        self.hc_detail_text.config(state="disabled")

    def _build_right(self, parent):
        """우측 콘텐츠: KPI 카드 + 툴바 + 테이블 + 다크 로그 콘솔"""

        # ── KPI 카드 (4개) ────────────────────────────────────
        kpi_row = tk.Frame(parent, bg=BG)
        kpi_row.pack(fill="x", padx=16, pady=(12, 8))

        self.card_vars = {
            "total":    StringVar(value="0"),
            "eligible": StringVar(value="0"),
            "analyzed": StringVar(value="0"),
            "sources":  StringVar(value="0"),
        }
        kpi_meta = [
            ("📋", "전체 수집",  "total",    NAVY,  "#EEF2FF"),
            ("✅", "대학 가능",  "eligible", GREEN, GREEN_LT),
            ("🤖", "AI 분석",   "analyzed", AMBER, AMBER_LT),
            ("🔌", "수집처 수", "sources",  BLUE,  BLUE_LT),
        ]
        for icon, lbl, key, accent, bg_c in kpi_meta:
            outer = tk.Frame(kpi_row, bg=BORDER_DK, padx=1, pady=1)
            outer.pack(side="left", expand=True, fill="x", padx=(0, 8))
            card = tk.Frame(outer, bg=bg_c, padx=14, pady=10)
            card.pack(fill="both", expand=True)
            top = tk.Frame(card, bg=bg_c)
            top.pack(fill="x")
            tk.Label(top, text=icon, bg=bg_c,
                     font=("맑은 고딕", 11)).pack(side="left")
            tk.Label(top, text=lbl, bg=bg_c, fg=MUTED,
                     font=("맑은 고딕", 9)).pack(side="left", padx=4)
            tk.Label(card, textvariable=self.card_vars[key],
                     bg=bg_c, fg=accent,
                     font=("맑은 고딕", 22, "bold")).pack(anchor="w", pady=(4, 0))
            tk.Frame(card, bg=accent, height=3).pack(fill="x", pady=(6, 0))

        # ── 툴바 ─────────────────────────────────────────────
        toolbar = tk.Frame(parent, bg=SURFACE,
                           highlightthickness=1, highlightbackground=BORDER)
        toolbar.pack(fill="x", padx=16, pady=(0, 1))

        # 검색 아이콘 + 입력
        tk.Label(toolbar, text="🔍", bg=SURFACE,
                 font=("맑은 고딕", 10)).pack(side="left", padx=(10, 2), pady=8)
        self.search_var = StringVar()
        self.search_var.trace("w", self._filter_results)
        tk.Entry(toolbar, textvariable=self.search_var,
                 font=("맑은 고딕", 9), relief="flat",
                 bg=SURFACE, fg=TEXT, width=24,
                 highlightthickness=0).pack(side="left", padx=(0, 10), pady=8)

        # 구분자
        tk.Frame(toolbar, bg=BORDER, width=1).pack(side="left", fill="y", pady=6)

        # 수집원 필터
        tk.Label(toolbar, text="수집원", bg=SURFACE, fg=MUTED,
                 font=("맑은 고딕", 9)).pack(side="left", padx=(10, 4))
        self.filter_source = StringVar(value="전체")
        self.source_combo = ttk.Combobox(toolbar, textvariable=self.filter_source,
                                          width=16, state="readonly")
        self.source_combo["values"] = ["전체"]
        self.source_combo.bind("<<ComboboxSelected>>", self._filter_results)
        self.source_combo.pack(side="left", pady=6)

        # 구분자
        tk.Frame(toolbar, bg=BORDER, width=1).pack(side="left", fill="y", pady=6, padx=10)

        # 액션 버튼
        for txt, fn, bg_, fg_ in [
            ("📊  Excel 내보내기", self._export_excel, NAVY, WHITE),
            ("🔗  URL 열기",       self._open_url,     GOLD, WHITE),
        ]:
            tk.Button(toolbar, text=txt, command=fn,
                      bg=bg_, fg=fg_,
                      font=("맑은 고딕", 9), relief="flat",
                      padx=10, pady=5, cursor="hand2",
                      activebackground=NAVY_HL if bg_==NAVY else GOLD_LT,
                      activeforeground=WHITE
                      ).pack(side="right", padx=(0, 8), pady=6)

        # ── 결과 테이블 ───────────────────────────────────────
        tbl_outer = tk.Frame(parent, bg=BORDER_DK, padx=1, pady=1)
        tbl_outer.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        tbl_inner = tk.Frame(tbl_outer, bg=SURFACE)
        tbl_inner.pack(fill="both", expand=True)

        cols = ("번호", "수집원", "기관명", "공고제목", "게시일", "마감일", "AI점수")
        self.tree = ttk.Treeview(tbl_inner, columns=cols,
                                  show="headings", selectmode="browse",
                                  style="Pro.Treeview")
        col_w = {"번호": 44, "수집원": 112, "기관명": 132,
                  "공고제목": 380, "게시일": 86, "마감일": 86, "AI점수": 58}
        for col in cols:
            self.tree.heading(col, text=col,
                               command=lambda c=col: self._sort_tree(c))
            self.tree.column(col, width=col_w.get(col, 100), minwidth=40, anchor="w")
        self.tree.column("번호",   anchor="center")
        self.tree.column("AI점수", anchor="center")

        tsy = ttk.Scrollbar(tbl_inner, orient="vertical",   command=self.tree.yview)
        tsx = ttk.Scrollbar(tbl_inner, orient="horizontal",  command=self.tree.xview)
        self.tree.configure(yscrollcommand=tsy.set, xscrollcommand=tsx.set)
        tsx.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        tsy.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # 행 태그 (현대적 파스텔)
        self.tree.tag_configure("high",  background="#D1FAE5", foreground="#065F46")
        self.tree.tag_configure("mid",   background="#FEF3C7", foreground="#92400E")
        self.tree.tag_configure("low",   background="#FEE2E2", foreground="#991B1B")
        self.tree.tag_configure("noai",  background=SURFACE)
        self.tree.tag_configure("alt",   background=LIGHT)

        # ── 다크 로그 콘솔 ────────────────────────────────────
        log_title = tk.Frame(parent, bg="#161B22")
        log_title.pack(fill="x", padx=16, pady=(4, 0))
        tk.Label(log_title, text="● ● ●", bg="#161B22", fg="#3D444D",
                 font=("맑은 고딕", 8)).pack(side="left", padx=8, pady=4)
        tk.Label(log_title, text="수집 로그", bg="#161B22", fg="#7D8590",
                 font=("맑은 고딕", 8, "bold")).pack(side="left")

        log_f = tk.Frame(parent, bg="#0D1117", height=120)
        log_f.pack(fill="x", padx=16, pady=(0, 8))
        log_f.pack_propagate(False)
        self.log_text = scrolledtext.ScrolledText(
            log_f, font=("Consolas", 8),
            bg="#0D1117", fg="#E6EDF3",
            insertbackground=WHITE, state="disabled", wrap="word",
            borderwidth=0, relief="flat", padx=10, pady=6)
        self.log_text.pack(fill="both", expand=True)

    def _section_frame(self, parent, title: str, pad: int = 12) -> tk.Frame:
        """카드 스타일 섹션 컨테이너"""
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="x", padx=pad, pady=(0, 6))
        # 테두리 시뮬레이션 (1px border)
        card = tk.Frame(outer, bg=BORDER_DK, padx=1, pady=1)
        card.pack(fill="both", expand=True)
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="both", expand=True)
        # 카드 헤더
        hdr = tk.Frame(inner, bg=LIGHT, pady=5)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=GOLD, width=4).pack(side="left", fill="y")
        tk.Label(hdr, text=f"  {title}", bg=LIGHT, fg=NAVY,
                 font=("맑은 고딕", 9, "bold")).pack(side="left", padx=8)
        content = tk.Frame(inner, bg=SURFACE, padx=10, pady=8)
        content.pack(fill="both", expand=True)
        return content

    # ────────────────────────────────────────────────────────────
    # 수집 제어
    # ────────────────────────────────────────────────────────────
    def _start_collection(self):
        if self.is_running:
            return

        selected = [k for k, v in self.source_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("선택 없음", "수집할 소스를 하나 이상 선택하세요.")
            return

        self.is_running = True
        self.notices = []
        self._clear_tree()
        self._update_cards(0, 0, 0, 0)

        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress_bar.start(10)

        use_ai = self.ai_var.get()
        days = self.days_var.get()

        self.worker = CollectionWorker(selected, days, use_ai, self.progress_queue)
        self.worker_thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker_thread.start()
        self._log(f"[시작] 수집 시작: {len(selected)}개 소스, 최근 {days}일, AI={'ON' if use_ai else 'OFF'}")

    def _stop_collection(self):
        if self.worker:
            self.worker.stop()
        self._log("[중지] 사용자 요청으로 중지")
        self.status_var.set("중지됨")

    def _process_queue(self):
        """큐에서 진행 메시지 처리 (main thread)"""
        try:
            while True:
                msg_type, data = self.progress_queue.get_nowait()

                if msg_type == "progress":
                    self.progress_label.config(text=data)
                    self.status_var.set(data[:60])
                elif msg_type == "tick":
                    self._log(f"[완료] {data}")
                elif msg_type == "warn":
                    self._log(f"[경고] {data}")
                elif msg_type == "error":
                    self._log(f"[오류] {data}")
                    messagebox.showerror("수집 오류", data)
                    self._collection_finished([])
                elif msg_type == "done":
                    self._collection_finished(data)

        except queue.Empty:
            pass

        self.root.after(200, self._process_queue)

    def _collection_finished(self, notices: list):
        self.is_running = False
        self.notices = notices
        self.progress_bar.stop()
        self.progress_var.set(100)
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress_label.config(text=f"수집 완료: {len(notices)}건")
        self.status_var.set(f"수집 완료: {len(notices)}건")

        self._display_results(notices)
        self._log(f"[완료] 전체 수집: {len(notices)}건")

        if notices:
            if messagebox.askyesno("수집 완료",
                                   f"총 {len(notices)}건 수집 완료!\n\nExcel로 내보내시겠습니까?"):
                self._export_excel()

    # ────────────────────────────────────────────────────────────
    # 결과 표시
    # ────────────────────────────────────────────────────────────
    def _display_results(self, notices: list):
        self._clear_tree()

        sources = {"전체"}
        for i, n in enumerate(notices, 1):
            src = n.get("source", "")
            sources.add(src.split("-")[0] if "-" in src else src)

            score = n.get("ai_score", "")
            score_str = f"{score}점" if score else "-"

            tag = "noai"
            if score:
                s = int(score)
                if s >= 80:   tag = "high"
                elif s >= 60: tag = "mid"
                else:          tag = "low"
            elif i % 2 == 0:
                tag = "alt"

            self.tree.insert("", END, iid=str(i), tags=(tag,), values=(
                i,
                n.get("source", "")[:20],
                n.get("agency", "")[:20],
                n.get("title", "")[:60],
                n.get("post_date", ""),
                n.get("end_date", ""),
                score_str,
            ))

        # 콤보박스 업데이트
        self.source_combo["values"] = sorted(sources)

        # 카드 업데이트
        eligible = sum(1 for n in notices if n.get("ai_score", 0) >= 70)
        analyzed = sum(1 for n in notices if n.get("ai_score"))
        self._update_cards(len(notices), eligible, analyzed, len(sources) - 1)

    def _filter_results(self, *args):
        """검색/필터 적용"""
        keyword = self.search_var.get().lower()
        src_filter = self.filter_source.get()

        self._clear_tree()
        idx = 1
        for n in self.notices:
            src = n.get("source", "")
            src_short = src.split("-")[0] if "-" in src else src

            if src_filter != "전체" and src_filter != src_short:
                continue
            if keyword and keyword not in n.get("title", "").lower() \
                       and keyword not in n.get("agency", "").lower():
                continue

            score = n.get("ai_score", "")
            score_str = f"{score}점" if score else "-"
            tag = "noai"
            if score:
                s = int(score)
                tag = "high" if s >= 80 else "mid" if s >= 60 else "low"
            elif idx % 2 == 0:
                tag = "alt"

            self.tree.insert("", END, iid=str(idx), tags=(tag,), values=(
                idx, src[:20], n.get("agency", "")[:20],
                n.get("title", "")[:60], n.get("post_date", ""),
                n.get("end_date", ""), score_str,
            ))
            idx += 1

    def _clear_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _sort_tree(self, col: str):
        """컬럼 클릭 정렬"""
        items = [(self.tree.set(child, col), child)
                 for child in self.tree.get_children("")]
        items.sort(reverse=getattr(self, f"_sort_rev_{col}", False))
        setattr(self, f"_sort_rev_{col}", not getattr(self, f"_sort_rev_{col}", False))
        for idx, (_, child) in enumerate(items):
            self.tree.move(child, "", idx)

    def _update_cards(self, total, eligible, analyzed, sources):
        self.card_vars["total"].set(f"{total:,}")
        self.card_vars["eligible"].set(f"{eligible:,}")
        self.card_vars["analyzed"].set(f"{analyzed:,}")
        self.card_vars["sources"].set(f"{sources:,}")

    # ────────────────────────────────────────────────────────────
    # 사용자 정의 수집처 관리
    # ────────────────────────────────────────────────────────────
    def _load_custom_sources(self):
        self.custom_sources = []
        if os.path.exists(CUSTOM_SOURCES_FILE):
            try:
                with open(CUSTOM_SOURCES_FILE, encoding="utf-8") as f:
                    self.custom_sources = json.load(f)
            except Exception:
                pass
        self._refresh_custom_listbox()

    def _save_custom_sources(self):
        with open(CUSTOM_SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.custom_sources, f, ensure_ascii=False, indent=2)

    def _refresh_custom_listbox(self):
        self.custom_listbox.delete(0, END)
        for s in self.custom_sources:
            status = "✓" if s.get("enabled", True) else "✗"
            self.custom_listbox.insert(END, f"{status} {s['name']}")

    def _add_custom_source(self):
        """사용자 정의 수집처 추가 다이얼로그"""
        dialog = tk.Toplevel(self.root)
        dialog.title("수집처 추가")
        dialog.geometry("500x260")
        dialog.resizable(False, False)
        dialog.grab_set()

        tk.Label(dialog, text="수집처 추가", font=("맑은 고딕", 12, "bold"),
                 fg=NAVY).grid(row=0, column=0, columnspan=2, pady=12)

        labels = ["기관/사이트 이름 *", "공고 목록 URL *", "CSS 셀렉터 (선택)"]
        entries = []
        defaults = ["", "", "tbody tr, li"]

        for i, (label, default) in enumerate(zip(labels, defaults)):
            tk.Label(dialog, text=label, font=("맑은 고딕", 9)).grid(
                row=i+1, column=0, padx=12, pady=4, sticky="e")
            e = ttk.Entry(dialog, width=40)
            e.insert(0, default)
            e.grid(row=i+1, column=1, padx=8, pady=4, sticky="w")
            entries.append(e)

        tk.Label(dialog, text="* 공고 목록이 표시되는 페이지 URL을 입력하세요",
                 fg=GRAY, font=("맑은 고딕", 8)).grid(
                     row=4, column=0, columnspan=2, pady=4)

        def save():
            name = entries[0].get().strip()
            url  = entries[1].get().strip()
            sel  = entries[2].get().strip() or "tbody tr, li"

            if not name or not url:
                messagebox.showwarning("입력 오류", "이름과 URL은 필수입니다.", parent=dialog)
                return
            if not url.startswith("http"):
                messagebox.showwarning("URL 오류", "http:// 또는 https://로 시작해야 합니다.", parent=dialog)
                return

            import uuid
            new = {"id": str(uuid.uuid4())[:8], "name": name,
                   "url": url, "selector": sel, "enabled": True,
                   "added_at": datetime.now().strftime("%Y-%m-%d")}
            self.custom_sources.append(new)
            self._save_custom_sources()
            self._refresh_custom_listbox()
            self._log(f"[추가] 수집처 추가: {name}")
            dialog.destroy()

        tk.Button(dialog, text="저장", command=save,
                  bg=NAVY, fg=WHITE, font=("맑은 고딕", 10, "bold"),
                  relief="flat", padx=20, pady=6).grid(row=5, column=1, pady=12, sticky="e", padx=8)
        tk.Button(dialog, text="취소", command=dialog.destroy,
                  bg=GRAY, fg=WHITE, font=("맑은 고딕", 10),
                  relief="flat", padx=12, pady=6).grid(row=5, column=0, pady=12, sticky="e")

    def _remove_custom_source(self):
        sel = self.custom_listbox.curselection()
        if not sel:
            messagebox.showinfo("선택 없음", "삭제할 항목을 선택하세요.")
            return
        idx = sel[0]
        name = self.custom_sources[idx]["name"]
        if messagebox.askyesno("삭제 확인", f"'{name}'을(를) 삭제하시겠습니까?"):
            self.custom_sources.pop(idx)
            self._save_custom_sources()
            self._refresh_custom_listbox()
            self._log(f"[삭제] 수집처 삭제: {name}")

    # ────────────────────────────────────────────────────────────
    # Excel 내보내기
    # ────────────────────────────────────────────────────────────
    def _export_excel(self):
        if not self.notices:
            messagebox.showinfo("데이터 없음", "먼저 수집을 실행하세요.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        default_name = f"공모레이더_{timestamp}.xlsx"
        path = filedialog.asksaveasfilename(
            title="Excel 파일 저장",
            defaultextension=".xlsx",
            filetypes=[("Excel 파일", "*.xlsx"), ("모든 파일", "*.*")],
            initialfile=default_name,
            initialdir=os.path.expanduser("~\\Documents"),
        )
        if not path:
            return

        try:
            from app.excel_exporter import ExcelExporter
            saved = ExcelExporter().export(self.notices, path)
            self._log(f"[저장] Excel 저장: {saved}")
            if messagebox.askyesno("저장 완료", f"Excel 파일이 저장되었습니다.\n\n{saved}\n\n파일을 여시겠습니까?"):
                os.startfile(saved)
        except ImportError:
            messagebox.showerror("오류", "openpyxl이 설치되지 않았습니다.\n\npip install openpyxl 실행 후 재시도하세요.")
        except Exception as e:
            messagebox.showerror("저장 오류", str(e))

    # ────────────────────────────────────────────────────────────
    # 기타
    # ────────────────────────────────────────────────────────────
    def _open_url(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0]) - 1
        if 0 <= idx < len(self.notices):
            url = self.notices[idx].get("url", "")
            if url:
                import webbrowser
                webbrowser.open(url)

    def _on_tree_double_click(self, event):
        self._open_url()

    def _toggle_all(self, state: bool):
        for var in self.source_vars.values():
            var.set(state)

    def _check_ollama_status(self):
        """Ollama 실행 상태 비동기 확인"""
        def check():
            try:
                urllib.request.urlopen("http://localhost:11434", timeout=2)
                self.root.after(0, lambda: self.ollama_label.config(
                    text="● Ollama 실행 중", fg="#00FF88"))
            except Exception:
                self.root.after(0, lambda: self.ollama_label.config(
                    text="○ Ollama 미실행 (AI 분석 불가)", fg=GOLD))

        threading.Thread(target=check, daemon=True).start()
        self.root.after(30000, self._check_ollama_status)  # 30초마다 재확인

    def _log(self, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert(END, f"[{timestamp}] {msg}\n")
        self.log_text.see(END)
        self.log_text.config(state="disabled")

    def _update_clock(self):
        self.time_label.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.root.after(1000, self._update_clock)


# ════════════════════════════════════════════════════════════════
# 진입점
# ════════════════════════════════════════════════════════════════
def main():
    # ── 자동 업데이트: 이전 다운로드 있으면 교체 후 재시작 ──────────────
    try:
        from app.auto_updater import apply_pending_if_exists
        apply_pending_if_exists()   # GongmoRadar_new.exe 있으면 → bat 교체 → sys.exit()
    except Exception:
        pass

    root = tk.Tk()

    # DPI 인식 (Windows 고해상도)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = GongmoRadarApp(root)

    # 창 중앙 배치
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ── 백그라운드 업데이트 체크 (앱 시작 30초 후, 비차단) ─────────
    def _bg_update():
        time.sleep(30)   # 앱 완전 로딩 후 실행
        try:
            from app.auto_updater import background_check
            def _notify(msg):
                try:
                    if hasattr(app, "_log"):
                        app._log(f"[업데이트] {msg}")
                except Exception:
                    pass
            background_check(notify_cb=_notify)
        except Exception:
            pass

    threading.Thread(target=_bg_update, daemon=True).start()

    root.mainloop()


if __name__ == "__main__":
    main()

