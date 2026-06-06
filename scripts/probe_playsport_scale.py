"""Probe PlaySport predict/scale HTML structure."""
import re
import requests
from bs4 import BeautifulSoup

url = "https://www.playsport.cc/predict/scale?allianceid=3&gametime=20260606&sid=1"
r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
soup = BeautifulSoup(r.text, "html.parser")

for tr in soup.select("tr.game-set"):
    gid = tr.get("gameid")
    print("gameid", gid)
    # find parent table context - game-set appears twice per game (2 rows)
    
for table in soup.select("table"):
    if not table.select("tr.game-set"):
        continue
    print("TABLE classes", table.get("class"))
    header = table.select("tr th, tr td")
    
rows = []
current = None
for tr in soup.find_all("tr"):
    if tr.get("gameid"):
        if current:
            rows.append(current)
        current = {"gameid": tr.get("gameid"), "parts": []}
    if current is not None:
        tds = tr.find_all("td", recursive=False)
        if tds:
            part = []
            for td in tds:
                cls = " ".join(td.get("class") or [])
                txt = td.get_text(" ", strip=True)
                part.append((cls, txt[:80]))
            current["parts"].append(part)
if current:
    rows.append(current)

for g in rows:
    print("\n===", g["gameid"], "parts", len(g["parts"]))
    for i, part in enumerate(g["parts"]):
        for cls, txt in part:
            if txt:
                print(f"  [{i}] {cls}: {txt}")

# team links
for a in soup.select("a[href*='teamid=']"):
    print("team", a.get_text(strip=True), a.get("href"))
