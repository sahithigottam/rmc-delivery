"""Explicitly link the approved Auckland subset; never run at startup."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.database import engine
from app.db.geography import BusinessCountry, City, State
from app.db.models import Business, CatalogueEvent, Plant, Region


APPROVED_PLANTS = {
    "nz_central_west": {"holcim_avondale"},
    "nz_west": {"holcim_ranui", "liquidstone_swanson", "grc_henderson"},
    "nz_south_east": {"holcim_east_tamaki", "ocean_east_tamaki", "aeon_east_tamaki"},
    "nz_central_east": {"allied_mt_wellington", "atlas_mt_wellington"},
    "nz_north": {"allied_silverdale"},
    "nz_central_south": {"firth_penrose", "cemix_onehunga"},
    "nz_east": {"akl_landscape_st_johns"},
    "nz_north_west": {"citi_whenuapai"},
    "nz_north_shore": {"consult_hub_takapuna"},
}


def link_approved(database: Engine, organization_id: str) -> dict[str, int]:
    if database.dialect.name != "sqlite":
        raise ValueError("This operator command requires SQLite")
    with database.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        with Session(bind=connection) as db:
            if db.get(Business, organization_id) is None:
                raise ValueError("Target business is not registered")
            if db.get(BusinessCountry, (organization_id, "NZ")) is None:
                raise ValueError("Target business must already have its NZ country entry")
            regions = []
            for region_id, expected_plants in APPROVED_PLANTS.items():
                region = db.get(Region, region_id)
                if region is None or region.organization_id != organization_id:
                    raise ValueError(f"Region {region_id} is missing or belongs to another business")
                if (region.country_code, region.administrative_area, region.timezone) != (
                    "NZ", "Auckland", "Pacific/Auckland",
                ):
                    raise ValueError(f"Region {region_id} no longer matches the approved mapping")
                plants = db.scalars(select(Plant).where(Plant.region_id == region_id)).unique().all()
                if {plant.id for plant in plants} != expected_plants or any(
                    plant.organization_id != organization_id or
                    plant.brand.organization_id != organization_id or
                    "auckland" not in plant.address.casefold()
                    for plant in plants
                ):
                    raise ValueError(f"Region {region_id} plant data changed; review before linking")
                regions.append(region)
            state = db.scalar(select(State).where(
                State.organization_id == organization_id,
                State.country_code == "NZ",
                State.name.ilike("Auckland"),
            ))
            created_states = int(state is None)
            if state is None:
                state = State(organization_id=organization_id, country_code="NZ", name="Auckland")
                db.add(state)
                db.flush()
                db.add(CatalogueEvent(
                    entity_type="state", entity_id=state.id, action="created",
                    organization_id=organization_id, actor_user_id=None,
                    data={"source": "explicit_operator_approved_auckland_linkage",
                          "after": {"name": state.name, "country_code": "NZ"}},
                ))
            city = db.scalar(select(City).where(City.state_id == state.id, City.name.ilike("Auckland")))
            created_cities = int(city is None)
            if city is None:
                city = City(
                    organization_id=organization_id, state_id=state.id,
                    name="Auckland", timezone="Pacific/Auckland",
                )
                db.add(city)
                db.flush()
                db.add(CatalogueEvent(
                    entity_type="city", entity_id=city.id, action="created",
                    organization_id=organization_id, actor_user_id=None,
                    data={"source": "explicit_operator_approved_auckland_linkage",
                          "after": {"name": city.name, "state_id": state.id, "timezone": city.timezone}},
                ))
            if city.organization_id != organization_id or city.timezone != "Pacific/Auckland":
                raise ValueError("Existing Auckland city conflicts with approved ownership/timezone")
            linked = 0
            for region in regions:
                if region.city_id == city.id:
                    continue
                if region.city_id is not None:
                    raise ValueError(f"Region {region.id} already has a different city; review required")
                before = {"city_id": None, "version": region.version}
                region.city_id = city.id
                region.version += 1
                db.add(CatalogueEvent(
                    entity_type="region", entity_id=region.id, action="updated",
                    organization_id=organization_id, actor_user_id=None,
                    data={"source": "explicit_operator_approved_auckland_linkage",
                          "before": before,
                          "after": {"city_id": city.id, "version": region.version}},
                ))
                linked += 1
            db.flush()
            return {"states_created": created_states, "cities_created": created_cities,
                    "regions_linked": linked, "plants_covered": sum(map(len, APPROVED_PLANTS.values()))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--backup-directory", type=Path, required=True)
    args = parser.parse_args()
    if engine.dialect.name != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        raise ValueError("This operator command requires a file-backed SQLite database")
    source_path = Path(engine.url.database).resolve()
    if not source_path.is_file():
        raise ValueError("Database file does not exist")
    args.backup_directory.mkdir(parents=True, exist_ok=True)
    backup = args.backup_directory / f"before-auckland-linkage-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.sqlite"
    with sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True) as source:
        with sqlite3.connect(backup) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed; linkage was not executed")
    print(f"Linked approved geography: {link_approved(engine, args.organization_id)}. Backup: {backup}")


if __name__ == "__main__":
    main()
