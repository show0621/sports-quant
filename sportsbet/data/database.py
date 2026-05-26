"""SQLite 本地資料庫：賽程、賠率、球隊統計與預測紀錄。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
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
    bookmaker TEXT DEFAULT 'mock',
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

CREATE INDEX IF NOT EXISTS idx_games_date ON games(sport, match_date);
CREATE INDEX IF NOT EXISTS idx_odds_game ON odds(game_id);
CREATE INDEX IF NOT EXISTS idx_predictions_game ON predictions(game_id);
"""


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
    ) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO games (sport, match_date, match_datetime, home_team, away_team,
                                   home_score, away_score, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sport, match_date, home_team, away_team) DO UPDATE SET
                    match_datetime=excluded.match_datetime,
                    home_score=COALESCE(excluded.home_score, games.home_score),
                    away_score=COALESCE(excluded.away_score, games.away_score),
                    status=excluded.status
                """,
                (sport, match_date, match_datetime, home_team, away_team, home_score, away_score, status),
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
        bookmaker: str = "mock",
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO odds (game_id, market, selection, handicap, odds, bookmaker)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (game_id, market, selection, handicap, odds, bookmaker),
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
            sql += " AND home_score IS NOT NULL AND away_score IS NOT NULL"
        sql += " ORDER BY match_date, id"
        with self.connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

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
                       o.market, o.selection, o.handicap, o.odds,
                       p.model_prob, p.ev, p.stake_fraction AS kelly_stake
                FROM games g
                LEFT JOIN odds o ON o.game_id = g.id
                LEFT JOIN predictions p ON p.game_id = g.id
                    AND p.market = o.market
                    AND (p.selection = o.selection OR p.selection IS NULL)
                WHERE g.sport = ? AND g.match_date = ?
                ORDER BY g.id, o.market, o.selection
                """,
                conn,
                params=(sport, d),
            )

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
                  AND p.model_prob IS NOT NULL
                ORDER BY g.match_date, g.id
                """,
                conn,
                params=(sport,),
            )
