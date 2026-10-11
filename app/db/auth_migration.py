"""Idempotent additive migration for Clerk organization ownership and audit actors."""
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.db.models import OrganizationPlant


_COLUMNS = {
    "routes": {
        "organization_id": "VARCHAR(100)",
        "created_by_user_id": "VARCHAR(100)",
    },
    "trips": {
        "organization_id": "VARCHAR(100)",
        "created_by_user_id": "VARCHAR(100)",
        "archived_at": "TIMESTAMP",
        "archived_by_user_id": "VARCHAR(100)",
    },
    "trip_events": {
        "actor_user_id": "VARCHAR(100)",
    },
    "catalogue_events": {
        "actor_user_id": "VARCHAR(100)",
        "organization_id": "VARCHAR(100)",
    },
}


def migrate_auth_schema(engine: Engine) -> None:
    """Add nullable ownership columns, preserving existing rows as legacy data."""
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        existing_tables = set(inspect(connection).get_table_names())
        for table_name, columns in _COLUMNS.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {
                column["name"] for column in inspect(connection).get_columns(table_name)
            }
            for column_name, column_type in columns.items():
                if column_name not in existing_columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                    )
        OrganizationPlant.__table__.create(connection, checkfirst=True)
        for table_name in ("routes", "trips", "catalogue_events"):
            if table_name in existing_tables:
                index_name = f"ix_{table_name}_organization_id"
                connection.exec_driver_sql(
                    f"CREATE INDEX IF NOT EXISTS {index_name} "
                    f"ON {table_name} (organization_id)"
                )
