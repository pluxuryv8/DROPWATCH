from __future__ import annotations

from datetime import datetime
import enum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dropwatch.db.database import Base


class TaskStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    stopped = "stopped"


class Condition(str, enum.Enum):
    any = "any"
    new = "new"
    used = "used"


class Delivery(str, enum.Enum):
    any = "any"
    yes = "yes"
    no = "no"


class SellerType(str, enum.Enum):
    any = "any"
    private = "private"
    shop = "shop"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")

    default_interval_sec: Mapped[int] = mapped_column(Integer, default=120)
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    notify_limit_per_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_new: Mapped[bool] = mapped_column(Boolean, default=True)
    event_price_drop: Mapped[bool] = mapped_column(Boolean, default=False)
    event_update: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tasks: Mapped[list[Task]] = relationship(back_populates="user")
    settings: Mapped[Settings | None] = relationship(back_populates="user", uselist=False)


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)

    proxy_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    proxy_change_url_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    cookies_api_key_b64: Mapped[str | None] = mapped_column(Text, nullable=True)

    avito_links_json: Mapped[str] = mapped_column(Text, default="[]")
    keywords_white_json: Mapped[str] = mapped_column(Text, default="[]")
    keywords_black_json: Mapped[str] = mapped_column(Text, default="[]")

    min_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_age: Mapped[int] = mapped_column(Integer, default=0)
    ignore_reserv: Mapped[bool] = mapped_column(Boolean, default=False)
    ignore_promotion: Mapped[bool] = mapped_column(Boolean, default=False)
    interval: Mapped[int] = mapped_column(Integer, default=60)
    monitor_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="settings")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(200))
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    minus_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    radius_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_max: Mapped[int | None] = mapped_column(Integer, nullable=True)

    condition: Mapped[Condition] = mapped_column(Enum(Condition), default=Condition.any)
    delivery: Mapped[Delivery] = mapped_column(Enum(Delivery), default=Delivery.any)
    seller_type: Mapped[SellerType] = mapped_column(Enum(SellerType), default=SellerType.any)

    sort_new_first: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_sec: Mapped[int] = mapped_column(Integer, default=120)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.active)

    search_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="tasks")
    seen_listings: Mapped[list[SeenListing]] = relationship(back_populates="task")


class SeenListing(Base):
    __tablename__ = "seen_listings"
    __table_args__ = (UniqueConstraint("task_id", "listing_id", name="uq_task_listing"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    listing_id: Mapped[str] = mapped_column(String(128))

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    last_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_muted: Mapped[bool] = mapped_column(Boolean, default=False)

    task: Mapped[Task] = relationship(back_populates="seen_listings")


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "listing_id", name="uq_user_listing"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    listing_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
