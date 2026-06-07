"""Decode React Router compact stream and inspect StatsHub match payload."""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any


def fetch_page(match_id: str, page: str) -> str:
    url = f"https://statshub.sportradar.com/taiwansportslottery/zht/match/{match_id}/{page}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def extract_stream(html: str) -> list[Any]:
    chunks = re.findall(
        r"window\.__reactRouterContext\.streamController\.enqueue\(\"((?:\\.|[^\"])*)\"\)",
        html,
    )
    text = "".join(bytes(c, "utf-8").decode("unicode_escape") for c in chunks)
    return json.loads(text)


def decode_rr(arr: list[Any], idx: int, stack: frozenset[int] | None = None) -> Any:
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
            out[key] = decode_rr(arr, int(v_ref), stack | {idx})
        return out
    if isinstance(val, list):
        return [decode_rr(arr, int(x), stack | {idx}) if isinstance(x, int) else x for x in val]
    return val


def find_keys(obj: Any, needles: tuple[str, ...], path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(n in kl for n in needles):
                preview = json.dumps(v, ensure_ascii=False)[:200] if not isinstance(v, (dict, list)) else type(v).__name__
                print(f"{path}.{k}: {preview}")
            find_keys(v, needles, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            find_keys(v, needles, f"{path}[{i}]")


def main() -> None:
    match_id = "70505022"
    for page in ("report", "statistics", "lineups"):
        try:
            html = fetch_page(match_id, page)
        except Exception as exc:
            print(page, "fetch fail", exc)
            continue
        arr = extract_stream(html)
        root = decode_rr(arr, 0)
        loader = root.get("loaderData", {}) if isinstance(root, dict) else {}
        print(f"\n=== {page} loader routes: {list(loader.keys())} ===")
        for route, payload in loader.items():
            if "match" not in route:
                continue
            ds = payload.get("dehydratedState") if isinstance(payload, dict) else None
            if not isinstance(ds, dict):
                continue
            for qk, qv in ds.items():
                if isinstance(qv, dict) and "queryKey" in qv:
                    print(" query", qv.get("queryKey"), "tab", qv.get("tabName"))
                    data = qv.get("data")
                    if isinstance(data, dict):
                        find_keys(data, ("injur", "lineup", "starter", "player", "stat", "missing", "sidelin"))
        # dump one route fully for report
        if page == "report":
            rep = loader.get("routes/_sh.match.$matchId/report/_report", {})
            ds = rep.get("dehydratedState", {})
            out_path = f"logs/statshub_decoded_{page}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(ds, f, ensure_ascii=False, indent=2)
            print("saved", out_path)


if __name__ == "__main__":
    main()
