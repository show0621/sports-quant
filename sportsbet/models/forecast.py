"""單場完整預測：勝負、大小分、勝分差與各隊明細。"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Literal

import pandas as pd

from sportsbet import analytics, config
from sportsbet.models.analytics_engine import AnalyticsEngine


@dataclass
class TeamForecastDetail:
    team: str
    rs_per_game: float
    ra_per_game: float
    games: int
    pythagorean_win_pct: float
    season_win_pct: float
    recent_win_pct: float
    log5_matchup_win_pct: float
    bayesian_win_pct: float


@dataclass
class GameForecast:
    sport: str
    match_date: str
    home_team: str
    away_team: str
    home: TeamForecastDetail
    away: TeamForecastDetail
    home_win_prob: float
    away_win_prob: float
    predicted_winner: str
    predicted_home_score: float
    predicted_away_score: float
    predicted_total: float
    predicted_margin: float
    total_line: float | None
    prob_over: float | None
    prob_under: float | None
    margin_note: str
    home_win_prob_base: float | None = None
    away_win_prob_base: float | None = None
    home_injury_adj: float | None = None
    away_injury_adj: float | None = None
    match_datetime: str | None = None
    home_logo_url: str | None = None
    away_logo_url: str | None = None
    game_id: int | None = None
    status: str = "scheduled"
    actual_winner: str | None = None
    actual_home_score: int | None = None
    actual_away_score: int | None = None
    pick_correct: bool | None = None
    margin_error: float | None = None
    total_error: float | None = None
    home_adjusted_rating: float | None = None
    away_adjusted_rating: float | None = None
    home_injury_penalty: float | None = None
    away_injury_penalty: float | None = None
    home_missing: list[dict[str, Any]] | None = None
    away_missing: list[dict[str, Any]] | None = None
    season_type: str | None = None
    competition_note: str | None = None
    sim_result: Any | None = None  # MonteCarloResult when enabled
    prob_breakdown: Any | None = None  # ProbabilityBreakdown from ensemble engine

    def to_db_row(self) -> dict[str, Any]:
        row = {
            "game_id": self.game_id,
            "sport": self.sport,
            "match_date": self.match_date,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "status": self.status,
            "home_rs": self.home.rs_per_game,
            "home_ra": self.home.ra_per_game,
            "away_rs": self.away.rs_per_game,
            "away_ra": self.away.ra_per_game,
            "home_pyth": self.home.pythagorean_win_pct,
            "away_pyth": self.away.pythagorean_win_pct,
            "home_season_win_pct": self.home.season_win_pct,
            "away_season_win_pct": self.away.season_win_pct,
            "home_recent_win_pct": self.home.recent_win_pct,
            "away_recent_win_pct": self.away.recent_win_pct,
            "home_log5_win_pct": self.home.log5_matchup_win_pct,
            "away_log5_win_pct": self.away.log5_matchup_win_pct,
            "home_bayesian_win_pct": self.home.bayesian_win_pct,
            "away_bayesian_win_pct": self.away.bayesian_win_pct,
            "home_win_prob": self.home_win_prob,
            "away_win_prob": self.away_win_prob,
            "home_win_prob_base": self.home_win_prob_base,
            "away_win_prob_base": self.away_win_prob_base,
            "home_injury_adj": self.home_injury_adj,
            "away_injury_adj": self.away_injury_adj,
            "predicted_winner": self.predicted_winner,
            "predicted_home_score": self.predicted_home_score,
            "predicted_away_score": self.predicted_away_score,
            "predicted_total": self.predicted_total,
            "predicted_margin": self.predicted_margin,
            "total_line": self.total_line,
            "prob_over": self.prob_over,
            "prob_under": self.prob_under,
            "margin_note": self.margin_note,
            "actual_winner": self.actual_winner,
            "actual_home_score": self.actual_home_score,
            "actual_away_score": self.actual_away_score,
            "pick_correct": int(self.pick_correct) if self.pick_correct is not None else None,
            "margin_error": self.margin_error,
            "total_error": self.total_error,
            "home_adjusted_rating": self.home_adjusted_rating,
            "away_adjusted_rating": self.away_adjusted_rating,
            "home_injury_penalty": self.home_injury_penalty,
            "away_injury_penalty": self.away_injury_penalty,
        }
        return row


def forecast_event_label(fc: GameForecast | object) -> str:
    """賽事性質標籤（季後賽 / 總冠軍賽等）；相容舊版物件缺欄位。"""
    note = getattr(fc, "competition_note", None) or getattr(fc, "season_type", None) or ""
    return str(note).strip() if note else ""


def _team_detail(
    team: str,
    rs: float,
    ra: float,
    games: int,
    pyth: float,
    season_wp: float,
    recent_wp: float,
    log5_wp: float,
    bayes_wp: float,
) -> TeamForecastDetail:
    return TeamForecastDetail(
        team=team,
        rs_per_game=rs,
        ra_per_game=ra,
        games=games,
        pythagorean_win_pct=pyth,
        season_win_pct=season_wp,
        recent_win_pct=recent_wp,
        log5_matchup_win_pct=log5_wp,
        bayesian_win_pct=bayes_wp,
    )


def build_game_forecast(
    engine: AnalyticsEngine,
    home_team: str,
    away_team: str,
    home_rs: float,
    home_ra: float,
    away_rs: float,
    away_ra: float,
    *,
    match_date: str,
    sport: Literal["nba", "mlb"],
    home_games: int = 0,
    away_games: int = 0,
    home_season_win_pct: float | None = None,
    away_season_win_pct: float | None = None,
    home_recent_win_pct: float | None = None,
    away_recent_win_pct: float | None = None,
    total_line: float | None = None,
    match_datetime: str | None = None,
    home_logo_url: str | None = None,
    away_logo_url: str | None = None,
    game_id: int | None = None,
    status: str = "scheduled",
    actual_home_score: int | None = None,
    actual_away_score: int | None = None,
    db: Any | None = None,
    use_roster: bool = True,
    season_type: str | None = None,
    competition_note: str | None = None,
) -> GameForecast:
    """產生單場完整預測（含各隊畢達哥拉斯、賽季勝率、貝氏後驗）。"""
    home_pyth = engine.team_win_pct(home_rs, home_ra, home_games)
    away_pyth = engine.team_win_pct(away_rs, away_ra, away_games)
    h_season = home_season_win_pct if home_season_win_pct is not None else home_pyth
    a_season = away_season_win_pct if away_season_win_pct is not None else away_pyth
    h_recent = home_recent_win_pct if home_recent_win_pct is not None else h_season
    a_recent = away_recent_win_pct if away_recent_win_pct is not None else a_season

    log5_home, log5_away = analytics.matchup_win_prob(home_pyth, away_pyth, engine.home_advantage)

    prob_breakdown = None
    if config.USE_MARKOV_FORM or config.USE_CONTEXT_FEATURES:
        from sportsbet.models.probability_engine import ensemble_matchup_probability

        prob_breakdown = ensemble_matchup_probability(
            engine,
            sport,
            home_team,
            away_team,
            home_rs,
            home_ra,
            away_rs,
            away_ra,
            match_date,
            home_games=home_games,
            away_games=away_games,
            home_season_win_pct=home_season_win_pct,
            away_season_win_pct=away_season_win_pct,
            home_recent_win_pct=home_recent_win_pct,
            away_recent_win_pct=away_recent_win_pct,
            db=db,
        )
        bayes_home = prob_breakdown.bayesian_home
        bayes_away = prob_breakdown.bayesian_away
        home_prob_base = prob_breakdown.final_home
        away_prob_base = prob_breakdown.final_away
    else:
        bayes_home = engine.bayesian_posterior(
            log5_home,
            is_home=True,
            recent_win_pct=h_recent,
            season_win_pct=home_pyth,
        )
        bayes_away = engine.bayesian_posterior(
            log5_away,
            recent_win_pct=a_recent,
            season_win_pct=away_pyth,
        )
        total = bayes_home + bayes_away
        home_prob_base = bayes_home / total
        away_prob_base = bayes_away / total

    home_prob = home_prob_base
    away_prob = away_prob_base

    home_adj = away_adj = home_pen = away_pen = None
    home_base = away_base = None
    home_miss: list[dict[str, Any]] = []
    away_miss: list[dict[str, Any]] = []

    if db is not None and use_roster:
        from sportsbet.data.data_quality import roster_rating_enabled

        if roster_rating_enabled(db, sport):
            from sportsbet.models.roster_engine import DynamicRosterRatingEngine

            rr = DynamicRosterRatingEngine(db).matchup_with_roster(
                sport, home_team, away_team, match_date, home_prob, away_prob,
            )
            home_prob = rr["home_win_prob"]
            away_prob = rr["away_win_prob"]
            home_adj = rr["home"].adjusted_rating
            away_adj = rr["away"].adjusted_rating
            home_base = rr["home"].baseline_rating
            away_base = rr["away"].baseline_rating
            home_pen = rr["home"].injury_penalty
            away_pen = rr["away"].injury_penalty
            home_miss = [
                {"name": m.name, "status": m.status, "penalty": m.win_prob_penalty}
                for m in rr["home"].excluded_players + rr["home"].discounted_players
            ]
            away_miss = [
                {"name": m.name, "status": m.status, "penalty": m.win_prob_penalty}
                for m in rr["away"].excluded_players + rr["away"].discounted_players
            ]

    lam_h, lam_a = engine.expected_score_lambdas(home_rs, home_ra, away_rs, away_ra)

    if db is not None:
        from sportsbet.models.matchup_simulator import (
            adjust_lambdas_from_roster,
            blend_lambdas_with_h2h,
        )

        lam_h, lam_a = blend_lambdas_with_h2h(
            db, sport, home_team, away_team, match_date, lam_h, lam_a,
            blend=config.MC_H2H_LAMBDA_BLEND,
        )
        if home_adj is not None and away_adj is not None:
            lam_h, lam_a = adjust_lambdas_from_roster(
                lam_h, lam_a,
                home_adjusted=home_adj,
                away_adjusted=away_adj,
                home_baseline=home_base,
                away_baseline=away_base,
            )

    spread_home_line = None
    if db is not None and game_id and hasattr(db, "get_market_line"):
        spread_home_line = db.get_market_line(game_id, "spread")

    sim_result = None
    if config.USE_MONTE_CARLO:
        from sportsbet.models.matchup_simulator import simulate_matchup

        sim_result = simulate_matchup(
            lam_h, lam_a,
            sport=sport,
            total_line=total_line,
            spread_home=spread_home_line,
            home_win_anchor=home_prob,
            n_sims=config.MC_N_SIMS,
        )

    pred_home = round(lam_h, 1)
    pred_away = round(lam_a, 1)
    pred_total = round(lam_h + lam_a, 1)
    pred_margin = round(lam_h - lam_a, 1)

    if sport == "nba":
        market_line = total_line
        prob_o = prob_u = None
        if market_line is not None:
            prob_o = engine.prob_total_over(market_line, lam_h, lam_a)
            prob_u = 1.0 - prob_o
    else:
        market_line = total_line
        prob_o = prob_u = None
        if market_line is not None:
            prob_o = engine.prob_total_over(market_line, lam_h, lam_a)
            prob_u = 1.0 - prob_o

    if sim_result is not None:
        if sim_result.prob_over is not None:
            prob_o = sim_result.prob_over
            prob_u = sim_result.prob_under
        home_prob = 0.65 * home_prob + 0.35 * sim_result.home_win_prob
        away_prob = 1.0 - home_prob

    winner = home_team if home_prob >= away_prob else away_team
    unit = "分" if sport == "nba" else "分"
    margin_note = (
        f"主隊預估淨勝 {pred_margin:+.1f} {unit}"
        if pred_margin > 0
        else f"客隊預估淨勝 {-pred_margin:.1f} {unit}"
        if pred_margin < 0
        else "預估平手"
    )
    if market_line is None:
        margin_note += f" · 預估總得 {pred_total:.1f}（無大小盤口）"
    else:
        label = "大小分" if sport == "nba" else "大小"
        margin_note += f" · {label}線 {market_line} · 預估總得 {pred_total:.1f}"
    if sim_result is not None:
        margin_note += f" · {sim_result.summary_line(sport=sport)}"

    actual_winner = None
    pick_correct = None
    margin_error = None
    total_error = None
    if actual_home_score is not None and actual_away_score is not None:
        if actual_home_score > actual_away_score:
            actual_winner = home_team
        elif actual_away_score > actual_home_score:
            actual_winner = away_team
        else:
            actual_winner = "平手"
        pick_correct = winner == actual_winner
        margin_error = (actual_home_score - actual_away_score) - pred_margin
        total_error = (actual_home_score + actual_away_score) - pred_total

    return GameForecast(
        sport=sport,
        match_date=match_date,
        home_team=home_team,
        away_team=away_team,
        game_id=game_id,
        status=status,
        home=_team_detail(
            home_team, home_rs, home_ra, home_games,
            home_pyth, h_season, h_recent, log5_home, bayes_home,
        ),
        away=_team_detail(
            away_team, away_rs, away_ra, away_games,
            away_pyth, a_season, a_recent, log5_away, bayes_away,
        ),
        home_win_prob=home_prob,
        away_win_prob=away_prob,
        home_win_prob_base=home_prob_base,
        away_win_prob_base=away_prob_base,
        home_injury_adj=home_prob - home_prob_base,
        away_injury_adj=away_prob - away_prob_base,
        predicted_winner=winner,
        predicted_home_score=pred_home,
        predicted_away_score=pred_away,
        predicted_total=pred_total,
        predicted_margin=pred_margin,
        total_line=market_line,
        prob_over=prob_o,
        prob_under=prob_u,
        margin_note=margin_note,
        match_datetime=match_datetime,
        home_logo_url=home_logo_url,
        away_logo_url=away_logo_url,
        actual_winner=actual_winner,
        actual_home_score=actual_home_score,
        actual_away_score=actual_away_score,
        pick_correct=pick_correct,
        margin_error=margin_error,
        total_error=total_error,
        home_adjusted_rating=home_adj,
        away_adjusted_rating=away_adj,
        home_injury_penalty=home_pen,
        away_injury_penalty=away_pen,
        home_missing=home_miss or None,
        away_missing=away_miss or None,
        season_type=season_type,
        competition_note=competition_note,
        sim_result=sim_result,
        prob_breakdown=prob_breakdown,
    )


def forecasts_to_matchup_table(forecasts: list[GameForecast]) -> pd.DataFrame:
    """將多場預測展平為對戰總表。"""
    rows = []
    for f in forecasts:
        rows.append(
            {
                "game_id": f.game_id,
                "日期": f.match_date,
                "對戰": f"{f.home_team} vs {f.away_team}",
                "日期": f.match_date,
                "開賽時間": f.match_datetime,
                "狀態": f.status,
                "預測勝者": f.predicted_winner,
                "主隊勝率": f.home_win_prob,
                "客隊勝率": f.away_win_prob,
                "預估比分": f"{f.predicted_home_score:.0f}-{f.predicted_away_score:.0f}",
                "預估總分": f.predicted_total,
                "大小分線": f.total_line,
                "大分機率": f.prob_over,
                "預估分差": f.predicted_margin,
                "實際勝者": f.actual_winner,
                "實際比分": (
                    f"{f.actual_home_score}-{f.actual_away_score}"
                    if f.actual_home_score is not None
                    else None
                ),
                "預測正確": f.pick_correct,
                "分差誤差": f.margin_error,
            }
        )
    return pd.DataFrame(rows)


def format_wl_record(games: int, win_pct: float) -> str:
    """由出賽數與勝率推算 W-L 戰績。"""
    if games <= 0:
        return "—"
    wins = round(float(win_pct) * games)
    wins = max(0, min(games, wins))
    return f"{wins}-{games - wins}"


def forecast_pick_dict(fc: GameForecast) -> dict[str, Any]:
    """供盤口/EV 計算使用的扁平 dict。"""
    return {
        "predicted_winner": fc.predicted_winner,
        "home_win_prob": fc.home_win_prob,
        "away_win_prob": fc.away_win_prob,
        "predicted_margin": fc.predicted_margin,
        "predicted_total": fc.predicted_total,
        "total_line": fc.total_line,
        "prob_over": fc.prob_over,
        "prob_under": fc.prob_under,
        "predicted_home_score": fc.predicted_home_score,
        "predicted_away_score": fc.predicted_away_score,
        "pick_correct": fc.pick_correct,
        "home_team": fc.home_team,
        "away_team": fc.away_team,
    }


def _fmt_pct(v: float | None, *, signed: bool = False) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    x = float(v)
    if signed:
        return f"{x * 100:+.1f}%"
    return f"{x * 100:.1f}%"


def team_rating_panel_html(fc: GameForecast, sport: str) -> str:
    """即時看板：兩隊評分對照表 HTML。"""
    from sportsbet.data.team_names import team_bilingual

    away = fc.away
    home = fc.home
    a_en, a_zh = team_bilingual(away.team, sport)
    h_en, h_zh = team_bilingual(home.team, sport)
    a_head = f"{a_en}<br><span class='sq-rating-zh'>{a_zh}</span>" if a_zh else a_en
    h_head = f"{h_en}<br><span class='sq-rating-zh'>{h_zh}</span>" if h_zh else h_en

    away_base = fc.away_win_prob_base
    home_base = fc.home_win_prob_base
    away_adj = fc.away_injury_adj
    home_adj = fc.home_injury_adj

    rows = [
        ("戰績 W-L", format_wl_record(away.games, away.season_win_pct),
         format_wl_record(home.games, home.season_win_pct)),
        ("賽季勝率", _fmt_pct(away.season_win_pct), _fmt_pct(home.season_win_pct)),
        ("畢氏勝率", _fmt_pct(away.pythagorean_win_pct), _fmt_pct(home.pythagorean_win_pct)),
        ("貝氏勝率", _fmt_pct(away.bayesian_win_pct), _fmt_pct(home.bayesian_win_pct)),
        ("傷兵前勝率", _fmt_pct(away_base), _fmt_pct(home_base)),
        ("傷兵修正", _fmt_pct(away_adj, signed=True), _fmt_pct(home_adj, signed=True)),
        ("模型預測勝率", _fmt_pct(fc.away_win_prob), _fmt_pct(fc.home_win_prob)),
    ]

    body = "".join(
        f"<tr><td class='sq-rating-metric'>{label}</td>"
        f"<td class='sq-rating-val away'>{av}</td>"
        f"<td class='sq-rating-val home'>{hv}</td></tr>"
        for label, av, hv in rows
    )
    return (
        f"<div class='sq-rating-panel'>"
        f"<div class='sq-rating-title'>球隊評分明細</div>"
        f"<table class='sq-rating-table'>"
        f"<thead><tr><th></th><th>客 · {a_head}</th><th>主 · {h_head}</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def team_detail_dataframe(f: GameForecast) -> pd.DataFrame:
    """單場兩隊明細表。"""
    rows = []
    for side, label in [(f.home, "主"), (f.away, "客")]:
        rows.append(
            {
                "主客": label,
                "隊伍": side.team,
                "戰績 W-L": format_wl_record(side.games, side.season_win_pct),
                "场均得分": round(side.rs_per_game, 2),
                "场均失分": round(side.ra_per_game, 2),
                "畢達哥拉斯勝率": side.pythagorean_win_pct,
                "賽季勝率": side.season_win_pct,
                "近況勝率": side.recent_win_pct,
                "Log5單場勝率": side.log5_matchup_win_pct,
                "貝氏修正勝率": side.bayesian_win_pct,
                "傷兵前勝率": (
                    f.home_win_prob_base if label == "主" else f.away_win_prob_base
                ),
                "傷兵修正": (
                    f.home_injury_adj if label == "主" else f.away_injury_adj
                ),
                "最終預測勝率": f.home_win_prob if label == "主" else f.away_win_prob,
            }
        )
    return pd.DataFrame(rows)
