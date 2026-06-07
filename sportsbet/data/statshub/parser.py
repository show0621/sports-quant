"""解析 StatsHub 頁面內嵌 React Router 資料流。"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

TENANT_DEFAULT = "taiwansportslottery"
LANG_DEFAULT = "zht"
BASE = "https://statshub.sportradar.com"


def decode_rr(arr: list[Any], idx: int, stack: frozenset[int] | None = None) -> Any:
    """解碼 Sportradar StatsHub 精簡 JSON 參照格式。"""
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
    return val


def extract_stream_array(html: str) -> list[Any]:
    chunks = re.findall(
        r'window\.__reactRouterContext\.streamController\.enqueue\("((?:\\.|[^"])*)"\)',
        html,
    )
    if not chunks:
        raise ValueError("找不到 StatsHub 資料流")
    text = "".join(bytes(c, "utf-8").decode("unicode_escape") for c in chunks)
    return json.loads(text)


def parse_loader_data(html: str) -> dict[str, Any]:
    arr = extract_stream_array(html)
    root = decode_rr(arr, 0)
    if not isinstance(root, dict):
        raise ValueError("StatsHub loader 格式異常")
    loader = root.get("loaderData")
    return loader if isinstance(loader, dict) else {}


def _route_payload(loader: dict[str, Any], page: str) -> dict[str, Any]:
    key = f"routes/_sh.match.$matchId/{page}/_{page}"
    payload = loader.get(key)
    return payload if isinstance(payload, dict) else {}


def extract_match_info(html: str, *, page: str = "statistics") -> dict[str, Any]:
    loader = parse_loader_data(html)
    for route_key in (f"routes/_sh.match.$matchId/{page}/_{page}", "routes/_sh.match.$matchId/_matchRoot"):
        payload = loader.get(route_key, {})
        if not isinstance(payload, dict):
            continue
        mi = payload.get("matchInfo")
        if isinstance(mi, dict) and isinstance(mi.get("data"), dict):
            return mi["data"]
    raise ValueError("頁面無 matchInfo 資料")


def extract_cctx(html: str) -> dict[str, Any]:
    loader = parse_loader_data(html)
    root = loader.get("root", {})
    cctx = root.get("cctx") if isinstance(root, dict) else None
    return cctx if isinstance(cctx, dict) else {}


def fetch_page_html(
    match_id: str | int,
    page: str = "statistics",
    *,
    tenant: str = TENANT_DEFAULT,
    lang: str = LANG_DEFAULT,
    session: requests.Session | None = None,
) -> str:
    url = f"{BASE}/{tenant}/{lang}/match/{match_id}/{page}"
    sess = session or requests.Session()
    resp = sess.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def parse_match_id_from_url(url: str) -> str | None:
    m = re.search(r"/match/(\d+)(?:/|$)", url)
    return m.group(1) if m else None


def statshub_urls(match_id: str | int, *, tenant: str = TENANT_DEFAULT, lang: str = LANG_DEFAULT) -> dict[str, str]:
    base = f"{BASE}/{tenant}/{lang}/match/{match_id}"
    return {
        "report": f"{base}/report",
        "statistics": f"{base}/statistics",
    }
