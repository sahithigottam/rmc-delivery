"""Isolated catalogue bootstrap and storage regressions; no app lifespan."""
from datetime import timedelta
import json
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.catalogue_migration import (
    CATALOGUE_TABLES, CatalogueMigrationError, migrate_catalogue,
)
from app.db.database import Base
from app.db.geography import BusinessCountry, Country, State, City
from app.db.models import (
    Business, Brand, CatalogueEvent, CatalogueIdempotency, CatalogueMigration, Plant, Region, Route, Trip,
)


@pytest.fixture
def engine():
    isolated = create_engine("sqlite:///:memory:")
    yield isolated
    isolated.dispose()


@pytest.fixture
def seed_path():
    # Keep scratch files inside the repository, not OS temporary directories.
    directory = Path(__file__).resolve().parent / f".catalogue_test_{uuid4().hex}"
    directory.mkdir()
    path = directory / "seed.json"
    path.write_text(json.dumps(seed_rows()), encoding="utf-8")
    yield path
    shutil.rmtree(directory)


def seed_rows():
    return [
        {
            "id": "legacy_plant_id", "name": "Original plant", "brand": "Acme",
            "region": "central_west", "address": "Auckland", "lat": -36.8,
            "lng": 174.7, "active": True,
        },
        {
            "id": "inactive_india_id", "name": "Inactive plant", "brand": "Acme",
            "region": "warangal", "address": "Warangal", "lat": 18.0,
            "lng": 79.5, "active": False,
        },
    ]


def test_import_preserves_ids_inactive_relationships_and_utc(engine, seed_path):
    result = migrate_catalogue(engine, seed_path)
    assert (result.version, result.applied, result.brands, result.regions, result.plants) == (
        1, True, 1, 2, 2,
    )
    prerequisites = {table.__tablename__ for table in (Business, Country, BusinessCountry, State, City)}
    assert set(inspect(engine).get_table_names()) == {table.name for table in CATALOGUE_TABLES} | prerequisites
    with Session(engine) as db:
        plant = db.get(Plant, "inactive_india_id")
        assert plant.active is False
        assert plant.brand.id == "brand_acme"
        assert plant.brand.name_key == "acme"
        assert plant.region.id == "in_telangana_warangal"
        assert plant.region.country_code == "IN"
        assert plant.region.administrative_area == "Telangana"
        assert plant.region.timezone == "Asia/Kolkata"
        assert plant.region.calibration_status == "uncalibrated"
        nz = db.get(Plant, "legacy_plant_id").region
        assert (nz.id, nz.country_code, nz.administrative_area, nz.timezone) == (
            "nz_central_west", "NZ", "Auckland", "Pacific/Auckland",
        )
        assert nz.calibration_status == "nz_baseline"
        assert plant.supported_mix_codes == ["GP", "HE", "RE"]
        for record in (plant, plant.brand, plant.region):
            assert record.version == 1
            assert record.created_at.utcoffset() == timedelta(0)
            assert record.updated_at.utcoffset() == timedelta(0)
        assert db.get(CatalogueMigration, 1).applied_at.utcoffset() == timedelta(0)


def test_restart_does_not_read_seed_or_overwrite_edits(engine, seed_path, monkeypatch):
    migrate_catalogue(engine, seed_path)
    with Session(engine) as db:
        plant = db.get(Plant, "legacy_plant_id")
        plant.name = "Edited by administrator"
        plant.active = False
        plant.version = 7
        plant.brand.name = "New Supplier"
        db.delete(db.get(Plant, "inactive_india_id"))
        db.commit()
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("Seed reread"))
    result = migrate_catalogue(engine, seed_path)
    assert not result.applied
    assert (result.brands, result.regions, result.plants) == (0, 0, 0)
    with Session(engine) as db:
        plant = db.get(Plant, "legacy_plant_id")
        assert (plant.name, plant.active, plant.version) == (
            "Edited by administrator", False, 7,
        )
        assert plant.brand.name_key == "new supplier"
        assert db.get(Plant, "inactive_india_id") is None


