"""產生、儲存與覆盤賽事預測。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

import pandas as pd

from sportsbet.data.database import SportsDatabase
from sportsbet.data.point_in_time_stats import PointInTimeStatsBuilder
from sportsbet.data.team_logos import espn_logo_url
from sportsbet.models.analytics_engine import AnalyticsEngine
from sportsbet.models.forecast import (
    GameForecast,
    build_game_forecast,
    forecast_event_label,
    forecasts_to_matchup_table,
)

Sport = Literal["nba", "mlb"]

_FINISHED = ("final", "FT", "AOT", "Finished", "POST")


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
        use_roster: bool = True,
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
            use_roster=use_roster,
            season_type=str(game_row["season_type"]) if pd.notna(game_row.get("season_type")) else None,
            competition_note=str(game_row["competition_note"]) if pd.notna(game_row.get("competition_note")) else None,
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

    def run_backtest_reconcile(
        self,
        sport: Sport,
        *,
        only_missing: bool = False,
        game_ids: list[int] | None = None,
    ) -> pd.DataFrame:
        """對已結束賽事重新預測（賽前 stats，無傷兵前視偏差）。"""
        if game_ids is not None:
            games = self.db.get_games_by_ids(game_ids)
        elif only_missing:
            games = self.db.get_scored_games_missing_forecast(sport)
        else:
            games = self.db.get_games(sport, with_scores_only=True)
        if games.empty:
            return pd.DataFrame()

        games = games.sort_values(["match_date", "id"]).reset_index(drop=True)
        builder = PointInTimeStatsBuilder.from_db(self.db, sport)
        forecasts: list[GameForecast] = []
        total = len(games)

        for i, (_, g) in enumerate(games.iterrows(), start=1):
            g = g.copy()
            g["status"] = "final"
            d = str(g["match_date"])[:10]
            stats = builder.snapshot_before(d)
            if stats.empty or g["home_team"] not in stats.index or g["away_team"] not in stats.index:
                continue
            gid = int(g["id"])
            line = self.db.get_market_line(gid, "total")
            fc = self.forecast_game_row(sport, g, stats, total_line=line, use_roster=False)
            if fc:
                self.db.upsert_game_forecast(fc)
                forecasts.append(fc)
            if i % 200 == 0 or i == total:
                import logging
                logging.getLogger(__name__).info(
                    "backtest reconcile sport=%s %d/%d", sport, i, total,
                )

        return forecasts_to_matchup_table(forecasts)

    def get_review_table(self, sport: Sport, *, final_only: bool = True) -> pd.DataFrame:
        from sportsbet.data.team_names import is_cross_sport_game, team_belongs_to_sport

        df = self.db.get_forecast_review(sport, final_only=final_only)
        if df.empty:
            return df
        valid = []
        for _, row in df.iterrows():
            h, a = str(row["home_team"]), str(row["away_team"])
            if is_cross_sport_game(sport, h, a):
                continue
            if not team_belongs_to_sport(h, sport) or not team_belongs_to_sport(a, sport):
                continue
            valid.append(row)
        if not valid:
            return pd.DataFrame()
        out = pd.DataFrame(valid).reset_index(drop=True)
        out["預測正確"] = out["pick_correct"].map({1: "✓", 0: "✗", None: "—"})
        return out

    def _refresh_team_stats(self, sport: Sport) -> None:
        """依 DB 已完賽結果更新 team_stats（含近況勝率）。"""
        from sportsbet.data.api_sports import calendar_season
        from sportsbet.data.team_stats import build_team_stats_from_games, persist_team_stats

        games = self.db.get_games(sport, with_scores_only=True)
        if games.empty:
            return
        stats = build_team_stats_from_games(games, sport)
        if not stats.empty:
            persist_team_stats(self.db, sport, stats, season=calendar_season(sport))

    def ensure_schedule_sync(self, sport: Sport, *, days_ahead: int) -> int:
        """向 ESPN 補抓今日起 N 天賽程（若該日尚無賽事）。"""
        from sportsbet.data.espn_schedule import EspnScheduleClient

        today = date.today()
        client = EspnScheduleClient()
        synced = 0
        for offset in range(days_ahead + 1):
            d = (today + timedelta(days=offset)).isoformat()
            existing = self.db.get_games(sport, d)
            if not existing.empty:
                continue
            df = client.sync_date_to_database(self.db, sport, d)
            synced += len(df)
        return synced

    def _stats_for_game(
        self,
        sport: Sport,
        g: pd.Series,
        builder: PointInTimeStatsBuilder,
        fallback: pd.DataFrame,
    ) -> pd.DataFrame:
        """依開賽日取賽前 stats（含該日前所有完賽，如前一場 G2 結果）。"""
        from sportsbet.ui.matchup_display import taipei_match_date

        tw = taipei_match_date(
            str(g["match_datetime"]) if pd.notna(g.get("match_datetime")) else None,
            str(g["match_date"])[:10],
        )
        as_of = (date.fromisoformat(tw) + timedelta(days=1)).isoformat()
        stats = builder.snapshot_before(as_of)
        if stats.empty or g["home_team"] not in stats.index or g["away_team"] not in stats.index:
            if not fallback.empty:
                return fallback
            self._refresh_team_stats(sport)
            return self.db.get_team_stats(sport).set_index("team")
        return stats

    def _collect_dashboard_games(self, sport: Sport, *, days_ahead: int) -> pd.DataFrame:
        """今日（台灣）至未來區間的所有賽事，含今日已完賽。"""
        from sportsbet.ui.matchup_display import taipei_match_date

        today = date.today()
        end = today + timedelta(days=days_ahead)
        start_buf = (today - timedelta(days=1)).isoformat()
        end_buf = (end + timedelta(days=1)).isoformat()
        raw = self.db.get_games_in_range(sport, start_buf, end_buf)
        if raw.empty:
            return raw

        today_str = today.isoformat()
        end_str = end.isoformat()
        rows: list[pd.Series] = []
        for _, g in raw.drop_duplicates(subset=["id"]).iterrows():
            tw = taipei_match_date(
                str(g["match_datetime"]) if pd.notna(g.get("match_datetime")) else None,
                str(g["match_date"])[:10],
            )
            if today_str <= tw <= end_str:
                rows.append(g)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).drop_duplicates(subset=["id"])

    def run_upcoming(
        self,
        sport: Sport,
        *,
        days_ahead: int = 14,
    ) -> list[GameForecast]:
        """對現在/未來賽事產生預測；今日（台灣）含已完賽，作為當日儀表板。"""
        from sportsbet.ui.matchup_display import taipei_match_date

        self._refresh_team_stats(sport)
        games = self._collect_dashboard_games(sport, days_ahead=days_ahead)
        if games.empty:
            return []

        games = games.sort_values(["match_date", "match_datetime", "id"], na_position="last")
        fallback = self.db.get_team_stats(sport).set_index("team")
        builder = PointInTimeStatsBuilder.from_db(self.db, sport)
        today_str = date.today().isoformat()
        forecasts: list[GameForecast] = []
        for _, g in games.drop_duplicates(subset=["id"]).iterrows():
            ht, at = str(g["home_team"]), str(g["away_team"])
            from sportsbet.data.team_names import is_cross_sport_game, team_belongs_to_sport

            if is_cross_sport_game(sport, ht, at):
                continue
            if not team_belongs_to_sport(ht, sport) or not team_belongs_to_sport(at, sport):
                continue
            stats = self._stats_for_game(sport, g, builder, fallback)
            d = str(g["match_date"])[:10]
            gid = int(g["id"])
            line = self.db.get_market_line(gid, "total")
            if line is None:
                board = self.db.get_daily_board(sport, d)
                if not board.empty:
                    totals = board[(board["game_id"] == gid) & (board["market"] == "total")]
                    if not totals.empty and pd.notna(totals.iloc[0].get("handicap")):
                        line = float(totals.iloc[0]["handicap"])
            fc = self.forecast_game_row(sport, g, stats, total_line=line, use_roster=True)
            if not fc:
                continue
            tw = taipei_match_date(fc.match_datetime, fc.match_date)
            is_today = tw == today_str
            if fc.status in _FINISHED and not is_today:
                continue
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
        games = self._collect_dashboard_games(sport, days_ahead=days_ahead)
        stats = self.db.get_team_stats(sport).set_index("team")
        return [
            fc
            for _, g in games.iterrows()
            if (fc := self.forecast_game_row(sport, g, stats)) is not None
        ]

    def upcoming_summary_table(self, forecasts: list[GameForecast]) -> pd.DataFrame:
        """現在/未來賽事預測總表。"""
        from sportsbet.data.team_names import team_bilingual
        from sportsbet.ui.matchup_display import format_match_datetime, taipei_match_date
        from sportsbet.ui.odds_display import summarize_game_odds

        rows = []
        today = date.today().isoformat()
        for f in forecasts:
            d_str, t_str = format_match_datetime(f.match_datetime, f.match_date)
            tw_date = taipei_match_date(f.match_datetime, f.match_date)
            tag = forecast_event_label(f)
            h_en, h_zh = team_bilingual(f.home_team, f.sport)
            a_en, a_zh = team_bilingual(f.away_team, f.sport)
            odds = summarize_game_odds(self.db, f.game_id)
            rows.append(
                {
                    "區間": "今日" if tw_date == today else "未來",
                    "日期": d_str,
                    "開賽時間": t_str,
                    "賽事性質": tag or "—",
                    "主隊": f"{h_en} / {h_zh}" if h_zh else h_en,
                    "客隊": f"{a_en} / {a_zh}" if a_zh else a_en,
                    "預測勝者": f.predicted_winner,
                    "主隊勝率": f.home_win_prob,
                    "客隊勝率": f.away_win_prob,
                    "主隊勝率(傷兵前)": f.home_win_prob_base,
                    "客隊勝率(傷兵前)": f.away_win_prob_base,
                    "主隊傷兵修正": f.home_injury_adj,
                    "客隊傷兵修正": f.away_injury_adj,
                    "預估比分": f"{f.predicted_home_score:.0f}-{f.predicted_away_score:.0f}",
                    "預估總分": f.predicted_total,
                    "大小分線": odds.get("total_line") or f.total_line,
                    "大分機率": f.prob_over,
                    "讓分(主)": odds.get("spread_home_line"),
                    "主勝賠率": odds.get("ml_home"),
                    "客勝賠率": odds.get("ml_away"),
                    "預估分差": f.predicted_margin,
                    "狀態": f.status,
                }
            )
        return pd.DataFrame(rows)

    def get_upcoming_and_today(self, sport: Sport) -> list[GameForecast]:
        return self.run_upcoming(sport, days_ahead=0) + self.run_upcoming(
            sport, days_ahead=14
        )

    def recompute_all_forecasts(
        self,
        sport: Sport,
        *,
        days_ahead: int | None = None,
        include_history: bool = True,
    ) -> dict[str, int]:
        """重算今日/未來與歷史覆盤預測（完整貝氏集成管線）。"""
        from sportsbet import config

        ahead = days_ahead if days_ahead is not None else config.SCHEDULE_SYNC_DAYS_AHEAD
        self._refresh_team_stats(sport)
        upcoming = self.run_upcoming(sport, days_ahead=ahead)
        history_n = 0
        if include_history:
            review = self.run_backtest_reconcile(sport, only_missing=False)
            history_n = len(review)
        return {"upcoming": len(upcoming), "history": history_n}
