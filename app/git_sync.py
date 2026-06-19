"""
GitHub 자동 동기화 모듈
수집 완료 후 코드/설정 변경사항을 자동 commit + push
"""

import logging
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 프로젝트 루트 (이 파일의 상위 디렉토리)
REPO_DIR = str(Path(__file__).parent.parent)


def _run(cmd: list, timeout: int = 60) -> tuple[int, str, str]:
    """subprocess 실행 → (returncode, stdout, stderr)"""
    try:
        r = subprocess.run(
            cmd, cwd=REPO_DIR,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace"
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", "git not found"
    except Exception as e:
        return -1, "", str(e)


def has_changes() -> bool:
    """커밋할 변경사항이 있는지 확인 (추적 파일 기준)."""
    code, out, _ = _run(["git", "status", "--porcelain"])
    return code == 0 and bool(out.strip())


def git_push(message: str = None, add_all: bool = False) -> bool:
    """
    변경사항 commit 후 push.
    실패해도 수집 프로세스에 영향 없음 (warning 로그만 기록).

    Args:
        message: 커밋 메시지 (None이면 자동 생성)
        add_all: True면 `git add .` (신규 파일 포함), False면 `git add -u` (추적 파일만)
    Returns:
        bool: push 성공 여부
    """
    if message is None:
        message = f"[자동] 수집 완료 {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    # git add
    add_cmd = ["git", "add", "."] if add_all else ["git", "add", "-u"]
    code, _, err = _run(add_cmd)
    if code != 0:
        logger.warning(f"git_sync: add 실패 — {err}")
        return False

    # 변경사항 없으면 skip
    if not has_changes():
        logger.info("git_sync: 변경사항 없음, skip")
        return True

    # commit
    code, out, err = _run(["git", "commit", "-m", message])
    if code != 0 and "nothing to commit" not in err:
        logger.warning(f"git_sync: commit 실패 — {err}")
        return False

    # push
    code, out, err = _run(["git", "push"], timeout=90)
    if code == 0:
        logger.info(f"git_sync: push 완료 — {out.splitlines()[-1] if out else 'ok'}")
        return True
    else:
        logger.warning(f"git_sync: push 실패 — {err}")
        return False


def git_status_summary() -> dict:
    """현재 git 상태 요약 (GUI 상태 패널용)."""
    code, branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    _, log, _ = _run(["git", "log", "--oneline", "-1"])
    _, remote, _ = _run(["git", "remote", "get-url", "origin"])
    _, status, _ = _run(["git", "status", "--short"])
    return {
        "branch": branch if code == 0 else "N/A",
        "last_commit": log or "없음",
        "remote": remote or "미설정",
        "changed_files": len([l for l in status.splitlines() if l.strip()]),
    }
