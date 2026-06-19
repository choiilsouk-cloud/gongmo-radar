# -*- coding: utf-8 -*-
"""
공모레이더 자동 설치 스크립트
- Ollama 감지 → 없으면 winget 자동 설치
- 한국어/비ASCII 사용자 경로 감지 → C:\\OllamaModels + Junction 자동 생성
- exaone3.5:7.8b 모델 다운로드 (없을 경우)
- Python 패키지 설치
- 전체 동작 검증

사용법: python setup.py
"""

import io
import os
import sys
import shutil
import subprocess
import time
import platform
import urllib.request
import json

# Windows 콘솔 UTF-8 출력 강제 (한국어 깨짐 방지)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ──────────────────────────────────────────────
# 컬러 출력 (Windows ANSI 지원)
# ──────────────────────────────────────────────
os.system("")  # ANSI 활성화 (Windows 10+)

def ok(msg):   print(f"  \033[92m✅ {msg}\033[0m")
def warn(msg): print(f"  \033[93m⚠️  {msg}\033[0m")
def err(msg):  print(f"  \033[91m❌ {msg}\033[0m")
def info(msg): print(f"  \033[94m   {msg}\033[0m")
def step(n, total, msg): print(f"\n\033[1m[{n}/{total}] {msg}\033[0m")

OLLAMA_MODELS_PATH = r"C:\OllamaModels"
MODEL_PRIMARY   = "exaone3.5:7.8b"
MODEL_FALLBACK  = "qwen2.5:7b"


# ──────────────────────────────────────────────
# 1. Python 버전 확인
# ──────────────────────────────────────────────
def check_python():
    step(1, 6, "Python 버전 확인")
    ver = sys.version_info
    if ver < (3, 9):
        err(f"Python {ver.major}.{ver.minor} - 3.9 이상 필요")
        err("https://www.python.org/downloads/ 에서 최신 버전 설치 후 재실행")
        sys.exit(1)
    ok(f"Python {ver.major}.{ver.minor}.{ver.micro}")

# ──────────────────────────────────────────────
# 2. 한국어(비ASCII) 사용자 경로 감지
# ──────────────────────────────────────────────
def has_non_ascii_path():
    """사용자 홈 경로에 비ASCII 문자(한국어 등) 포함 여부"""
    try:
        home = os.path.expanduser("~")
        home.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True

def setup_ollama_model_path():
    """
    한국어 경로 PC에서 Ollama 모델 경로 문제 해결:
      1. C:\\OllamaModels 생성
      2. %USERPROFILE%\\.ollama\\models → C:\\OllamaModels Junction 생성
      3. OLLAMA_MODELS 환경변수 영구 설정 (setx)
    """
    step(2, 6, "Ollama 모델 경로 설정")
    home = os.path.expanduser("~")

    if not has_non_ascii_path():
        ok(f"경로 정상 (ASCII): {home}")
        return None  # 특별 처리 불필요

    warn(f"한국어/비ASCII 사용자 경로 감지: {home}")
    info(f"Ollama 모델을 {OLLAMA_MODELS_PATH} 에 저장합니다.")

    # C:\OllamaModels 생성
    os.makedirs(OLLAMA_MODELS_PATH, exist_ok=True)
    ok(f"{OLLAMA_MODELS_PATH} 폴더 생성/확인")

    # Junction 생성: %USERPROFILE%\.ollama\models → C:\OllamaModels
    junction_src = os.path.join(home, ".ollama", "models")
    os.makedirs(os.path.join(home, ".ollama"), exist_ok=True)

    # ── Junction 생성 시도 ──────────────────────────────
    # mklink /J 시도 → 이미 존재하면 "already exists" 오류 → 기존 junction 사용으로 간주
    r = subprocess.run(
        ["cmd", "/c", f'mklink /J "{junction_src}" "{OLLAMA_MODELS_PATH}"'],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if r.returncode == 0:
        ok(f"Junction 생성: .ollama\\models -> {OLLAMA_MODELS_PATH}")
    elif os.path.isdir(junction_src):
        # 이미 존재하는 junction 또는 폴더 — 접근 가능하면 정상
        ok(f"Junction 이미 설정됨: .ollama\\models -> {OLLAMA_MODELS_PATH}")
    else:
        warn(f"Junction 생성 실패 (OLLAMA_MODELS 환경변수로 대체 동작)")

    # OLLAMA_MODELS 환경변수 영구 설정
    subprocess.run(["setx", "OLLAMA_MODELS", OLLAMA_MODELS_PATH],
                   capture_output=True)
    ok(f"환경변수 OLLAMA_MODELS={OLLAMA_MODELS_PATH} 영구 설정")
    return OLLAMA_MODELS_PATH

# ──────────────────────────────────────────────
# 3. Ollama 설치 확인 및 자동 설치
# ──────────────────────────────────────────────
def install_ollama():
    step(3, 6, "Ollama 확인 및 설치")

    if shutil.which("ollama"):
        result = subprocess.run(["ollama", "--version"],
                                capture_output=True, text=True)
        ok(f"Ollama 이미 설치됨: {result.stdout.strip()}")
        return True

    warn("Ollama가 설치되어 있지 않습니다. winget으로 자동 설치합니다...")

    if not shutil.which("winget"):
        err("winget을 찾을 수 없습니다.")
        err("수동 설치: https://ollama.com/download")
        return False

    print()
    info("설치 중... (약 3-5분 소요)")
    result = subprocess.run([
        "winget", "install", "Ollama.Ollama",
        "--accept-package-agreements", "--accept-source-agreements"
    ])

    if result.returncode != 0:
        err("winget 설치 실패. 수동 설치: https://ollama.com/download")
        return False

    ok("Ollama 설치 완료")
    # PATH 갱신 (현재 프로세스에서 ollama 인식)
    local_programs = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                  "Programs", "Ollama")
    if os.path.isdir(local_programs):
        os.environ["PATH"] = local_programs + ";" + os.environ.get("PATH", "")
    return True

