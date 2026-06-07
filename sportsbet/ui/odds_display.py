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
    if market == "margin":
        from sportsbet.models.margin_bands import bands_for_sport, margin_band_hit

        for band in bands_for_sport("nba"):
            if band.key == selection:
                return margin_band_hit(band.side, band.lo, band.hi, home_score, away_score)
        if selection.startswith("home_") or selection.startswith("away_"):
            parts = selection.split("_")
            if len(parts) >= 3:
                side = parts[0]
                try:
                    lo = int(parts[1])
                    hi = int(parts[2]) if parts[2] != "plus" else 99
                    return margin_band_hit(side, lo, hi, home_score, away_score)
                except ValueError:
                    pass
    return None


def _pick_with_ev(
    candidates: list[tuple[str, str, float | None, float | None, float | None]],
    *,
    market: str = "spread",
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
                market=market,
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
    spread = _pick_with_ev(spread_candidates, market="spread")
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

    margin: MarketPickView | None = None
    margin_odds = odds.get("margin_odds") or {}
    if margin_f is not None and margin_odds:
        from sportsbet.models.margin_bands import bands_for_sport, best_margin_pick, prob_margin_band

        band_probs = {
            band.key: prob_margin_band(
                band.side, band.lo, band.hi, margin_f, sport=sport, pred_total=total_f,
            )
            for band in bands_for_sport(sport)
        }
        sel_key, prob, ev = best_margin_pick(band_probs, margin_odds, sport=sport, min_ev=-999.0)
        if sel_key and prob is not None:
            band = next(b for b in bands_for_sport(sport) if b.key == sel_key)
            margin = MarketPickView(
                band.label_zh,
                None,
                float(margin_odds[sel_key]),
                prob,
                ev,
                market="margin",
                selection=sel_key,
            )

    if is_final and home_score is not None and away_score is not None:
        hs, aws = int(home_score), int(away_score)
        for pick in (ml, spread, total, margin):
            if pick and pick.market and pick.selection:
                line = pick.line if pick.market != "moneyline" else None
                pick.settled = _bet_settled(pick.market, pick.selection, line, hs, aws)

    return {"moneyline": ml, "spread": spread, "total": total, "margin": margin}


def actual_result_line(
    home_score: int | None,
    away_score: int | None,
    *,
    home_team: str,
    away_team: str,
    sport: str,
) -> str:
    """完賽實際比分與勝方（供覆盤說明）。"""
    if home_score is None or away_score is None:
        return ""
    hs, aws = int(home_score), int(away_score)
    if hs > aws:
        side = "主勝"
    elif aws > hs:
        side = "客勝"
    else:
        side = "平手"
    return f"實際 {aws}–{hs}（{side}）"


def _result_tag(pick: MarketPickView | None) -> str:
    if pick is None or pick.settled is None:
        return ""
    if pick.market == "moneyline":
        ok_txt, miss_txt = "✓ 預測正確", "✗ 預測錯誤"
    else:
        ok_txt, miss_txt = "✓ 過盤", "✗ 未過盤"
    if pick.settled:
        return f"<span class='sq-pred-hit sq-pred-ok'>{ok_txt}</span>"
    return f"<span class='sq-pred-hit sq-pred-miss'>{miss_txt}</span>"


def _ev_class(ev: float | None) -> str:
    if ev is None or pd.isna(ev):
        return ""
    return "sq-pred-ev-pos" if float(ev) > 0 else "sq-pred-ev-neg"


def format_market_pick_html(
    pick: MarketPickView | None,
    *,
    extra_sub: str = "",
    actual_line: str = "",
) -> str:
    """渲染單格玩法：建議、賠率、EV、完賽結果。"""
    if pick is None:
        return "<div class='sq-pred-value'>—</div>"
    odds_txt = f"賠率 {_fmt_odds(pick.odds)}" if pick.odds is not None else "賠率 —"
    prob_txt = f"模型 {_fmt_pct(pick.model_prob)}" if pick.model_prob is not None else ""
    ev_cls = _ev_class(pick.ev)
    ev_txt = f"<span class='{ev_cls}'>EV {_fmt_ev(pick.ev)}</span>" if pick.ev is not None else "EV —"
    sub_parts = [p for p in [odds_txt, prob_txt, ev_txt, extra_sub, actual_line] if p]
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
        "margin_odds": {},
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
        "margin_odds": {
            str(row["selection"]): float(row["odds"])
            for _, row in raw.iterrows()
            if str(row.get("market")) == "margin" and pd.notna(row.get("odds"))
        },
    }


def _margin_odds_html(margin_odds: dict[str, float], sport: str, *, limit: int = 6) -> str:
    if not margin_odds:
        return "<div class='sq-odds-cap'>尚無勝分差盤</div>"
    from sportsbet.models.margin_bands import bands_for_sport

    labels = {b.key: b.label_zh for b in bands_for_sport(sport)}
    lines = []
    for key, o in sorted(margin_odds.items(), key=lambda x: x[1]):
        label = labels.get(key, key)
        lines.append(f"<div class='sq-odds-line'>{label} · <strong>{_fmt_odds(o)}</strong></div>")
        if len(lines) >= limit:
            break
    extra = len(margin_odds) - limit
    if extra > 0:
        lines.append(f"<div class='sq-odds-cap'>另有 {extra} 個區間…</div>")
    return "".join(lines)


