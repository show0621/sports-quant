# 架構 V3 — 真實資料 ETL 分離

## 模組分層

```
sportsbet/
├── data/
│   ├── orchestrator.py       # ETL 編排（daily / backtest / games / odds / players）
│   ├── registry/
│   │   └── team_registry.py  # 隊名 canonical 對齊
│   ├── nba_player_stats.py   # nba_api 球員 OFF/NET + game log 滾動
│   ├── mlb_player_stats.py   # ESPN athlete statistics
│   ├── data_quality.py       # 資料品質 gate（Bottom-Up 啟用條件）
│   ├── hybrid_provider.py    # nba_api + ESPN + 運彩 Blob
│   └── player_ingestion.py   # 傷兵 + 球員 + 先發（無 mock）
├── models/
│   ├── analytics_engine.py   # Top-Down
│   ├── roster_engine.py      # Bottom-Up（需真實 vorp/war）
│   └── forecast.py           # 混合預測 + feature gate
├── services/
│   ├── prediction_service.py
│   └── data_refresh.py
└── ui/
    └── dashboard.py          # 唯讀為主，ETL 走 CLI / GitHub Actions
```

## 資料源（一域一主源）

| 資料 | NBA | MLB |
|------|-----|-----|
| 賽程/賽果 | nba_api + ESPN | ESPN + **MLB Stats API** |
| 台灣盤口 | 運彩 Blob | 運彩 Blob |
| 歷史盤口 | JBot / 玩運彩 | JBot / 玩運彩 |
| 傷兵/先發 | ESPN | ESPN |
| 球員統計 | nba_api Advanced + GameLog | ESPN athlete stats |
| 情境特徵 | DB 計算（休息/B2B/H2H） | 同左 |

## 勝率集成模型

Log5 + 貝氏 + Beta-Binomial + 馬可夫 Hot/Cold + 情境修正 → `probability_engine.py`

回測 EV 驗證 → `evaluation/ev_report.py`（ROI、Profit Factor、p-value）

## 回測誠實性（V3.1）

- **賽前 stats**：`point_in_time_stats.py` + `run_backtest_reconcile`（禁止全季 stats 前視）
- **回測不套用傷兵修正**（`use_roster=False`）
- **moneyline**：JBot 歷史盤 → 缺漏補 `TW_MONEYLINE_ODDS=1.75`
- **占位 final 清理**：`cleanup_placeholder_final_games()`

## CLI

```bash
python main.py sync --mode daily --sport all      # 每日管線
python main.py sync --mode backtest --sport all   # 增量覆盤
python main.py sync --mode players --sport nba    # 球員真實統計
python main.py scan --sport nba --notify          # 正 EV 掃描
```

## GitHub Actions

`.github/workflows/daily-sync.yml` — 每日 UTC 00:00 自動 sync + push DB。

## 禁止虛擬資料

- 已移除 `MockDataProvider`
- `load_sample_format()` 已停用
- 陣容引擎僅在 `has_real_player_stats()` 為真時混合 Bottom-Up
