"""從 DB 賽程 + 預測 + preferred 盤口建立 GameInput。"""
from __future__ import annotations

from dataclasses import dataclass

from sportsbet.data.database import SportsDatabase
from sportsbet.data.odds_summary import summarize_preferred_odds
from sportsbet.models.forecast import GameForecast, forecast_event_label
from sportsbet.optimization.universal_sport_optimizer import GameInput, SportKind
from sportsbet.services.prediction_service import PredictionService


@dataclass
class LoadedGame:
    """DB 載入的單場優化輸入。"""

    game_input: GameInput
    forecast: GameForecast
    odds_meta: dict[str, object]
    game_id: int


def _sport_kind(sport: str) -> SportKind:
    if sport in ("nba", "mlb", "soccer", "tennis", "generic"):
        return sport  # type: ignore[return-value]
    return "generic"


def game_input_from_forecast(
    fc: GameForecast,
    odds: dict[str, object],
    *,
    win_prob_override: float | None = None,
    favorite_override: str | None = None,
) -> GameInput | None:
    """由 forecast + preferred 盤口摘要組裝 GameInput；缺核心盤口回傳 None。"""
    ml_h = odds.get("ml_home")
    ml_a = odds.get("ml_away")
    sp_line = odds.get("spread_home_line")
    sp_h = odds.get("spread_home_odds")
    sp_a = odds.get("spread_away_odds")
    total_line = odds.get("total_line")
    ov = odds.get("over_odds")
    un = odds.get("under_odds")

    if any(x is None for x in (ml_h, ml_a, sp_line, sp_h, sp_a, total_line, ov, un)):
        return None

    fav_side: str
    if favorite_override in ("home", "away"):
        fav_side = favorite_override
    elif fc.predicted_winner == fc.home_team:
        fav_side = "home"
    elif fc.predicted_winner == fc.away_team:
        fav_side = "away"
    elif float(fc.home_win_prob) >= float(fc.away_win_prob):
        fav_side = "home"
    else:
        fav_side = "away"

    if win_prob_override is not None:
        win_prob = float(win_prob_override)
    else:
        win_prob = float(fc.home_win_prob if fav_side == "home" else fc.away_win_prob)

    margin_odds = odds.get("margin_odds") or {}
    if not isinstance(margin_odds, dict):
        margin_odds = {}

    return GameInput(
        label=forecast_event_label(fc),
        sport=_sport_kind(fc.sport),
        favorite_side=fav_side,  # type: ignore[arg-type]
        win_prob_favorite=win_prob,
        moneyline_home=float(ml_h),
        moneyline_away=float(ml_a),
        spread_line=float(sp_line),
        spread_home_odds=float(sp_h),
        spread_away_odds=float(sp_a),
        total_line=float(total_line),
        total_over_odds=float(ov),
        total_under_odds=float(un),
        margin_odds={str(k): float(v) for k, v in margin_odds.items()},
        pred_total=float(fc.predicted_total) if fc.predicted_total else None,
        pred_margin=float(fc.predicted_margin) if fc.predicted_margin is not None else None,
    )


def load_games_from_db(
    db: SportsDatabase,
    sport: str,
    *,
    days_ahead: int = 7,
    game_ids: list[int] | None = None,
    require_odds: bool = True,
    svc: PredictionService | None = None,
) -> list[LoadedGame]:
    """
    載入今日起 N 天賽事（或指定 game_id），附模型預測與 preferred 盤口。
    """
    prediction_svc = svc or PredictionService(db)
    forecasts = prediction_svc.run_upcoming(sport, days_ahead=days_ahead)  # type: ignore[arg-type]

    if game_ids:
        id_set = {int(g) for g in game_ids}
        forecasts = [f for f in forecasts if f.game_id in id_set]

    loaded: list[LoadedGame] = []
    for fc in forecasts:
        if not fc.game_id:
            continue
        odds = summarize_preferred_odds(db, int(fc.game_id))
        if require_odds and not odds.get("has_core"):
            continue
        gi = game_input_from_forecast(fc, odds)
        if gi is None:
            continue
        loaded.append(
            LoadedGame(
                game_input=gi,
                forecast=fc,
                odds_meta=odds,
                game_id=int(fc.game_id),
            )
        )
    return loaded


def list_upcoming_with_odds_status(
    db: SportsDatabase,
    sport: str,
    *,
    days_ahead: int = 7,
    svc: PredictionService | None = None,
) -> list[dict[str, object]]:
    """列出前瞻賽事及盤口完整度（供 CLI / Streamlit 選單）。"""
    prediction_svc = svc or PredictionService(db)
    forecasts = prediction_svc.run_upcoming(sport, days_ahead=days_ahead)  # type: ignore[arg-type]
    rows: list[dict[str, object]] = []
    for fc in forecasts:
        if not fc.game_id:
            continue
        odds = summarize_preferred_odds(db, int(fc.game_id))
        rows.append(
            {
                "game_id": int(fc.game_id),
                "label": forecast_event_label(fc),
                "match_date": fc.match_date,
                "has_core_odds": bool(odds.get("has_core")),
                "margin_count": len(odds.get("margin_odds") or {}),
                "bookmakers": odds.get("bookmakers") or [],
                "home_win_prob": float(fc.home_win_prob),
                "predicted_winner": fc.predicted_winner,
            }
        )
    return rows
