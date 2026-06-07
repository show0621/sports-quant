"""StatsHub → SQLite 同步（傷兵 / 首發 / 球員統計）。"""
from __future__ import annotations

import logging
from datetime import date

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.statshub.client import StatsHubClient
from sportsbet.data.team_logos import resolve_team_in_database

logger = logging.getLogger(__name__)

Sport = str


def _map_nickname_to_team(db: SportsDatabase, sport: Sport, nickname: str | None) -> str | None:
    if not nickname:
        return None
    from sportsbet.data.team_logos import NBA_ALIASES, canonical_team_name

    full = NBA_ALIASES.get(nickname, nickname)
    try:
        return resolve_team_in_database(db, sport, canonical_team_name(full, sport))  # type: ignore[arg-type]
    except Exception:
        return resolve_team_in_database(db, sport, full)  # type: ignore[arg-type]


def _normalize_injury_status(raw: str | None) -> str:
    if not raw:
        return "Out"
    key = raw.strip().lower()
    if any(x in key for x in ("out", "缺席", "缺陣", "doubt")):
        return "Out" if "doubt" not in key else "Doubtful"
    if "question" in key or "疑" in key:
        return "Questionable"
    if "prob" in key or "可能" in key:
        return "Probable"
    return "Out"


def _apply_statshub_bundle(
    db: SportsDatabase,
    sport: Sport,
    game_id: int,
    bundle,
    *,
    client: StatsHubClient | None = None,
) -> dict[str, int]:
    client = client or StatsHubClient(tenant=config.STATSHUB_TENANT, lang=config.STATSHUB_LANG)
    db.set_sportradar_match_id(game_id, str(bundle.sportradar_match_id))
    db.save_statshub_snapshot(
        game_id,
        client.bundle_to_json(bundle),
        sportradar_match_id=str(bundle.sportradar_match_id),
    )

    with db.connection() as conn:
        row = conn.execute("SELECT home_team, away_team, match_date FROM games WHERE id=?", (game_id,)).fetchone()
    if row is None:
        return {"error": 1}

    home_team = str(row["home_team"])
    away_team = str(row["away_team"])
    match_date = str(row["match_date"])[:10]
    summary = bundle.summary
    side_team = {
        "home": _map_nickname_to_team(db, sport, summary.get("home_nickname")) or home_team,
        "away": _map_nickname_to_team(db, sport, summary.get("away_nickname")) or away_team,
    }

    out = {"players": 0, "injuries": 0, "lineups": 0, "player_stats": 0, "feeds_ok": len(bundle.merged.get("feeds_ok", []))}
    report_date = date.today().isoformat()
    merged = bundle.merged

    for p in merged.get("players") or []:
        pid = p.get("player_id")
        name = p.get("name")
        if not pid or not name:
            continue
        team = side_team.get(str(p.get("side")), home_team)
        db.upsert_player(sport, str(pid), str(name), team, position=p.get("position"))
        out["players"] += 1

    for inj in merged.get("injuries") or []:
        pid = inj.get("player_id")
        name = inj.get("name")
        if not name:
            continue
        if not pid:
            pid = f"sr-name-{name}"
            team = side_team.get(str(inj.get("side")), home_team)
            db.upsert_player(sport, pid, name, team)
        team = side_team.get(str(inj.get("side")), home_team)
        db.upsert_injury(
            sport,
            str(pid),
            team,
            report_date,
            _normalize_injury_status(inj.get("status")),
            injury_type=inj.get("injury_type"),
            source="statshub",
        )
        out["injuries"] += 1

    for lu in merged.get("lineups") or []:
        pid = lu.get("player_id")
        if not pid:
            continue
        team = side_team.get(str(lu.get("side")), home_team)
        db.upsert_projected_lineup(
            sport,
            team,
            match_date,
            str(pid),
            expected_minutes=float(lu["expected_minutes"]) if lu.get("expected_minutes") is not None else None,
            is_starter=bool(lu.get("is_starter")),
        )
        out["lineups"] += 1

    db.set_backtest_sync_meta(sport, "statshub_synced_at", report_date)  # type: ignore[arg-type]
    return out


def sync_statshub_for_game(
    db: SportsDatabase,
    sport: Sport,
    game_id: int,
    sportradar_match_id: str | int,
    *,
    client: StatsHubClient | None = None,
) -> dict[str, int]:
    """拉取 StatsHub 並寫入 players / injuries / lineups / snapshot。"""
    if not config.STATSHUB_ENABLED:
        return {"skipped": 1}

    client = client or StatsHubClient(tenant=config.STATSHUB_TENANT, lang=config.STATSHUB_LANG)
    bundle = client.fetch_match_bundle(sportradar_match_id)
    return _apply_statshub_bundle(db, sport, game_id, bundle, client=client)


