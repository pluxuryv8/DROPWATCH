from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


def parse_time(value: str) -> time | None:
    try:
        parts = value.split(":")
        if len(parts) != 2:
            return None
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, TypeError):
        return None


def is_quiet_hours(now_utc: datetime, timezone_str: str, start: str | None, end: str | None) -> bool:
    if not start or not end:
        return False
    start_time = parse_time(start)
    end_time = parse_time(end)
    if not start_time or not end_time:
        return False
    local = now_utc.astimezone(ZoneInfo(timezone_str))
    local_time = local.time()

    if start_time < end_time:
        return start_time <= local_time < end_time
    # quiet hours through midnight
    return local_time >= start_time or local_time < end_time
