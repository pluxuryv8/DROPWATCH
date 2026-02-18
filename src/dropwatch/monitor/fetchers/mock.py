from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dropwatch.common.types import Listing
from dropwatch.monitor.fetchers.base import GlobalFetcher


class MockFetcher(GlobalFetcher):
    def __init__(self, data_path: str) -> None:
        self.data_path = Path(data_path)

    async def fetch_all(self) -> list[Listing]:
        if not self.data_path.exists():
            return []
        raw = json.loads(self.data_path.read_text(encoding="utf-8"))
        listings: list[Listing] = []
        for item in raw:
            listings.append(
                Listing(
                    listing_id=str(item.get("id") or item.get("listing_id") or item.get("url")),
                    url=str(item.get("url") or ""),
                    title=str(item.get("title") or "Без названия"),
                    price=_to_int(item.get("price")),
                    location=item.get("location"),
                    published_at=None,
                    image_url=item.get("image_url"),
                    source="mock",
                    description=item.get("description"),
                    raw=item,
                )
            )
        return listings


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(str(value).replace(" ", "").replace("₽", ""))
    except ValueError:
        return None
