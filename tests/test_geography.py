"""Geography catalogue API and migration tests using isolated SQLite."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints.geography import router
from app.auth import Principal, get_current_principal
from app.db.database import Base, get_db
from app.db.geography import City, Country, State
from app.db.geography_migration import GEOGRAPHY_TABLES, migrate_geography


@pytest.fixture
def store():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    migrate_geography(engine)
    Base.metadata.create_all(engine)
    from app.db.models import Business
    with Session(engine) as db:
        db.add(Business(id="org_A", name="Business A"))
        db.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def database():
        with Session(store) as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="owner", organization_id=None, organization_role=None, is_super_admin=True,
    )
    return TestClient(app), app


def create(client, path, payload):
    if path in ("countries", "states"):
        payload = {"organization_id": "org_A", **payload}
    response = client.post(f"/api/v1/{path}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_migration_creates_only_geography_tables_and_is_idempotent(store):
    isolated = create_engine("sqlite://")
    migrate_geography(isolated)
    expected = {table.name for table in GEOGRAPHY_TABLES} | {"businesses"}
    assert set(inspect(isolated).get_table_names()) == expected
    assert "regions" not in inspect(isolated).get_table_names()
    isolated.dispose()
    with store.begin() as connection:
        connection.execute(text("INSERT INTO countries (code, name) VALUES ('NZ', 'New Zealand')"))
    migrate_geography(store)
    with Session(store) as db:
        assert db.get(Country, "NZ").name == "New Zealand"


def test_delete_unused_hierarchy_and_retain_audit(client, store):
    from app.db.models import CatalogueEvent

    http, _ = client
    create(http, "countries", {"code": "IN", "name": "India"})
    state = create(http, "states", {"country_code": "IN", "name": "Telangana"})
    city = create(http, "cities", {
        "state_id": state["id"], "name": "Warangal", "timezone": "Asia/Kolkata",
    })
    assert http.delete("/api/v1/countries/IN?organization_id=org_A").status_code == 409
    assert http.delete(f"/api/v1/states/{state['id']}").status_code == 409
    assert http.delete(f"/api/v1/cities/{city['id']}").status_code == 204
    assert http.delete(f"/api/v1/states/{state['id']}").status_code == 204
    assert http.delete("/api/v1/countries/IN?organization_id=org_A").status_code == 204
    assert http.delete("/api/v1/countries/IN?organization_id=org_A").status_code == 404
    with Session(store) as db:
        events = db.query(CatalogueEvent).filter_by(action="deleted").all()
        assert len(events) == 3
        assert all(event.actor_user_id == "owner" and "before" in event.data for event in events)


def test_company_role_cannot_delete_geography(client):
    http, app = client
    create(http, "countries", {"code": "IN", "name": "India"})
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        "member", "org_A", "org:admin", False,
    )
    assert http.delete("/api/v1/countries/IN?organization_id=org_A").status_code == 403


def test_region_and_saved_site_references_block_deletion(client, store):
    from app.api.v1.endpoints.catalogue import router as catalogue_router
    from app.db.models import Brand, JobSite, Plant, Region

    http, app = client
    app.include_router(catalogue_router, prefix="/api/v1")
    create(http, "countries", {"code": "IN", "name": "India"})
    state = create(http, "states", {"country_code": "IN", "name": "Telangana"})
    city = create(http, "cities", {
        "state_id": state["id"], "name": "Warangal", "timezone": "Asia/Kolkata",
    })
    with Session(store) as db:
        db.add(Brand(id="legacy-brand", name="Legacy"))
        db.add(Region(
            id="region-test", name="Area", city_id=city["id"], country_code="IN",
            administrative_area="Telangana", timezone="Asia/Kolkata",
        ))
        db.flush()
        db.add(Plant(
            id="plant-test", name="Plant", brand_id="legacy-brand",
            region_id="region-test", address="Address", lat=18, lng=79, active=False,
        ))
        db.commit()
    assert http.delete(f"/api/v1/cities/{city['id']}").status_code == 409
    assert http.delete("/api/v1/regions/region-test").status_code == 409
    with Session(store) as db:
        db.delete(db.get(Plant, "plant-test"))
        db.commit()
    assert http.delete("/api/v1/regions/region-test").status_code == 204
    assert http.delete(f"/api/v1/cities/{city['id']}").status_code == 204
    assert http.delete(f"/api/v1/states/{state['id']}").status_code == 204
    with Session(store) as db:
        db.add(JobSite(
            id="site-test", organization_id="org_A", name="Site", address="Address",
            country_code="IN", created_by_user_id="owner", updated_by_user_id="owner",
        ))
        db.commit()
    assert http.delete("/api/v1/countries/IN?organization_id=org_A").status_code == 409


def test_hierarchy_create_retrieve_filter_and_pagination(client):
    http, _ = client
    country = create(http, "countries", {"code": "IN", "name": "India"})
    state = create(http, "states", {"country_code": "IN", "name": "Telangana"})
    city = create(http, "cities", {
        "country_code": "IN", "state_id": state["id"],
        "name": "Warangal", "timezone": "Asia/Kolkata",
    })
    assert country["code"] == "IN"
    assert len(state["id"]) == 36
    assert len(city["id"]) == 36
    assert http.get("/api/v1/countries/IN?organization_id=org_A").json() == country
    assert http.get(f"/api/v1/states/{state['id']}").json() == state
    assert http.get(f"/api/v1/cities/{city['id']}").json() == city

    states = http.get("/api/v1/states", params={"country_code": "IN", "limit": 1})
    assert states.status_code == 200
    assert states.json() == {"items": [state], "total": 1, "limit": 1, "offset": 0}
    cities = http.get("/api/v1/cities", params={"country_code": "IN", "state_id": state["id"]})
    assert cities.json()["items"] == [city]
    assert cities.json()["total"] == 1
    assert http.get("/api/v1/countries", params={"limit": 101}).status_code == 422


def test_businesses_have_independent_private_geography(client, store):
    from app.api.v1.endpoints.catalogue import router as catalogue_router
    from app.db.models import Business

    http, app = client
    app.include_router(catalogue_router, prefix="/api/v1")
    with Session(store) as db:
        db.add(Business(id="org_B", name="Business B"))
        db.commit()
    data = {}
    for owner in ("org_A", "org_B"):
        create(http, "countries", {"organization_id": owner, "code": "IN", "name": "India"})
        state = create(http, "states", {
            "organization_id": owner, "country_code": "IN", "name": "Telangana",
        })
        city = create(http, "cities", {
            "state_id": state["id"], "name": "Warangal", "timezone": "Asia/Kolkata",
        })
        response = http.post("/api/v1/regions", json={
            "city_id": city["id"], "name": "Area",
        }, headers={"Idempotency-Key": owner})
        assert response.status_code == 201, response.text
        data[owner] = (state, city, response.json())
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        "member", "org_A", "org:admin", False,
    )
    for path in ("countries", "states", "cities", "regions"):
        response = http.get(f"/api/v1/{path}")
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["organization_id"] == "org_A"
        assert http.get(f"/api/v1/{path}?organization_id=org_B").status_code == 403
    assert http.get("/api/v1/countries/IN").json()["organization_id"] == "org_A"
    assert http.get(f"/api/v1/cities/{data['org_B'][1]['id']}").status_code == 403
    assert http.get(f"/api/v1/regions/{data['org_B'][2]['id']}").status_code == 403


@pytest.mark.parametrize("country_code", ["XX", "in", "USA"])
def test_country_requires_assigned_iso_alpha2_code(client, country_code):
    http, _ = client
    response = http.post(
        "/api/v1/countries", json={"code": country_code, "name": "Invalid"},
    )
    assert response.status_code == 422


def test_timezone_must_be_iana_and_parent_references_must_exist(client):
    http, _ = client
    assert http.post("/api/v1/states", json={
        "organization_id": "org_A", "country_code": "IN", "name": "Missing parent",
    }).status_code == 404
    assert http.post("/api/v1/cities", json={
        "state_id": "missing", "name": "No state", "timezone": "Asia/Kolkata",
    }).status_code == 404

    create(http, "countries", {"code": "IN", "name": "India"})
    state = create(http, "states", {"country_code": "IN", "name": "Telangana"})
    invalid_timezone = http.post("/api/v1/cities", json={
        "state_id": state["id"], "name": "Warangal", "timezone": "Not/A_Timezone",
    })
    assert invalid_timezone.status_code == 422


def test_city_country_assertion_must_match_state_parent(client):
    http, _ = client
    create(http, "countries", {"code": "IN", "name": "India"})
    create(http, "countries", {"code": "NZ", "name": "New Zealand"})
    state = create(http, "states", {"country_code": "IN", "name": "Telangana"})
    response = http.post("/api/v1/cities", json={
        "country_code": "NZ", "state_id": state["id"],
        "name": "Warangal", "timezone": "Asia/Kolkata",
    })
    assert response.status_code == 422
    assert "does not match state" in response.json()["detail"]


def test_duplicate_keys_return_conflict_without_duplicate_records(client, store):
    http, _ = client
    create(http, "countries", {"code": "IN", "name": "India"})
    assert http.post("/api/v1/countries", json={
        "organization_id": "org_A", "code": "IN", "name": "Republic of India",
    }).status_code == 409
    create(http, "states", {"country_code": "IN", "name": "Telangana"})
    assert http.post("/api/v1/states", json={
        "organization_id": "org_A", "country_code": "IN", "name": "telangana",
    }).status_code == 409
    with Session(store) as db:
        state = db.query(State).filter_by(country_code="IN").one()
    create(http, "cities", {
        "state_id": state.id, "name": "Warangal", "timezone": "Asia/Kolkata",
    })
    assert http.post("/api/v1/cities", json={
        "state_id": state.id, "name": "WARANGAL", "timezone": "Asia/Kolkata",
    }).status_code == 409
    with Session(store) as db:
        assert db.query(Country).count() == 1
        assert db.query(State).count() == 1
        assert db.query(City).count() == 1


def test_reads_require_authentication_and_create_requires_platform_owner(client):
    http, app = client
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="company-user", organization_id="org-a",
        organization_role="org:plantadmin", is_super_admin=False,
    )
    assert http.get("/api/v1/countries").status_code == 200
    assert http.post("/api/v1/countries", json={
        "code": "IN", "name": "India",
    }).status_code == 403

    app.dependency_overrides.pop(get_current_principal)
    assert http.get("/api/v1/countries").status_code == 401
