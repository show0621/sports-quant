import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SPORTSLOTTERY_EVENT_IDS_NBA", "3472877.1")

from sportsbet.data.database import SportsDatabase
from sportsbet.data import tw_odds_sync
from sportsbet.data.tw_odds_sync import sync_tw_odds_for_date

tw_odds_sync._web_odds_cache.clear()
db = SportsDatabase()
r = sync_tw_odds_for_date(db, "nba", "2026-06-09")
print("sync", r)
with db.connection() as conn:
    rows = conn.execute(
        """
        SELECT g.id, o.market, o.selection, o.handicap, o.odds
        FROM games g
        JOIN odds o ON o.game_id = g.id
        WHERE g.match_date = '2026-06-09' AND o.bookmaker = 'sportslottery'
        ORDER BY o.market, o.selection
        """
    ).fetchall()
for row in rows:
    print(dict(row))
