# 運動計算專案

NBA / MLB 台灣運彩量化監控與回測系統。結合運動統計學（畢達哥拉斯期望值）、機率推論（貝氏 / 馬可夫）與財務工程（期望值、凱利資金控管）。

**本專案僅使用真實 API / 爬蟲資料，禁止 mock 或合成賽果。**

詳見 [docs/ARCHITECTURE_V2.md](docs/ARCHITECTURE_V2.md)

## 快速開始

```powershell
cd "C:\Users\show0\OneDrive\Desktop\運動計算專案"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

### 同步真實資料

```powershell
# 每日：賽程 + 運彩 Blob + 預測
python main.py sync --mode daily --sport all

# 回測：歷史賽果 + 玩運彩/JBot 盤口 + 覆盤 forecast
python main.py sync --mode backtest --sport all --full

# 修復 DB / 清除污染資料
python scripts/purge_fake_data.py
python scripts/repair_backtest.py --sport nba

# 驗證資料真實性
python scripts/validate_model.py
```

### Streamlit 看板

```powershell
streamlit run dashboard.py
```

### 歷史 moneyline（JBot，必填才有回測 EV）

1. 至 [sportsbot.tech/trial](https://sportsbot.tech/trial) 申請 API 密鑰
2. 本機設定（不會 commit）：

```powershell
python scripts/setup_jbot_token.py YOUR_JBOT_TOKEN
python scripts/sync_jbot_moneyline.py --sport all --days 14 --rebuild
python main.py push-db
```

3. Streamlit Cloud → **Settings → Secrets** 加入 `JBOT_TOKEN = "..."`

```powershell
# 或透過 backtest 流程自動同步 JBot
python main.py sync --mode backtest --sport nba
```

## 資料來源

| 資料 | 來源 |
|------|------|
| NBA 賽程/賽果 | nba_api + ESPN |
| MLB 賽程/賽果 | ESPN + MLB Stats API |
| 台灣即時盤口 | 運彩 Blob |
| 歷史盤口 | 玩運彩 / JBot |
| 傷兵/先發 | ESPN |

## GitHub 資料庫

`data/sportsbet.db` 會追蹤至 repo（供 Streamlit Cloud）。更新後：

```powershell
python main.py push-db
```

## 核心公式

- 畢達哥拉斯：`Win% = RS^x / (RS^x + RA^x)`
- Log5 單場勝率、貝氏近況修正、馬可夫 Hot/Cold
- EV：`P × O - 1`；四分之一凱利控管

## 參數實驗（非回測）

`streamlit run simulator.py` — 手動輸入 RS/RA 與賠率，**不寫入資料庫**。
