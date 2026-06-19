# 📡 공모레이더 - 한서대학교 국가공모사업 자동탐지 시스템

> 정부·공공기관 공모사업을 매일 자동 수집하여 담당 부서에 알림을 발송합니다.
> **완전 무료** - 유료 API 없음 (Ollama 로컬 LLM 사용)

---

## 🏗️ 시스템 구조

```
수집 (06:00) → AI 분석 → 부서 매칭 → 알림 발송 (08:30)
   ↓              ↓           ↓              ↓
IRIS, e나라도움   EXAONE 3.5   키워드+임베딩   이메일+카카오톡
기업마당, 서산시  (Ollama)     하이브리드
```

---

## ⚡ 빠른 시작

### 1단계: Ollama + AI 모델 설치

```bash
# Ollama 설치 (Windows)
# https://ollama.com/download 에서 다운로드 후 설치

# 한국어 AI 모델 설치 (최초 1회, 약 5GB)
ollama pull exaone3.5:7.8b

# 서버 RAM 8GB 이하이면 경량 모델 사용
# ollama pull qwen2.5:7b
```

### 2단계: Python 환경 설정

```bash
git clone https://github.com/[your-org]/gongmo-radar.git
cd gongmo-radar

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
```

### 3단계: config.yaml 설정

```yaml
# config.yaml 열고 수정

email:
  enabled: true
  sender_email: "your@gmail.com"
  sender_password: "앱비밀번호16자리"   # Gmail 앱 비밀번호

kakao:
  enabled: true
  kakaowork:
    enabled: true
    webhook_url: "https://hook.kakaowork.com/..."  # 카카오워크 Webhook URL

departments:
  - name: 기획예산처
    contacts:
      - name: 홍길동
        email: hong@hanseo.ac.kr
        # 알림톡 사용 시: phone: "010-XXXX-XXXX"
```

### 4단계: 실행

```bash
# Ollama 실행 (별도 터미널)
ollama serve

# 즉시 1회 테스트 실행
python -m app.scheduler --now

# 매일 자동 실행 (스케줄러)
python -m app.scheduler

# 대시보드 열기
streamlit run dashboard/streamlit_app.py
```

---

## 📋 수집 대상

| 소스 | 내용 |
|------|------|
| IRIS | 전 부처 R&D 공고 (교육부, 과기부, 산업부 등) |
| e나라도움 | 정부 보조금 공모 |
| 기업마당 | 중소기업·창업 지원사업 |
| K-Startup | 창업 지원사업 |
| 충남도청 | 충청남도 공모사업 |
| 서산시청 | 서산시 공모사업 |
| 충남교육청 | 교육청 공모사업 |

---

## 🔔 알림 설정 가이드

### 이메일 (Gmail 기준)

1. Gmail 로그인 → 구글 계정 → 보안
2. 2단계 인증 활성화
3. "앱 비밀번호" 생성 (16자리)
4. config.yaml의 `sender_password`에 입력

### 카카오워크 Webhook (무료)

1. 카카오워크 관리자 페이지 접속
2. 서비스 → Incoming Webhook 생성
3. 발급된 URL을 config.yaml `webhook_url`에 입력

### 카카오 알림톡 (건당 약 8원)

1. [카카오 비즈니스](https://business.kakao.com) 가입
2. 알림톡 채널 등록 및 심사
3. API 키 발급 → config.yaml 입력

---

## 💻 서버 권장 사양

| 항목 | 권장 | 최소 |
|------|------|------|
| RAM | 16GB | 8GB (qwen2.5:7b 모델 사용) |
| CPU | 8코어 | 4코어 |
| 저장공간 | 20GB | 10GB |
| OS | Windows Server / Ubuntu 22.04 | - |

---

## 📁 파일 구조

```
gongmo-radar/
├── config.yaml              # ← 여기만 수정하면 됨
├── requirements.txt
├── app/
│   ├── scheduler.py         # 메인 실행 파일
│   ├── database.py          # SQLite DB
│   ├── collectors/
│   │   └── iris_collector.py # 수집기 (IRIS, e나라도움, 기업마당, 지자체)
│   ├── analyzers/
│   │   ├── ai_analyzer.py   # Ollama EXAONE 3.5 분석
│   │   └── matcher.py       # 부서 매칭
│   └── notifier/
│       ├── email_sender.py  # 이메일 알림
│       └── kakao.py         # 카카오톡/카카오워크 알림
├── dashboard/
│   └── streamlit_app.py     # 관리자 대시보드
└── data/
    └── gongmo.db            # 자동 생성
```

---

## ❓ 자주 묻는 질문

**Q. AI가 틀린 분석을 할 때는?**
A. 대시보드 피드백 버튼으로 "제외" 처리하면 됩니다. 향후 매칭 정확도 개선에 반영됩니다.

**Q. 특정 부서를 추가하고 싶으면?**
A. config.yaml의 `departments` 섹션에 부서명, 키워드, 담당자 이메일을 추가하면 됩니다.

**Q. AI 모델을 바꾸고 싶으면?**
A. config.yaml의 `ai.model`을 변경 후 `ollama pull [모델명]` 실행.
추천 대안: `qwen2.5:7b` (경량), `llama3.1:8b` (영어 강점)
