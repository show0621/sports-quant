"""Probe StatsHub / Sportradar odds endpoints."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsbet.data.statshub.parser import extract_cctx, fetch_page_html, parse_loader_data

MATCH_ID = "70505022"


def main() -> None:
    html = fetch_page_html(MATCH_ID, "report")
    cctx = extract_cctx(html)
    print("cctx keys:", list(cctx.keys())[:25])
    for k in ("oddsDeepLinkUrl", "fishnetUrl", "odds", "tenant", "client"):
        if k in cctx:
            print(f"  {k}:", cctx[k])

    loader = parse_loader_data(html)
    text = json.dumps(loader, ensure_ascii=False)
    urls = sorted(set(re.findall(r"https?://[^\s\"']+", text)))
    for u in urls:
        if any(x in u.lower() for x in ("odds", "mud", "bet", "market")):
            print("URL in loader:", u)

    mud = cctx.get("oddsDeepLinkUrl")
    if mud:
        for path in (
            f"/match/{MATCH_ID}/markets",
            f"/matches/{MATCH_ID}/odds",
            f"/v1/matches/{MATCH_ID}",
        ):
            url = mud.rstrip("/") + path
            try:
                r = requests.get(url, timeout=15)
                print(f"mud {path}: {r.status_code} {r.text[:120]}")
            except Exception as exc:
                print(f"mud {path}: ERR {exc}")


if __name__ == "__main__":
    main()
