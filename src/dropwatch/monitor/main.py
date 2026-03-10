import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from dropwatch.bot.keyboards import listing_actions_keyboard
from dropwatch.bot.texts import NEW_DROP_HEADER
from dropwatch.common.config import settings
from dropwatch.common.formatting import build_listing_summary, format_listing_message
from dropwatch.common.hash_utils import listing_hash
from dropwatch.common.logging import setup_logging
from dropwatch.common.matching import matches_task
from dropwatch.common.secrets import decode_secret
from dropwatch.common.single_tenant import ensure_owner_user, single_tenant_enabled
from dropwatch.common.time_utils import is_quiet_hours
from dropwatch.common.types import Listing
from dropwatch.db import crud
from dropwatch.db.database import create_db, get_sessionmaker, init_engine
from dropwatch.db.models import Task
from dropwatch.monitor.fetchers.avito_search import AvitoRuntimeProfile, BlockedError, RateLimitError
from dropwatch.monitor.fetchers.factory import create_fetcher


logger = logging.getLogger("monitor")
MAX_BACKOFF_SEC = 600
TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_MESSAGE_LIMIT = 4096


@dataclass
class RateLimitState:
    backoff_sec: int
    next_allowed_at: datetime
    success_streak: int = 0


def _build_fetch_profile(user_settings) -> AvitoRuntimeProfile:
    cookies_path_suffix = str(getattr(user_settings, "user_id", "default"))
    return AvitoRuntimeProfile(
        proxy=decode_secret(getattr(user_settings, "proxy_b64", None)) or settings.avito_proxy,
        proxy_change_url=decode_secret(getattr(user_settings, "proxy_change_url_b64", None))
        or settings.avito_proxy_change_url,
        cookies_api_key=(
            decode_secret(getattr(user_settings, "cookies_api_key_b64", None))
            or settings.avito_cookies_api_key
        ),
        cookies_path=f"./avito_cookies_user_{cookies_path_suffix}.json",
    )


def _missing_antiban_for_profile(profile: AvitoRuntimeProfile) -> list[str]:
    missing: list[str] = []
    if not (profile.proxy or "").strip():
        missing.append("/set_proxy")
    if not (profile.proxy_change_url or "").strip():
        missing.append("/set_proxy_change_url")
    return missing


def _price_drop_header(old_price: int | None, new_price: int | None) -> str:
    if old_price is None or new_price is None:
        return "Цена снизилась!"
    return f"Цена снизилась! Было {old_price} ₽ -> {new_price} ₽"


def _truncate_telegram_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


async def _send_telegram_request(
    description: str,
    request_factory: Callable[[], Awaitable[Any]],
) -> bool:
    for attempt in range(1, 3):
        try:
            await request_factory()
            return True
        except TelegramRetryAfter as exc:
            retry_after = max(1, int(getattr(exc, "retry_after", 1) or 1))
            wait_sec = min(60, retry_after)
            logger.warning("%s retry after %ss (attempt=%s)", description, wait_sec, attempt)
            await asyncio.sleep(wait_sec)
        except (TelegramNetworkError, TelegramServerError) as exc:
            if attempt >= 2:
                logger.warning("%s failed after retry: %s", description, exc)
                return False
            wait_sec = attempt * 2
            logger.warning("%s temporary Telegram error: %s; retry in %ss", description, exc, wait_sec)
            await asyncio.sleep(wait_sec)
        except TelegramForbiddenError as exc:
            logger.warning("%s forbidden: %s", description, exc)
            return False
        except TelegramBadRequest as exc:
            logger.warning("%s bad request: %s", description, exc)
            return False
        except TelegramAPIError as exc:
            logger.warning("%s Telegram API error: %s", description, exc)
            return False
        except Exception:
            logger.exception("%s unexpected error", description)
            return False
    return False


