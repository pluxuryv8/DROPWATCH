from __future__ import annotations

from datetime import datetime
from typing import Iterable

from dropwatch.common.types import Listing


def format_price(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", " ")


def format_listing_message(
    task_name: str,
    listing: Listing,
    detected_at: datetime,
    header: str = "🆕 Новое объявление!",
    extra_lines: list[str] | None = None,
) -> str:
    location = listing.location or "—"
    published_at = detected_at.strftime("%H:%M")
    price_text = f"{format_price(listing.price)} ₽" if listing.price is not None else "—"
    lines = [
        header,
        "",
        f"📡 Радар: {task_name}",
        f"📌 {listing.title}",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    lines.extend(
        [
            f"💰 {price_text}",
            f"📍 {location}",
            f"🕒 {published_at}",
        ]
    )
    return "\n".join(lines)


def build_listing_summary(listing: Listing, max_len: int = 120) -> str | None:
    text = (listing.description or "").strip()
    if not text:
        return None
    cleaned = " ".join(text.split())
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned


def format_task_filters(filters: dict[str, str | int | None]) -> str:
    parts: list[str] = []
    for key, value in filters.items():
        if value in (None, ""):
            continue
        parts.append(f"{key}: {value}")
    return "; ".join(parts) if parts else "без фильтров"


def chunked(iterable: Iterable, size: int) -> list[list]:
    chunk: list = []
    batches: list[list] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            batches.append(chunk)
            chunk = []
    if chunk:
        batches.append(chunk)
    return batches
