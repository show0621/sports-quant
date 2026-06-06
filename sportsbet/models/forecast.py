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
    h2h_recent_games: int | None = None
    sim_result: Any | None = None  # MonteCarloResult when enabled
    prob_breakdown: Any | None = None  # ProbabilityBreakdown from ensemble engine
    pipeline: Any | None = None  # BayesianForecastPipeline
    # V2：模型 + 玩運彩 60%+ 會員預測比例修正
    home_win_prob_v2: float | None = None
    away_win_prob_v2: float | None = None
    prob_over_v2: float | None = None
    prob_under_v2: float | None = None
    prob_home_cover_v2: float | None = None
    member_ml_home_pct: float | None = None
    member_spread_home_pct: float | None = None
    member_over_pct: float | None = None

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
            "home_win_prob_v2": self.home_win_prob_v2,
            "away_win_prob_v2": self.away_win_prob_v2,
            "prob_over_v2": self.prob_over_v2,
            "prob_under_v2": self.prob_under_v2,
            "prob_home_cover_v2": self.prob_home_cover_v2,
            "member_ml_home_pct": self.member_ml_home_pct,
            "member_spread_home_pct": self.member_spread_home_pct,
            "member_over_pct": self.member_over_pct,
        }
        return row


def _float_or(v: object, default: float = 0.0) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    return float(v)


