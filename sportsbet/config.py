"""運彩量化系統常數與環境設定。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
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
# 免費方案通常僅 2022–2024；付費後可調高 API_SPORTS_SEASON_MAX
API_SPORTS_SEASON_MIN = int(os.getenv("API_SPORTS_SEASON_MIN", "2022"))
API_SPORTS_SEASON_MAX = int(os.getenv("API_SPORTS_SEASON_MAX", "2024"))

# hybrid（預設）| api_sports
DATA_SOURCE = os.getenv("DATA_SOURCE", "hybrid").strip().lower()

# API-Sports 僅付費明確啟用時用於賽程（免費方案不穩定）
API_SPORTS_USE_FOR_SCHEDULE = os.getenv("API_SPORTS_USE_FOR_SCHEDULE", "false").lower() == "true"

# 玩運彩：僅完整/週期同步時執行（日常 live 不同步，避免 80 秒爬蟲）
PLAYSPORT_ENABLED = os.getenv("PLAYSPORT_ENABLED", "true").lower() == "true"
PLAYSPORT_ON_INCREMENTAL = os.getenv("PLAYSPORT_ON_INCREMENTAL", "false").lower() == "true"
PLAYSPORT_REQUEST_DELAY_SEC = float(os.getenv("PLAYSPORT_REQUEST_DELAY_SEC", "1.2"))
PLAYSPORT_MAX_TEAMS_PER_SYNC = int(os.getenv("PLAYSPORT_MAX_TEAMS_PER_SYNC", "30"))

# --- 即時同步 / 看板 ---
LIVE_SYNC_INTERVAL_SEC = int(os.getenv("LIVE_SYNC_INTERVAL_SEC", "180"))  # watch 背景每 3 分鐘
DASHBOARD_AUTOREFRESH_SEC = int(os.getenv("DASHBOARD_AUTOREFRESH_SEC", "120"))  # 看板每 2 分鐘刷新
LIVE_SYNC_DAYS_AHEAD = int(os.getenv("LIVE_SYNC_DAYS_AHEAD", "21"))  # 含季後賽/總冠軍賽完整排程
SCHEDULE_SYNC_DAYS_AHEAD = int(os.getenv("SCHEDULE_SYNC_DAYS_AHEAD", "21"))

# --- 賽事帳本（從指定日起累積每場賽前/賽後快照；起始日首次同步後寫入 DB 不再變更）---
GAME_LEDGER_ENABLED = os.getenv("GAME_LEDGER_ENABLED", "true").lower() == "true"
GAME_LEDGER_START_DATE = os.getenv("GAME_LEDGER_START_DATE", "")  # 空值=首次同步當天，見 sync_accumulation


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


def resolve_jbot_token() -> str:
    """從 .env 或 Streamlit Secrets 讀取 JBot API 密鑰。"""
    token = os.getenv("JBOT_TOKEN", "").strip()
    if token:
        return token
    try:
        import streamlit as st

        return str(st.secrets.get("JBOT_TOKEN", "")).strip()
    except Exception:
        return ""


def jbot_configured() -> bool:
    return bool(resolve_jbot_token())


API_SPORTS_KEY = resolve_api_sports_key()

# --- 畢達哥拉斯指數 ---
PYTH_EXPONENT_NBA = float(os.getenv("PYTH_EXPONENT_NBA", "14.0"))
PYTH_EXPONENT_MLB = float(os.getenv("PYTH_EXPONENT_MLB", "1.83"))

# MLB 動態指數（可選）：1.5 * log10((RS+RA)/G) + 0.45
USE_DYNAMIC_MLB_EXPONENT = os.getenv("USE_DYNAMIC_MLB_EXPONENT", "false").lower() == "true"

# --- 貝氏修正權重 ---
BAYES_HOME_ADVANTAGE = float(os.getenv("BAYES_HOME_ADVANTAGE", "0.03"))  # 主場 +3%
BAYES_RECENT_GAMES = int(os.getenv("BAYES_RECENT_GAMES", "5"))
BAYES_H2H_RECENT_GAMES = int(os.getenv("BAYES_H2H_RECENT_GAMES", "5"))
BAYES_RECENT_WEIGHT = float(os.getenv("BAYES_RECENT_WEIGHT", "0.25"))  # 近況權重 0~1
PLAYOFF_USE_H2H_RECENT = os.getenv("PLAYOFF_USE_H2H_RECENT", "true").lower() == "true"
PLAYOFF_H2H_BAYES_RECENT_WEIGHT = float(os.getenv("PLAYOFF_H2H_BAYES_RECENT_WEIGHT", "0.45"))
PLAYOFF_H2H_ENSEMBLE_BOOST = os.getenv("PLAYOFF_H2H_ENSEMBLE_BOOST", "true").lower() == "true"
PLAYOFF_WEIGHT_LOG5_SCALE = float(os.getenv("PLAYOFF_WEIGHT_LOG5_SCALE", "0.55"))
PLAYOFF_WEIGHT_BAYES_SCALE = float(os.getenv("PLAYOFF_WEIGHT_BAYES_SCALE", "1.35"))
PLAYOFF_WEIGHT_BETA_SCALE = float(os.getenv("PLAYOFF_WEIGHT_BETA_SCALE", "1.50"))
PLAYOFF_WEIGHT_MARKOV_SCALE = float(os.getenv("PLAYOFF_WEIGHT_MARKOV_SCALE", "1.10"))
PLAYOFF_CONTEXT_H2H_EXTRA = float(os.getenv("PLAYOFF_CONTEXT_H2H_EXTRA", "0.18"))
BAYES_INJURY_PENALTY = float(os.getenv("BAYES_INJURY_PENALTY", "0.05"))  # 核心缺陣 -5%

# --- 台灣運彩抽水 ---
TAIWAN_VIG_RETURN_RATE = float(os.getenv("TAIWAN_VIG_RETURN_RATE", "0.76"))  # 返還率 76%
# 平手盤 1.75/1.75 時，盈虧平衡勝率 ≈ 1/1.75 ≈ 57.14%
BREAKEVEN_WIN_RATE_AT_175 = 1.0 / 1.75
# 台灣運彩不讓分固定賠率（玩運彩/JBot 歷史盤口使用）
TW_MONEYLINE_ODDS = float(os.getenv("TW_MONEYLINE_ODDS", "1.75"))
# 玩運彩 td-bank-bet03 有開不讓分時，補固定賠率 moneyline（bookmaker=playsport）
PLAYSPORT_MONEYLINE_ENABLED = os.getenv("PLAYSPORT_MONEYLINE_ENABLED", "true").lower() == "true"
# 舊版全域補值（無玩運彩/JBot 驗證）— 預設關閉
ALLOW_TW_MONEYLINE_BACKFILL = os.getenv("ALLOW_TW_MONEYLINE_BACKFILL", "false").lower() == "true"

# --- 凱利與資金控管 ---
INITIAL_BANKROLL = float(os.getenv("INITIAL_BANKROLL", "100000"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))  # 四分之一凱利
MAX_BET_FRACTION = float(os.getenv("MAX_BET_FRACTION", "0.05"))  # 單注上限 5%
MIN_EV_THRESHOLD = float(os.getenv("MIN_EV_THRESHOLD", "0.02"))  # EV > 2% 才進場

# --- 回測區間 ---
BACKTEST_YEARS = int(os.getenv("BACKTEST_YEARS", "3"))
BACKTEST_DAYS = int(os.getenv("BACKTEST_DAYS", str(BACKTEST_YEARS * 365)))
# 增量同步：每日重查最近 N 天（補晚到比分）；其餘已寫入 DB 的日期不再重抓
BACKTEST_INCREMENTAL_LOOKBACK_DAYS = int(os.getenv("BACKTEST_INCREMENTAL_LOOKBACK_DAYS", "10"))
# 完整歷史同步時，僅對近 N 天抓 Blob 即時盤（歷史盤口靠 JBot / 玩運彩）
HISTORICAL_BLOB_ODDS_DAYS = int(os.getenv("HISTORICAL_BLOB_ODDS_DAYS", "14"))

# --- V2 Bottom-Up ---
USE_ROSTER_RATING = os.getenv("USE_ROSTER_RATING", "true").lower() == "true"
ROSTER_RATING_BLEND = float(os.getenv("ROSTER_RATING_BLEND", "0.35"))

# --- 集成勝率模型（Log5 + Bayesian + Beta + Markov）---
USE_MARKOV_FORM = os.getenv("USE_MARKOV_FORM", "true").lower() == "true"
USE_CONTEXT_FEATURES = os.getenv("USE_CONTEXT_FEATURES", "true").lower() == "true"
WEIGHT_LOG5 = float(os.getenv("WEIGHT_LOG5", "0.25"))
WEIGHT_BAYESIAN = float(os.getenv("WEIGHT_BAYESIAN", "0.25"))
WEIGHT_BETA = float(os.getenv("WEIGHT_BETA", "0.20"))
WEIGHT_MARKOV = float(os.getenv("WEIGHT_MARKOV", "0.30"))
BETA_PRIOR_STRENGTH = float(os.getenv("BETA_PRIOR_STRENGTH", "10"))
CONTEXT_B2B_PENALTY = float(os.getenv("CONTEXT_B2B_PENALTY", "0.04"))
CONTEXT_REST_BONUS = float(os.getenv("CONTEXT_REST_BONUS", "0.02"))
CONTEXT_SPLIT_WEIGHT = float(os.getenv("CONTEXT_SPLIT_WEIGHT", "0.15"))
CONTEXT_H2H_WEIGHT = float(os.getenv("CONTEXT_H2H_WEIGHT", "0.10"))
USE_MONTE_CARLO = os.getenv("USE_MONTE_CARLO", "true").lower() == "true"
MC_N_SIMS = int(os.getenv("MC_N_SIMS", "8000"))
MC_H2H_LAMBDA_BLEND = float(os.getenv("MC_H2H_LAMBDA_BLEND", "0.25"))
MC_H2H_PLAYOFF_SINGLE_BLEND = float(os.getenv("MC_H2H_PLAYOFF_SINGLE_BLEND", "0.38"))
MC_H2H_REGULAR_MIN_GAMES = int(os.getenv("MC_H2H_REGULAR_MIN_GAMES", "2"))
MC_H2H_PLAYOFF_MIN_GAMES = int(os.getenv("MC_H2H_PLAYOFF_MIN_GAMES", "1"))
# --- 大小分 / 勝率校準（回測顯示 Poisson 大小分過度自信）---
TOTAL_EDGE_SIGMA: dict[str, float] = {
    "nba": float(os.getenv("TOTAL_EDGE_SIGMA_NBA", "15.0")),
    "mlb": float(os.getenv("TOTAL_EDGE_SIGMA_MLB", "4.8")),
}
TOTAL_LINE_BLEND: dict[str, float] = {
    "nba": float(os.getenv("TOTAL_LINE_BLEND_NBA", "0.55")),
    "mlb": float(os.getenv("TOTAL_LINE_BLEND_MLB", "0.65")),
}
TOTAL_PROB_SHRINK: dict[str, float] = {
    "nba": float(os.getenv("TOTAL_PROB_SHRINK_NBA", "0.50")),
    "mlb": float(os.getenv("TOTAL_PROB_SHRINK_MLB", "0.38")),
}
TOTAL_MARKET_BLEND = float(os.getenv("TOTAL_MARKET_BLEND", "0.40"))
ML_PROB_SHRINK: dict[str, float] = {
    "nba": float(os.getenv("ML_PROB_SHRINK_NBA", "0.82")),
    "mlb": float(os.getenv("ML_PROB_SHRINK_MLB", "0.35")),
}
# 資金回測：MLB 勝率模型與實際相關性低，暫不納入 moneyline
BANKROLL_MARKETS: dict[str, tuple[str, ...]] = {
    "nba": ("moneyline", "total", "spread"),
    "mlb": ("total",),
}
BOXSCORE_REGULAR_DAYS_BACK = int(os.getenv("BOXSCORE_REGULAR_DAYS_BACK", "365"))
LINEUP_SCORING_BLEND = float(os.getenv("LINEUP_SCORING_BLEND", "0.22"))
MARKOV_B2B_EDGE = float(os.getenv("MARKOV_B2B_EDGE", "0.03"))
MARKOV_REST_EDGE_PER_DAY = float(os.getenv("MARKOV_REST_EDGE_PER_DAY", "0.005"))

# 回測門檻：模型健康度判定
MIN_BACKTEST_SAMPLES = int(os.getenv("MIN_BACKTEST_SAMPLES", "30"))
MIN_ROI_FOR_PASS = float(os.getenv("MIN_ROI_FOR_PASS", "0.0"))
INJURY_EXCLUDE_STATUSES = ("Out", "Doubtful")
INJURY_DISCOUNT = {"Questionable": 0.5, "Probable": 0.85}

# --- GitHub 資料庫持久化 ---
GITHUB_DB_SYNC_ENABLED = os.getenv("GITHUB_DB_SYNC_ENABLED", "true").lower() == "true"
GITHUB_AUTO_PUSH = os.getenv("GITHUB_AUTO_PUSH", "true").lower() == "true"
WATCH_PUSH_GITHUB = os.getenv("WATCH_PUSH_GITHUB", "true").lower() == "true"
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
JBOT_TOKEN = resolve_jbot_token()
# 單次 sync 最多抓取天數（試用密鑰每日 20 次，建議 14 以內）
JBOT_MAX_DAYS_PER_RUN = int(os.getenv("JBOT_MAX_DAYS_PER_RUN", "14"))
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
