"""Streamlit：全玩法 EV 優化 / 對沖 / 串關（DB 盤口自動載入）。"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from sportsbet import analytics, config
from sportsbet.data.database import SportsDatabase
from sportsbet.models.margin_bands import bands_for_sport
from sportsbet.optimization.db_loader import LoadedGame, load_games_from_db, list_upcoming_with_odds_status
from sportsbet.optimization.parlay_engine import MatchParlayOptions, ParlayLeg, ParlaySystemOptimizer
from sportsbet.optimization.universal_sport_optimizer import UniversalSportOptimizer
from sportsbet.services.prediction_service import PredictionService
from sportsbet.ui.odds_display import _fmt_ev, _fmt_odds


def _build_match_parlay_options(
    loaded: LoadedGame,
    optimizer: UniversalSportOptimizer,
    matrix,
    total_stake: float,
) -> MatchParlayOptions:
    best, hedges = optimizer.find_best_single_bet(matrix, loaded.game_input, total_stake=total_stake)
    legs: list[ParlayLeg] = []
    if best:
        legs.append(
            ParlayLeg(
                match_label=loaded.game_input.label,
                market=best.market,
                selection_label=f"{best.title}:{best.selection}",
                prob=best.prob,
                odds=best.odds,
            )
        )
    for h in hedges[:1]:
        for lbl, _stake, odds in h.stake_allocations[:2]:
            legs.append(
                ParlayLeg(
                    match_label=loaded.game_input.label,
                    market="hedge",
                    selection_label=lbl,
                    prob=h.combined_hit_prob / max(len(h.stake_allocations), 1),
                    odds=odds,
                )
            )
    return MatchParlayOptions(match_label=loaded.game_input.label, legs=legs)


def page_bet_optimizer(db: SportsDatabase, sport: str, svc: PredictionService) -> None:
    st.subheader("EV 優化 · 對沖 · 串關")
    st.caption(
        "自動讀取 DB `get_preferred_game_odds`（sportslottery > playsport）"
        " + 模型預測，執行 MC 全玩法 EV 優化。"
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        days_ahead = st.number_input("前瞻天數", min_value=0, max_value=14, value=7, step=1)
    with c2:
        total_stake = st.number_input("總注碼（元）", min_value=10.0, value=100.0, step=10.0)
    with c3:
        min_ev = st.slider("最低 EV", min_value=0.0, max_value=0.20, value=float(config.MIN_EV_THRESHOLD), step=0.01)
    with c4:
        n_sim = st.selectbox("MC 次數", [5_000, 10_000, 20_000], index=2)

    status_rows = list_upcoming_with_odds_status(db, sport, days_ahead=int(days_ahead), svc=svc)
    if not status_rows:
        st.info("目前無前瞻賽事。請先執行「完整同步」或 `python main.py sync --mode daily`。")
        return

    df_status = pd.DataFrame(status_rows)
    st.markdown("**賽程與盤口狀態**")
    st.dataframe(
        df_status.assign(
            盤口完整=df_status["has_core_odds"].map({True: "✓", False: "—"}),
            來源=df_status["bookmakers"].map(lambda x: ", ".join(x) if x else "—"),
        )[["match_date", "label", "盤口完整", "margin_count", "來源", "home_win_prob", "predicted_winner"]],
        use_container_width=True,
        hide_index=True,
    )

    ready_ids = [int(r["game_id"]) for r in status_rows if r.get("has_core_odds")]
    if not ready_ids:
        st.warning("尚無具完整核心盤口（不讓分/讓分/大小）的賽事。請同步台灣運彩盤口後再試。")
        return

    options = {int(r["game_id"]): str(r["label"]) for r in status_rows if int(r["game_id"]) in ready_ids}
    selected = st.multiselect(
        "選擇要優化的賽事（可多選串關）",
        options=list(options.keys()),
        default=list(options.keys())[: min(3, len(options))],
        format_func=lambda gid: options.get(gid, str(gid)),
    )

    run = st.button("執行 EV 優化", type="primary")
    if not run:
        return
    if not selected:
        st.warning("請至少選擇一場賽事。")
        return

    with st.spinner("MC 模擬與 EV 計算中…"):
        optimizer = UniversalSportOptimizer(n_simulations=int(n_sim), min_ev=float(min_ev))
        parlay_opt = ParlaySystemOptimizer(min_ev=float(min_ev))
        loaded = load_games_from_db(
            db,
            sport,
            days_ahead=int(days_ahead),
            game_ids=selected,
            svc=svc,
        )

        if not loaded:
            st.error("所選賽事無法載入完整盤口。")
            return

        match_options: list[MatchParlayOptions] = []
        for item in loaded:
            matrix = optimizer.build_probability_matrix(item.game_input)
            best, hedges = optimizer.find_best_single_bet(
                matrix, item.game_input, total_stake=float(total_stake),
            )

            st.markdown(f"### {item.game_input.label}")
            bm = ", ".join(item.odds_meta.get("bookmakers") or []) or "—"
            st.caption(f"game_id={item.game_id} · 盤口來源：{bm} · 模型看好 {item.forecast.predicted_winner}")

            prob_cols = st.columns(4)
            prob_cols[0].metric("主勝", f"{matrix.moneyline_home:.1%}")
            prob_cols[1].metric("主讓過盤", f"{matrix.spread_cover_home:.1%}")
            prob_cols[2].metric("大分", f"{matrix.total_over:.1%}")
            prob_cols[3].metric("MC 次數", f"{matrix.n_simulations:,}")

            if best:
                st.success(
                    f"最佳單注：**{best.title} · {best.selection}** | "
                    f"賠率 {_fmt_odds(best.odds)} | 機率 {best.prob:.1%} | EV {_fmt_ev(best.ev)}"
                )
            else:
                st.info(f"無單注達 EV ≥ {min_ev:.0%}")

            if hedges:
                for h in hedges:
                    with st.expander(f"{h.title} · EV {_fmt_ev(h.ev_total)}"):
                        st.write(h.rationale)
                        for lbl, stake, odds in h.stake_allocations:
                            st.write(f"- {lbl}: **{stake:.0f} 元** @ {odds:.2f}")

            sport_key = sport if sport in ("nba", "mlb") else "nba"
            margin_rows = [
                {
                    "區間": next((b.label_zh for b in bands_for_sport(sport_key) if b.key == k), k),
                    "模型機率": f"{v:.1%}",
                    "賠率": _fmt_odds(item.game_input.margin_odds.get(k)),
                    "EV": _fmt_ev(analytics.expected_value(v, o))
                    if (o := item.game_input.margin_odds.get(k))
                    else "—",
                }
                for k, v in sorted(matrix.margin_probs.items(), key=lambda x: -x[1])[:8]
            ]
            if margin_rows:
                st.markdown("**勝分差機率 Top8**")
                st.dataframe(pd.DataFrame(margin_rows), use_container_width=True, hide_index=True)

            match_options.append(
                _build_match_parlay_options(item, optimizer, matrix, float(total_stake))
            )

        if len(loaded) >= 2:
            st.divider()
            st.markdown("### 串關 / 過關組合")
            parlays, systems, dutch = parlay_opt.optimize_parlay_system(
                match_options,
                total_stake=float(total_stake),
                parlay_size=2,
            )

            if dutch:
                st.markdown("**荷蘭式拆單（跨場包牌）**")
                for labels, odds, stake in dutch:
                    st.write(f"- {' × '.join(labels)} @ {odds:.2f} → **{stake:.0f} 元**")

            if parlays:
                st.markdown("**推薦 2串1**")
                for pl in parlays[:5]:
                    legs = " × ".join(f"{l.match_label}:{l.selection_label}" for l in pl.legs)
                    st.write(
                        f"- {legs} | 合成 {pl.parlay_odds:.2f} | "
                        f"P {pl.combined_prob:.1%} | EV {_fmt_ev(pl.ev)} | 注 **{pl.stake:.0f} 元**"
                    )

            if systems:
                for sys in systems:
                    with st.expander(f"{sys.name} · 複合 EV {_fmt_ev(sys.compound_ev)} · 總注 {sys.total_stake:.0f} 元"):
                        st.write(sys.description)
                        for j, pl in enumerate(sys.parlays, 1):
                            leg_txt = " × ".join(l.selection_label for l in pl.legs)
                            st.write(f"{j}. {leg_txt} @ {pl.parlay_odds:.2f} → {pl.stake:.0f} 元")

    st.caption("提醒：量化建議僅供研究，請量力而為。")
