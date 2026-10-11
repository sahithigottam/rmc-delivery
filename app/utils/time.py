"""UTC conversion for persistence and API timestamps."""
from datetime import datetime, timezone


def as_utc(value: datetime) -> datetime:
    """Treat legacy naive database values as UTC, never as server-local time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
