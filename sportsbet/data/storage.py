"""本地 CSV/Parquet 資料存檔。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from sportsbet import config
from sportsbet.data.sportslottery import STANDARD_ODDS_COLUMNS


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_games(df: pd.DataFrame, sport: str, season: str | int) -> Path:
    """儲存比賽/球隊統計。"""
    out = config.DATA_DIR / sport / f"games_{season}.csv"
    _ensure_parent(out)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return out


def load_games(sport: str, season: str | int) -> pd.DataFrame:
    path = config.DATA_DIR / sport / f"games_{season}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def save_odds(df: pd.DataFrame, source: str = "wanda") -> Path:
    """儲存賠率（標準 schema），依日期分檔。"""
    today = date.today().isoformat()
    out = config.WANDA_DATA_DIR / f"odds_{source}_{today}.csv"
    _ensure_parent(out)
    if out.exists():
        existing = pd.read_csv(out, encoding="utf-8-sig")
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates()
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return out


def load_odds_history(pattern: str = "odds_*.csv") -> pd.DataFrame:
    files = sorted(config.WANDA_DATA_DIR.glob(pattern))
    if not files:
        return pd.DataFrame()
    frames = [pd.read_csv(f, encoding="utf-8-sig") for f in files]
    return pd.concat(frames, ignore_index=True)


def save_timeline(df: pd.DataFrame, sport: str, tag: str = "merged") -> Path:
    """儲存合併賽果後的 timeline / 回測資料集。"""
    today = date.today().isoformat()
    out = config.DATA_DIR / sport / f"timeline_{tag}_{today}.parquet"
    _ensure_parent(out)
    df.to_parquet(out, index=False)
    # 同步寫一份 CSV 方便檢視
    csv_out = out.with_suffix(".csv")
    df.to_csv(csv_out, index=False, encoding="utf-8-sig")
    return out


def load_timeline(sport: str, tag: str | None = None) -> pd.DataFrame:
    """
    載入最新 timeline。

    tag 若指定則匹配 timeline_{tag}_*；否則取最新 timeline_* 檔。
    """
    sport_dir = config.DATA_DIR / sport
    if tag:
        pattern = f"timeline_{tag}_*.parquet"
    else:
        pattern = "timeline_*.parquet"
    files = sorted(sport_dir.glob(pattern))
    if not files:
        # 回退至賠率歷史
        odds = load_odds_history()
        if odds.empty:
            return pd.DataFrame()
        return odds
    return pd.read_parquet(files[-1])


def list_timeline_files(sport: str) -> list[Path]:
    return sorted((config.DATA_DIR / sport).glob("timeline_*.parquet"))


def save_team_stats(df: pd.DataFrame, sport: str) -> Path:
    out = config.DATA_DIR / sport / "team_stats.csv"
    _ensure_parent(out)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return out


def load_team_stats(sport: str) -> pd.DataFrame:
    path = config.DATA_DIR / sport / "team_stats.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def ensure_standard_odds_columns(df: pd.DataFrame) -> pd.DataFrame:
    """補齊標準賠率欄位。"""
    for col in STANDARD_ODDS_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df
