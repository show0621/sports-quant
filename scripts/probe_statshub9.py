"""Decode matchRoot payload indices."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "logs"


def load_arr(page: str) -> list[Any]:
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


def main() -> None:
    for page in ("report", "statistics"):
        arr = load_arr(page)
        root = decode(arr, 10)
        OUT.joinpath(f"statshub_{page}_matchroot.json").write_text(
            json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(page, "matchRoot keys", list(root.keys()) if isinstance(root, dict) else root)
        if isinstance(root, dict):
            for k, v in root.items():
                if k in ("dehydratedState", "matchInfo"):
                    continue
                preview = json.dumps(v, ensure_ascii=False)[:200]
                print(" ", k, preview)


if __name__ == "__main__":
    main()