async def _send_notification(
    bot: Bot,
    user_id: int,
    task: Task,
    listing: Listing,
    header: str,
) -> bool:
    logger.info(
        "Send notification: user_id=%s task_id=%s listing_id=%s title=%s",
        user_id,
        task.id,
        listing.listing_id,
        listing.title,
    )
    extra_lines: list[str] = []
    summary = build_listing_summary(listing)
    if summary:
        extra_lines.append(f"📝 {summary}")
    if listing.total_views is not None or listing.today_views is not None:
        if listing.total_views is not None and listing.today_views is not None:
            extra_lines.append(f"👀 {listing.today_views} сегодня / {listing.total_views} всего")
        elif listing.total_views is not None:
            extra_lines.append(f"👀 {listing.total_views} всего")
        else:
            extra_lines.append(f"👀 {listing.today_views} сегодня")

    message = format_listing_message(
        task.name,
        listing,
        datetime.utcnow(),
        header=header,
        extra_lines=extra_lines or None,
    )
    reply_markup = listing_actions_keyboard(task.id, listing.listing_id, listing.url)
    sent = False

    if listing.image_url:
        sent = await _send_telegram_request(
            f"send_photo user_id={user_id} task_id={task.id} listing_id={listing.listing_id}",
            lambda: bot.send_photo(
                chat_id=user_id,
                photo=listing.image_url,
                caption=_truncate_telegram_text(message, TELEGRAM_CAPTION_LIMIT),
                reply_markup=reply_markup,
            ),
        )
        if not sent:
            logger.info(
                "Send photo failed, fallback to text: user_id=%s task_id=%s listing_id=%s",
                user_id,
                task.id,
                listing.listing_id,
            )

    if not sent:
        sent = await _send_telegram_request(
            f"send_message user_id={user_id} task_id={task.id} listing_id={listing.listing_id}",
            lambda: bot.send_message(
                chat_id=user_id,
                text=_truncate_telegram_text(message, TELEGRAM_MESSAGE_LIMIT),
                reply_markup=reply_markup,
            ),
        )

    return sent


async def _process_task(
    session,
    bot: Bot,
    task: Task,
    listings: list[Listing],
) -> None:
    user = await crud.get_user(session, task.user_id)
    if not user:
        logger.warning("Task user missing: task_id=%s", task.id)
        return

    user_settings = await crud.get_or_create_settings(
        session,
        user_id=user.id,
        default_interval=user.default_interval_sec,
    )
    if not user_settings.monitor_enabled:
        logger.info("Skip task: monitoring disabled user_id=%s task_id=%s", user.id, task.id)
        return

    now_utc = datetime.utcnow()
    quiet_mode = is_quiet_hours(now_utc, user.timezone, user.quiet_hours_start, user.quiet_hours_end)
    first_run = task.last_checked_at is None
    logger.info(
        "Process task: task_id=%s user_id=%s quiet=%s first_run=%s listings=%s",
        task.id,
        user.id,
        quiet_mode,
        first_run,
        len(listings),
    )

    remaining_limit = None
    if user.notify_limit_per_hour is not None:
        sent_count = await crud.notification_count_last_hour(session, user.id)
        remaining_limit = max(0, user.notify_limit_per_hour - sent_count)
        logger.info(
            "Notify limit: user_id=%s sent_last_hour=%s remaining=%s",
            user.id,
            sent_count,
            remaining_limit,
        )

    notifications: list[tuple[Listing, str]] = []
    matched = 0
    skipped = 0

    for listing in listings:
        if not matches_task(task, listing, monitor_settings=user_settings):
            skipped += 1
            continue
        matched += 1

        content_hash = listing_hash(listing.title, listing.price, listing.location, listing.url)
        seen = await crud.get_seen_listing(session, task.id, listing.listing_id)

        if seen:
            logger.info(
                "Seen listing: task_id=%s listing_id=%s muted=%s",
                task.id,
                listing.listing_id,
                seen.is_muted,
            )
            if seen.is_muted:
                await crud.update_seen_listing(
                    session,
                    seen.id,
                    listing.price,
                    listing.title,
                    listing.url,
                    listing.location,
                    content_hash,
                )
                continue

            price_drop = (
                user.event_price_drop
                and listing.price is not None
                and seen.last_price is not None
                and listing.price < seen.last_price
            )
            updated = user.event_update and content_hash != seen.last_hash

            if price_drop:
                logger.info(
                    "Price drop detected: task_id=%s listing_id=%s old=%s new=%s",
                    task.id,
                    listing.listing_id,
                    seen.last_price,
                    listing.price,
                )
                notifications.append((listing, _price_drop_header(seen.last_price, listing.price)))
            elif updated:
                logger.info("Update detected: task_id=%s listing_id=%s", task.id, listing.listing_id)
                notifications.append((listing, "Объявление обновилось!"))

            await crud.update_seen_listing(
                session,
                seen.id,
                listing.price,
                listing.title,
                listing.url,
                listing.location,
                content_hash,
            )
            continue

        if user.event_new and not first_run:
            notifications.append((listing, NEW_DROP_HEADER))

        await crud.add_seen_listing(
            session,
            task.id,
            listing.listing_id,
            listing.price,
            listing.title,
            listing.url,
            listing.location,
            content_hash,
        )

    if not notifications:
        logger.info("No notifications: task_id=%s matched=%s skipped=%s", task.id, matched, skipped)
        return

    if not quiet_mode and len(notifications) >= settings.aggregate_threshold:
        logger.info("Aggregate notice: task_id=%s count=%s", task.id, len(notifications))
        await _send_telegram_request(
            f"send_aggregate_notice user_id={user.tg_id} task_id={task.id}",
            lambda: bot.send_message(
                chat_id=user.tg_id,
                text=f"Нашёл {len(notifications)} новых объявлений по радару {task.name}",
            ),
        )

    for listing, header in notifications:
        if quiet_mode:
            logger.info("Skip notify (quiet hours): task_id=%s listing_id=%s", task.id, listing.listing_id)
            continue
        if remaining_limit is not None and remaining_limit <= 0:
            logger.info("Skip notify (limit): task_id=%s listing_id=%s", task.id, listing.listing_id)
            continue
        sent = await _send_notification(bot, user.tg_id, task, listing, header)
        if sent:
            await crud.log_notification(session, user.id)
            if remaining_limit is not None:
                remaining_limit -= 1