def game_forecast_from_db_row(row: pd.Series, game: pd.Series | None = None) -> GameForecast:
    """由 game_forecasts 資料列還原 GameForecast（不重算模型）。"""
    g = game if game is not None else row
    home_team = str(row.get("home_team") or g.get("home_team", ""))
    away_team = str(row.get("away_team") or g.get("away_team", ""))
    sport = str(row.get("sport") or g.get("sport", "nba"))

    def _side(prefix: str, team: str) -> TeamForecastDetail:
        return TeamForecastDetail(
            team=team,
            rs_per_game=_float_or(row.get(f"{prefix}_rs")),
            ra_per_game=_float_or(row.get(f"{prefix}_ra")),
            games=0,
            pythagorean_win_pct=_float_or(row.get(f"{prefix}_pyth")),
            season_win_pct=_float_or(row.get(f"{prefix}_season_win_pct")),
            recent_win_pct=_float_or(row.get(f"{prefix}_recent_win_pct")),
            log5_matchup_win_pct=_float_or(row.get(f"{prefix}_log5_win_pct")),
            bayesian_win_pct=_float_or(row.get(f"{prefix}_bayesian_win_pct")),
        )

    pick = row.get("pick_correct")
    pick_correct = bool(int(pick)) if pick is not None and pd.notna(pick) else None
    ah = row.get("actual_home_score")
    aa = row.get("actual_away_score")

    fc = GameForecast(
        sport=sport,
        match_date=str(row.get("match_date") or g.get("match_date", ""))[:10],
        home_team=home_team,
        away_team=away_team,
        home=_side("home", home_team),
        away=_side("away", away_team),
        home_win_prob=_float_or(row.get("home_win_prob"), 0.5),
        away_win_prob=_float_or(row.get("away_win_prob"), 0.5),
        predicted_winner=str(row.get("predicted_winner") or ""),
        predicted_home_score=_float_or(row.get("predicted_home_score")),
        predicted_away_score=_float_or(row.get("predicted_away_score")),
        predicted_total=_float_or(row.get("predicted_total")),
        predicted_margin=_float_or(row.get("predicted_margin")),
        total_line=float(row["total_line"]) if pd.notna(row.get("total_line")) else None,
        prob_over=float(row["prob_over"]) if pd.notna(row.get("prob_over")) else None,
        prob_under=float(row["prob_under"]) if pd.notna(row.get("prob_under")) else None,
        margin_note=str(row.get("margin_note") or ""),
        home_win_prob_base=float(row["home_win_prob_base"]) if pd.notna(row.get("home_win_prob_base")) else None,
        away_win_prob_base=float(row["away_win_prob_base"]) if pd.notna(row.get("away_win_prob_base")) else None,
        home_injury_adj=float(row["home_injury_adj"]) if pd.notna(row.get("home_injury_adj")) else None,
        away_injury_adj=float(row["away_injury_adj"]) if pd.notna(row.get("away_injury_adj")) else None,
        match_datetime=str(g["match_datetime"]) if g is not None and pd.notna(g.get("match_datetime")) else None,
        home_logo_url=str(g["home_logo_url"]) if g is not None and pd.notna(g.get("home_logo_url")) else None,
        away_logo_url=str(g["away_logo_url"]) if g is not None and pd.notna(g.get("away_logo_url")) else None,
        game_id=int(row["game_id"]) if pd.notna(row.get("game_id")) else None,
        status=str(row.get("status") or g.get("status") or "scheduled"),
        actual_winner=str(row["actual_winner"]) if pd.notna(row.get("actual_winner")) else None,
        actual_home_score=int(ah) if pd.notna(ah) else None,
        actual_away_score=int(aa) if pd.notna(aa) else None,
        pick_correct=pick_correct,
        margin_error=float(row["margin_error"]) if pd.notna(row.get("margin_error")) else None,
        total_error=float(row["total_error"]) if pd.notna(row.get("total_error")) else None,
        home_adjusted_rating=float(row["home_adjusted_rating"]) if pd.notna(row.get("home_adjusted_rating")) else None,
        away_adjusted_rating=float(row["away_adjusted_rating"]) if pd.notna(row.get("away_adjusted_rating")) else None,
        home_injury_penalty=float(row["home_injury_penalty"]) if pd.notna(row.get("home_injury_penalty")) else None,
        away_injury_penalty=float(row["away_injury_penalty"]) if pd.notna(row.get("away_injury_penalty")) else None,
        season_type=str(g["season_type"]) if g is not None and pd.notna(g.get("season_type")) else None,
        competition_note=str(g["competition_note"]) if g is not None and pd.notna(g.get("competition_note")) else None,
        home_win_prob_v2=float(row["home_win_prob_v2"]) if pd.notna(row.get("home_win_prob_v2")) else None,
        away_win_prob_v2=float(row["away_win_prob_v2"]) if pd.notna(row.get("away_win_prob_v2")) else None,
        prob_over_v2=float(row["prob_over_v2"]) if pd.notna(row.get("prob_over_v2")) else None,
        prob_under_v2=float(row["prob_under_v2"]) if pd.notna(row.get("prob_under_v2")) else None,
        prob_home_cover_v2=float(row["prob_home_cover_v2"]) if pd.notna(row.get("prob_home_cover_v2")) else None,
        member_ml_home_pct=float(row["member_ml_home_pct"]) if pd.notna(row.get("member_ml_home_pct")) else None,
        member_spread_home_pct=float(row["member_spread_home_pct"]) if pd.notna(row.get("member_spread_home_pct")) else None,
        member_over_pct=float(row["member_over_pct"]) if pd.notna(row.get("member_over_pct")) else None,
    )
    from sportsbet.models.bayesian_pipeline import ensure_forecast_pipeline

    ensure_forecast_pipeline(fc)
    return fc


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
    h2h_recent_games = 0

    from sportsbet.data.h2h_recent import is_playoff_series, resolve_matchup_recent_form

    _playoff = is_playoff_series(season_type, competition_note)
    if db is not None and _playoff:
        h_recent, a_recent, _, _, h2h_recent_games = resolve_matchup_recent_form(
            db,
            sport,
            home_team,
            away_team,
            match_date,
            h_recent,
            a_recent,
            playoff=True,
        )

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
            season_type=season_type,
            competition_note=competition_note,
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
            recent_weight=(
                config.PLAYOFF_H2H_BAYES_RECENT_WEIGHT
                if h2h_recent_games >= 1 and config.PLAYOFF_USE_H2H_RECENT
                else None
            ),
        )
        bayes_away = engine.bayesian_posterior(
            log5_away,
            recent_win_pct=a_recent,
            season_win_pct=away_pyth,
            recent_weight=(
                config.PLAYOFF_H2H_BAYES_RECENT_WEIGHT
                if h2h_recent_games >= 1 and config.PLAYOFF_USE_H2H_RECENT
                else None
            ),
        )
        total = bayes_home + bayes_away
        home_prob_base = bayes_home / total
        away_prob_base = bayes_away / total

    home_prob = home_prob_base
    away_prob = away_prob_base
    home_prob_roster = away_prob_roster = None
    roster_applied = False

    home_adj = away_adj = home_pen = away_pen = None
    home_base = away_base = None
    home_miss: list[dict[str, Any]] = []
    away_miss: list[dict[str, Any]] = []

    if db is not None and use_roster:
        from sportsbet.data.data_quality import matchup_injury_adjustment_ready

        if matchup_injury_adjustment_ready(db, sport, home_team, away_team, match_date):
            from sportsbet.models.roster_engine import DynamicRosterRatingEngine

            rr = DynamicRosterRatingEngine(db).matchup_with_roster(
                sport, home_team, away_team, match_date, home_prob, away_prob,
            )
            if rr.get("roster_applied"):
                roster_applied = True
                home_prob_roster = rr["home_win_prob"]
                away_prob_roster = rr["away_win_prob"]
                home_prob = home_prob_roster
                away_prob = away_prob_roster
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

        _playoff = bool(
            (season_type and "季後" in str(season_type))
            or (competition_note and ("總冠軍" in str(competition_note) or "季後" in str(competition_note)))
        )
        lam_h, lam_a = blend_lambdas_with_h2h(
            db, sport, home_team, away_team, match_date, lam_h, lam_a,
            blend=config.MC_H2H_LAMBDA_BLEND,
            playoff_series=_playoff,
        )
        from sportsbet.models.player_scoring import blend_lambdas_with_lineup_scoring

        lam_h, lam_a = blend_lambdas_with_lineup_scoring(
            db, sport, home_team, away_team, match_date, lam_h, lam_a,
        )
        if home_adj is not None and away_adj is not None and roster_applied:
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

    mc_prob_over = sim_result.prob_over if sim_result is not None else None
    if sim_result is not None:
        home_prob = 0.65 * home_prob + 0.35 * sim_result.home_win_prob
        away_prob = 1.0 - home_prob

    from sportsbet.models.calibration import (
        calibrate_total_prob,
        calibrate_win_prob,
        market_implied_over_prob,
    )

    home_prob = calibrate_win_prob(home_prob, sport)
    away_prob = 1.0 - home_prob

    if market_line is not None and prob_o is not None:
        mkt_implied = None
        if db is not None and game_id and hasattr(db, "get_game_odds"):
            try:
                mkt_implied = market_implied_over_prob(db.get_game_odds(game_id))
            except Exception:
                mkt_implied = None
        prob_o = calibrate_total_prob(
            market_line,
            pred_total,
            sport,
            poisson_prob=prob_o,
            mc_prob=mc_prob_over,
            market_implied=mkt_implied,
        )
        prob_u = 1.0 - prob_o

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

    from sportsbet.models.member_consensus_v2 import (
        compute_forecast_v2,
        snapshot_from_db_row,
    )

    consensus_row = None
    if db is not None and game_id:
        try:
            consensus_row = db.get_member_consensus_snapshot(int(game_id))
        except Exception:
            consensus_row = None
    consensus = snapshot_from_db_row(consensus_row)
    v2 = compute_forecast_v2(
        sport=sport,
        home_win_prob=home_prob,
        prob_over=prob_o,
        predicted_margin=pred_margin,
        spread_home_line=spread_home_line,
        consensus=consensus,
    )

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

    fc = GameForecast(
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
        home_injury_adj=(
            (home_prob_roster - home_prob_base) if roster_applied and home_prob_roster is not None else None
        ),
        away_injury_adj=(
            (away_prob_roster - away_prob_base) if roster_applied and away_prob_roster is not None else None
        ),
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
        h2h_recent_games=h2h_recent_games or None,
        sim_result=sim_result,
        prob_breakdown=prob_breakdown,
        home_win_prob_v2=v2.home_win_prob_v2,
        away_win_prob_v2=v2.away_win_prob_v2,
        prob_over_v2=v2.prob_over_v2,
        prob_under_v2=v2.prob_under_v2,
        prob_home_cover_v2=v2.prob_home_cover_v2,
        member_ml_home_pct=consensus.ml_home_pct if consensus else None,
        member_spread_home_pct=consensus.spread_home_pct if consensus else None,
        member_over_pct=consensus.over_pct if consensus else None,
    )
    from sportsbet.models.bayesian_pipeline import build_pipeline_from_forecast

    fc.pipeline = build_pipeline_from_forecast(fc)
    return fc


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
        "home_win_prob_v2": fc.home_win_prob_v2,
        "away_win_prob_v2": fc.away_win_prob_v2,
        "prob_over_v2": fc.prob_over_v2,
        "prob_under_v2": fc.prob_under_v2,
        "prob_home_cover_v2": fc.prob_home_cover_v2,
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


