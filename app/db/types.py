"""Database types that preserve UTC semantics on SQLite."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.utils.time import as_utc


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: Optional[datetime], dialect: Dialect,
    ) -> Optional[datetime]:
        if value is None:
            return None
        utc_value = as_utc(value)
        return utc_value.replace(tzinfo=None) if dialect.name == "sqlite" else utc_value

    def process_result_value(
        self, value: Optional[datetime], dialect: Dialect,
    ) -> Optional[datetime]:
        return as_utc(value) if value is not None else None
