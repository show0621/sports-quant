"""各預測管線層級之勝負／讓分準確率回測。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import norm

from sportsbet.backtest.metrics import accuracy_report, brier_score
from sportsbet.data.database import SportsDatabase
from sportsbet.models.forecast import game_forecast_from_db_row
from sportsbet.models.totals import margin_std_for_sport, prob_home_covers_spread

Sport = Literal["nba", "mlb"]

# 使用者關注的層級 + 參考基準
LAYER_SPECS: list[tuple[str, str]] = [
    ("log5", "Log5 對戰"),
    ("beta", "Beta-Binomial"),
    ("bayes_recent", "貝氏近況修正"),
    ("markov", "馬可夫鏈 Hot/Cold"),
    ("ensemble", "集成後驗（傷兵前）"),
    ("player_pk", "球員數據 PK"),
    ("mc", "MC 模擬後驗"),
    ("final", "最終 PK 修正勝率"),
]


def _clip_prob(p: float) -> float:
    return float(max(0.001, min(0.999, p)))


def _implied_margin(home_prob: float, sport: str, pred_total: float | None) -> float:
    std = margin_std_for_sport(sport, pred_total=pred_total)
    return float(norm.ppf(_clip_prob(home_prob)) * std)


def _ml_correct(home_prob: float | None, home_won: bool) -> bool | None:
    if home_prob is None or np.isnan(home_prob):
        return None
    pred_home = float(home_prob) >= 0.5
    return pred_home == home_won


def _spread_correct(
    *,
    home_prob: float | None,
    sport: str,
    handicap: float,
    home_won_cover: bool,
    pred_margin: float | None = None,
    prob_home_cover: float | None = None,
    pred_total: float | None = None,
) -> bool | None:
    if prob_home_cover is not None and not np.isnan(prob_home_cover):
        pick_home = float(prob_home_cover) >= 0.5
        return pick_home == home_won_cover
    margin = pred_margin
    if margin is None:
        if home_prob is None or np.isnan(home_prob):
            return None
        margin = _implied_margin(float(home_prob), sport, pred_total)
    p_cover = prob_home_covers_spread(
        float(handicap), float(margin), sport=sport, pred_total=pred_total,
    )
    return (p_cover >= 0.5) == home_won_cover


def _stage_probs_from_forecast(fc) -> dict[str, tuple[float | None, float | None]]:
    pipeline = getattr(fc, "pipeline", None)
    if pipeline is None or not pipeline.stages:
        from sportsbet.models.bayesian_pipeline import ensure_forecast_pipeline

        pipeline = ensure_forecast_pipeline(fc)
    return {s.key: (s.home_prob, s.away_prob) for s in pipeline.stages}


def _mc_sim_result(fc, handicap: float | None):
    if fc.predicted_home_score is None or fc.predicted_away_score is None:
        return None
    sim = getattr(fc, "sim_result", None)
    if sim is not None and sim.home_win_prob is not None:
        if handicap is None or sim.prob_home_cover is not None:
            return sim
    try:
        from sportsbet import config
        from sportsbet.models.matchup_simulator import simulate_matchup

        if not config.USE_MONTE_CARLO:
            return None
        sim = simulate_matchup(
            float(fc.predicted_home_score),
            float(fc.predicted_away_score),
            sport=fc.sport,
            total_line=fc.total_line,
            spread_home=handicap,
            home_win_anchor=fc.home_win_prob,
            n_sims=min(config.MC_N_SIMS, 2000),
        )
        fc.sim_result = sim
        return sim
    except Exception:
        return None


def _mc_home_cover_prob(fc, handicap: float | None) -> float | None:
    sim = _mc_sim_result(fc, handicap)
    if sim is None or sim.prob_home_cover is None:
        return None
    return float(sim.prob_home_cover)


def _mc_home_win_prob(fc, handicap: float | None) -> float | None:
    sim = _mc_sim_result(fc, handicap)
    if sim is None or sim.home_win_prob is None:
        return None
    return float(sim.home_win_prob)


def _player_pk_margin(fc) -> float | None:
    pipeline = getattr(fc, "pipeline", None)
    if pipeline is None:
        return None
    ph, pa = pipeline.player_home_pts_est, pipeline.player_away_pts_est
    if ph is None or pa is None:
        return None
    return float(ph) - float(pa)


@dataclass
class LayerBacktestResult:
    sport: str
    summary: pd.DataFrame
    by_team: pd.DataFrame
    n_games: int
    n_spread: int


def run_layer_backtest(
    db: SportsDatabase | None = None,
    sport: Sport = "nba",
) -> LayerBacktestResult:
    """逐場比對各管線層級的勝負／讓分預測準確率。"""
    db = db or SportsDatabase()
    with db.connection() as conn:
        games = pd.read_sql_query(
            """
            SELECT g.id AS game_id, g.match_date, g.home_team, g.away_team,
                   g.home_score, g.away_score, g.sport, g.status,
                   g.match_datetime, g.home_logo_url, g.away_logo_url,
                   g.season_type, g.competition_note,
                   (SELECT o.handicap FROM odds o
                    WHERE o.game_id = g.id AND o.market = 'spread' AND o.selection = 'home'
                      AND o.handicap IS NOT NULL
                    ORDER BY o.id LIMIT 1) AS spread_handicap
            FROM games g
            WHERE g.sport = ?
              AND g.status = 'final'
              AND g.home_score IS NOT NULL
              AND g.away_score IS NOT NULL
              AND (g.home_score + g.away_score) > 0
              AND g.match_date <= date('now')
              AND EXISTS (SELECT 1 FROM game_forecasts f WHERE f.game_id = g.id)
            ORDER BY g.match_date, g.id
            """,
            conn,
            params=(sport,),
        )

    if games.empty:
        empty = pd.DataFrame(columns=["layer", "label", "n_ml", "ml_accuracy", "n_spread", "spread_accuracy", "brier"])
        return LayerBacktestResult(sport=sport, summary=empty, by_team=pd.DataFrame(), n_games=0, n_spread=0)

    fc_by_gid = db.get_game_forecasts_for_ids(games["game_id"].astype(int).tolist())

    ml_rows: dict[str, list[dict]] = {k: [] for k, _ in LAYER_SPECS}
    sp_rows: dict[str, list[dict]] = {k: [] for k, _ in LAYER_SPECS}
    team_ml: dict[str, dict[str, list[int]]] = {}

    for _, row in games.iterrows():
        fc_row = fc_by_gid.get(int(row["game_id"]))
        if fc_row is None:
            continue
        fc = game_forecast_from_db_row(fc_row, row)
        stages = _stage_probs_from_forecast(fc)
        home_won = int(row["home_score"]) > int(row["away_score"])
        handicap = row.get("spread_handicap")
        has_spread = handicap is not None and pd.notna(handicap)
        home_cover = (int(row["home_score"]) + float(handicap)) > int(row["away_score"]) if has_spread else None
        pred_total = fc.predicted_total
        mc_cover = _mc_home_cover_prob(fc, float(handicap) if has_spread else None)
        pk_margin = _player_pk_margin(fc)

        meta = {
            "game_id": row["game_id"],
            "match_date": row["match_date"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
        }

        for key, _label in LAYER_SPECS:
            hp, _ap = stages.get(key, (None, None))
            if key == "final":
                hp = fc.home_win_prob
            elif key == "mc":
                hp = _mc_home_win_prob(fc, float(handicap) if has_spread else None)

            ml_ok = _ml_correct(hp, home_won)
            if ml_ok is not None:
                ml_rows[key].append({**meta, "home_prob": hp, "won": int(home_won), "correct": int(ml_ok)})
                for team in (row["home_team"], row["away_team"]):
                    team_ml.setdefault(team, {}).setdefault(key, []).append(int(ml_ok))

            if has_spread and home_cover is not None:
                sp_margin = None
                sp_cover_prob = None
                if key == "final":
                    sp_margin = fc.predicted_margin
                elif key == "player_pk" and pk_margin is not None:
                    sp_margin = pk_margin
                elif key == "mc":
                    sp_cover_prob = mc_cover

                sp_ok = _spread_correct(
                    home_prob=hp,
                    sport=sport,
                    handicap=float(handicap),
                    home_won_cover=home_cover,
                    pred_margin=sp_margin,
                    prob_home_cover=sp_cover_prob,
                    pred_total=pred_total,
                )
                if sp_ok is not None:
                    sp_rows[key].append({**meta, "correct": int(sp_ok)})

    summary_rows = []
    for key, label in LAYER_SPECS:
        ml_df = pd.DataFrame(ml_rows[key])
        sp_df = pd.DataFrame(sp_rows[key])
        n_ml = len(ml_df)
        n_sp = len(sp_df)
        ml_acc = float(ml_df["correct"].mean()) if n_ml else float("nan")
        sp_acc = float(sp_df["correct"].mean()) if n_sp else float("nan")
        bs = float("nan")
        if n_ml:
            bs = brier_score(ml_df["won"].astype(int).values, ml_df["home_prob"].astype(float).values)
        summary_rows.append(
            {
                "layer": key,
                "label": label,
                "n_ml": n_ml,
                "ml_accuracy": ml_acc,
                "n_spread": n_sp,
                "spread_accuracy": sp_acc,
                "brier": bs,
            }
        )

    summary = pd.DataFrame(summary_rows).sort_values("ml_accuracy", ascending=False)

    team_records = []
    for team, layers in sorted(team_ml.items()):
        for key, _label in LAYER_SPECS:
            vals = layers.get(key, [])
            if not vals:
                continue
            team_records.append(
                {
                    "team": team,
                    "layer": key,
                    "n_games": len(vals),
                    "ml_accuracy": sum(vals) / len(vals),
                }
            )
    by_team = pd.DataFrame(team_records)

    n_spread = len(pd.DataFrame(sp_rows["final"])) if sp_rows["final"] else 0
    return LayerBacktestResult(
        sport=sport,
        summary=summary,
        by_team=by_team,
        n_games=len(games),
        n_spread=n_spread,
    )


def format_layer_report(result: LayerBacktestResult) -> str:
    """文字報告。"""
    lines = [
        f"=== {result.sport.upper()} 管線層級回測（共 {result.n_games} 場）===",
        "",
        "【勝負準確率】（主隊勝率 >=50% 判主勝，否則判客勝）",
    ]
    for _, r in result.summary.iterrows():
        ml = f"{r['ml_accuracy']:.1%}" if pd.notna(r["ml_accuracy"]) else "—"
        sp = f"{r['spread_accuracy']:.1%}" if pd.notna(r["spread_accuracy"]) else "—"
        bs = f"{r['brier']:.4f}" if pd.notna(r["brier"]) else "—"
        lines.append(
            f"  {r['label']:<22}  勝負 {ml} ({int(r['n_ml'])} 場)  "
            f"讓分 {sp} ({int(r['n_spread'])} 場)  Brier {bs}"
        )
    if not result.by_team.empty:
        best = (
            result.by_team.groupby("layer")
            .agg(n=("n_games", "sum"), acc=("ml_accuracy", "mean"))
            .reset_index()
        )
        lines.append("")
        lines.append("【各隊加總場次已納入上述統計；隊伍層級明細見 by_team】")
    lines.append("")
    lines.append(
        f"讓分樣本：{result.n_spread} 場有讓分盤口（資料仍偏少時僅供參考）。"
    )
    lines.append("讓分方法：final 用預估淨勝；player_pk 用球員估分；MC 用模擬過盤率；其餘層由勝率反推淨勝。")
    return "\n".join(lines)
