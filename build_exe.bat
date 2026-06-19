@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ════════════════════════════════════════════════════════════════
echo   공모레이더 EXE 빌드 스크립트
echo   한서대학교 성과혁신IR센터
echo ════════════════════════════════════════════════════════════════
echo.

:: ── 현재 디렉토리를 스크립트 위치로 설정 ──────────────────────────
cd /d "%~dp0"

:: ── Python 확인 ────────────────────────────────────────────────
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되지 않았습니다.
    echo        https://www.python.org/downloads/ 에서 Python 3.10+ 설치 후 재시도하세요.
    pause
    exit /b 1
)
echo [OK] Python 확인 완료

:: ── pip 패키지 설치 ────────────────────────────────────────────
echo.
echo [1/4] 필수 패키지 설치 중...
pip install --quiet --prefer-binary ^
    pyinstaller ^
    requests ^
    beautifulsoup4 ^
    lxml ^
    pyyaml ^
    openpyxl ^
    schedule
if errorlevel 1 (
    echo [경고] 일부 패키지 설치에 실패했습니다. 계속 진행합니다.
)
echo [OK] 패키지 설치 완료

:: ── dist / build 폴더 초기화 ───────────────────────────────────
echo.
echo [2/4] 이전 빌드 결과 정리 중...
if exist dist\GongmoRadar.exe del /f /q dist\GongmoRadar.exe > nul 2>&1
if exist dist\공모레이더.exe  del /f /q "dist\공모레이더.exe"  > nul 2>&1
if exist build rmdir /s /q build > nul 2>&1
echo [OK] 정리 완료

:: ── PyInstaller 빌드 ────────────────────────────────────────────
:: 주의: --name 에 한글을 쓰면 일부 Windows 환경에서 빌드 실패하므로
::       영문 이름 GongmoRadar 로 빌드 후 배포 시 한글 이름으로 복사합니다.
echo.
echo [3/4] EXE 빌드 중 (1-5분 소요)...
echo       창이 응답 없음으로 보여도 정상입니다. 잠시 기다려 주세요.

pyinstaller ^
    --onefile ^
    --windowed ^
    --name "GongmoRadar" ^
    --add-data "config.yaml;." ^
    --add-data "app;app" ^
    --hidden-import "app.collectors.iris_collector" ^
    --hidden-import "app.collectors.nrf_collector" ^
    --hidden-import "app.collectors.g2b_collector" ^
    --hidden-import "app.collectors.ministry_collector" ^
    --hidden-import "app.collectors.custom_collector" ^
    --hidden-import "app.collectors.ntis_collector" ^
    --hidden-import "app.collectors.kstartup_collector" ^
    --hidden-import "app.excel_exporter" ^
    --hidden-import "app.scheduler" ^
    --hidden-import "bs4" ^
    --hidden-import "lxml" ^
    --hidden-import "lxml.etree" ^
    --hidden-import "openpyxl" ^
    --hidden-import "requests" ^
    --hidden-import "yaml" ^
    --hidden-import "schedule" ^
    --hidden-import "tkinter" ^
    --hidden-import "tkinter.ttk" ^
    --hidden-import "tkinter.scrolledtext" ^
    --hidden-import "tkinter.filedialog" ^
    --hidden-import "tkinter.messagebox" ^
    --collect-submodules bs4 ^
    --collect-submodules lxml ^
    --collect-submodules openpyxl ^
    --noconfirm ^
    --clean ^
    gui_app.py

if errorlevel 1 (
    echo.
    echo [오류] 빌드 실패!
    echo        위의 오류 메시지를 확인하세요.
    pause
    exit /b 1
)

:: ── 배포 패키지 생성 ───────────────────────────────────────────
echo.
echo [4/4] 배포 패키지 생성 중...

set "DIST_DIR=배포패키지"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"

:: EXE 한글 이름으로 복사 (원본 영문 exe는 dist\ 에 유지)
copy "dist\GongmoRadar.exe" "%DIST_DIR%\공모레이더.exe" > nul

:: 설정 파일 복사
if exist config.yaml copy config.yaml "%DIST_DIR%\" > nul

:: 빈 custom_sources.json 생성
if not exist "%DIST_DIR%\custom_sources.json" (
    echo [] > "%DIST_DIR%\custom_sources.json"
)

:: 사용 설명서 생성
(
echo 공모레이더 v2.0 사용 설명서
echo ============================
echo 한서대학교 성과혁신IR센터
echo.
echo [필수 준비사항]
echo 1. Ollama 설치 (AI 분석 사용 시)
echo    https://ollama.com/download/windows
echo    설치 후: ollama pull exaone3.5:7.8b
echo.
echo [실행 방법]
echo 공모레이더.exe 를 더블클릭하여 실행
echo.
echo [주요 기능]
echo - 수집처 선택: 좌측 체크박스에서 원하는 수집처 선택
echo - 수집 기간: 최근 N일 설정 (기본 7일)
echo - 수집 시작: '수집 시작' 버튼 클릭
echo - Excel 저장: '엑셀 내보내기' 버튼 클릭
echo.
echo [사용자 정의 수집처 추가]
echo 좌측 하단 '+ 추가' 버튼 클릭
echo → 기관명, URL 입력 후 저장
echo.
echo [수집 기관 목록]
echo - IRIS (한국연구재단 범부처통합연구지원시스템)
echo - 한국연구재단 (NRF)
echo - NTIS (국가과학기술정보서비스)
echo - e나라도움 (정부보조금통합관리시스템)
echo - 기업마당 (중소기업 지원사업)
echo - K-Startup (창업지원)
echo - 나라장터 (G2B 공모/용역)
echo - 중앙행정기관 21개 부처/처/청/위원회
echo   (교육부, 과기부, 중기부, 복지부, 문체부,
echo    고용부, 농림부, 환경부, 산업부, 국토부,
echo    해수부, 식약처, 특허청, 농진청, 공정위 등)
echo - 지자체 (충남도청, 서산시, 교육청)
echo - 사용자 정의 수집처 (직접 추가)
echo.
echo [문의]
echo 한서대학교 기획예산처 성과혁신IR센터
) > "%DIST_DIR%\사용설명서.txt"

echo.
echo ════════════════════════════════════════════════════════════════
echo   빌드 성공!
echo.
echo   배포 파일 위치: %CD%\%DIST_DIR%\
echo.
echo   포함 파일:
dir /b "%DIST_DIR%"
echo ════════════════════════════════════════════════════════════════
echo.
echo   공모레이더.exe 파일만 있으면 어디서든 실행 가능합니다.
echo   (Python/라이브러리 설치 불필요)
echo.

pause
