"""每日開盤賠率掃描，比對模型 EV（SQLite + 運彩 Blob）。"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from sportsbet.data.database import SportsDatabase
from sportsbet.data.orchestrator import DataOrchestrator
from sportsbet.risk.ev import RiskManager
from sportsbet.services.prediction_service import PredictionService

logger = logging.getLogger(__name__)


class DailyScanner:
    def __init__(self, sport: str = "nba", db: SportsDatabase | None = None):
        self.sport = sport
        self.db = db or SportsDatabase()
        self.orchestrator = DataOrchestrator(self.db)
        self.prediction = PredictionService(self.db)
        self.risk = RiskManager()

    def run(self, *, match_date: str | None = None) -> pd.DataFrame:
        from sportsbet.services.live_sync import LiveSyncService

        d = match_date or date.today().isoformat()
        LiveSyncService(self.db).sync_live(self.sport)  # type: ignore[arg-type]

        board = self.db.get_daily_board(self.sport, d)
        if board.empty:
            logger.warning("無 %s 賽程或賠率", d)
            return pd.DataFrame()

        forecasts = {
            fc.game_id: fc
            for fc in self.prediction.run_for_date(self.sport, d)
            if fc.game_id
        }
        rows = []
        for _, g in board.drop_duplicates(subset=["game_id", "market", "selection"]).iterrows():
            gid = int(g["game_id"])
            fc = forecasts.get(gid)
            if not fc:
                continue
            market = g.get("market", "moneyline")
            sel = g.get("selection", "home")
            if market == "moneyline":
                prob = fc.home_win_prob if sel == "home" else fc.away_win_prob
            elif fc.prob_over is not None:
                prob = fc.prob_over if sel == "over" else (1.0 - fc.prob_over)
            else:
                continue
            odds = float(g["odds"])
            sig = self.risk.evaluate(prob, odds)
            rows.append(
                {
                    "match_date": d,
                    "home_team": g["home_team"],
                    "away_team": g["away_team"],
                    "market": market,
                    "selection": sel,
                    "odds": odds,
                    "model_prob": prob,
                    "ev": sig.ev,
                    "kelly_fraction": sig.kelly_fraction,
                    "stake_fraction": sig.recommended_stake_fraction,
                    "signal": sig.is_positive_ev,
                }
            )

        signals = pd.DataFrame(rows)
        if not signals.empty:
            positive = signals[signals["signal"] == True]  # noqa: E712
            logger.info("掃描完成：%d 筆賠率，%d 筆正 EV", len(signals), len(positive))
        return signals

    def positive_ev_only(self, **kwargs) -> pd.DataFrame:
        df = self.run(**kwargs)
        return df[df["signal"] == True] if not df.empty else df  # noqa: E712
