"""
台灣運彩賠率同步：① 官網 SPA（Playwright）② Blob 場中 ③ 玩運彩補缺／當日比對。

策略：
- **未來賽事**：官網有盤即寫入，不等待玩運彩（玩運彩通常賽當日才有）。
- **比賽當日**：同步玩運彩 predict/scale，與官網交叉比對；官網失敗時以玩運彩備援。
- **過去賽事**：官網缺漏時以玩運彩歷史頁補缺。
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
PS_BOOKMAKER = "playsport"
CORE_MARKETS = ("moneyline", "spread", "total")
TW_ODDS_BOOKMAKERS = ("sportslottery", "playsport", "tw_standard")
ODDS_COMPARE_TOLERANCE = 0.08
LINE_COMPARE_TOLERANCE = 0.26
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
            "賽前盤口：台灣運彩官網 SPA（Playwright）；"
            "比賽當日另抓玩運彩 predict/scale 交叉比對，官網失敗時備援。"
            "若 Cloud 仍空白，請在本機執行 "
            "`python main.py sync --mode daily --sport nba` 或 watch 後推送 DB。"
        )
    return (
        "請啟用 SPORTSLOTTERY_PLAYWRIGHT_ENABLED=true，"
        "由官網 event 頁抓取賽前盤口；玩運彩僅於比賽當日比對或官網缺漏時備援。"
    )


def _odds_snapshot(
    db: SportsDatabase,
    game_id: int,
    bookmaker: str,
) -> dict[str, float]:
    """擷取單一 bookmaker 的核心盤口（moneyline / spread / total）。"""
    raw = db.get_game_odds(game_id)
    if raw.empty:
        return {}
    sub = raw[raw["bookmaker"].astype(str) == bookmaker]
    if sub.empty:
        return {}
    out: dict[str, float] = {}
    for _, r in sub.iterrows():
        market = str(r["market"])
        sel = str(r["selection"])
        key = f"{market}:{sel}"
        if market == "spread" and pd.notna(r.get("handicap")):
            out[f"spread_line:{sel}"] = float(r["handicap"])
        if market == "total" and pd.notna(r.get("handicap")):
            out["total_line"] = float(r["handicap"])
        if pd.notna(r.get("odds")):
            out[key] = float(r["odds"])
    return out


def compare_tw_odds_sources(db: SportsDatabase, game_id: int) -> list[str]:
    """官網 vs 玩運彩核心盤口比對，回傳不一致訊息。"""
    sl = _odds_snapshot(db, game_id, TW_BOOKMAKER)
    ps = _odds_snapshot(db, game_id, PS_BOOKMAKER)
    if not sl or not ps:
        return []

    issues: list[str] = []
    for sel in ("home", "away"):
        k = f"moneyline:{sel}"
        if k in sl and k in ps and abs(sl[k] - ps[k]) > ODDS_COMPARE_TOLERANCE:
            issues.append(f"moneyline {sel}: 官網 {sl[k]:.2f} vs 玩運彩 {ps[k]:.2f}")

    for sel in ("home", "away"):
        lk = f"spread_line:{sel}"
        ok = f"spread:{sel}"
        if lk in sl and lk in ps and abs(sl[lk] - ps[lk]) > LINE_COMPARE_TOLERANCE:
            issues.append(f"spread {sel} 讓分: 官網 {sl[lk]:+.1f} vs 玩運彩 {ps[lk]:+.1f}")
        if ok in sl and ok in ps and abs(sl[ok] - ps[ok]) > ODDS_COMPARE_TOLERANCE:
            issues.append(f"spread {sel} 賠率: 官網 {sl[ok]:.2f} vs 玩運彩 {ps[ok]:.2f}")

    if "total_line" in sl and "total_line" in ps and abs(sl["total_line"] - ps["total_line"]) > LINE_COMPARE_TOLERANCE:
        issues.append(f"大小分線: 官網 {sl['total_line']:.1f} vs 玩運彩 {ps['total_line']:.1f}")
    for sel in ("over", "under"):
        k = f"total:{sel}"
        if k in sl and k in ps and abs(sl[k] - ps[k]) > ODDS_COMPARE_TOLERANCE:
            issues.append(f"total {sel}: 官網 {sl[k]:.2f} vs 玩運彩 {ps[k]:.2f}")

    return issues


def sync_playsport_game_day(
    db: SportsDatabase,
    sport: Sport,
    match_date: str,
) -> dict[str, int]:
    """
    比賽當日：抓玩運彩 predict/scale 寫入 DB，並與官網比對。
    官網缺漏時，UI 會透過 get_preferred_game_odds 自動改用 playsport。
    """
    from sportsbet.data.playsport_scraper import PlaySportScraper

    out = {"playsport_rows": 0, "odds_mismatch": 0, "odds_match": 0}
    if not config.PLAYSPORT_ENABLED:
        return out

    scraper = PlaySportScraper()
    out["playsport_rows"] = scraper.sync_predict_scale_to_database(db, sport, match_date)

    games = db.get_games(sport, match_date)
    for _, g in games.iterrows():
        gid = int(g["id"])
        if not _game_has_market_from_bookmaker(db, gid, PS_BOOKMAKER):
            continue
        if not _game_has_market_from_bookmaker(db, gid, TW_BOOKMAKER):
            logger.info(
                "玩運彩備援 game_id=%d %s vs %s（官網尚無盤口）",
                gid, g["away_team"], g["home_team"],
            )
            continue
        issues = compare_tw_odds_sources(db, gid)
        if issues:
            out["odds_mismatch"] += 1
            logger.warning(
                "盤口不一致 game_id=%d %s vs %s: %s",
                gid, g["away_team"], g["home_team"], "; ".join(issues),
            )
        else:
            out["odds_match"] += 1
            logger.info(
                "盤口一致 game_id=%d %s vs %s",
                gid, g["away_team"], g["home_team"],
            )
    return out


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
    """玩運彩歷史頁補缺：僅用於已結束賽事，官網尚無盤口時才抓。"""
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
    單日台灣盤口：
    ① 官網/Blob（未來賽事有官網即寫入，不等玩運彩）
    ② 比賽當日：玩運彩 predict/scale 比對＋備援
    ③ 過去賽事：官網缺漏時玩運彩歷史補缺
    """
    today = date.today().isoformat()
    is_game_day = match_date == today
    is_future = match_date > today

    out = {
        "sportslottery_rows": 0,
        "playsport_fallback": 0,
        "playsport_verify": 0,
        "odds_mismatch": 0,
        "odds_match": 0,
        "sportslottery_web": 0,
        "cached": 0,
    }

    skip_official = False
    if not replace and _date_odds_fresh_in_db(db, sport, match_date):
        logger.info(
            "盤口 %s %s 已快取於 DB（<%d 小時），跳過官網抓取",
            sport, match_date, config.ODDS_DB_FRESH_HOURS,
        )
        out["cached"] = 1
        skip_official = True
    if not skip_official:
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
    if not use_ps:
        return out

    if is_game_day:
        ps_stats = sync_playsport_game_day(db, sport, match_date)
        out["playsport_verify"] = ps_stats.get("playsport_rows", 0)
        out["odds_mismatch"] = ps_stats.get("odds_mismatch", 0)
        out["odds_match"] = ps_stats.get("odds_match", 0)
        return out

    if is_future:
        logger.debug("未來賽事 %s %s：跳過玩運彩（僅用官網賽前盤）", sport, match_date)
        return out

    games = db.get_games(sport, match_date)
    need_ps = [
        int(r["id"])
        for _, r in games.iterrows()
        if not _game_has_market_from_bookmaker(db, int(r["id"]), TW_BOOKMAKER)
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
    totals = {
        "sportslottery_rows": 0,
        "playsport_fallback": 0,
        "playsport_verify": 0,
        "odds_mismatch": 0,
        "odds_match": 0,
        "days": 0,
    }
    for offset in range(-3, span + 1):
        d = (date.today() + timedelta(days=offset)).isoformat()
        if db.get_games(sport, d).empty and offset > 0:
            continue
        part = sync_tw_odds_for_date(db, sport, d, replace=False)
        totals["sportslottery_rows"] += part.get("sportslottery_rows", 0)
        totals["playsport_fallback"] += part.get("playsport_fallback", 0)
        totals["playsport_verify"] += part.get("playsport_verify", 0)
        totals["odds_mismatch"] += part.get("odds_mismatch", 0)
        totals["odds_match"] += part.get("odds_match", 0)
        totals["days"] += 1
    db.set_backtest_sync_meta(sport, "tw_odds_synced_at", date.today().isoformat())
    return totals
