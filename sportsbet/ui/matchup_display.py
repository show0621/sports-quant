"""對戰卡片：日期時間 + 隊徽 + 中英文隊名。"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from sportsbet.data.team_logos import resolve_logo_url
from sportsbet.data.team_names import team_bilingual
from sportsbet.models.forecast import GameForecast


def format_match_datetime(match_datetime: str | None, match_date: str) -> tuple[str, str]:
    """回傳 (日期, 時間) 台灣時區字串。"""
    if not match_datetime or (isinstance(match_datetime, float) and pd.isna(match_datetime)):
        return match_date, "時間待定"

    try:
        dt = pd.to_datetime(match_datetime, utc=True, errors="coerce")
        if pd.isna(dt):
            return match_date, "時間待定"
        local = dt.tz_convert(ZoneInfo("Asia/Taipei"))
        return local.strftime("%Y-%m-%d"), local.strftime("%H:%M") + " (台灣)"
    except Exception:
        return match_date, str(match_datetime)[:16]


def taipei_match_date(match_datetime: str | None, match_date: str) -> str:
    """以台灣日期判定「今日」賽事。"""
    d_str, _ = format_match_datetime(match_datetime, match_date)
    return d_str


def render_season_badges_html(
    season_type: str | None,
    competition_note: str | None,
    *,
    is_live: bool = False,
    status: str | None = None,
) -> str:
    parts: list[str] = []
    if is_live:
        parts.append("<span class='sq-badge sq-badge-live'>LIVE</span>")
    st_val = str(status or "").lower()
    if st_val == "final":
        parts.append("<span class='sq-badge sq-badge-finals'>已完賽</span>")
    elif st_val == "in_progress":
        parts.append("<span class='sq-badge sq-badge-live'>進行中</span>")
    stype = str(season_type or "").strip()
    if stype:
        cls = "sq-badge-reg"
        low = stype.lower()
        if "季後" in stype or "post" in low or "play" in low:
            cls = "sq-badge-post"
        parts.append(f"<span class='sq-badge {cls}'>{stype}</span>")
    note = str(competition_note or "").strip()
    if note:
        cls = "sq-badge-finals" if "冠軍" in note or "final" in note.lower() else "sq-badge-post"
        parts.append(f"<span class='sq-badge {cls}'>{note}</span>")
    return " ".join(parts)


def team_bilingual_html(
    team: str,
    sport: str,
    logo_url: str | None,
    *,
    align: str = "left",
    logo_size: int = 40,
) -> str:
    """Bing Sports 風格：小隊徽 + 英文 + 中文並列。"""
    en, zh = team_bilingual(team, sport)
    logo = ""
    if logo_url:
        logo = (
            f"<img class='sq-team-logo' src='{logo_url}' width='{logo_size}' height='{logo_size}' "
            f"alt='{en}' loading='lazy'/>"
        )
    zh_line = f"<div class='sq-team-zh'>{zh}</div>" if zh else ""
    return (
        f"<div class='sq-team-block' style='text-align:{align}'>"
        f"<div class='sq-team-inline'>{logo}"
        f"<div class='sq-team-text'><div class='sq-team-en'>{en}</div>{zh_line}</div>"
        f"</div></div>"
    )


def render_matchup_header(
    fc: GameForecast,
    *,
    sport: str,
    home_logo_db: str | None = None,
    away_logo_db: str | None = None,
) -> None:
    """渲染隊徽 + 中英文隊名 + 日期時間。"""
    date_str, time_str = format_match_datetime(fc.match_datetime, fc.match_date)
    home_logo = resolve_logo_url(fc.home_team, sport, db_url=home_logo_db)  # type: ignore[arg-type]
    away_logo = resolve_logo_url(fc.away_team, sport, db_url=away_logo_db)  # type: ignore[arg-type]
    badges = render_season_badges_html(
        getattr(fc, "season_type", None),
        getattr(fc, "competition_note", None),
        is_live=str(getattr(fc, "status", "") or "").lower() == "in_progress",
        status=getattr(fc, "status", None),
    )

    score_html = ""
    if fc.actual_home_score is not None and fc.actual_away_score is not None:
        score_html = (
            f"<div class='sq-score'>{fc.actual_home_score} – {fc.actual_away_score}</div>"
            f"<div class='sq-clock'>實際比分</div>"
        )
        if fc.pick_correct is not None:
            mark = "✓ 預測正確" if fc.pick_correct else "✗ 預測錯誤"
            score_html += f"<div class='sq-clock'>{mark}</div>"

    left, center, right = st.columns([1.15, 1.7, 1.15])

    with left:
        st.markdown(team_bilingual_html(fc.home_team, sport, home_logo, align="left"), unsafe_allow_html=True)
        st.caption("主場")

    with center:
        if badges:
            st.markdown(badges, unsafe_allow_html=True)
        st.markdown(f"##### {date_str}")
        st.markdown(f"**{time_str}**")
        if score_html:
            st.markdown(score_html, unsafe_allow_html=True)
        else:
            st.markdown("##### VS")
            st.markdown(f"預估比分 {fc.predicted_home_score:.0f} – {fc.predicted_away_score:.0f}")
        st.markdown(f"預測勝者：**{fc.predicted_winner}**")

    with right:
        st.markdown(team_bilingual_html(fc.away_team, sport, away_logo, align="right"), unsafe_allow_html=True)
        st.caption("客場")

    st.divider()
