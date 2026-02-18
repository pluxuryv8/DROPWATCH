from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from dropwatch.common.config import settings
from dropwatch.common.types import Listing
from dropwatch.monitor.fetchers.base import BaseFetcher


logger = logging.getLogger("avito_search")

HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
}

BLOCK_MARKERS = (
    "\u0414\u043e\u0441\u0442\u0443\u043f \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d",
    "problem with ip",
    "captcha",
)


class RateLimitError(RuntimeError):
    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class BlockedError(RuntimeError):
    def __init__(self, reason: str = "blocked") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class ProxyConfig:
    proxy_url: str | None
    server: str | None
    username: str | None
    password: str | None


class AvitoSearchFetcher(BaseFetcher):
    def __init__(self) -> None:
        self.headers = dict(HEADERS)
        self.proxy_config = _parse_proxy(settings.avito_proxy)
        self.proxy_change_url = settings.avito_proxy_change_url
        self.use_webdriver = settings.avito_use_webdriver
        self.max_pages = max(1, settings.avito_max_pages)
        self.pause_sec = max(0.0, settings.avito_pause_sec)
        self.max_retries = max(1, settings.avito_max_retries)
        self.timeout_sec = settings.avito_request_timeout_sec
        self.impersonate = settings.avito_impersonate
        self.parse_views = settings.avito_parse_views
        self.views_delay_sec = max(0.0, settings.avito_views_delay_sec)
        self.cookies_path = settings.avito_cookies_path
        self.session = curl_requests.Session()
        self.cookies = _load_cookies(self.cookies_path)
        self._apply_cookies()
        self.good_request_count = 0
        self.bad_request_count = 0

    async def fetch(self, task=None) -> list[Listing]:
        if not task or not task.search_url:
            logger.info("AvitoSearchFetcher: no task url")
            return []
        return await asyncio.to_thread(self._fetch_sync, task.search_url)

    def _fetch_sync(self, url: str) -> list[Listing]:
        listings: dict[str, Listing] = {}
        current_url = url

        for page in range(self.max_pages):
            html_code = self._fetch_data(current_url)
            if not html_code:
                break

            data_from_page = _extract_state_data(html_code)
            items = _extract_items(data_from_page)
            parsed = [_to_listing(item, current_url) for item in items]
            for listing in parsed:
                listings.setdefault(listing.listing_id, listing)

            current_url = _next_page_url(current_url)
            if not current_url:
                break
            if page < self.max_pages - 1 and self.pause_sec:
                time.sleep(self.pause_sec)

        if self.parse_views and listings:
            self._fill_views(listings.values())

        logger.info(
            "AvitoSearchFetcher: good_requests=%s bad_requests=%s",
            self.good_request_count,
            self.bad_request_count,
        )
        return list(listings.values())

    def _fetch_data(self, url: str) -> str | None:
        proxies = None
        if self.proxy_config.proxy_url:
            proxies = {"https": self.proxy_config.proxy_url}

        last_status: int | None = None
        last_retry_after: int | None = None
        last_blocked = False

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(
                    url=url,
                    headers=self.headers,
                    proxies=proxies,
                    cookies=self.cookies or None,
                    impersonate=self.impersonate,
                    timeout=self.timeout_sec,
                    verify=False,
                )
            except curl_requests.RequestsError as exc:
                logger.warning("Avito request failed attempt=%s error=%s", attempt, exc)
                self._backoff(attempt)
                continue

            status = response.status_code
            text = response.text or ""
            if status >= 500:
                logger.warning("Avito server error status=%s attempt=%s", status, attempt)
                self._backoff(attempt)
                continue
            blocked_page = _looks_blocked(text)
            if status in (302, 403, 429) or blocked_page:
                self.bad_request_count += 1
                logger.warning("Avito blocked status=%s attempt=%s", status, attempt)
                last_status = status
                last_blocked = blocked_page
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        last_retry_after = int(retry_after)
                    except ValueError:
                        last_retry_after = None
                self._reset_session()
                if attempt >= 3:
                    self._refresh_cookies()
                self._change_ip()
                self._backoff(attempt)
                continue

            self.good_request_count += 1
            self._save_cookies()
            return text

        if last_status == 429:
            raise RateLimitError(retry_after=last_retry_after)
        if last_status in (302, 403) or last_blocked:
            raise BlockedError("blocked")
        logger.warning("Avito request failed after retries url=%s", url)
        return None

    def _reset_session(self) -> None:
        self.session = curl_requests.Session()
        self._apply_cookies()

    def _apply_cookies(self) -> None:
        if self.cookies:
            self.session.cookies.update(self.cookies)

    def _save_cookies(self) -> None:
        try:
            self.cookies = self.session.cookies.get_dict()
            _save_cookies(self.cookies_path, self.cookies)
        except Exception:
            logger.debug("Avito cookies save failed", exc_info=True)

    def _refresh_cookies(self) -> None:
        if not self.use_webdriver:
            return
        try:
            cookies, user_agent = asyncio.run(_get_cookies_via_playwright(self.proxy_config))
        except Exception:
            logger.exception("Avito cookie refresh failed")
            return
        if cookies:
            self.cookies = cookies
            if user_agent:
                self.headers["user-agent"] = user_agent
            self._apply_cookies()
            _save_cookies(self.cookies_path, self.cookies)

    def _change_ip(self) -> None:
        if not self.proxy_change_url:
            return
        try:
            response = httpx.get(self.proxy_change_url, timeout=20)
            if response.status_code == 200:
                logger.info("Avito proxy IP changed")
        except Exception:
            logger.warning("Avito proxy IP change failed", exc_info=True)

    @staticmethod
    def _backoff(attempt: int) -> None:
        delay = min(10, attempt) + random.uniform(0.1, 0.9)
        time.sleep(delay)

    def _fill_views(self, listings: Iterable[Listing]) -> None:
        for listing in listings:
            if not listing.url:
                continue
            try:
                html_code = self._fetch_data(listing.url)
            except (RateLimitError, BlockedError):
                return
            if not html_code:
                continue
            total_views, today_views = _extract_views(html_code)
            listing.total_views = total_views
            listing.today_views = today_views
            if self.views_delay_sec:
                time.sleep(self.views_delay_sec)


