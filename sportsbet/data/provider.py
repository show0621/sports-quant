"""資料來源選擇：混合模式（預設）或純 API-Sports。"""
from __future__ import annotations

from sportsbet import config
from sportsbet.data.api_sports import ApiSportsClient
from sportsbet.data.database import SportsDatabase
from sportsbet.data.hybrid_provider import HybridIngestionProvider, data_source_description
from sportsbet.data.ingestion import ApiSportsIngestionAdapter, DataIngestionProvider, SportLit


def api_key_configured() -> bool:
    return bool(config.resolve_api_sports_key())


def get_data_provider(db: SportsDatabase | None = None) -> DataIngestionProvider:
    db = db or SportsDatabase()
    mode = config.DATA_SOURCE
    if mode == "api_sports":
        client = ApiSportsClient()
        if not client.is_configured:
            raise RuntimeError("DATA_SOURCE=api_sports 但未設定 API_SPORTS_KEY。")
        return ApiSportsIngestionAdapter(db=db, client=client)
    return HybridIngestionProvider(db=db)


def describe_data_source(sport: SportLit = "nba") -> str:
    return data_source_description(sport)
