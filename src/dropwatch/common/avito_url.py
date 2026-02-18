from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse


_PRICE_MIN_KEYS = ("pmin", "price_min", "priceMin", "minPrice", "price_from")
_PRICE_MAX_KEYS = ("pmax", "price_max", "priceMax", "maxPrice", "price_to")
_RADIUS_KEYS = ("radius", "searchRadius", "r")
_QUERY_KEYS = ("q", "query", "text")


def is_avito_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return "avito" in (parsed.netloc or "").lower()


def extract_task_name(url: str) -> str | None:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    query = _first_param(params, _QUERY_KEYS)
    if query:
        return query[:200]
    slug = _extract_slug(parsed.path)
    return slug[:200] if slug else None


def parse_search_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    keywords = _first_param(params, _QUERY_KEYS)
    if not keywords:
        keywords = _extract_slug(parsed.path)
    result: dict[str, Any] = {
        "search_url": url,
        "keywords": keywords,
        "price_min": _parse_int(_first_param(params, _PRICE_MIN_KEYS)),
        "price_max": _parse_int(_first_param(params, _PRICE_MAX_KEYS)),
        "radius_km": _parse_int(_first_param(params, _RADIUS_KEYS)),
    }
    coords = _first_param(params, ("geoCoords", "geo", "coords"))
    if coords and _looks_coords(coords):
        result["city"] = coords
    else:
        city, category = _extract_path_parts(parsed.path)
        if city:
            result["city"] = city
        if category:
            result["category"] = category
    return result


def _extract_path_parts(path: str) -> tuple[str | None, str | None]:
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return None, None
    city = segments[0]
    category = "/".join(segments[1:]) if len(segments) > 1 else None
    return city, category


def _extract_slug(path: str) -> str | None:
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return None
    slug = segments[-1]
    slug = re.sub(r"-ASg.*$", "", slug)
    slug = slug.replace("_", " ")
    return slug or None


def _first_param(params: dict[str, list[str]], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        values = params.get(key)
        if not values:
            continue
        value = values[0].strip()
        if value:
            return value
    return None


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        cleaned = re.sub(r"[^0-9]", "", value)
        return int(cleaned) if cleaned else None
    except ValueError:
        return None


def _looks_coords(value: str) -> bool:
    return bool(re.match(r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$", value))
