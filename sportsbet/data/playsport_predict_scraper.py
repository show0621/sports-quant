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
    # 玩運彩版面：winnerteam=客隊、secondteam=主隊（與運彩盤 客/主 一致）
    ps_away_en: str = ""
    ps_home_en: str = ""

    def to_db_consensus_rows(
        self,
        db_home: str,
        db_away: str,
    ) -> list[dict[str, Any]]:
        """依 DB 主客隊對齊會員占比（避免 winnerteam 與 DB 主客不一致）。"""
        rows: list[dict[str, Any]] = []

        def _db_sel(ps_side: str) -> str | None:
            """ps_side: away/home/over/under → DB selection。"""
            if ps_side == "over":
                return "over"
            if ps_side == "under":
                return "under"
            ps_team = self.ps_away_en if ps_side == "away" else self.ps_home_en
            if ps_team == db_home:
                return "home"
            if ps_team == db_away:
                return "away"
            return None

        for ps_side, market, obj in (
            ("away", "moneyline", self.tw_ml_away),
            ("home", "moneyline", self.tw_ml_home),
            ("away", "spread", self.tw_spread_away),
            ("home", "spread", self.tw_spread_home),
            ("over", "total", self.tw_over),
            ("under", "total", self.tw_under),
        ):
            if obj.pct is None:
                continue
            sel = _db_sel(ps_side)
            if sel is None:
                continue
            rows.append(
                {
                    "playsport_game_id": self.playsport_game_id,
                    "match_date": self.match_date,
                    "sport": self.sport,
                    "member_tier": self.member_tier,
                    "board": "tw",
                    "market": market,
                    "selection": sel,
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
    compact = text.replace(" ", "")
    m = re.search(r"([+-]?\d+\.?\d*)\s*,", compact)
    if not m:
        m = re.search(r"([+-]?\d+\.?\d*)", compact)
    if m:
        try:
            line = float(m.group(1))
        except ValueError:
            pass
    om = _ODDS_TAIL_RE.search(text)
    if om:
        try:
            odds = float(om.group(1))
        except ValueError:
            pass
    return line, odds


def _bank_row_side(bet_txt: str) -> str | None:
    t = bet_txt.strip()
    if t.startswith("客") or t[:4].find("客") >= 0:
        return "away"
    if t.startswith("主") or t[:4].find("主") >= 0:
        return "home"
    if "大" in t[:3]:
        return "over"
    if "小" in t[:3]:
        return "under"
    return None


def _parse_bank_pair(bet_td, predict_td) -> tuple[str | None, MemberMarketSide]:
    bet_txt = bet_td.get_text(" ", strip=True) if bet_td else ""
    pred_txt = predict_td.get_text(" ", strip=True) if predict_td else ""
    pct, count = _parse_pct_count(pred_txt)
    line, odds = _parse_line_odds(bet_txt)
    side = _bank_row_side(bet_txt)
    return side, MemberMarketSide(pct=pct, count=count, line=line, odds=odds)


def _extract_bank_cols(tr) -> list[tuple[str, str, MemberMarketSide]]:
    """回傳 [(market, ps_side, data), ...]。"""
    out: list[tuple[str, str, MemberMarketSide]] = []
    tds = tr.find_all("td", recursive=False)
    i = 0
    while i < len(tds):
        td = tds[i]
        cls = " ".join(td.get("class") or [])
        pred = tds[i + 1] if i + 1 < len(tds) else None
        if "td-bank-bet01" in cls:
            side, data = _parse_bank_pair(td, pred)
            if side in ("away", "home"):
                out.append(("spread", side, data))
            i += 2
        elif "td-bank-bet03" in cls:
            side, data = _parse_bank_pair(td, pred)
            if side in ("away", "home"):
                out.append(("moneyline", side, data))
            i += 2
        elif "td-bank-bet02" in cls:
            side, data = _parse_bank_pair(td, pred)
            if side in ("over", "under"):
                out.append(("total", side, data))
            i += 2
        else:
            i += 1
    return out


def _apply_bank_entry(g: PlaySportMemberGame, market: str, side: str, data: MemberMarketSide) -> None:
    key = {
        ("moneyline", "away"): "tw_ml_away",
        ("moneyline", "home"): "tw_ml_home",
        ("spread", "away"): "tw_spread_away",
        ("spread", "home"): "tw_spread_home",
        ("total", "over"): "tw_over",
        ("total", "under"): "tw_under",
    }.get((market, side))
    if key:
        setattr(g, key, data)


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
            ps_away_en=en_a,
            ps_home_en=en_b,
        )

        for tr in trs:
            for market, side, data in _extract_bank_cols(tr):
                _apply_bank_entry(g, market, side, data)

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