@pytest.mark.parametrize("mutation,match", [
    (lambda rows: rows.append(dict(rows[0])), "Duplicate plant id"),
    (lambda rows: rows[1].update(region="unknown"), "Unknown legacy region"),
    (lambda rows: rows[1].update(lat=91), "invalid lat"),
    (lambda rows: rows[1].update(lng=-181), "invalid lng"),
    (lambda rows: rows[1].update(lat=float("nan")), "invalid lat"),
    (lambda rows: rows[1].update(lng=True), "invalid lng"),
    (lambda rows: rows[1].update(active="false"), "invalid active"),
    (lambda rows: rows[1].update(name=" "), "invalid name"),
    (lambda rows: rows[1].update(brand=" "), "invalid brand"),
    (lambda rows: rows[1].update(supported_mix_codes=["UNKNOWN"]), "invalid supported_mix_codes"),
    (lambda rows: rows[0].update(brand="A & B") or rows[1].update(brand="A-B"), "slug collision"),
    (lambda rows: rows[0].update(brand="Café") or rows[1].update(brand="Cafe"), "slug collision"),
])
def test_invalid_seed_changes_nothing(engine, seed_path, mutation, match):
    rows = seed_rows()
    mutation(rows)
    seed_path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(CatalogueMigrationError, match=match):
        migrate_catalogue(engine, seed_path)
    assert inspect(engine).get_table_names() == []


@pytest.mark.parametrize("payload", ["{}", "[]", "{broken"])
def test_invalid_seed_structure(engine, seed_path, payload):
    seed_path.write_text(payload, encoding="utf-8")
    with pytest.raises(CatalogueMigrationError):
        migrate_catalogue(engine, seed_path)
    assert inspect(engine).get_table_names() == []


def test_failed_insert_rolls_back_ddl_data_and_ledger(engine, seed_path):
    def fail_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO plants"):
            raise RuntimeError("simulated insert failure")

    event.listen(engine, "before_cursor_execute", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            migrate_catalogue(engine, seed_path)
    finally:
        event.remove(engine, "before_cursor_execute", fail_insert)
    assert inspect(engine).get_table_names() == []
    assert migrate_catalogue(engine, seed_path).applied


def test_nonempty_unledgered_catalogue_rejected(engine, seed_path):
    Business.__table__.create(engine)
    Brand.__table__.create(engine)
    with Session(engine) as db:
        db.add(Brand(id="custom", name="Existing Supplier"))
        db.commit()
    with pytest.raises(CatalogueMigrationError, match="Nonempty catalogue"):
        migrate_catalogue(engine, seed_path)
    assert set(inspect(engine).get_table_names()) == {"brands", "businesses"}
    with Session(engine) as db:
        assert db.get(Brand, "custom").name == "Existing Supplier"


def test_existing_empty_tables_can_be_bootstrapped(engine, seed_path):
    Base.metadata.create_all(engine, tables=CATALOGUE_TABLES)
    assert migrate_catalogue(engine, seed_path).plants == 2


def test_seed_is_read_once_and_brand_variants_share_key(engine, seed_path, monkeypatch):
    rows = seed_rows()
    rows[0]["brand"] = " ACME  Supply "
    rows[1]["brand"] = "acme supply"
    seed_path.write_text(json.dumps(rows), encoding="utf-8")
    original = Path.read_text
    reads = []

    def counted(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    assert migrate_catalogue(engine, seed_path).brands == 1
    assert not migrate_catalogue(engine, seed_path).applied
    assert reads == [seed_path]
    with Session(engine) as db:
        assert db.get(Brand, "brand_acme_supply").name_key == "acme supply"


def test_legacy_routes_trips_and_schema_unchanged(engine, seed_path):
    Base.metadata.create_all(engine, tables=[Route.__table__, Trip.__table__])
    with Session(engine) as db:
        route = Route(
            start_address="Original", start_lat=1, start_lng=2,
            end_address="Destination", end_lat=3, end_lng=4, vehicle_type="rmc_truck",
        )
        db.add(route)
        db.flush()
        db.add(Trip(
            route_id=route.id, start_address="Original", end_address="Destination",
            start_lat=1, start_lng=2, end_lat=3, end_lng=4, plant_id="legacy_plant_id",
        ))
        db.commit()
    with engine.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT * FROM {table}")).all()
            for table in ("routes", "trips")
        }
        schema = connection.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE tbl_name IN ('routes', 'trips')"
        )).all()
    migrate_catalogue(engine, seed_path)
    with engine.connect() as connection:
        for table, records in before.items():
            assert connection.execute(text(f"SELECT * FROM {table}")).all() == records
        assert connection.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE tbl_name IN ('routes', 'trips')"
        )).all() == schema


@pytest.mark.parametrize("table,values", [
    ("plants", {"lat": 90.1}),
    ("plants", {"lng": -180.1}),
    ("plants", {"brand_id": "missing"}),
    ("plants", {"region_id": "missing"}),
    ("regions", {"country_code": "nz"}),
    ("regions", {"country_code": "NZL"}),
    ("regions", {"country_code": "12"}),
    ("regions", {"calibration_status": "validated"}),
])
def test_database_constraints(engine, seed_path, table, values):
    migrate_catalogue(engine, seed_path)
    model = Plant if table == "plants" else Region
    with engine.begin() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        with pytest.raises(IntegrityError):
            connection.execute(model.__table__.update().values(**values))


