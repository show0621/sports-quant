"""
合併賠率、賽果與「賽前」球隊統計，產出回測用 timeline 資料集。

- 以正規化隊名 + 比賽日期對齊 API-Sports 賽果
- `won` 依實際比分與盤口計算
- `model_prob` 僅使用 match_date 之前的比賽建立統計（避免前視偏差）
"""
from __future__ import annotations

import logging
from typing import Literal

import pandas as pd

from sportsbet import analytics
from sportsbet.data.api_sports import ApiSportsClient
from sportsbet.data.storage import load_timeline
from sportsbet.data.team_names import normalize_matchup, normalize_team_name

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]

FINISHED_STATUS = {"FT", "AOT", "Finished", "FINAL", "Final"}


def load_all_games(sport: Sport) -> pd.DataFrame:
    """載入 data/{sport}/games_*.csv 並合併。"""
    from pathlib import Path

    from sportsbet import config

    sport_dir = config.DATA_DIR / sport
    files = sorted(sport_dir.glob("games_*.csv"))
    if not files:
        return pd.DataFrame()
    frames = [pd.read_csv(f, encoding="utf-8-sig") for f in files]
    games = pd.concat(frames, ignore_index=True)
    games["date"] = games["date"].astype(str).str[:10]
    games["home_team"] = games["home_team"].apply(lambda x: normalize_team_name(x, sport))
    games["away_team"] = games["away_team"].apply(lambda x: normalize_team_name(x, sport))
    return games.drop_duplicates(subset=["game_id"], keep="last")


def _build_stats_as_of(games: pd.DataFrame, as_of: str, sport: Sport) -> pd.DataFrame:
    """僅使用 date < as_of 的已完成比賽彙總球隊統計。"""
    if games.empty or "date" not in games.columns:
        return pd.DataFrame()
    subset = games[
        (games["date"] < as_of)
        & (games["status"].isin(FINISHED_STATUS) | games["status"].isna())
    ].copy()
    subset = subset.dropna(subset=["home_score", "away_score"])
    if subset.empty:
        return pd.DataFrame()

    client = ApiSportsClient()
    return client.build_team_stats(subset, sport)


def compute_model_prob_row(
    row: pd.Series,
    stats: pd.DataFrame,
    sport: Sport,
) -> float | None:
    """依賽前統計計算單注勝率（畢達哥拉斯 + Log5）。"""
    if stats.empty or "team" not in stats.columns:
        return None
    idx = stats.set_index("team")
    ht, at = row["home_team"], row["away_team"]
    if ht not in idx.index or at not in idx.index:
        return None
    h, a = idx.loc[ht], idx.loc[at]
    home_pyth = analytics.team_win_pct(
        sport,
        float(h["rs_per_game"]),
        float(h["ra_per_game"]),
        int(h.get("games", 0)),
    )
    away_pyth = analytics.team_win_pct(
        sport,
        float(a["rs_per_game"]),
        float(a["ra_per_game"]),
        int(a.get("games", 0)),
    )
    p_home, p_away = analytics.matchup_win_prob(home_pyth, away_pyth)
    sel = str(row.get("selection", "home"))
    if sel == "home":
        return p_home
    if sel == "away":
        return p_away
    # spread / total 簡化：仍用 moneyline 勝率作為 proxy（回測可再擴充）
    return p_home if sel in ("home", "over") else p_away


def compute_won(row: pd.Series, game: pd.Series) -> int | None:
    """依盤口類型與實際比分計算是否贏盤 (1/0)，無法判定回傳 None。"""
    try:
        hs, aws = float(game["home_score"]), float(game["away_score"])
    except (TypeError, ValueError, KeyError):
        return None

    market = str(row.get("market", "moneyline"))
    sel = str(row.get("selection", ""))

    if market == "moneyline":
        if sel == "home":
            return int(hs > aws)
        if sel == "away":
            return int(aws > hs)
        return None

    if market == "spread":
        hcap = row.get("handicap")
        if hcap is None or (isinstance(hcap, float) and pd.isna(hcap)):
            return None
        line = float(hcap)
        if sel == "home":
            return int(hs + line > aws)
        if sel == "away":
            return int(aws - line > hs)
        return None

    if market == "total":
        hcap = row.get("handicap")
        if hcap is None or (isinstance(hcap, float) and pd.isna(hcap)):
            return None
        total_line = float(hcap)
        combined = hs + aws
        if sel == "over":
            return int(combined > total_line)
        if sel == "under":
            return int(combined < total_line)
        return None

    return None


