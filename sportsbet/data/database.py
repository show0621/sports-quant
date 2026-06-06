"""SQLite 本地資料庫：賽程、賠率、球隊統計與預測紀錄。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Generator, Literal

import pandas as pd

from sportsbet import config

Sport = Literal["nba", "mlb"]


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sport TEXT NOT NULL,
    match_date TEXT NOT NULL,
    match_datetime TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_score INTEGER,
    away_score INTEGER,
    status TEXT DEFAULT 'scheduled',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(sport, match_date, home_team, away_team)
);

CREATE TABLE IF NOT EXISTS team_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sport TEXT NOT NULL,
    team TEXT NOT NULL,
    season TEXT,
    rs_per_game REAL NOT NULL,
    ra_per_game REAL NOT NULL,
    games INTEGER DEFAULT 0,
    win_pct REAL,
    recent_win_pct REAL,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(sport, team, season)
);

CREATE TABLE IF NOT EXISTS odds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    handicap REAL,
    odds REAL NOT NULL,
    bookmaker TEXT DEFAULT 'sportslottery',
    odds_phase TEXT DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    selection TEXT,
    model_prob REAL NOT NULL,
    ev REAL,
    kelly_fraction REAL,
    stake_fraction REAL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS game_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER,
    sport TEXT NOT NULL,
    match_date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    status TEXT DEFAULT 'scheduled',
    home_rs REAL, home_ra REAL, away_rs REAL, away_ra REAL,
    home_pyth REAL, away_pyth REAL,
    home_season_win_pct REAL, away_season_win_pct REAL,
    home_recent_win_pct REAL, away_recent_win_pct REAL,
    home_log5_win_pct REAL, away_log5_win_pct REAL,
    home_bayesian_win_pct REAL, away_bayesian_win_pct REAL,
    home_win_prob REAL, away_win_prob REAL,
    predicted_winner TEXT,
    predicted_home_score REAL, predicted_away_score REAL,
    predicted_total REAL, predicted_margin REAL,
    total_line REAL, prob_over REAL, prob_under REAL,
    margin_note TEXT,
    actual_winner TEXT,
    actual_home_score INTEGER, actual_away_score INTEGER,
    pick_correct INTEGER,
    margin_error REAL, total_error REAL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(game_id)
);

CREATE INDEX IF NOT EXISTS idx_games_date ON games(sport, match_date);
CREATE INDEX IF NOT EXISTS idx_odds_game ON odds(game_id);
CREATE INDEX IF NOT EXISTS idx_predictions_game ON predictions(game_id);
CREATE INDEX IF NOT EXISTS idx_forecasts_date ON game_forecasts(sport, match_date);

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sport TEXT NOT NULL,
    team TEXT NOT NULL,
    logo_url TEXT,
    api_team_id INTEGER,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(sport, team)
);

-- V2: 球員微觀數據
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sport TEXT NOT NULL,
    player_id TEXT NOT NULL,
    name TEXT NOT NULL,
    team TEXT NOT NULL,
    position TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(sport, player_id)
);

CREATE TABLE IF NOT EXISTS player_advanced_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sport TEXT NOT NULL,
    player_id TEXT NOT NULL,
    season TEXT,
    as_of_date TEXT NOT NULL,
    window_games INTEGER DEFAULT 10,
    bpm REAL,
    vorp REAL,
    usg_pct REAL,
    pace REAL,
    war REAL,
    wrc_plus REAL,
    fip REAL,
    rolling_off_rating REAL,
    hot_cold_index REAL,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(sport, player_id, as_of_date, window_games),
    FOREIGN KEY (sport, player_id) REFERENCES players(sport, player_id)
);

CREATE TABLE IF NOT EXISTS injury_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sport TEXT NOT NULL,
    player_id TEXT NOT NULL,
    team TEXT NOT NULL,
    report_date TEXT NOT NULL,
    status TEXT NOT NULL,
    injury_type TEXT,
    expected_return TEXT,
    source TEXT DEFAULT 'espn',
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(sport, player_id, report_date),
    FOREIGN KEY (sport, player_id) REFERENCES players(sport, player_id)
);

CREATE TABLE IF NOT EXISTS projected_lineups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sport TEXT NOT NULL,
    team TEXT NOT NULL,
    match_date TEXT NOT NULL,
    player_id TEXT NOT NULL,
    expected_minutes REAL,
    expected_innings REAL,
    is_starter INTEGER DEFAULT 0,
    UNIQUE(sport, team, match_date, player_id)
);

CREATE INDEX IF NOT EXISTS idx_players_team ON players(sport, team);
CREATE INDEX IF NOT EXISTS idx_injury_date ON injury_reports(sport, report_date);
CREATE INDEX IF NOT EXISTS idx_player_stats_date ON player_advanced_stats(sport, as_of_date);

CREATE TABLE IF NOT EXISTS backtest_sync_meta (
    sport TEXT NOT NULL,
    meta_key TEXT NOT NULL,
    meta_value TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(sport, meta_key)
);

CREATE TABLE IF NOT EXISTS team_aliases (
    sport TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    alias TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'builtin',
    PRIMARY KEY (sport, alias, source)
);

CREATE TABLE IF NOT EXISTS sync_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sport TEXT NOT NULL,
    sync_type TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    duration_ms INTEGER,
    synced_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sync_health_sport ON sync_health(sport, sync_type, synced_at);

CREATE TABLE IF NOT EXISTS game_ledger (
    game_id INTEGER PRIMARY KEY,
    sport TEXT NOT NULL,
    match_date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    pre_captured_at TEXT,
    pre_snapshot_json TEXT,
    post_captured_at TEXT,
    post_snapshot_json TEXT,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_game_ledger_date ON game_ledger(sport, match_date);
"""

