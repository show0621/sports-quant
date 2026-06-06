"""
玩運彩 playsport.cc — 球隊歷史賽事（賽果 + 台灣運彩盤口）。

頁面範例：https://www.playsport.cc/gamesData/teams?teamid=53#historyGame

注意：請遵守網站服務條款，僅供個人研究；請勿高頻請求。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from typing import Any, Literal

import pandas as pd
import requests
from bs4 import BeautifulSoup

from sportsbet import config
from sportsbet import config
from sportsbet.data.database import SportsDatabase
from sportsbet.data.team_logos import espn_logo_url
from sportsbet.data.team_names import normalize_matchup, normalize_team_name

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]

USER_AGENT = "sports-quant/1.0 (+https://github.com/show0621/sports-quant)"
BASE_URL = "https://www.playsport.cc/gamesData/teams"

# allianceid：1=NBA, 6=MLB（依玩運彩分站）
ALLIANCE_ID: dict[str, int] = {"nba": 1, "mlb": 6}

_SCORE_RE = re.compile(r"(\d+)\s*V\.?\s*S\.?\s*(\d+)", re.I)
_DATE_RE = re.compile(r"(\d{2})/(\d{2})\s+AM\s+(\d{2}):(\d{2})")
_STAT_RANGE_RE = re.compile(
    r"統計時間[：:]\s*(\d{4}/\d{2}/\d{2})\s*[-–]\s*(\d{4}/\d{2}/\d{2})"
)
_SPREAD_RE = re.compile(r"([+-]?\d+\.?\d*)\s*分")
_TOTAL_RE = re.compile(r"([大小])\s*(\d+\.?\d*)")
_GAME_ID_RE = re.compile(r"gameid=(\d+)")


def _sport_team_names(sport: Sport) -> list[str]:
    from sportsbet.data.team_names import MLB_ZH_TO_EN, NBA_ZH_TO_EN

    m = NBA_ZH_TO_EN if sport == "nba" else MLB_ZH_TO_EN
    return sorted(m.keys(), key=len, reverse=True)


def _infer_year(month: int, day: int, range_end: date | None) -> int:
    ref = range_end or date.today()
    year = ref.year
    try:
        d = date(year, month, day)
        if d > ref and (ref - d).days > 200:
            year -= 1
    except ValueError:
        pass
    return year


def _parse_stat_range(html: str) -> tuple[date | None, date | None]:
    m = _STAT_RANGE_RE.search(html)
    if not m:
        return None, None
    try:
        start = datetime.strptime(m.group(1), "%Y/%m/%d").date()
        end = datetime.strptime(m.group(2), "%Y/%m/%d").date()
        return start, end
    except ValueError:
        return None, None


class PlaySportScraper:
    def __init__(
        self,
        *,
        delay_sec: float | None = None,
        timeout: float = 25.0,
    ):
        self.delay_sec = delay_sec if delay_sec is not None else config.PLAYSPORT_REQUEST_DELAY_SEC
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _get(self, params: dict[str, Any]) -> str:
        resp = self._session.get(BASE_URL, params=params, timeout=self.timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        time.sleep(self.delay_sec)
        return resp.text

    def list_team_ids(self, sport: Sport) -> dict[int, str]:
        """NBA/MLB 球隊 teamid → 中文隊名。"""
        aid = ALLIANCE_ID.get(sport)
        if aid is None:
            return {}
        html = self._get({"allianceid": aid})
        soup = BeautifulSoup(html, "html.parser")
        out: dict[int, str] = {}
        for a in soup.find_all("a", href=True):
            m = re.search(r"teamid=(\d+)", a["href"])
            if not m:
                continue
            tid = int(m.group(1))
            name = a.get_text(strip=True)
            if name and tid not in out:
                out[tid] = name
        return out

    def fetch_team_history(
        self,
        team_id: int,
        sport: Sport = "nba",
    ) -> pd.DataFrame:
        """解析單隊「歷史賽事」主表。"""
        html = self._get({"teamid": team_id})
        _, range_end = _parse_stat_range(html)
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return pd.DataFrame()

        rows_out: list[dict[str, Any]] = []
        for tr in soup.find_all("tr"):
            date_td = tr.find("td", class_="td-gameinfo")
            team_td = tr.find("td", class_="td-teaminfo")
            if not date_td or not team_td:
                continue

            h3 = date_td.find("h3")
            h4 = date_td.find("h4")
            if not h3 or not h4:
                continue
            month_day = h3.get_text(strip=True)
            time_part = h4.get_text(strip=True)
            date_txt = f"{month_day} {time_part}"
            dm = _DATE_RE.search(date_txt.replace("\n", " "))
            if not dm:
                continue

            loser_el = team_td.find("td", class_="secondteam")
            winner_el = team_td.find("td", class_="winnerteam")
            score_lis = team_td.find("ul")
            if not loser_el or not winner_el or not score_lis:
                continue
            winner_team = normalize_team_name(winner_el.get_text(strip=True), sport)
            loser_team = normalize_team_name(loser_el.get_text(strip=True), sport)
            numeric_scores = []
            for li in score_lis.find_all("li"):
                t = li.get_text(strip=True)
                if t.isdigit():
                    numeric_scores.append(int(t))
            if len(numeric_scores) < 2:
                continue
            away_score, home_score = numeric_scores[0], numeric_scores[1]
            if away_score > home_score:
                away_team, home_team = winner_team, loser_team
            else:
                away_team, home_team = loser_team, winner_team

            month, day = int(dm.group(1)), int(dm.group(2))
            hour, minute = int(dm.group(3)), int(dm.group(4))
            year = _infer_year(month, day, range_end)
            match_date = date(year, month, day).isoformat()
            match_datetime = f"{match_date}T{hour:02d}:{minute:02d}:00+08:00"

            game_id = None
            for a in tr.find_all("a", href=True):
                gm = _GAME_ID_RE.search(a["href"])
                if gm:
                    game_id = gm.group(1)
                    break

            spread_txt = ""
            spread_div = tr.find("td", class_="td-bank-bet01")
            if spread_div:
                spread_txt = spread_div.get_text(" ", strip=True)
            total_txt = ""
            total_div = tr.find("td", class_="td-bank-bet02")
            if total_div:
                total_txt = total_div.get_text(" ", strip=True)
            total_points = ""
            sum_td = tr.find("td", class_="td-scoresum")
            if sum_td:
                total_points = sum_td.get_text(strip=True)

            spread_line = None
            spread_team = None
            sm = _SPREAD_RE.search(spread_txt)
            if sm:
                spread_line = float(sm.group(1))
                for zh in _sport_team_names(sport):
                    if zh in spread_txt:
                        spread_team = normalize_team_name(zh, sport)
                        break

            total_line = None
            tm = _TOTAL_RE.search(total_txt)
            if tm:
                total_line = float(tm.group(2))

            rows_out.append(
                {
                    "playsport_game_id": game_id,
                    "playsport_team_id": team_id,
                    "sport": sport,
                    "match_date": match_date,
                    "match_datetime": match_datetime,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": "final",
                    "spread_team": spread_team,
                    "spread_line": spread_line,
                    "total_line": total_line,
                    "actual_total": int(total_points) if str(total_points).isdigit() else None,
                    "source": "playsport",
                }
            )

        return pd.DataFrame(rows_out)

    def sync_team_to_database(
        self,
        db: SportsDatabase,
        team_id: int,
        sport: Sport = "nba",
    ) -> pd.DataFrame:
        """寫入 games + 運彩盤口（讓分/大小）。"""
        df = self.fetch_team_history(team_id, sport)
        if df.empty:
            return df

        for _, row in df.iterrows():
            gid = db.upsert_game(
                sport,
                row["match_date"],
                row["home_team"],
                row["away_team"],
                match_datetime=row["match_datetime"],
                home_score=int(row["home_score"]),
                away_score=int(row["away_score"]),
                status="final",
                home_logo_url=espn_logo_url(row["home_team"], sport),
                away_logo_url=espn_logo_url(row["away_team"], sport),
            )
            if row.get("spread_line") is not None and row.get("spread_team"):
                sel = "home" if row["spread_team"] == row["home_team"] else "away"
                handicap = float(row["spread_line"])
                db.insert_odds(gid, "spread", sel, 1.75, handicap=handicap, bookmaker="playsport")
            if row.get("total_line") is not None:
                line = float(row["total_line"])
                db.insert_odds(gid, "total", "over", 1.75, handicap=line, bookmaker="playsport")
                db.insert_odds(gid, "total", "under", 1.75, handicap=line, bookmaker="playsport")
            # 台灣運彩不讓分制（玩運彩頁面未列 moneyline，回測用標準 1.75）
            ml = config.TW_MONEYLINE_ODDS
            db.insert_odds(gid, "moneyline", "home", ml, bookmaker="tw_standard")
            db.insert_odds(gid, "moneyline", "away", ml, bookmaker="tw_standard")

        logger.info("playsport teamid=%s 寫入 %d 場", team_id, len(df))
        return df

    def sync_sport(
        self,
        db: SportsDatabase,
        sport: Sport = "nba",
        *,
        max_teams: int | None = None,
    ) -> pd.DataFrame:
        """同步聯盟所有球隊歷史賽事（請控制頻率）。"""
        teams = self.list_team_ids(sport)
        if max_teams:
            teams = dict(list(teams.items())[:max_teams])
        all_rows = []
        for tid in teams:
            try:
                df = self.sync_team_to_database(db, tid, sport)
                all_rows.append(df)
            except Exception as exc:
                logger.warning("playsport teamid=%s 失敗: %s", tid, exc)
        if not all_rows:
            return pd.DataFrame()
        return pd.concat(all_rows, ignore_index=True)
