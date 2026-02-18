from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Listing:
    listing_id: str
    url: str
    title: str
    price: int | None
    location: str | None
    published_at: datetime | None
    image_url: str | None
    source: str
    category: str | None = None
    condition: str | None = None
    delivery: str | None = None
    seller_type: str | None = None
    seller_id: str | None = None
    is_reserved: bool | None = None
    is_promotion: bool | None = None
    total_views: int | None = None
    today_views: int | None = None
    description: str | None = None
    raw: dict[str, Any] | None = None