_MIGRATION_COLUMNS = [
    ("games", "home_logo_url", "TEXT"),
    ("games", "away_logo_url", "TEXT"),
    ("game_forecasts", "home_adjusted_rating", "REAL"),
    ("game_forecasts", "away_adjusted_rating", "REAL"),
    ("game_forecasts", "home_injury_penalty", "REAL"),
    ("game_forecasts", "away_injury_penalty", "REAL"),
    ("game_forecasts", "home_win_prob_base", "REAL"),
    ("game_forecasts", "away_win_prob_base", "REAL"),
    ("game_forecasts", "home_injury_adj", "REAL"),
    ("game_forecasts", "away_injury_adj", "REAL"),
]


class SportsDatabase:
    """SQLite 存取層。"""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (config.DATA_DIR / "sportsbet.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)
            for table, col, typ in _MIGRATION_COLUMNS:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                except sqlite3.OperationalError:
                    pass

    def upsert_game(
        self,
        sport: Sport,
        match_date: str,
        home_team: str,
        away_team: str,
        *,
        match_datetime: str | None = None,
        home_score: int | None = None,
        away_score: int | None = None,
        status: str = "scheduled",
        home_logo_url: str | None = None,
        away_logo_url: str | None = None,
    ) -> int:
        from sportsbet.data.team_names import is_cross_sport_game

        if is_cross_sport_game(sport, home_team, away_team):
            raise ValueError(
                f"cross-sport game rejected: sport={sport} {home_team} vs {away_team}"
            )
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO games (sport, match_date, match_datetime, home_team, away_team,
                                   home_score, away_score, status, home_logo_url, away_logo_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sport, match_date, home_team, away_team) DO UPDATE SET
                    match_datetime=excluded.match_datetime,
                    home_score=COALESCE(excluded.home_score, games.home_score),
                    away_score=COALESCE(excluded.away_score, games.away_score),
                    status=excluded.status,
                    home_logo_url=COALESCE(excluded.home_logo_url, games.home_logo_url),
                    away_logo_url=COALESCE(excluded.away_logo_url, games.away_logo_url)
                """,
                (
                    sport, match_date, match_datetime, home_team, away_team,
                    home_score, away_score, status, home_logo_url, away_logo_url,
                ),
            )
            if cur.lastrowid:
                return int(cur.lastrowid)
            row = conn.execute(
                """
                SELECT id FROM games
                WHERE sport=? AND match_date=? AND home_team=? AND away_team=?
                """,
                (sport, match_date, home_team, away_team),
            ).fetchone()
            return int(row["id"])

    def insert_odds(
        self,
        game_id: int,
        market: str,
        selection: str,
        odds: float,
        *,
        handicap: float | None = None,
        bookmaker: str = "sportslottery",
        odds_phase: str = "close",
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO odds (game_id, market, selection, handicap, odds, bookmaker, odds_phase)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (game_id, market, selection, handicap, odds, bookmaker, odds_phase),
            )

    def upsert_odds(
        self,
        game_id: int,
        market: str,
        selection: str,
        odds: float,
        *,
        handicap: float | None = None,
        bookmaker: str = "jbot",
        odds_phase: str = "close",
    ) -> None:
        """同一 game/market/selection/bookmaker/phase 只保留一筆。"""
        with self.connection() as conn:
            conn.execute(
                """
                DELETE FROM odds
                WHERE game_id = ? AND market = ? AND selection = ?
                  AND bookmaker = ? AND odds_phase = ?
                """,
                (game_id, market, selection, bookmaker, odds_phase),
            )
            conn.execute(
                """
                INSERT INTO odds (game_id, market, selection, handicap, odds, bookmaker, odds_phase)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (game_id, market, selection, handicap, odds, bookmaker, odds_phase),
            )

    def upsert_team_stats(
        self,
        sport: Sport,
        team: str,
        rs_per_game: float,
        ra_per_game: float,
        *,
        season: str | None = None,
        games: int = 0,
        win_pct: float | None = None,
        recent_win_pct: float | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO team_stats (sport, team, season, rs_per_game, ra_per_game,
                                        games, win_pct, recent_win_pct, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sport, team, season) DO UPDATE SET
                    rs_per_game=excluded.rs_per_game,
                    ra_per_game=excluded.ra_per_game,
                    games=excluded.games,
                    win_pct=excluded.win_pct,
                    recent_win_pct=excluded.recent_win_pct,
                    updated_at=excluded.updated_at
                """,
                (
                    sport,
                    team,
                    season or str(date.today().year),
                    rs_per_game,
                    ra_per_game,
                    games,
                    win_pct,
                    recent_win_pct,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def insert_prediction(
        self,
        game_id: int,
        market: str,
        model_prob: float,
        *,
        selection: str | None = None,
        ev: float | None = None,
        kelly_fraction: float | None = None,
        stake_fraction: float | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO predictions (game_id, market, selection, model_prob, ev,
                                         kelly_fraction, stake_fraction)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (game_id, market, selection, model_prob, ev, kelly_fraction, stake_fraction),
            )

    def get_upcoming_games(
        self,
        sport: Sport,
        *,
        from_date: str | None = None,
        days_ahead: int = 14,
    ) -> pd.DataFrame:
        """今日起、未結束的賽事（現在 / 未來）。"""
        start = from_date or date.today().isoformat()
        end = (date.fromisoformat(start) + timedelta(days=days_ahead)).isoformat()
        finished = ("final", "FT", "AOT", "Finished", "POST")
        placeholders = ",".join("?" for _ in finished)
        sql = f"""
            SELECT * FROM games
            WHERE sport = ?
              AND match_date >= ?
              AND match_date <= ?
              AND (status IS NULL OR status NOT IN ({placeholders}))
            ORDER BY match_date, match_datetime, id
        """
        params: list[Any] = [sport, start, end, *finished]
        with self.connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def get_games(
        self,
        sport: Sport,
        match_date: str | None = None,
        *,
        with_scores_only: bool = False,
    ) -> pd.DataFrame:
        sql = "SELECT * FROM games WHERE sport = ?"
        params: list[Any] = [sport]
        if match_date:
            sql += " AND match_date = ?"
            params.append(match_date)
        if with_scores_only:
            sql += (
                " AND home_score IS NOT NULL AND away_score IS NOT NULL"
                " AND (home_score + away_score) > 0"
                " AND match_date <= date('now')"
            )
        sql += " ORDER BY match_date, id"
        with self.connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def upsert_team_logo(
        self,
        sport: Sport,
        team: str,
        logo_url: str | None,
        api_team_id: int | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO teams (sport, team, logo_url, api_team_id, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sport, team) DO UPDATE SET
                    logo_url=COALESCE(excluded.logo_url, teams.logo_url),
                    api_team_id=COALESCE(excluded.api_team_id, teams.api_team_id),
                    updated_at=excluded.updated_at
                """,
                (sport, team, logo_url, api_team_id, datetime.now().isoformat(timespec="seconds")),
            )

    def get_team_logo(self, sport: Sport, team: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT logo_url FROM teams WHERE sport = ? AND team = ?",
                (sport, team),
            ).fetchone()
            return str(row["logo_url"]) if row and row["logo_url"] else None

    def get_team_stats(self, sport: Sport) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM team_stats WHERE sport = ? ORDER BY team",
                conn,
                params=(sport,),
            )

    def get_daily_board(self, sport: Sport, match_date: str | None = None) -> pd.DataFrame:
        """合併賽程、最新賠率與預測，供看板使用。"""
        d = match_date or date.today().isoformat()
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT g.id AS game_id, g.match_date, g.home_team, g.away_team,
                       g.home_score, g.away_score, g.status,
                       o.market, o.selection, o.handicap, o.odds, o.created_at AS odds_updated_at,
                       p.model_prob, p.ev, p.stake_fraction AS kelly_stake
                FROM games g
                LEFT JOIN (
                    SELECT o2.*
                    FROM odds o2
                    INNER JOIN (
                        SELECT game_id, market, selection, MAX(id) AS max_id
                        FROM odds
                        GROUP BY game_id, market, selection
                    ) lo ON o2.id = lo.max_id
                ) o ON o.game_id = g.id
                LEFT JOIN predictions p ON p.game_id = g.id
                    AND p.market = o.market
                    AND (p.selection = o.selection OR p.selection IS NULL)
                WHERE g.sport = ? AND g.match_date = ?
                ORDER BY g.id, o.market, o.selection
                """,
                conn,
                params=(sport, d),
            )

    def clear_odds_for_date(
        self,
        sport: Sport,
        match_date: str,
        *,
        bookmaker: str = "sportslottery",
    ) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """
                DELETE FROM odds
                WHERE bookmaker = ?
                  AND game_id IN (
                      SELECT id FROM games WHERE sport = ? AND match_date = ?
                  )
                """,
                (bookmaker, sport, match_date),
            )
            return cur.rowcount

    def record_sync_health(
        self,
        sport: Sport,
        sync_type: str,
        status: str,
        *,
        message: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO sync_health (sport, sync_type, status, message, duration_ms)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sport, sync_type, status, message, duration_ms),
            )

    def get_last_sync_health(
        self,
        sport: Sport,
        sync_type: str | None = None,
    ) -> pd.DataFrame:
        sql = "SELECT * FROM sync_health WHERE sport = ?"
        params: list = [sport]
        if sync_type:
            sql += " AND sync_type = ?"
            params.append(sync_type)
        sql += " ORDER BY synced_at DESC LIMIT 20"
        with self.connection() as conn:
            return pd.read_sql_query(sql, conn, params=tuple(params))

    def get_sync_status_summary(self, sport: Sport) -> dict[str, str | None]:
        """各 sync_type 最後一次成功/失敗時間。"""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT sync_type, status, message, synced_at
                FROM sync_health
                WHERE sport = ?
                ORDER BY synced_at DESC
                """,
                (sport,),
            ).fetchall()
        summary: dict[str, str | None] = {}
        for row in rows:
            key = str(row["sync_type"])
            if key not in summary:
                summary[key] = str(row["synced_at"])
        for meta_key, label in (
            ("live_synced_at", "live"),
            ("daily_synced_at", "daily"),
            ("backtest_refreshed_at", "backtest"),
        ):
            if label not in summary:
                val = self.get_backtest_sync_meta(sport, meta_key)
                if val:
                    summary[label] = val
        return summary

    def upsert_game_forecast(self, forecast: Any) -> None:
        row = forecast.to_db_row()
        if not row.get("game_id"):
            return
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "game_id")
        with self.connection() as conn:
            conn.execute(
                f"""
                INSERT INTO game_forecasts ({", ".join(cols)})
                VALUES ({placeholders})
                ON CONFLICT(game_id) DO UPDATE SET {updates}
                """,
                tuple(row[c] for c in cols),
            )

    def get_upcoming_forecast_review(self, sport: Sport) -> pd.DataFrame:
        """已儲存的現在/未來預測紀錄（未結束賽事）。"""
        finished = ("final", "FT", "AOT", "Finished", "POST")
        placeholders = ",".join("?" for _ in finished)
        with self.connection() as conn:
            return pd.read_sql_query(
                f"""
                SELECT f.*, g.match_datetime, g.status AS game_status,
                       g.home_logo_url, g.away_logo_url
                FROM game_forecasts f
                JOIN games g ON g.id = f.game_id AND g.sport = f.sport
                WHERE f.sport = ?
                  AND g.match_date >= date('now')
                  AND (g.status IS NULL OR g.status NOT IN ({placeholders}))
                ORDER BY g.match_date, g.match_datetime
                """,
                conn,
                params=(sport, *finished),
            )

    def get_forecast_review(self, sport: Sport, *, final_only: bool = True) -> pd.DataFrame:
        sql = """
            SELECT f.match_date, f.home_team, f.away_team, f.status,
                   f.predicted_winner, f.actual_winner, f.pick_correct,
                   f.home_win_prob, f.away_win_prob,
                   f.home_win_prob_base, f.away_win_prob_base,
                   f.home_injury_adj, f.away_injury_adj,
                   f.home_injury_penalty, f.away_injury_penalty,
                   f.home_pyth, f.away_pyth,
                   f.home_season_win_pct, f.away_season_win_pct,
                   f.home_recent_win_pct, f.away_recent_win_pct,
                   f.home_bayesian_win_pct, f.away_bayesian_win_pct,
                   f.predicted_home_score, f.predicted_away_score, f.predicted_total,
                   f.actual_home_score, f.actual_away_score,
                   f.predicted_margin, f.margin_error, f.total_error,
                   f.total_line, f.prob_over, f.prob_under, f.margin_note
            FROM game_forecasts f
            JOIN games g ON g.id = f.game_id AND g.sport = f.sport
            WHERE f.sport = ?
        """
        params: list[Any] = [sport]
        if final_only:
            sql += " AND f.status = 'final' AND f.actual_winner IS NOT NULL"
        sql += " ORDER BY f.match_date DESC, f.id DESC"
        with self.connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def get_forecasts_by_date(self, sport: Sport, match_date: str) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM game_forecasts WHERE sport = ? AND match_date = ? ORDER BY id",
                conn,
                params=(sport, match_date),
            )

    def upsert_player(
        self,
        sport: Sport,
        player_id: str,
        name: str,
        team: str,
        position: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO players (sport, player_id, name, team, position, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(sport, player_id) DO UPDATE SET
                    name=excluded.name, team=excluded.team,
                    position=excluded.position, updated_at=excluded.updated_at
                """,
                (sport, player_id, name, team, position, datetime.now().isoformat(timespec="seconds")),
            )

    def upsert_player_stats(
        self,
        sport: Sport,
        player_id: str,
        as_of_date: str,
        *,
        window_games: int = 10,
        season: str | None = None,
        bpm: float | None = None,
        vorp: float | None = None,
        usg_pct: float | None = None,
        pace: float | None = None,
        war: float | None = None,
        wrc_plus: float | None = None,
        fip: float | None = None,
        rolling_off_rating: float | None = None,
        hot_cold_index: float | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO player_advanced_stats (
                    sport, player_id, season, as_of_date, window_games,
                    bpm, vorp, usg_pct, pace, war, wrc_plus, fip,
                    rolling_off_rating, hot_cold_index, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sport, player_id, as_of_date, window_games) DO UPDATE SET
                    bpm=excluded.bpm, vorp=excluded.vorp, usg_pct=excluded.usg_pct,
                    pace=excluded.pace, war=excluded.war, wrc_plus=excluded.wrc_plus,
                    fip=excluded.fip, rolling_off_rating=excluded.rolling_off_rating,
                    hot_cold_index=excluded.hot_cold_index, updated_at=excluded.updated_at
                """,
                (
                    sport, player_id, season or str(date.today().year), as_of_date, window_games,
                    bpm, vorp, usg_pct, pace, war, wrc_plus, fip,
                    rolling_off_rating, hot_cold_index,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def upsert_injury(
        self,
        sport: Sport,
        player_id: str,
        team: str,
        report_date: str,
        status: str,
        *,
        injury_type: str | None = None,
        expected_return: str | None = None,
        source: str = "espn",
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO injury_reports
                (sport, player_id, team, report_date, status, injury_type, expected_return, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sport, player_id, report_date) DO UPDATE SET
                    status=excluded.status, injury_type=excluded.injury_type,
                    expected_return=excluded.expected_return, source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (
                    sport, player_id, team, report_date, status,
                    injury_type, expected_return, source,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def upsert_projected_lineup(
        self,
        sport: Sport,
        team: str,
        match_date: str,
        player_id: str,
        *,
        expected_minutes: float | None = None,
        expected_innings: float | None = None,
        is_starter: bool = False,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO projected_lineups
                (sport, team, match_date, player_id, expected_minutes, expected_innings, is_starter)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sport, team, match_date, player_id) DO UPDATE SET
                    expected_minutes=excluded.expected_minutes,
                    expected_innings=excluded.expected_innings,
                    is_starter=excluded.is_starter
                """,
                (
                    sport, team, match_date, player_id,
                    expected_minutes, expected_innings, int(is_starter),
                ),
            )

    def get_players_by_team(self, sport: Sport, team: str) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT p.*, s.bpm, s.vorp, s.usg_pct, s.pace, s.war, s.wrc_plus, s.fip,
                       s.rolling_off_rating, s.hot_cold_index, s.window_games, s.as_of_date
                FROM players p
                LEFT JOIN player_advanced_stats s ON s.sport = p.sport AND s.player_id = p.player_id
                WHERE p.sport = ? AND p.team = ?
                ORDER BY COALESCE(s.vorp, s.war, 0) DESC
                """,
                conn,
                params=(sport, team),
            )

    def clear_injuries(self, sport: Sport, *, source: str | None = "espn") -> int:
        with self.connection() as conn:
            if source:
                cur = conn.execute(
                    "DELETE FROM injury_reports WHERE sport = ? AND source = ?",
                    (sport, source),
                )
            else:
                cur = conn.execute("DELETE FROM injury_reports WHERE sport = ?", (sport,))
            return cur.rowcount

    def get_injuries(self, sport: Sport, report_date: str | None = None) -> pd.DataFrame:
        d = report_date or date.today().isoformat()
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT i.*, p.name AS player_name
                FROM injury_reports i
                JOIN players p ON p.sport = i.sport AND p.player_id = i.player_id
                WHERE i.sport = ? AND i.report_date = ?
                ORDER BY i.team, i.status
                """,
                conn,
                params=(sport, d),
            )

    def get_projected_lineup(self, sport: Sport, team: str, match_date: str) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM projected_lineups WHERE sport=? AND team=? AND match_date=?",
                conn,
                params=(sport, team, match_date),
            )

    def get_player_hot_cold(self, sport: Sport, *, limit: int = 50) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT p.name, p.team, p.position, s.hot_cold_index,
                       s.rolling_off_rating, s.vorp, s.war, s.as_of_date
                FROM player_advanced_stats s
                JOIN players p ON p.sport = s.sport AND p.player_id = s.player_id
                WHERE s.sport = ? AND s.hot_cold_index IS NOT NULL
                ORDER BY ABS(s.hot_cold_index) DESC
                LIMIT ?
                """,
                conn,
                params=(sport, limit),
            )

    def get_games_in_range(
        self,
        sport: Sport,
        start_date: str,
        end_date: str,
        *,
        final_only: bool = False,
    ) -> pd.DataFrame:
        sql = "SELECT * FROM games WHERE sport = ? AND match_date >= ? AND match_date <= ?"
        if final_only:
            sql += " AND status = 'final'"
        sql += " ORDER BY match_date"
        with self.connection() as conn:
            return pd.read_sql_query(sql, conn, params=(sport, start_date, end_date))

    def cleanup_placeholder_final_games(self, sport: Sport) -> int:
        """修正未開賽或未得分卻標為 final 的占位賽事。"""
        with self.connection() as conn:
            cur = conn.execute(
                """
                UPDATE games
                SET status = 'scheduled',
                    home_score = NULL,
                    away_score = NULL
                WHERE sport = ?
                  AND status = 'final'
                  AND (
                      match_date > date('now')
                      OR (
                          home_score IS NOT NULL AND away_score IS NOT NULL
                          AND (home_score + away_score) = 0
                      )
                  )
                """,
                (sport,),
            )
            return cur.rowcount

    def purge_cross_sport_games(self, sport: Sport | None = None) -> int:
        """刪除 sport 欄位與隊名不符的污染賽事及關聯資料。"""
        from sportsbet.data.team_names import is_cross_sport_game

        sports: tuple[Sport, ...] = (sport,) if sport else ("nba", "mlb")
        removed = 0
        with self.connection() as conn:
            for sp in sports:
                rows = conn.execute(
                    "SELECT id, home_team, away_team FROM games WHERE sport = ?",
                    (sp,),
                ).fetchall()
                bad_ids = [
                    int(r["id"])
                    for r in rows
                    if is_cross_sport_game(sp, r["home_team"], r["away_team"])
                ]
                if not bad_ids:
                    continue
                ph = ",".join("?" for _ in bad_ids)
                for table, col in (
                    ("predictions", "game_id"),
                    ("odds", "game_id"),
                    ("game_forecasts", "game_id"),
                ):
                    conn.execute(f"DELETE FROM {table} WHERE {col} IN ({ph})", bad_ids)
                conn.execute(f"DELETE FROM games WHERE id IN ({ph})", bad_ids)
                removed += len(bad_ids)
        return removed

    def clip_prediction_probabilities(self) -> int:
        """修正浮點誤差導致 model_prob 略大於 1 的紀錄。"""
        with self.connection() as conn:
            cur = conn.execute(
                """
                UPDATE predictions
                SET model_prob = MIN(model_prob, 1.0)
                WHERE model_prob > 1.0 OR model_prob < 0.0
                """
            )
            return cur.rowcount

    def finalize_games_with_scores(self, sport: Sport) -> int:
        """將已有有效比分且賽日不晚於今日的賽事標記為 final。"""
        with self.connection() as conn:
            cur = conn.execute(
                """
                UPDATE games
                SET status = 'final'
                WHERE sport = ?
                  AND home_score IS NOT NULL
                  AND away_score IS NOT NULL
                  AND (home_score + away_score) > 0
                  AND match_date <= date('now')
                  AND (status IS NULL OR status NOT IN ('final', 'FT', 'AOT', 'Finished', 'POST'))
                """,
                (sport,),
            )
            return cur.rowcount

    def count_games_with_scores(self, sport: Sport) -> int:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM games
                WHERE sport = ? AND home_score IS NOT NULL AND away_score IS NOT NULL
                """,
                (sport,),
            ).fetchone()
            return int(row["n"]) if row else 0

    def count_odds_for_date(self, sport: Sport, match_date: str) -> int:
        """某天是否已存在 odds（用於避免反覆抓取）。"""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM odds o
                JOIN games g ON g.id = o.game_id
                WHERE g.sport = ?
                  AND g.match_date = ?
                """,
                (sport, match_date),
            ).fetchone()
            return int(row["n"]) if row else 0

    def count_scored_games_missing_forecast(self, sport: Sport) -> int:
        """已完賽（有分數）但尚未產生 game_forecasts 的場次數量。"""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM games g
                LEFT JOIN game_forecasts f ON f.game_id = g.id
                WHERE g.sport = ?
                  AND g.status = 'final'
                  AND g.home_score IS NOT NULL
                  AND g.away_score IS NOT NULL
                  AND (g.home_score + g.away_score) > 0
                  AND g.match_date <= date('now')
                  AND f.game_id IS NULL
                """,
                (sport,),
            ).fetchone()
            return int(row["n"]) if row else 0

    def count_scored_games_missing_predictions(self, sport: Sport) -> int:
        """已完賽（有分數）但尚未產生 predictions 的場次數量。"""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM games g
                LEFT JOIN predictions p ON p.game_id = g.id
                WHERE g.sport = ?
                  AND g.status = 'final'
                  AND g.home_score IS NOT NULL
                  AND g.away_score IS NOT NULL
                  AND (g.home_score + g.away_score) > 0
                  AND g.match_date <= date('now')
                  AND p.game_id IS NULL
                """,
                (sport,),
            ).fetchone()
            return int(row["n"]) if row else 0

    def get_backtest_frame(self, sport: Sport) -> pd.DataFrame:
        """已結束賽事 + 預測機率 + 賠率，供評估模組使用。"""
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT g.id AS game_id, g.match_date, g.home_team, g.away_team,
                       g.home_score, g.away_score,
                       o.market, o.selection, o.handicap, o.odds,
                       p.model_prob,
                       CASE
                           WHEN o.market = 'moneyline' AND o.selection = 'home'
                               THEN CASE WHEN g.home_score > g.away_score THEN 1 ELSE 0 END
                           WHEN o.market = 'moneyline' AND o.selection = 'away'
                               THEN CASE WHEN g.away_score > g.home_score THEN 1 ELSE 0 END
                           WHEN o.market = 'total' AND o.selection = 'over'
                               THEN CASE WHEN (g.home_score + g.away_score) > o.handicap THEN 1 ELSE 0 END
                           WHEN o.market = 'total' AND o.selection = 'under'
                               THEN CASE WHEN (g.home_score + g.away_score) < o.handicap THEN 1 ELSE 0 END
                           ELSE NULL
                       END AS won
                FROM games g
                JOIN odds o ON o.game_id = g.id
                LEFT JOIN predictions p ON p.game_id = g.id
                    AND p.market = o.market
                    AND p.selection = o.selection
                WHERE g.sport = ?
                  AND g.status = 'final'
                  AND g.home_score IS NOT NULL
                  AND (g.home_score + g.away_score) > 0
                  AND g.match_date <= date('now')
                  AND p.model_prob IS NOT NULL
                ORDER BY g.match_date, g.id
                """,
                conn,
                params=(sport,),
            )

    def get_backtest_sync_meta(self, sport: Sport, meta_key: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT meta_value FROM backtest_sync_meta WHERE sport = ? AND meta_key = ?",
                (sport, meta_key),
            ).fetchone()
            return str(row["meta_value"]) if row and row["meta_value"] is not None else None

    def set_backtest_sync_meta(self, sport: Sport, meta_key: str, meta_value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO backtest_sync_meta (sport, meta_key, meta_value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(sport, meta_key) DO UPDATE SET
                    meta_value = excluded.meta_value,
                    updated_at = excluded.updated_at
                """,
                (sport, meta_key, meta_value, datetime.now().isoformat(timespec="seconds")),
            )

    def is_backtest_cache_warm(self, sport: Sport) -> bool:
        """是否已有覆盤快取（至少一場已結束賽事且含 forecast）。"""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM game_forecasts f
                JOIN games g ON g.id = f.game_id
                WHERE f.sport = ?
                  AND g.status = 'final'
                  AND g.home_score IS NOT NULL
                  AND (g.home_score + g.away_score) > 0
                  AND g.match_date <= date('now')
                """,
                (sport,),
            ).fetchone()
            return int(row["n"]) > 0 if row else False

    def count_games_for_date(self, sport: Sport, match_date: str) -> int:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM games WHERE sport = ? AND match_date = ?",
                (sport, match_date),
            ).fetchone()
            return int(row["n"]) if row else 0

    def is_schedule_date_checked(self, sport: Sport, match_date: str) -> bool:
        return self.get_backtest_sync_meta(sport, f"schedule_checked_{match_date}") == "1"

    def mark_schedule_date_checked(self, sport: Sport, match_date: str) -> None:
        self.set_backtest_sync_meta(sport, f"schedule_checked_{match_date}", "1")

    def get_scored_games_missing_forecast(self, sport: Sport) -> pd.DataFrame:
        """已完賽但尚未產生 game_forecasts 的場次。"""
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT g.*
                FROM games g
                LEFT JOIN game_forecasts f ON f.game_id = g.id
                WHERE g.sport = ?
                  AND g.status = 'final'
                  AND g.home_score IS NOT NULL
                  AND g.away_score IS NOT NULL
                  AND (g.home_score + g.away_score) > 0
                  AND g.match_date <= date('now')
                  AND f.game_id IS NULL
                ORDER BY g.match_date, g.id
                """,
                conn,
                params=(sport,),
            )

    def get_scored_games_missing_predictions(self, sport: Sport) -> pd.DataFrame:
        """已完賽但尚未產生 predictions 的場次。"""
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT DISTINCT g.*
                FROM games g
                JOIN game_forecasts f ON f.game_id = g.id
                LEFT JOIN predictions p ON p.game_id = g.id
                WHERE g.sport = ?
                  AND g.status = 'final'
                  AND g.home_score IS NOT NULL
                  AND g.away_score IS NOT NULL
                  AND (g.home_score + g.away_score) > 0
                  AND g.match_date <= date('now')
                  AND p.game_id IS NULL
                ORDER BY g.match_date, g.id
                """,
                conn,
                params=(sport,),
            )

    def get_games_by_ids(self, game_ids: list[int]) -> pd.DataFrame:
        if not game_ids:
            return pd.DataFrame()
        placeholders = ",".join("?" for _ in game_ids)
        with self.connection() as conn:
            return pd.read_sql_query(
                f"SELECT * FROM games WHERE id IN ({placeholders}) ORDER BY match_date, id",
                conn,
                params=game_ids,
            )

    def get_dates_needing_backtest_work(self, sport: Sport, *, days_back: int) -> list[str]:
        """
        回測區間內、今天以前需補齊的日期：
        - 尚未檢查過的日期
        - 或最近 lookback 內（比分可能晚到）
        - 或有已結束賽事但缺 forecast / odds
        """
        from sportsbet import config

        lookback = config.BACKTEST_INCREMENTAL_LOOKBACK_DAYS
        today = date.today()
        yesterday = today - timedelta(days=1)
        start = today - timedelta(days=days_back)
        out: set[str] = set()

        d = start
        while d <= yesterday:
            ds = d.isoformat()
            if not self.is_schedule_date_checked(sport, ds):
                out.add(ds)
            d += timedelta(days=1)

        for offset in range(1, lookback + 1):
            out.add((today - timedelta(days=offset)).isoformat())

        start_s, end_s = start.isoformat(), yesterday.isoformat()
        with self.connection() as conn:
            for row in conn.execute(
                """
                SELECT DISTINCT g.match_date
                FROM games g
                LEFT JOIN game_forecasts f ON f.game_id = g.id
                WHERE g.sport = ?
                  AND g.match_date >= ?
                  AND g.match_date <= ?
                  AND g.home_score IS NOT NULL
                  AND g.away_score IS NOT NULL
                  AND f.game_id IS NULL
                """,
                (sport, start_s, end_s),
            ).fetchall():
                out.add(str(row["match_date"])[:10])

            for row in conn.execute(
                """
                SELECT DISTINCT g.match_date
                FROM games g
                LEFT JOIN odds o ON o.game_id = g.id
                WHERE g.sport = ?
                  AND g.match_date >= ?
                  AND g.match_date <= ?
                  AND g.home_score IS NOT NULL
                  AND g.away_score IS NOT NULL
                GROUP BY g.match_date
                HAVING COUNT(o.id) = 0
                """,
                (sport, start_s, end_s),
            ).fetchall():
                out.add(str(row["match_date"])[:10])

        return sorted(d for d in out if start_s <= d <= end_s)

    def get_games_for_ledger_pre(
        self,
        sport: Sport,
        *,
        start_date: str,
    ) -> pd.DataFrame:
        """尚未結束、需更新賽前快照的賽事。"""
        finished = ("final", "FT", "AOT", "Finished", "POST")
        placeholders = ",".join("?" for _ in finished)
        with self.connection() as conn:
            return pd.read_sql_query(
                f"""
                SELECT g.*
                FROM games g
                WHERE g.sport = ?
                  AND g.match_date >= ?
                  AND (g.status IS NULL OR g.status NOT IN ({placeholders}))
                ORDER BY g.match_date, g.id
                """,
                conn,
                params=(sport, start_date, *finished),
            )

    def get_games_for_ledger_post(
        self,
        sport: Sport,
        *,
        start_date: str,
    ) -> pd.DataFrame:
        """已結束但尚未寫入賽後快照的賽事。"""
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT g.*
                FROM games g
                LEFT JOIN game_ledger l ON l.game_id = g.id
                WHERE g.sport = ?
                  AND g.match_date >= ?
                  AND g.status = 'final'
                  AND g.home_score IS NOT NULL
                  AND g.away_score IS NOT NULL
                  AND (g.home_score + g.away_score) > 0
                  AND l.post_captured_at IS NULL
                ORDER BY g.match_date, g.id
                """,
                conn,
                params=(sport, start_date),
            )

    def get_game_odds(self, game_id: int) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM odds WHERE game_id = ? ORDER BY market, selection, created_at",
                conn,
                params=(game_id,),
            )

    def get_game_predictions(self, game_id: int) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM predictions WHERE game_id = ? ORDER BY market, selection",
                conn,
                params=(game_id,),
            )

    def get_game_forecast_row(self, game_id: int) -> pd.Series | None:
        with self.connection() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM game_forecasts WHERE game_id = ?",
                conn,
                params=(game_id,),
            )
        if df.empty:
            return None
        return df.iloc[0]

    def get_team_player_stats(self, sport: Sport, team: str) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT p.player_id, p.name, p.position, s.*
                FROM players p
                LEFT JOIN player_advanced_stats s
                    ON s.sport = p.sport AND s.player_id = p.player_id
                WHERE p.sport = ? AND p.team = ?
                ORDER BY (s.war IS NULL), s.war DESC, p.name
                """,
                conn,
                params=(sport, team),
            )

    def get_team_injuries(self, sport: Sport, team: str, report_date: str) -> pd.DataFrame:
        with self.connection() as conn:
            return pd.read_sql_query(
                """
                SELECT i.*, p.name
                FROM injury_reports i
                JOIN players p ON p.sport = i.sport AND p.player_id = i.player_id
                WHERE i.sport = ? AND i.team = ? AND i.report_date <= ?
                ORDER BY i.report_date DESC
                LIMIT 30
                """,
                conn,
                params=(sport, team, report_date),
            )

    def upsert_game_ledger_pre(
        self,
        game_id: int,
        sport: Sport,
        match_date: str,
        home_team: str,
        away_team: str,
        snapshot_json: str,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO game_ledger
                    (game_id, sport, match_date, home_team, away_team,
                     pre_captured_at, pre_snapshot_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    pre_captured_at = excluded.pre_captured_at,
                    pre_snapshot_json = excluded.pre_snapshot_json
                """,
                (game_id, sport, match_date, home_team, away_team, now, snapshot_json),
            )

    def upsert_game_ledger_post(
        self,
        game_id: int,
        sport: Sport,
        match_date: str,
        home_team: str,
        away_team: str,
        snapshot_json: str,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO game_ledger
                    (game_id, sport, match_date, home_team, away_team,
                     post_captured_at, post_snapshot_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    post_captured_at = excluded.post_captured_at,
                    post_snapshot_json = excluded.post_snapshot_json
                """,
                (game_id, sport, match_date, home_team, away_team, now, snapshot_json),
            )
