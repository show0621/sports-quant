"""將 SQLite 資料庫同步至 GitHub 倉庫（供 Streamlit Cloud 持久化）。"""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sportsbet import config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DbPushResult:
    ok: bool
    status: str  # pushed | unchanged | skipped | failed
    detail: str


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


def _checkpoint_sqlite(db_path: Path) -> None:
    """合併 WAL，確保 push 的 .db 含最新寫入。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def push_database_to_github(
    *,
    db_path: Path | None = None,
    message: str | None = None,
    force: bool = False,
) -> DbPushResult:
    """
    將 data/sportsbet.db commit 並 push 至 origin。
    需設定環境變數或 Streamlit Secrets：GITHUB_TOKEN（repo 寫入權限）。
    """
    if not config.GITHUB_DB_SYNC_ENABLED and not force:
        return DbPushResult(False, "skipped", "GITHUB_DB_SYNC_ENABLED=false")

    token = _resolve_github_token()
    if not token:
        return DbPushResult(
            False,
            "skipped",
            "未設定 GITHUB_TOKEN · 請在 Streamlit Secrets 或 .env 加入",
        )

    root = config.PROJECT_ROOT
    db_path = db_path or (config.DATA_DIR / "sportsbet.db")
    if not db_path.exists():
        return DbPushResult(False, "failed", f"資料庫不存在：{db_path}")

    try:
        _checkpoint_sqlite(db_path)
    except Exception as exc:
        logger.warning("WAL checkpoint 略過: %s", exc)

    rel = db_path.relative_to(root).as_posix()
    msg = message or f"chore(data): sync sports database {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    status = _git("status", "--porcelain", rel, cwd=root)
    if status.returncode != 0:
        return DbPushResult(False, "failed", f"git status 失敗：{status.stderr.strip()}")
    if not status.stdout.strip():
        return DbPushResult(True, "unchanged", "資料庫無變更（GitHub 已是最新）")

    add = _git("add", rel, cwd=root)
    if add.returncode != 0:
        return DbPushResult(False, "failed", f"git add 失敗：{add.stderr.strip()}")

    commit = _git("commit", "-m", msg, cwd=root)
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        return DbPushResult(False, "failed", f"git commit 失敗：{commit.stderr.strip()}")

    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    branch_name = branch.stdout.strip() or "main"

    remote = config.GITHUB_REPO_REMOTE
    if remote.startswith("https://github.com/") and "@" not in remote:
        remote_url = remote.replace("https://", f"https://x-access-token:{token}@")
        set_url = _git("remote", "set-url", "origin", remote_url, cwd=root)
        if set_url.returncode != 0:
            return DbPushResult(False, "failed", f"git remote 失敗：{set_url.stderr.strip()}")
        try:
            push = _git("push", "origin", branch_name, cwd=root)
        finally:
            _git("remote", "set-url", "origin", remote, cwd=root)
    else:
        push = _git("push", "origin", branch_name, cwd=root)

    if push.returncode != 0:
        return DbPushResult(False, "failed", f"git push 失敗：{push.stderr.strip()}")

    logger.info("資料庫已推送至 GitHub: %s", rel)
    return DbPushResult(True, "pushed", f"已推送 {rel} → GitHub ({branch_name})")


def persist_database_after_sync(
    message: str | None = None,
    *,
    db: "SportsDatabase | None" = None,
    force: bool = False,
) -> DbPushResult:
    """同步管線結束後：checkpoint + push，並記錄 db_pushed_at。"""
    from sportsbet.data.database import SportsDatabase

    result = push_database_to_github(message=message, force=force)
    if result.status in ("pushed", "unchanged"):
        db = db or SportsDatabase()
        now = datetime.now().isoformat(timespec="seconds")
        for sport in ("nba", "mlb"):
            db.set_backtest_sync_meta(sport, "db_pushed_at", now)  # type: ignore[arg-type]
    return result
