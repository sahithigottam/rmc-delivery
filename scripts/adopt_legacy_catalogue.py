"""Explicit operator-approved adoption; never run automatically at startup."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import engine
from app.db.models import Brand, Business, CatalogueEvent, OrganizationPlant, Plant, brand_name_key
from app.db.models import Region
from app.db.geography import BusinessCountry, City, Country, State
from app.db.business_migration import migrate_business_schema


def adopt(organization_id: str) -> tuple[int, int]:
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        with Session(bind=connection) as db:
            if db.get(Business, organization_id) is None:
                raise ValueError("Target business is not registered")
            brands = db.scalars(select(Brand).where(Brand.organization_id.is_(None))).unique().all()
            plants = db.scalars(select(Plant).where(Plant.organization_id.is_(None))).unique().all()
            keys = {
                row.name_key for row in db.scalars(select(Brand).where(
                    Brand.organization_id == organization_id,
                )).unique()
            }
            for brand in brands:
                key = brand_name_key(brand.name, organization_id)
                if key in keys:
                    raise ValueError(f"Conflicting brand name: {brand.name}; review before adoption")
                keys.add(key)
            for plant in plants:
                if plant.brand.organization_id not in (None, organization_id):
                    raise ValueError(f"Plant {plant.id} has a brand owned by another business")
                conflict = db.query(OrganizationPlant).filter(
                    OrganizationPlant.plant_id == plant.id,
                    OrganizationPlant.organization_id != organization_id,
                ).first()
                if conflict is not None:
                    raise ValueError(f"Plant {plant.id} has conflicting legacy assignments")
            for kind, records in (("brand", brands), ("plant", plants)):
                for record in records:
                    previous_version = record.version
                    record.organization_id = organization_id
                    record.version += 1
                    db.add(CatalogueEvent(
                        entity_type=kind, entity_id=record.id, action="ownership_assigned",
                        organization_id=organization_id, actor_user_id=None,
                        data={
                            "before": {"organization_id": None, "version": previous_version},
                            "after": {"organization_id": organization_id, "version": record.version},
                            "source": "explicit_operator_legacy_adoption",
                            "geography_preserved_requires_review": kind == "plant",
                        },
                    ))
            db.flush()
            return len(brands), len(plants)


def adopt_geography(organization_id: str) -> dict[str, int]:
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        with Session(bind=connection) as db:
            if db.get(Business, organization_id) is None:
                raise ValueError("Target business is not registered")
            states = db.scalars(select(State).where(State.organization_id.is_(None))).unique().all()
            cities = db.scalars(select(City).where(City.organization_id.is_(None))).unique().all()
            regions = db.scalars(select(Region).where(Region.organization_id.is_(None))).unique().all()
            for city in cities:
                if city.state.organization_id not in (None, organization_id):
                    raise ValueError("A legacy city has a parent owned by another business")
            for region in regions:
                if region.city is not None and region.city.organization_id not in (None, organization_id):
                    raise ValueError("A legacy region has a city owned by another business")
                if db.query(Plant).filter(
                    Plant.region_id == region.id, Plant.organization_id.is_not(None),
                    Plant.organization_id != organization_id,
                ).first() is not None:
                    raise ValueError("A legacy region is used by another business's plant")
            countries = {country.code: country.name for country in db.scalars(select(Country))}
            needed = {state.country_code for state in states} | {region.country_code for region in regions}
            known_names = {"IN": "India", "NZ": "New Zealand"}
            for code in needed - countries.keys():
                if code not in known_names:
                    raise ValueError(f"Country {code} needs an explicit country record before adoption")
                countries[code] = known_names[code]
                db.add(Country(code=code, name=countries[code]))
            db.flush()
            count = 0
            for code, name in countries.items():
                if db.get(BusinessCountry, (organization_id, code)) is None:
                    db.add(BusinessCountry(organization_id=organization_id, code=code, name=name))
                    db.add(CatalogueEvent(
                        entity_type="country", entity_id=code, action="ownership_assigned",
                        organization_id=organization_id,
                        data={"source": "explicit_operator_geography_adoption"},
                    ))
                    count += 1
            for kind, records in (("state", states), ("city", cities), ("region", regions)):
                for record in records:
                    record.organization_id = organization_id
                    if kind == "region":
                        record.version += 1
                    db.add(CatalogueEvent(
                        entity_type=kind, entity_id=record.id, action="ownership_assigned",
                        organization_id=organization_id,
                        data={"source": "explicit_operator_geography_adoption",
                              "city_links_preserved": True},
                    ))
            db.flush()
            return {"countries": count, "states": len(states), "cities": len(cities), "regions": len(regions)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--backup-directory", type=Path, required=True)
    parser.add_argument("--include-geography", action="store_true")
    args = parser.parse_args()
    if engine.dialect.name != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        raise ValueError("This operator command requires a file-backed SQLite database")
    source_path = Path(engine.url.database).resolve()
    if not source_path.is_file():
        raise ValueError("Database file does not exist")
    args.backup_directory.mkdir(parents=True, exist_ok=True)
    backup = args.backup_directory / f"before-legacy-adoption-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.sqlite"
    with sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True) as source:
        with sqlite3.connect(backup) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed; adoption was not executed")
    if args.include_geography:
        migrate_business_schema(engine)
        BusinessCountry.__table__.create(engine, checkfirst=True)
        counts = adopt_geography(args.organization_id)
        print(f"Adopted private geography: {counts}")
    brands, plants = adopt(args.organization_id)
    print(f"Adopted {brands} brands and {plants} plants. Backup: {backup}")


if __name__ == "__main__":
    main()
