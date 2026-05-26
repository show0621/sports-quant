"""依設定自動選擇 MOCK 或 API-Sports 資料來源。"""
from __future__ import annotations

from sportsbet import config
from sportsbet.data.api_sports import ApiSportsClient
from sportsbet.data.database import SportsDatabase
from sportsbet.data.ingestion import ApiSportsIngestionAdapter, DataIngestionProvider, MockDataProvider


def get_data_provider(db: SportsDatabase | None = None) -> DataIngestionProvider:
    """
    有 API_SPORTS_KEY 時使用 ApiSportsIngestionAdapter；
    否則使用 MockDataProvider。
    """
    db = db or SportsDatabase()
    client = ApiSportsClient()
    if client.is_configured:
        return ApiSportsIngestionAdapter(db=db, client=client)
    return MockDataProvider(db)


def api_key_configured() -> bool:
    return bool(config.resolve_api_sports_key())
