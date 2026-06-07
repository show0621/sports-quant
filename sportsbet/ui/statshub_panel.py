"""StatsHub（台灣運彩 Sportradar）賽事數據面板。"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

import pandas as pd
import streamlit as st

from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.statshub.parser import statshub_urls

logger = logging.getLogger(__name__)


def _table_exists(db: SportsDatabase, conn: sqlite3.Connection, table: str) -> bool:
    fn = getattr(db, "_table_exists", None)
    if callable(fn):
        return bool(fn(conn, table))
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _compat_get_sportradar_match_id(db: SportsDatabase, game_id: int) -> str | None:
    getter = getattr(db, "get_sportradar_match_id", None)
    if callable(getter):
        return getter(game_id)
    try:
        with db.connection() as conn:
            row = conn.execute(
                "SELECT sportradar_match_id FROM games WHERE id = ?",
                (int(game_id),),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    val = row["sportradar_match_id"] if "sportradar_match_id" in row.keys() else None
    return str(val).strip() if val else None


def _compat_get_statshub_snapshot(db: SportsDatabase, game_id: int) -> dict[str, object] | None:
    getter = getattr(db, "get_statshub_snapshot", None)
    if callable(getter):
        return getter(game_id)
    try:
        with db.connection() as conn:
            if not _table_exists(db, conn, "statshub_snapshots"):
                return None
            row = conn.execute(
                "SELECT sportradar_match_id, payload_json, synced_at FROM statshub_snapshots WHERE game_id=?",
                (int(game_id),),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        payload = {}
    return {
        "sportradar_match_id": row["sportradar_match_id"],
        "payload": payload,
        "synced_at": row["synced_at"],
    }


def _compat_set_sportradar_match_id(db: SportsDatabase, game_id: int, match_id: str) -> None:
    setter = getattr(db, "set_sportradar_match_id", None)
    if callable(setter):
        setter(game_id, match_id)
        return
    with db.connection() as conn:
        conn.execute(
            "UPDATE games SET sportradar_match_id = ? WHERE id = ?",
            (str(match_id), int(game_id)),
        )


def _compat_link_match(db: SportsDatabase, game_id: int, url_or_match_id: str) -> str | None:
    try:
        from sportsbet.data.statshub_sync import link_statshub_match

        return link_statshub_match(db, game_id, url_or_match_id)
    except Exception:
        from sportsbet.data.statshub.parser import parse_match_id_from_url

        raw = str(url_or_match_id).strip()
        mid = parse_match_id_from_url(raw) if "/" in raw else raw
        if not mid or not mid.isdigit():
            return None
        _compat_set_sportradar_match_id(db, game_id, mid)
        return mid


def _period_table(summary: dict[str, Any]) -> pd.DataFrame:
    periods = summary.get("periods") if isinstance(summary.get("periods"), dict) else {}
    rows: list[dict[str, Any]] = []
    labels = {"p1": "Q1", "p2": "Q2", "p3": "Q3", "p4": "Q4", "ft": "總分"}
    for key, label in labels.items():
        block = periods.get(key)
        if isinstance(block, dict):
            rows.append({"節次": label, "主隊": block.get("home"), "客隊": block.get("away")})
    if not rows and summary.get("result_home") is not None:
        rows.append({
            "節次": "總分",
            "主隊": summary.get("result_home"),
            "客隊": summary.get("result_away"),
        })
    return pd.DataFrame(rows)


def _coverage_caption(summary: dict[str, Any]) -> str:
    cov = summary.get("coverage") if isinstance(summary.get("coverage"), dict) else {}
    flags = []
    if cov.get("hasstats"):
        flags.append("統計")
    if cov.get("basiclineup") or cov.get("lineup"):
        flags.append("陣容")
    if cov.get("injuries"):
        flags.append("傷兵")
    return " · ".join(flags) if flags else "僅基本賽事資訊"


def _players_df(players: list[dict[str, Any]], side: str) -> pd.DataFrame:
    rows = []
    for p in players:
        if str(p.get("side")) != side:
            continue
        stats = p.get("stats") if isinstance(p.get("stats"), dict) else {}
        rows.append({
            "球員": p.get("name"),
            "位置": p.get("position"),
            "PTS": p.get("points") or stats.get("points"),
            "REB": p.get("rebounds") or stats.get("rebounds"),
            "AST": p.get("assists") or stats.get("assists"),
            "MIN": p.get("minutes") or stats.get("minutes"),
            "首發": "✓" if p.get("is_starter") else "",
        })
    return pd.DataFrame(rows)


def _injuries_df(injuries: list[dict[str, Any]], side: str) -> pd.DataFrame:
    rows = []
    for inj in injuries:
        if str(inj.get("side")) != side:
            continue
        rows.append({
            "球員": inj.get("name"),
            "狀態": inj.get("status"),
            "傷勢": inj.get("injury_type"),
        })
    return pd.DataFrame(rows)


def _lineups_df(lineups: list[dict[str, Any]], side: str) -> pd.DataFrame:
    rows = []
    for lu in lineups:
        if str(lu.get("side")) != side:
            continue
        rows.append({
            "球員": lu.get("name"),
            "位置": lu.get("position"),
            "預估分鐘": lu.get("expected_minutes"),
        })
    return pd.DataFrame(rows)


def _team_stats_df(team_stats: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for ts in team_stats:
        stats = ts.get("stats") if isinstance(ts.get("stats"), dict) else {}
        flat = {k: v for k, v in stats.items() if not isinstance(v, (dict, list))}
        flat["隊伍"] = ts.get("team_name") or ts.get("side")
        rows.append(flat)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _espn_injuries_for_teams(db: SportsDatabase, sport: str, home: str, away: str) -> pd.DataFrame:
    inj = db.get_injuries(sport)
    if inj.empty:
        return inj
    teams = {home, away}
    if "team" in inj.columns:
        return inj[inj["team"].isin(teams)].copy()
    return inj


def _espn_lineups_for_teams(
    db: SportsDatabase,
    sport: str,
    home: str,
    away: str,
    match_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    home_lu = db.get_projected_lineup(sport, home, match_date)
    away_lu = db.get_projected_lineup(sport, away, match_date)
    return home_lu, away_lu


def _load_payload(db: SportsDatabase, game_id: int) -> dict[str, Any] | None:
    snap = _compat_get_statshub_snapshot(db, game_id)
    if snap and isinstance(snap.get("payload"), dict):
        return snap["payload"]  # type: ignore[return-value]
    return None


def render_statshub_panel(
    db: SportsDatabase,
    sport: str,
    game_id: int | None,
    *,
    home_team: str,
    away_team: str,
    match_date: str,
) -> None:
    """在賽事卡片內顯示 StatsHub 連結、賽事摘要、傷兵/陣容/統計。"""
    try:
        _render_statshub_panel_inner(
            db, sport, game_id,
            home_team=home_team, away_team=away_team, match_date=match_date,
        )
    except Exception as exc:
        logger.warning("StatsHub 面板略過: %s", exc)
        st.caption(f"StatsHub 面板暫不可用：{exc}")


def _render_statshub_panel_inner(
    db: SportsDatabase,
    sport: str,
    game_id: int | None,
    *,
    home_team: str,
    away_team: str,
    match_date: str,
) -> None:
    if sport != "nba" or not config.STATSHUB_ENABLED:
        return

    st.markdown("**StatsHub（台灣運彩）**")
    st.caption(
        "資料來源：[Sportradar StatsHub](https://statshub.sportradar.com/taiwansportslottery/zht/) · "
        "伺服器可讀取賽事摘要；詳細傷兵/統計需綁定 Match ID 或匯入瀏覽器 JSON"
    )

    if not game_id:
        st.info("尚無 game_id，無法同步 StatsHub。")
        return

    match_id = _compat_get_sportradar_match_id(db, int(game_id))
    payload = _load_payload(db, int(game_id))

    col_link, col_sync = st.columns([3, 1])
    with col_link:
        url_input = st.text_input(
            "StatsHub URL 或 Match ID",
            value=match_id or "",
            key=f"statshub_mid_{game_id}",
            placeholder="https://statshub.sportradar.com/.../match/70505022/report",
            label_visibility="collapsed",
        )
    with col_sync:
        if st.button("同步 StatsHub", key=f"statshub_sync_{game_id}"):
            from sportsbet.data.statshub_sync import sync_statshub_for_game

            raw = (url_input or match_id or "").strip()
            if raw:
                linked = _compat_link_match(db, int(game_id), raw)
                if linked:
                    with st.spinner("拉取 StatsHub…"):
                        stats = sync_statshub_for_game(db, sport, int(game_id), linked)
                    st.success(
                        f"已同步 · feeds {stats.get('feeds_ok', 0)} · "
                        f"傷兵 {stats.get('injuries', 0)} · 首發 {stats.get('lineups', 0)}"
                    )
                    st.rerun()
                else:
                    st.error("無效的 URL 或 Match ID")
            else:
                st.warning("請先輸入 StatsHub URL 或 Match ID")

    mid = (url_input or match_id or "").strip()
    if mid and mid.isdigit():
        urls = statshub_urls(mid, tenant=config.STATSHUB_TENANT, lang=config.STATSHUB_LANG)
        st.markdown(
            f"[賽前報告 report]({urls['report']}) · "
            f"[數據 statistics]({urls['statistics']})"
        )
    elif mid and "/" in mid:
        from sportsbet.data.statshub.parser import parse_match_id_from_url

        parsed = parse_match_id_from_url(mid)
        if parsed:
            urls = statshub_urls(parsed, tenant=config.STATSHUB_TENANT, lang=config.STATSHUB_LANG)
            st.markdown(
                f"[賽前報告 report]({urls['report']}) · "
                f"[數據 statistics]({urls['statistics']})"
            )

    summary: dict[str, Any] = {}
    merged: dict[str, Any] = {}
    fetch_errors: list[str] = []
    if payload:
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        merged = payload.get("merged") if isinstance(payload.get("merged"), dict) else {}
        fetch_errors = payload.get("fetch_errors") if isinstance(payload.get("fetch_errors"), list) else []

    if not summary and mid and mid.isdigit():
        try:
            from sportsbet.data.statshub.client import StatsHubClient

            bundle = StatsHubClient(
                tenant=config.STATSHUB_TENANT,
                lang=config.STATSHUB_LANG,
            ).fetch_match_bundle(mid)
            summary = bundle.summary
            if not merged.get("players"):
                merged = bundle.merged
            fetch_errors = bundle.fetch_errors
        except Exception as exc:
            st.caption(f"即時摘要讀取失敗：{exc}")

    if summary:
        home_zh = summary.get("home_team_zh") or home_team
        away_zh = summary.get("away_team_zh") or away_team
        st.caption(
            f"{away_zh} @ {home_zh} · "
            f"{summary.get('match_date', match_date)} · "
            f"{summary.get('status') or '—'} · "
            f"比分 {summary.get('result_away', '—')}–{summary.get('result_home', '—')} · "
            f"{_coverage_caption(summary)}"
        )
        pt = _period_table(summary)
        if not pt.empty:
            st.dataframe(pt, use_container_width=True, hide_index=True)

    players = merged.get("players") or []
    injuries = merged.get("injuries") or []
    lineups = merged.get("lineups") or []
    team_stats = merged.get("team_stats") or []
    feeds_ok = merged.get("feeds_ok") or []

    if fetch_errors and not feeds_ok:
        st.info(
            "Gismo 詳細 feed 無法由伺服器直接存取（origin 限制）。"
            "請在瀏覽器開啟上方連結，或於下方匯入 DevTools 複製的 JSON。"
        )

    tab_inj, tab_lu, tab_pl, tab_ts = st.tabs(["傷兵", "首發陣容", "球員數據", "球隊統計"])

    with tab_inj:
        if injuries:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**{away_team}（客）**")
                df = _injuries_df(injuries, "away")
                st.dataframe(df if not df.empty else pd.DataFrame({"訊息": ["無"]}), hide_index=True)
            with c2:
                st.markdown(f"**{home_team}（主）**")
                df = _injuries_df(injuries, "home")
                st.dataframe(df if not df.empty else pd.DataFrame({"訊息": ["無"]}), hide_index=True)
        else:
            espn_inj = _espn_injuries_for_teams(db, sport, home_team, away_team)
            if not espn_inj.empty:
                st.caption("StatsHub 無傷兵 feed · 以下為 ESPN 資料")
                show_cols = [c for c in ["team", "player_name", "status", "injury_type", "source"] if c in espn_inj.columns]
                st.dataframe(espn_inj[show_cols].head(20), hide_index=True, use_container_width=True)
            else:
                st.caption("尚無傷兵資料（StatsHub / ESPN）")

    with tab_lu:
        if lineups:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**{away_team}（客）**")
                df = _lineups_df(lineups, "away")
                st.dataframe(df if not df.empty else pd.DataFrame({"訊息": ["無"]}), hide_index=True)
            with c2:
                st.markdown(f"**{home_team}（主）**")
                df = _lineups_df(lineups, "home")
                st.dataframe(df if not df.empty else pd.DataFrame({"訊息": ["無"]}), hide_index=True)
        else:
            h_lu, a_lu = _espn_lineups_for_teams(db, sport, home_team, away_team, match_date[:10])
            if not h_lu.empty or not a_lu.empty:
                st.caption("StatsHub 無陣容 feed · 以下為 ESPN 預計上場")
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**{away_team}**")
                    if not a_lu.empty:
                        st.dataframe(a_lu, hide_index=True, use_container_width=True)
                with c2:
                    st.markdown(f"**{home_team}**")
                    if not h_lu.empty:
                        st.dataframe(h_lu, hide_index=True, use_container_width=True)
            else:
                st.caption("尚無首發/預計陣容")

    with tab_pl:
        if players:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**{away_team}（客）**")
                df = _players_df(players, "away")
                st.dataframe(df, hide_index=True, use_container_width=True)
            with c2:
                st.markdown(f"**{home_team}（主）**")
                df = _players_df(players, "home")
                st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.caption("尚無 StatsHub 球員統計（需 Gismo feed 或匯入 JSON）")

    with tab_ts:
        ts_df = _team_stats_df(team_stats)
        if not ts_df.empty:
            st.dataframe(ts_df, hide_index=True, use_container_width=True)
        else:
            st.caption("尚無球隊統計（需 match_stats feed）")

    with st.expander("匯入瀏覽器 Gismo JSON（進階）", expanded=False):
        st.caption(
            "在 Chrome DevTools → Network 篩選 `gismo`，複製 "
            "`match_squads` / `match_playerdetails` / `match_stats` 回應 JSON，"
            "貼成 `{\"match_squads\": {...}, ...}` 格式"
        )
        raw_json = st.text_area("Feeds JSON", key=f"statshub_import_{game_id}", height=120)
        if st.button("匯入並寫入 DB", key=f"statshub_import_btn_{game_id}"):
            try:
                feeds = json.loads(raw_json)
                if not isinstance(feeds, dict):
                    raise ValueError("需為 JSON 物件")
                import_mid = mid if mid and mid.isdigit() else None
                if not import_mid:
                    from sportsbet.data.statshub.parser import parse_match_id_from_url

                    import_mid = parse_match_id_from_url(mid or "")
                if not import_mid:
                    st.error("請先綁定 Match ID")
                else:
                    from sportsbet.data.statshub_sync import import_statshub_feeds_json

                    stats = import_statshub_feeds_json(
                        db, sport, int(game_id), import_mid, feeds,
                    )
                    st.success(
                        f"已匯入 · 球員 {stats.get('players', 0)} · "
                        f"傷兵 {stats.get('injuries', 0)} · 首發 {stats.get('lineups', 0)}"
                    )
                    st.rerun()
            except json.JSONDecodeError:
                st.error("JSON 格式錯誤")
            except Exception as exc:
                st.error(str(exc))

    snap = _compat_get_statshub_snapshot(db, int(game_id))
    if snap and snap.get("synced_at"):
        st.caption(f"快照同步：{snap['synced_at']}")
