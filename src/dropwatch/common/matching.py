from __future__ import annotations

from datetime import datetime
import re

from dropwatch.common.config import settings


_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)
_COORD_RE = re.compile(r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$")


def _normalize(text: str) -> str:
    return text.lower().strip()


def _extract_words(text: str) -> list[str]:
    return _WORD_RE.findall(_normalize(text))


def _match_keywords(text: str, keywords: str | None) -> bool:
    if not keywords:
        return True
    tokens = _extract_words(keywords)
    if not tokens:
        return True
    haystack = _normalize(text)
    return all(token in haystack for token in tokens)


def _match_minus_words(text: str, minus_words: str | None) -> bool:
    if not minus_words:
        return True
    tokens = _extract_words(minus_words)
    if not tokens:
        return True
    haystack = _normalize(text)
    return not any(token in haystack for token in tokens)


def matches_task(task, listing) -> bool:
    text = f"{listing.title or ''} {listing.description or ''}"
    if settings.avito_keywords_whitelist and not _match_global_whitelist(text, settings.avito_keywords_whitelist):
        return False
    if settings.avito_keywords_blacklist and _match_global_blacklist(text, settings.avito_keywords_blacklist):
        return False
    if not _match_keywords(text, task.keywords):
        return False
    if not _match_minus_words(text, task.minus_keywords):
        return False

    if listing.price is not None:
        if task.price_min is not None and listing.price < task.price_min:
            return False
        if task.price_max is not None and listing.price > task.price_max:
            return False

    if task.city:
        city_value = task.city.strip()
        if not (city_value.lower().startswith("gps:") or _COORD_RE.match(city_value)):
            if listing.location:
                if city_value.lower() not in listing.location.lower():
                    return False
            # if location missing, мягко пропускаем
    if settings.avito_geo_filter and listing.location:
        if settings.avito_geo_filter.lower() not in listing.location.lower():
            return False

    if task.category and getattr(listing, "category", None):
        if task.category.lower() not in listing.category.lower():
            return False

    if settings.avito_ignore_reserved and getattr(listing, "is_reserved", False):
        return False
    if settings.avito_ignore_promotion and getattr(listing, "is_promotion", False):
        return False

    if settings.avito_seller_blacklist and getattr(listing, "seller_id", None):
        blacklist = _split_csv(settings.avito_seller_blacklist)
        if listing.seller_id in blacklist:
            return False

    if settings.avito_max_age_sec > 0 and getattr(listing, "published_at", None):
        age_sec = (datetime.utcnow() - listing.published_at).total_seconds()
        if age_sec > settings.avito_max_age_sec:
            return False

    # Доп. поля (если источник их поддерживает)
    if getattr(listing, "condition", None) and task.condition and task.condition != "any":
        if listing.condition != task.condition:
            return False

    if getattr(listing, "delivery", None) and task.delivery and task.delivery != "any":
        if listing.delivery != task.delivery:
            return False

    if getattr(listing, "seller_type", None) and task.seller_type and task.seller_type != "any":
        if listing.seller_type != task.seller_type:
            return False

    return True


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _match_global_whitelist(text: str, whitelist: str) -> bool:
    phrases = _split_csv(whitelist)
    if not phrases:
        return True
    haystack = _normalize(text)
    return any(phrase.lower() in haystack for phrase in phrases)


def _match_global_blacklist(text: str, blacklist: str) -> bool:
    phrases = _split_csv(blacklist)
    if not phrases:
        return False
    haystack = _normalize(text)
    return any(phrase.lower() in haystack for phrase in phrases)