def _stage_probs(fc: GameForecast) -> dict[str, tuple[float | None, float | None]]:
    """管線各步驟 (home_prob, away_prob)。"""
    from sportsbet.models.bayesian_pipeline import ensure_forecast_pipeline

    pipeline = ensure_forecast_pipeline(fc)
    return {s.key: (s.home_prob, s.away_prob) for s in pipeline.stages}


def _pair_away_home(
    stages: dict[str, tuple[float | None, float | None]],
    key: str,
) -> tuple[str, str]:
    h, a = stages.get(key, (None, None))
    return _fmt_pct(a), _fmt_pct(h)


def team_rating_panel_rows(fc: GameForecast) -> list[tuple[str, str, str, bool]]:
    """球隊評分明細列：(指標, 客隊顯示, 主隊顯示, 是否最終列)。"""
    away = fc.away
    home = fc.home
    stages = _stage_probs(fc)

    rows: list[tuple[str, str, str, bool]] = [
        ("戰績 W-L", format_wl_record(away.games, away.season_win_pct),
         format_wl_record(home.games, home.season_win_pct), False),
        ("賽季勝率", _fmt_pct(away.season_win_pct), _fmt_pct(home.season_win_pct), False),
    ]
    recent_label = (
        f"近況（對手 H2H·{fc.h2h_recent_games}）"
        if fc.h2h_recent_games and fc.h2h_recent_games >= 1
        else "近況勝率"
    )
    rows.append(
        (recent_label, _fmt_pct(away.recent_win_pct), _fmt_pct(home.recent_win_pct), False),
    )
    rows.extend([
        ("畢氏勝率", _fmt_pct(away.pythagorean_win_pct), _fmt_pct(home.pythagorean_win_pct), False),
        ("Log5 對戰", _fmt_pct(away.log5_matchup_win_pct), _fmt_pct(home.log5_matchup_win_pct), False),
    ])

    for key, label in (
        ("beta", "Beta-Binomial"),
        ("bayes_recent", "貝氏近況修正"),
        ("markov", "馬可夫鏈 Hot/Cold"),
        ("h2h", "前次交鋒 H2H PK"),
        ("ensemble", "集成後驗（傷兵前）"),
    ):
        av, hv = _pair_away_home(stages, key)
        if av != "—" or hv != "—":
            rows.append((label, av, hv, False))

    if fc.away_injury_adj is not None or fc.home_injury_adj is not None:
        rows.append(
            ("傷兵修正", _fmt_pct(fc.away_injury_adj, signed=True),
             _fmt_pct(fc.home_injury_adj, signed=True), False),
        )
        av, hv = _pair_away_home(stages, "injury")
        if av != "—" or hv != "—":
            rows.append(("傷兵後勝率", av, hv, False))

    av, hv = _pair_away_home(stages, "player_pk")
    if av != "—" or hv != "—":
        rows.append(("球員數據 PK", av, hv, False))

    av, hv = _pair_away_home(stages, "mc")
    if av != "—" or hv != "—":
        rows.append(("MC 模擬後驗", av, hv, False))

    rows.append(
        ("最終 PK 修正勝率", _fmt_pct(fc.away_win_prob), _fmt_pct(fc.home_win_prob), True),
    )
    return rows


