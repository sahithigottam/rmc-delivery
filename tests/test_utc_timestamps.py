"""UTC request, SQLite persistence, and response contract regressions."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api.v1.endpoints import routes, trips
from app.db.database import Base
from app.db.models import Route, Trip, TripEvent
from app.dependencies import get_route_service, get_trip_service
from app.schemas import (
    DispatchRequest,
    RouteCreate,
    TripBeginRequest,
    TripStart,
)
from app.services.trip import TripService
from app.domain.enums import LoadStatus

LOCAL_TIME = "2026-10-11T10:00:00+05:30"
UTC_TIME = datetime(2026, 10, 11, 4, 30, tzinfo=timezone.utc)
ROUTE_INPUT = {"start": {"address": "Plant"}, "end": {"address": "Job site"}}


@pytest.mark.parametrize("model,field,payload", [
    (RouteCreate, "departure_datetime", ROUTE_INPUT),
    (TripStart, "batch_time", {"route_id": 1}),
    (TripBeginRequest, "batch_time", {}),
    (DispatchRequest, "scheduled_at", {"plant_id": "test", "job_site_address": "Site"}),
])
def test_timestamp_input_requires_offset_and_normalizes_utc(model, field, payload):
    for invalid in ["2026-10-11T10:00:00", "2026-10-11", "invalid"]:
        with pytest.raises(ValidationError):
            model.model_validate({**payload, field: invalid})
    parsed = model.model_validate({**payload, field: LOCAL_TIME})
    assert getattr(parsed, field) == UTC_TIME
    assert getattr(parsed, field).utcoffset() == timedelta(0)
    assert parsed.model_dump(mode="json")[field] == "2026-10-11T04:30:00Z"
    negative_offset = model.model_validate({
        **payload, field: "2026-10-10T21:30:00-07:00",
    })
    assert getattr(negative_offset, field) == UTC_TIME


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        route = Route(
            start_address="Plant", start_lat=0, start_lng=0,
            resolved_start_address="Plant",
            end_address="Site", end_lat=0, end_lng=0,
            resolved_end_address="Site", vehicle_type="rmc_truck",
            distance_meters=2000, duration_seconds=600,
        )
        db.add(route)
        db.commit()
        yield db, route
    engine.dispose()


def test_sqlite_storage_is_utc_and_reloaded_values_are_aware(database):
    db, route = database
    local = datetime.fromisoformat(LOCAL_TIME)
    route.departure_datetime = local
    trip = Trip(
        route_id=route.id, status="pending",
        start_address="Plant", end_address="Site",
        start_lat=0, start_lng=0, end_lat=0, end_lng=0,
        scheduled_at=local, batch_time=local, started_at=local,
        load_expiry_time=local + timedelta(minutes=90),
        completed_at=local, estimated_arrival=local,
        last_reroute_at=local, last_traffic_check_at=local,
    )
    db.add(trip)
    db.commit()
    trip_id = trip.id
    db.expire_all()
    for field in [
        "scheduled_at", "batch_time", "started_at", "completed_at",
        "estimated_arrival", "last_reroute_at", "last_traffic_check_at",
    ]:
        assert getattr(trip, field) == UTC_TIME
        assert getattr(trip, field).utcoffset() == timedelta(0)
    assert trip.load_expiry_time == UTC_TIME + timedelta(minutes=90)
    assert route.departure_datetime == UTC_TIME
    assert trip.created_at.tzinfo is not None
    row = db.execute(text(
        "SELECT batch_time, scheduled_at FROM trips WHERE id = :id"
    ), {"id": trip_id}).one()
    assert row.batch_time.startswith("2026-10-11 04:30:00")
    assert row.scheduled_at.startswith("2026-10-11 04:30:00")


def test_existing_naive_sqlite_values_are_read_as_utc_without_rewrite(database):
    db, route = database
    db.execute(text(
        "UPDATE routes SET departure_datetime = '2026-10-11 04:30:00' WHERE id = :id"
    ), {"id": route.id})
    db.commit()
    db.expire_all()
    assert route.departure_datetime == UTC_TIME
    # Legacy values are interpreted as stored; an unknown lost offset is not guessed.
    assert db.execute(text(
        "SELECT departure_datetime FROM routes WHERE id = :id"
    ), {"id": route.id}).scalar_one() == "2026-10-11 04:30:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("begin_pending", [False, True])
async def test_batch_time_survives_start_begin_and_response_round_trip(database, begin_pending):
    db, route = database
    service = TripService(db, Mock())
    batch_utc = datetime.now(timezone.utc) - timedelta(minutes=10)
    batch_local = batch_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    if begin_pending:
        trip = Trip(
            route_id=route.id, status="pending",
            start_address="Plant", end_address="Site",
            start_lat=0, start_lng=0, end_lat=0, end_lng=0,
        )
        db.add(trip)
        db.commit()
        response = await service.begin_trip(
            trip.id, TripBeginRequest(batch_time=batch_local),
        )
    else:
        response = await service.start_trip(TripStart(route_id=route.id, batch_time=batch_local))
    assert response.batch_time == batch_utc
    assert response.load_expiry_time == batch_utc + timedelta(minutes=90)
    db.expire_all()
    reloaded = service._get_trip(response.id)
    assert reloaded.batch_time == batch_utc
    data = service._to_response(reloaded).model_dump(mode="json")
    for field in ["batch_time", "load_expiry_time", "started_at", "created_at", "updated_at"]:
        assert data[field].endswith("Z")
    event = db.query(TripEvent).filter_by(trip_id=response.id, event_type="trip_started").one()
    assert event.data["batch_time"] == batch_utc.isoformat()
    assert data["recent_events"][0]["created_at"].endswith("Z")


@pytest.mark.asyncio
async def test_dispatch_passes_and_persists_utc_time(database, monkeypatch):
    db, route = database
    monkeypatch.setattr("app.services.plant_locator.PlantLocator.get_by_id", lambda self, pid: {
        "id": pid, "name": "Plant", "address": "Plant",
        "active": True, "brand_id": "brand_test", "brand": "Test",
        "region_id": "nz_test", "lat": 0, "lng": 0,
        "country_code": "NZ", "timezone": "Pacific/Auckland",
        "calibration_status": "uncalibrated", "supported_mix_codes": ["GP"],
        "version": 1, "brand_version": 1, "region_version": 1,
    })
    route_service = AsyncMock()
    route_service.estimate_route.return_value = Mock(id=route.id)
    service = TripService(db, Mock())
    response = await service.dispatch_trip(
        DispatchRequest(
            plant_id="test", job_site_address="Site", scheduled_at=LOCAL_TIME,
        ),
        route_service,
    )
    assert route_service.estimate_route.await_args.args[0].departure_datetime == UTC_TIME
    assert service._get_trip(response.trip_id).scheduled_at == UTC_TIME
    assert response.model_dump(mode="json")["scheduled_at"] == "2026-10-11T04:30:00Z"
    assert response.model_dump(mode="json")["created_at"].endswith("Z")


@pytest.mark.asyncio
async def test_api_rejects_naive_times_before_any_service_call():
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.include_router(trips.router, prefix="/api/v1")
    route_service = AsyncMock()
    trip_service = AsyncMock()
    app.dependency_overrides[get_route_service] = lambda: route_service
    app.dependency_overrides[get_trip_service] = lambda: trip_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        for path, field, payload in [
            ("/routes/estimate", "departure_datetime", ROUTE_INPUT),
            ("/trips/start", "batch_time", {"route_id": 1}),
            ("/trips/1/begin", "batch_time", {}),
            ("/trips/dispatch", "scheduled_at", {"plant_id": "test", "job_site_address": "Site"}),
        ]:
            response = await client.post(
                f"/api/v1{path}", json={**payload, field: "2026-10-11T10:00:00"},
            )
            assert response.status_code == 422, (path, response.text)
    route_service.estimate_route.assert_not_awaited()
    trip_service.start_trip.assert_not_awaited()
    trip_service.begin_trip.assert_not_awaited()
    trip_service.dispatch_trip.assert_not_awaited()


def test_optional_batch_and_departure_times_can_still_be_omitted():
    assert TripStart(route_id=1).batch_time is None
    assert TripBeginRequest().batch_time is None
    assert RouteCreate.model_validate(ROUTE_INPUT).departure_datetime is None


@pytest.mark.asyncio
@pytest.mark.parametrize("begin_pending", [False, True])
@pytest.mark.parametrize("grade,base,extension", [
    ("25MPa", 90, 45), ("40MPa", 75, 45), ("25MPa", 90, 0),
])
async def test_retarder_applied_once_after_sqlite_reload(
    database, begin_pending, grade, base, extension,
):
    db, route = database
    batch_time = datetime.now(timezone.utc) - timedelta(minutes=60)
    service = TripService(db, Mock())
    payload = {
        "batch_time": batch_time, "concrete_grade": grade,
        "requires_retarder": bool(extension),
    }
    if begin_pending:
        trip = Trip(
            route_id=route.id, status="pending",
            start_address="Plant", end_address="Site",
            start_lat=0, start_lng=0, end_lat=0, end_lng=0,
        )
        db.add(trip)
        db.commit()
        response = await service.begin_trip(trip.id, TripBeginRequest(**payload))
    else:
        response = await service.start_trip(TripStart(route_id=route.id, **payload))
    assert response.load_max_life_minutes == base
    assert response.retarder_extension_minutes == extension
    assert response.load_expiry_time == batch_time + timedelta(minutes=base + extension)
    assert response.load_minutes_remaining == pytest.approx(base + extension - 60, abs=0.1)
    db.expire_all()
    trip = service._get_trip(response.id)
    timer = service._load_timer(trip)
    assert timer.effective_max_minutes == base + extension
    assert timer.expiry_time == trip.load_expiry_time
    assert timer.effective_warning_minutes == (45 if grade == "40MPa" else 60) + extension
    assert timer.effective_critical_minutes == (60 if grade == "40MPa" else 75) + extension
    assert trip.load_max_life_minutes == base
    # Monitoring must use the same limit and remain callable with a real LoadManager.
    await service._evaluate_load_status(trip, eta_minutes=0)
    db.commit()
    event = db.query(TripEvent).filter_by(
        trip_id=trip.id, event_type="load_check",
    ).one()
    assert event.data["effective_max_minutes"] == base + extension
    assert event.data["expiry_time"] == trip.load_expiry_time.isoformat()
    assert trip.load_status == timer.status.value


@pytest.mark.asyncio
async def test_legacy_retarder_record_does_not_gain_an_extra_extension(database):
    db, route = database
    batch_time = datetime.now(timezone.utc) - timedelta(minutes=140)
    trip = Trip(
        route_id=route.id, status="in_progress",
        start_address="Plant", end_address="Site",
        start_lat=0, start_lng=0, end_lat=0, end_lng=0,
        batch_time=batch_time, load_expiry_time=batch_time + timedelta(minutes=135),
        load_max_life_minutes=135, retarder_added=True,
        retarder_extension_minutes=45, concrete_grade="25MPa",
    )
    db.add(trip)
    db.commit()
    db.expire_all()
    service = TripService(db, Mock())
    response = service._to_response(trip)
    assert response.load_max_life_minutes == 90
    assert response.load_minutes_remaining == pytest.approx(-5, abs=0.1)
    assert service._load_timer(trip).effective_max_minutes == 135
    await service._evaluate_load_status(trip, eta_minutes=0)
    db.commit()
    assert trip.load_status == LoadStatus.EXPIRED.value
    # Compatibility is read-time only; historical storage is not silently rewritten.
    assert trip.load_max_life_minutes == 135


@pytest.mark.asyncio
@pytest.mark.parametrize("begin_pending", [False, True])
@pytest.mark.parametrize("offset_minutes,message", [
    (5, "future"), (-100, "already-expired"),
])
async def test_invalid_batch_time_rejected_before_state_change(
    database, begin_pending, offset_minutes, message,
):
    db, route = database
    service = TripService(db, Mock())
    batch_time = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    if begin_pending:
        trip = Trip(
            route_id=route.id, status="pending",
            start_address="Plant", end_address="Site",
            start_lat=0, start_lng=0, end_lat=0, end_lng=0,
        )
        db.add(trip)
        db.commit()
        with pytest.raises(ValueError, match=message):
            await service.begin_trip(trip.id, TripBeginRequest(batch_time=batch_time))
        assert trip.status == "pending"
        assert trip.batch_time is None
    else:
        with pytest.raises(ValueError, match=message):
            await service.start_trip(TripStart(route_id=route.id, batch_time=batch_time))
        assert db.query(Trip).count() == 0
    assert db.query(TripEvent).count() == 0
