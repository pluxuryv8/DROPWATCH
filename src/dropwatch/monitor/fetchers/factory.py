from __future__ import annotations

from dropwatch.common.config import settings
from dropwatch.monitor.fetchers.avito_search import AvitoSearchFetcher
from dropwatch.monitor.fetchers.base import BaseFetcher
from dropwatch.monitor.fetchers.mock import MockFetcher


def create_fetcher() -> BaseFetcher:
    fetcher_name = settings.fetcher.lower()
    if fetcher_name == "mock":
        return MockFetcher(settings.mock_data_path)
    if fetcher_name == "avito_search":
        return AvitoSearchFetcher()
    raise RuntimeError(f"Unknown fetcher: {fetcher_name}")