# ──────────────────────────────────────────────
# 4. Ollama 서버 시작 (OLLAMA_MODELS 환경 상속)
# ──────────────────────────────────────────────
def start_ollama_serve(ollama_models_path=None):
    """Ollama serve를 올바른 환경변수와 함께 백그라운드 실행"""
    # 이미 실행 중인지 확인
    try:
        urllib.request.urlopen("http://localhost:11434", timeout=2)
        ok("Ollama 서버 이미 실행 중")
        return True
    except Exception:
        pass

    info("Ollama 서버 시작 중...")
    env = os.environ.copy()
    if ollama_models_path:
        env["OLLAMA_MODELS"] = ollama_models_path
    elif has_non_ascii_path():
        env["OLLAMA_MODELS"] = OLLAMA_MODELS_PATH

    # DETACHED_PROCESS | CREATE_NO_WINDOW
    creation_flags = 0x00000008 | 0x08000000
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            env=env,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        err("ollama 명령을 찾을 수 없습니다. 설치를 확인하세요.")
        return False

    # 서버 준비 대기 (최대 15초)
    for i in range(15):
        time.sleep(1)
        try:
            urllib.request.urlopen("http://localhost:11434", timeout=1)
            ok("Ollama 서버 시작 완료 (localhost:11434)")
            return True
        except Exception:
            print(f"  대기 중... ({i+1}/15)", end="\r")

    warn("서버 응답 없음. 수동으로 'ollama serve' 실행 후 재시도하세요.")
    return False

# ──────────────────────────────────────────────
# 5. 모델 다운로드
# ──────────────────────────────────────────────
def pull_model():
    step(4, 6, f"AI 모델 다운로드 ({MODEL_PRIMARY})")

    # 이미 있는지 확인
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if MODEL_PRIMARY.split(":")[0] in result.stdout:
        ok(f"{MODEL_PRIMARY} 이미 설치됨")
        return MODEL_PRIMARY

    info(f"다운로드 시작... (약 4.8GB, 인터넷 속도에 따라 10~30분)")
    info("진행 상황이 아래에 표시됩니다.")
    print()

    env = os.environ.copy()
    if has_non_ascii_path():
        env["OLLAMA_MODELS"] = OLLAMA_MODELS_PATH

    result = subprocess.run(["ollama", "pull", MODEL_PRIMARY], env=env)
    if result.returncode == 0:
        ok(f"{MODEL_PRIMARY} 다운로드 완료")
        return MODEL_PRIMARY

    warn(f"{MODEL_PRIMARY} 실패. 대체 모델 {MODEL_FALLBACK} 시도...")
    result = subprocess.run(["ollama", "pull", MODEL_FALLBACK], env=env)
    if result.returncode == 0:
        ok(f"{MODEL_FALLBACK} 다운로드 완료")
        _update_config_model(MODEL_FALLBACK)
        return MODEL_FALLBACK

    err("모델 다운로드 실패. 인터넷 연결을 확인하고 재시도하세요.")
    return None