def join_games_to_odds(odds_df: pd.DataFrame, games_df: pd.DataFrame, sport: Sport) -> pd.DataFrame:
    """將賠率列對齊 API-Sports 賽果（正規化隊名 + 日期）。"""
    if odds_df.empty:
        return odds_df

    df = odds_df.copy()
    df["match_date"] = df["match_date"].astype(str).str[:10]
    df["home_team"] = df["home_team"].apply(lambda x: normalize_team_name(x, sport))
    df["away_team"] = df["away_team"].apply(lambda x: normalize_team_name(x, sport))

    if games_df.empty:
        df["game_id"] = None
        df["home_score"] = None
        df["away_score"] = None
        df["won"] = None
        return df

    g = games_df.copy()
    g["date"] = g["date"].astype(str).str[:10]
    g = g[g["status"].isin(FINISHED_STATUS) | g["status"].isna()]
    g = g.dropna(subset=["home_score", "away_score"])

    # 建立查找表：(home, away, date) -> game row
    lookup: dict[tuple[str, str, str], pd.Series] = {}
    for _, gr in g.iterrows():
        key = (
            str(gr["home_team"]).strip().lower(),
            str(gr["away_team"]).strip().lower(),
            gr["date"],
        )
        lookup[key] = gr

    game_ids = []
    home_scores = []
    away_scores = []
    won_list = []

    for _, row in df.iterrows():
        key = (
            str(row["home_team"]).strip().lower(),
            str(row["away_team"]).strip().lower(),
            row["match_date"],
        )
        gr = lookup.get(key)
        if gr is None:
            game_ids.append(None)
            home_scores.append(None)
            away_scores.append(None)
            won_list.append(None)
            continue
        game_ids.append(gr.get("game_id"))
        home_scores.append(gr["home_score"])
        away_scores.append(gr["away_score"])
        won_list.append(compute_won(row, gr))

    df["game_id"] = game_ids
    df["home_score"] = home_scores
    df["away_score"] = away_scores
    df["won"] = won_list
    return df


def attach_model_probs(
    df: pd.DataFrame,
    games_df: pd.DataFrame,
    sport: Sport,
) -> pd.DataFrame:
    """為每列附加賽前 model_prob（僅用 match_date 之前的比賽）。"""
    if df.empty:
        return df

    out = df.copy()
    probs: list[float | None] = []

    if games_df.empty:
        out["model_prob"] = None
        return out

    dates = sorted(out["match_date"].dropna().unique())

    stats_cache: dict[str, pd.DataFrame] = {}
    for d in dates:
        stats_cache[str(d)[:10]] = _build_stats_as_of(games_df, str(d)[:10], sport)

    for _, row in out.iterrows():
        d = str(row["match_date"])[:10]
        stats = stats_cache.get(d, pd.DataFrame())
        probs.append(compute_model_prob_row(row, stats, sport))

    out["model_prob"] = probs
    return out


def merge_timeline(
    odds_df: pd.DataFrame,
    sport: Sport,
    games_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    完整合併：賽果 + 賽前 model_prob + EV。

    預設僅保留 moneyline 且 won 可判定之列（回測常用）。
    """
    games = games_df if games_df is not None else load_all_games(sport)
    merged = join_games_to_odds(odds_df, games, sport)
    merged = attach_model_probs(merged, games, sport)

    merged["ev"] = merged.apply(
        lambda r: (
            analytics.expected_value(float(r["model_prob"]), float(r["odds"]))
            if r.get("model_prob") is not None and pd.notna(r["model_prob"])
            else None
        ),
        axis=1,
    )
    return merged


def build_backtest_dataset(
    sport: Sport,
    odds_df: pd.DataFrame | None = None,
    *,
    market: str | None = "moneyline",
    odds_phase: str | None = "close",
    min_parlay: int = 1,
) -> pd.DataFrame:
    """
    產出回測就緒資料集。

    Parameters
    ----------
    sport : nba | mlb
    odds_df : 若 None 則嘗試 load_timeline；仍無則回傳空表
    market : 篩選盤口，None 表示不篩
    odds_phase : 篩選開收盤階段（如 close 代表尾盤）
    min_parlay : 最低串關數（1=單場）
    """
    if odds_df is None:
        odds_df = load_timeline(sport)
    if odds_df is None or odds_df.empty:
        logger.warning("無賠率資料可合併")
        return pd.DataFrame()

    df = merge_timeline(odds_df, sport)

    if market:
        df = df[df["market"] == market]
    if odds_phase:
        df = df[df["odds_phase"] == odds_phase]
    if "min_parlay" in df.columns:
        df = df[df["min_parlay"] <= min_parlay]

    df = df.dropna(subset=["won", "model_prob", "odds"])
    df["won"] = df["won"].astype(int)
    return df.reset_index(drop=True)
