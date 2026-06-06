"""台灣運彩中文隊名 → API-Sports 英文隊名對照（NBA / MLB）。"""
from __future__ import annotations

import re
import unicodedata

# NBA：運彩常見中文全名 → API-Sports 英文隊名
NBA_ZH_TO_EN: dict[str, str] = {
    "亞特蘭大老鷹": "Atlanta Hawks",
    "波士頓塞爾提克": "Boston Celtics",
    "布魯克林籃網": "Brooklyn Nets",
    "夏洛特黃蜂": "Charlotte Hornets",
    "芝加哥公牛": "Chicago Bulls",
    "克里夫蘭騎士": "Cleveland Cavaliers",
    "達拉斯獨行俠": "Dallas Mavericks",
    "丹佛金塊": "Denver Nuggets",
    "底特律活塞": "Detroit Pistons",
    "金州勇士": "Golden State Warriors",
    "休士頓火箭": "Houston Rockets",
    "印第安納溜馬": "Indiana Pacers",
    "洛杉磯快艇": "LA Clippers",
    "洛杉磯湖人": "Los Angeles Lakers",
    "曼菲斯灰熊": "Memphis Grizzlies",
    "邁阿密熱火": "Miami Heat",
    "密爾瓦基公鹿": "Milwaukee Bucks",
    "明尼蘇達灰狼": "Minnesota Timberwolves",
    "紐奧良鵜鶘": "New Orleans Pelicans",
    "紐約尼克": "New York Knicks",
    "奧蘭多魔術": "Orlando Magic",
    "費城七六人": "Philadelphia 76ers",
    "鳳凰城太陽": "Phoenix Suns",
    "波特蘭拓荒者": "Portland Trail Blazers",
    "沙加緬度國王": "Sacramento Kings",
    "聖安東尼奧馬刺": "San Antonio Spurs",
    "多倫多暴龍": "Toronto Raptors",
    "猶他爵士": "Utah Jazz",
    "華盛頓巫師": "Washington Wizards",
    "奧克拉荷馬雷霆": "Oklahoma City Thunder",
    # 簡稱 / 別名
    "老鷹": "Atlanta Hawks",
    "塞爾提克": "Boston Celtics",
    "籃網": "Brooklyn Nets",
    "黃蜂": "Charlotte Hornets",
    "公牛": "Chicago Bulls",
    "騎士": "Cleveland Cavaliers",
    "獨行俠": "Dallas Mavericks",
    "金塊": "Denver Nuggets",
    "活塞": "Detroit Pistons",
    "勇士": "Golden State Warriors",
    "火箭": "Houston Rockets",
    "溜馬": "Indiana Pacers",
    "快艇": "LA Clippers",
    "湖人": "Los Angeles Lakers",
    "灰熊": "Memphis Grizzlies",
    "熱火": "Miami Heat",
    "公鹿": "Milwaukee Bucks",
    "灰狼": "Minnesota Timberwolves",
    "鵜鶘": "New Orleans Pelicans",
    "尼克": "New York Knicks",
    "魔術": "Orlando Magic",
    "七六人": "Philadelphia 76ers",
    "太陽": "Phoenix Suns",
    "拓荒者": "Portland Trail Blazers",
    "國王": "Sacramento Kings",
    "馬刺": "San Antonio Spurs",
    "暴龍": "Toronto Raptors",
    "爵士": "Utah Jazz",
    "巫師": "Washington Wizards",
    "雷霆": "Oklahoma City Thunder",
}

# MLB：運彩常見中文全名 → API-Sports 英文隊名
MLB_ZH_TO_EN: dict[str, str] = {
    "亞利桑那響尾蛇": "Arizona Diamondbacks",
    "亞特蘭大勇士": "Atlanta Braves",
    "巴爾的摩金鶯": "Baltimore Orioles",
    "波士頓紅襪": "Boston Red Sox",
    "芝加哥白襪": "Chicago White Sox",
    "芝加哥小熊": "Chicago Cubs",
    "辛辛那提紅人": "Cincinnati Reds",
    "克里夫蘭守護者": "Cleveland Guardians",
    "克里夫蘭印地安人": "Cleveland Guardians",
    "科羅拉多洛磯": "Colorado Rockies",
    "底特律老虎": "Detroit Tigers",
    "休士頓太空人": "Houston Astros",
    "堪薩斯市皇家": "Kansas City Royals",
    "洛杉磯天使": "Los Angeles Angels",
    "洛杉磯道奇": "Los Angeles Dodgers",
    "邁阿密馬林魚": "Miami Marlins",
    "密爾瓦基釀酒人": "Milwaukee Brewers",
    "明尼蘇達雙城": "Minnesota Twins",
    "紐約大都會": "New York Mets",
    "紐約洋基": "New York Yankees",
    "奧克蘭運動家": "Oakland Athletics",
    "費城費城人": "Philadelphia Phillies",
    "匹茲堡海盜": "Pittsburgh Pirates",
    "聖地牙哥教士": "San Diego Padres",
    "舊金山巨人": "San Francisco Giants",
    "西雅圖水手": "Seattle Mariners",
    "聖路易紅雀": "St.Louis Cardinals",
    "聖路易斯紅雀": "St.Louis Cardinals",
    "坦帕灣光芒": "Tampa Bay Rays",
    "德州遊騎兵": "Texas Rangers",
    "多倫多藍鳥": "Toronto Blue Jays",
    "華盛頓國民": "Washington Nationals",
    # 簡稱
    "響尾蛇": "Arizona Diamondbacks",
    "勇士": "Atlanta Braves",
    "金鶯": "Baltimore Orioles",
    "紅襪": "Boston Red Sox",
    "白襪": "Chicago White Sox",
    "小熊": "Chicago Cubs",
    "紅人": "Cincinnati Reds",
    "守護者": "Cleveland Guardians",
    "洛磯": "Colorado Rockies",
    "老虎": "Detroit Tigers",
    "太空人": "Houston Astros",
    "皇家": "Kansas City Royals",
    "天使": "Los Angeles Angels",
    "道奇": "Los Angeles Dodgers",
    "馬林魚": "Miami Marlins",
    "釀酒人": "Milwaukee Brewers",
    "雙城": "Minnesota Twins",
    "大都會": "New York Mets",
    "洋基": "New York Yankees",
    "運動家": "Oakland Athletics",
    "費城人": "Philadelphia Phillies",
    "海盜": "Pittsburgh Pirates",
    "教士": "San Diego Padres",
    "巨人": "San Francisco Giants",
    "水手": "Seattle Mariners",
    "紅雀": "St.Louis Cardinals",
    "光芒": "Tampa Bay Rays",
    "遊騎兵": "Texas Rangers",
    "藍鳥": "Toronto Blue Jays",
    "國民": "Washington Nationals",
}

