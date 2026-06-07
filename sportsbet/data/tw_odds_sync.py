"""
台灣運彩賠率同步：① 官網 SPA（Playwright）② Blob 場中 ③ 玩運彩補缺。

官網 event 例：
/sportsbook/sport/籃球/美國/美國職籃/34801.1/event/3472877.1
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
TW_ODDS_BOOKMAKERS = ("sportslottery", "playsport", "tw_standard")
_web_odds_cache: dict[str, pd.DataFrame] = {}


def _resolve_playsport_team_id(
    name_to_id: dict[str, int],
    team: str,
    sport: Sport,
) -> int | None:
    """玩運彩 teamid 對照（支援「尼克」等縮寫，非僅「紐約尼克」）。"""
    from sportsbet.data.team_names import build_reverse_map, team_bilingual

    en, zh = team_bilingual(team, sport)  # type: ignore[arg-type]
    rev = build_reverse_map(sport)  # type: ignore[arg-type]
    short_zh = rev.get(en, "")
    candidates: list[str] = []
    for c in (team, en, zh, short_zh):
        if c and c not in candidates:
            candidates.append(c)

    for ps_name, tid in name_to_id.items():
        if ps_name in candidates:
            return int(tid)

    en_last = en.split()[-1].lower() if en else ""
    for ps_name, tid in name_to_id.items():
        ps_lower = str(ps_name).lower()
        if en_last and en_last in ps_lower:
            return int(tid)
        if zh and (zh in ps_name or ps_name in zh):
            return int(tid)
        if short_zh and (short_zh in ps_name or ps_name in short_zh):
            return int(tid)
    return None


def _game_has_any_odds(db: SportsDatabase, game_id: int) -> bool:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM odds WHERE game_id = ? LIMIT 1",
            (game_id,),
        ).fetchone()
    return row is not None


def _game_has_tw_core_markets(db: SportsDatabase, game_id: int) -> bool:
    """任一台湾盤口來源具備 moneyline / spread / total 即視為完整。"""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT market FROM odds
            WHERE game_id = ? AND bookmaker IN ({})
            """.format(",".join("?" * len(TW_ODDS_BOOKMAKERS))),
            (game_id, *TW_ODDS_BOOKMAKERS),
        ).fetchall()
    markets = {str(r["market"]) for r in rows}
    return all(m in markets for m in CORE_MARKETS)


def _date_odds_fresh_in_db(db: SportsDatabase, sport: Sport, match_date: str) -> bool:
    """該日所有賽事具 sportslottery 核心盤且更新時間在 TTL 內。"""
    from datetime import datetime, timedelta, timezone

    games = db.get_games(sport, match_date)
    if games.empty:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.ODDS_DB_FRESH_HOURS)
    for _, g in games.iterrows():
        gid = int(g["id"])
        if not _game_has_tw_core_markets(db, gid):
            return False
        with db.connection() as conn:
            row = conn.execute(
                """
                SELECT MAX(created_at) AS ts FROM odds
                WHERE game_id = ? AND bookmaker = ?
                """,
                (gid, TW_BOOKMAKER),
            ).fetchone()
        ts_raw = row["ts"] if row else None
        if not ts_raw:
            return False
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        if ts < cutoff:
            return False
    return True


def prematch_odds_source_hint() -> str:
    """Streamlit / 日誌用：說明賽前盤口來源。"""
    if config.SPORTSLOTTERY_PLAYWRIGHT_ENABLED:
        return (
            "賽前盤口：台灣運彩官網 SPA（Playwright）。"
            "若 Cloud 仍空白，請在本機執行 "
            "`python main.py sync --mode daily --sport nba` 或 watch 後推送 DB。"
        )
    return (
        "請啟用 SPORTSLOTTERY_PLAYWRIGHT_ENABLED=true，"
        "由官網 event 頁抓取賽前盤口；玩運彩僅補官網缺漏之歷史場次。"
    )


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
        src = str(o.get("source", ""))
        if (
            market == "spread"
            and selection == "away"
            and handicap is not None
            and src not in ("sportslottery_web", "sportslottery_web_dom")
        ):
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
    """Blob 場中 + 官網 Playwright 賽前。"""
    from sportsbet.data.sportslottery import SportLotteryClient
    from sportsbet.data.team_logos import resolve_team_in_database

    frames: list[pd.DataFrame] = []
    client = SportLotteryClient()
    blob_df = client.fetch_all(sports={sport})
    if not blob_df.empty:
        frames.append(blob_df)

    if config.SPORTSLOTTERY_PLAYWRIGHT_ENABLED:
        from sportsbet.data.sportslottery_web import fetch_web_odds_df

        if sport not in _web_odds_cache:
            _web_odds_cache[sport] = fetch_web_odds_df(sport)
        web_df = _web_odds_cache[sport]
        if not web_df.empty:
            frames.append(web_df)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["event_id", "market", "selection", "handicap", "odds", "odds_phase"],
        keep="last",
    )
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
    """玩運彩補缺：僅當官網（sportslottery）尚無完整盤口時才抓。"""
    if not config.PLAYSPORT_ENABLED:
        return 0

    games = db.get_games(sport, match_date)
    if games.empty:
        return 0

    need_gids = [
        int(r["id"])
        for _, r in games.iterrows()
        if not _game_has_market_from_bookmaker(db, int(r["id"]), TW_BOOKMAKER)
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

    targets: list[int] = []
    for team in teams:
        tid = _resolve_playsport_team_id(name_to_id, team, sport)
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
    單日台灣盤口：① 官網/Blob ② 缺漏時玩運彩（官網有則不抓玩運彩）。
    DB 已有完整 sportslottery 核心盤且未過期時跳過官網抓取。
    """
    out = {"sportslottery_rows": 0, "playsport_fallback": 0, "sportslottery_web": 0, "cached": 0}
    if not replace and _date_odds_fresh_in_db(db, sport, match_date):
        logger.info(
            "盤口 %s %s 已快取於 DB（<%d 小時），跳過官網抓取",
            sport, match_date, config.ODDS_DB_FRESH_HOURS,
        )
        out["cached"] = 1
    else:
        try:
            odds_df = fetch_sportslottery_odds_df(sport)
            if not odds_df.empty and "match_date" in odds_df.columns:
                day_df = odds_df[odds_df["match_date"].astype(str).str[:10] == match_date]
                out["sportslottery_rows"] = _write_sportslottery_rows(
                    db, sport, day_df, match_date, replace=replace,
                )
        except Exception as exc:
            logger.warning("台灣運彩抓取失敗 %s %s: %s", sport, match_date, exc)

    use_ps = playsport_fallback if playsport_fallback is not None else config.PLAYSPORT_ENABLED
    if use_ps:
        games = db.get_games(sport, match_date)
        need_ps = [
            int(r["id"])
            for _, r in games.iterrows()
            if not _game_has_market_from_bookmaker(db, int(r["id"]), TW_BOOKMAKER)
            and not _game_has_tw_core_markets(db, int(r["id"]))
        ] if not games.empty else []
        if need_ps:
            out["playsport_fallback"] = fill_playsport_gaps_for_date(
                db,
                sport,
                match_date,
                max_teams=config.PLAYSPORT_MAX_TEAMS_PER_SYNC,
            )

    return out


def _game_has_market_from_bookmaker(db: SportsDatabase, game_id: int, bookmaker: str) -> bool:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM odds WHERE game_id = ? AND bookmaker = ? LIMIT 1",
            (game_id, bookmaker),
        ).fetchone()
    return row is not None


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
    db.set_backtest_sync_meta(sport, "tw_odds_synced_at", date.today().isoformat())
    return totals
