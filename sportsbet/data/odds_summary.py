"""從 DB 讀取 preferred 盤口摘要（無 Streamlit 依賴）。"""
from __future__ import annotations

import pandas as pd

from sportsbet.data.database import SportsDatabase


def latest_odds_by_key(odds_df: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    if odds_df.empty:
        return {}
    df = odds_df.sort_values("id")
    out: dict[tuple[str, str], pd.Series] = {}
    for _, row in df.iterrows():
        out[(str(row["market"]), str(row["selection"]))] = row
    return out


def summarize_preferred_odds(db: SportsDatabase, game_id: int | None) -> dict[str, object]:
    """取該場 get_preferred_game_odds 摘要。"""
    empty: dict[str, object] = {
        "ml_home": None,
        "ml_away": None,
        "spread_home_line": None,
        "spread_away_line": None,
        "spread_home_odds": None,
        "spread_away_odds": None,
        "total_line": None,
        "over_odds": None,
        "under_odds": None,
        "margin_odds": {},
        "bookmakers": [],
        "has_core": False,
    }
    if not game_id:
        return empty

    raw = db.get_preferred_game_odds(int(game_id))
    if raw.empty:
        return empty

    by = latest_odds_by_key(raw)
    ml_h = by.get(("moneyline", "home"))
    ml_a = by.get(("moneyline", "away"))
    sp_h = by.get(("spread", "home"))
    sp_a = by.get(("spread", "away"))
    ov = by.get(("total", "over"))
    un = by.get(("total", "under"))

    total_line = None
    if ov is not None and pd.notna(ov.get("handicap")):
        total_line = float(ov["handicap"])
    elif un is not None and pd.notna(un.get("handicap")):
        total_line = float(un["handicap"])

    spread_home_line = float(sp_h["handicap"]) if sp_h is not None and pd.notna(sp_h.get("handicap")) else None
    spread_away_line = float(sp_a["handicap"]) if sp_a is not None and pd.notna(sp_a.get("handicap")) else None

    margin_odds = {
        str(row["selection"]): float(row["odds"])
        for _, row in raw.iterrows()
        if str(row.get("market")) == "margin" and pd.notna(row.get("odds"))
    }

    has_core = all(
        x is not None
        for x in (
            ml_h,
            ml_a,
            sp_h,
            sp_a,
            total_line,
            ov,
            un,
        )
    )

    bookmakers = sorted({str(b) for b in raw["bookmaker"].dropna().unique()}) if "bookmaker" in raw.columns else []

    return {
        "ml_home": float(ml_h["odds"]) if ml_h is not None else None,
        "ml_away": float(ml_a["odds"]) if ml_a is not None else None,
        "spread_home_line": spread_home_line,
        "spread_away_line": spread_away_line,
        "spread_home_odds": float(sp_h["odds"]) if sp_h is not None else None,
        "spread_away_odds": float(sp_a["odds"]) if sp_a is not None else None,
        "total_line": total_line,
        "over_odds": float(ov["odds"]) if ov is not None else None,
        "under_odds": float(un["odds"]) if un is not None else None,
        "margin_odds": margin_odds,
        "bookmakers": bookmakers,
        "has_core": has_core,
    }
