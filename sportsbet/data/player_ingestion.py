"""V2 球員/傷兵資料：僅 ESPN + nba_api / ESPN 真實統計。"""
from __future__ import annotations

from datetime import date, timedelta

from sportsbet.data.database import SportsDatabase

Sport = str  # nba | mlb


def sync_v2_player_data(db: SportsDatabase, sport: str, *, days_lineup: int = 7) -> dict[str, int]:
    """同步傷兵、真實球員統計、預計上場（無 mock / 位置預設值）。"""
    from sportsbet.data.espn_injuries import (
        EspnInjuryClient,
        sync_espn_injuries,
        sync_espn_projected_lineups,
    )

    match_dates = [(date.today() + timedelta(days=i)).isoformat() for i in range(days_lineup)]
    client = EspnInjuryClient()

    injuries_n = sync_espn_injuries(db, sport, report_date=date.today().isoformat(), client=client)

    statshub_inj = 0
    if sport == "nba":
        from sportsbet import config

        if config.STATSHUB_ENABLED:
            try:
                from sportsbet.data.statshub_sync import supplement_injuries_from_statshub

                statshub_inj = supplement_injuries_from_statshub(db, sport, days_ahead=days_lineup)
            except Exception:
                statshub_inj = 0

    if sport == "nba":
        from sportsbet.data.nba_player_stats import sync_nba_player_stats

        players_n = sync_nba_player_stats(db, client=client)
    elif sport == "mlb":
        from sportsbet.data.mlb_player_stats import sync_mlb_player_stats

        players_n = sync_mlb_player_stats(db, client=client)
    else:
        players_n = 0

    lineups_n = sync_espn_projected_lineups(
        db,
        sport,
        match_dates=match_dates,
        client=client,
    )

    out = {"players": players_n, "injuries": injuries_n, "lineups": lineups_n}
    if statshub_inj:
        out["statshub_injuries"] = statshub_inj
    return out
