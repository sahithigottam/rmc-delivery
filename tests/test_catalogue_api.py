"""Structured catalogue HTTP and lifecycle integration contract."""
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import catalogue, plants
from app.auth import Principal, get_current_principal
from app.config import settings
from app.db import Base, get_db
from app.db.models import Business, CatalogueEvent, Plant, Route
from app.db.geography import BusinessCountry, City, Country, State
from app.dependencies import get_prediction_service
from app.schemas import DispatchRequest
from app.services.plant_locator import PlantLocator
from app.services.trip import TripService


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(settings, "env", "development")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Business(id="org_Test", name="Test business"), Business(id="org_Other", name="Other business"),
                    Country(code="IN", name="India")])
        db.flush()
        db.add_all([BusinessCountry(organization_id="org_Test", code="IN", name="India"),
                    State(id="test-state", organization_id="org_Test", country_code="IN", name="Telangana")])
        db.flush()
        db.add(City(id="test-city", organization_id="org_Test", state_id="test-state",
                    name="Warangal", timezone="Asia/Kolkata"))
        db.commit()
    yield engine
    plants._analysis_cache.clear()
    engine.dispose()


@pytest_asyncio.fixture
async def client(store):
    app = FastAPI()
    app.include_router(plants.router, prefix="/api/v1")
    app.include_router(catalogue.router, prefix="/api/v1")
    def database():
        with Session(store) as db:
            yield db
    service = AsyncMock()
    service.geocode_job_site.return_value = {"latitude": 18.0, "longitude": 79.5}
    service.predict_delivery.return_value = {
        "traffic": {"google_eta_minutes": 10},
        "prediction": {
            "adjusted_eta_minutes": 15, "remaining_life_minutes": 70,
            "buffer_depletion_rate": 0.2, "delay_constant_used": 1.5,
            "risk_level": "LOW", "success_probability": 0.9,
        }, "recommendation": "Planning estimate",
    }
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="test-super-admin", organization_id="org_Test",
        organization_role="org:admin", is_super_admin=True,
    )
    app.dependency_overrides[get_prediction_service] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as http:
        yield http, service


