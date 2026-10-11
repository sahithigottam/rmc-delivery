"""Idempotently create only the Country -> State -> City catalogue tables."""
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.db.database import Base
from app.db.geography import City, Country, State
from app.db.models import Business


GEOGRAPHY_TABLES = (Country.__table__, State.__table__, City.__table__)
REQUIRED_COLUMNS = {
    "countries": {"code", "name"},
    "states": {"id", "country_code", "name"},
    "cities": {"id", "state_id", "name", "timezone"},
}


class GeographyMigrationError(RuntimeError):
    """The existing geography schema is incomplete or incompatible."""


def migrate_geography(engine: Engine) -> None:
    """Create missing geography tables without importing or changing catalogue data."""
    if not isinstance(engine, Engine):
        raise TypeError("migrate_geography requires an Engine")

    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        Business.__table__.create(connection, checkfirst=True)
        Base.metadata.create_all(connection, tables=GEOGRAPHY_TABLES, checkfirst=True)
        inspector = inspect(connection)
        missing_tables = set(REQUIRED_COLUMNS) - set(inspector.get_table_names())
        if missing_tables:
            raise GeographyMigrationError(
                f"Geography migration did not create tables: {sorted(missing_tables)}",
            )
        for table_name, required in REQUIRED_COLUMNS.items():
            actual = {column["name"] for column in inspector.get_columns(table_name)}
            if not required <= actual:
                raise GeographyMigrationError(
                    f"Existing {table_name} table is missing columns: "
                    f"{sorted(required - actual)}",
                )
