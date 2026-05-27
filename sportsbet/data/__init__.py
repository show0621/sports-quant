"""資料抓取與持久化。

避免在 package import 階段就載入所有子模組，降低循環匯入/死結風險。
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

_SYMBOL_MAP = {
    "ApiSportsClient": "sportsbet.data.api_sports",
    "SportsDatabase": "sportsbet.data.database",
    "DataIngestionProvider": "sportsbet.data.ingestion",
    "ApiSportsIngestionAdapter": "sportsbet.data.ingestion",
    "get_data_provider": "sportsbet.data.provider",
    "api_key_configured": "sportsbet.data.provider",
    "JBotClient": "sportsbet.data.jbot",
    "SportLotteryClient": "sportsbet.data.sportslottery",
    "STANDARD_ODDS_COLUMNS": "sportsbet.data.sportslottery",
    "WandaScraper": "sportsbet.data.wanda_scraper",
    "PlaySportScraper": "sportsbet.data.playsport_scraper",
    "build_backtest_dataset": "sportsbet.data.timeline",
    "merge_timeline": "sportsbet.data.timeline",
    "load_games": "sportsbet.data.storage",
    "save_games": "sportsbet.data.storage",
    "save_odds": "sportsbet.data.storage",
    "load_odds_history": "sportsbet.data.storage",
    "save_timeline": "sportsbet.data.storage",
    "load_timeline": "sportsbet.data.storage",
}

__all__ = list(_SYMBOL_MAP.keys())


def __getattr__(name: str) -> Any:
    module_name = _SYMBOL_MAP.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    return getattr(module, name)
