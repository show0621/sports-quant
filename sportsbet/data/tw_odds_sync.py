"""
台灣運彩賠率同步：官方 Blob（sportslottery.com.tw 後端）→ 玩運彩補缺。

官網 event 頁（如 /sportsbook/.../event/3472877.1）資料來自同一套 Blob JSON；
Cloudflare 擋 HTML API，故以 blob.sportslottery.com.tw/apidata 為主來源。
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_logos import resolve_team_in_database

logger = logging.getLogger(__name__)

Sport = str
TW_BOOKMAKER = "sportslottery"
CORE_MARKETS = ("moneyline", "spread", "total")


def _match_game_id(
    db: SportsDatabase,
    sport: Sport,
    games: pd.DataFrame,
    home_team: str,
    away_team: str,
) -> int | None:
    h = resolve_team_in_database(db, sport, str(home_team))  # type: ignore[arg-type]
    a = resolve_team_in_database(db, sport, str(away_team))  # type: ignore[arg-type]
    for gh, ga in ((h, a), (a, h)):
        hit = games[(games["home_team"] == gh) & (games["away_team"] == ga)]
        if not hit.empty:
            return int(hit.iloc[0]["id"])
    return None


def _game_has_market(db: SportsDatabase, game_id: int, market: str, *, bookmaker: str) -> bool:
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM odds
            WHERE game_id = ? AND market = ? AND bookmaker = ?
            LIMIT 1
            """,
            (game_id, market, bookmaker),
        ).fetchone()
    return row is not None


def _game_tw_markets_complete(db: SportsDatabase, game_id: int) -> bool:
    return all(_game_has_market(db, game_id, m, bookmaker=TW_BOOKMAKER) for m in CORE_MARKETS)


def _write_sportslottery_rows(
    db: SportsDatabase,
    sport: Sport,
    odds_df: pd.DataFrame,
    match_date: str,
    *,
    replace: bool,
) -> int:
    if odds_df.empty:
        return 0

    games = db.get_games(sport, match_date)
    if games.empty:
        return 0

    if replace:
        db.clear_odds_for_date(sport, match_date, bookmaker=TW_BOOKMAKER)

    n = 0
    for _, o in odds_df.iterrows():
        if str(o.get("match_date", ""))[:10] != match_date:
            continue
        gid = _match_game_id(db, sport, games, o["home_team"], o["away_team"])
        if gid is None:
            continue
        market = str(o.get("market", "moneyline"))
        selection = str(o.get("selection", "home"))
        handicap = float(o["handicap"]) if pd.notna(o.get("handicap")) else None
        if market == "spread" and selection == "away" and handicap is not None:
            handicap = -handicap
        db.upsert_odds(
            gid,
            market,
            selection,
            float(o["odds"]),
            handicap=handicap,
            bookmaker=TW_BOOKMAKER,
            odds_phase=str(o.get("odds_phase", "live")),
        )
        n += 1
        event_id = o.get("event_id")
        if event_id and hasattr(db, "set_game_tw_event_id"):
            try:
                db.set_game_tw_event_id(gid, str(event_id))  # type: ignore[attr-defined]
            except Exception:
                pass
    return n


def fetch_sportslottery_odds_df(sport: Sport) -> pd.DataFrame:
    from sportsbet.data.sportslottery import SportLotteryClient
    from sportsbet.data.team_logos import resolve_team_in_database

    client = SportLotteryClient()
    df = client.fetch_all(sports={sport})
    if df.empty:
        return df
    db = SportsDatabase()
    out = df.copy()
    out["home_team"] = out["home_team"].map(
        lambda t: resolve_team_in_database(db, sport, str(t))  # type: ignore[arg-type]
    )
    out["away_team"] = out["away_team"].map(
        lambda t: resolve_team_in_database(db, sport, str(t))  # type: ignore[arg-type]
    )
    return out