def _update_config_model(new_model: str):
    """config.yaml 의 model 항목을 새 모델로 교체"""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(config_path):
        return
    with open(config_path, encoding="utf-8") as f:
        content = f.read()
    content = content.replace(f"model: {MODEL_PRIMARY}", f"model: {new_model}")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)
    info(f"config.yaml model → {new_model} 으로 자동 변경")

# ──────────────────────────────────────────────
# 6. Python 패키지 설치
# ──────────────────────────────────────────────
def install_packages():
    step(5, 6, "Python 패키지 설치")
    req = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if not os.path.exists(req):
        warn("requirements.txt 없음. 건너뜀.")
        return

    # --prefer-binary: 소스 빌드 대신 미리 컴파일된 wheel 우선 사용
    # (Python 3.14 등 최신 버전에서 numpy/pandas 빌드 오류 방지)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req,
         "--prefer-binary", "-q"]
    )
    if result.returncode == 0:
        ok("패키지 설치 완료")
    else:
        warn("일부 패키지 설치 실패.")
        info("수동 실행: pip install -r requirements.txt --prefer-binary")

    # 데이터/로그 폴더 생성
    base = os.path.dirname(__file__)
    for folder in ["data", "logs"]:
        os.makedirs(os.path.join(base, folder), exist_ok=True)
    ok("data/, logs/ 폴더 생성")

# ──────────────────────────────────────────────
# 7. 최종 검증
# ──────────────────────────────────────────────
def verify(model_name):
    step(6, 6, "최종 동작 검증")

    # API 응답 확인
    try:
        payload = json.dumps({
            "model": model_name or MODEL_PRIMARY,
            "prompt": "안녕? 한 단어로만 대답해.",
            "stream": False
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            answer = data.get("response", "").strip()
            ok(f"AI 응답 확인: {answer[:50]}")
            return True
    except Exception as e:
        warn(f"AI 응답 테스트 실패 (서버가 아직 준비 중일 수 있음): {e}")
        return False

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
def main():
    print("\n" + "="*60)
    print("  공모레이더 자동 설치 - 한서대학교 성과혁신IR센터")
    print("="*60)

    if platform.system() != "Windows":
        err("이 스크립트는 Windows 전용입니다.")
        sys.exit(1)

    # 1. Python 버전
    check_python()

    # 2. 모델 경로 설정 (한국어 경로 감지)
    ollama_models = setup_ollama_model_path()

    # 3. Ollama 설치
    if not install_ollama():
        err("Ollama 설치 실패. 수동 설치 후 재실행하세요.")
        sys.exit(1)

    # 4. Ollama 서버 시작
    start_ollama_serve(ollama_models)

    # 5. 모델 다운로드
    model_name = pull_model()

    # 6. Python 패키지
    install_packages()

    # 7. 검증
    verify(model_name)

    # ── 완료 안내 ──────────────────────────────
    print("\n" + "="*60)
    print("  \033[92m설치 완료!\033[0m")
    print("="*60)
    print()
    print("  다음 단계:")
    print("  1. config.yaml 열기: notepad config.yaml")
    print("     - telegram.bot_token 입력")
    print("     - 각 부서 telegram_chat_id 입력")
    print()
    print("  2. 즉시 테스트 실행:")
    print("     python -m app.scheduler --now")
    print()
    print("  3. 자동 실행 등록 (마지막 단계):")
    print("     setup_scheduler.bat")
    print()
    if has_non_ascii_path():
        print("  \033[93m⚠️  한국어 경로 PC 주의사항:\033[0m")
        print(f"     Ollama는 반드시 OLLAMA_MODELS={OLLAMA_MODELS_PATH}")
        print("     환경변수와 함께 실행해야 합니다.")
        print("     (setup.py 또는 app.scheduler가 자동 처리)")
    print()

if __name__ == "__main__":
    main()
