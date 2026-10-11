"""Add explicit ownership without guessing the owners of legacy catalogue rows."""
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.db.models import Business


def migrate_business_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        Business.__table__.create(connection, checkfirst=True)
        tables = set(inspect(connection).get_table_names())
        for table, field, target in (
            ("brands", "organization_id", "businesses(id)"),
            ("plants", "organization_id", "businesses(id)"),
            ("regions", "city_id", "cities(id)"),
            ("regions", "organization_id", "businesses(id)"),
            ("states", "organization_id", "businesses(id)"),
            ("cities", "organization_id", "businesses(id)"),
        ):
            if table not in tables:
                continue
            columns = {c["name"] for c in inspect(connection).get_columns(table)}
            if field not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {field} VARCHAR(100) REFERENCES {target}"
                )
            connection.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_{field} ON {table} ({field})"
            )
        if connection.dialect.name == "postgresql" and "brands" in tables:
            connection.exec_driver_sql("ALTER TABLE brands ALTER COLUMN name_key TYPE VARCHAR(400)")
        if "states" in tables:
            connection.exec_driver_sql("DROP INDEX IF EXISTS uq_states_country_name_ci")
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_states_owner_country_name_ci "
                "ON states (organization_id, country_code, lower(name))"
            )
