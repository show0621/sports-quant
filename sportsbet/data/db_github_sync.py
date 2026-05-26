"""將 SQLite 資料庫同步至 GitHub 倉庫（供 Streamlit Cloud 持久化）。"""
from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

from sportsbet import config

logger = logging.getLogger(__name__)


def _resolve_github_token() -> str:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        import streamlit as st

        return str(st.secrets.get("GITHUB_TOKEN", "")).strip()
    except Exception:
        return ""


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def push_database_to_github(
    *,
    db_path: Path | None = None,
    message: str | None = None,
    force: bool = False,
) -> bool:
    """
    將 data/sportsbet.db commit 並 push 至 origin。
    需設定環境變數或 Streamlit Secrets：GITHUB_TOKEN（repo 寫入權限）。
 
    回傳 True 表示已成功推送或無變更；False 表示失敗或未設定 token。
    """
    if not config.GITHUB_DB_SYNC_ENABLED and not force:
        return False

    token = _resolve_github_token()
    if not token:
        logger.info("未設定 GITHUB_TOKEN，略過資料庫同步")
        return False

    root = config.PROJECT_ROOT
    db_path = db_path or (config.DATA_DIR / "sportsbet.db")
    if not db_path.exists():
        logger.warning("資料庫不存在：%s", db_path)
        return False

    rel = db_path.relative_to(root).as_posix()
    msg = message or f"chore(data): sync sports database {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    status = _git("status", "--porcelain", rel, cwd=root)
    if status.returncode != 0:
        logger.error("git status 失敗: %s", status.stderr)
        return False
    if not status.stdout.strip():
        logger.info("資料庫無變更，略過 push")
        return True

    add = _git("add", rel, cwd=root)
    if add.returncode != 0:
        logger.error("git add 失敗: %s", add.stderr)
        return False

    commit = _git("commit", "-m", msg, cwd=root)
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        logger.error("git commit 失敗: %s", commit.stderr)
        return False

    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    branch_name = branch.stdout.strip() or "main"

    remote = config.GITHUB_REPO_REMOTE
    if remote.startswith("https://github.com/") and "@" not in remote:
        # 注入 token 供非互動 push
        remote_url = remote.replace("https://", f"https://x-access-token:{token}@")

        set_url = _git("remote", "set-url", "origin", remote_url, cwd=root)
        if set_url.returncode != 0:
            logger.error("git remote set-url 失敗: %s", set_url.stderr)
            return False
        try:
            push = _git("push", "origin", branch_name, cwd=root)
        finally:
            _git("remote", "set-url", "origin", remote, cwd=root)
    else:
        push = _git("push", "origin", branch_name, cwd=root)

    if push.returncode != 0:
        logger.error("git push 失敗: %s", push.stderr)
        return False

    logger.info("資料庫已推送至 GitHub: %s", rel)
    return True
