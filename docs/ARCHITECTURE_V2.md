# 架構 V2.0 — Bottom-Up 與傷兵動態

## 模組分層

```
sportsbet/
├── data/
│   ├── database.py          # SQLite V1 + V2 表
│   ├── ingestion.py         # 賽程/賠率 MOCK + API
│   ├── player_ingestion.py  # 球員/傷兵/先發 MOCK + ESPN 介面預留
│   └── api_sports.py
├── models/
│   ├── analytics_engine.py  # Top-Down：畢達哥拉斯 + 貝氏 + 卜瓦松
│   ├── roster_engine.py     # Bottom-Up：動態陣容評分 ★
│   └── forecast.py          # 單場預測整合（混合 Top/Bottom）
├── services/
│   └── prediction_service.py
├── evaluation/
├── risk/
└── ui/
    ├── dashboard.py
    ├── upcoming_page.py     # 現在/未來賽事預測
    ├── injury_ticker.py     # 傷兵跑馬燈
    └── hot_cold_page.py     # 球員熱區圖
```

## 資料庫 V2 表

| 表 | 用途 |
|----|------|
| `players` | 球員 ID、姓名、隊伍、位置 |
| `player_advanced_stats` | BPM/VORP/USG/Pace (NBA)、WAR/wRC+/FIP (MLB)、滾動 hot/cold |
| `injury_reports` | Out/Doubtful/Questionable/Probable |
| `projected_lineups` | 預計上場時間/局數 |

## 動態陣容演算法 (`DynamicRosterRatingEngine`)

1. 讀取 `projected_lineups` → 預計上場名單  
2. `injury_reports` → 剔除 Out/Doubtful；Questionable 打折  
3. 加權平均 VORP (NBA) 或 WAR (MLB) → `adjusted_rating`  
4. `injury_penalty = baseline_rating - adjusted_rating`  
5. 與畢達哥拉斯勝率混合：`ROSTER_RATING_BLEND`（預設 35%）

## 回測

- `BACKTEST_YEARS=3` → `BACKTEST_DAYS=1095`
- `python scripts/seed_mock_db.py --sport nba` 產生 3 年 MOCK 歷史

## 待接真實資料

- ESPN / CBS 傷兵 RSS → `EspnInjuryProvider`
- Basketball-Reference / FanGraphs 球員高階數據
- API-Sports 球員端點（若方案支援）