def team_rating_panel_html(fc: GameForecast, sport: str) -> str:
    """即時看板：兩隊評分對照表 HTML。"""
    from sportsbet.data.team_names import team_bilingual

    away = fc.away
    home = fc.home
    a_en, a_zh = team_bilingual(away.team, sport)
    h_en, h_zh = team_bilingual(home.team, sport)
    a_head = f"{a_en}<br><span class='sq-rating-zh'>{a_zh}</span>" if a_zh else a_en
    h_head = f"{h_en}<br><span class='sq-rating-zh'>{h_zh}</span>" if h_zh else h_en

    body = "".join(
        f"<tr{' class=\"sq-rating-final\"' if is_final else ''}>"
        f"<td class='sq-rating-metric'>{label}</td>"
        f"<td class='sq-rating-val away'>{av}</td>"
        f"<td class='sq-rating-val home'>{hv}</td></tr>"
        for label, av, hv, is_final in team_rating_panel_rows(fc)
    )
    return (
        f"<div class='sq-rating-panel'>"
        f"<div class='sq-rating-title'>球隊評分明細</div>"
        f"<table class='sq-rating-table'>"
        f"<thead><tr><th></th><th>客 · {a_head}</th><th>主 · {h_head}</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def team_detail_dataframe(f: GameForecast) -> pd.DataFrame:
    """單場兩隊明細表（含貝氏/馬可夫/球員 PK 各層修正至最終勝率）。"""
    stages = _stage_probs(f)

    def _side(key: str, side: str) -> float | None:
        pair = stages.get(key)
        if not pair:
            return None
        return pair[0] if side == "home" else pair[1]

    rows = []
    for side_obj, label, side_key in [(f.home, "主", "home"), (f.away, "客", "away")]:
        rows.append(
            {
                "主客": label,
                "隊伍": side_obj.team,
                "戰績 W-L": format_wl_record(side_obj.games, side_obj.season_win_pct),
                "场均得分": round(side_obj.rs_per_game, 2),
                "场均失分": round(side_obj.ra_per_game, 2),
                "畢達哥拉斯勝率": side_obj.pythagorean_win_pct,
                "賽季勝率": side_obj.season_win_pct,
                "近況勝率": side_obj.recent_win_pct,
                "Log5單場勝率": side_obj.log5_matchup_win_pct,
                "Beta-Binomial": _side("beta", side_key),
                "貝氏近況修正": side_obj.bayesian_win_pct,
                "馬可夫鏈 Hot/Cold": _side("markov", side_key),
                "前次交鋒 H2H PK": _side("h2h", side_key),
                "集成後驗（傷兵前）": _side("ensemble", side_key),
                "傷兵修正": f.home_injury_adj if side_key == "home" else f.away_injury_adj,
                "傷兵後勝率": _side("injury", side_key),
                "球員數據 PK": _side("player_pk", side_key),
                "MC 模擬後驗": _side("mc", side_key),
                "最終 PK 修正勝率": f.home_win_prob if side_key == "home" else f.away_win_prob,
            }
        )
    return pd.DataFrame(rows)
