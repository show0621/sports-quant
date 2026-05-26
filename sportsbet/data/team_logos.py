"""球隊 Logo：API-Sports 快取 + ESPN CDN 備援。"""
from __future__ import annotations

from typing import Literal

Sport = Literal["nba", "mlb"]

# Mock 短隊名 → 標準全名
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
    return aliases.get(team, team)


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
