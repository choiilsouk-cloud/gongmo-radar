@echo off
chcp 65001 > nul
title 공모레이더 설치 마법사
color 0A

echo.
echo ============================================================
echo   공모레이더 (GongmoRadar) 자동 설치
echo   한서대학교 성과혁신IR센터
echo ============================================================
echo.

:: Python 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [오류] Python이 설치되어 있지 않습니다.
    echo.
    echo  Python 설치 방법:
    echo  1. https://www.python.org/downloads/ 접속
    echo  2. "Download Python 3.x.x" 클릭
    echo  3. 설치 시 "Add Python to PATH" 반드시 체크!
    echo  4. 설치 완료 후 이 파일을 다시 실행
    echo.
    pause
    exit /b 1
)

echo  Python 확인 완료. 설치 스크립트를 시작합니다...
echo.

:: setup.py 실행 (모든 설치 로직은 Python 스크립트에서 처리)
python "%~dp0setup.py"

if errorlevel 1 (
    echo.
    echo  설치 중 오류가 발생했습니다.
    echo  위 오류 메시지를 확인하고 문제를 해결한 후 재실행하세요.
    echo.
    pause
    exit /b 1
)

pause