async def create(http, path, payload, key):
    if path == "brands":
        payload = {"organization_id": "org_Test", **payload}
    response = await http.post(
        f"/api/v1/{path}", json=payload, headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert response.headers["Location"] == f"/api/v1/{path}/{data['id']}"
    assert data["created_at"].endswith("Z")
    return data


async def seed(http):
    brand = await create(http, "brands", {"name": "Test Brand"}, "brand-create")
    region = await create(http, "regions", {
        "name": "Warangal", "city_id": "test-city", "country_code": "IN", "administrative_area": "Telangana",
        "timezone": "Asia/Kolkata",
    }, "region-create")
    payload = {
        "name": "NIT Plant", "brand_id": brand["id"], "region_id": region["id"],
        "address": "NIT Warangal, India",
        "location": {"latitude": 18, "longitude": 79.5},
        "supported_mix_codes": ["GP"],
    }
    plant = await create(http, "plants", payload, "plant-create")
    return brand, region, plant, payload


@pytest.mark.asyncio
async def test_create_list_patch_deactivate_preserve_identity_and_audit(client, store):
    http, _ = client
    brand, region, plant, _ = await seed(http)
    assert plant["country_code"] == "IN"
    assert plant["calibration_status"] == "uncalibrated"
    assert plant["timezone"] == "Asia/Kolkata"
    listed = (await http.get("/api/v1/plants", params={"brand_id": brand["id"], "limit": 1})).json()
    assert listed["total"] == 1
    assert listed["items"][0]["location"] == {"latitude": 18, "longitude": 79.5}
    updated = await http.patch(f"/api/v1/plants/{plant['id']}", json={
        "version": 1, "name": "Renamed", "active": False,
    })
    assert updated.status_code == 200
    assert updated.json()["id"] == plant["id"]
    assert updated.json()["version"] == 2
    assert (await http.get("/api/v1/plants")).json()["total"] == 0
    assert (await http.get("/api/v1/plants", params={"active_only": False})).json()["total"] == 1
    assert (await http.get(f"/api/v1/plants/{plant['id']}")).status_code == 200
    assert (await http.delete(f"/api/v1/plants/{plant['id']}")).status_code == 405
    with Session(store) as db:
        events = db.query(CatalogueEvent).filter_by(entity_id=plant["id"]).all()
        assert len(events) == 2
        assert events[-1].data["before"]["active"] is True
        assert events[-1].data["after"]["active"] is False
        assert PlantLocator(db).get_by_id(plant["id"])["active"] is False


@pytest.mark.asyncio
async def test_idempotent_create_conflicting_key_and_normalized_brand_uniqueness(client, store):
    http, _ = client
    first = await create(http, "brands", {"name": " Holcim "}, "retry-key")
    again = await create(http, "brands", {"name": "Holcim"}, "retry-key")
    assert first == again
    conflict = await http.post("/api/v1/brands", json={"organization_id": "org_Test", "name": "Other"}, headers={"Idempotency-Key": "retry-key"})
    assert conflict.status_code == 409
    duplicate = await http.post("/api/v1/brands", json={"organization_id": "org_Test", "name": "HOLCIM"}, headers={"Idempotency-Key": "different-key"})
    assert duplicate.status_code == 409
    assert (await http.get("/api/v1/brands")).json()["total"] == 1
    with Session(store) as db:
        assert db.query(CatalogueEvent).count() == 1


@pytest.mark.asyncio
async def test_stale_version_conflict_does_not_change_record(client):
    http, _ = client
    _, _, plant, _ = await seed(http)
    path = f"/api/v1/plants/{plant['id']}"
    assert (await http.patch(path, json={"version": 1, "name": "First"})).status_code == 200
    conflict = await http.patch(path, json={"version": 1, "name": "Lost update"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["details"]["current_version"] == 2
    assert (await http.get(path)).json()["name"] == "First"


@pytest.mark.asyncio
async def test_owned_plants_are_company_scoped_and_catalogue_writes_are_super_admin_only(
    client,
):
    http, _ = client
    brand, region, plant, payload = await seed(http)
    second_plant = await create(http, "plants", {
        **payload, "name": "Unassigned Plant",
    }, "second-plant")
    assigned = await http.post(
        "/api/v1/organizations/org_Test/plants",
        json={"plant_id": plant["id"]},
    )
    assert assigned.status_code == 409, assigned.text
    assert {row["plant"]["id"] for row in (await http.get(
        "/api/v1/organizations/org_Test/plants",
    )).json()} == {plant["id"], second_plant["id"]}

    app = http._transport.app
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="company-admin", organization_id="org_Test",
        organization_role="org:member", is_super_admin=False,
    )
    visible = (await http.get("/api/v1/plants")).json()
    assert visible["total"] == 2
    assert {p["id"] for p in visible["items"]} == {plant["id"], second_plant["id"]}
    assert (await http.get(f"/api/v1/plants/{second_plant['id']}")).status_code == 200
    assert (await http.get("/api/v1/plants", params={"organization_id": "org_Other"})).status_code == 403
    assert (
        await http.get("/api/v1/organizations/someone-elses-org/plants")
    ).status_code == 404
    assert (
        await http.post(
            "/api/v1/organizations/someone-elses-org/plants",
            json={"plant_id": second_plant["id"]},
        )
    ).status_code == 403
    denied = await http.patch(f"/api/v1/plants/{plant['id']}", json={
        "version": 1, "name": "Company cannot edit global catalogue",
    })
    assert denied.status_code == 403
    assert brand["id"]
    assert region["id"]


@pytest.mark.asyncio
async def test_platform_owner_cannot_share_or_unassign_owned_plants(client, store):
    http, _ = client
    http._transport.app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="test-super-admin", organization_id=None,
        organization_role=None, is_super_admin=True,
    )
    _, _, plant, _ = await seed(http)
    for company in ("org_Test", "org_Other"):
        response = await http.post(
            f"/api/v1/organizations/{company}/plants",
            json={"plant_id": plant["id"]},
        )
        assert response.status_code == 409, response.text
        response = await http.get(f"/api/v1/organizations/{company}/plants")
        assert response.status_code == 200
        expected = [plant["id"]] if company == "org_Test" else []
        assert [row["plant"]["id"] for row in response.json()] == expected
    response = await http.delete(
        f"/api/v1/organizations/org_Test/plants/{plant['id']}",
    )
    assert response.status_code == 409
    assert (await http.get("/api/v1/organizations/org_Other/plants")).json() == []
    assert len((await http.get("/api/v1/organizations/org_Test/plants")).json()) == 1
    with Session(store) as db:
        events = db.query(CatalogueEvent).filter_by(
            entity_id=plant["id"],
        ).order_by(CatalogueEvent.id).all()
        assert [event.action for event in events] == ["created"]
        assert all(event.actor_user_id == "test-super-admin" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["org:admin", "org:plantadmin", "org:driver"])
async def test_company_roles_cannot_manage_catalogue_or_company_assignments(client, role):
    http, _ = client
    _, _, plant, _ = await seed(http)
    app = http._transport.app
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="company-user", organization_id="business-a",
        organization_role=role, is_super_admin=False,
    )
    for company in ("business-a", "business-b"):
        assert (await http.post(
            f"/api/v1/organizations/{company}/plants",
            json={"plant_id": plant["id"]},
        )).status_code == 403
        assert (await http.delete(
            f"/api/v1/organizations/{company}/plants/{plant['id']}",
        )).status_code == 403
    assert (await http.patch(
        f"/api/v1/plants/{plant['id']}", json={"version": 1, "active": False},
    )).status_code == 403
    assert (await http.post(
        "/api/v1/brands", json={"name": "Forbidden"},
        headers={"Idempotency-Key": "forbidden-brand"},
    )).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"name": "   "}, {"brand_id": "missing"}, {"region_id": "missing"},
    {"location": {"latitude": 91, "longitude": 0}},
    {"location": {"latitude": 0, "longitude": 181}},
    {"supported_mix_codes": []}, {"supported_mix_codes": ["GP", "GP"]},
    {"supported_mix_codes": ["bogus"]}, {"unknown": 1},
])
async def test_plant_validation(client, change):
    http, _ = client
    _, _, _, payload = await seed(http)
    response = await http.post(
        "/api/v1/plants", json={**payload, **change}, headers={"Idempotency-Key": "invalid"},
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"country_code": "XX"}, {"country_code": "in"}, {"timezone": "Mars/City"},
    {"administrative_area": ""}, {"calibration_status": "nz_baseline"},
])
async def test_region_validation_and_no_calibration_claims(client, change):
    http, _ = client
    response = await http.post("/api/v1/regions", json={
        "name": "Test", "city_id": "test-city", "country_code": "IN", "administrative_area": "Telangana",
        "timezone": "Asia/Kolkata", **change,
    }, headers={"Idempotency-Key": "invalid-region"})
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_patch_null_empty_and_missing_idempotency_rejected(client):
    http, _ = client
    _, _, plant, payload = await seed(http)
    for body in [{"version": 1}, {"version": 1, "name": None}, {"version": 1, "active": None}]:
        response = await http.patch(f"/api/v1/plants/{plant['id']}", json=body)
        assert response.status_code == 422
    assert (await http.post("/api/v1/plants", json=payload)).status_code == 422
    assert (await http.get("/api/v1/plants", params={"limit": 101})).status_code == 422
    assert (await http.get("/api/v1/plants", params={"offset": -1})).status_code == 422


