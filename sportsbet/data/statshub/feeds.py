"""解析 Sportradar Gismo feed JSON（match_stats / match_squads 等）。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _doc_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    doc = payload.get("doc")
    if isinstance(doc, list) and doc:
        row = doc[0]
        if isinstance(row, dict):
            if row.get("event") == "exception":
                return None
            data = row.get("data")
            return data if isinstance(data, dict) else row
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _team_side(team_obj: dict[str, Any], *, home_uid: int | None, away_uid: int | None) -> str | None:
    uid = team_obj.get("uid") or team_obj.get("_id")
    if home_uid is not None and uid == home_uid:
        return "home"
    if away_uid is not None and uid == away_uid:
        return "away"
    return None


def parse_match_info_doc(data: dict[str, Any]) -> dict[str, Any]:
    """從 match_info SSR 資料提取常用欄位。"""
    match = data.get("match") if isinstance(data.get("match"), dict) else {}
    teams = match.get("teams") if isinstance(match.get("teams"), dict) else {}
    home = teams.get("home") if isinstance(teams.get("home"), dict) else {}
    away = teams.get("away") if isinstance(teams.get("away"), dict) else {}
    dt = match.get("_dt") if isinstance(match.get("_dt"), dict) else {}
    periods = match.get("periods") if isinstance(match.get("periods"), dict) else {}
    result = match.get("result") if isinstance(match.get("result"), dict) else {}

    ts = dt.get("uts")
    match_date = None
    if ts:
        try:
            match_date = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError):
            pass

    return {
        "sportradar_match_id": match.get("_id"),
        "home_team_zh": home.get("name") or home.get("mediumname"),
        "away_team_zh": away.get("name") or away.get("mediumname"),
        "home_nickname": home.get("nickname"),
        "away_nickname": away.get("nickname"),
        "home_uid": home.get("uid"),
        "away_uid": away.get("uid"),
        "match_date": match_date,
        "status": (match.get("status") or {}).get("name") if isinstance(match.get("status"), dict) else None,
        "result_home": result.get("home"),
        "result_away": result.get("away"),
        "periods": periods,
        "coverage": match.get("coverage") if isinstance(match.get("coverage"), dict) else {},
        "round_name": (match.get("roundname") or {}).get("name") if isinstance(match.get("roundname"), dict) else None,
    }


def parse_gismo_feed(feed_key: str, payload: dict[str, Any], *, match_info: dict[str, Any] | None = None) -> dict[str, Any]:
    """依 feed 名稱解析 JSON。"""
    data = _doc_data(payload)
    if data is None:
        return {"feed": feed_key, "ok": False, "players": [], "injuries": [], "lineups": [], "team_stats": []}

    mi = match_info or {}
    home_uid = mi.get("home_uid")
    away_uid = mi.get("away_uid")

    if feed_key.startswith("match_stats"):
        return _parse_match_stats(data, feed_key, home_uid=home_uid, away_uid=away_uid)
    if feed_key.startswith("match_squads"):
        return _parse_match_squads(data, feed_key, home_uid=home_uid, away_uid=away_uid)
    if feed_key.startswith("match_playerdetails"):
        return _parse_player_details(data, feed_key, home_uid=home_uid, away_uid=away_uid)
    if feed_key.startswith("match_details"):
        return _parse_match_details(data, feed_key)

    return {"feed": feed_key, "ok": True, "raw": data}


def _parse_match_stats(data: dict[str, Any], feed_key: str, *, home_uid, away_uid) -> dict[str, Any]:
    team_stats: list[dict[str, Any]] = []
    values = data.get("values") if isinstance(data.get("values"), dict) else data
    teams = values.get("teams") if isinstance(values.get("teams"), dict) else values.get("team")
    if isinstance(teams, dict):
        for side_key, team_block in teams.items():
            if not isinstance(team_block, dict):
                continue
            team = team_block.get("team") if isinstance(team_block.get("team"), dict) else team_block
            stats = team_block.get("stats") if isinstance(team_block.get("stats"), dict) else team_block
            team_stats.append(
                {
                    "side": side_key,
                    "team_name": team.get("name") or team.get("nickname"),
                    "stats": stats,
                }
            )
    return {"feed": feed_key, "ok": True, "team_stats": team_stats, "players": [], "injuries": [], "lineups": []}


def _parse_match_squads(data: dict[str, Any], feed_key: str, *, home_uid, away_uid) -> dict[str, Any]:
    lineups: list[dict[str, Any]] = []
    injuries: list[dict[str, Any]] = []
    players: list[dict[str, Any]] = []

    squads = data.get("squads") if isinstance(data.get("squads"), dict) else data
    for side_key in ("home", "away"):
        block = squads.get(side_key)
        if not isinstance(block, dict):
            continue
        for p in block.get("players") or block.get("squad") or []:
            if not isinstance(p, dict):
                continue
            player = p.get("player") if isinstance(p.get("player"), dict) else p
            name = player.get("name") or player.get("fullname")
            pid = player.get("_id") or player.get("id")
            pos = player.get("position") or player.get("primarypositiontype")
            starter = bool(p.get("starter") or p.get("substitute") is False)
            entry = {
                "side": side_key,
                "player_id": f"sr-{pid}" if pid else None,
                "name": name,
                "position": pos,
                "is_starter": starter,
                "expected_minutes": p.get("minutes") or p.get("expectedminutes"),
            }
            players.append(entry)
            if starter:
                lineups.append(entry)
            status = p.get("status") or p.get("injury") or player.get("status")
            if status and str(status).lower() not in ("ok", "available", "active", "none", ""):
                injuries.append(
                    {
                        "side": side_key,
                        "player_id": entry["player_id"],
                        "name": name,
                        "status": str(status),
                        "injury_type": p.get("reason") or p.get("injury_type"),
                    }
                )
    return {"feed": feed_key, "ok": True, "lineups": lineups, "injuries": injuries, "players": players, "team_stats": []}


def _parse_player_details(data: dict[str, Any], feed_key: str, *, home_uid, away_uid) -> dict[str, Any]:
    players: list[dict[str, Any]] = []
    for side_key in ("home", "away"):
        block = data.get(side_key)
        if not isinstance(block, dict):
            continue
        for p in block.get("players") or []:
            if not isinstance(p, dict):
                continue
            player = p.get("player") if isinstance(p.get("player"), dict) else p
            stats = p.get("stats") if isinstance(p.get("stats"), dict) else p.get("statistics")
            players.append(
                {
                    "side": side_key,
                    "player_id": f"sr-{player.get('_id')}" if player.get("_id") else None,
                    "name": player.get("name"),
                    "position": player.get("position"),
                    "stats": stats if isinstance(stats, dict) else {},
                    "points": _num(stats, "points"),
                    "rebounds": _num(stats, "rebounds"),
                    "assists": _num(stats, "assists"),
                    "minutes": _num(stats, "minutes"),
                }
            )
    return {"feed": feed_key, "ok": True, "players": players, "injuries": [], "lineups": [], "team_stats": []}


def _parse_match_details(data: dict[str, Any], feed_key: str) -> dict[str, Any]:
    injuries: list[dict[str, Any]] = []
    for side_key in ("home", "away"):
        block = data.get(side_key) or data.get(f"{side_key}team")
        if not isinstance(block, dict):
            continue
        missing = block.get("missingplayers") or block.get("injuries") or block.get("unavailable")
        if isinstance(missing, list):
            for p in missing:
                if not isinstance(p, dict):
                    continue
                player = p.get("player") if isinstance(p.get("player"), dict) else p
                injuries.append(
                    {
                        "side": side_key,
                        "player_id": f"sr-{player.get('_id')}" if player.get("_id") else None,
                        "name": player.get("name"),
                        "status": p.get("status") or "Out",
                        "injury_type": p.get("reason") or p.get("description"),
                    }
                )
    return {"feed": feed_key, "ok": True, "injuries": injuries, "players": [], "lineups": [], "team_stats": []}


def _num(stats: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(stats, dict):
        return None
    val = stats.get(key)
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def merge_feed_results(parts: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "players": [],
        "injuries": [],
        "lineups": [],
        "team_stats": [],
        "feeds_ok": [],
        "feeds_failed": [],
    }
    seen_p: set[str] = set()
    seen_i: set[str] = set()
    for p in parts:
        feed = p.get("feed", "?")
        if p.get("ok"):
            out["feeds_ok"].append(feed)
        else:
            out["feeds_failed"].append(feed)
        for row in p.get("players") or []:
            key = f"{row.get('player_id')}|{row.get('name')}"
            if key in seen_p:
                continue
            seen_p.add(key)
            out["players"].append(row)
        for row in p.get("injuries") or []:
            key = f"{row.get('player_id')}|{row.get('name')}"
            if key in seen_i:
                continue
            seen_i.add(key)
            out["injuries"].append(row)
        out["lineups"].extend(p.get("lineups") or [])
        out["team_stats"].extend(p.get("team_stats") or [])
    return out
