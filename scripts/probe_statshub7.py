"""Decode key StatsHub indices and dump JSON."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any

URL = "https://statshub.sportradar.com/taiwansportslottery/zht/match/70505022/report"
OUT = Path(__file__).resolve().parents[1] / "logs"


def load_arr(page: str = "report") -> list[Any]:
    url = f"https://statshub.sportradar.com/taiwansportslottery/zht/match/70505022/{page}"
    html = urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30,
    ).read().decode("utf-8", "replace")
    chunks = re.findall(
        r'window\.__reactRouterContext\.streamController\.enqueue\("((?:\\.|[^"])*)"\)',
        html,
    )
    return json.loads("".join(bytes(c, "utf-8").decode("unicode_escape") for c in chunks))


def decode(arr: list[Any], idx: int, stack: frozenset[int] | None = None) -> Any:
    if idx < 0 or idx >= len(arr):
        return None
    if stack is None:
        stack = frozenset()
    if idx in stack:
        return None
    val = arr[idx]
    if isinstance(val, dict) and val and all(str(k).startswith("_") for k in val):
        out: dict[str, Any] = {}
        for k_ref, v_ref in val.items():
            key_idx = int(str(k_ref).lstrip("_"))
            key = arr[key_idx]
            if not isinstance(key, str):
                continue
            out[key] = decode(arr, int(v_ref), stack | {idx})
        return out
    return val


def find_strings(obj: Any, needles: tuple[str, ...], path: str = "") -> list[tuple[str, Any]]:
    hits: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            if any(n in str(k).lower() for n in needles):
                hits.append((p, v))
            hits.extend(find_strings(v, needles, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(find_strings(v, needles, f"{path}[{i}]"))
    return hits


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for page in ("report", "statistics"):
        arr = load_arr(page)
        route = decode(arr, 12 if page == "report" else 12)  # may differ
        # locate report/statistics route dict index
        route_idx = None
        for i, v in enumerate(arr):
            if v == f"routes/_sh.match.$matchId/{page}/_{page}":
                route_idx = i + 1
                break
        if route_idx is None:
            print(page, "route not found")
            continue
        payload = decode(arr, route_idx)
        OUT.joinpath(f"statshub_{page}_route.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(page, "route keys", list(payload.keys()) if isinstance(payload, dict) else type(payload))
        if isinstance(payload, dict):
            ds = payload.get("dehydratedState")
            mi = payload.get("matchInfo")
            if mi:
                OUT.joinpath(f"statshub_{page}_matchinfo.json").write_text(
                    json.dumps(mi, ensure_ascii=False, indent=2), encoding="utf-8",
                )
            if ds:
                OUT.joinpath(f"statshub_{page}_dehydrated.json").write_text(
                    json.dumps(ds, ensure_ascii=False, indent=2), encoding="utf-8",
                )
                for path, val in find_strings(ds, ("injur", "lineup", "starter", "player", "stat", "missing"))[:40]:
                    print(" ", path, str(val)[:100])


if __name__ == "__main__":
    main()
