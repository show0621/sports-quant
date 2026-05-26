"""產生、儲存與覆盤賽事預測。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

import pandas as pd

from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_logos import espn_logo_url
from sportsbet.models.analytics_engine import AnalyticsEngine
from sportsbet.models.forecast import GameForecast, build_game_forecast, forecasts_to_matchup_table

Sport = Literal["nba", "mlb"]


class PredictionService:
    def __init__(self, db: SportsDatabase | None = None):
        self.db = db or SportsDatabase()

    def forecast_game_row(
        self,
        sport: Sport,
        game_row: pd.Series,
        stats: pd.DataFrame,
        *,
        total_line: float | None = None,
    ) -> GameForecast | None:
        ht, at = game_row["home_team"], game_row["away_team"]
        if ht not in stats.index or at not in stats.index:
            return None
        h, a = stats.loc[ht], stats.loc[at]
        engine = AnalyticsEngine(sport)
        return build_game_forecast(
            engine,
            ht,
            at,
            float(h["rs_per_game"]),
            float(h["ra_per_game"]),
            float(a["rs_per_game"]),
            float(a["ra_per_game"]),
            match_date=str(game_row.get("match_date", ""))[:10],
            sport=sport,
            home_games=int(h.get("games", 0)),
            away_games=int(a.get("games", 0)),
            home_season_win_pct=float(h["win_pct"]) if pd.notna(h.get("win_pct")) else None,
            away_season_win_pct=float(a["win_pct"]) if pd.notna(a.get("win_pct")) else None,
            home_recent_win_pct=float(h["recent_win_pct"]) if pd.notna(h.get("recent_win_pct")) else None,
            away_recent_win_pct=float(a["recent_win_pct"]) if pd.notna(a.get("recent_win_pct")) else None,
            total_line=total_line,
            match_datetime=str(game_row["match_datetime"]) if pd.notna(game_row.get("match_datetime")) else None,
            home_logo_url=(
                str(game_row["home_logo_url"])
                if pd.notna(game_row.get("home_logo_url"))
                else espn_logo_url(ht, sport)
            ),
            away_logo_url=(
                str(game_row["away_logo_url"])
                if pd.notna(game_row.get("away_logo_url"))
                else espn_logo_url(at, sport)
            ),
            game_id=int(game_row["id"]) if pd.notna(game_row.get("id")) else int(game_row.get("game_id", 0)),
            status=str(game_row.get("status", "scheduled")),
            actual_home_score=int(game_row["home_score"]) if pd.notna(game_row.get("home_score")) else None,
            actual_away_score=int(game_row["away_score"]) if pd.notna(game_row.get("away_score")) else None,
            db=self.db,
        )

    def run_for_date(self, sport: Sport, match_date: str | None = None) -> list[GameForecast]:
        d = match_date or date.today().isoformat()
        games = self.db.get_games(sport, d)
        if games.empty:
            return []
        stats = self.db.get_team_stats(sport).set_index("team")
        forecasts: list[GameForecast] = []
        for _, g in games.drop_duplicates(subset=["home_team", "away_team"]).iterrows():
            board = self.db.get_daily_board(sport, d)
            line = None
            if not board.empty:
                totals = board[(board["game_id"] == g["id"]) & (board["market"] == "total")]
                if not totals.empty and pd.notna(totals.iloc[0].get("handicap")):
                    line = float(totals.iloc[0]["handicap"])
            fc = self.forecast_game_row(sport, g, stats, total_line=line)
            if fc:
                self.db.upsert_game_forecast(fc)
                forecasts.append(fc)
        return forecasts

    def run_backtest_reconcile(self, sport: Sport) -> pd.DataFrame:
        """對所有已結束賽事重新預測並寫入覆盤紀錄。"""
        games = self.db.get_games(sport, with_scores_only=True)
        if games.empty:
            return pd.DataFrame()
        stats = self.db.get_team_stats(sport).set_index("team")
        forecasts: list[GameForecast] = []
        for _, g in games.iterrows():
            g = g.copy()
            g["status"] = "final"
            fc = self.forecast_game_row(sport, g, stats)
            if fc:
                self.db.upsert_game_forecast(fc)
                forecasts.append(fc)
        return forecasts_to_matchup_table(forecasts)

    def get_review_table(self, sport: Sport, *, final_only: bool = True) -> pd.DataFrame:
        df = self.db.get_forecast_review(sport, final_only=final_only)
        if df.empty:
            return df
        out = df.copy()
        out["預測正確"] = out["pick_correct"].map({1: "✓", 0: "✗", None: "—"})
        return out

    def run_upcoming(
        self,
        sport: Sport,
        *,
        days_ahead: int = 14,
    ) -> list[GameForecast]:
        """對現在/未來賽事產生預測並寫入資料庫。"""
        games = self.db.get_upcoming_games(sport, days_ahead=days_ahead)
        if games.empty:
            return []
        stats = self.db.get_team_stats(sport).set_index("team")
        forecasts: list[GameForecast] = []
        for _, g in games.drop_duplicates(subset=["id"]).iterrows():
            d = str(g["match_date"])[:10]
            board = self.db.get_daily_board(sport, d)
            line = None
            if not board.empty:
                totals = board[(board["game_id"] == g["id"]) & (board["market"] == "total")]
                if not totals.empty and pd.notna(totals.iloc[0].get("handicap")):
                    line = float(totals.iloc[0]["handicap"])
            fc = self.forecast_game_row(sport, g, stats, total_line=line)
            if fc and fc.status not in ("final", "FT", "AOT", "Finished", "POST"):
                self.db.upsert_game_forecast(fc)
                forecasts.append(fc)
        return forecasts

    def get_upcoming_forecasts(
        self,
        sport: Sport,
        *,
        days_ahead: int = 14,
        refresh: bool = True,
    ) -> list[GameForecast]:
        if refresh:
            return self.run_upcoming(sport, days_ahead=days_ahead)
        games = self.db.get_upcoming_games(sport, days_ahead=days_ahead)
        stats = self.db.get_team_stats(sport).set_index("team")
        return [
            fc
            for _, g in games.iterrows()
            if (fc := self.forecast_game_row(sport, g, stats)) is not None
        ]

    def upcoming_summary_table(self, forecasts: list[GameForecast]) -> pd.DataFrame:
        """現在/未來賽事預測總表。"""
        from sportsbet.ui.matchup_display import format_match_datetime

        rows = []
        today = date.today().isoformat()
        for f in forecasts:
            d_str, t_str = format_match_datetime(f.match_datetime, f.match_date)
            rows.append(
                {
                    "區間": "今日" if f.match_date == today else "未來",
                    "日期": d_str,
                    "開賽時間": t_str,
                    "主隊": f.home_team,
                    "客隊": f.away_team,
                    "預測勝者": f.predicted_winner,
                    "主隊勝率": f.home_win_prob,
                    "客隊勝率": f.away_win_prob,
                    "主隊勝率(傷兵前)": f.home_win_prob_base,
                    "客隊勝率(傷兵前)": f.away_win_prob_base,
                    "主隊傷兵修正": f.home_injury_adj,
                    "客隊傷兵修正": f.away_injury_adj,
                    "預估比分": f"{f.predicted_home_score:.0f}-{f.predicted_away_score:.0f}",
                    "預估總分": f.predicted_total,
                    "大小分線": f.total_line,
                    "大分機率": f.prob_over,
                    "預估分差": f.predicted_margin,
                    "狀態": f.status,
                }
            )
        return pd.DataFrame(rows)

    def get_upcoming_and_today(self, sport: Sport) -> list[GameForecast]:
        return self.run_upcoming(sport, days_ahead=0) + self.run_upcoming(
            sport, days_ahead=14
        )
