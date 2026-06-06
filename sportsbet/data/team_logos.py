"""球隊 Logo：API-Sports 快取 + ESPN CDN 備援。"""
from __future__ import annotations

from typing import Literal

Sport = Literal["nba", "mlb"]

# 短隊名 / 別名 → 標準全名
NBA_ALIASES: dict[str, str] = {
    "Lakers": "Los Angeles Lakers",
    "Celtics": "Boston Celtics",
    "Warriors": "Golden State Warriors",
    "Nuggets": "Denver Nuggets",
    "Bucks": "Milwaukee Bucks",
    "Suns": "Phoenix Suns",
    "Heat": "Miami Heat",
    "Knicks": "New York Knicks",
    "Mavericks": "Dallas Mavericks",
    "Clippers": "LA Clippers",
    "76ers": "Philadelphia 76ers",
    "Thunder": "Oklahoma City Thunder",
}

# nba_api TEAM_ABBREVIATION → 標準全名（players 表與 games 表對齊）
NBA_ABBREV: dict[str, str] = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "BRK": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}

MLB_ALIASES: dict[str, str] = {
    "Yankees": "New York Yankees",
    "Dodgers": "Los Angeles Dodgers",
    "Astros": "Houston Astros",
    "Braves": "Atlanta Braves",
    "Orioles": "Baltimore Orioles",
    "Rangers": "Texas Rangers",
    "Phillies": "Philadelphia Phillies",
    "Padres": "San Diego Padres",
    "Mariners": "Seattle Mariners",
    "Twins": "Minnesota Twins",
    "Rays": "Tampa Bay Rays",
    "Guardians": "Cleveland Guardians",
}

# ESPN CDN 縮寫（顯示用，穩定且無需 API）
NBA_ESPN: dict[str, str] = {
    "Atlanta Hawks": "atl",
    "Boston Celtics": "bos",
    "Brooklyn Nets": "bkn",
    "Charlotte Hornets": "cha",
    "Chicago Bulls": "chi",
    "Cleveland Cavaliers": "cle",
    "Dallas Mavericks": "dal",
    "Denver Nuggets": "den",
    "Detroit Pistons": "det",
    "Golden State Warriors": "gs",
    "Houston Rockets": "hou",
    "Indiana Pacers": "ind",
    "LA Clippers": "lac",
    "Los Angeles Clippers": "lac",
    "Los Angeles Lakers": "lal",
    "Memphis Grizzlies": "mem",
    "Miami Heat": "mia",
    "Milwaukee Bucks": "mil",
    "Minnesota Timberwolves": "min",
    "New Orleans Pelicans": "no",
    "New York Knicks": "ny",
    "Oklahoma City Thunder": "okc",
    "Orlando Magic": "orl",
    "Philadelphia 76ers": "phi",
    "Phoenix Suns": "phx",
    "Portland Trail Blazers": "por",
    "Sacramento Kings": "sac",
    "San Antonio Spurs": "sa",
    "Toronto Raptors": "tor",
    "Utah Jazz": "utah",
    "Washington Wizards": "wsh",
}

MLB_ESPN: dict[str, str] = {
    "Arizona Diamondbacks": "ari",
    "Atlanta Braves": "atl",
    "Baltimore Orioles": "bal",
    "Boston Red Sox": "bos",
    "Chicago Cubs": "chc",
    "Chicago White Sox": "chw",
    "Cincinnati Reds": "cin",
    "Cleveland Guardians": "cle",
    "Colorado Rockies": "col",
    "Detroit Tigers": "det",
    "Houston Astros": "hou",
    "Kansas City Royals": "kc",
    "Los Angeles Angels": "laa",
    "Los Angeles Dodgers": "lad",
    "Miami Marlins": "mia",
    "Milwaukee Brewers": "mil",
    "Minnesota Twins": "min",
    "New York Mets": "nym",
    "New York Yankees": "nyy",
    "Oakland Athletics": "oak",
    "Philadelphia Phillies": "phi",
    "Pittsburgh Pirates": "pit",
    "San Diego Padres": "sd",
    "San Francisco Giants": "sf",
    "Seattle Mariners": "sea",
    "St. Louis Cardinals": "stl",
    "Tampa Bay Rays": "tb",
    "Texas Rangers": "tex",
    "Toronto Blue Jays": "tor",
    "Washington Nationals": "wsh",
}


def canonical_team_name(team: str, sport: Sport) -> str:
    aliases = NBA_ALIASES if sport == "nba" else MLB_ALIASES
    t = team.strip()
    if sport == "nba" and t.upper() in NBA_ABBREV:
        return NBA_ABBREV[t.upper()]
    return aliases.get(t, t)


def team_name_variants(team: str, sport: Sport) -> set[str]:
    """同一隊所有常見寫法（全名、縮寫、別名）。"""
    names: set[str] = {team.strip()}
    canonical = canonical_team_name(team, sport)
    names.add(canonical)
    if sport == "nba":
        for abbr, full in NBA_ABBREV.items():
            if full == canonical or abbr == team.strip().upper():
                names.add(abbr)
                names.add(full)
        nick = canonical.split()[-1] if canonical else ""
        if nick:
            names.add(nick)
    return {n for n in names if n}


def resolve_team_in_database(db, sport: Sport, candidate: str) -> str:
    """
    將 ESPN / API-Sports 隊名對齊至資料庫既有寫法。
    若 DB 尚無該隊，回傳 canonical 全名供新資料寫入。
    """
    from sportsbet.data.database import SportsDatabase

    if not isinstance(db, SportsDatabase):
        db = SportsDatabase()

    name = canonical_team_name(candidate.strip(), sport)
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT team FROM (
                SELECT home_team AS team FROM games WHERE sport = ?
                UNION SELECT away_team FROM games WHERE sport = ?
                UNION SELECT team FROM team_stats WHERE sport = ?
                UNION SELECT team FROM players WHERE sport = ?
            )
            """,
            (sport, sport, sport, sport),
        ).fetchall()
    known = {r[0] for r in rows if r[0]}

    if not known:
        return name
    if name in known:
        return name
    if candidate in known:
        return candidate

    low = name.lower()
    for k in known:
        if k.lower() == low:
            return k

    last = name.split()[-1].lower()
    matches = [k for k in known if k.split()[-1].lower() == last]
    if len(matches) == 1:
        return matches[0]
    return name


def espn_logo_url(team: str, sport: Sport) -> str | None:
    name = canonical_team_name(team, sport)
    abbr_map = NBA_ESPN if sport == "nba" else MLB_ESPN
    abbr = abbr_map.get(name)
    if not abbr:
        return None
    league = "nba" if sport == "nba" else "mlb"
    return f"https://a.espncdn.com/i/teamlogos/{league}/500/{abbr}.png"


def resolve_logo_url(
    team: str,
    sport: Sport,
    *,
    db_url: str | None = None,
) -> str | None:
    """優先 DB（API-Sports），其次 ESPN CDN。"""
    if db_url and str(db_url).startswith("http"):
        return str(db_url)
    return espn_logo_url(team, sport)
