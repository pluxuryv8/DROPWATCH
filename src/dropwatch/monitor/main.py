import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from aiogram import Bot

from dropwatch.common.config import settings
from dropwatch.common.enrichment import enrich_listing
from dropwatch.common.formatting import build_listing_summary, format_listing_message
from dropwatch.common.hash_utils import listing_hash
from dropwatch.common.logging import setup_logging
from dropwatch.common.matching import matches_task
from dropwatch.common.secrets import decode_secret
from dropwatch.common.time_utils import is_quiet_hours
from dropwatch.common.types import Listing
from dropwatch.db import crud
from dropwatch.db.database import create_db, get_sessionmaker, init_engine
from dropwatch.db.models import Task
from dropwatch.monitor.fetchers.factory import create_fetcher
from dropwatch.monitor.fetchers.avito_search import AvitoRuntimeProfile, BlockedError, RateLimitError
from dropwatch.bot.keyboards import listing_actions_keyboard
from dropwatch.bot.texts import NEW_DROP_HEADER


logger = logging.getLogger("monitor")
MAX_BACKOFF_SEC = 600
MIN_REQUEST_GAP_SEC = 30


@dataclass
class RateLimitState:
    backoff_sec: int
    next_allowed_at: datetime
    success_streak: int = 0


def _build_fetch_profile(user_settings) -> AvitoRuntimeProfile:
    cookies_path_suffix = str(getattr(user_settings, "user_id", "default"))
    return AvitoRuntimeProfile(
        proxy=decode_secret(getattr(user_settings, "proxy_b64", None)),
        proxy_change_url=decode_secret(getattr(user_settings, "proxy_change_url_b64", None)),
        cookies_api_key=None,
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
        return "💸 Цена снизилась!"
    return f"💸 Цена снизилась! Было {old_price} ₽ → {new_price} ₽"


async def _send_notification(
    bot: Bot,
    user_id: int,
    task: Task,
    listing: Listing,
    header: str,
) -> None:
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
    if listing.image_url:
        await bot.send_photo(
            chat_id=user_id,
            photo=listing.image_url,
            caption=message,
            reply_markup=listing_actions_keyboard(task.id, listing.listing_id, listing.url),
        )
    else:
        await bot.send_message(
            chat_id=user_id,
            text=message,
            reply_markup=listing_actions_keyboard(task.id, listing.listing_id, listing.url),
        )
    if settings.llm_enabled:
        asyncio.create_task(_send_llm_followup(bot, user_id, listing))


async def _send_llm_followup(bot: Bot, user_id: int, listing: Listing) -> None:
    logger.info("LLM followup start: user_id=%s listing_id=%s", user_id, listing.listing_id)
    enrichment = await enrich_listing(listing)
    lines = ["🤖 Анализ объявления", f"📌 {listing.title}"]
    if enrichment.summary:
        lines.append(f"📝 Кратко: {enrichment.summary}")
    if enrichment.score is not None:
        lines.append(f"⭐ Оценка состояния: {enrichment.score}/10")
    if enrichment.notes:
        lines.append(f"⚠️ {enrichment.notes}")
    if enrichment.error:
        lines.append(f"⚠️ {enrichment.error}")
    if len(lines) <= 2:
        logger.info("LLM followup skipped: user_id=%s listing_id=%s", user_id, listing.listing_id)
        return
    if listing.url:
        lines.append(listing.url)
    await bot.send_message(chat_id=user_id, text="\n".join(lines))
    logger.info("LLM followup sent: user_id=%s listing_id=%s", user_id, listing.listing_id)


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
        default_interval=settings.default_task_interval_sec,
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
                notifications.append((listing, "✏️ Обновление объявления!"))
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

        if user.event_new:
            if not first_run:
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
        await bot.send_message(
            chat_id=user.tg_id,
            text=f"Нашёл {len(notifications)} новых объявлений по радару {task.name}",
        )

    for listing, header in notifications:
        if quiet_mode:
            logger.info("Skip notify (quiet hours): task_id=%s listing_id=%s", task.id, listing.listing_id)
            continue
        if remaining_limit is not None and remaining_limit <= 0:
            logger.info("Skip notify (limit): task_id=%s listing_id=%s", task.id, listing.listing_id)
            continue
        await _send_notification(bot, user.tg_id, task, listing, header)
        await crud.log_notification(session, user.id)
        if remaining_limit is not None:
            remaining_limit -= 1


async def main() -> None:
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    await create_db()

    bot = Bot(token=settings.telegram_token)

    session_maker = get_sessionmaker()
    bootstrap_fetcher = create_fetcher()
    logger.info("Monitor started: fetcher=%s", bootstrap_fetcher.__class__.__name__)

    last_global_fetch = None
    rate_limits: dict[int, RateLimitState] = {}
    blocked_until: dict[int, datetime] = {}
    blocked_notified_until: dict[int, datetime] = {}
    antiban_notified_until: dict[int, datetime] = {}
    last_request_at: datetime | None = None

    while True:
        now = datetime.utcnow()
        async with session_maker() as session:
            due_tasks = await crud.list_due_tasks(session, now)
            if not due_tasks:
                logger.info("No due tasks")
                await asyncio.sleep(settings.scheduler_tick_sec)
                continue

            listings: list[Listing] = []
            if bootstrap_fetcher.is_global:
                if not last_global_fetch or now - last_global_fetch >= timedelta(seconds=settings.global_poll_interval_sec):
                    logger.info("Global fetch start")
                    listings = await bootstrap_fetcher.fetch()
                    logger.info("Global fetch done: listings=%s", len(listings))
                    last_global_fetch = now
                else:
                    logger.info("Global fetch skipped (interval)")
                    await asyncio.sleep(settings.scheduler_tick_sec)
                    continue

                for task in due_tasks:
                    await _process_task(session, bot, task, listings)
                    await crud.touch_task(session, task.id, now)
            else:
                for task in due_tasks:
                    now = datetime.utcnow()
                    user = await crud.get_user(session, task.user_id)
                    if not user:
                        logger.warning("Skip task without user: task_id=%s", task.id)
                        continue
                    user_settings = await crud.get_or_create_settings(
                        session,
                        user_id=user.id,
                        default_interval=settings.default_task_interval_sec,
                    )
                    if not user_settings.monitor_enabled:
                        logger.info("Monitor disabled for user_id=%s task_id=%s", user.id, task.id)
                        await crud.touch_task(session, task.id, now)
                        continue
                    profile = _build_fetch_profile(user_settings)
                    missing_antiban = _missing_antiban_for_profile(profile)
                    if missing_antiban:
                        notify_until = antiban_notified_until.get(user.id)
                        if not notify_until or now >= notify_until:
                            await bot.send_message(
                                chat_id=user.tg_id,
                                text=(
                                    "Мониторинг приостановлен: не заполнен обязательный антибан.\n"
                                    f"Заполни команды: {' '.join(missing_antiban)}"
                                ),
                            )
                            antiban_notified_until[user.id] = now + timedelta(minutes=30)
                        await crud.touch_task(session, task.id, now)
                        continue
                    fetcher = create_fetcher(profile=profile)

                    if last_request_at:
                        delta = now - last_request_at
                        if delta < timedelta(seconds=MIN_REQUEST_GAP_SEC):
                            wait_sec = (timedelta(seconds=MIN_REQUEST_GAP_SEC) - delta).total_seconds()
                            logger.info("Global throttle: sleep %.1fs", wait_sec)
                            await asyncio.sleep(wait_sec)
                            now = datetime.utcnow()

                    block_until = blocked_until.get(task.id)
                    if block_until and now < block_until:
                        wait_sec = int((block_until - now).total_seconds())
                        logger.info("Blocked cooldown: task_id=%s wait_sec=%s", task.id, wait_sec)
                        continue

                    rl_state = rate_limits.get(task.id)
                    if rl_state and now < rl_state.next_allowed_at:
                        wait_sec = int((rl_state.next_allowed_at - now).total_seconds())
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
                            streak = 0
                        else:
                            backoff = min(MAX_BACKOFF_SEC, base * 2)
                            streak = 0
                        if exc.retry_after:
                            backoff = max(backoff, exc.retry_after)
                        jitter = random.randint(1, max(2, backoff // 4))
                        next_allowed = now + timedelta(seconds=backoff + jitter)
                        rate_limits[task.id] = RateLimitState(
                            backoff_sec=backoff,
                            next_allowed_at=next_allowed,
                            success_streak=streak,
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
                        blocked_until[task.id] = now + timedelta(seconds=cooldown_sec)
                        notify_until = blocked_notified_until.get(task.id)
                        if not notify_until or now >= notify_until:
                            if user:
                                await bot.send_message(
                                    chat_id=user.tg_id,
                                    text=(
                                        "Avito ограничил доступ (бан/капча). "
                                        "Проверьте /set_proxy и /set_proxy_change_url."
                                    ),
                                )
                            blocked_notified_until[task.id] = now + timedelta(minutes=30)
                        logger.warning("Blocked: task_id=%s cooldown=%s", task.id, cooldown_sec)
                        continue
                    logger.info("Task fetch done: task_id=%s listings=%s", task.id, len(listings))
                    if task.id in rate_limits:
                        rl_state = rate_limits[task.id]
                        rl_state.success_streak += 1
                        if rl_state.success_streak >= 3:
                            base = max(30, task.interval_sec)
                            new_backoff = max(base, rl_state.backoff_sec // 2)
                            if new_backoff <= base:
                                rate_limits.pop(task.id, None)
                                logger.info("Rate limit cleared: task_id=%s", task.id)
                            else:
                                rl_state.backoff_sec = new_backoff
                                rl_state.next_allowed_at = now + timedelta(seconds=new_backoff)
                                rl_state.success_streak = 0
                                logger.info(
                                    "Rate limit reduced: task_id=%s backoff=%s",
                                    task.id,
                                    new_backoff,
                                )
                    await _process_task(session, bot, task, listings)
                    await crud.touch_task(session, task.id, now)

        await asyncio.sleep(settings.scheduler_tick_sec)


if __name__ == "__main__":
    asyncio.run(main())
