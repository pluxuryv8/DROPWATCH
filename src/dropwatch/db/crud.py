from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dropwatch.db.models import (
    Condition,
    Delivery,
    Favorite,
    NotificationLog,
    SeenListing,
    SellerType,
    Task,
    TaskStatus,
    User,
)


async def get_or_create_user(session: AsyncSession, tg_id: int, timezone_str: str, default_interval: int) -> User:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalars().first()
    if user:
        return user
    user = User(
        tg_id=tg_id,
        timezone=timezone_str,
        default_interval_sec=default_interval,
        event_new=True,
        event_price_drop=False,
        event_update=False,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user_settings(
    session: AsyncSession,
    user_id: int,
    **kwargs,
) -> None:
    await session.execute(update(User).where(User.id == user_id).values(**kwargs))
    await session.commit()


async def list_tasks(session: AsyncSession, user_id: int) -> list[Task]:
    result = await session.execute(select(Task).where(Task.user_id == user_id).order_by(Task.created_at.desc()))
    return list(result.scalars())


async def get_task(session: AsyncSession, task_id: int, user_id: int | None = None) -> Task | None:
    stmt = select(Task).where(Task.id == task_id)
    if user_id is not None:
        stmt = stmt.where(Task.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_task(
    session: AsyncSession,
    user_id: int,
    name: str,
    keywords: str | None,
    minus_keywords: str | None,
    category: str | None,
    city: str | None,
    radius_km: int | None,
    price_min: int | None,
    price_max: int | None,
    condition: Condition,
    delivery: Delivery,
    seller_type: SellerType,
    sort_new_first: bool,
    interval_sec: int,
    status: TaskStatus,
    search_url: str | None,
    source: str | None,
) -> Task:
    task = Task(
        user_id=user_id,
        name=name,
        keywords=keywords,
        minus_keywords=minus_keywords,
        category=category,
        city=city,
        radius_km=radius_km,
        price_min=price_min,
        price_max=price_max,
        condition=condition,
        delivery=delivery,
        seller_type=seller_type,
        sort_new_first=sort_new_first,
        interval_sec=interval_sec,
        status=status,
        search_url=search_url,
        source=source,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def update_task(session: AsyncSession, task_id: int, **kwargs) -> None:
    await session.execute(update(Task).where(Task.id == task_id).values(**kwargs))
    await session.commit()


async def delete_task(session: AsyncSession, task_id: int) -> None:
    await session.execute(delete(Task).where(Task.id == task_id))
    await session.commit()


async def clear_seen_for_task(session: AsyncSession, task_id: int) -> None:
    await session.execute(delete(SeenListing).where(SeenListing.task_id == task_id))
    await session.commit()


async def set_task_status(session: AsyncSession, task_id: int, status: TaskStatus) -> None:
    await session.execute(update(Task).where(Task.id == task_id).values(status=status))
    await session.commit()


async def pause_tasks_for_user(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(Task)
        .where(Task.user_id == user_id, Task.status == TaskStatus.active)
        .values(status=TaskStatus.paused)
    )
    await session.commit()


async def list_due_tasks(session: AsyncSession, now: datetime) -> list[Task]:
    result = await session.execute(select(Task).where(Task.status == TaskStatus.active))
    tasks = list(result.scalars())
    due: list[Task] = []
    for task in tasks:
        if task.last_checked_at is None:
            due.append(task)
            continue
        if now - task.last_checked_at >= timedelta(seconds=task.interval_sec):
            due.append(task)
    return due


async def list_active_tasks(session: AsyncSession) -> list[Task]:
    result = await session.execute(select(Task).where(Task.status == TaskStatus.active))
    return list(result.scalars())


async def touch_task(session: AsyncSession, task_id: int, when: datetime) -> None:
    await session.execute(update(Task).where(Task.id == task_id).values(last_checked_at=when))
    await session.commit()


async def get_seen_listing(session: AsyncSession, task_id: int, listing_id: str) -> SeenListing | None:
    result = await session.execute(
        select(SeenListing).where(SeenListing.task_id == task_id, SeenListing.listing_id == listing_id)
    )
    return result.scalars().first()


async def add_seen_listing(
    session: AsyncSession,
    task_id: int,
    listing_id: str,
    price: int | None,
    title: str | None,
    url: str | None,
    location: str | None,
    content_hash: str | None,
) -> SeenListing:
    seen = SeenListing(
        task_id=task_id,
        listing_id=listing_id,
        last_price=price,
        last_title=title,
        last_url=url,
        last_location=location,
        last_hash=content_hash,
        last_seen_at=datetime.utcnow(),
    )
    session.add(seen)
    await session.commit()
    await session.refresh(seen)
    return seen


async def update_seen_listing(
    session: AsyncSession,
    seen_id: int,
    price: int | None,
    title: str | None,
    url: str | None,
    location: str | None,
    content_hash: str | None,
) -> None:
    await session.execute(
        update(SeenListing)
        .where(SeenListing.id == seen_id)
        .values(
            last_price=price,
            last_title=title,
            last_url=url,
            last_location=location,
            last_hash=content_hash,
            last_seen_at=datetime.utcnow(),
        )
    )
    await session.commit()


async def mute_seen_listing(session: AsyncSession, task_id: int, listing_id: str) -> None:
    await session.execute(
        update(SeenListing)
        .where(SeenListing.task_id == task_id, SeenListing.listing_id == listing_id)
        .values(is_muted=True)
    )
    await session.commit()


async def add_favorite(
    session: AsyncSession,
    user_id: int,
    listing_id: str,
    title: str | None,
    price: int | None,
    url: str | None,
    location: str | None,
) -> None:
    existing = await session.execute(
        select(Favorite).where(Favorite.user_id == user_id, Favorite.listing_id == listing_id)
    )
    if existing.scalars().first():
        return
    favorite = Favorite(
        user_id=user_id,
        listing_id=listing_id,
        title=title,
        price=price,
        url=url,
        location=location,
    )
    session.add(favorite)
    await session.commit()


async def list_favorites(session: AsyncSession, user_id: int) -> list[Favorite]:
    result = await session.execute(select(Favorite).where(Favorite.user_id == user_id).order_by(Favorite.saved_at.desc()))
    return list(result.scalars())


async def log_notification(session: AsyncSession, user_id: int) -> None:
    session.add(NotificationLog(user_id=user_id))
    await session.commit()


async def notification_count_last_hour(session: AsyncSession, user_id: int) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=1)
    result = await session.execute(
        select(func.count(NotificationLog.id)).where(
            NotificationLog.user_id == user_id,
            NotificationLog.sent_at >= cutoff,
        )
    )
    return int(result.scalar() or 0)


async def delete_favorite(session: AsyncSession, user_id: int, listing_id: str) -> None:
    await session.execute(
        delete(Favorite).where(Favorite.user_id == user_id, Favorite.listing_id == listing_id)
    )
    await session.commit()


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalars().first()


async def get_user_by_tg(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalars().first()


async def get_tasks_for_user(session: AsyncSession, user_id: int) -> list[Task]:
    result = await session.execute(select(Task).where(Task.user_id == user_id))
    return list(result.scalars())