async def main() -> None:
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    await create_db()
    await ensure_owner_user()

    bot = Bot(token=settings.telegram_token)
    session_maker = get_sessionmaker()
    bootstrap_fetcher = create_fetcher()
    logger.info("Monitor started: fetcher=%s", bootstrap_fetcher.__class__.__name__)
    if single_tenant_enabled():
        logger.info("Single-tenant mode enabled: owner_tg_id=%s", settings.owner_tg_id)

    last_global_fetch: datetime | None = None
    rate_limits: dict[int, RateLimitState] = {}
    blocked_until: dict[int, datetime] = {}
    blocked_notified_until: dict[int, datetime] = {}
    antiban_notified_until: dict[int, datetime] = {}
    last_request_at: datetime | None = None

    while True:
        now = datetime.utcnow()
        try:
            async with session_maker() as session:
                due_tasks = await crud.list_due_tasks(session, now, owner_tg_id=settings.owner_tg_id)
                if not due_tasks:
                    logger.info("No due tasks")
                    await asyncio.sleep(settings.scheduler_tick_sec)
                    continue

                if bootstrap_fetcher.is_global:
                    listings: list[Listing] = []
                    if not last_global_fetch or now - last_global_fetch >= timedelta(seconds=settings.global_poll_interval_sec):
                        logger.info("Global fetch start")
                        try:
                            listings = await bootstrap_fetcher.fetch()
                        except Exception:
                            logger.exception("Global fetch failed")
                            await asyncio.sleep(settings.scheduler_tick_sec)
                            continue
                        logger.info("Global fetch done: listings=%s", len(listings))
                        last_global_fetch = datetime.utcnow()
                    else:
                        logger.info("Global fetch skipped (interval)")
                        await asyncio.sleep(settings.scheduler_tick_sec)
                        continue

                    for task in due_tasks:
                        touched_at = datetime.utcnow()
                        try:
                            await _process_task(session, bot, task, listings)
                        except Exception:
                            logger.exception("Task processing failed: task_id=%s", task.id)
                        finally:
                            await crud.touch_task(session, task.id, touched_at)
                else:
                    for task in due_tasks:
                        task_now = datetime.utcnow()
                        user = None
                        try:
                            user = await crud.get_user(session, task.user_id)
                            if not user:
                                logger.warning("Skip task without user: task_id=%s", task.id)
                                continue

                            user_settings = await crud.get_or_create_settings(
                                session,
                                user_id=user.id,
                                default_interval=user.default_interval_sec,
                            )
                            if not user_settings.monitor_enabled:
                                logger.info("Monitor disabled for user_id=%s task_id=%s", user.id, task.id)
                                await crud.touch_task(session, task.id, task_now)
                                continue

                            profile = _build_fetch_profile(user_settings)
                            missing_antiban = _missing_antiban_for_profile(profile)
                            if missing_antiban:
                                notify_until = antiban_notified_until.get(user.id)
                                if not notify_until or task_now >= notify_until:
                                    await _send_telegram_request(
                                        f"send_antiban_notice user_id={user.tg_id} task_id={task.id}",
                                        lambda: bot.send_message(
                                            chat_id=user.tg_id,
                                            text=(
                                                "Мониторинг приостановлен: не заполнен обязательный антибан.\n"
                                                f"Заполни команды: {' '.join(missing_antiban)}"
                                            ),
                                        ),
                                    )
                                    antiban_notified_until[user.id] = task_now + timedelta(minutes=30)
                                await crud.touch_task(session, task.id, task_now)
                                continue

                            fetcher = create_fetcher(profile=profile)

                            if last_request_at:
                                delta = task_now - last_request_at
                                if delta < timedelta(seconds=settings.min_request_gap_sec):
                                    wait_sec = (timedelta(seconds=settings.min_request_gap_sec) - delta).total_seconds()
                                    logger.info("Global throttle: sleep %.1fs", wait_sec)
                                    await asyncio.sleep(wait_sec)
                                    task_now = datetime.utcnow()

                            block_until = blocked_until.get(task.id)
                            if block_until and task_now < block_until:
                                wait_sec = int((block_until - task_now).total_seconds())
                                logger.info("Blocked cooldown: task_id=%s wait_sec=%s", task.id, wait_sec)
                                continue

                            rl_state = rate_limits.get(task.id)
                            if rl_state and task_now < rl_state.next_allowed_at:
                                wait_sec = int((rl_state.next_allowed_at - task_now).total_seconds())
                                logger.info(
                                    "Rate limit active: task_id=%s wait_sec=%s backoff=%s",
                                    task.id,
                                    wait_sec,
                                    rl_state.backoff_sec,
                                )
                                continue

                            logger.info("Task fetch start: task_id=%s url=%s", task.id, task.search_url)
                            try:
                                listings = await fetcher.fetch(task=task)
                                last_request_at = datetime.utcnow()
                            except RateLimitError as exc:
                                base = max(30, task.interval_sec)
                                prev = rate_limits.get(task.id)
                                if prev:
                                    backoff = min(MAX_BACKOFF_SEC, max(base, prev.backoff_sec * 2))
                                else:
                                    backoff = min(MAX_BACKOFF_SEC, base * 2)
                                if exc.retry_after:
                                    backoff = max(backoff, exc.retry_after)
                                jitter = random.randint(1, max(2, backoff // 4))
                                next_allowed = task_now + timedelta(seconds=backoff + jitter)
                                rate_limits[task.id] = RateLimitState(
                                    backoff_sec=backoff,
                                    next_allowed_at=next_allowed,
                                    success_streak=0,
                                )
                                logger.warning(
                                    "Rate limited: task_id=%s backoff=%s retry_after=%s",
                                    task.id,
                                    backoff,
                                    exc.retry_after,
                                )
                                continue
                            except BlockedError:
                                cooldown_sec = max(300, task.interval_sec * 4)
                                blocked_until[task.id] = task_now + timedelta(seconds=cooldown_sec)
                                notify_until = blocked_notified_until.get(task.id)
                                if not notify_until or task_now >= notify_until:
                                    await _send_telegram_request(
                                        f"send_blocked_notice user_id={user.tg_id} task_id={task.id}",
                                        lambda: bot.send_message(
                                            chat_id=user.tg_id,
                                            text=(
                                                "Avito ограничил доступ (бан/капча). "
                                                "Проверь /set_proxy и /set_proxy_change_url."
                                            ),
                                        ),
                                    )
                                    blocked_notified_until[task.id] = task_now + timedelta(minutes=30)
                                logger.warning("Blocked: task_id=%s cooldown=%s", task.id, cooldown_sec)
                                continue

                            logger.info("Task fetch done: task_id=%s listings=%s", task.id, len(listings))
                            rl_state = rate_limits.get(task.id)
                            if rl_state:
                                rl_state.success_streak += 1
                                if rl_state.success_streak >= 3:
                                    base = max(30, task.interval_sec)
                                    new_backoff = max(base, rl_state.backoff_sec // 2)
                                    if new_backoff <= base:
                                        rate_limits.pop(task.id, None)
                                        logger.info("Rate limit cleared: task_id=%s", task.id)
                                    else:
                                        rl_state.backoff_sec = new_backoff
                                        rl_state.next_allowed_at = task_now + timedelta(seconds=new_backoff)
                                        rl_state.success_streak = 0
                                        logger.info(
                                            "Rate limit reduced: task_id=%s backoff=%s",
                                            task.id,
                                            new_backoff,
                                        )

                            await _process_task(session, bot, task, listings)
                            await crud.touch_task(session, task.id, datetime.utcnow())
                        except Exception:
                            logger.exception("Task loop failed: task_id=%s", task.id)
                            await crud.touch_task(session, task.id, datetime.utcnow())
                            continue
        except Exception:
            logger.exception("Monitor loop iteration failed")

        await asyncio.sleep(settings.scheduler_tick_sec)


if __name__ == "__main__":
    asyncio.run(main())
