"""
玩運彩「預測比例」— 月勝率 60%+ 會員對各盤口的預測占比。

頁面：https://www.playsport.cc/predict/scale?allianceid=3&gametime=YYYYMMDD&sid=1
sid=1 → 月勝率 60% 以上會員（運彩盤：讓分 / 不讓分 / 大小）
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

import requests
from bs4 import BeautifulSoup

from sportsbet import config
from sportsbet.data.playsport_scraper import ALLIANCE_ID, USER_AGENT
from sportsbet.data.team_names import normalize_matchup

logger = logging.getLogger(__name__)

Sport = Literal["nba", "mlb"]

SCALE_URL = "https://www.playsport.cc/predict/scale"

MEMBER_TIER_SID: dict[str, int] = {
    "all": 0,
    "win60": 1,
    "top100": 2,
}

_PCT_RE = re.compile(r"(\d+)\s*%")
_COUNT_RE = re.compile(r"(\d+)\s*人預測")
_LINE_RE = re.compile(r"([+-]?\d+\.?\d*)")
_ODDS_TAIL_RE = re.compile(r",\s*([\d.]+)\s*$")


@dataclass
class MemberMarketSide:
    pct: float | None = None
    count: int | None = None
    line: float | None = None
    odds: float | None = None


@dataclass
class PlaySportMemberGame:
    playsport_game_id: str
    match_date: str
    sport: Sport
    member_tier: str
    team_a_zh: str
    team_b_zh: str
    team_a_en: str
    team_b_en: str
    tw_spread_away: MemberMarketSide = field(default_factory=MemberMarketSide)
    tw_spread_home: MemberMarketSide = field(default_factory=MemberMarketSide)
    tw_ml_away: MemberMarketSide = field(default_factory=MemberMarketSide)
    tw_ml_home: MemberMarketSide = field(default_factory=MemberMarketSide)
    tw_over: MemberMarketSide = field(default_factory=MemberMarketSide)
    tw_under: MemberMarketSide = field(default_factory=MemberMarketSide)

    def to_consensus_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for market, side, obj in (
            ("spread", "away", self.tw_spread_away),
            ("spread", "home", self.tw_spread_home),
            ("moneyline", "away", self.tw_ml_away),
            ("moneyline", "home", self.tw_ml_home),
            ("total", "over", self.tw_over),
            ("total", "under", self.tw_under),
        ):
            if obj.pct is None:
                continue
            rows.append(
                {
                    "playsport_game_id": self.playsport_game_id,
                    "match_date": self.match_date,
                    "sport": self.sport,
                    "member_tier": self.member_tier,
                    "board": "tw",
                    "market": market,
                    "selection": side,
                    "member_pct": obj.pct,
                    "sample_size": obj.count,
                    "line": obj.line,
                    "odds": obj.odds,
                }
            )
        return rows


def _parse_pct_count(text: str) -> tuple[float | None, int | None]:
    pm = _PCT_RE.search(text)
    cm = _COUNT_RE.search(text)
    pct = int(pm.group(1)) / 100.0 if pm else None
    count = int(cm.group(1)) if cm else None
    return pct, count


def _parse_line_odds(text: str) -> tuple[float | None, float | None]:
    line = odds = None
    lm = _LINE_RE.search(text.replace(" ", ""))
    if lm:
        try:
            line = float(lm.group(1))
        except ValueError:
            pass
    om = _ODDS_TAIL_RE.search(text)
    if om:
        try:
            odds = float(om.group(1))
        except ValueError:
            pass
    return line, odds


def _parse_bank_pair(bet_td, predict_td) -> MemberMarketSide:
    bet_txt = bet_td.get_text(" ", strip=True) if bet_td else ""
    pred_txt = predict_td.get_text(" ", strip=True) if predict_td else ""
    pct, count = _parse_pct_count(pred_txt)
    line, odds = _parse_line_odds(bet_txt)
    return MemberMarketSide(pct=pct, count=count, line=line, odds=odds)


def _extract_bank_cols(tr) -> dict[str, MemberMarketSide]:
    out: dict[str, MemberMarketSide] = {}
    tds = tr.find_all("td", recursive=False)
    i = 0
    while i < len(tds):
        td = tds[i]
        cls = " ".join(td.get("class") or [])
        pred = tds[i + 1] if i + 1 < len(tds) else None
        if "td-bank-bet01" in cls:
            out["spread"] = _parse_bank_pair(td, pred)
            i += 2
        elif "td-bank-bet03" in cls:
            out["moneyline"] = _parse_bank_pair(td, pred)
            i += 2
        elif "td-bank-bet02" in cls:
            out["total"] = _parse_bank_pair(td, pred)
            i += 2
        else:
            i += 1
    return out


def _assign_spread(g: PlaySportMemberGame, side: MemberMarketSide) -> None:
    if side.line is None:
        return
    if side.line > 0:
        g.tw_spread_away = side
    else:
        g.tw_spread_home = side


def _parse_game_blocks(
    soup: BeautifulSoup,
    sport: Sport,
    match_date: str,
    tier: str,
) -> list[PlaySportMemberGame]:
    by_gid: dict[str, list[Any]] = {}
    for tr in soup.select("tr.game-set"):
        gid = tr.get("gameid")
        if gid:
            by_gid.setdefault(str(gid), []).append(tr)

    games: list[PlaySportMemberGame] = []
    for gid, trs in by_gid.items():
        first = trs[0]
        ti = first.select_one("td.td-teaminfo")
        if not ti:
            continue
        wt, st = ti.select_one(".winnerteam"), ti.select_one(".secondteam")
        if not wt or not st:
            continue
        zh_a, zh_b = wt.get_text(strip=True), st.get_text(strip=True)
        en_a, en_b = normalize_matchup(zh_a, zh_b, sport)

        bank_rows = [_extract_bank_cols(tr) for tr in trs if _extract_bank_cols(tr)]
        if not bank_rows:
            continue

        g = PlaySportMemberGame(
            playsport_game_id=gid,
            match_date=match_date,
            sport=sport,
            member_tier=tier,
            team_a_zh=zh_a,
            team_b_zh=zh_b,
            team_a_en=en_a,
            team_b_en=en_b,
        )

        r0 = bank_rows[0]
        if "moneyline" in r0:
            g.tw_ml_away = r0["moneyline"]
        if "total" in r0:
            g.tw_over = r0["total"]
        if "spread" in r0:
            _assign_spread(g, r0["spread"])

        if len(bank_rows) >= 2:
            r1 = bank_rows[1]
            if "moneyline" in r1:
                g.tw_ml_home = r1["moneyline"]
            if "total" in r1:
                g.tw_under = r1["total"]
            if "spread" in r1:
                _assign_spread(g, r1["spread"])

        games.append(g)
    return games


class PlaySportPredictScraper:
    def __init__(self, *, delay_sec: float | None = None):
        self.delay_sec = delay_sec if delay_sec is not None else config.PLAYSPORT_REQUEST_DELAY_SEC
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def fetch_scale_html(
        self,
        sport: Sport,
        match_date: str,
        *,
        member_tier: str = "win60",
    ) -> str:
        alliance = ALLIANCE_ID[sport]
        sid = MEMBER_TIER_SID.get(member_tier, 1)
        gametime = match_date.replace("-", "")
        url = f"{SCALE_URL}?allianceid={alliance}&gametime={gametime}&sid={sid}"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        if self.delay_sec > 0:
            time.sleep(self.delay_sec)
        return resp.text

    def fetch_games_for_date(
        self,
        sport: Sport,
        match_date: str,
        *,
        member_tier: str = "win60",
    ) -> list[PlaySportMemberGame]:
        html = self.fetch_scale_html(sport, match_date, member_tier=member_tier)
        soup = BeautifulSoup(html, "html.parser")
        return _parse_game_blocks(soup, sport, match_date, member_tier)

    def fetch_recent(
        self,
        sport: Sport,
        *,
        days_ahead: int = 7,
        member_tier: str = "win60",
    ) -> list[PlaySportMemberGame]:
        out: list[PlaySportMemberGame] = []
        for offset in range(days_ahead + 1):
            d = (date.today() + timedelta(days=offset)).isoformat()
            try:
                out.extend(self.fetch_games_for_date(sport, d, member_tier=member_tier))
            except Exception as exc:
                logger.warning("玩運彩預測比例 %s %s 失敗: %s", sport, d, exc)
        return out
