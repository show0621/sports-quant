"""僅使用 API-Sports 資料來源（API-only）。"""
from __future__ import annotations

from sportsbet import config
from sportsbet.data.api_sports import ApiSportsClient
from sportsbet.data.database import SportsDatabase
from sportsbet.data.ingestion import ApiSportsIngestionAdapter, DataIngestionProvider


def get_data_provider(db: SportsDatabase | None = None) -> DataIngestionProvider:
    """僅在 API_SPORTS_KEY 可用時回傳 API provider。"""
    db = db or SportsDatabase()
    client = ApiSportsClient()
    if not client.is_configured:
        raise RuntimeError("API_SPORTS_KEY 未設定，系統已停用 MOCK，請先設定真實 API 金鑰。")
    return ApiSportsIngestionAdapter(db=db, client=client)


def api_key_configured() -> bool:
    return bool(config.resolve_api_sports_key())
