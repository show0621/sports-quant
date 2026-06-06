"""賽事預測卡片：盤口（大小分、讓分、勝負賠率）呈現。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import streamlit as st

from sportsbet import analytics
from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_names import team_bilingual
from sportsbet.models.forecast import GameForecast
from sportsbet.models.totals import prob_away_covers_spread, prob_home_covers_spread


def _latest_odds_by_key(odds_df: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    if odds_df.empty:
        return {}
    df = odds_df.sort_values("id")
    out: dict[tuple[str, str], pd.Series] = {}
    for _, row in df.iterrows():
        out[(str(row["market"]), str(row["selection"]))] = row
    return out


def _fmt_odds(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v):.2f}"


def _fmt_ev(ev: float | None) -> str:
    if ev is None or (isinstance(ev, float) and pd.isna(ev)):
        return "—"
    pct = float(ev) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _fmt_pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v) * 100:.1f}%"


@dataclass
class MarketPickView:
    """單一玩法模型建議（含賠率、EV、完賽結果）。"""

    selection_label: str
    line: float | None
    odds: float | None
    model_prob: float | None
    ev: float | None
    market: str | None = None
    selection: str | None = None
    settled: bool | None = None


def _bet_settled(
    market: str,
    selection: str,
    handicap: float | None,
    home_score: int,
    away_score: int,
) -> bool | None:
    """1=過盤 / 0=未過；平手或無法判定回傳 None。"""
    margin = home_score - away_score
    total = home_score + away_score
    if market == "moneyline":
        if selection == "home":
            if margin > 0:
                return True
            if margin < 0:
                return False
            return None
        if selection == "away":
            if margin < 0:
                return True
            if margin > 0:
                return False
            return None
    if market == "spread" and handicap is not None:
        if selection == "home":
            adj = home_score + handicap - away_score
            if adj > 0:
                return True
            if adj < 0:
                return False
            return None
        if selection == "away":
            adj = away_score + handicap - home_score
            if adj > 0:
                return True
            if adj < 0:
                return False
            return None
    if market == "total" and handicap is not None:
        if selection == "over":
            if total > handicap:
                return True
            if total < handicap:
                return False
            return None
        if selection == "under":
            if total < handicap:
                return True
            if total > handicap:
                return False
            return None
    return None


def _pick_with_ev(
    candidates: list[tuple[str, str, float | None, float | None, float | None]],
) -> MarketPickView | None:
    """從 (selection, label, line, odds, prob) 候選中取 EV 最高者。"""
    best: MarketPickView | None = None
    best_ev = float("-inf")
    for selection, label, line, odds, prob in candidates:
        if prob is None or odds is None or pd.isna(prob) or pd.isna(odds):
            continue
        ev = analytics.expected_value(float(prob), float(odds))
        if best is None or ev > best_ev:
            best_ev = ev
            best = MarketPickView(
                selection_label=label,
                line=line,
                odds=float(odds),
                model_prob=float(prob),
                ev=ev,
                market="spread",
                selection=selection,
            )
    return best


def build_game_market_picks(
    fc: dict[str, Any],
    odds: dict[str, object],
    sport: str,
    *,
    home_team: str,
    away_team: str,
    home_score: int | None = None,
    away_score: int | None = None,
    is_final: bool = False,
) -> dict[str, MarketPickView | None]:
    """依模型預測與盤口，產生勝負 / 讓分 / 大小分建議與 EV。"""
    pred_margin = fc.get("predicted_margin")
    pred_total = fc.get("predicted_total")
    margin_f = float(pred_margin) if pred_margin is not None and not pd.isna(pred_margin) else None
    total_f = float(pred_total) if pred_total is not None and not pd.isna(pred_total) else None

    winner = str(fc.get("predicted_winner") or "")
    home_prob = fc.get("home_win_prob")
    away_prob = fc.get("away_win_prob")

    ml: MarketPickView | None = None
    if winner == home_team and home_prob is not None:
        prob, sel_odds = float(home_prob), odds.get("ml_home")
        h_en, h_zh = team_bilingual(home_team, sport)
        label = f"主 {h_en}" + (f" / {h_zh}" if h_zh else "")
        ml = MarketPickView(
            label, None, float(sel_odds) if sel_odds else None, prob, None,
            market="moneyline", selection="home",
        )
    elif winner == away_team and away_prob is not None:
        prob, sel_odds = float(away_prob), odds.get("ml_away")
        a_en, a_zh = team_bilingual(away_team, sport)
        label = f"客 {a_en}" + (f" / {a_zh}" if a_zh else "")
        ml = MarketPickView(
            label, None, float(sel_odds) if sel_odds else None, prob, None,
            market="moneyline", selection="away",
        )
    if ml and ml.odds is not None and ml.model_prob is not None:
        ml.ev = analytics.expected_value(ml.model_prob, ml.odds)

    spread_candidates: list[tuple[str, str, float | None, float | None, float | None]] = []
    sp_h_line, sp_a_line = odds.get("spread_home_line"), odds.get("spread_away_line")
    if margin_f is not None and sp_h_line is not None and not pd.isna(sp_h_line):
        h_line = float(sp_h_line)
        prob = prob_home_covers_spread(h_line, margin_f, sport=sport, pred_total=total_f)
        h_en, _ = team_bilingual(home_team, sport)
        spread_candidates.append(
            ("home", f"主 {h_en} {h_line:+.1f}", h_line, odds.get("spread_home_odds"), prob),
        )
    if margin_f is not None and sp_a_line is not None and not pd.isna(sp_a_line):
        a_line = float(sp_a_line)
        prob = prob_away_covers_spread(a_line, margin_f, sport=sport, pred_total=total_f)
        a_en, _ = team_bilingual(away_team, sport)
        spread_candidates.append(
            ("away", f"客 {a_en} {a_line:+.1f}", a_line, odds.get("spread_away_odds"), prob),
        )
    spread = _pick_with_ev(spread_candidates)
    if spread is None and margin_f is not None:
        m = margin_f
        if m > 0:
            h_en, h_zh = team_bilingual(home_team, sport)
            spread = MarketPickView(
                f"主隊淨勝 {m:+.1f}" + (f"（{h_zh}）" if h_zh else ""),
                sp_h_line if sp_h_line is not None else None,
                None,
                None,
                None,
            )
        elif m < 0:
            a_en, a_zh = team_bilingual(away_team, sport)
            spread = MarketPickView(
                f"客隊淨勝 {-m:.1f}" + (f"（{a_zh}）" if a_zh else ""),
                sp_a_line if sp_a_line is not None else None,
                None,
                None,
                None,
            )
        else:
            spread = MarketPickView("平手", None, None, None, None)

    prob_over = fc.get("prob_over")
    prob_under = fc.get("prob_under")
    total_line = odds.get("total_line") if odds.get("total_line") is not None else fc.get("total_line")
    total: MarketPickView | None = None
    if prob_over is not None and not pd.isna(prob_over):
        po, pu = float(prob_over), float(prob_under) if prob_under is not None and not pd.isna(prob_under) else 1.0 - float(prob_over)
        line_f = float(total_line) if total_line is not None and not pd.isna(total_line) else None
        if po >= pu:
            total = MarketPickView(
                f"大 {line_f:.1f}" if line_f is not None else "大",
                line_f,
                float(odds["over_odds"]) if odds.get("over_odds") is not None else None,
                po,
                None,
                market="total",
                selection="over",
            )
        else:
            total = MarketPickView(
                f"小 {line_f:.1f}" if line_f is not None else "小",
                line_f,
                float(odds["under_odds"]) if odds.get("under_odds") is not None else None,
                pu,
                None,
                market="total",
                selection="under",
            )
        if total.odds is not None and total.model_prob is not None:
            total.ev = analytics.expected_value(total.model_prob, total.odds)
        if total_f is not None:
            total.selection_label += f" · 預估 {total_f:.1f}"

    if is_final and home_score is not None and away_score is not None:
        hs, aws = int(home_score), int(away_score)
        for pick in (ml, spread, total):
            if pick and pick.market and pick.selection:
                line = pick.line if pick.market != "moneyline" else None
                pick.settled = _bet_settled(pick.market, pick.selection, line, hs, aws)

    return {"moneyline": ml, "spread": spread, "total": total}


def _result_tag(pick: MarketPickView | None) -> str:
    if pick is None or pick.settled is None:
        return ""
    if pick.settled:
        return "<span class='sq-pred-hit sq-pred-ok'>✓ 過盤</span>"
    return "<span class='sq-pred-hit sq-pred-miss'>✗ 未過</span>"


def _ev_class(ev: float | None) -> str:
    if ev is None or pd.isna(ev):
        return ""
    return "sq-pred-ev-pos" if float(ev) > 0 else "sq-pred-ev-neg"


def format_market_pick_html(pick: MarketPickView | None, *, extra_sub: str = "") -> str:
    """渲染單格玩法：建議、賠率、EV、完賽結果。"""
    if pick is None:
        return "<div class='sq-pred-value'>—</div>"
    odds_txt = f"賠率 {_fmt_odds(pick.odds)}" if pick.odds is not None else "賠率 —"
    prob_txt = f"模型 {_fmt_pct(pick.model_prob)}" if pick.model_prob is not None else ""
    ev_cls = _ev_class(pick.ev)
    ev_txt = f"<span class='{ev_cls}'>EV {_fmt_ev(pick.ev)}</span>" if pick.ev is not None else "EV —"
    sub_parts = [p for p in [odds_txt, prob_txt, ev_txt, extra_sub] if p]
    sub = " · ".join(sub_parts)
    result = _result_tag(pick)
    result_html = f"<div class='sq-pred-result'>{result}</div>" if result else ""
    return (
        f"<div class='sq-pred-value'>{pick.selection_label}</div>"
        f"<div class='sq-pred-sub'>{sub}</div>"
        f"{result_html}"
    )


def summarize_game_odds(db: SportsDatabase, game_id: int | None) -> dict[str, object]:
    """取該場最新盤口摘要。"""
    empty: dict[str, object] = {
        "ml_home": None,
        "ml_away": None,
        "spread_home_line": None,
        "spread_away_line": None,
        "spread_home_odds": None,
        "spread_away_odds": None,
        "total_line": None,
        "over_odds": None,
        "under_odds": None,
    }
    if not game_id:
        return empty

    raw = db.get_game_odds(int(game_id))
    if raw.empty:
        return empty

    by = _latest_odds_by_key(raw)

    ml_h = by.get(("moneyline", "home"))
    ml_a = by.get(("moneyline", "away"))
    sp_h = by.get(("spread", "home"))
    sp_a = by.get(("spread", "away"))
    ov = by.get(("total", "over"))
    un = by.get(("total", "under"))

    total_line = None
    if ov is not None and pd.notna(ov.get("handicap")):
        total_line = float(ov["handicap"])
    elif un is not None and pd.notna(un.get("handicap")):
        total_line = float(un["handicap"])

    spread_home_line = float(sp_h["handicap"]) if sp_h is not None and pd.notna(sp_h.get("handicap")) else None
    spread_away_line = float(sp_a["handicap"]) if sp_a is not None and pd.notna(sp_a.get("handicap")) else None

    return {
        "ml_home": float(ml_h["odds"]) if ml_h is not None else None,
        "ml_away": float(ml_a["odds"]) if ml_a is not None else None,
        "spread_home_line": spread_home_line,
        "spread_away_line": spread_away_line,
        "spread_home_odds": float(sp_h["odds"]) if sp_h is not None else None,
        "spread_away_odds": float(sp_a["odds"]) if sp_a is not None else None,
        "total_line": total_line,
        "over_odds": float(ov["odds"]) if ov is not None else None,
        "under_odds": float(un["odds"]) if un is not None else None,
    }


def render_odds_panel(
    db: SportsDatabase,
    fc: GameForecast,
    sport: str,
) -> None:
    """清楚呈現大小分、讓分（勝分差）、主客勝負賠率。"""
    odds = summarize_game_odds(db, fc.game_id)
    total_label = "大小分" if sport == "nba" else "大小分（總得分）"
    spread_label = "讓分（勝分差）"

    ml_body = (
        f"<div class='sq-odds-line'>主隊 <strong>{_fmt_odds(odds['ml_home'])}</strong></div>"
        f"<div class='sq-odds-line'>客隊 <strong>{_fmt_odds(odds['ml_away'])}</strong></div>"
    )
    if odds["ml_home"] is None and odds["ml_away"] is None:
        ml_body += "<div class='sq-odds-cap'>尚無勝負賠率</div>"

    sp_parts = []
    if odds["spread_home_line"] is not None:
        sp_parts.append(
            f"主 {odds['spread_home_line']:+.1f} · {_fmt_odds(odds['spread_home_odds'])}"
        )
    if odds["spread_away_line"] is not None:
        sp_parts.append(
            f"客 {odds['spread_away_line']:+.1f} · {_fmt_odds(odds['spread_away_odds'])}"
        )
    sp_body = "".join(f"<div class='sq-odds-line'>{p}</div>" for p in sp_parts)
    if not sp_parts:
        sp_body = "<div class='sq-odds-cap'>尚無讓分盤</div>"
    elif fc.predicted_margin is not None:
        sp_body += f"<div class='sq-odds-cap'>模型預估分差 {fc.predicted_margin:+.1f}</div>"

    line = odds["total_line"] if odds["total_line"] is not None else fc.total_line
    if line is not None:
        under = fc.prob_under if fc.prob_under is not None else (
            (1.0 - fc.prob_over) if fc.prob_over is not None else None
        )
        tot_body = (
            f"<div class='sq-odds-line'>盤口線 <strong>{float(line):.1f}</strong></div>"
            f"<div class='sq-odds-line'>大 {_fmt_odds(odds['over_odds'])} · 小 {_fmt_odds(odds['under_odds'])}</div>"
        )
        if fc.prob_over is not None and under is not None:
            tot_body += (
                f"<div class='sq-odds-cap'>模型 大 {fc.prob_over * 100:.1f}% · 小 {under * 100:.1f}%</div>"
            )
    else:
        tot_body = "<div class='sq-odds-cap'>尚無大小分盤</div>"
        if fc.predicted_total is not None:
            tot_body += f"<div class='sq-odds-cap'>模型預估總分 {fc.predicted_total:.1f}</div>"

    st.markdown(
        f"""
        <div class="sq-odds-panel">
            <h4>盤口分析</h4>
            <div class="sq-odds-grid">
                <div class="sq-odds-col">
                    <div class="sq-odds-col-title">勝負（不讓分）</div>
                    {ml_body}
                </div>
                <div class="sq-odds-col">
                    <div class="sq-odds-col-title">{spread_label}</div>
                    {sp_body}
                </div>
                <div class="sq-odds-col">
                    <div class="sq-odds-col-title">{total_label}</div>
                    {tot_body}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
