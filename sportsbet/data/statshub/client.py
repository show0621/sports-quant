"""Sportradar StatsHub（台灣運彩）資料客戶端。"""
from __future__ import annotations

import json
import logging
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import requests

from sportsbet.data.statshub.feeds import merge_feed_results, parse_gismo_feed, parse_match_info_doc
from sportsbet.data.statshub.parser import (
    extract_cctx,
    extract_match_info,
    fetch_page_html,
    parse_match_id_from_url,
    statshub_urls,
)

logger = logging.getLogger(__name__)

FEEDS_FOR_MATCH = (
    "match_stats",
    "match_squads",
    "match_playerdetails",
    "match_details",
    "match_detailsextended",
)


@dataclass
class StatsHubMatchBundle:
    sportradar_match_id: str
    match_info: dict[str, Any]
    summary: dict[str, Any]
    feeds: dict[str, Any] = field(default_factory=dict)
    merged: dict[str, Any] = field(default_factory=dict)
    urls: dict[str, str] = field(default_factory=dict)
    fetch_errors: list[str] = field(default_factory=list)


class StatsHubClient:
    """抓取 StatsHub SSR 並嘗試 Fishnet Gismo feeds。"""

    def __init__(
        self,
        *,
        tenant: str = "taiwansportslottery",
        lang: str = "zht",
        timezone: str = "Asia/Taipei",
        session: requests.Session | None = None,
    ) -> None:
        self.tenant = tenant
        self.lang = lang
        self.timezone = timezone
        self.session = session or requests.Session()

    def fetch_match_bundle(self, match_id: str | int) -> StatsHubMatchBundle:
        mid = str(match_id)
        html = fetch_page_html(mid, "statistics", tenant=self.tenant, lang=self.lang, session=self.session)
        info_raw = extract_match_info(html, page="statistics")
        summary = parse_match_info_doc(info_raw)
        cctx = extract_cctx(html)

        feeds: dict[str, Any] = {}
        errors: list[str] = []
        for feed in FEEDS_FOR_MATCH:
            try:
                feeds[feed] = self._fetch_gismo_feed(cctx, feed, mid)
            except Exception as exc:
                errors.append(f"{feed}: {exc}")
                logger.debug("StatsHub feed 失敗 %s %s: %s", mid, feed, exc)

        parsed = [parse_gismo_feed(k, v, match_info=summary) for k, v in feeds.items() if isinstance(v, dict)]
        merged = merge_feed_results(parsed)

        return StatsHubMatchBundle(
            sportradar_match_id=mid,
            match_info=info_raw,
            summary=summary,
            feeds=feeds,
            merged=merged,
            urls=statshub_urls(mid, tenant=self.tenant, lang=self.lang),
            fetch_errors=errors,
        )

    def _fetch_gismo_feed(self, cctx: dict[str, Any], feed: str, match_id: str) -> dict[str, Any]:
        token = cctx.get("fishnetToken")
        base = str(cctx.get("fishnetUrl") or "https://sh.fn.sportradar.com").rstrip("/")
        alias = cctx.get("fishnetClientAlias") or self.tenant
        if not token:
            raise RuntimeError("缺少 fishnetToken")

        path = f"/{alias}/{self.lang}/{self.timezone}/gismo/{feed}/{match_id}"
        url = f"{base}{path}?T={urllib.parse.quote(str(token), safe='')}"
        referer = statshub_urls(match_id, tenant=self.tenant, lang=self.lang)["statistics"]
        resp = self.session.get(
            url,
            headers={
                "Referer": referer,
                "Origin": "https://statshub.sportradar.com",
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=25,
        )
        resp.raise_for_status()
        payload = resp.json()
        doc = payload.get("doc") if isinstance(payload, dict) else None
        if isinstance(doc, list) and doc and isinstance(doc[0], dict):
            if doc[0].get("event") == "exception":
                raise RuntimeError(doc[0].get("data", {}).get("message", "Unauthorized feed"))
        return payload

    @staticmethod
    def match_id_from_url(url: str) -> str | None:
        return parse_match_id_from_url(url)

    def bundle_to_json(self, bundle: StatsHubMatchBundle) -> str:
        return json.dumps(
            {
                "sportradar_match_id": bundle.sportradar_match_id,
                "summary": bundle.summary,
                "merged": bundle.merged,
                "fetch_errors": bundle.fetch_errors,
                "urls": bundle.urls,
            },
            ensure_ascii=False,
        )

    def bundle_from_feeds(
        self,
        match_id: str | int,
        feeds: dict[str, Any],
        *,
        summary: dict[str, Any] | None = None,
    ) -> StatsHubMatchBundle:
        """從瀏覽器匯出的 Gismo JSON 組裝 bundle（繞過 origin 限制）。"""
        mid = str(match_id)
        summary = summary or {}
        parsed = [parse_gismo_feed(k, v, match_info=summary) for k, v in feeds.items() if isinstance(v, dict)]
        merged = merge_feed_results(parsed)
        return StatsHubMatchBundle(
            sportradar_match_id=mid,
            match_info={},
            summary=summary,
            feeds=feeds,
            merged=merged,
            urls=statshub_urls(mid, tenant=self.tenant, lang=self.lang),
            fetch_errors=[],
        )
