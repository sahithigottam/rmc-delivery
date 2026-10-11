"""Approved linkage is bounded, atomic, and repeatable."""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.geography import BusinessCountry, City, Country, State
from app.db.models import Brand, Business, CatalogueEvent, Plant, Region
from app.services.catalogue import plant_out
from scripts.link_legacy_auckland_geography import APPROVED_PLANTS, link_approved


@pytest.fixture
def store():
    database = create_engine("sqlite://")
    Base.metadata.create_all(database)
    seed = json.loads((Path(__file__).parents[1] / "config" / "plants.json").read_text())
    with Session(database) as db:
        db.add(Business(id="org_A", name="Business A"))
        db.add(Country(code="NZ", name="New Zealand"))
        db.flush()
        db.add(BusinessCountry(organization_id="org_A", code="NZ", name="New Zealand"))
        db.add(Brand(id="brand", organization_id="org_A", name="Seed Brand"))
        for region_id in [*APPROVED_PLANTS, "nz_south"]:
            db.add(Region(
                id=region_id, name=region_id, organization_id="org_A",
                country_code="NZ", administrative_area="Auckland", timezone="Pacific/Auckland",
            ))
        db.flush()
        for item in seed:
            if item["region"] == "warangal":
                continue
            db.add(Plant(
                id=item["id"], name=item["name"], address=item["address"],
                organization_id="org_A", brand_id="brand", region_id=f"nz_{item['region']}",
                lat=item["lat"], lng=item["lng"], active=item["active"],
            ))
        db.commit()
    yield database
    database.dispose()


def test_links_only_approved_subset_and_retry_is_noop(store):
    assert link_approved(store, "org_A") == {
        "states_created": 1, "cities_created": 1, "regions_linked": 9, "plants_covered": 15,
    }
    with Session(store) as db:
        assert db.scalar(select(func.count()).select_from(CatalogueEvent)) == 11
        assert db.get(Region, "nz_south").city_id is None
        city = db.scalar(select(City))
        assert city.name == "Auckland" and city.organization_id == "org_A"
        for region_id, plant_ids in APPROVED_PLANTS.items():
            assert db.get(Region, region_id).version == 2
            for plant_id in plant_ids:
                plant = db.get(Plant, plant_id)
                output = plant_out(plant)
                assert output.city_id == city.id
                assert output.state_id == city.state_id
                assert plant.version == 1
    assert link_approved(store, "org_A")["regions_linked"] == 0
    with Session(store) as db:
        assert db.scalar(select(func.count()).select_from(CatalogueEvent)) == 11


@pytest.mark.parametrize("change", ["foreign_owner", "changed_address", "existing_link"])
def test_conflicts_leave_no_partial_changes(store, change):
    with Session(store) as db:
        if change == "foreign_owner":
            db.add(Business(id="org_B", name="Business B"))
            db.flush()
            db.get(Plant, "consult_hub_takapuna").organization_id = "org_B"
        elif change == "changed_address":
            db.get(Plant, "consult_hub_takapuna").address = "Unknown location"
        else:
            state = State(organization_id="org_A", country_code="NZ", name="Different state")
            db.add(state)
            db.flush()
            city = City(
                organization_id="org_A", state_id=state.id,
                name="Different city", timezone="Pacific/Auckland",
            )
            db.add(city)
            db.flush()
            db.get(Region, "nz_north_shore").city_id = city.id
        db.commit()
    with pytest.raises(ValueError):
        link_approved(store, "org_A")
    with Session(store) as db:
        assert db.get(Region, "nz_central_west").city_id is None
        assert db.get(Region, "nz_central_west").version == 1
        assert db.scalar(select(State).where(State.name == "Auckland")) is None
        assert db.scalar(select(func.count()).select_from(CatalogueEvent)) == 0
