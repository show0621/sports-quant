"""Probe Sportradar StatsHub for internal JSON API routes."""
from __future__ import annotations

import json
import re
import urllib.request

MATCH_ID = "70505022"
TENANT = "taiwansportslottery"
BASE = f"https://statshub.sportradar.com/{TENANT}/zht/match/{MATCH_ID}/report"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/json"}


def get(url: str, accept_json: bool = False) -> tuple[int, bytes]:
    h = dict(HEADERS)
    if accept_json:
        h["Accept"] = "application/json"
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, resp.read()
    except Exception as exc:
        return -1, str(exc).encode()


def main() -> None:
    status, raw = get(BASE)
    html = raw.decode("utf-8", "replace")
    print("report html len", len(html), "status", status)

    # Next.js data
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if m:
        data = json.loads(m.group(1))
        print("__NEXT_DATA__ keys", data.keys())
        pp = data.get("props", {}).get("pageProps", {})
        print("pageProps", json.dumps(pp, ensure_ascii=False)[:2000])
    else:
        print("no __NEXT_DATA__")

    # script src
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
    print("scripts", len(scripts))
    for s in scripts[:8]:
        print(" ", s[:120])

    # inline api hints
    apis = sorted(set(re.findall(r'["\'](/[^"\']*api[^"\']*)["\']', html)))
    print("inline api paths", apis[:30])

    # fetch first few _next static chunks for api strings
    for s in scripts:
        if "_next/static" not in s:
            continue
        url = s if s.startswith("http") else "https://statshub.sportradar.com" + s
        st, body = get(url)
        text = body.decode("utf-8", "replace")
        hits = sorted(set(re.findall(r'["\'](/[^"\']*(?:api|match|lineup|injur|stat)[^"\']*)["\']', text)))
        if hits:
            print(f"\nchunk {s[-40:]} hits={len(hits)}")
            for h in hits[:25]:
                print(" ", h)

    # try json accept on common paths
    candidates = [
        f"https://statshub.sportradar.com/{TENANT}/api/v1/match/{MATCH_ID}",
        f"https://statshub.sportradar.com/{TENANT}/api/v1/matches/{MATCH_ID}",
        f"https://statshub.sportradar.com/{TENANT}/api/v1/match/{MATCH_ID}/report",
        f"https://statshub.sportradar.com/{TENANT}/api/v1/match/{MATCH_ID}/statistics",
        f"https://statshub.sportradar.com/{TENANT}/api/v1/match/{MATCH_ID}/lineups",
        f"https://statshub.sportradar.com/{TENANT}/api/v1/match/{MATCH_ID}/injuries",
        f"https://statshub.sportradar.com/{TENANT}/api/v1/match/{MATCH_ID}/players",
        f"https://statshub.sportradar.com/{TENANT}/api/match/{MATCH_ID}/data",
        f"https://statshub.sportradar.com/{TENANT}/bff/match/{MATCH_ID}",
        f"https://statshub.sportradar.com/{TENANT}/graphql",
    ]
    print("\n=== JSON probes ===")
    for url in candidates:
        st, body = get(url, accept_json=True)
        preview = body[:180].decode("utf-8", "replace")
        print(st, url)
        print(" ", preview.replace("\n", " "))


if __name__ == "__main__":
    main()