_SPORT_MAPS: dict[str, dict[str, str]] = {
    "nba": NBA_ZH_TO_EN,
    "mlb": MLB_ZH_TO_EN,
}

# 英文別名 → 標準英文名（API-Sports 可能略有差異）
_EN_ALIASES: dict[str, str] = {
    "LA Clippers": "Los Angeles Clippers",
    "LA Lakers": "Los Angeles Lakers",
    "St. Louis Cardinals": "St.Louis Cardinals",
    "St Louis Cardinals": "St.Louis Cardinals",
}


def _strip_noise(name: str) -> str:
    """移除空白、全形字與括號內英文副標。"""
    if not name or (isinstance(name, float) and name != name):  # NaN
        return ""
    s = str(name).strip()
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[（(].*?[）)]", "", s)
    return s


def normalize_team_name(name: str, sport: str) -> str:
    """
    將隊名正規化為 API-Sports 使用的英文名。

    - 已是英文則做別名對照
    - 中文則查表；查無則回傳原字串（由呼叫端處理未匹配）
    """
    if not name or (isinstance(name, float) and name != name):
        return ""

    raw = str(name).strip()
    key = _strip_noise(raw)
    mapping = _SPORT_MAPS.get(sport.lower(), {})

    if key in mapping:
        return mapping[key]

    # 部分運彩名稱為 list：["中文","English"]
    if isinstance(name, (list, tuple)) and name:
        return normalize_team_name(name[0], sport)

    # 已是英文
    if re.search(r"[A-Za-z]", raw):
        for alias, canonical in _EN_ALIASES.items():
            if alias.lower() in raw.lower():
                return canonical
        return raw

    # 模糊：去掉「隊」後再查
    alt = key.replace("隊", "")
    if alt in mapping:
        return mapping[alt]

    return raw


def normalize_matchup(
    home: str,
    away: str,
    sport: str,
) -> tuple[str, str]:
    """正規化主客隊名稱。"""
    return normalize_team_name(home, sport), normalize_team_name(away, sport)


def build_reverse_map(sport: str) -> dict[str, str]:
    """英文 → 中文（便於除錯）。"""
    m = _SPORT_MAPS.get(sport.lower(), {})
    rev: dict[str, str] = {}
    for zh, en in m.items():
        if en not in rev or len(zh) > len(rev[en]):
            rev[en] = zh
    return rev


def known_teams(sport: str) -> set[str]:
    """該運動的標準英文隊名集合。"""
    m = _SPORT_MAPS.get(sport.lower(), {})
    return set(m.values()) | {v for v in _EN_ALIASES.values()}


NBA_TEAMS = known_teams("nba")
MLB_TEAMS = known_teams("mlb")


def _looks_like_playsport_pitcher_row(name: str) -> bool:
    """玩運彩誤植：投手名當隊名（例：Lambert (洋基)）。"""
    raw = str(name or "").strip()
    return bool(raw) and "(" in raw


def team_belongs_to_sport(team: str, sport: str) -> bool:
    """隊名是否屬於指定運動（含正規化後比對）。"""
    if not team:
        return False
    canonical = normalize_team_name(team, sport)
    known = known_teams(sport)
    if canonical in known:
        return True
    low = canonical.lower()
    return any(t.lower() == low or t.lower() in low or low in t.lower() for t in known)


def is_cross_sport_game(sport: str, home_team: str, away_team: str) -> bool:
    """偵測 sport 欄位與隊名明顯不符（NBA 混入 MLB 等）。"""
    sport = sport.lower()
    other = "mlb" if sport == "nba" else "nba"
    other_teams = MLB_TEAMS if sport == "nba" else NBA_TEAMS
    own_teams = NBA_TEAMS if sport == "nba" else MLB_TEAMS

    for team in (home_team, away_team):
        if sport == "nba" and _looks_like_playsport_pitcher_row(team):
            return True
        canonical = normalize_team_name(team, sport)
        if canonical in other_teams and canonical not in own_teams:
            return True
        alt = normalize_team_name(team, other)
        if alt in other_teams and alt not in own_teams:
            return True
    return False