def render_bet_recommendations(
    picks: dict[str, MarketPickView | None],
    *,
    min_ev: float | None = None,
) -> None:
    """依 EV 門檻列出各玩法推薦下注。"""
    from sportsbet import config

    threshold = config.MIN_EV_THRESHOLD if min_ev is None else min_ev
    labels = {
        "moneyline": "不讓分（勝負）",
        "spread": "讓分",
        "margin": "勝分差",
        "total": "大小分",
    }
    rows: list[tuple[str, MarketPickView]] = []
    for key, pick in picks.items():
        if pick and pick.ev is not None and pick.odds is not None and pick.ev >= threshold:
            rows.append((labels.get(key, key), pick))
    rows.sort(key=lambda x: float(x[1].ev or 0), reverse=True)

    if not rows:
        st.markdown(
            f"<div class='sq-odds-cap'>尚無 EV ≥ {threshold:.0%} 的推薦（需有盤口賠率）</div>",
            unsafe_allow_html=True,
        )
        return

    body = "".join(
        f"<div class='sq-odds-line'><strong>{label}</strong> · {pick.selection_label} · "
        f"賠率 {_fmt_odds(pick.odds)} · 模型 {_fmt_pct(pick.model_prob)} · "
        f"<span class='{_ev_class(pick.ev)}'>EV {_fmt_ev(pick.ev)}</span></div>"
        for label, pick in rows
    )
    st.markdown(
        f"<div class='sq-rec-panel'><h4>推薦下注（EV ≥ {threshold:.0%}）</h4>{body}</div>",
        unsafe_allow_html=True,
    )


def render_odds_panel(
    db: SportsDatabase,
    fc: GameForecast,
    sport: str,
) -> None:
    """呈現四玩法盤口（不讓分 / 讓分 / 勝分差 / 大小分）與模型推薦。"""
    from sportsbet.models.forecast import forecast_pick_dict

    odds = summarize_game_odds(db, fc.game_id)
    fc_dict = forecast_pick_dict(fc)
    is_final = str(getattr(fc, "status", "") or "").lower() == "final"
    hs = getattr(fc, "home_score", None)
    aws = getattr(fc, "away_score", None)
    picks = build_game_market_picks(
        fc_dict,
        odds,
        sport,
        home_team=fc.home_team,
        away_team=fc.away_team,
        home_score=int(hs) if hs is not None and not pd.isna(hs) else None,
        away_score=int(aws) if aws is not None and not pd.isna(aws) else None,
        is_final=is_final,
    )

    total_label = "大小分" if sport == "nba" else "大小分（總得分）"

    ml_body = (
        f"<div class='sq-odds-line'>主隊 <strong>{_fmt_odds(odds['ml_home'])}</strong></div>"
        f"<div class='sq-odds-line'>客隊 <strong>{_fmt_odds(odds['ml_away'])}</strong></div>"
    )
    if odds["ml_home"] is None and odds["ml_away"] is None:
        ml_body += "<div class='sq-odds-cap'>尚無勝負賠率</div>"
    ml_pick = picks.get("moneyline")
    if ml_pick:
        ml_body += f"<div class='sq-odds-cap'>模型 → {ml_pick.selection_label}</div>"

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
    sp_pick = picks.get("spread")
    if sp_pick and sp_pick.odds is not None:
        sp_body += (
            f"<div class='sq-odds-cap'>推 → {sp_pick.selection_label} · EV {_fmt_ev(sp_pick.ev)}</div>"
        )

    margin_odds = odds.get("margin_odds") or {}
    mg_body = _margin_odds_html(margin_odds, sport)
    if fc.predicted_margin is not None:
        mg_body += f"<div class='sq-odds-cap'>模型預估分差 {fc.predicted_margin:+.1f}</div>"
    mg_pick = picks.get("margin")
    if mg_pick:
        mg_body += (
            f"<div class='sq-odds-cap'>推 → {mg_pick.selection_label} · "
            f"賠率 {_fmt_odds(mg_pick.odds)} · EV {_fmt_ev(mg_pick.ev)}</div>"
        )

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
    tot_pick = picks.get("total")
    if tot_pick and tot_pick.odds is not None:
        tot_body += f"<div class='sq-odds-cap'>推 → {tot_pick.selection_label} · EV {_fmt_ev(tot_pick.ev)}</div>"

    st.markdown(
        f"""
        <div class="sq-odds-panel">
            <h4>盤口分析</h4>
            <div class="sq-odds-grid sq-odds-grid-4">
                <div class="sq-odds-col">
                    <div class="sq-odds-col-title">勝負（不讓分）</div>
                    {ml_body}
                </div>
                <div class="sq-odds-col">
                    <div class="sq-odds-col-title">讓分</div>
                    {sp_body}
                </div>
                <div class="sq-odds-col">
                    <div class="sq-odds-col-title">勝分差</div>
                    {mg_body}
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
    render_bet_recommendations(picks)
