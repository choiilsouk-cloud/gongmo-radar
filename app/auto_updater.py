# -*- coding: utf-8 -*-
"""
GitHub Releases 기반 자동 업데이트 모듈
========================================
동작 흐름:
  1. [시작 시] apply_pending_if_exists() → GongmoRadar_new.exe 있으면 bat으로 교체 후 재시작
  2. [백그라운드] background_check()     → 원격 버전 확인 → 신버전이면 다운로드만 (다음 실행에 적용)

개발자 배포 절차:
  1. version.txt 버전 올리기 (예: 1.0.0 → 1.0.1)
  2. build_exe.bat 실행 → GongmoRadar.exe 빌드
  3. GitHub에 release 생성 (tag: v1.0.1), GongmoRadar.exe 업로드
  4. git push (version.txt 포함)
  → 직원 PC 다음 실행 시 자동 업데이트
"""

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 설정 ────────────────────────────────────────────────────
GITHUB_OWNER  = "choiilsouk-cloud"
GITHUB_REPO   = "gongmo-radar"
EXE_NAME      = "GongmoRadar.exe"
VERSION_URL   = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/version.txt"
)
RELEASE_URL   = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
    f"/releases/latest/download/{EXE_NAME}"
)

# exe 실행 위치 기준 (PyInstaller frozen 여부 무관)
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent

NEW_EXE  = BASE_DIR / f"{EXE_NAME}.new"
CURR_EXE = BASE_DIR / EXE_NAME
VER_FILE = BASE_DIR / "version.txt"
BAT_FILE = BASE_DIR / "_gongmo_update.bat"


# ── 버전 유틸 ────────────────────────────────────────────────
def _local_version() -> str:
    return VER_FILE.read_text(encoding="utf-8").strip() if VER_FILE.exists() else "0.0.0"


def _remote_version(timeout: int = 6) -> str | None:
    try:
        with urllib.request.urlopen(VERSION_URL, timeout=timeout) as r:
            return r.read().decode("utf-8").strip()
    except Exception as e:
        logger.debug("[updater] 원격 버전 확인 실패: %s", e)
        return None


def _is_newer(remote: str, local: str) -> bool:
    """숫자 튜플 비교 — 1.0.1 > 1.0.0"""
    try:
        return tuple(int(x) for x in remote.split(".")) > \
               tuple(int(x) for x in local.split("."))
    except Exception:
        return remote != local


# ── 다운로드 ─────────────────────────────────────────────────
def _download_new_exe(progress_cb=None) -> bool:
    """
    GitHub Release에서 GongmoRadar.exe 다운로드 → GongmoRadar.exe.new 저장.
    progress_cb(int): 0~100 진행률 콜백 (선택)
    """
    tmp = NEW_EXE.with_suffix(".tmp")
    try:
        def _hook(count, block_size, total):
            if progress_cb and total > 0:
                pct = min(100, int(count * block_size * 100 / total))
                progress_cb(pct)

        logger.info("[updater] 다운로드 시작: %s", RELEASE_URL)
        urllib.request.urlretrieve(RELEASE_URL, tmp, reporthook=_hook)
        shutil.move(str(tmp), str(NEW_EXE))
        logger.info("[updater] 다운로드 완료 → %s", NEW_EXE.name)
        return True
    except Exception as e:
        logger.warning("[updater] 다운로드 실패: %s", e)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False


# ── bat 기반 교체 ────────────────────────────────────────────
def _run_update_bat(new_version: str):
    """
    현재 프로세스 종료 후 bat이 exe를 교체하고 재시작.
    Windows는 실행 중인 exe를 직접 덮어쓸 수 없어 bat 우회 사용.
    """
    bat_content = (
        "@echo off\n"
        "timeout /t 3 /nobreak >nul\n"
        f"move /y \"{NEW_EXE}\" \"{CURR_EXE}\"\n"
        f"echo {new_version}> \"{VER_FILE}\"\n"
        f"start \"\" \"{CURR_EXE}\"\n"
        "del \"%~f0\"\n"
    )
    BAT_FILE.write_text(bat_content, encoding="cp949")

    subprocess.Popen(
        ["cmd", "/c", str(BAT_FILE)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
    logger.info("[updater] 업데이트 배치 실행 → 3초 후 재시작")
    time.sleep(0.5)
    sys.exit(0)


# ── 공개 API ─────────────────────────────────────────────────
def apply_pending_if_exists():
    """
    [앱 시작 시 호출] GongmoRadar_new.exe 가 있으면 즉시 교체 후 재시작.
    없으면 아무것도 하지 않음.
    """
    if not NEW_EXE.exists():
        return

    # 다운로드 중 남은 .tmp 파일은 무시
    if NEW_EXE.stat().st_size < 1024 * 100:   # 100 KB 미만은 불완전
        NEW_EXE.unlink(missing_ok=True)
        return

    # 새 버전 번호를 version.txt.new 에서 읽거나 원격에서 가져옴
    ver_new_file = BASE_DIR / "version.txt.new"
    if ver_new_file.exists():
        new_ver = ver_new_file.read_text(encoding="utf-8").strip()
        ver_new_file.unlink(missing_ok=True)
    else:
        new_ver = _remote_version() or "latest"

    logger.info("[updater] 대기 중인 업데이트 적용: %s", new_ver)
    _run_update_bat(new_ver)  # → sys.exit(0)


def background_check(notify_cb=None):
    """
    [백그라운드 스레드에서 호출]
    원격 버전 확인 → 신버전이면 다운로드 → 다음 실행 시 apply_pending_if_exists() 처리.
    notify_cb(str): 상태 메시지 콜백 (GUI 로그 표시용, 선택)
    """
    # 이미 .new 파일 있으면 skip (이전 다운로드 완료)
    if NEW_EXE.exists():
        if notify_cb:
            notify_cb("업데이트 대기 중 — 재시작 시 적용됩니다")
        return

    remote = _remote_version()
    if not remote:
        return

    local = _local_version()
    if not _is_newer(remote, local):
        logger.info("[updater] 최신 버전 사용 중 (%s)", local)
        return

    logger.info("[updater] 신버전 발견: %s → %s, 백그라운드 다운로드 시작", local, remote)
    if notify_cb:
        notify_cb(f"새 버전({remote}) 다운로드 중... (재시작 시 적용)")

    ok = _download_new_exe()
    if ok:
        # 버전 번호를 .new 파일로 저장해 두어 교체 시 참조
        (BASE_DIR / "version.txt.new").write_text(remote, encoding="utf-8")
        logger.info("[updater] 다운로드 완료 — 다음 실행 시 자동 업데이트")
        if notify_cb:
            notify_cb(f"업데이트 준비 완료 ({remote}) — 재시작 시 적용됩니다")
    else:
        if notify_cb:
            notify_cb("업데이트 다운로드 실패 (네트워크 확인)")
