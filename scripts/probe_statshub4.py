"""Parse StatsHub dehydrated React Router stream from HTML."""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any


def fetch_page(path: str) -> str:
    url = f"https://statshub.sportradar.com/taiwansportslottery/zht/match/70505022/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def extract_stream_chunks(html: str) -> list[str]:
    chunks = re.findall(
        r"window\.__reactRouterContext\.streamController\.enqueue\(\"((?:\\.|[^\"])*)\"\)",
        html,
    )
    return [bytes(c, "utf-8").decode("unicode_escape") for c in chunks]


def parse_dehydrated(chunks: list[str]) -> Any:
    text = "".join(chunks)
    return json.loads(text)


def walk(obj: Any, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(x in kl for x in ("injur", "lineup", "player", "starter", "stat", "team")):
                print(path, k, type(v).__name__, str(v)[:120] if not isinstance(v, (dict, list)) else f"len={len(v)}")
            walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            walk(v, f"{path}[{i}]")


def main() -> None:
    for page in ("report", "statistics"):
        html = fetch_page(page)
        chunks = extract_stream_chunks(html)
        print(f"\n=== {page} chunks={len(chunks)} total_len={sum(len(c) for c in chunks)} ===")
        if not chunks:
            continue
        data = parse_dehydrated(chunks)
        # print top-level structure
        print(json.dumps(data, ensure_ascii=False)[:2500])
        walk(data)


if __name__ == "__main__":
    main()
