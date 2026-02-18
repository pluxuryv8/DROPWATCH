from __future__ import annotations

import hashlib


def listing_hash(title: str | None, price: int | None, location: str | None, url: str | None) -> str:
    raw = "|".join(
        [
            title or "",
            str(price) if price is not None else "",
            location or "",
            url or "",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
