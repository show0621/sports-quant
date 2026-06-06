"""賽事帳本：從指定日起累積每場賽前/賽後完整快照。"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

import pandas as pd

from sportsbet import config
from sportsbet.data.database import SportsDatabase

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]


def _df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    df = df.loc[:, ~df.columns.duplicated()]
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _series_dict(row: pd.Series | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return json.loads(pd.Series(row).to_json(date_format="iso"))


def _bet_won(
    market: str,
    selection: str | None,
    handicap: float | None,
    home_score: int,
    away_score: int,
) -> int | None:
    total = home_score + away_score
    if market == "moneyline":
        if selection == "home":
            return 1 if home_score > away_score else 0
        if selection == "away":
            return 1 if away_score > home_score else 0
    if market == "total" and handicap is not None:
        if selection == "over":
            return 1 if total > handicap else 0
        if selection == "under":
            return 1 if total < handicap else 0
    if market == "spread" and handicap is not None and selection in ("home", "away"):
        if selection == "home":
            return 1 if home_score + handicap > away_score else 0
        return 1 if away_score + handicap > home_score else 0
    return None


def _build_bet_results(
    predictions: pd.DataFrame,
    odds: pd.DataFrame,
    home_score: int,
    away_score: int,
) -> list[dict[str, Any]]:
    from sportsbet import analytics

    bankroll = config.INITIAL_BANKROLL
    rows: list[dict[str, Any]] = []
    if predictions.empty or odds.empty:
        return rows

    odds_by_key = {
        (str(r["market"]), str(r["selection"])): r for _, r in odds.iterrows()
    }
    for _, pred in predictions.iterrows():
        key = (str(pred["market"]), str(pred.get("selection") or ""))
        odd_row = odds_by_key.get(key)
        if odd_row is None:
            continue
        prob = float(pred["model_prob"])
        odds_val = float(odd_row["odds"])
        handicap = (
            float(odd_row["handicap"]) if pd.notna(odd_row.get("handicap")) else None
        )
        won = _bet_won(
            str(pred["market"]),
            str(pred.get("selection") or ""),
            handicap,
            home_score,
            away_score,
        )
        if won is None:
            continue
        stake_frac = float(pred["stake_fraction"]) if pd.notna(pred.get("stake_fraction")) else 0.0
        if stake_frac <= 0:
            stake_frac = analytics.adjusted_kelly(prob, odds_val, config.KELLY_FRACTION)
        stake = bankroll * stake_frac
        pnl = stake * (odds_val - 1) if won else -stake
        rows.append(
            {
                "market": pred["market"],
                "selection": pred.get("selection"),
                "model_prob": prob,
                "ev": float(pred["ev"]) if pd.notna(pred.get("ev")) else None,
                "odds": odds_val,
                "handicap": handicap,
                "stake_fraction": stake_frac,
                "stake": stake,
                "won": won,
                "pnl": pnl,
            }
        )
    return rows


class GameLedgerService:
    """賽前/賽後快照寫入 game_ledger 表。"""

    def __init__(self, db: SportsDatabase | None = None):
        self.db = db or SportsDatabase()

    def _build_pre_snapshot(self, game: pd.Series) -> dict[str, Any]:
        gid = int(game["id"])
        sport = str(game["sport"])
        match_date = str(game["match_date"])[:10]
        home, away = game["home_team"], game["away_team"]
        stats = self.db.get_team_stats(sport)
        home_stats = stats[stats["team"] == home]
        away_stats = stats[stats["team"] == away]
        return {
            "game": {
                "id": gid,
                "sport": sport,
                "match_date": match_date,
                "match_datetime": game.get("match_datetime"),
                "home_team": home,
                "away_team": away,
                "status": game.get("status"),
            },
            "odds": _df_records(self.db.get_game_odds(gid)),
            "predictions": _df_records(self.db.get_game_predictions(gid)),
            "forecast": _series_dict(self.db.get_game_forecast_row(gid)),
            "team_stats": {
                "home": _df_records(home_stats),
                "away": _df_records(away_stats),
            },
            "player_stats": {
                "home": _df_records(self.db.get_team_player_stats(sport, home)),
                "away": _df_records(self.db.get_team_player_stats(sport, away)),
            },
            "injuries": {
                "home": _df_records(self.db.get_team_injuries(sport, home, match_date)),
                "away": _df_records(self.db.get_team_injuries(sport, away, match_date)),
            },
        }

    def _build_post_snapshot(self, game: pd.Series) -> dict[str, Any]:
        gid = int(game["id"])
        home_score = int(game["home_score"])
        away_score = int(game["away_score"])
        odds = self.db.get_game_odds(gid)
        predictions = self.db.get_game_predictions(gid)
        forecast = self.db.get_game_forecast_row(gid)
        forecast_dict = _series_dict(forecast)
        if forecast_dict:
            actual_winner = (
                game["home_team"]
                if home_score > away_score
                else game["away_team"] if away_score > home_score else "push"
            )
            forecast_dict["actual_home_score"] = home_score
            forecast_dict["actual_away_score"] = away_score
            forecast_dict["actual_winner"] = actual_winner
            pred_winner = forecast_dict.get("predicted_winner")
            forecast_dict["pick_correct"] = (
                1 if pred_winner and pred_winner == actual_winner else 0
            )
        return {
            "game": {
                "id": gid,
                "home_score": home_score,
                "away_score": away_score,
                "total_points": home_score + away_score,
                "margin": home_score - away_score,
                "status": game.get("status"),
            },
            "forecast_result": forecast_dict,
            "bet_results": _build_bet_results(predictions, odds, home_score, away_score),
        }

    def sync_sport(self, sport: Sport) -> dict[str, int]:
        if not config.GAME_LEDGER_ENABLED:
            return {"pre": 0, "post": 0}
        start = config.GAME_LEDGER_START_DATE
        pre_n = post_n = 0

        pre_games = self.db.get_games_for_ledger_pre(sport, start_date=start)
        for _, g in pre_games.iterrows():
            snap = self._build_pre_snapshot(g)
            if not snap["odds"] and not snap["predictions"] and snap["forecast"] is None:
                continue
            self.db.upsert_game_ledger_pre(
                int(g["id"]),
                sport,
                str(g["match_date"])[:10],
                str(g["home_team"]),
                str(g["away_team"]),
                json.dumps(snap, ensure_ascii=False, default=str),
            )
            pre_n += 1

        post_games = self.db.get_games_for_ledger_post(sport, start_date=start)
        for _, g in post_games.iterrows():
            snap = self._build_post_snapshot(g)
            self.db.upsert_game_ledger_post(
                int(g["id"]),
                sport,
                str(g["match_date"])[:10],
                str(g["home_team"]),
                str(g["away_team"]),
                json.dumps(snap, ensure_ascii=False, default=str),
            )
            post_n += 1

        logger.info("game ledger sport=%s pre=%d post=%d", sport, pre_n, post_n)
        return {"pre": pre_n, "post": post_n}

    def sync_all(self) -> dict[str, dict[str, int]]:
        return {"nba": self.sync_sport("nba"), "mlb": self.sync_sport("mlb")}