def auto_link_statshub_match_ids(db: SportsDatabase, sport: Sport, *, days_ahead: int = 21) -> int:
    """同一對戰組合：已綁定 sportradar_match_id 的場次共享給未綁定場次。"""
    from datetime import date, timedelta

    end = (date.today() + timedelta(days=days_ahead)).isoformat()
    linked = 0
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT home_team, away_team, sportradar_match_id
            FROM games
            WHERE sport = ?
              AND match_date >= date('now', '-1 day')
              AND match_date <= ?
              AND sportradar_match_id IS NOT NULL
              AND TRIM(sportradar_match_id) != ''
            GROUP BY home_team, away_team, sportradar_match_id
            """,
            (sport, end),
        ).fetchall()
        for row in rows:
            mid = str(row["sportradar_match_id"])
            cur = conn.execute(
                """
                UPDATE games SET sportradar_match_id = ?
                WHERE sport = ?
                  AND home_team = ?
                  AND away_team = ?
                  AND match_date >= date('now', '-1 day')
                  AND match_date <= ?
                  AND (sportradar_match_id IS NULL OR TRIM(sportradar_match_id) = '')
                """,
                (mid, sport, row["home_team"], row["away_team"], end),
            )
            linked += cur.rowcount
    return linked


def supplement_injuries_from_statshub(
    db: SportsDatabase,
    sport: Sport,
    *,
    days_ahead: int = 7,
) -> int:
    """ESPN 無該隊傷兵時，從 StatsHub 同步補足（需 sportradar_match_id）。"""
    if sport != "nba" or not config.STATSHUB_ENABLED:
        return 0

    from datetime import date, timedelta

    auto_link_statshub_match_ids(db, sport, days_ahead=days_ahead)
    report_date = date.today().isoformat()
    end = (date.today() + timedelta(days=days_ahead)).isoformat()
    espn_teams: set[str] = set()
    inj = db.get_injuries(sport, report_date)
    if not inj.empty:
        espn_teams = set(inj["team"].astype(str))

    added = 0
    with db.connection() as conn:
        games = conn.execute(
            """
            SELECT id, home_team, away_team, sportradar_match_id
            FROM games
            WHERE sport = ?
              AND match_date >= date('now', '-1 day')
              AND match_date <= ?
              AND sportradar_match_id IS NOT NULL
              AND TRIM(sportradar_match_id) != ''
            """,
            (sport, end),
        ).fetchall()

    client = StatsHubClient(tenant=config.STATSHUB_TENANT, lang=config.STATSHUB_LANG)
    for row in games:
        home = str(row["home_team"])
        away = str(row["away_team"])
        if home in espn_teams and away in espn_teams:
            continue
        gid = int(row["id"])
        mid = str(row["sportradar_match_id"])
        try:
            part = sync_statshub_for_game(db, sport, gid, mid, client=client)
            added += int(part.get("injuries", 0))
        except Exception as exc:
            logger.debug("StatsHub 傷兵補足略過 game=%s: %s", gid, exc)
    return added


def sync_statshub_for_upcoming(
    db: SportsDatabase,
    sport: Sport,
    *,
    days_ahead: int = 7,
) -> dict[str, int]:
    """對已有 sportradar_match_id 的 upcoming 賽事同步 StatsHub。"""
    totals = {"games": 0, "players": 0, "injuries": 0, "lineups": 0}
    games = db.get_upcoming_games_with_sportradar_id(sport, days_ahead=days_ahead)
    client = StatsHubClient(tenant=config.STATSHUB_TENANT, lang=config.STATSHUB_LANG)
    for _, row in games.iterrows():
        gid = int(row["id"])
        mid = str(row["sportradar_match_id"])
        part = sync_statshub_for_game(db, sport, gid, mid, client=client)
        totals["games"] += 1
        for k in ("players", "injuries", "lineups"):
            totals[k] += int(part.get(k, 0))
    return totals


def link_statshub_match(
    db: SportsDatabase,
    game_id: int,
    url_or_match_id: str,
) -> str | None:
    """將 StatsHub URL 或 match ID 綁定至 games.sportradar_match_id。"""
    from sportsbet.data.statshub.parser import parse_match_id_from_url

    raw = str(url_or_match_id).strip()
    mid = parse_match_id_from_url(raw) if "/" in raw else raw
    if not mid or not mid.isdigit():
        return None
    db.set_sportradar_match_id(game_id, mid)
    auto_link_statshub_match_ids(db, "nba")
    return mid


def import_statshub_feeds_json(
    db: SportsDatabase,
    sport: Sport,
    game_id: int,
    match_id: str | int,
    feeds: dict[str, object],
    *,
    summary: dict[str, object] | None = None,
) -> dict[str, int]:
    """匯入瀏覽器 DevTools 複製的 Gismo feed JSON。"""
    client = StatsHubClient(tenant=config.STATSHUB_TENANT, lang=config.STATSHUB_LANG)
    if summary is None:
        try:
            bundle_ssr = client.fetch_match_bundle(match_id)
            summary = bundle_ssr.summary
        except Exception:
            summary = {}
    bundle = client.bundle_from_feeds(match_id, feeds, summary=summary)  # type: ignore[arg-type]
    return _apply_statshub_bundle(db, sport, game_id, bundle, client=client)
