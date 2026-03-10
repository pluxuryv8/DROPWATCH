from __future__ import annotations

from datetime import datetime
from typing import Iterable

from dropwatch.common.types import Listing


def format_price(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", " ")


def _format_published_at(published_at: datetime, detected_at: datetime) -> str:
    if published_at.date() == detected_at.date():
        return published_at.strftime("%H:%M")
    return published_at.strftime("%d.%m %H:%M")


def format_listing_message(
    task_name: str,
    listing: Listing,
    detected_at: datetime,
    header: str = "🆕 Новое объявление!",
    extra_lines: list[str] | None = None,
) -> str:
    location = listing.location or "—"
    published_source = listing.published_at or detected_at
    published_at = _format_published_at(published_source, detected_at)
    price_text = f"{format_price(listing.price)} ₽" if listing.price is not None else "—"
    lines = [
        header,
        "",
        f"📡 Радар: {task_name}",
        f"📌 {listing.title}",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    if listing.category:
        lines.append(f"🏷️ {listing.category}")
    lines.extend(
        [
            f"💰 {price_text}",
            f"📍 {location}",
            f"🕒 Опубликовано: {published_at}",
        ]
    )
    if listing.url:
        lines.extend(["", f"🔗 {listing.url}"])
    return "\n".join(lines)


def build_listing_summary(listing: Listing, max_len: int = 140) -> str | None:
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
