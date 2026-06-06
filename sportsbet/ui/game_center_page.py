"""單場賽事詳情（Bing Sports Game Center 風格 + AI PK）。"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_logos import resolve_logo_url
from sportsbet.models.forecast import GameForecast, game_forecast_from_db_row, team_rating_panel_html
from sportsbet.ui.matchup_display import (
    format_match_datetime,
    render_season_badges_html,
    team_bilingual_html,
)


def _pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v) * 100:.1f}%"


def _load_game(db: SportsDatabase, game_id: int) -> pd.Series | None:
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT g.*, f.home_win_prob, f.away_win_prob, f.predicted_home_score,
                   f.predicted_away_score, f.predicted_total, f.predicted_margin,
                   f.predicted_winner, f.prob_over, f.prob_under, f.total_line,
                   f.margin_note
            FROM games g
            LEFT JOIN game_forecasts f ON f.game_id = g.id
            WHERE g.id = ?
            """,
            (int(game_id),),
        ).fetchone()
    return pd.Series(dict(row)) if row else None


def _quarter_table_html(
    away: str,
    home: str,
    away_logo: str,
    home_logo: str,
    qs: pd.Series | None,
    *,
    away_score: int | None,
    home_score: int | None,
    sport: str,
) -> str:
    headers = ["1", "2", "3", "4", "T"] if sport == "nba" else ["1", "2", "3", "4", "5", "T"]
    n_q = 4 if sport == "nba" else 5

    def _row(team: str, logo: str, prefix: str, total: int | None) -> str:
        cells = []
        for i in range(1, n_q + 1):
            v = qs.get(f"{prefix}_q{i}") if qs is not None else None
            cells.append(str(int(v)) if v is not None and pd.notna(v) else "—")
        t = str(total) if total is not None else "—"
        return (
            f"<tr><td><img src='{logo}' width='18' height='18' style='vertical-align:middle;margin-right:6px'>"
            f"{team}</td>"
            + "".join(f"<td>{c}</td>" for c in cells)
            + f"<td><b>{t}</b></td></tr>"
        )

    hdr = "".join(f"<th>{h}</th>" for h in headers)
    body = _row(away, away_logo, "away", away_score) + _row(home, home_logo, "home", home_score)
    return (
        f"<table class='sq-quarter-table'><thead><tr><th>球隊</th>{hdr}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _leader_card(title: str, row: pd.Series | None) -> str:
    if row is None or row.empty:
        return f"<div class='sq-leader'><div class='sq-leader-cat'>{title}</div><div>—</div></div>"
    name = str(row.get("player_name") or "—")
    pts = row.get("points")
    reb = row.get("rebounds")
    ast = row.get("assists")
    return (
        f"<div class='sq-leader'><div class='sq-leader-cat'>{title}</div>"
        f"<div class='sq-leader-name'>{name}</div>"
        f"<div class='sq-leader-stat'>Pts {pts or 0} · Reb {reb or 0} · Ast {ast or 0}</div></div>"
    )


def _team_totals(stats: pd.DataFrame, team: str) -> dict[str, float]:
    d = stats[stats["team"] == team]
    if d.empty:
        return {}
    return {
        "得分": float(d["points"].fillna(0).sum()),
        "籃板": float(d["rebounds"].fillna(0).sum()),
        "助攻": float(d["assists"].fillna(0).sum()),
        "抄截": float(d["steals"].fillna(0).sum()),
        "阻攻": float(d["blocks"].fillna(0).sum()),
        "失誤": float(d["turnovers"].fillna(0).sum()),
    }


def render_game_center(
    db: SportsDatabase,
    sport: str,
    game_id: int,
    *,
    on_close: str | None = None,
) -> None:
    """渲染單場詳情；on_close 為 session_state key，設 None 可關閉。"""
    g = _load_game(db, game_id)
    if g is None or g.empty:
        st.warning("找不到此場賽事。")
        return

    if on_close and st.button("← 返回列表", key=f"gc_close_{game_id}"):
        st.session_state.pop(on_close, None)
        st.rerun()

    home, away = str(g["home_team"]), str(g["away_team"])
    status = str(g.get("status") or "scheduled")
    hs = int(g["home_score"]) if pd.notna(g.get("home_score")) else None
    aws = int(g["away_score"]) if pd.notna(g.get("away_score")) else None
    d_str, t_str = format_match_datetime(g.get("match_datetime"), str(g["match_date"]))

    home_logo = resolve_logo_url(home, sport, db_url=g.get("home_logo_url"))
    away_logo = resolve_logo_url(away, sport, db_url=g.get("away_logo_url"))
    badges = render_season_badges_html(
        g.get("season_type"), g.get("competition_note"), status=status,
    )

    score_mid = f"{aws} – {hs}" if hs is not None and aws is not None else "VS"
    st.markdown(
        f"<div class='sq-game-center-header'>{badges}"
        f"<div class='sq-gc-meta'>{d_str} {t_str}</div>"
        f"<div class='sq-gc-matchup'>"
        f"<div class='sq-gc-team'>{team_bilingual_html(away, sport, away_logo, align='left', logo_size=48)}</div>"
        f"<div class='sq-gc-score'>{score_mid}</div>"
        f"<div class='sq-gc-team'>{team_bilingual_html(home, sport, home_logo, align='right', logo_size=48)}</div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    qs = db.get_game_quarter_scores(game_id)
    st.markdown("#### 逐節比分")
    st.markdown(
        _quarter_table_html(away, home, away_logo, home_logo, qs, away_score=aws, home_score=hs, sport=sport),
        unsafe_allow_html=True,
    )

    fc = None
    fc_row = db.get_game_forecast_row(game_id) if hasattr(db, "get_game_forecast_row") else None
    if fc_row is not None and not (hasattr(fc_row, "empty") and fc_row.empty):
        try:
            fc = game_forecast_from_db_row(fc_row, g)
        except Exception:
            fc = None
    elif pd.notna(g.get("home_win_prob")):
        try:
            fc = game_forecast_from_db_row(g, g)
        except Exception:
            fc = None

    st.markdown("#### AI 預測（PK）")
    if fc:
        winner = fc.predicted_winner or (home if fc.home_win_prob >= fc.away_win_prob else away)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("預測勝者", winner)
        c2.metric("主勝機率", _pct(fc.home_win_prob))
        c3.metric("客勝機率", _pct(fc.away_win_prob))
        if fc.predicted_home_score and fc.predicted_away_score:
            c4.metric("預估比分", f"{int(fc.predicted_away_score)}–{int(fc.predicted_home_score)}")
        if fc.prob_over is not None:
            st.caption(
                f"大小{'分' if sport == 'nba' else ''} · 大 {_pct(fc.prob_over)} · 小 {_pct(fc.prob_under)}"
                + (f" · 盤口線 {fc.total_line}" if fc.total_line else "")
            )
        st.markdown(team_rating_panel_html(fc, sport), unsafe_allow_html=True)
    else:
        st.info("尚無 AI 預測，請執行完整同步。")

    stats = db.get_player_game_stats(game_id)
    st.markdown("#### 比賽領先者")
    if stats.empty and status == "final":
        if st.button("從 ESPN 同步本場 box score", key=f"sync_box_{game_id}"):
            from sportsbet.data.espn_boxscore import EspnBoxScoreClient

            n = EspnBoxScoreClient().sync_game_box_score(db, sport, g.to_dict())  # type: ignore[arg-type]
            if n:
                st.success(f"已同步 {n} 位球員")
                st.rerun()
            else:
                st.warning("同步失敗或 ESPN 尚無資料。")
        st.caption("資料來源：ESPN（與 Bing 相同類型的公開賽事 API，非付費 API-Sports）")
    elif not stats.empty:
        for team, label in [(away, "客隊"), (home, "主隊")]:
            td = stats[stats["team"] == team]
            st.markdown(f"**{label} · {team}**")
            lc1, lc2, lc3 = st.columns(3)
            with lc1:
                st.markdown("**得分**")
                top = td.sort_values("points", ascending=False).head(1)
                if not top.empty:
                    r = top.iloc[0]
                    st.write(f"{r['player_name']} — {int(r['points'] or 0)} 分")
            with lc2:
                st.markdown("**籃板**")
                top = td.sort_values("rebounds", ascending=False).head(1)
                if not top.empty:
                    r = top.iloc[0]
                    st.write(f"{r['player_name']} — {int(r['rebounds'] or 0)}")
            with lc3:
                st.markdown("**助攻**")
                top = td.sort_values("assists", ascending=False).head(1)
                if not top.empty:
                    r = top.iloc[0]
                    st.write(f"{r['player_name']} — {int(r['assists'] or 0)}")

        st.markdown("#### 技術統計（全隊）")
        rows = []
        for team, label in [(away, away), (home, home)]:
            tot = _team_totals(stats, team)
            if tot:
                tot["球隊"] = label
                rows.append(tot)
        if rows:
            st.dataframe(pd.DataFrame(rows).set_index("球隊"), use_container_width=True)

        with st.expander("球員 box score"):
            show = stats[
                ["player_name", "team", "minutes", "points", "rebounds", "assists", "threes", "steals", "blocks", "turnovers"]
            ].copy()
            st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.caption("賽前尚無 box score；完賽後可同步或等 watch 自動更新。")
