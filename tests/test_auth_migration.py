"""Legacy operational rows are preserved and left explicitly unscoped."""
from sqlalchemy import create_engine, inspect, text

from app.db.auth_migration import migrate_auth_schema


def test_additive_auth_migration_is_idempotent_and_preserves_legacy_rows():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE plants (id VARCHAR(100) PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE routes (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE trips (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE trip_events (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE catalogue_events (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO routes (id) VALUES (7)")
        connection.exec_driver_sql("INSERT INTO trips (id) VALUES (11)")

    migrate_auth_schema(engine)
    migrate_auth_schema(engine)

    with engine.connect() as connection:
        route_columns = {c["name"] for c in inspect(connection).get_columns("routes")}
        trip_columns = {c["name"] for c in inspect(connection).get_columns("trips")}
        assert {"organization_id", "created_by_user_id"} <= route_columns
        assert {
            "organization_id", "created_by_user_id", "archived_at",
            "archived_by_user_id",
        } <= trip_columns
        assert connection.execute(text(
            "SELECT organization_id, created_by_user_id FROM routes WHERE id=7",
        )).one() == (None, None)
        assert connection.execute(text(
            "SELECT organization_id, created_by_user_id FROM trips WHERE id=11",
        )).one() == (None, None)
        assert "organization_plants" in inspect(connection).get_table_names()

    engine.dispose()