def test_brand_normalized_uniqueness_and_fk_deletion(engine, seed_path):
    migrate_catalogue(engine, seed_path)
    with Session(engine) as db:
        db.add(Brand(id="duplicate", name="  ACME  "))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.delete(db.get(Brand, "brand_acme"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_reject_connection_without_committing_callers_transaction(engine, seed_path):
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(TypeError, match="Engine"):
            migrate_catalogue(connection, seed_path)
        assert transaction.is_active
        transaction.rollback()
    assert inspect(engine).get_table_names() == []


def test_region_defaults_and_independent_mix_lists(engine, seed_path):
    migrate_catalogue(engine, seed_path)
    with Session(engine) as db:
        region = Region(
            id="new_region", name="New region", country_code="IN",
            administrative_area="Telangana", timezone="Asia/Kolkata",
        )
        db.add(region)
        db.flush()
        assert region.calibration_status == "uncalibrated"
        for number in (1, 2):
            db.add(Plant(
                id=f"new_{number}", name="New", address="Address",
                lat=0, lng=0, brand_id="brand_acme", region_id=region.id,
            ))
        db.flush()
        first, second = db.scalars(
            select(Plant).where(Plant.id.in_(["new_1", "new_2"])).order_by(Plant.id)
        ).all()
        assert first.supported_mix_codes == second.supported_mix_codes == ["GP", "HE", "RE"]
        assert first.supported_mix_codes is not second.supported_mix_codes


def test_all_explicit_legacy_regions_and_default_seed_argument(engine, seed_path, monkeypatch):
    slugs = [
        "central_west", "west", "south_east", "south", "central_east", "north",
        "central_south", "east", "north_west", "north_shore", "warangal",
    ]
    rows = [
        {**seed_rows()[0], "id": f"plant_{slug}", "region": slug}
        for slug in slugs
    ]
    seed_path.write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr("app.db.catalogue_migration.DEFAULT_SEED_PATH", seed_path)
    assert migrate_catalogue(engine).regions == 11
    with Session(engine) as db:
        assert set(db.scalars(select(Region.id))) == (
            {f"nz_{slug}" for slug in slugs[:-1]} | {"in_telangana_warangal"}
        )


def test_catalogue_event_json_and_utc_storage(engine, seed_path):
    migrate_catalogue(engine, seed_path)
    with Session(engine) as db:
        audit = CatalogueEvent(
            entity_type="plant", entity_id="legacy_plant_id", action="update",
            data={"before": {"active": True}, "after": {"active": False}},
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)
        assert isinstance(audit.id, int)
        assert audit.data["after"] == {"active": False}
        assert audit.created_at.utcoffset() == timedelta(0)


def test_idempotency_response_commits_and_rolls_back_with_resource(engine, seed_path):
    migrate_catalogue(engine, seed_path)
    with Session(engine) as db:
        brand = Brand(id="brand_created", name="Created supplier")
        response = {"id": brand.id, "name": brand.name, "version": 1}
        db.add_all([
            brand,
            CatalogueIdempotency(
                key="create-1", entity_type="brand", request_hash="abc",
                response_data=response,
            ),
        ])
        db.commit()
        db.expire_all()
        saved = db.get(CatalogueIdempotency, "create-1")
        assert saved.response_data == response
        assert saved.created_at.utcoffset() == timedelta(0)
        db.expunge(saved)
        db.add_all([
            Brand(id="brand_rolled_back", name="Rolled back supplier"),
            CatalogueIdempotency(
                key="create-1", entity_type="brand", request_hash="other",
                response_data={"id": "brand_rolled_back"},
            ),
        ])
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.get(Brand, "brand_rolled_back") is None
        assert db.get(CatalogueIdempotency, "create-1").request_hash == "abc"


def test_unrecognized_ledger_version_is_not_overwritten(engine, seed_path):
    CatalogueMigration.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(CatalogueMigration.__table__.insert().values(version=9))
    with pytest.raises(CatalogueMigrationError, match="Unsupported"):
        migrate_catalogue(engine, seed_path)
    assert inspect(engine).get_table_names() == ["catalogue_migrations"]


def test_ledger_missing_tables_rejected_without_recreating(engine, seed_path):
    migrate_catalogue(engine, seed_path)
    CatalogueEvent.__table__.drop(engine)
    with pytest.raises(CatalogueMigrationError, match="missing tables"):
        migrate_catalogue(engine, seed_path)
    assert "catalogue_events" not in inspect(engine).get_table_names()
