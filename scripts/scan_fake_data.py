"""掃描 DB 與 repo 中的可疑假資料。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sqlite3

from sportsbet.data.database import SportsDatabase


def main() -> None:
    db = SportsDatabase()
    conn = sqlite3.connect(db.db_path)

    checks = [
        ("mock 隊名", "SELECT COUNT(*) FROM games WHERE home_team LIKE '%Mock%' OR away_team LIKE '%Mock%'"),
        ("0-0 final", "SELECT COUNT(*) FROM games WHERE status='final' AND home_score=0 AND away_score=0"),
        ("future final", "SELECT COUNT(*) FROM games WHERE status='final' AND match_date > date('now')"),
        ("nba 含 MLB 投手名", """
            SELECT COUNT(*) FROM games WHERE sport='nba'
            AND (home_team LIKE '%Rocker%' OR home_team LIKE '%Lambert%' OR home_team LIKE '%Valdez%')
        """),
        ("mlb 中文隊名污染", """
            SELECT COUNT(*) FROM games WHERE sport='mlb'
            AND (home_team LIKE '%東京%' OR home_team LIKE '%運動家%')
        """),
    ]
    for label, sql in checks:
        print(f"{label}: {conn.execute(sql).fetchone()[0]}")

    print("\n可疑 NBA 列:")
    for r in conn.execute(
        """
        SELECT id, match_date, home_team, away_team, status
        FROM games WHERE sport='nba'
        AND (home_team LIKE '%Rocker%' OR home_team LIKE '%Lambert%' OR home_team LIKE '%Valdez%'
             OR home_team LIKE '%Messick%' OR home_team LIKE '%Woo%')
        LIMIT 20
        """
    ):
        print(r)

    print("\n賠率來源:")
    for r in conn.execute("SELECT bookmaker, COUNT(*) FROM odds GROUP BY bookmaker"):
        print(r)

    conn.close()


if __name__ == "__main__":
    main()