def fill_playsport_gaps_for_date(
    db: SportsDatabase,
    sport: Sport,
    match_date: str,
    *,
    max_teams: int | None = None,
) -> int:
    """玩運彩補缺：僅對尚無 sportslottery 完整盤口的場次/球隊抓取。"""
    if not config.PLAYSPORT_ENABLED:
        return 0

    games = db.get_games(sport, match_date)
    if games.empty:
        return 0

    need_gids = [
        int(r["id"])
        for _, r in games.iterrows()
        if not _game_tw_markets_complete(db, int(r["id"]))
    ]
    if not need_gids:
        return 0

    teams: set[str] = set()
    for gid in need_gids:
        row = games[games["id"] == gid].iloc[0]
        teams.add(str(row["home_team"]))
        teams.add(str(row["away_team"]))

    from sportsbet.data.playsport_scraper import PlaySportScraper

    scraper = PlaySportScraper()
    team_ids = scraper.list_team_ids(sport)  # type: ignore[arg-type]
    name_to_id = {name: tid for tid, name in team_ids.items()}

    from sportsbet.data.team_names import team_bilingual

    targets: list[int] = []
    for team in teams:
        zh = team_bilingual(team, sport)[1] or team
        tid = name_to_id.get(zh) or name_to_id.get(team)
        if tid:
            targets.append(int(tid))
    targets = list(dict.fromkeys(targets))
    if max_teams:
        targets = targets[:max_teams]

    if not targets:
        logger.info("playsport 補缺 %s %s：找不到 teamid", sport, match_date)
        return 0

    before = sum(db.count_odds_for_date(sport, match_date) for _ in [0])
    for tid in targets:
        try:
            scraper.sync_team_to_database(db, tid, sport)  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("playsport 補缺 teamid=%s: %s", tid, exc)
    after = db.count_odds_for_date(sport, match_date)
    added = max(0, after - before)
    logger.info(
        "playsport 補缺 sport=%s date=%s teams=%d added~%d",
        sport, match_date, len(targets), added,
    )
    return added


def sync_tw_odds_for_date(
    db: SportsDatabase,
    sport: Sport,
    match_date: str,
    *,
    replace: bool = False,
    playsport_fallback: bool | None = None,
) -> dict[str, int]:
    """
    單日台灣盤口：① 台灣運彩 Blob ② 缺漏時玩運彩。
    含不讓分 / 讓分 / 大小分 / 勝分差（margin）。
    """
    out = {"sportslottery_rows": 0, "playsport_fallback": 0}
    try:
        odds_df = fetch_sportslottery_odds_df(sport)
        if not odds_df.empty and "match_date" in odds_df.columns:
            day_df = odds_df[odds_df["match_date"].astype(str).str[:10] == match_date]
            out["sportslottery_rows"] = _write_sportslottery_rows(
                db, sport, day_df, match_date, replace=replace,
            )
    except Exception as exc:
        logger.warning("台灣運彩 Blob 失敗 %s %s: %s", sport, match_date, exc)

    use_ps = playsport_fallback if playsport_fallback is not None else config.PLAYSPORT_ENABLED
    if use_ps:
        games = db.get_games(sport, match_date)
        incomplete = any(
            not _game_tw_markets_complete(db, int(r["id"])) for _, r in games.iterrows()
        ) if not games.empty else out["sportslottery_rows"] == 0
        if incomplete or out["sportslottery_rows"] == 0:
            out["playsport_fallback"] = fill_playsport_gaps_for_date(
                db,
                sport,
                match_date,
                max_teams=config.PLAYSPORT_MAX_TEAMS_PER_SYNC,
            )

    return out


def sync_tw_odds_recent(
    db: SportsDatabase,
    sport: Sport,
    *,
    days: int | None = None,
) -> dict[str, int]:
    """同步近 N 天（含今日/未來）台灣運彩 + 玩運彩補缺。"""
    from datetime import timedelta

    span = days if days is not None else config.HISTORICAL_BLOB_ODDS_DAYS + 7
    totals = {"sportslottery_rows": 0, "playsport_fallback": 0, "days": 0}
    for offset in range(-3, span + 1):
        d = (date.today() + timedelta(days=offset)).isoformat()
        if db.get_games(sport, d).empty and offset > 0:
            continue
        part = sync_tw_odds_for_date(db, sport, d, replace=False)
        totals["sportslottery_rows"] += part["sportslottery_rows"]
        totals["playsport_fallback"] += part["playsport_fallback"]
        totals["days"] += 1
    if config.jbot_configured():
        from sportsbet.data.jbot_odds_sync import sync_jbot_upcoming_odds

        totals["jbot_upcoming"] = sync_jbot_upcoming_odds(db, sport, days_ahead=span)
    db.set_backtest_sync_meta(sport, "tw_odds_synced_at", date.today().isoformat())
    return totals