@pytest.mark.asyncio
async def test_non_super_admin_catalogue_writes_are_forbidden(client):
    http, _ = client
    _, _, plant, payload = await seed(http)
    app = http._transport.app
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="company-admin", organization_id="org_Test",
        organization_role="org:member", is_super_admin=False,
    )
    for path, body in [
        ("plants", payload), ("brands", {"name": "New"}),
        ("regions", {"name": "Test", "country_code": "IN", "administrative_area": "Test", "timezone": "Asia/Kolkata"}),
    ]:
        assert (await http.post(f"/api/v1/{path}", json=body, headers={"Idempotency-Key": "production"})).status_code == 403
    assert (await http.patch(
        f"/api/v1/plants/{plant['id']}", json={"version": 1, "active": False},
    )).status_code == 403
    assert (await http.get("/api/v1/plants")).status_code == 200


@pytest.mark.asyncio
async def test_analysis_changes_with_catalogue_and_selects_nearest(client):
    http, predictor = client
    brand, region, first, payload = await seed(http)
    farther = await create(http, "plants", {
        **payload, "name": "Far plant", "location": {"latitude": 18.9, "longitude": 79.5},
    }, "farther")
    request = {
        "brand_id": brand["id"], "country_code": "IN",
        "job_site_data": {"display_name": "Job, India"},
        "top_n": 1, "include_llm_analysis": False,
    }
    response = await http.post("/api/v1/plants/analyse", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["best_plant_id"] == first["id"]
    assert predictor.predict_delivery.await_args.kwargs["country_code"] == "IN"
    await http.patch(f"/api/v1/plants/{first['id']}", json={"version": 1, "active": False})
    response = await http.post("/api/v1/plants/analyse", json=request)
    assert response.json()["best_plant_id"] == farther["id"]
    await http.patch(f"/api/v1/regions/{region['id']}", json={
        "version": 1, "name": "Updated Warangal", "city_id": region["city_id"], "country_code": "IN",
        "administrative_area": "Telangana", "timezone": "Asia/Kolkata",
    })
    await http.post("/api/v1/plants/analyse", json=request)
    assert predictor.predict_delivery.await_count == 3


@pytest.mark.asyncio
async def test_dispatch_reads_database_support_and_saves_snapshot(client, store):
    http, _ = client
    _, _, plant, _ = await seed(http)
    with Session(store) as db:
        route = Route(
            start_address="Plant", end_address="Site",
            start_lat=18, start_lng=79.5, end_lat=18.1, end_lng=79.5,
            vehicle_type="rmc_truck", distance_meters=1000, duration_seconds=600,
        )
        db.add(route)
        db.commit()
        router = AsyncMock()
        router.estimate_route.return_value = Mock(id=route.id)
        service = TripService(db, Mock())
        req = DispatchRequest(
            plant_id=plant["id"], job_site_address="Site", scheduled_at="2030-01-01T10:00:00Z",
        )
        response = await service.dispatch_trip(req, router)
        stored = service._get_trip(response.trip_id)
        snapshot = json.loads(stored.prediction_json)["catalogue_snapshot"]
        assert snapshot["id"] == plant["id"]
        assert snapshot["timezone"] == "Asia/Kolkata"
        assert snapshot["version"] == 1
        db.query(Plant).filter_by(id=plant["id"]).update({"active": False, "name": "Changed"})
        db.commit()
        assert json.loads(stored.prediction_json)["catalogue_snapshot"]["name"] == "NIT Plant"
        with pytest.raises(ValueError, match="inactive"):
            await service.dispatch_trip(req, router)
