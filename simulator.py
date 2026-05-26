"""
Streamlit 互動式模擬器：測試畢達哥拉斯、貝氏修正、威剛高抽水下的 EV 與 ROI。

啟動：streamlit run simulator.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsbet import analytics, config  # noqa: E402

st.set_page_config(page_title="運彩量化模擬器", layout="wide")
st.title("NBA / MLB 運彩量化模擬器")
st.caption("畢達哥拉斯 · 貝氏修正 · 期望值 · 凱利公式 · 台灣運彩高抽水")

col1, col2 = st.columns(2)

with col1:
    sport = st.selectbox("運動", ["nba", "mlb"])
    home_rs = st.number_input("主隊场均得分", value=112.0, min_value=50.0)
    home_ra = st.number_input("主隊场均失分", value=108.0, min_value=50.0)
    away_rs = st.number_input("客隊场均得分", value=110.0, min_value=50.0)
    away_ra = st.number_input("客隊场均失分", value=111.0, min_value=50.0)
    recent_home = st.slider("主隊近5場勝率", 0.0, 1.0, 0.6)
    recent_away = st.slider("客隊近5場勝率", 0.0, 1.0, 0.5)
    injury_home = st.checkbox("主隊核心缺陣")
    injury_away = st.checkbox("客隊核心缺陣")

with col2:
    odds_home = st.number_input("主隊賠率（含本金）", value=1.75, min_value=1.01, step=0.05)
    odds_away = st.number_input("客隊賠率（含本金）", value=1.75, min_value=1.01, step=0.05)
    bayes_weight = st.slider("貝氏近況權重", 0.0, 1.0, config.BAYES_RECENT_WEIGHT)
    kelly_frac = st.slider("凱利倍數（0.25=四分之一凱利）", 0.05, 1.0, config.KELLY_FRACTION)
    min_ev = st.number_input("最低 EV 門檻", value=config.MIN_EV_THRESHOLD, format="%.3f")

home_pyth = analytics.team_win_pct(sport, home_rs, home_ra)
away_pyth = analytics.team_win_pct(sport, away_rs, away_ra)
p_home, p_away = analytics.matchup_win_prob(home_pyth, away_pyth)

# 暫時覆寫近況權重
import sportsbet.config as cfg  # noqa: E402

_orig = cfg.BAYES_RECENT_WEIGHT
cfg.BAYES_RECENT_WEIGHT = bayes_weight

p_home = analytics.apply_bayesian_adjustments(
    p_home, is_home=True, recent_win_pct=recent_home, season_win_pct=home_pyth, key_player_out=injury_home
)
p_away = analytics.apply_bayesian_adjustments(
    p_away, recent_win_pct=recent_away, season_win_pct=away_pyth, key_player_out=injury_away
)
total = p_home + p_away
p_home, p_away = p_home / total, p_away / total
cfg.BAYES_RECENT_WEIGHT = _orig

sig_h = analytics.evaluate_bet(p_home, odds_home, min_ev)
sig_a = analytics.evaluate_bet(p_away, odds_away, min_ev)

st.subheader("模型輸出")
m1, m2, m3, m4 = st.columns(4)
m1.metric("主隊畢氏勝率", f"{home_pyth:.1%}")
m2.metric("主隊後驗勝率", f"{p_home:.1%}")
m3.metric("主隊 EV", f"{sig_h.ev:.2%}", delta="正 EV" if sig_h.is_positive_ev else None)
m4.metric("主隊建議倉位", f"{analytics.adjusted_kelly(p_home, odds_home, kelly_frac):.2%}")

m5, m6, m7, m8 = st.columns(4)
m5.metric("客隊畢氏勝率", f"{away_pyth:.1%}")
m6.metric("客隊後驗勝率", f"{p_away:.1%}")
m7.metric("客隊 EV", f"{sig_a.ev:.2%}")
m8.metric("客隊建議倉位", f"{analytics.adjusted_kelly(p_away, odds_away, kelly_frac):.2%}")

st.subheader("台灣運彩抽水現實")
vig = analytics.implied_vig(odds_home, odds_away)
be = analytics.taiwan_break_even_note(odds_home)
st.write(
    f"- 雙邊賠率隱含 overround（抽水）：**{vig:.2%}**（返還率約 **{1-vig:.1%}**）\n"
    f"- 賠率 {odds_home} 時，盈虧平衡勝率需 ≥ **{be['breakeven_pct']:.1f}%**"
)

st.subheader("串關模擬（威剛強制 2 關）")
parlay_odds = st.number_input("串關總賠率", value=3.0, min_value=1.01)
p2 = st.slider("第二場模型勝率", 0.3, 0.8, 0.55)
parlay = analytics.evaluate_parlay([p_home, p2], parlay_odds, min_ev)
st.write(f"組合勝率 {parlay.combined_prob:.1%} | 串關 EV {parlay.ev:.2%} | 建議倉位 {parlay.recommended_stake_fraction:.2%}")

st.subheader("長期 ROI 粗估（模擬 1000 注）")
n_sims = 1000
import numpy as np  # noqa: E402

rng = np.random.default_rng(42)
bet_prob = p_home if sig_h.is_positive_ev else (p_away if sig_a.is_positive_ev else None)
bet_odds = odds_home if sig_h.is_positive_ev else (odds_away if sig_a.is_positive_ev else None)
if bet_prob and bet_odds:
    stake_f = analytics.adjusted_kelly(bet_prob, bet_odds, kelly_frac)
    bankroll = config.INITIAL_BANKROLL
    for _ in range(n_sims):
        won = rng.random() < bet_prob
        stake = bankroll * stake_f
        bankroll += stake * (bet_odds - 1) if won else -stake
    st.metric("模擬終值（起始 10 萬）", f"${bankroll:,.0f}")
else:
    st.info("目前無正 EV 訊號，不進行模擬下注。")
