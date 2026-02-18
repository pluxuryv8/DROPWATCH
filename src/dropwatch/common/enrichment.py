from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

import aiohttp

from dropwatch.common.config import settings
from dropwatch.common.types import Listing


logger = logging.getLogger("enrichment")
_llm_disabled_reason: str | None = None


@dataclass(slots=True)
class Enrichment:
    summary: str | None
    score: int | None
    notes: str | None
    error: str | None = None


async def enrich_listing(listing: Listing) -> Enrichment:
    base = _heuristic_enrich(listing)
    if not settings.llm_enabled:
        return base
    if not settings.llm_api_key:
        return Enrichment(summary=base.summary, score=base.score, notes=base.notes, error="LLM не настроена")
    if _llm_disabled_reason:
        return Enrichment(summary=base.summary, score=base.score, notes=base.notes, error=_llm_disabled_reason)
    if settings.llm_provider.lower() != "openai":
        return Enrichment(summary=base.summary, score=base.score, notes=base.notes, error="LLM провайдер не поддержан")

    try:
        llm = await _call_openai(listing)
        if llm:
            return llm
    except LLMUnavailable as exc:
        _set_llm_disabled(str(exc))
        return Enrichment(summary=base.summary, score=base.score, notes=base.notes, error=str(exc))
    except Exception:
        logger.exception("LLM request failed")
        return Enrichment(summary=base.summary, score=base.score, notes=base.notes, error="LLM временно недоступна")
    return base


def _heuristic_enrich(listing: Listing) -> Enrichment:
    title = (listing.title or "").strip()
    description = (listing.description or "").strip()
    text = f"{title} {description}".lower()

    score = 5
    notes: list[str] = []

    if any(word in text for word in ["нов", "new", "nwt", "бирк", "запечатан"]):
        score += 2
        notes.append("похоже новое")
    if any(word in text for word in ["как новый", "идеал", "mint", "отличн"]):
        score += 2
        notes.append("состояние близко к идеалу")
    if any(word in text for word in ["б/у", "бу", "used", "понош", "следы"]):
        score -= 1
        notes.append("есть следы использования")
    if any(word in text for word in ["ремонт", "не работает", "дефект", "косяк", "трещина"]):
        score -= 3
        notes.append("возможны проблемы")

    score = max(1, min(10, score))
    summary = (title or description)[:120] if (title or description) else None
    notes_text = "; ".join(notes) if notes else None

    return Enrichment(summary=summary, score=score, notes=notes_text)


class LLMUnavailable(RuntimeError):
    pass


async def _call_openai(listing: Listing) -> Enrichment | None:
    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты помощник по описанию объявлений. "
                    "Ответь строго JSON-объектом: "
                    "{\"summary\": str, \"score\": int, \"notes\": str}."
                ),
            },
            {
                "role": "user",
                "content": _llm_prompt_text(listing),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 180,
    }

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=settings.llm_timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status in (401, 402, 403, 429):
                raise LLMUnavailable("LLM недоступна: закончились токены")
            if resp.status >= 400:
                raise LLMUnavailable("LLM недоступна")
            data = await resp.json()

    content = _extract_llm_content(data)
    if not content:
        return None

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = _try_extract_json(content)

    if not isinstance(parsed, dict):
        return None

    summary = _clean_text(parsed.get("summary"))
    notes = _clean_text(parsed.get("notes"))
    score = _to_score(parsed.get("score"))

    return Enrichment(summary=summary, score=score, notes=notes)


def _llm_prompt_text(listing: Listing) -> str:
    parts = [
        f"Название: {listing.title or '—'}",
        f"Описание: {listing.description or '—'}",
        f"Цена: {listing.price or '—'}",
        f"Локация: {listing.location or '—'}",
    ]
    return "\n".join(parts)


def _extract_llm_content(data: dict) -> str | None:
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


def _try_extract_json(text: str) -> dict | None:
    match = re.search(r"{.*}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _to_score(value) -> int | None:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, min(10, score))


def _clean_text(value: Any) -> str | None:
    if not value:
        return None
    return str(value).strip()


def _set_llm_disabled(reason: str) -> None:
    global _llm_disabled_reason
    _llm_disabled_reason = reason