def _extract_state_data(html_code: str) -> dict:
    soup = BeautifulSoup(html_code, "html.parser")
    for script in soup.select("script[type='mime/invalid']"):
        payload = html.unescape(script.text)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            if "state" in parsed:
                return parsed["state"]
            if "data" in parsed:
                return parsed["data"]
            return parsed
    return {}


def _extract_items(data_from_page: dict) -> list[dict]:
    catalog = None
    if isinstance(data_from_page, dict):
        catalog = data_from_page.get("data", {}).get("catalog")
        if not catalog:
            catalog = data_from_page.get("catalog")
        if not catalog:
            catalog = data_from_page.get("state", {}).get("data", {}).get("catalog")
    if not isinstance(catalog, dict):
        return []
    items = catalog.get("items") or []
    return [item for item in items if isinstance(item, dict)]


def _to_listing(item: dict, source_url: str) -> Listing:
    listing_id = str(item.get("id") or item.get("itemId") or _fallback_id(item))
    url_path = item.get("urlPath") or item.get("url") or ""
    url = _absolute_url(url_path)
    title = item.get("title") or "Объявление"
    description = item.get("description")
    price = _to_int(_deep_get(item, ["priceDetailed", "value"]) or item.get("price"))
    location = (
        _deep_get(item, ["geo", "formattedAddress"])
        or _deep_get(item, ["addressDetailed", "locationName"])
        or _deep_get(item, ["location", "name"])
    )
    image_url = _extract_image(item)
    published_at = _to_datetime(item.get("sortTimeStamp"))
    category = _deep_get(item, ["category", "name"])
    seller_id = _extract_seller_id(item)
    is_reserved = bool(item.get("isReserved")) if item.get("isReserved") is not None else None
    is_promotion = _is_promotion(item)

    return Listing(
        listing_id=listing_id,
        url=url or source_url,
        title=title,
        price=price,
        location=location,
        published_at=published_at,
        image_url=image_url,
        source="avito_search",
        category=category,
        seller_id=seller_id,
        is_reserved=is_reserved,
        is_promotion=is_promotion,
        description=description,
        raw=item,
    )


