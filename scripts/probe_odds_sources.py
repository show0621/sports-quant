"""Probe odds sources for upcoming NBA games."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def probe_blob_paths() -> None:
    base = "https://blob.sportslottery.com.tw/apidata"
    # list common paths
    paths = [
        "Live/On.json",
        "Register/On.json",
        "Prematch/On.json",
        "PreMatch/On.json",
        "Pre/On.json",
        "Scheduled/On.json",
        "Sports/On.json",
        "Book/On.json",
        "Open/On.json",
        "Early/On.json",
        "Future/On.json",
        "Register/All.json",
        "Live/All.json",
    ]
    for p in paths:
        url = f"{base}/{p}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            body = r.text[:200].replace("\n", " ")
            print(f"blob {p}: {r.status_code} len={len(r.text)} {body}")
        except Exception as exc:
            print(f"blob {p}: ERR {exc}")


def probe_legacy_api() -> None:
    urls = [
        "https://www.sportslottery.com.tw/api/services/app/LiveGames/GetLiveOnAndRegister?isContainRegister=true",
        "https://www.sportslottery.com.tw/api/services/app/LiveGames/GetLiveOnAndRegister?isContainRegister=false",
        "https://www.sportslottery.com.tw/api/services/app/RegisterGames/GetRegisterOn",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers={**HEADERS, "Referer": "https://www.sportslottery.com.tw/"}, timeout=20)
            print(f"legacy {url.split('/')[-1][:40]}: {r.status_code} len={len(r.text)}")
            if r.status_code == 200 and len(r.text) > 50:
                data = r.json()
                if isinstance(data, dict):
                    result = data.get("result", data)
                    if isinstance(result, dict):
                        for k in ("liveOn", "registerOn", "register"):
                            v = result.get(k)
                            if isinstance(v, list):
                                nba = [e for e in v if e.get("si") == 442]
                                print(f"  {k}: total={len(v)} nba={len(nba)}")
        except Exception as exc:
            print(f"legacy ERR: {exc}")


def probe_statshub(match_id: str = "70505022") -> None:
    url = f"https://statshub.sportradar.com/taiwansportslottery/zht/match/{match_id}/report"
    r = requests.get(url, headers=HEADERS, timeout=30)
    print(f"statshub report: {r.status_code} len={len(r.text)}")
    for kw in ("odds", "market", "handicap", "讓分", "大小", "賠率", "moneyline", "spread"):
        if kw.lower() in r.text.lower() or kw in r.text:
            print(f"  contains: {kw}")
    try:
        from sportsbet.data.statshub.parser import parse_loader_data

        loader = parse_loader_data(r.text)
        print(f"  loader keys: {list(loader.keys())[:8]}")
        # dump small json sample
        sample = json.dumps(loader, ensure_ascii=False)[:2000]
        if "odds" in sample.lower() or "market" in sample.lower():
            print("  loader sample has odds/market keywords")
    except Exception as exc:
        print(f"  parse failed: {exc}")


if __name__ == "__main__":
    print("=== Blob paths ===")
    probe_blob_paths()
    print("\n=== Legacy API ===")
    probe_legacy_api()
    print("\n=== StatsHub ===")
    probe_statshub()
