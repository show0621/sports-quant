"""運彩量化系統常數與環境設定。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
NBA_DATA_DIR = DATA_DIR / "nba"
MLB_DATA_DIR = DATA_DIR / "mlb"
WANDA_DATA_DIR = DATA_DIR / "wanda"
LOG_DIR = PROJECT_ROOT / "logs"

for _d in (NBA_DATA_DIR, MLB_DATA_DIR, WANDA_DATA_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- API ---
API_SPORTS_BASE = "https://v1.basketball.api-sports.io"  # NBA
API_SPORTS_MLB_BASE = "https://v1.baseball.api-sports.io"  # MLB
API_SPORTS_LEAGUE_NBA = int(os.getenv("API_SPORTS_LEAGUE_NBA", "12"))
API_SPORTS_LEAGUE_MLB = int(os.getenv("API_SPORTS_LEAGUE_MLB", "1"))


def resolve_api_sports_key() -> str:
    """從 .env 或 Streamlit Secrets 讀取 API-Sports 金鑰。"""
    key = os.getenv("API_SPORTS_KEY", "").strip()
    if key:
        return key
    try:
        import streamlit as st

        return str(st.secrets.get("API_SPORTS_KEY", "")).strip()
    except Exception:
        return ""


API_SPORTS_KEY = resolve_api_sports_key()

# --- 畢達哥拉斯指數 ---
PYTH_EXPONENT_NBA = float(os.getenv("PYTH_EXPONENT_NBA", "14.0"))
PYTH_EXPONENT_MLB = float(os.getenv("PYTH_EXPONENT_MLB", "1.83"))

# MLB 動態指數（可選）：1.5 * log10((RS+RA)/G) + 0.45
USE_DYNAMIC_MLB_EXPONENT = os.getenv("USE_DYNAMIC_MLB_EXPONENT", "false").lower() == "true"

# --- 貝氏修正權重 ---
BAYES_HOME_ADVANTAGE = float(os.getenv("BAYES_HOME_ADVANTAGE", "0.03"))  # 主場 +3%
BAYES_RECENT_GAMES = int(os.getenv("BAYES_RECENT_GAMES", "5"))
BAYES_RECENT_WEIGHT = float(os.getenv("BAYES_RECENT_WEIGHT", "0.25"))  # 近況權重 0~1
BAYES_INJURY_PENALTY = float(os.getenv("BAYES_INJURY_PENALTY", "0.05"))  # 核心缺陣 -5%

# --- 台灣運彩抽水 ---
TAIWAN_VIG_RETURN_RATE = float(os.getenv("TAIWAN_VIG_RETURN_RATE", "0.76"))  # 返還率 76%
# 平手盤 1.75/1.75 時，盈虧平衡勝率 ≈ 1/1.75 ≈ 57.14%
BREAKEVEN_WIN_RATE_AT_175 = 1.0 / 1.75

# --- 凱利與資金控管 ---
INITIAL_BANKROLL = float(os.getenv("INITIAL_BANKROLL", "100000"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))  # 四分之一凱利
MAX_BET_FRACTION = float(os.getenv("MAX_BET_FRACTION", "0.05"))  # 單注上限 5%
MIN_EV_THRESHOLD = float(os.getenv("MIN_EV_THRESHOLD", "0.02"))  # EV > 2% 才進場

# --- 回測區間 ---
BACKTEST_YEARS = int(os.getenv("BACKTEST_YEARS", "3"))
BACKTEST_DAYS = int(os.getenv("BACKTEST_DAYS", str(BACKTEST_YEARS * 365)))

# --- V2 Bottom-Up ---
USE_ROSTER_RATING = os.getenv("USE_ROSTER_RATING", "true").lower() == "true"
ROSTER_RATING_BLEND = float(os.getenv("ROSTER_RATING_BLEND", "0.35"))  # 與畢達哥拉斯混合權重
INJURY_EXCLUDE_STATUSES = ("Out", "Doubtful")
INJURY_DISCOUNT = {"Questionable": 0.5, "Probable": 0.85}

# --- GitHub 資料庫持久化 ---
GITHUB_DB_SYNC_ENABLED = os.getenv("GITHUB_DB_SYNC_ENABLED", "true").lower() == "true"
GITHUB_REPO_REMOTE = os.getenv("GITHUB_REPO_REMOTE", "https://github.com/show0621/sports-quant.git")

# --- 威剛爬蟲（舊 HTML；現以運彩 Blob + JBot 為主） ---
WANDA_BASE_URL = os.getenv("WANDA_BASE_URL", "https://www.twsport.com.tw")
WANDA_REQUEST_DELAY_SEC = float(os.getenv("WANDA_REQUEST_DELAY_SEC", "1.5"))

# --- 台灣運彩 Blob API（公開 JSON）---
SPORTSLOTTERY_BLOB_BASE = os.getenv(
    "SPORTSLOTTERY_BLOB_BASE",
    "https://blob.sportslottery.com.tw/apidata",
)

# --- JBot 歷史賠率 https://sportsbot.tech/api/sportslottery/ ---
JBOT_TOKEN = os.getenv("JBOT_TOKEN", "")
# 內部 sport → JBot API sport code
JBOT_SPORT_CODES: dict[str, str] = {
    "nba": os.getenv("JBOT_SPORT_CODE_NBA", "BKB"),
    "mlb": os.getenv("JBOT_SPORT_CODE_MLB", "BSB"),
}

# --- 告警 ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
LINE_NOTIFY_TOKEN = os.getenv("LINE_NOTIFY_TOKEN", "")


@dataclass(frozen=True)
class SportConfig:
    name: str
    pyth_exponent: float
    data_dir: Path


NBA = SportConfig("nba", PYTH_EXPONENT_NBA, NBA_DATA_DIR)
MLB = SportConfig("mlb", PYTH_EXPONENT_MLB, MLB_DATA_DIR)