def _fallback_id(item: dict) -> str:
    for key in ("urlPath", "url"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value.strip("/")
    return str(hash(json.dumps(item, ensure_ascii=True, sort_keys=True)))


def _extract_image(item: dict) -> str | None:
    gallery = item.get("gallery") or {}
    for key in ("imageLargeUrl", "imageUrl", "imageLargeVipUrl", "imageVipUrl"):
        value = gallery.get(key)
        if isinstance(value, str) and value:
            return value
    images = item.get("images") or []
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            root = image.get("root")
            if isinstance(root, dict):
                for value in root.values():
                    if isinstance(value, str) and value:
                        return value
    return None


def _extract_seller_id(item: dict) -> str | None:
    for key in ("sellerId", "seller_id", "userId", "user_id"):
        value = item.get(key)
        if value:
            return str(value)
    return _extract_seller_slug(item)


def _extract_seller_slug(item: dict) -> str | None:
    try:
        blob = json.dumps(item, ensure_ascii=True)
    except Exception:
        blob = str(item)
    match = re.search(r"/brands/([^/?#]+)", blob)
    if match:
        return match.group(1)
    return None


def _is_promotion(item: dict) -> bool | None:
    iva = item.get("iva") or {}
    steps = iva.get("DateInfoStep") if isinstance(iva, dict) else None
    if not steps:
        return False
    for step in steps:
        payload = step.get("payload") if isinstance(step, dict) else None
        if not payload:
            continue
        for info in payload.get("vas") or []:
            if isinstance(info, dict) and info.get("title") == "\u041f\u0440\u043e\u0434\u0432\u0438\u043d\u0443\u0442\u043e":
                return True
    return False


def _absolute_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url:
        return ""
    return f"https://www.avito.ru{url}" if url.startswith("/") else f"https://www.avito.ru/{url}"


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(timestamp_ms: Any) -> datetime | None:
    if not timestamp_ms:
        return None
    try:
        return datetime.utcfromtimestamp(int(timestamp_ms) / 1000)
    except (TypeError, ValueError):
        return None


def _deep_get(obj: dict, keys: list[str]) -> Any:
    current: Any = obj
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _looks_blocked(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in BLOCK_MARKERS)


def _extract_views(html_code: str) -> tuple[int | None, int | None]:
    soup = BeautifulSoup(html_code, "html.parser")

    def _digits(node) -> int | None:
        if not node:
            return None
        value = "".join(ch for ch in node.get_text() if ch.isdigit())
        return int(value) if value else None

    total = _digits(soup.select_one('[data-marker="item-view/total-views"]'))
    today = _digits(soup.select_one('[data-marker="item-view/today-views"]'))
    return total, today


def _next_page_url(url: str) -> str | None:
    try:
        parts = urlparse(url)
        query_params = parse_qs(parts.query)
        current_page = int(query_params.get("p", [1])[0])
        query_params["p"] = [str(current_page + 1)]
        new_query = urlencode(query_params, doseq=True)
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
    except Exception:
        logger.debug("Failed to build next page url", exc_info=True)
        return None


def _load_cookies(path: str) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except Exception:
        logger.debug("Avito cookies load failed", exc_info=True)
    return {}


def _save_cookies(path: str, cookies: dict[str, str]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f)
    except Exception:
        logger.debug("Avito cookies write failed", exc_info=True)


def _parse_proxy(proxy_string: str | None) -> ProxyConfig:
    if not proxy_string:
        return ProxyConfig(proxy_url=None, server=None, username=None, password=None)
    normalized = proxy_string.strip()
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    parsed = urlparse(normalized)
    if parsed.username and parsed.password and parsed.hostname and parsed.port:
        server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        return ProxyConfig(
            proxy_url=normalized,
            server=server,
            username=parsed.username,
            password=parsed.password,
        )
    if "@" in proxy_string:
        host_port, creds = proxy_string.split("@", 1)
        if ":" in creds:
            user, pwd = creds.split(":", 1)
            proxy_url = f"http://{user}:{pwd}@{host_port}"
            server = f"http://{host_port}"
            return ProxyConfig(proxy_url=proxy_url, server=server, username=user, password=pwd)
    parts = proxy_string.split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        proxy_url = f"http://{user}:{pwd}@{host}:{port}"
        server = f"http://{host}:{port}"
        return ProxyConfig(proxy_url=proxy_url, server=server, username=user, password=pwd)
    return ProxyConfig(proxy_url=normalized, server=None, username=None, password=None)


async def _get_cookies_via_playwright(proxy: ProxyConfig) -> tuple[dict[str, str], str | None]:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning("Playwright not installed: %s", exc)
        return {}, None
    try:
        from playwright_stealth import Stealth
    except Exception:  # pragma: no cover - optional dependency
        Stealth = None

    user_agent = HEADERS["user-agent"]
    target = f"https://www.avito.ru/{random.randint(111111111, 999999999)}"

    if Stealth:
        stealth = Stealth()
        ctx = stealth.use_async(async_playwright())
        playwright = await ctx.__aenter__()
    else:
        ctx = None
        playwright = await async_playwright().start()

    browser = None
    try:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--start-maximized",
                "--window-size=1920,1080",
            ],
        )
        context_args = {
            "user_agent": user_agent,
            "viewport": {"width": 1920, "height": 1080},
            "screen": {"width": 1920, "height": 1080},
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
        }
        if proxy.server:
            context_args["proxy"] = {
                "server": proxy.server,
                "username": proxy.username,
                "password": proxy.password,
            }
        context = await browser.new_context(**context_args)
        page = await context.new_page()
        await page.goto(target, timeout=60_000, wait_until="domcontentloaded")

        cookies: dict[str, str] = {}
        for _ in range(10):
            raw = await context.cookies()
            cookies = {cookie["name"]: cookie["value"] for cookie in raw}
            if cookies.get("ft"):
                logger.info("Avito cookies refreshed")
                break
            await asyncio.sleep(5)
        return cookies, user_agent
    finally:
        if browser:
            await browser.close()
        if ctx:
            await ctx.__aexit__(None, None, None)
        else:
            await playwright.stop()
