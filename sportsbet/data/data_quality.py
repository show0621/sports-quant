"""資料品質檢查：決定是否啟用 Bottom-Up / 熱區等功能。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from sportsbet.data.database import SportsDatabase

Sport = Literal["nba", "mlb"]

# 台灣盤口來源（玩運彩 / 運彩 Blob / JBot / 標準賠率）
TW_ODDS_BOOKMAKERS = ("sportslottery", "playsport", "jbot", "tw_standard")


def has_real_player_stats(db: SportsDatabase, sport: Sport) -> bool:
    """至少 5 名球員有非空 rolling_off_rating（來自真實 API）。"""
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT player_id) AS n
            FROM player_advanced_stats
            WHERE sport = ?
              AND rolling_off_rating IS NOT NULL
              AND hot_cold_index IS NOT NULL
            """,
            (sport,),
        ).fetchone()
    return int(row["n"] or 0) >= 5


def roster_rating_enabled(db: SportsDatabase, sport: Sport) -> bool:
    from sportsbet import config

    if not config.USE_ROSTER_RATING:
        return False
    return has_real_player_stats(db, sport)


def team_has_player_metrics(db: SportsDatabase, sport: Sport, team: str) -> bool:
    """該隊是否有真實球員進階數據（非虛構）。"""
    players = db.get_players_by_team(sport, team)
    if players.empty:
        return False
    col = "vorp" if sport == "nba" else "war"
    if col not in players.columns:
        return False
    return int(players[col].notna().sum()) >= 3


def matchup_injury_adjustment_ready(
    db: SportsDatabase,
    sport: Sport,
    home_team: str,
    away_team: str,
    match_date: str,
) -> bool:
    """
    是否允許套用傷兵/陣容勝率修正：
    需近期傷兵已同步，且主客隊皆有真實球員 VORP/WAR。
    """
    if not roster_rating_enabled(db, sport):
        return False
    if not _injuries_synced_recently(db, sport):
        return False
    return (
        team_has_player_metrics(db, sport, home_team)
        and team_has_player_metrics(db, sport, away_team)
    )


def _injuries_synced_recently(db: SportsDatabase, sport: Sport) -> bool:
    """今日或昨日已成功跑過 ESPN 傷兵同步（即使 0 人受傷也算）。"""
    last = db.get_backtest_sync_meta(sport, "injuries_synced_at")
    if not last:
        return False
    cutoff = (date.today() - timedelta(days=1)).isoformat()
    return str(last)[:10] >= cutoff


def data_quality_summary(db: SportsDatabase, sport: Sport) -> dict[str, bool]:
    detail = data_quality_detail(db, sport)
    return {key: bool(info.get("ok")) for key, info in detail.items()}


def data_quality_detail(db: SportsDatabase, sport: Sport) -> dict[str, dict[str, object]]:
    """各資料源是否就緒 + 除錯用說明。"""
    stats = db.get_team_stats(sport)
    bm_placeholders = ",".join("?" for _ in TW_ODDS_BOOKMAKERS)
    with db.connection() as conn:
        games_n = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM games WHERE sport = ? AND status = 'final'",
                (sport,),
            ).fetchone()["n"]
            or 0
        )
        tw_row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT o.game_id) AS n,
                   GROUP_CONCAT(DISTINCT o.bookmaker) AS sources
            FROM odds o
            JOIN games g ON g.id = o.game_id
            WHERE g.sport = ? AND o.bookmaker IN ({bm_placeholders})
            """,
            (sport, *TW_ODDS_BOOKMAKERS),
        ).fetchone()
        tw_n = int(tw_row["n"] or 0)
        tw_sources = str(tw_row["sources"] or "")
        blob_n = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT o.game_id) AS n FROM odds o
                JOIN games g ON g.id = o.game_id
                WHERE g.sport = ? AND o.bookmaker = 'sportslottery'
                """,
                (sport,),
            ).fetchone()["n"]
            or 0
        )
        ml_n = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT o.game_id) AS n FROM odds o
                JOIN games g ON g.id = o.game_id
                WHERE g.sport = ? AND o.market = 'moneyline'
                """,
                (sport,),
            ).fetchone()["n"]
            or 0
        )
        inj_n = int(
            conn.execute(
                """
                SELECT COUNT(*) AS n FROM injury_reports
                WHERE sport = ? AND source = 'espn'
                  AND report_date >= date('now', '-7 days')
                """,
                (sport,),
            ).fetchone()["n"]
            or 0
        )
        inj_last = db.get_backtest_sync_meta(sport, "injuries_synced_at")

    injuries_ok = _injuries_synced_recently(db, sport) or inj_n > 0
    if injuries_ok:
        if inj_n > 0:
            inj_note = f"{inj_n} 筆 · 最近 {str(inj_last or '')[:10] or '—'}"
        else:
            inj_note = f"已同步 · 近 7 日無 Out/D/Q · {str(inj_last or '')[:10]}"
    else:
        inj_note = "未同步 · 請完整同步或 watch"

    if tw_n > 0:
        tw_note = f"{tw_n} 場 · {tw_sources or '—'}"
        if blob_n == 0 and "playsport" in tw_sources:
            tw_note += "（玩運彩歷史；即時 Blob 尚無）"
    else:
        tw_note = "無盤口 · 賽前需 JBOT_TOKEN 或 watch 同步"
        from sportsbet import config

        if not config.jbot_configured():
            tw_note += "（Register Blob 已下架）"

    return {
        "team_stats": {
            "ok": not stats.empty,
            "detail": f"{len(stats)} 隊" if not stats.empty else "尚無統計",
        },
        "historical_games": {
            "ok": games_n > 0,
            "detail": f"{games_n} 場完賽",
        },
        "tw_odds": {
            "ok": tw_n > 0,
            "detail": tw_note,
        },
        "moneyline_odds": {
            "ok": ml_n > 0,
            "detail": f"{ml_n} 場",
        },
        "injuries": {
            "ok": injuries_ok,
            "detail": inj_note,
        },
        "player_rolling": {
            "ok": has_real_player_stats(db, sport),
            "detail": "≥5 人滾動統計" if has_real_player_stats(db, sport) else "執行完整同步（ESPN 爬取）",
        },
    }
