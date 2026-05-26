# 運動計算專案

NBA / MLB 台灣運彩（威剛）量化監控與回測系統。結合運動統計學（畢達哥拉斯期望值）、機率推論（貝氏定理）與財務工程（期望值、凱利資金控管）。

## V2.0 擴充（Bottom-Up + 傷兵）

詳見 [docs/ARCHITECTURE_V2.md](docs/ARCHITECTURE_V2.md)

- **回測預設 3 年**：`BACKTEST_YEARS=3`（1095 天）
- **動態陣容評分**：`sportsbet/models/roster_engine.py`（VORP/WAR 加權 + 傷兵剔除）
- **看板**：傷兵跑馬燈、賽事預測（現在/未來）、回測覆盤、球員熱區圖

```powershell
python main.py seed --sport nba
python scripts/seed_mock_db.py --sport nba
```

## 系統架構

```
資料獲取 (data/)        →  ingestion 介面、MOCK、SQLite、API-Sports、運彩 Blob
分析引擎 (models/)      →  AnalyticsEngine：畢達哥拉斯、貝氏、卜瓦松大小分
風險控管 (risk/)        →  EV、四分之一凱利
驗證評估 (evaluation/)  →  Brier、校準度、資金曲線
前端看板 (ui/)          →  Streamlit 三頁：每日預測、模型健康、資金回測
監控告警 (monitor/)     →  每日掃描、Telegram / LINE
```

## 快速開始

```powershell
cd "C:\Users\show0\OneDrive\Desktop\運動計算專案"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# 編輯 .env 填入 API_SPORTS_KEY（至 https://api-sports.io/ 後台取得）
```

**Streamlit Cloud**：在 App → Settings → Secrets 加入：

```toml
API_SPORTS_KEY = "你的金鑰"
# 選填：自動將 data/sportsbet.db 推送到 GitHub（需 repo 寫入權限）
# GITHUB_TOKEN = "ghp_xxxxxxxx"
```

（可參考 `.streamlit/secrets.toml.example`）

**GitHub 資料庫持久化**：`data/sportsbet.db` 會被追蹤並在資料更新後自動 push（需設定 `GITHUB_TOKEN`）。本機可執行：

```powershell
python main.py refresh-backtest --sport nba --push
python main.py push-db
```

### 1. 抓取國外賽事數據（API-Sports）

先在 `.env` 設定 `API_SPORTS_KEY`，再執行：

```powershell
python main.py fetch --sport nba --season 2025
python main.py fetch --sport mlb --season 2025
```

看板側欄可點 **「同步 API-Sports + 運彩賠率」**（賽程/統計來自 API，賠率來自台灣運彩 Blob）。

### 2. 運彩賠率

```powershell
# 範例資料（離線開發）
python main.py scrape --sample

# 即時：運彩官方 Blob（Live/Register On.json）
python main.py scrape --sport nba

# 歷史：JBot API（需在 .env 設定 JBOT_TOKEN）
python main.py scrape --sport nba --jbot --days-back 30
```

標準賠率欄位：`source, scrape_time, event_id, sport, league, match_datetime, match_date, home_team, away_team, market, selection, handicap, odds, min_parlay, odds_phase`

### 3. MOCK 資料與 SQLite

```powershell
python main.py seed --sport nba --days 60
# 或
python scripts/seed_mock_db.py --sport nba
```

資料庫預設路徑：`data/sportsbet.db`（賽程、賠率、預測、賽果）

### 4. Streamlit 量化看板（三頁）

```powershell
python main.py simulate
# 或
streamlit run dashboard.py
```

- **每日預測**：正 EV 場次、模型勝率、凱利建議倉位
- **模型健康度**：Brier Score、校準度曲線
- **資金回測**：ROI、最大回撤、淨值曲線

舊版單頁參數實驗：`python main.py simulate --legacy` 或 `streamlit run simulator.py`

### 5. 每日掃描與告警

```powershell
python main.py scan --sport nba --offline
python main.py scan --sport nba --notify
```

### 6. 回測

```powershell
# 簡易示範（範例賠率）
python main.py backtest --sport nba

# 合併真實賽果 + 賽前 model_prob（需先 fetch）
python main.py fetch --sport nba --season 2024
python main.py merge-backtest --sport nba --sample --save
python main.py merge-backtest --sport nba --jbot --start 2024-10-01 --end 2024-10-31 --save

# 或直接執行腳本
python scripts/merge_backtest.py --sport nba --live --save
```

## 核心公式

| 模組 | 公式 |
|------|------|
| 畢達哥拉斯 | `Win% = RS^x / (RS^x + RA^x)`，NBA x≈14，MLB x≈1.83 |
| 貝氏修正 | `posterior_odds = prior_odds × LR` |
| 期望值 | `EV = P × O − 1` |
| 凱利 | `f* = EV / (O − 1)`，預設四分之一凱利 |
| 大小分 | 卜瓦松卷積：`P(總分 > line)` |
| 串關 | `EV = P₁×P₂×…×O − 1` |

## 台灣運彩注意事項

- **高抽水**：返還率約 75%～78%，賠率 1.75 時盈虧平衡勝率約 **57.1%**
- **強制串關**：`min_parlay ≥ 2` 時須用 `evaluate_parlay()` 計算組合 EV

## 目錄結構

```
運動計算專案/
├── sportsbet/
│   ├── analytics.py      # 核心演算法（畢達哥拉斯、貝氏、EV）
│   ├── config.py
│   ├── data/             # ingestion、SQLite、API、運彩 Blob
│   ├── models/           # AnalyticsEngine、GamePredictor、卜瓦松大小分
│   ├── risk/             # EV、凱利資金控管
│   ├── evaluation/       # Brier、校準度、回測報告
│   ├── ui/               # Streamlit 看板
│   ├── backtest/         # 回測引擎
│   └── monitor/          # 掃描與告警
├── scripts/
├── dashboard.py          # Streamlit 三頁看板
├── simulator.py          # 舊版單頁模擬器
├── main.py
└── data/                 # 本地資料（gitignore）
```

## 資料來源

| 來源 | 用途 | 設定 |
|------|------|------|
| API-Sports | 賽果、球隊統計 | `API_SPORTS_KEY` |
| 運彩 Blob | 即時/受注賠率 | `SPORTSLOTTERY_BLOB_BASE` |
| JBot | 歷史開盤/收盤 | `JBOT_TOKEN` |

## 下一步開發建議

1. 申請 [JBot](https://sportsbot.tech/api/) 密鑰，抓取 30～180 天歷史賠率回測
2. 調整 `team_names.py` 中未匹配的隊名別名
3. 調整 `BAYES_RECENT_WEIGHT` 等參數，觀察 Brier Score 與 ROI
4. 設定 Telegram / LINE token 啟用即時告警

## 免責聲明

本專案僅供學術研究與量化分析，不構成投注建議。請遵守當地法規與彩券網站服務條款。
