"""Probe Sportradar StatsHub pages for API endpoints."""
from __future__ import annotations

import json
import re
import urllib.request

MATCH_ID = "70505022"
BASE = f"https://statshub.sportradar.com/taiwansportslottery/zht/match/{MATCH_ID}"

PAGES = ["report", "statistics", "lineups", "players", "injuries", "overview"]

CANDIDATE_APIS = [
    f"https://statshub.sportradar.com/api/match/{MATCH_ID}",
    f"https://statshub.sportradar.com/api/matches/{MATCH_ID}",
    f"https://statshub.sportradar.com/taiwansportslottery/api/match/{MATCH_ID}",
    f"https://statshub.sportradar.com/taiwansportslottery/api/matches/{MATCH_ID}",
    f"https://statshub.sportradar.com/taiwansportslottery/api/match/{MATCH_ID}/report",
    f"https://statshub.sportradar.com/taiwansportslottery/api/match/{MATCH_ID}/statistics",
    f"https://statshub.sportradar.com/taiwansportslottery/api/match/{MATCH_ID}/lineups",
    f"https://statshub.sportradar.com/taiwansportslottery/api/match/{MATCH_ID}/injuries",
    f"https://api.statshub.sportradar.com/taiwansportslottery/match/{MATCH_ID}",
    f"https://api.statshub.sportradar.com/match/{MATCH_ID}",
]


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, body[:8000]
    except Exception as exc:
        return -1, str(exc)[:200]


def main() -> None:
    for page in PAGES:
        url = f"{BASE}/{page}"
        status, body = fetch(url)
        print(f"\n=== PAGE {page} status={status} len={len(body)} ===")
        if status == 200:
            for pat in [
                r"https://[^\"'\s>]+sportradar[^\"'\s>]+",
                r"/api/[^\"'\s>]+",
                r"__NEXT_DATA__",
            ]:
                hits = sorted(set(re.findall(pat, body)))
                for h in hits[:15]:
                    print(" ", h[:140])

            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.S)
            if m:
                data = json.loads(m.group(1))
                print(" NEXT keys:", list(data.keys()))
                props = data.get("props", {}).get("pageProps", {})
                print(" pageProps keys:", list(props.keys())[:20])

    print("\n=== API CANDIDATES ===")
    for url in CANDIDATE_APIS:
        status, body = fetch(url)
        preview = body.replace("\n", " ")[:120]
        print(f"{status} {url}\n  {preview}")


if __name__ == "__main__":
    main()
